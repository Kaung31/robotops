"""Mission ownership, Nav2 cancellation and recording through stable ROS interfaces."""

import copy
import hashlib
import json
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import rclpy
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.action.server import ServerGoalHandle
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSCompatibility, qos_check_compatible
from rclpy.signals import SignalHandlerOptions
from rclpy.task import Future
from robot_recorder.artifacts import RunStore, map_reference, utc_now
from robot_recorder.recording import Recorder, load_recording_config
from robotops_interfaces.action import ExecuteMission

from mission_manager.model import positive_seconds, validate_mission


class MissionCanceled(Exception):
    pass


def pose_snapshot(poses: list[PoseStamped]) -> list[dict]:
    return [
        dict(
            frame=p.header.frame_id,
            x=p.pose.position.x,
            y=p.pose.position.y,
            z=p.pose.position.z,
            qx=p.pose.orientation.x,
            qy=p.pose.orientation.y,
            qz=p.pose.orientation.z,
            qw=p.pose.orientation.w,
        )
        for p in poses
    ]


class MissionServer(Node):
    def __init__(self):
        super().__init__("mission_manager")
        defaults = {
            "runtime_mode": "mock",
            "artifact_root": "artifacts/runs",
            "robot_model": "robotops_base",
            "environment": "unspecified",
            "navigation_profile": "unspecified",
            "software_revision": "",
            "map_file": "",
            "global_frame": "map",
            "startup_timeout": 15.0,
            "goal_timeout": 120.0,
            "goal_wall_timeout": 180.0,
            "response_timeout": 5.0,
            "cancel_timeout": 5.0,
            "recording_config": str(
                Path(get_package_share_directory("robot_recorder")) / "config/recording.yaml"
            ),
        }
        self.settings = {
            name: self.declare_parameter(
                name, value, descriptor=ParameterDescriptor(read_only=True)
            ).value
            for name, value in defaults.items()
        }
        clock_descriptor = copy.deepcopy(self.describe_parameter("use_sim_time"))
        clock_descriptor.read_only = True
        self.set_descriptor("use_sim_time", clock_descriptor)
        if self.settings["runtime_mode"] not in ("mock", "sim"):
            raise ValueError("Missions support mock/sim only; replay and real are disabled")
        for name in (
            "startup_timeout",
            "goal_timeout",
            "goal_wall_timeout",
            "response_timeout",
            "cancel_timeout",
        ):
            positive_seconds(self.settings[name], name)
        config = load_recording_config(Path(self.settings["recording_config"]))
        self.recording_config = {
            "topics": [self.resolve_topic_name(t) for t in config["topics"]],
            "required_topics": [self.resolve_topic_name(t) for t in config["required_topics"]],
            "startup_topics": [self.resolve_topic_name(t) for t in config["startup_topics"]],
            "qos": {self.resolve_topic_name(t): q for t, q in config["qos"].items()},
        }
        self.stopping = threading.Event()
        self._lock = threading.Lock()
        self.busy = False
        self.faulted = False
        self.execution_started = False
        self.reservation_started = 0.0
        self.group = ReentrantCallbackGroup()
        self.navigator = ActionClient(
            self, NavigateToPose, "navigate_to_pose", callback_group=self.group
        )
        self.server = ActionServer(
            self,
            ExecuteMission,
            "missions/execute",
            execute_callback=self.execute,
            goal_callback=self.accept,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=self.group,
        )
        self.store = None
        self.recorder = None
        self.nav_pending = self.nav_handle = self.nav_result = None
        self.completed = 0
        self.current = 0
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mission")

    def accept(self, request: ExecuteMission.Goal) -> GoalResponse:
        try:
            validate_mission(
                request.label, pose_snapshot(request.waypoints), self.settings["global_frame"]
            )
        except ValueError as error:
            self.get_logger().warning(str(error))
            return GoalResponse.REJECT
        with self._lock:
            if self.busy or self.faulted or self.stopping.is_set():
                return GoalResponse.REJECT
            self.busy = True
            self.execution_started = False
            self.reservation_started = time.monotonic()
        return GoalResponse.ACCEPT

    def check_reservation(self) -> None:
        # A middleware response failure can prevent the accepted callback from
        # ever starting. Latch uncertainty instead of waiting forever on shutdown.
        with self._lock:
            expired = (
                self.busy
                and not self.execution_started
                and (
                    time.monotonic() - self.reservation_started > self.settings["response_timeout"]
                )
            )
            if expired:
                self.faulted, self.busy = True, False
        if expired:
            self.get_logger().error("Mission acceptance did not complete; manager fault latched")

    def now_ns(self) -> int:
        return self.get_clock().now().nanoseconds

    def transition(self, goal: ServerGoalHandle, state: str) -> None:
        self.store.event(
            state, self.now_ns(), current_waypoint=self.current, completed_waypoints=self.completed
        )
        goal.publish_feedback(
            ExecuteMission.Feedback(
                run_id=self.store.run_id,
                state=state,
                current_waypoint=self.current,
                completed_waypoints=self.completed,
            )
        )

    def check(self, goal: ServerGoalHandle) -> None:
        if goal.is_cancel_requested or self.stopping.is_set():
            raise MissionCanceled("Mission cancellation requested")
        if self.recorder is not None:
            self.recorder.check_alive()

    def wait_future(self, future: Future, seconds: float):
        deadline = time.monotonic() + seconds
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not future.done():
            raise TimeoutError("ROS action response timed out")
        return future.result()

    def prepare(self, goal: ServerGoalHandle) -> None:
        deadline = time.monotonic() + self.settings["startup_timeout"]
        while not self.navigator.server_is_ready() or self.now_ns() <= 0:
            self.check(goal)
            if time.monotonic() >= deadline:
                raise TimeoutError("Nav2 action server or ROS clock is unavailable")
            time.sleep(0.02)
        if not goal.request.record:
            return
        self.recorder = Recorder(
            self.store.directory,
            self.store.run_id,
            self.recording_config,
            bool(self.get_parameter("use_sim_time").value),
        )
        deadline = time.monotonic() + self.settings["startup_timeout"]
        while True:
            self.check(goal)
            status = self.recorder.startup_status(
                self.get_subscriptions_info_by_topic,
                self.get_publishers_info_by_topic,
                lambda offered, requested: qos_check_compatible(offered, requested)[0]
                == QoSCompatibility.OK,
            )
            if status["ready"]:
                self.store.event("recorder_ready", self.now_ns(), assessment=status)
                break
            if time.monotonic() >= deadline:
                self.store.event("recorder_readiness_failed", self.now_ns(), assessment=status)
                raise TimeoutError("Recorder readiness failed: " + json.dumps(status))
            time.sleep(0.02)
        self.transition(goal, "recording")

    def navigate(self, goal: ServerGoalHandle, pose: PoseStamped) -> None:
        self.check(goal)
        request = NavigateToPose.Goal()
        request.pose = copy.deepcopy(pose)
        request.pose.header.stamp = self.get_clock().now().to_msg()
        self.nav_pending = self.navigator.send_goal_async(request)
        self.nav_handle = self.wait_future(self.nav_pending, self.settings["response_timeout"])
        if not self.nav_handle.accepted:
            self.nav_pending = self.nav_handle = None
            raise RuntimeError("Nav2 rejected waypoint")
        self.nav_result = self.nav_handle.get_result_async()
        start = previous = self.now_ns()
        deadline = time.monotonic() + self.settings["goal_wall_timeout"]
        while not self.nav_result.done():
            self.check(goal)
            now = self.now_ns()
            if now < previous:
                raise RuntimeError("ROS clock moved backwards during navigation")
            previous = now
            if (now - start) / 1e9 > self.settings["goal_timeout"] or time.monotonic() >= deadline:
                raise TimeoutError("Navigation waypoint exceeded its ROS or wall-time limit")
            time.sleep(0.02)
        self.check(goal)
        result = self.nav_result.result()
        self.nav_pending = self.nav_handle = self.nav_result = None
        if result.status != GoalStatus.STATUS_SUCCEEDED:
            raise RuntimeError(f"Nav2 waypoint ended with status {result.status}")
        self.completed += 1

    def request_cancel(self, handle) -> None:
        future = handle.cancel_goal_async()

        def observe_response(reply):
            try:
                reply.result()
            except Exception as error:
                self.get_logger().error(f"Cancellation response failed: {error}")

        future.add_done_callback(observe_response)

    def cancel_navigation(self) -> bool:
        """Confirm a terminal action result, never infer stop from a cancel request."""
        if self.nav_pending is None:
            return True
        deadline = time.monotonic() + self.settings["cancel_timeout"]
        try:
            if self.nav_handle is None:
                self.nav_handle = self.wait_future(
                    self.nav_pending, max(0.0, deadline - time.monotonic())
                )
            if not self.nav_handle.accepted:
                return True
            if self.nav_result is None:
                self.nav_result = self.nav_handle.get_result_async()
            if not self.nav_result.done():
                self.request_cancel(self.nav_handle)
            result = self.wait_future(self.nav_result, max(0.0, deadline - time.monotonic()))
            return result.status in (
                GoalStatus.STATUS_SUCCEEDED,
                GoalStatus.STATUS_ABORTED,
                GoalStatus.STATUS_CANCELED,
            )
        except Exception as error:
            self.get_logger().error(f"Cannot confirm Nav2 cancellation: {error}")
            # A delayed acceptance still belongs to this mission. Cancel it if it
            # arrives later; keep the fault latched regardless of its later result.
            pending = self.nav_pending

            def cancel_late(future):
                try:
                    handle = future.result()
                    if handle.accepted:
                        self.request_cancel(handle)
                except Exception as late_error:
                    self.get_logger().error(f"Late goal cancellation failed: {late_error}")

            pending.add_done_callback(cancel_late)
            return False

    async def execute(self, goal: ServerGoalHandle) -> ExecuteMission.Result:
        # Keep ROS callbacks on one executor thread. The explicitly owned worker
        # handles blocking orchestration and is joined before ROS objects die.
        self.execution_started = True
        if self.faulted:
            goal.abort()
            with self._lock:
                self.busy = False
            return ExecuteMission.Result(
                outcome="failed", message="Mission acceptance expired; manager fault latched"
            )
        result = Future(executor=self.executor)

        def completed(task):
            try:
                result.set_result(task.result())
            except Exception as error:
                result.set_exception(error)

        self.worker.submit(self.run_owned, goal).add_done_callback(completed)
        try:
            return await result
        finally:
            with self._lock:
                self.busy = False

    def run_owned(self, goal: ServerGoalHandle) -> ExecuteMission.Result:
        try:
            return self.execute_owned(goal)
        except Exception as error:
            # An unexpected callback failure must not orphan our navigation goal.
            confirmed = self.cancel_navigation()
            self.faulted = True
            if self.recorder is not None and not self.recorder.log.closed:
                try:
                    self.recorder.stop()
                except Exception as recording_error:
                    self.get_logger().error(str(recording_error))
            message = f"Unexpected mission failure: {error}"
            self.get_logger().error(message)
            result = ExecuteMission.Result(
                outcome="failed" if confirmed else "cancellation_unconfirmed",
                message=message,
                completed_waypoints=self.completed,
            )
            goal.abort()
            return result

    def execute_owned(self, goal: ServerGoalHandle) -> ExecuteMission.Result:
        self.store = self.recorder = None
        self.nav_pending = self.nav_handle = self.nav_result = None
        self.current = self.completed = 0
        started_wall, accepted_ros = time.monotonic(), self.now_ns()
        self.run_started_ros = None
        mission_started_wall = mission_ended_wall = mission_ended_ros = None
        outcome, message, bag = "failed", "Mission did not complete", None
        result = ExecuteMission.Result()
        try:
            definition = dict(
                label=goal.request.label,
                waypoints=pose_snapshot(goal.request.waypoints),
                record=goal.request.record,
            )
            mission_id = hashlib.sha256(
                json.dumps(definition, sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
            metadata = dict(
                mission_id=mission_id,
                map=map_reference(self.settings["map_file"]),
                settings=self.settings,
                recording=self.recording_config,
                label=goal.request.label,
                waypoints=pose_snapshot(goal.request.waypoints),
                recording_enabled=goal.request.record,
                use_sim_time=bool(self.get_parameter("use_sim_time").value),
                accepted_utc=utc_now(),
                accepted_ros_ns=accepted_ros,
                started_utc=None,
                started_ros_ns=None,
                software_revision=self.settings["software_revision"] or None,
                software_revision_source="operator supplied"
                if self.settings["software_revision"]
                else "unavailable",
                experiment_id=None,
                fault_configuration=None,
            )
            self.store = RunStore(Path(self.settings["artifact_root"]), metadata)
            result.run_id, result.artifact_directory = self.store.run_id, str(self.store.directory)
            self.transition(goal, "preparing")
            self.prepare(goal)
            self.check(goal)
            self.run_started_ros = self.now_ns()
            mission_started_wall = time.monotonic()
            self.store.start(self.run_started_ros)
            for self.current, pose in enumerate(goal.request.waypoints):
                self.transition(goal, "navigating")
                self.navigate(goal, pose)
            self.check(goal)
            outcome, message = "succeeded", "All waypoints completed"
        except MissionCanceled as error:
            outcome, message = "canceled", str(error)
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
        preparation_ended_wall = (
            mission_started_wall if mission_started_wall is not None else time.monotonic()
        )
        if self.run_started_ros is not None:
            mission_ended_ros, mission_ended_wall = self.now_ns(), time.monotonic()
        try:
            if self.nav_pending is not None:
                if self.store is not None:
                    self.transition(goal, "canceling")
                if not self.cancel_navigation():
                    self.faulted = True
                    outcome = "cancellation_unconfirmed"
                    message += (
                        "; Nav2 termination unconfirmed; restart only after checking navigation"
                    )
            if self.store is not None:
                self.transition(goal, "finalizing")
        except Exception as error:
            # Artifact/feedback failure must not skip cancellation or bag cleanup.
            confirmed = self.cancel_navigation()
            self.faulted = self.faulted or not confirmed
            outcome = "failed" if confirmed else "cancellation_unconfirmed"
            message += f"; finalization error: {error}"
        try:
            if self.recorder is not None:
                bag = self.recorder.stop()
        except Exception as error:
            if outcome != "cancellation_unconfirmed":
                outcome = "failed"
            message += f"; recording failed: {error}"
        if outcome == "succeeded" and (goal.is_cancel_requested or self.stopping.is_set()):
            outcome, message = "canceled", "Canceled during finalization"
        ended_ros = self.now_ns()
        started_ros = self.run_started_ros
        if (
            started_ros is not None
            and (ended_ros < started_ros or mission_ended_ros < started_ros)
            and outcome != "cancellation_unconfirmed"
        ):
            outcome, message = "failed", "ROS clock moved backwards during mission"
        try:
            if self.store is not None:
                self.store.event(outcome, ended_ros, message=message)
                self.store.finish(
                    dict(
                        outcome=outcome,
                        message=message,
                        completed_waypoints=self.completed,
                        ended_ros_ns=ended_ros,
                        recording=bag,
                        started_ros_ns=started_ros,
                        mission_ended_ros_ns=mission_ended_ros,
                        preparation_wall_seconds=preparation_ended_wall - started_wall,
                        total_elapsed_wall_seconds=time.monotonic() - started_wall,
                        elapsed_ros_seconds=(mission_ended_ros - started_ros) / 1e9
                        if started_ros is not None
                        else None,
                        elapsed_wall_seconds=mission_ended_wall - mission_started_wall
                        if mission_started_wall is not None
                        else None,
                    )
                )
        except Exception as error:
            if outcome != "cancellation_unconfirmed":
                outcome = "failed"
            message += f"; cannot persist result: {error}"
        result.outcome, result.message, result.completed_waypoints = (
            outcome,
            message,
            self.completed,
        )
        self.get_logger().info(f"Mission {result.run_id}: {outcome}: {message}")
        if outcome == "succeeded":
            goal.succeed()
        elif outcome == "canceled" and goal.is_cancel_requested:
            goal.canceled()
        else:
            goal.abort()
        return result


def main() -> int:
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = None
    executor = SingleThreadedExecutor()
    try:
        node = MissionServer()
        executor.add_node(node)
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: node.stopping.set())
        while not node.stopping.is_set():
            node.check_reservation()
            executor.spin_once(timeout_sec=0.1)
        # The action worker cancels its owned goal before finalizing the recording.
        # Keep servicing action responses while it does so, even with a paused clock.
        while node.busy:
            node.check_reservation()
            executor.spin_once(timeout_sec=0.1)
        return 1 if node.faulted else 0
    finally:
        if node is not None:
            node.stopping.set()
            node.worker.shutdown(wait=True)
            executor.remove_node(node)
        executor.shutdown()
        if node is not None:
            node.server.destroy()
            node.navigator.destroy()
            node.destroy_node()
        rclpy.shutdown()
