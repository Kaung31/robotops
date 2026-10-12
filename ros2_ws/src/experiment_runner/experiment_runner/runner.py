"""Own sequential mission trials without owning a robot backend or velocity path."""

import json
import math
import signal
import time
from pathlib import Path
from uuid import uuid4

import rclpy
import rosbag2_py
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from rcl_interfaces.srv import GetParameters, ListParameters
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.parameter import Parameter, parameter_value_to_python
from rclpy.serialization import deserialize_message
from rclpy.signals import SignalHandlerOptions
from rclpy.time import Time
from robot_recorder.artifacts import atomic_json, map_reference, utc_now
from robotops_interfaces.action import ExecuteMission
from tf2_ros import Buffer, TransformListener
from unique_identifier_msgs.msg import UUID

from experiment_runner.contact_observation import ContactObservation
from experiment_runner.model import check_start, parameter_json, path_length, report
from experiment_runner.observation import FinalObservation
from experiment_runner.validation import artifact_provenance, file_hash, policy_for, validate_final

PARAMETER_NODES = (
    "mission_manager",
    "drive_controller",
    "controller_server",
    "planner_server",
    "bt_navigator",
    "behavior_server",
    "map_server",
    "amcl",
)


class Interrupted(Exception):
    pass


def bag_metrics(directory: Path, result: dict, odom_topic: str) -> dict:
    metrics = {
        "mission_ros_seconds": result.get("elapsed_ros_seconds"),
        "odom_path_metres": None,
        "unavailable": {},
    }
    try:
        reader = rosbag2_py.SequentialReader()
        reader.open(
            rosbag2_py.StorageOptions(uri=str(directory / "telemetry"), storage_id="mcap"),
            rosbag2_py.ConverterOptions("cdr", "cdr"),
        )
        types = {t.name: t.type for t in reader.get_all_topics_and_types()}
        if types.get(odom_topic) != "nav_msgs/msg/Odometry":
            raise ValueError(f"No Odometry recording on {odom_topic}")

        def samples():
            while reader.has_next():
                topic, data, _ = reader.read_next()
                if topic == odom_topic:
                    msg = deserialize_message(data, Odometry)
                    yield (
                        msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec,
                        msg.header.frame_id,
                        msg.child_frame_id,
                        msg.pose.pose.position.x,
                        msg.pose.pose.position.y,
                    )

        metrics["odom_path_metres"] = path_length(samples())
    except Exception as error:
        metrics["unavailable"]["odom_path_metres"] = str(error)
    return metrics


