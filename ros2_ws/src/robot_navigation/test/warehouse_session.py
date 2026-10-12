"""Corrected W3 session infrastructure; no CLI/test entry starts robotics.

Importing this file or constructing message fixtures does not initialise ROS.
The replacement warehouse_qualification driver performs runtime ownership,
preflight, immutable claims and mission/runner cleanup only after separate approval.
The historical W3 script is immutable and must not be rerun.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

from geometry_msgs.msg import PoseWithCovarianceStamped
from lifecycle_msgs.srv import GetState
from nav_msgs.msg import OccupancyGrid, Odometry
from navigation_system import NavigationSession
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from rclpy.serialization import serialize_message
from rclpy.time import Time
from robotops_interfaces.msg import ContactEvidence
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Imu, LaserScan
from tf2_msgs.msg import TFMessage

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from warehouse_qualification.geometry import scan_check  # noqa: E402
from warehouse_qualification.journal import (  # noqa: E402
    BufferedJournal,
    critical_event,
    save_summary,
    shutdown_summary,
)
from warehouse_qualification.localisation import LocalisationReadiness  # noqa: E402
from warehouse_qualification.observer import QualificationObserver  # noqa: E402


def stamp(message) -> int:
    return message.header.stamp.sec * 10**9 + message.header.stamp.nanosec


def receipt(info) -> dict:
    """DDS timestamps may be unavailable; zero never proves low latency."""
    return {
        "middleware_received_wall_ns": getattr(info, "received_timestamp", 0) or None,
        "middleware_source_wall_ns": getattr(info, "source_timestamp", 0) or None,
        "publisher_gid": bytes(getattr(info, "publisher_gid", b"")).hex(),
    }


class WarehouseQualificationSession(NavigationSession):
    def __init__(self, directory: Path, map_file: Path, profile: str):
        super().__init__(directory, map_file, profile)
        plugin = ET.parse(ROOT / "ros2_ws/src/robot_simulation/urdf/gazebo.urdf.xacro").find(
            './/plugin[@name="robot_simulation::ContactEvidence"]'
        )
        self.journal = BufferedJournal(directory / "observations.jsonl")
        self.observer = QualificationObserver(
            self.journal,
            expected_bodies=[e.text for e in plugin.findall("body")],
            expected_support_pairs=[
                e.text + "|" + plugin.findtext("floor") for e in plugin.findall("support_body")
            ],
        )
        self.attached = False
        self.closed = False
        self.last_clock_record = None
        self.log_offsets = {}
        self.failed_children = []
        self.stop_verified = False
        self.sampled_topics = set()
        self.readiness_established = False
        self.consumer_stamps = {}
        self.last_scan_stamp = None
        self.last_scan_change_mono = None
        self.localisation = LocalisationReadiness()
        self.last_readiness = None
        self.last_readiness_signature = None

    def safe_callback(self, function):
        def receive(message, info):
            try:
                function(message, info)
            except Exception as exc:
                # Keep the executor available for bounded cleanup; the next
                # supervision boundary raises the sticky observation failure.
                self.observer.fail(f"Observation callback failed: {type(exc).__name__}: {exc}")

        return receive

    def record_message(self, topic, message, info, kind="ros_message"):
        if topic == "/scan" and stamp(message) != self.last_scan_stamp:
            self.last_scan_stamp = stamp(message)
            self.last_scan_change_mono = time.monotonic_ns()
        from mapping_system import yaw

        mono = time.monotonic_ns()
        if topic == "/odom":
            if message.header.frame_id != "odom" or message.child_frame_id != "base_link":
                self.localisation.fault = "motion.odom.frames"
            p, v = message.pose.pose, message.twist.twist
            q = p.orientation
            if (
                not all(math.isfinite(v) for v in (q.x, q.y, q.z, q.w))
                or abs(sum(v * v for v in (q.x, q.y, q.z, q.w)) - 1) > 0.01
            ):
                self.localisation.fault = "motion.odom.quaternion"
            self.localisation.observe(
                "odom",
                stamp(message),
                mono,
                p.position.x,
                p.position.y,
                yaw(p.orientation),
                v.linear.x,
                v.angular.z,
            )
        elif topic == "/simulation/ground_truth":
            matches = [t for t in message.transforms if t.child_frame_id == "robotops"]
            if len(matches) != 1 or matches[0].header.frame_id != "warehouse_v1":
                self.localisation.fault = "motion.truth.identity"
            else:
                t = matches[0]
                p = t.transform
                q = p.rotation
                if (
                    not all(math.isfinite(v) for v in (q.x, q.y, q.z, q.w))
                    or abs(sum(v * v for v in (q.x, q.y, q.z, q.w)) - 1) > 0.01
                ):
                    self.localisation.fault = "motion.truth.quaternion"
                self.localisation.observe(
                    "truth", stamp(t), mono, p.translation.x, p.translation.y, yaw(p.rotation)
                )
        payload = serialize_message(message)
        if len(payload) > 128 * 1024:
            self.journal.reject(f"Oversized CDR observation: {topic}")
            return False
        return self.journal.submit(
            kind,
            topic=topic,
            receipt_ros_ns=self.node.get_clock().now().nanoseconds,
            receipt_monotonic_ns=time.monotonic_ns(),
            callback_wall_ns=time.time_ns(),
            cdr_sha256=hashlib.sha256(payload).hexdigest(),
            cdr_base64=base64.b64encode(payload).decode("ascii"),
            **receipt(info),
        )

    def attach(self):
        def tf(message, info, static=False):
            ros = self.node.get_clock().now().nanoseconds
            mono, wall = time.monotonic_ns(), time.time_ns()
            if len(message.transforms) > 64:
                self.journal.reject("Oversized TF edge array")
                return
            if not self.record_message("/tf_static" if static else "/tf", message, info):
                return
            timing = receipt(info)
            for transform in message.transforms:
                self.observer.tf(
                    transform.header.frame_id,
                    transform.child_frame_id,
                    stamp(transform),
                    receipt_ros_ns=ros,
                    receipt_monotonic_ns=mono,
                    callback_wall_ns=wall,
                    middleware_received_wall_ns=timing["middleware_received_wall_ns"],
                    static=static,
                )

        def clock(message, info):
            now = message.clock.sec * 10**9 + message.clock.nanosec
            if self.observer.last_clock is not None and now < self.observer.last_clock:
                self.journal.submit(
                    "clock_regression",
                    previous_ros_ns=self.observer.last_clock,
                    observed_ros_ns=now,
                    receipt_monotonic_ns=time.monotonic_ns(),
                    allowed_regression_ns=0,
                )
            self.observer.clock(now, time.monotonic_ns())
            if (
                self.last_clock_record is None
                or now < self.last_clock_record
                or now - self.last_clock_record >= 100_000_000
            ):
                self.record_message("/clock", message, info, "sampled_clock")
                self.last_clock_record = now

        def contact(message, info):
            if (
                max(
                    len(message.contacts),
                    len(message.monitored_bodies),
                    len(message.support_pairs),
                )
                > 64
            ):
                self.journal.reject("Oversized contact inventory")
                return
            if not self.record_message("/validation/contacts", message, info, "contact_wire"):
                return
            frame = {
                key: getattr(message, key)
                for key in (
                    "source_id",
                    "sequence",
                    "start_ns",
                    "end_ns",
                    "physics_steps",
                    "coverage_complete",
                )
            }
            frame.update(
                monitored_bodies=list(message.monitored_bodies),
                support_pairs=list(message.support_pairs),
                contacts=[
                    {
                        "body_a": p.body_a,
                        "body_b": p.body_b,
                        "first_ns": p.first_ns,
                        "last_ns": p.last_ns,
                    }
                    for p in message.contacts
                ],
            )
            self.observer.contact(frame, time.monotonic_ns())

        def once(topic, message, info):
            if topic not in self.sampled_topics:
                self.record_message(topic, message, info)
                self.sampled_topics.add(topic)

        durable = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        definitions = [
            (
                PoseWithCovarianceStamped,
                "/amcl_pose",
                lambda m, i: self.record_message("/amcl_pose", m, i),
                durable,
            ),
            (
                TFMessage,
                "/simulation/ground_truth",
                lambda m, i: self.record_message("/simulation/ground_truth", m, i),
                10,
            ),
            (
                Imu,
                "/imu/data",
                lambda m, i: self.record_message("/imu/data", m, i),
                qos_profile_sensor_data,
            ),
            *[
                (OccupancyGrid, t, lambda m, i, topic=t: once(topic, m, i), durable)
                for t in ("/map", "/global_costmap/costmap", "/local_costmap/costmap")
            ],
            (TFMessage, "/tf", tf, QoSProfile(depth=100)),
            (TFMessage, "/tf_static", lambda m, i: tf(m, i, True), durable),
            (Clock, "/clock", clock, qos_profile_sensor_data),
            (ContactEvidence, "/validation/contacts", contact, 100),
            (
                LaserScan,
                "/scan",
                lambda m, i: self.record_message("/scan", m, i),
                qos_profile_sensor_data,
            ),
            (
                Odometry,
                "/odom",
                lambda m, i: self.record_message("/odom", m, i),
                qos_profile_sensor_data,
            ),
        ]
        self.subscriptions.extend(
            self.node.create_subscription(kind, topic, self.safe_callback(callback), qos)
            for kind, topic, callback, qos in definitions
        )
        self.attached = True

    def start(self, label, command):
        if label == "base":
            assert "world:=mapping_lab" in command
            command = ["world:=warehouse_v1" if a == "world:=mapping_lab" else a for a in command]
            command.append("diagnostics:=false")
            from warehouse_scenario import validate_support_floor

            validate_support_floor(
                (ROOT / "ros2_ws/src/robot_simulation/worlds/warehouse_v1.sdf").read_bytes(),
                (ROOT / "ros2_ws/src/robot_simulation/urdf/gazebo.urdf.xacro").read_bytes(),
            )
            # Base Session created its ROS node/subscriptions but has not started
            # any owned launch yet: contact supervision covers startup too.
            self.attach()
            if hasattr(self, "runtime_lock_fd"):
                import rclpy

                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    rclpy.spin_once(self.node, timeout_sec=0.05)
                    self.observer.check()
                nodes = self.node.get_node_names()
                self.journal.submit("prelaunch_graph", nodes=nodes, domain_id=self.domain_id)
                if nodes != [self.node.get_name()]:
                    raise RuntimeError("Conflicting ROS graph before base startup")
        self.journal.submit(
            "process_start_requested",
            label=label,
            command=command,
            domain_id=self.domain_id,
            gazebo_partition=self.partition,
        )
        self.observer.check()
        if not hasattr(self, "runtime_lock_fd"):
            super().start(label, command)
        else:
            # Same launch/environment contract, with the canonical inherited lock
            # FD retained by every owned parent if this supervisor dies.
            path = self.directory / f"{self.workflow}-{label}.log"
            stream = path.open("x")
            self.logs.append((path, stream))
            env = dict(
                os.environ,
                GZ_PARTITION=self.partition,
                ROS_DOMAIN_ID=str(self.domain_id),
                LIBGL_ALWAYS_SOFTWARE="1",
                __EGL_VENDOR_LIBRARY_FILENAMES="/dev/null",
            )
            self.processes.append(
                subprocess.Popen(
                    command,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    env=env,
                    start_new_session=True,
                    pass_fds=(self.runtime_lock_fd,),
                )
            )
        self.journal.submit("process_started", label=label, pid=self.processes[-1].pid)

    def pipeline_command(self):
        return super().pipeline_command() + ["sensor_filter_debug:=true"]

    def capture_logs(self):
        pattern = (
            r"\[(controller_server|planner_server)-\d+\].*MessageFilter \[target=([^\]]+)\]: "
            r"(Added message|Message ready) in frame (\S+) at time ([0-9.]+)"
        )
        for path, _ in self.logs:
            with path.open("rb") as stream:
                stream.seek(self.log_offsets.get(path, 0))
                # Bound each pass; backlog is explicit and must drain before a gate.
                chunk = stream.read(64 * 1024)
            end = chunk.rfind(b"\n") + 1
            if end == 0 and len(chunk) == 64 * 1024:
                self.observer.fail("Oversized or unterminated owned log line")
            self.log_offsets[path] = self.log_offsets.get(path, 0) + end
            for line in chunk[:end].decode(errors="replace").splitlines():
                match = re.search(pattern, line)
                if match:
                    server, target, event, frame, timestamp = match.groups()
                    if event == "Message ready" and (server, target.strip()) in (
                        ("controller_server", "odom"),
                        ("planner_server", "map"),
                    ):
                        values = self.consumer_stamps.setdefault(server, set())
                        if len(values) < 64:
                            values.add(int(Decimal(timestamp) * 10**9))
                    self.journal.submit(
                        "consumer_filter",
                        server=server,
                        target_frame=target.strip(),
                        event=event,
                        frame=frame,
                        stamp_ns=int(Decimal(timestamp) * 10**9),
                    )
                if "process has died" in line:
                    self.failed_children.append(line)
                if "process has died" in line or "process has finished cleanly" in line:
                    self.journal.submit("child_process_exit_log", log_name=path.name, line=line)

    def consumer_receipts_ready(self):
        self.capture_logs()
        drained = all(
            self.log_offsets.get(path, 0) == path.stat().st_size for path, _ in self.logs
        )
        return drained and all(
            len(self.consumer_stamps.get(server, set())) >= 5
            for server in ("controller_server", "planner_server")
        )

    def wait(self, predicate, reason, timeout=60.0):
        def supervised():
            self.capture_logs()
            if self.readiness_established:
                self.require_readiness()
            else:
                self.observer.check(time.monotonic_ns())
            if self.failed_children:
                raise RuntimeError("Owned child process exited unexpectedly")
            return predicate()

        return super().wait(supervised, reason, timeout)

    def spin_for(self, seconds, hold_teleop=False):
        remaining = seconds
        while remaining > 0:
            super().spin_for(min(0.1, remaining), hold_teleop)
            if self.readiness_established:
                self.require_readiness()
            else:
                self.observer.check(time.monotonic_ns())
            remaining -= min(0.1, remaining)

    def validate_sensors(self):
        self.wait(
            lambda: len(self.scan) >= 5 and len(self.imu) >= 10 and self.truth_pose(),
            "Missing warehouse sensor/truth observations",
            90,
        )
        self.wait(
            lambda: self.buffer.can_transform("base_link", "lidar_link", Time()),
            "Missing sensor TF",
        )
        truth = self.truth_pose()
        from mapping_system import yaw

        heading = yaw(truth.rotation)
        lidar = self.buffer.lookup_transform("base_link", "lidar_link", Time()).transform
        x = (
            truth.translation.x
            + math.cos(heading) * lidar.translation.x
            - math.sin(heading) * lidar.translation.y
        )
        y = (
            truth.translation.y
            + math.sin(heading) * lidar.translation.x
            + math.cos(heading) * lidar.translation.y
        )
        descriptor = json.loads(
            (ROOT / "ros2_ws/src/robot_simulation/config/warehouse_v1.json").read_text()
        )
        scan = self.scan[-1]
        assert scan.header.frame_id == "lidar_link" and len(scan.ranges) == 360
        result, okay = scan_check(
            scan.ranges,
            scan.angle_min,
            scan.angle_increment,
            scan.range_max,
            x,
            y,
            heading + yaw(lidar.rotation),
            descriptor["boxes"],
        )
        self.journal.submit("warehouse_lidar_geometry", **result)
        assert okay, "Warehouse geometry alignment failed"
        assert self.scan[-1].header.stamp != self.scan[0].header.stamp
        assert self.node.count_publishers("/scan") == 1
        assert self.node.count_publishers("/imu/data") == 1
        a = self.imu[-1].linear_acceleration
        assert 8.5 < math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z) < 11

    def pose_inputs(self):
        if not self.poses:
            return None, [], False
        pose = self.poses[-1]
        p, q = pose.pose.pose.position, pose.pose.pose.orientation

        def safe(v):
            return v if math.isfinite(v) else str(v)

        self.last_pose_geometry = dict(
            frame=pose.header.frame_id,
            position=[safe(v) for v in (p.x, p.y, p.z)],
            quaternion=[safe(v) for v in (q.x, q.y, q.z, q.w)],
            quaternion_norm_squared=safe(sum(v * v for v in (q.x, q.y, q.z, q.w))),
            required_frame="map",
            quaternion_norm_squared_tolerance=0.01,
        )
        valid = (
            pose.header.frame_id == "map"
            and all(math.isfinite(v) for v in (p.x, p.y, p.z, q.x, q.y, q.z, q.w))
            and abs(sum(v * v for v in (q.x, q.y, q.z, q.w)) - 1) <= 0.01
        )
        return stamp(pose), [pose.pose.covariance[i] for i in (0, 7, 35)], valid

    def require_readiness(self):
        if not self.readiness():
            critical_event(self.journal, "readiness_failure", assessment=self.last_readiness)
            raise RuntimeError("Established readiness lost: " + json.dumps(self.last_readiness))

    def readiness(self):
        node_now, mono = self.node.get_clock().now().nanoseconds, time.monotonic_ns()
        now = max(node_now, self.observer.last_clock or 0)
        try:
            self.observer.check()
        except Exception as error:
            # Independent lifecycle persistence still reports a main-writer fault.
            critical_event(
                self.journal,
                "readiness_failure",
                now_ros_ns=now,
                now_monotonic_ns=mono,
                error=str(error),
                observer_faults=self.observer.faults,
                evidence_status=self.journal.status(),
                observed_clock_ns=self.observer.last_clock,
                node_clock_ns=node_now,
                clock_receipt_ns=self.observer.clock_receipt_ns,
                clock_receipt_limit_ns=1_000_000_000,
                contact_receipt_ns=self.observer.last_contact_receipt_ns,
                contact_limit_ns=250_000_000,
            )
            raise
        transform = None
        if self.buffer.can_transform("map", "base_link", Time()):
            transform = self.buffer.lookup_transform("map", "base_link", Time())
        tf = self.observer.assess_tf(node_now, mono, stamp(transform) if transform else None)
        contact = self.observer.ready(mono)
        scan_age = (
            None if self.last_scan_change_mono is None else mono - self.last_scan_change_mono
        )
        local = None
        if self.localisation.initial_stamp is not None:
            local = self.localisation.assess(now, mono, *self.pose_inputs())
        causes = []
        if not tf["ready"]:
            causes.append("tf.readiness")
        if not contact:
            causes.append("contact.coverage_or_silence")
        if local is not None:
            causes.extend(local["causes"])
            if scan_age is None or not 0 <= scan_age <= 3_000_000_000:
                causes.append("sensor.scan_stamp_not_advancing")
        result = dict(
            ready=not causes,
            causes=causes,
            now_ros_ns=now,
            now_monotonic_ns=mono,
            tf=tf,
            localisation=local,
            pose_geometry=getattr(self, "last_pose_geometry", None),
            scan_stamp_ns=self.last_scan_stamp,
            scan_change_age_ns=scan_age,
            scan_change_limit_ns=3_000_000_000,
            contact_ready=contact,
            contact_receipt_ns=self.observer.last_contact_receipt_ns,
            contact_age_ns=None
            if self.observer.last_contact_receipt_ns is None
            else mono - self.observer.last_contact_receipt_ns,
            contact_limit_ns=250_000_000,
        )
        self.last_readiness = result
        signature = (tuple(causes), local["mode"] if local else None)
        # Emit transitions only; every failed call retains its exact measurements.
        if signature != self.last_readiness_signature or (causes and self.readiness_established):
            self.journal.submit("readiness_assessment", **result)
            self.last_readiness_signature = signature
        return result["ready"]

    def active(self, name):
        client = self.node.create_client(GetState, f"/{name}/get_state")
        try:
            self.wait(client.service_is_ready, f"No lifecycle service {name}", 45)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                future = client.call_async(GetState.Request())
                self.wait(future.done, f"No lifecycle reply {name}", 5)
                state = future.result().current_state.id
                self.journal.submit("lifecycle_observed", node=name, state_id=state)
                if state == 3:
                    return
            raise RuntimeError(f"Lifecycle {name} never activated")
        finally:
            self.node.destroy_client(client)

    def initialize(self):
        # No blocking wait_for_service/server during startup: every spin boundary
        # checks sticky contact/observation failures before proceeding.
        self.validate_sensors()
        self.active("amcl")
        self.active("map_server")
        self.wait(lambda: self.initial_pose.get_subscription_count() > 0, "No AMCL subscriber")
        pose = PoseWithCovarianceStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self.node.get_clock().now().to_msg()
        pose.pose.pose.orientation.w = 1.0
        pose.pose.covariance[0] = pose.pose.covariance[7] = pose.pose.covariance[35] = 0.05
        self.initial_pose.publish(pose)
        self.wait(
            lambda: self.poses and self.buffer.can_transform("map", "base_link", Time()),
            "No localisation",
        )

        def stationary_history():
            status = self.localisation.motion_status(
                self.node.get_clock().now().nanoseconds, time.monotonic_ns()
            )
            return status["ready"] and all(v["stationary"] for v in status["streams"].values())

        self.wait(stationary_history, "Initial stationary motion history unavailable", 5)
        self.localisation.arm(
            self.node.get_clock().now().nanoseconds, time.monotonic_ns(), *self.pose_inputs()
        )
        for name in ("controller_server", "planner_server", "behavior_server", "bt_navigator"):
            self.active(name)
        self.wait(self.navigator.server_is_ready, "No navigation action server", 10)
        self.wait(self.planner.server_is_ready, "No planner action server", 10)
        self.wait(self.readiness, "Warehouse TF/contact readiness never qualified", 15)
        self.readiness_established = True

    def __enter__(self):
        try:
            return super().__enter__()
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, exc_type, exc, tb):
        if self.closed:
            return
        self.closed = True
        exception = str(exc) if exc_type else None
        cleanup = False
        try:
            if (
                hasattr(self, "node")
                and self.processes
                and all(p.poll() is None for p in self.processes)
            ):
                try:
                    # Continue stop observation despite a sticky journal/contact
                    # failure; do not disable the failure or robot command guard.
                    self._stop_assessment()
                except Exception as stop_error:
                    critical_event(self.journal, "robot_stop_unverified", error=str(stop_error))
            if hasattr(self, "node"):
                self._terminate_owned()
            cleanup = True
        except BaseException as cleanup_error:
            exception = (
                f"{exception or ''}; cleanup: {type(cleanup_error).__name__}: {cleanup_error}"
            )
            raise
        finally:
            # Inspect every remaining owned log line for child failures, even
            # when an earlier assertion caused parent __exit__ to skip checks.
            for path, _ in self.logs:
                for line in path.read_text(errors="replace").splitlines():
                    if "process has died" in line and line not in self.failed_children:
                        self.failed_children.append(line)
            critical_event(
                self.journal,
                "cleanup_observed",
                completed=cleanup,
                exits=[p.poll() for p in self.processes],
                failed_children=self.failed_children,
            )
            critical_event(
                self.journal,
                "observer_terminal_status",
                faults=self.observer.faults,
                derived_tf=self.observer.assessment_status(),
            )
            status = self.journal.close(close_lifecycle=False)
            critical_event(self.journal, "observation_journal_closed", status=status)
            lifecycle = self.journal.lifecycle.close()
            summary = shutdown_summary(
                exception=exception,
                cleanup_completed=cleanup,
                exits=[p.poll() for p in self.processes],
                failed_children=self.failed_children,
                robot_stop_verified=self.stop_verified,
                journal=status,
            )
            # This is cleanup infrastructure, not the mission/result authority.
            summary["critical_lifecycle"] = lifecycle
            summary["derived_tf_assessments"] = self.observer.assessment_status()
            summary["observer_and_cleanup_complete"] &= lifecycle["complete"]
            summary["original_mission_result"] = "NOT_ASSESSED_BY_OBSERVER"
            summary["observer_faults"] = self.observer.faults
            summary["observer_and_cleanup_complete"] = (
                summary["observer_and_cleanup_complete"] and not self.observer.faults
            )
            save_summary(self.directory / "observer-shutdown.json", summary)
            if exc_type is None and (
                not summary["observer_and_cleanup_complete"] or self.observer.faults
            ):
                raise RuntimeError("Qualification observer or cleanup incomplete; inspect summary")

    def _terminate_owned(self):
        import rclpy

        failures = []
        for process in reversed(self.processes):
            try:
                if process.poll() is None:
                    critical_event(
                        self.journal,
                        "process_shutdown_requested",
                        pid=process.pid,
                        signal="SIGINT",
                    )
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    critical_event(self.journal, "process_forced_shutdown", pid=process.pid)
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            except BaseException as error:
                failures.append(f"{process.pid}: {error}")
        for cleanup in (
            lambda: self.listener.unregister(),
            lambda: self.node.destroy_node(),
            rclpy.shutdown,
        ):
            try:
                cleanup()
            except BaseException as error:
                failures.append(str(error))
        for _, stream in self.logs:
            stream.close()
        if failures:
            raise RuntimeError(f"Owned teardown incomplete: {failures}")

    def _stop_assessment(self):
        # Use the same existing stop limits, while bypassing only observer.check
        # so an evidence failure does not prevent bounded cleanup observations.
        NavigationSession.spin_for(self, 1.5)
        assert self.odometry
        assert all(
            abs(m.twist.twist.linear.x) < 0.025 and abs(m.twist.twist.angular.z) < 0.04
            for m in list(self.odometry)[-5:]
        )
        start = self.truth_pose().translation
        NavigationSession.spin_for(self, 0.5)
        end = self.truth_pose().translation
        assert math.hypot(end.x - start.x, end.y - start.y) < 0.03
        self.stop_verified = True
        critical_event(self.journal, "robot_stop_verified")
