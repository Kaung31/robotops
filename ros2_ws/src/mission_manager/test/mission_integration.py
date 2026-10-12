"""Real mission action + real MCAP recording against a controlled Nav2 server."""

import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest
import rclpy
import rosbag2_py
import yaml
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_prefix
from geometry_msgs.msg import PoseStamped, TransformStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rcl_interfaces.srv import SetParameters
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.serialization import deserialize_message
from robotops_interfaces.action import ExecuteMission
from rosgraph_msgs.msg import Clock
from tf2_msgs.msg import TFMessage


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out waiting for ROS test condition")


def future_result(future, timeout=15):
    wait_for(future.done, timeout)
    return future.result()


class Rig:
    def __init__(self, path, domain, mode="success", mission_parameters=None):
        self.path, self.mode = path, mode
        self.goals, self.cancels = [], []
        self.stop = threading.Event()
        self.pause_clock = mode == "no_clock"
        self.started = time.monotonic()
        rclpy.init(domain_id=domain)
        self.namespace = "/unit" if mode == "namespace" else "/"
        self.node = rclpy.create_node("controlled_nav2", namespace=self.namespace)
        self.group = ReentrantCallbackGroup()
        self.nav = ActionServer(
            self.node,
            NavigateToPose,
            "navigate_to_pose",
            execute_callback=self.execute,
            goal_callback=self.accept,
            cancel_callback=self.cancel,
            callback_group=self.group,
        )
        self.client = ActionClient(
            self.node, ExecuteMission, "missions/execute", callback_group=self.group
        )
        self.odom = self.node.create_publisher(Odometry, "odom", 10)
        self.clock = self.node.create_publisher(Clock, "/clock", 10)
        self.static = self.node.create_publisher(
            TFMessage,
            "tf_static",
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        transform = TransformStamped()
        transform.header.frame_id, transform.child_frame_id = "base_link", "test_sensor"
        transform.transform.rotation.w = 1.0
        self.static.publish(TFMessage(transforms=[transform]))
        self.timer = self.node.create_timer(0.02, self.telemetry)
        self.executor = MultiThreadedExecutor(num_threads=4)
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin)
        self.thread.start()
        config = {
            "topics": ["odom", "tf_static"],
            "required_topics": ["odom", "tf_static"],
            "qos": {
                "tf_static": {
                    "reliability": "reliable",
                    "durability": "transient_local",
                    "depth": 1,
                }
            },
        }
        if mode == "missing_telemetry":
            config["topics"].append("missing")
            config["required_topics"].append("missing")
        config_path = path / "recording.yaml"
        config_path.write_text(yaml.safe_dump(config))
        executable = (
            Path(get_package_prefix("mission_manager")) / "lib/mission_manager/mission_server"
        )
        parameters = {
            "artifact_root": str(path / "runs"),
            "recording_config": str(config_path),
            "startup_timeout": 2.0 if mode in ("missing_telemetry", "no_clock") else 15.0,
            "response_timeout": 0.4,
            "cancel_timeout": 0.5,
            "goal_timeout": 10.0,
            "goal_wall_timeout": 2.0 if mode == "paused" else 10.0,
            "use_sim_time": mode in ("paused", "no_clock"),
        }
        parameters.update(mission_parameters or {})
        command = [str(executable), "--ros-args", "-r", f"__ns:={self.namespace}"]
        for key, value in parameters.items():
            value = str(value).lower() if isinstance(value, bool) else str(value)
            command += ["-p", f"{key}:={value}"]
        self.log_path = path / "mission.log"
        self.log = self.log_path.open("w")
        self.process = subprocess.Popen(
            command,
            env=dict(os.environ, ROS_DOMAIN_ID=str(domain)),
            stdout=self.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        assert self.client.wait_for_server(timeout_sec=15), self.log_path.read_text()
        time.sleep(0.1)

    def telemetry(self):
        self.odom.publish(Odometry())
        if not self.pause_clock:
            now = 10.0 + time.monotonic() - self.started
            message = Clock()
            message.clock.sec = int(now)
            message.clock.nanosec = int((now % 1.0) * 1e9)
            self.clock.publish(message)

    def accept(self, _request):
        if self.mode == "late_accept":
            time.sleep(1.5)
        return GoalResponse.REJECT if self.mode == "reject" else GoalResponse.ACCEPT

    def cancel(self, handle):
        self.cancels.append(handle.goal_id)
        return CancelResponse.REJECT if self.mode == "refuse_cancel" else CancelResponse.ACCEPT

    def execute(self, handle):
        self.goals.append(handle.request.pose.pose.position.x)
        deadline = time.monotonic() + (
            0.5 if self.mode in ("success", "namespace", "abort") else 12.0
        )
        while time.monotonic() < deadline and not self.stop.is_set():
            if handle.is_cancel_requested:
                handle.canceled()
                return NavigateToPose.Result()
            time.sleep(0.02)
        if self.mode == "abort" or self.stop.is_set():
            handle.abort()
        else:
            handle.succeed()
        return NavigateToPose.Result()

    def send(self, record=True, count=1, invalid=False):
        request = ExecuteMission.Goal(label="integration", record=record)
        for i in range(count):
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.pose.position.x = float(i + 1)
            pose.pose.orientation.w = 0.0 if invalid else 1.0
            request.waypoints.append(pose)
        return future_result(self.client.send_goal_async(request))

    def close(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
        try:
            code = self.process.wait(timeout=20)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait(timeout=5)
            self.stop.set()
            self.executor.shutdown(timeout_sec=5)
            self.thread.join(timeout=5)
            self.node.destroy_node()
            rclpy.shutdown()
            self.log.close()
        assert code == int(self.mode in ("late_accept", "refuse_cancel")), (
            self.log_path.read_text()
        )
        assert "Traceback" not in self.log_path.read_text(), self.log_path.read_text()
        assert "exception was never retrieved" not in self.log_path.read_text(), (
            self.log_path.read_text()
        )


@pytest.fixture
def rig(tmp_path, request):
    mode = getattr(request, "param", "success")
    modes = [
        "success",
        "abort",
        "reject",
        "hold",
        "refuse_cancel",
        "late_accept",
        "paused",
        "missing_telemetry",
        "recorder_loss",
        "shutdown",
        "namespace",
        "no_clock",
    ]
    instance = Rig(tmp_path, 160 + modes.index(mode), mode)
    try:
        yield instance
    finally:
        instance.close()


@pytest.mark.parametrize("rig", ["success", "namespace"], indirect=True)
def test_recorded_success_and_durable_data(rig):
    parameter_client = rig.node.create_client(SetParameters, "mission_manager/set_parameters")
    assert parameter_client.wait_for_service(timeout_sec=5)
    mutation = SetParameters.Request(
        parameters=[
            Parameter("runtime_mode", value="replay").to_parameter_msg(),
            Parameter("use_sim_time", value=True).to_parameter_msg(),
        ]
    )
    response = future_result(parameter_client.call_async(mutation))
    assert all(not result.successful for result in response.results)
    rig.node.destroy_client(parameter_client)
    assert not rig.send(invalid=True).accepted
    handle = rig.send(count=2)
    assert handle.accepted
    assert not rig.send(record=False).accepted
    reply = future_result(handle.get_result_async(), 25)
    assert reply.status == GoalStatus.STATUS_SUCCEEDED, reply.result
    assert reply.result.outcome == "succeeded"
    assert rig.goals == [1.0, 2.0]
    directory = Path(reply.result.artifact_directory)
    metadata = json.loads((directory / "metadata.json").read_text())
    result = json.loads((directory / "result.json").read_text())
    assert metadata["software_revision"] is None
    assert len(metadata["mission_id"]) == 64
    assert result["completed_waypoints"] == 2
    assert result["elapsed_wall_seconds"] > 0
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(directory / "telemetry"), storage_id="mcap"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    topics = set()
    while reader.has_next():
        topic, raw, timestamp = reader.read_next()
        topics.add(topic)
        assert timestamp > 0
        if topic == rig.node.resolve_topic_name("tf_static"):
            assert (
                deserialize_message(raw, TFMessage).transforms[0].child_frame_id == "test_sensor"
            )
    assert {rig.node.resolve_topic_name(t) for t in ("odom", "tf_static")} <= topics
    del reader
    assert rig.node.count_publishers("/drive_controller/cmd_vel") == 0
    # Same server can execute another completed run without a recording.
    reply2 = future_result(rig.send(record=False).get_result_async())
    assert reply2.result.outcome == "succeeded"
    assert reply2.result.run_id != reply.result.run_id
    assert not (Path(reply2.result.artifact_directory) / "telemetry").exists()


@pytest.mark.parametrize(
    "rig", ["reject", "abort", "missing_telemetry", "no_clock"], indirect=True
)
def test_dependencies_or_navigation_failure(rig):
    reply = future_result(rig.send(record=rig.mode == "missing_telemetry").get_result_async(), 25)
    assert reply.status == GoalStatus.STATUS_ABORTED
    assert reply.result.outcome == "failed"
    if rig.mode in ("missing_telemetry", "no_clock"):
        assert not rig.goals
    if rig.mode == "no_clock":
        data = json.loads((Path(reply.result.artifact_directory) / "result.json").read_text())
        assert data["started_ros_ns"] is None and data["elapsed_ros_seconds"] is None


@pytest.mark.parametrize("rig", ["hold"], indirect=True)
def test_cancel_and_overlap(rig):
    handle = rig.send()
    wait_for(lambda: rig.goals)
    assert not rig.send().accepted
    assert future_result(handle.cancel_goal_async()).goals_canceling
    reply = future_result(handle.get_result_async())
    assert reply.status == GoalStatus.STATUS_CANCELED
    assert reply.result.outcome == "canceled" and rig.cancels
    assert json.loads((Path(reply.result.artifact_directory) / "result.json").read_text())[
        "recording"
    ]


@pytest.mark.parametrize("rig", ["late_accept", "refuse_cancel"], indirect=True)
def test_uncertain_navigation_latches_fault(rig):
    handle = rig.send(record=False)
    if rig.mode == "refuse_cancel":
        wait_for(lambda: rig.goals)
        future_result(handle.cancel_goal_async())
    reply = future_result(handle.get_result_async())
    assert reply.result.outcome == "cancellation_unconfirmed", reply.result
    assert reply.status == GoalStatus.STATUS_ABORTED
    assert not rig.send(record=False).accepted
    wait_for(lambda: rig.cancels)


@pytest.mark.parametrize("rig", ["paused"], indirect=True)
def test_paused_clock_has_wall_time_bound(rig):
    handle = rig.send(record=False)
    wait_for(lambda: rig.goals)
    rig.pause_clock = True
    reply = future_result(handle.get_result_async())
    assert reply.result.outcome == "failed"
    assert "wall-time" in reply.result.message and rig.cancels


@pytest.mark.parametrize("rig", ["recorder_loss"], indirect=True)
def test_recorder_loss_cancels_navigation(rig):
    handle = rig.send()
    wait_for(lambda: rig.goals)
    matched = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if (
            b"record" in args
            and any(str(rig.path / "runs").encode() in a for a in args)
            and b"--node-name" in args
        ):
            matched.append(int(entry.name))
    assert len(matched) == 1, matched
    os.kill(matched[0], signal.SIGKILL)
    reply = future_result(handle.get_result_async())
    assert reply.result.outcome == "failed" and rig.cancels
    assert "recording failed" in reply.result.message


@pytest.mark.parametrize("rig", ["shutdown"], indirect=True)
def test_shutdown_cancels_before_finalizing_recording(rig):
    rig.send()
    wait_for(lambda: rig.goals)
    rig.process.send_signal(signal.SIGINT)
    assert rig.process.wait(timeout=20) == 0, rig.log_path.read_text()
    assert rig.cancels
    results = list((rig.path / "runs").glob("*/result.json"))
    assert len(results) == 1
    result = json.loads(results[0].read_text())
    assert result["outcome"] == "canceled" and result["recording"]


def test_unacknowledged_acceptance_latches_fault():
    from mission_manager.server import MissionServer

    rclpy.init(args=["--ros-args", "-p", "response_timeout:=0.02"], domain_id=173)
    node = MissionServer()
    try:
        pose = PoseStamped()
        pose.header.frame_id = "map"
        pose.pose.orientation.w = 1.0
        request = ExecuteMission.Goal(label="lost_ack", waypoints=[pose], record=False)
        assert node.accept(request) == GoalResponse.ACCEPT
        # Model a response transport failure: accepted execution never starts.
        time.sleep(0.04)
        node.check_reservation()
        assert node.faulted and not node.busy
        assert node.accept(request) == GoalResponse.REJECT
    finally:
        node.worker.shutdown(wait=True)
        node.server.destroy()
        node.navigator.destroy()
        node.destroy_node()
        rclpy.shutdown()
