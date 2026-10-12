"""Owned probe-only observation/teardown instrumentation; no guard mutation."""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from decimal import Decimal
from pathlib import Path

from diagnostic_msgs.msg import DiagnosticArray
from nav_msgs.msg import Odometry
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from rclpy.serialization import serialize_message
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import LaserScan

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "robot_navigation/test"))
from navigation_system import NavigationSession  # noqa: E402
from probe_evidence import EvidenceJournal, diagnostic_level  # noqa: E402


def stamp(message) -> int:
    return message.header.stamp.sec * 10**9 + message.header.stamp.nanosec


class ObservedNavigationSession(NavigationSession):
    def __init__(self, directory, map_file, profile, journal: EvidenceJournal):
        self.journal = journal
        self.offsets = {}
        self.last_clock = None
        self.clock_observations = []
        self.child_failure_lines = []
        super().__init__(directory, map_file, profile)

    def pipeline_command(self):
        # Only logging is enabled; sensor topic/default route remains unchanged.
        return super().pipeline_command() + ["sensor_filter_debug:=true"]

    def start(self, label, command):
        self.journal.record(
            "process_start_requested",
            label=label,
            command=command,
            domain_id=self.domain_id,
            gazebo_partition=self.partition,
        )
        super().start(label, command)
        self.journal.record("process_started", label=label, pid=self.processes[-1].pid)

    def record_message(self, topic, message, kind="ros_message", **fields):
        cdr = serialize_message(message)
        receipt_ros_ns = self.node.get_clock().now().nanoseconds
        self.journal.record(
            kind,
            topic=topic,
            receipt_ros_ns=receipt_ros_ns,
            cdr_sha256=hashlib.sha256(cdr).hexdigest(),
            cdr_base64=base64.b64encode(cdr).decode("ascii"),
            **fields,
        )
        return receipt_ros_ns

    def __enter__(self):
        try:
            super().__enter__()

            def clock(message):
                now = message.clock.sec * 10**9 + message.clock.nanosec
                if (
                    self.last_clock is None
                    or now < self.last_clock
                    or now - self.last_clock >= 100_000_000
                ):
                    self.record_message(
                        "/clock", message, "clock", ros_ns=now, sampling="100ms_or_regression"
                    )
                    self.clock_observations.append(now)
                    self.last_clock = now

            self.subscriptions.extend(
                [
                    self.node.create_subscription(
                        LaserScan,
                        "/scan",
                        lambda m: self.record_message("/scan", m, "raw_scan", stamp_ns=stamp(m)),
                        qos_profile_sensor_data,
                    ),
                    self.node.create_subscription(Clock, "/clock", clock, qos_profile_sensor_data),
                    self.node.create_subscription(
                        Odometry,
                        "/odom",
                        lambda m: self.record_message("/odom", m, "odometry", stamp_ns=stamp(m)),
                        qos_profile_sensor_data,
                    ),
                ]
            )
            from geometry_msgs.msg import PoseWithCovarianceStamped

            self.subscriptions.append(
                self.node.create_subscription(
                    PoseWithCovarianceStamped,
                    "/amcl_pose",
                    lambda m: self.record_message(
                        "/amcl_pose", m, "localization", stamp_ns=stamp(m)
                    ),
                    QoSProfile(depth=5, durability=DurabilityPolicy.TRANSIENT_LOCAL),
                )
            )
            return self
        except BaseException:
            if hasattr(self, "node"):
                self.__exit__(*sys.exc_info())
            raise

    def capture_logs(self):
        pattern = (
            r"\[(controller_server|planner_server)-\d+\].*MessageFilter \[target=([^\]]+)\]: "
            r"(Added message|Message ready) in frame (\S+) at time ([0-9.]+)"
        )
        for path, _ in self.logs:
            if not path.exists():
                continue
            with path.open("rb") as stream:
                stream.seek(self.offsets.get(path, 0))
                while line := stream.readline():
                    if not line.endswith(b"\n"):
                        break
                    self.offsets[path] = stream.tell()
                    text = line.decode(errors="replace").rstrip()
                    match = re.search(pattern, text)
                    if match:
                        server, target, event, frame, t = match.groups()
                        self.journal.record(
                            "consumer_filter",
                            server=server,
                            target_frame=target.strip(),
                            event=event,
                            frame=frame,
                            stamp_ns=int(Decimal(t) * 10**9),
                            line=text,
                        )
                    if "process has finished cleanly" in text or "process has died" in text:
                        if "process has died" in text:
                            self.child_failure_lines.append(text)
                        self.journal.record(
                            "child_process_exit_log", log_name=path.name, line=text
                        )

    def wait(self, predicate, reason, timeout=60.0):
        def observed():
            self.capture_logs()
            return predicate()

        try:
            return super().wait(observed, reason, timeout)
        finally:
            self.capture_logs()

    def active(self, name):
        self.journal.record("lifecycle_check_requested", node=name)
        try:
            super().active(name)
        except BaseException as exc:
            self.journal.record("lifecycle_check_failed", node=name, error=str(exc))
            raise
        self.journal.record("lifecycle_active", node=name, state_id=3)

    def spin_for(self, seconds, hold_teleop=False):
        remaining = seconds
        while remaining > 0:
            step = min(0.2, remaining)
            super().spin_for(step, hold_teleop)
            self.capture_logs()
            remaining -= step

    def __exit__(self, exc_type, exc, tb):
        self.journal.record(
            "teardown_requested",
            exception_type=exc_type.__name__ if exc_type else None,
            exception=str(exc) if exc else None,
        )
        cleanup_completed = False
        try:
            result = super().__exit__(exc_type, exc, tb)
            cleanup_completed = True
            return result
        finally:
            self.capture_logs()
            for process, (path, _) in zip(self.processes, self.logs, strict=True):
                self.journal.record(
                    "owned_process_termination",
                    pid=process.pid,
                    log_name=path.name,
                    returncode=process.poll(),
                    still_running=process.poll() is None,
                )
            self.journal.record(
                "teardown_finished",
                all_owned_parents_exited_zero=all(p.poll() == 0 for p in self.processes),
                failed_child_exit_lines=self.child_failure_lines,
                cleanup_sequence_completed=cleanup_completed,
                clean_shutdown_verified=(
                    cleanup_completed
                    and all(p.poll() == 0 for p in self.processes)
                    and not self.child_failure_lines
                ),
            )

    def diagnostics(self, rows, topic, message: DiagnosticArray):
        # Persist exact CDR BEFORE conversion; malformed values remain investigable.
        self.record_message(topic, message, "diagnostic_wire", stamp_ns=stamp(message))
        row = {
            "stamp_ns": stamp(message),
            "receipt_ros_ns": self.node.get_clock().now().nanoseconds,
            "status": [
                {
                    "name": s.name,
                    "hardware_id": s.hardware_id,
                    "level": diagnostic_level(s.level),
                    "message": s.message,
                    "values": {v.key: v.value for v in s.values},
                }
                for s in message.status
            ],
        }
        self.journal.record("diagnostic", **row)
        rows.append(row)