class ExperimentRunner(Node):
    def __init__(self, config: dict, root: Path, baseline: dict | None = None):
        super().__init__("experiment_runner")
        self.config = config
        self.stopping = False
        self.client = ActionClient(self, ExecuteMission, "missions/execute")
        self.buffer = Buffer(node=self)
        self.listener = TransformListener(self.buffer, self)
        self.observation = FinalObservation(self, self.buffer)
        self.contacts = ContactObservation(self)
        self.validation_policy = policy_for(config)
        self.dispatch_ros_ns = None
        self.clock_regressed = False
        self.previous_ros_ns = None
        self.directory = root.expanduser().resolve() / uuid4().hex
        self.directory.mkdir(parents=True, exist_ok=False)
        self.manifest = dict(
            schema_version=1,
            validation_version=1,
            validation_policy=self.validation_policy,
            experiment_id=self.directory.name,
            created_utc=utc_now(),
            state="running",
            config=config,
            fault_configuration=None,
            random_seed=None,
            trials=[],
        )
        self.pending = self.mission_handle = self.terminal = None
        self.baseline = baseline["parameters"] if baseline else None
        if baseline:
            self.manifest["map_hashes"] = baseline["map_hashes"]
            self.manifest["baseline_source"] = baseline["source"]
        self.persist()

    def persist(self) -> None:
        atomic_json(self.directory / "manifest.json", self.manifest)
        atomic_json(self.directory / "report.json", report(self.manifest))

    def wait(self, predicate, seconds: float, interruptible: bool = True) -> None:
        deadline = time.monotonic() + seconds
        while not predicate():
            if interruptible and self.stopping:
                raise Interrupted("Experiment interrupted")
            if time.monotonic() >= deadline:
                raise TimeoutError("ROS readiness/action response timed out")
            rclpy.spin_once(self, timeout_sec=0.05)
            if self.dispatch_ros_ns is not None:
                now = self.get_clock().now().nanoseconds
                if self.previous_ros_ns is not None and now < self.previous_ros_ns:
                    self.clock_regressed = True
                self.previous_ros_ns = now
        if interruptible and self.stopping:
            raise Interrupted("Experiment interrupted")

    def call(self, kind, name: str, request):
        client = self.create_client(kind, name)
        try:
            self.wait(client.service_is_ready, self.config["timeouts"]["response"])
            future = client.call_async(request)
            self.wait(future.done, self.config["timeouts"]["response"])
            return future.result()
        finally:
            self.destroy_client(client)

    def parameters(self) -> dict:
        snapshot = {}
        for node in PARAMETER_NODES:
            names = sorted(
                self.call(
                    ListParameters, f"{node}/list_parameters", ListParameters.Request()
                ).result.names
            )
            values = self.call(
                GetParameters, f"{node}/get_parameters", GetParameters.Request(names=names)
            ).values
            snapshot[node] = {
                n: parameter_json(parameter_value_to_python(v))
                for n, v in zip(names, values, strict=True)
            }
        return snapshot

    def preflight(self) -> dict:
        snapshot = self.parameters()
        mission = snapshot["mission_manager"]
        for name, expected in self.config["expected"].items():
            if mission.get(name) != expected:
                raise ValueError(f"Live mission setting {name} differs from configuration")
        if mission.get("global_frame") != "map":
            raise ValueError("Experiment poses currently require global frame map")
        clock = mission.get("use_sim_time")
        if type(clock) is not bool:
            raise ValueError("Mission clock setting is unavailable")
        if any(s.get("use_sim_time") != clock for s in snapshot.values()):
            raise ValueError("Live nodes do not share the same clock setting")
        self.set_parameters([Parameter("use_sim_time", value=clock)])
        if self.baseline is not None and snapshot != self.baseline:
            raise ValueError("Live parameters changed between trials")
        reference = map_reference(snapshot["map_server"].get("yaml_filename", ""))
        if reference is None:
            raise ValueError("Live map server must identify a saved map")
        hashes = {k: reference[k] for k in ("yaml_sha256", "image_sha256")}
        if "map_hashes" in self.manifest and self.manifest["map_hashes"] != hashes:
            raise ValueError("Saved map changed between trials")
        self.manifest["map_hashes"] = hashes
        self.manifest["map_reference"] = dict(
            reference, source="live map_server yaml_filename parameter; files on shared filesystem"
        )

        # TF must be current, not merely a cached transform from an earlier run.
        def ready():
            if not self.buffer.can_transform("map", "base_link", Time()):
                return False
            transform = self.buffer.lookup_transform("map", "base_link", Time())
            age = (
                self.get_clock().now() - Time.from_msg(transform.header.stamp)
            ).nanoseconds / 1e9
            return self.get_clock().now().nanoseconds > 0 and 0 <= age <= 1.0

        self.wait(ready, self.config["timeouts"]["response"])
        transform = self.buffer.lookup_transform("map", "base_link", Time()).transform
        q = transform.rotation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        check_start(self.config["start"], transform.translation.x, transform.translation.y, yaw)
        self.baseline = snapshot
        return {
            "parameters": snapshot,
            "start_pose": {"x": transform.translation.x, "y": transform.translation.y, "yaw": yaw},
            "observed_utc": utc_now(),
        }

    def cancel(self) -> bool:
        if self.pending is None:
            return True
        try:
            deadline = time.monotonic() + self.config["timeouts"]["cancel"]
            self.wait(self.pending.done, max(0, deadline - time.monotonic()), False)
            self.mission_handle = self.pending.result()
            if not self.mission_handle.accepted:
                return True
            if self.terminal is None:
                self.terminal = self.mission_handle.get_result_async()
            if not self.terminal.done():
                cancellation = self.mission_handle.cancel_goal_async()
                self.wait(cancellation.done, max(0, deadline - time.monotonic()), False)
                cancellation.result()
            self.wait(self.terminal.done, max(0, deadline - time.monotonic()), False)
            reply = self.terminal.result()
            return (
                reply.status
                in (
                    GoalStatus.STATUS_SUCCEEDED,
                    GoalStatus.STATUS_ABORTED,
                    GoalStatus.STATUS_CANCELED,
                )
                and reply.result.outcome != "cancellation_unconfirmed"
            )
        except Exception as error:
            self.get_logger().error(f"Mission termination unconfirmed: {error}")
            return False

    def execute(self) -> bool:
        trial = None
        try:
            self.wait(self.client.server_is_ready, self.config["timeouts"]["response"])
            for index in range(self.config["repetitions"]):
                trial = None
                self.pending = self.mission_handle = self.terminal = None
                self.dispatch_ros_ns = None
                evidence = self.preflight()
                goal_id = uuid4()
                trial = dict(
                    index=index,
                    mission_goal_id=goal_id.hex,
                    outcome="pending",
                    collision={
                        "schema_version": 1,
                        "verdict": "UNKNOWN",
                        "reasons": ["No finalized contact evidence"],
                    },
                    validation={
                        "schema_version": 1,
                        "verdict": "INCONCLUSIVE",
                        "reasons": ["No finalized validation evidence"],
                    },
                    started_utc=utc_now(),
                    **evidence,
                )
                self.manifest["trials"].append(trial)
                # A killed process leaves a pending trial; never auto-retry.
                self.persist()
                request = ExecuteMission.Goal(label=self.config["name"], record=True)
                for pose in self.config["mission"]["waypoints"]:
                    msg = PoseStamped()
                    msg.header.frame_id = "map"
                    msg.pose.position.x, msg.pose.position.y = float(pose["x"]), float(pose["y"])
                    msg.pose.orientation.z = math.sin(pose["yaw"] / 2)
                    msg.pose.orientation.w = math.cos(pose["yaw"] / 2)
                    request.waypoints.append(msg)

                def feedback(message, owned_trial=trial):
                    owned_trial.update(
                        run_id=message.feedback.run_id, mission_state=message.feedback.state
                    )
                    self.persist()

                self.dispatch_ros_ns = self.get_clock().now().nanoseconds
                self.contacts.begin()
                self.previous_ros_ns = self.dispatch_ros_ns
                self.clock_regressed = False
                trial["dispatch_ros_ns"] = self.dispatch_ros_ns
                self.persist()
                self.pending = self.client.send_goal_async(
                    request, feedback_callback=feedback, goal_uuid=UUID(uuid=list(goal_id.bytes))
                )
                self.wait(self.pending.done, self.config["timeouts"]["response"])
                self.mission_handle = self.pending.result()
                if not self.mission_handle.accepted:
                    trial["outcome"] = "rejected"
                    raise RuntimeError("Mission rejected; no retry will be submitted")
                self.terminal = self.mission_handle.get_result_async()
                self.wait(self.terminal.done, self.config["timeouts"]["trial"])
                reply = self.terminal.result()
                value = reply.result
                snapshot = self.observation.capture(
                    self.dispatch_ros_ns, evidence["parameters"], self.clock_regressed
                )
                trial["final_observation"] = snapshot
                trial["collision"], contact_frames = self.contacts.finish(
                    self.dispatch_ros_ns, snapshot["observed_ros_ns"]
                )
                contact_file = self.directory / f"contacts-{index}.json"
                atomic_json(contact_file, {"frames": contact_frames})
                trial["collision"]["artifact"] = {
                    "path": str(contact_file),
                    "sha256": file_hash(contact_file),
                }
                trial.update(
                    outcome=value.outcome,
                    mission_outcome=value.outcome,
                    run_id=value.run_id,
                    artifact_directory=value.artifact_directory,
                    message=value.message,
                    action_status=reply.status,
                    ended_utc=utc_now(),
                )
                if value.outcome == "succeeded" and not (
                    value.run_id and value.artifact_directory
                ):
                    raise ValueError("Successful mission did not identify its artifacts")
                if value.run_id and value.artifact_directory:
                    directory = Path(value.artifact_directory)
                    saved = json.loads((directory / "result.json").read_text())
                    metadata = json.loads((directory / "metadata.json").read_text())
                    if (
                        saved["run_id"] != value.run_id
                        or metadata["run_id"] != value.run_id
                        or saved["outcome"] != value.outcome
                    ):
                        raise ValueError("Mission artifacts do not match action result")
                    trial["software_revision"] = metadata.get("software_revision")
                    trial["metrics"] = bag_metrics(
                        directory, saved, self.resolve_topic_name("odom")
                    )
                trial["parameters_after"] = self.parameters()
                if trial["parameters_after"] != evidence["parameters"]:
                    trial["outcome"] = "invalid_conditions"
                    raise ValueError("Live parameters changed during the trial")
                after_map = map_reference(
                    trial["parameters_after"]["map_server"].get("yaml_filename", "")
                )
                if after_map is None or any(
                    after_map[k] != v for k, v in self.manifest["map_hashes"].items()
                ):
                    trial["outcome"] = "invalid_conditions"
                    raise ValueError("Saved map changed during the trial")
                trial["map_hashes_after"] = {k: after_map[k] for k in self.manifest["map_hashes"]}
                provenance = artifact_provenance(
                    Path(value.artifact_directory), trial, self.manifest
                )
                trial["collision"]["provenance_state"] = provenance["state"]
                if provenance["state"] != "confirmed":
                    trial["collision"]["verdict"] = "UNKNOWN"
                    trial["collision"]["reasons"].append("Unconfirmed mission provenance")
                trial["validation"] = validate_final(
                    self.validation_policy,
                    self.config["mission"]["waypoints"][-1],
                    snapshot,
                    provenance,
                    value.outcome,
                    reply.status,
                )
                controller = evidence["parameters"].get("controller_server", {})
                trial["validation"]["nav2_goal_checkers"] = {
                    key: value
                    for key, value in controller.items()
                    if key == "goal_checker_plugins"
                    or any(
                        key.startswith(f"{plugin}.")
                        for plugin in controller.get("goal_checker_plugins", [])
                    )
                }
                self.persist()
                if value.outcome != "succeeded" or reply.status != GoalStatus.STATUS_SUCCEEDED:
                    raise RuntimeError(
                        f"Trial ended with {value.outcome}; remaining trials stopped"
                    )
            self.manifest["state"] = "completed"
            return True
        except Exception as error:
            confirmed = self.cancel()
            self.manifest.update(
                state="interrupted" if isinstance(error, Interrupted) and confirmed else "failed",
                error=str(error),
                termination_confirmed=confirmed,
            )
            if trial is not None and trial["outcome"] in ("pending", "succeeded"):
                if self.terminal is not None and self.terminal.done():
                    try:
                        reply = self.terminal.result()
                        value = reply.result
                        trial.update(
                            run_id=value.run_id,
                            artifact_directory=value.artifact_directory,
                            mission_outcome=value.outcome,
                            action_status=reply.status,
                        )
                    except Exception as result_error:
                        trial["result_error"] = str(result_error)
                trial.update(
                    outcome=("interrupted" if isinstance(error, Interrupted) else "failed")
                    if confirmed
                    else "termination_unconfirmed",
                    error=str(error),
                    ended_utc=utc_now(),
                )
            return False
        finally:
            if trial is not None and (
                trial["collision"].get("provenance_state") != "confirmed"
                or self.clock_regressed
                or trial.get("mission_outcome")
                in ("termination_unconfirmed", "cancellation_unconfirmed")
            ):
                trial["collision"]["verdict"] = "UNKNOWN"
                trial["collision"]["reasons"].append(
                    "Mission provenance, clock or terminal confirmation unavailable"
                )
            if trial is not None and trial["validation"].get("reasons") == [
                "No finalized validation evidence"
            ]:
                trial["validation"] = validate_final(
                    self.validation_policy,
                    self.config["mission"]["waypoints"][-1],
                    trial.get("final_observation", {}),
                    {
                        "state": "unconfirmed",
                        "error": self.manifest.get("error", "Validation not finalized"),
                    },
                    trial.get("mission_outcome", trial["outcome"]),
                    trial.get("action_status"),
                )
            self.manifest["ended_utc"] = utc_now()
            self.persist()

    def close(self) -> None:
        self.listener.unregister()
        self.client.destroy()
        self.destroy_node()


def run(config: dict, root: Path, ros_args: list[str], baseline: dict | None = None) -> int:
    rclpy.init(args=ros_args, signal_handler_options=SignalHandlerOptions.NO)
    node = ExperimentRunner(config, root, baseline=baseline)
    old = {}

    def stop(_signal, _frame):
        node.stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        old[sig] = signal.signal(sig, stop)
    try:
        success = node.execute()
        print(node.directory, flush=True)
        return 0 if success else 1
    finally:
        node.close()
        rclpy.shutdown()
        for sig, handler in old.items():
            signal.signal(sig, handler)
