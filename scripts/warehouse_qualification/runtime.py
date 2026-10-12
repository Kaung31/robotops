"""Concrete normal-route W3 adapter; lazy ROS imports, no execution entry point."""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .driver import ATTEMPT_SET, GUARD, identity, sha, validate_contract, verify_history
from .evidence import verify_evidence
from .geometry import flatten
from .journal import critical_event, critical_status, save_summary


def robotics_processes(proc: Path = Path("/proc")) -> list[dict]:
    """Inspect executables/argv, not substring matches inside shell scripts."""
    names = {
        "controller_server",
        "planner_server",
        "bt_navigator",
        "behavior_server",
        "amcl",
        "map_server",
        "mission_server",
        "robot_state_publisher",
        "ros2_control_node",
        "component_container_isolated",
        "scan_relay",
        "scan_fault_relay",
        "parameter_bridge",
        "velocity_mux",
        "command_guard",
        "static_transform_publisher",
        "gzserver",
        "gzclient",
        "fault_injector",
        "gazebo_runner",
    }
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            args = entry.joinpath("cmdline").read_bytes().decode().strip("\0").split("\0")
        except (FileNotFoundError, ProcessLookupError):
            continue
        if not args or not args[0]:
            continue
        base = Path(args[0]).name
        script = Path(args[1]).name if len(args) > 1 else ""
        match = base in names or script in names
        match |= base.startswith(("gz-sim", "ruby")) and any("gz-sim" in a for a in args)
        match |= (base in {"gz", "ign"} or script in {"gz", "ign"}) and "sim" in args[1:3]
        match |= (base == "ros2" or script == "ros2") and any(
            a in {"launch", "bag"} for a in args[1:4]
        )
        match |= (base == "experiment" or script == "experiment") and "run" in args[1:4]
        if match:
            found.append({"pid": int(entry.name), "argv": args})
    return found


def installed_inventory(root: Path) -> dict:
    """Offline ament lookup/hash only; no ROS node initialization or subprocess."""
    from ament_index_python.packages import get_package_prefix, get_package_share_directory

    result = {}
    for source in sorted((root / "ros2_ws/src").iterdir()):
        if not (source / "package.xml").is_file():
            continue
        prefix = Path(get_package_prefix(source.name))
        share = Path(get_package_share_directory(source.name))
        # Compare every installed source/config/launch asset to its original.
        for item in source.rglob("*"):
            if (
                not item.is_file()
                or "__pycache__" in item.parts
                or "test" in item.relative_to(source).parts
            ):
                continue
            relative = item.relative_to(source)
            candidates = [share / relative]
            if relative.parts[0] == source.name:
                candidates += list(prefix.glob(f"lib/python*/site-packages/{relative}"))
            if (
                relative.parts[0] in {"config", "launch", "worlds", "urdf", "meshes"}
                or relative.parts[0] == source.name
                or str(relative) == "package.xml"
            ):
                if not any(candidate.is_file() for candidate in candidates):
                    raise RuntimeError(f"Required installed asset missing: {item}")
            for candidate in candidates:
                if candidate.is_file():
                    if sha(candidate) != sha(item):
                        raise RuntimeError(f"Installed source differs: {item}")
                    result[str(candidate)] = sha(candidate)
        # Bind installed binaries/plugins and all installed package assets too.
        for directory in (share, prefix / "lib"):
            for item in directory.rglob("*"):
                if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc":
                    result[str(item)] = sha(item)
    return result


def stop_runner(child, journal, *, killpg=os.killpg, pump=None, clock=time.monotonic) -> bool:
    """Runner receives its existing SIGINT cancellation contract before forced stop."""
    if child is None:
        return True
    forced = False
    observation_error = None
    try:
        if child.poll() is None:
            critical_event(
                journal, "runner_cancellation_requested", pid=child.pid, signal="SIGINT"
            )
            child.send_signal(signal.SIGINT)
            try:
                if pump is None:
                    child.wait(timeout=35)
                else:
                    deadline = clock() + 35
                    while child.poll() is None:
                        try:
                            pump()
                        except BaseException as error:
                            observation_error = str(error)
                        if clock() >= deadline:
                            raise subprocess.TimeoutExpired("qualification runner", 35)
                        try:
                            child.wait(timeout=0.1)
                        except subprocess.TimeoutExpired:
                            pass
            except subprocess.TimeoutExpired:
                forced = True
                critical_event(journal, "runner_forced_shutdown", pid=child.pid)
                killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=5)
        return not forced and observation_error is None and child.poll() == 0
    finally:
        critical_event(
            journal,
            "runner_exit",
            pid=child.pid,
            returncode=child.poll(),
            forced=forced,
            cancellation_observation_error=observation_error,
        )


class QualificationRuntime:
    def __init__(self, root: Path, profile: str, plan_path: Path, permission_path: Path):
        self.root, self.profile = root.resolve(), profile
        self.plan_path, self.permission_path = plan_path, permission_path
        self.plan = {**json.loads(plan_path.read_text()), "plan_sha256": sha(plan_path)}
        self.directory = self.root / "artifacts" / ATTEMPT_SET / profile
        self.session = self.runner = self.runner_log = None
        self.manifest_path = None
        self.manifest_hash = None
        self.manifest = None
        self.lock_fd = None

    def preflight(self) -> dict:
        permission = json.loads(self.permission_path.read_text())
        if (
            permission.get("execution_approved") is not True
            or permission.get("plan_sha256") != self.plan["plan_sha256"]
            or permission.get("attempt_set") != ATTEMPT_SET
            or permission.get("profiles") != ["navfn_rpp", "smac_dwb"]
            or not permission.get("owner_approval_reference")
        ):
            raise RuntimeError("NEW explicit hash-bound owner execution approval required")
        validate_contract(self.plan)
        verify_history(self.root, self.plan)
        if identity(self.root / GUARD) != self.plan["guard"]:
            raise RuntimeError("Guard changed")
        for path, digest in self.plan["files"].items():
            if sha(self.root / path) != digest:
                raise RuntimeError(f"Source changed after review: {path}")
        from robotops_backend.benchmarks.warehouse import validate_matrix

        validate_matrix(self.root, self.root / "benchmarks/warehouse_v1/matrix.json")
        self.matrix = json.loads((self.root / "benchmarks/warehouse_v1/matrix.json").read_text())
        self.descriptor = json.loads(
            (self.root / self.matrix["scenario"]["descriptor"]["path"]).read_text()
        )
        installed = installed_inventory(self.root)
        if not self.plan.get("installed") or installed != self.plan["installed"]:
            raise RuntimeError("Installed build identity differs or is unreviewed")
        processes = robotics_processes()
        if processes:
            raise RuntimeError(f"Conflicting robotics processes: {processes}")
        if not os.environ.get("ROS_DOMAIN_ID", "").isdecimal():
            raise RuntimeError("Explicit isolated ROS_DOMAIN_ID required")
        if self.directory.exists():
            raise FileExistsError("Fresh profile evidence directory required")
        return {
            "source_install_map_profile_floor_verified": True,
            "processes": processes,
            "guard": self.plan["guard"],
        }

    def open(self, lock_fd: int) -> None:
        # All ROS dependencies remain inside this separately gated runtime path.
        sys.path.insert(0, str(self.root / "ros2_ws/src/robot_navigation/test"))
        from warehouse_session import WarehouseQualificationSession

        self.lock_fd = lock_fd
        self.session = WarehouseQualificationSession(
            self.directory, self.root / self.matrix["scenario"]["map_yaml"]["path"], self.profile
        )
        self.session.runtime_lock_fd = lock_fd
        self.session.__enter__()
        self.session.initialize()

    def params(self, node, names):
        from rcl_interfaces.srv import GetParameters
        from rclpy.parameter import parameter_value_to_python

        s = self.session
        client = s.node.create_client(GetParameters, f"/{node}/get_parameters")
        try:
            s.wait(client.service_is_ready, f"Missing parameter service {node}", 10)
            future = client.call_async(GetParameters.Request(names=names))
            s.wait(future.done, f"Missing parameters {node}", 10)
            return dict(
                zip(
                    names,
                    [parameter_value_to_python(v) for v in future.result().values],
                    strict=True,
                )
            )
        finally:
            s.node.destroy_client(client)

    def graph(self) -> dict:
        s = self.session
        nodes = s.node.get_node_names()
        scan_publishers = s.node.get_publishers_info_by_topic("/scan")
        subscribers = {e.node_name for e in s.node.get_subscriptions_info_by_topic("/scan")}
        graph = {
            "nodes": nodes,
            "scan_publishers": [e.node_name for e in scan_publishers],
            "scan_subscribers": sorted(subscribers),
        }
        s.journal.submit("route_graph", **graph)
        if (
            len(scan_publishers) != 1
            or not {"amcl", "local_costmap", "global_costmap"} <= subscribers
            or s.node.get_publishers_info_by_topic("/fault_probe/scan")
            or s.node.get_publishers_info_by_topic("/scan_raw")
            or any("relay" in n or "fault" in n for n in nodes)
        ):
            raise RuntimeError("Ordinary sensor routing not verified")
        return graph

    def gates(self) -> dict:
        from ament_index_python.packages import get_package_share_directory
        from mapping_system import yaw
        from rclpy.time import Time
        from robot_navigation.navigation_config import navigation_parameters

        s = self.session
        s.validate_tf_publishers()
        self.graph()
        share = Path(get_package_share_directory("robot_navigation"))
        expected = navigation_parameters(
            share / "config",
            self.profile,
            Path(get_package_share_directory("robot_description")) / "config/geometry.yaml",
            True,
        )
        for node, values in expected.items():
            name = node
            if node in ("local_costmap", "global_costmap"):
                values, name = values[node], f"{node}/{node}"
            configured = flatten(values["ros__parameters"])
            actual = self.params(name, list(configured))
            s.journal.submit(
                "effective_parameters", node=name, configured=configured, observed=actual
            )
            if actual != configured:
                raise RuntimeError(f"Live parameters differ: {name}")
        if (
            Path(self.params("map_server", ["yaml_filename"])["yaml_filename"]).resolve()
            != s.map_file.resolve()
        ):
            raise RuntimeError("Live map file differs")
        s.wait(lambda: bool(s.maps), "No map")
        message, spec = s.maps[-1], self.descriptor["map"]
        width, height = spec["width"], spec["height"]
        image = (
            (self.root / self.matrix["scenario"]["map_image"]["path"])
            .read_bytes()
            .split(b"\n", 3)[3]
        )
        raster = [
            100 if image[(height - 1 - y) * width + x] == 0 else 0
            for y in range(height)
            for x in range(width)
        ]
        if (
            (message.info.width, message.info.height) != (width, height)
            or abs(message.info.resolution - spec["resolution_m"]) > 1e-7
            or abs(message.info.origin.position.x - spec["origin_m"][0]) > 1e-7
            or abs(message.info.origin.position.y - spec["origin_m"][1]) > 1e-7
            or abs(message.info.origin.position.z) > 1e-7
            or abs(message.info.origin.orientation.x) > 1e-7
            or abs(message.info.origin.orientation.y) > 1e-7
            or abs(message.info.origin.orientation.z) > 1e-7
            or abs(message.info.origin.orientation.w - 1) > 1e-7
            or message.header.frame_id != "map"
            or list(message.data) != raster
        ):
            raise RuntimeError("Live occupancy map differs")
        s.journal.submit("map_raster_verified", cells=len(raster))
        s.wait(
            lambda: s.consumer_receipts_ready()
            and {"/local_costmap/costmap", "/global_costmap/costmap"} <= s.sampled_topics,
            "Missing actual costmap scan receipts",
            20,
        )
        tf = s.buffer.lookup_transform("map", "base_link", Time())
        pose = s.poses[-1]
        now = s.node.get_clock().now().nanoseconds
        age = (now - (pose.header.stamp.sec * 10**9 + pose.header.stamp.nanosec)) / 1e9
        cov = [pose.pose.covariance[i] for i in (0, 7, 35)]
        x, y, heading = (
            tf.transform.translation.x,
            tf.transform.translation.y,
            yaw(tf.transform.rotation),
        )
        truth = s.truth_pose()
        s.journal.submit(
            "measured_start",
            x=x,
            y=y,
            yaw=heading,
            localization_age_s=age,
            covariance=cov,
            truth_x=truth.translation.x,
            truth_y=truth.translation.y,
            truth_yaw=yaw(truth.rotation),
        )
        if not (
            all(math.isfinite(v) and 0 <= v <= 0.25 for v in cov)
            and math.hypot(x, y) <= 0.35
            and abs(heading) <= 0.4
            and math.hypot(truth.translation.x, truth.translation.y) <= 0.35
            and abs(yaw(truth.rotation)) <= 0.4
            and s.readiness()
        ):
            raise RuntimeError("Initial localisation/TF/contact gates failed")
        return dict(
            geometry=True,
            map=True,
            parameters=True,
            route=True,
            tf_ownership=True,
            consumer_receipts=True,
            localization=True,
            contact_coverage=True,
        )

    def run(self) -> dict:
        from ament_index_python.packages import get_package_prefix, get_package_share_directory
        from experiment_runner.model import validate

        s = self.session
        if identity(self.root / GUARD) != self.plan["guard"]:
            raise RuntimeError("Guard changed before mission startup")
        mission = (
            Path(get_package_prefix("mission_manager")) / "lib/mission_manager/mission_server"
        )
        s.start(
            "mission",
            [
                str(mission),
                "--ros-args",
                "--params-file",
                str(Path(get_package_share_directory("mission_manager")) / "config/mission.yaml"),
                "-p",
                "runtime_mode:=sim",
                "-p",
                "use_sim_time:=true",
                "-p",
                f"artifact_root:={self.directory}/runs",
                "-p",
                "recording_config:="
                + str(
                    Path(get_package_share_directory("robot_recorder"))
                    / "config/warehouse_qualification.yaml"
                ),
                "-p",
                "environment:=warehouse_v1",
                "-p",
                f"map_file:={s.map_file}",
                "-p",
                f"navigation_profile:={self.profile}",
                "-p",
                f"software_revision:=source-plan-{self.plan['plan_sha256']}",
            ],
        )
        mission_config = self.matrix["mission"]
        config = {
            "name": f"w3-requalification-{self.profile}",
            "repetitions": 1,
            "expected": dict(
                runtime_mode="sim",
                robot_model="robotops_base",
                environment="warehouse_v1",
                navigation_profile=self.profile,
            ),
            "mission": {"waypoints": mission_config["waypoints"]},
            "start": mission_config["start"],
            "timeouts": mission_config["timeouts"],
            "validation": mission_config["validation_policy"],
        }
        validate(config)
        path = self.directory / "qualification.json"
        save_summary(path, config)
        self.gates()  # Recheck immediately before delegating dispatch to canonical runner.
        exe = Path(get_package_prefix("experiment_runner")) / "lib/experiment_runner/experiment"
        command = [str(exe), "run", str(path), "--output", str(self.directory / "experiments")]
        critical_event(s.journal, "runner_start_requested", command=command)
        s.observer.check()
        self.runner_log = (self.directory / "experiment.log").open("x")
        self.runner = subprocess.Popen(
            command,
            stdout=self.runner_log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=(self.lock_fd,),
            env=dict(os.environ, ROS_DOMAIN_ID=str(s.domain_id), GZ_PARTITION=s.partition),
        )
        critical_event(s.journal, "runner_started", pid=self.runner.pid)
        s.wait(lambda: self.runner.poll() is not None, "Qualification wall deadline", 650)
        if self.runner.returncode != 0:
            raise RuntimeError("Canonical experiment runner failed; no retry")
        files = list((self.directory / "experiments").glob("*/manifest.json"))
        if len(files) != 1:
            raise RuntimeError("Expected exactly one original experiment manifest")
        self.manifest_path = files[0]
        self.manifest_hash = sha(files[0])
        self.manifest = json.loads(files[0].read_text())
        if self.manifest.get("config") != config:
            raise RuntimeError("Original experiment config differs")
        s.journal.submit("original_result", manifest=self.manifest, sha256=self.manifest_hash)
        return self.manifest

    def close(self, exception: BaseException | None) -> dict:
        s = self.session
        if s is None:
            return {"startup_complete": False}
        runner_clean = False
        cleanup_error = None
        try:
            import rclpy

            def pump():
                # Callback failures remain sticky; keep collecting during the
                # existing runner cancellation budget even after a failed gate.
                rclpy.spin_once(s.node, timeout_sec=0.02)
                s.capture_logs()

            runner_clean = stop_runner(self.runner, s.journal, pump=pump)
        except BaseException as exc:
            cleanup_error = exc
        finally:
            # Retain any failed/interrupted original report before closing the
            # journal. Never rewrite or reinterpret it as a successful result.
            try:
                if self.manifest is None:
                    files = list((self.directory / "experiments").glob("*/manifest.json"))
                    for path in files:
                        json.loads(
                            path.read_text()
                        )  # Reject corrupt terminal evidence; preserve original file.
                        critical_event(
                            s.journal,
                            "retained_terminal_manifest",
                            path=str(path),
                            sha256=sha(path),
                        )
            except BaseException as error:
                cleanup_error = error
            if self.runner_log:
                self.runner_log.close()
            try:
                cause = exception or cleanup_error
                s.__exit__(type(cause) if cause else None, cause, None)
            except BaseException as exc:
                cleanup_error = exc
        summary = json.loads((self.directory / "observer-shutdown.json").read_text())
        remaining = robotics_processes()
        save_summary(self.directory / "post-shutdown-processes.json", {"remaining": remaining})
        recordings = False
        if self.manifest is not None:
            from experiment_runner.validation import artifact_provenance

            trial = self.manifest["trials"][0]
            artifact = Path(trial["artifact_directory"]).resolve()
            artifact.relative_to((self.directory / "runs").resolve())
            import yaml
            from robot_recorder.recording import inspect_bag

            provenance = artifact_provenance(artifact, trial, self.manifest)
            # Existing recorder/result contracts are unchanged. This extra W3
            # evidence gate requires sensor/map/contact/clock presence too.
            coverage = inspect_bag(
                artifact / "telemetry",
                [
                    "/odom",
                    "/tf",
                    "/tf_static",
                    "/scan",
                    "/imu/data",
                    "/map",
                    "/validation/contacts",
                    "/clock",
                ],
            )
            info = yaml.safe_load((artifact / "telemetry/metadata.yaml").read_text())
            save_summary(
                self.directory / "recording-coverage.json",
                {
                    "finalized": coverage,
                    "bag_information": info,
                    "limitation": "Topic counts do not prove gap-free per-topic coverage; "
                    "retain original timestamps and report gaps at export qualification.",
                },
            )
            save_summary(self.directory / "post-shutdown-provenance.json", provenance)
            recordings = (
                provenance.get("state") == "confirmed"
                and sha(self.manifest_path) == self.manifest_hash
            )
        try:
            readback = verify_evidence(self.directory, self.manifest, self.manifest_hash)
        except Exception as error:
            readback = {"complete": False, "error": f"{type(error).__name__}: {error}"}
        save_summary(self.directory / "two-stream-verification.json", readback)
        return {
            "runner_clean": runner_clean,
            "two_stream_readback_complete": readback["complete"],
            "critical_lifecycle_complete": critical_status(s.journal)["complete"],
            "cleanup_no_exception": cleanup_error is None,
            "observer_and_cleanup_complete": summary["observer_and_cleanup_complete"],
            "recording_integrity_and_original_immutability": recordings,
            "no_remaining_robotics_processes": not remaining,
        }


def execute_reviewed(root: Path, profile: str, plan_path: Path, permission_path: Path) -> dict:
    """Future owner-approved entry, deliberately not exposed as a live CLI now."""
    from robotops_backend.campaigns.ownership import RuntimeOwnership

    from .driver import ReadOnlyLease, execute

    root = root.resolve(strict=True)
    adapter = QualificationRuntime(root, profile, plan_path, permission_path)
    ownership = RuntimeOwnership(
        root / "artifacts/runtime.lock", ReadOnlyLease(root / "artifacts/campaigns.sqlite3")
    )
    return execute(root, profile, ownership, adapter, adapter.plan)
