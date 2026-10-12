"""Optional ROS 2 adapter. Import only in an environment with the built workspace sourced."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from concurrent.futures import Future as ThreadFuture
from uuid import uuid4

from .models import (
    CommandResult,
    InitialPoseRequest,
    LifecycleNodeStatus,
    MapSnapshot,
    MissionCancellation,
    MissionRequest,
    MissionSubmission,
    NavigationReadiness,
    Pose2D,
    RuntimeMode,
    ScanPoint,
    TeleopRequest,
)
from .state import TelemetryStore


class RosGateway:
    def __init__(self, telemetry: TelemetryStore, runtime_mode: RuntimeMode):
        if runtime_mode not in (RuntimeMode.MOCK, RuntimeMode.SIM, RuntimeMode.REAL):
            raise ValueError("ROS live gateway requires mock, sim or real mode")
        self.telemetry = telemetry
        self._mode = runtime_mode
        self._thread: threading.Thread | None = None
        self._executor = None
        self._node = None
        self._goals: dict[str, object] = {}
        self._odom_seen = threading.Event()
        self._scan_seen = threading.Event()
        self._map_seen = threading.Event()
        self._amcl_seen = threading.Event()
        self._readiness_lock = threading.RLock()
        self._readiness = NavigationReadiness()

    @property
    def mode(self) -> RuntimeMode:
        return self._mode

    def start(self) -> None:
        if self._thread is not None:
            return
        ready: ThreadFuture[None] = ThreadFuture()
        self._thread = threading.Thread(target=self._spin, args=(ready,), daemon=True)
        self._thread.start()
        ready.result(timeout=10)
        self.telemetry.set_mode(self._mode)

    def _spin(self, ready: ThreadFuture[None]) -> None:
        try:
            import rclpy
            from geometry_msgs.msg import PoseWithCovarianceStamped, TwistStamped
            from lifecycle_msgs.srv import GetState
            from nav2_msgs.action import NavigateToPose
            from nav_msgs.msg import OccupancyGrid, Odometry, Path
            from rclpy.action import ActionClient
            from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
            from rclpy.executors import MultiThreadedExecutor
            from rclpy.node import Node
            from rclpy.parameter import Parameter
            from rclpy.qos import (
                DurabilityPolicy,
                QoSProfile,
                ReliabilityPolicy,
                qos_profile_sensor_data,
            )
            from robotops_interfaces.action import ExecuteMission
            from sensor_msgs.msg import LaserScan
            from std_srvs.srv import Trigger
            from tf2_ros import Buffer, TransformListener

            self._rclpy = rclpy
            self._ExecuteMission = ExecuteMission
            rclpy.init(args=None)
            node = Node(
                "robotops_web_gateway",
                parameter_overrides=[
                    Parameter("use_sim_time", value=self._mode == RuntimeMode.SIM)
                ],
            )
            self._node = node
            self._mission_client = ActionClient(node, ExecuteMission, "missions/execute")
            self._navigate_to_pose_client = ActionClient(node, NavigateToPose, "navigate_to_pose")
            map_qos = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            node.create_subscription(Odometry, "odom", self._odom, 10)
            node.create_subscription(OccupancyGrid, "map", self._map, map_qos)
            node.create_subscription(LaserScan, "scan", self._scan, qos_profile_sensor_data)
            node.create_subscription(Path, "plan", self._global_path, 10)
            node.create_subscription(Path, "local_plan", self._local_path, 10)
            amcl_pose_qos = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            node.create_subscription(
                PoseWithCovarianceStamped, "amcl_pose", self._localized_pose, amcl_pose_qos
            )
            self._initial_pose_type = PoseWithCovarianceStamped
            self._twist_type = TwistStamped
            self._initial_pose_publisher = node.create_publisher(
                PoseWithCovarianceStamped, "initialpose", 10
            )
            self._teleop_publisher = node.create_publisher(TwistStamped, "cmd_vel/teleop", 10)
            self._GetState = GetState
            self._Trigger = Trigger
            self._tf_buffer = Buffer(node=node)
            self._tf_listener = TransformListener(self._tf_buffer, node, spin_thread=False)
            lifecycle_names = (
                "amcl",
                "map_server",
                "controller_server",
                "local_costmap/local_costmap",
                "global_costmap/global_costmap",
                "behavior_server",
                "planner_server",
                "bt_navigator",
            )
            # Sensor callbacks copy cached map telemetry. Their default mutually
            # exclusive group must not exclude readiness response handling.
            self._readiness_callback_group = MutuallyExclusiveCallbackGroup()
            self._lifecycle_get_clients = {
                name: node.create_client(
                    GetState, f"/{name}/get_state", callback_group=self._readiness_callback_group
                )
                for name in lifecycle_names
            }
            self._lifecycle_manager_active_clients = {
                "nav2": node.create_client(
                    Trigger,
                    "/lifecycle_manager_nav2/is_active",
                    callback_group=self._readiness_callback_group,
                ),
            }
            executor = MultiThreadedExecutor(num_threads=2)
            self._executor = executor
            executor.add_node(node)
            ready.set_result(None)
            executor.spin()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                # A failed ROS executor is not fresh telemetry. Keep the last
                # payload for diagnosis, but force the connection state offline.
                self.telemetry.mark_disconnected(self._mode)
        finally:
            if self._node is not None:
                self._node.destroy_node()
            if hasattr(self, "_rclpy") and self._rclpy.ok():
                self._rclpy.shutdown()

    @staticmethod
    def _yaw(q) -> float:
        return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))

    def _odom(self, msg) -> None:
        self._odom_seen.set()
        p = msg.pose.pose.position
        self.telemetry.publish(
            runtime_mode=self._mode,
            source_timestamp_ns=str(
                msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
            ),
            pose=Pose2D(x=p.x, y=p.y, yaw=self._yaw(msg.pose.pose.orientation)),
        )

    def _map(self, msg) -> None:
        self._map_seen.set()
        origin = msg.info.origin
        self.telemetry.publish(
            runtime_mode=self._mode,
            source_timestamp_ns=str(
                msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
            ),
            map=MapSnapshot(
                frame_id=msg.header.frame_id or "map",
                width=msg.info.width,
                height=msg.info.height,
                resolution=msg.info.resolution,
                origin=Pose2D(
                    x=origin.position.x,
                    y=origin.position.y,
                    yaw=self._yaw(origin.orientation),
                ),
                data=list(msg.data),
            ),
        )

    @staticmethod
    def _path_points(msg) -> list[Pose2D]:
        return [
            Pose2D(
                x=pose.pose.position.x,
                y=pose.pose.position.y,
                yaw=RosGateway._yaw(pose.pose.orientation),
            )
            for pose in msg.poses
        ]

    def _global_path(self, msg) -> None:
        self.telemetry.publish(runtime_mode=self._mode, global_path=self._path_points(msg))

    def _local_path(self, msg) -> None:
        self.telemetry.publish(runtime_mode=self._mode, local_path=self._path_points(msg))

    def _localized_pose(self, msg) -> None:
        self._amcl_seen.set()
        p = msg.pose.pose.position
        self.telemetry.publish(
            runtime_mode=self._mode,
            source_timestamp_ns=str(
                msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
            ),
            pose=Pose2D(x=p.x, y=p.y, yaw=self._yaw(msg.pose.pose.orientation)),
        )

    def _scan(self, msg) -> None:
        self._scan_seen.set()
        # Downsample to bound WebSocket payload size; the full LaserScan stays in ROS/MCAP.
        stride = max(1, len(msg.ranges) // 360)
        points: list[ScanPoint] = []
        for i in range(0, len(msg.ranges), stride):
            r = msg.ranges[i]
            if not math.isfinite(r) or r < msg.range_min or r > msg.range_max:
                continue
            angle = msg.angle_min + i * msg.angle_increment
            points.append(ScanPoint(x=r * math.cos(angle), y=r * math.sin(angle)))
        self.telemetry.publish(runtime_mode=self._mode, scan=points)

    async def submit_mission(self, request: MissionRequest) -> MissionSubmission:
        if self._mode == RuntimeMode.REPLAY:
            return MissionSubmission(
                request_id="replay", accepted=False, message="Replay is read-only"
            )
        if self._node is None:
            return MissionSubmission(
                request_id="unavailable", accepted=False, message="ROS unavailable"
            )
        from geometry_msgs.msg import PoseStamped

        if not self._mission_client.server_is_ready():
            return MissionSubmission(
                request_id="unavailable",
                accepted=False,
                message="Mission server unavailable",
            )
        goal = self._ExecuteMission.Goal(label=request.label, record=request.record)
        for waypoint in request.waypoints:
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.pose.position.x = waypoint.x
            pose.pose.position.y = waypoint.y
            pose.pose.orientation.z = math.sin(waypoint.yaw / 2)
            pose.pose.orientation.w = math.cos(waypoint.yaw / 2)
            goal.waypoints.append(pose)
        request_id = uuid4().hex
        ros_future = self._mission_client.send_goal_async(
            goal, feedback_callback=lambda feedback: self._feedback(feedback.feedback)
        )
        handle = await self._await_ros(ros_future, 10.0)
        if not handle.accepted:
            return MissionSubmission(
                request_id=request_id, accepted=False, message="Mission rejected"
            )
        self._goals[request_id] = handle
        result_future = handle.get_result_async()
        result_future.add_done_callback(
            lambda future, owned_request_id=request_id: self._mission_result(
                owned_request_id, future
            )
        )
        return MissionSubmission(request_id=request_id, accepted=True, message="Mission accepted")

    def _feedback(self, feedback) -> None:
        self.telemetry.publish(
            runtime_mode=self._mode,
            mission_state=feedback.state,
            mission_run_id=feedback.run_id or None,
        )

    def _mission_result(self, request_id: str, future) -> None:
        try:
            wrapped = future.result()
            result = wrapped.result
            self.telemetry.publish(
                runtime_mode=self._mode,
                mission_state=result.outcome,
                mission_run_id=result.run_id or None,
            )
        except Exception:
            self.telemetry.publish(runtime_mode=self._mode, mission_state="result_unavailable")
        finally:
            self._goals.pop(request_id, None)

    async def cancel_mission(self, request_id: str) -> MissionCancellation:
        handle = self._goals.get(request_id)
        if handle is None:
            return MissionCancellation(
                request_id=request_id,
                confirmed=False,
                message="Unknown mission request",
            )
        result = await self._await_ros(handle.cancel_goal_async(), 10.0)
        confirmed = bool(result.goals_canceling)
        if confirmed:
            self._goals.pop(request_id, None)
        return MissionCancellation(
            request_id=request_id,
            confirmed=confirmed,
            message="Cancellation accepted" if confirmed else "Cancellation not confirmed",
        )

    async def _await_ros(self, future, timeout: float):
        deadline = asyncio.get_running_loop().time() + timeout
        while not future.done():
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("ROS response timed out")
            await asyncio.sleep(0.02)
        return future.result()

    async def set_initial_pose(self, request: InitialPoseRequest) -> CommandResult:
        if self._node is None or not hasattr(self, "_initial_pose_publisher"):
            return CommandResult(accepted=False, message="ROS unavailable")
        msg = self._initial_pose_type()
        msg.header.frame_id = "map"
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.pose.position.x = request.x
        msg.pose.pose.position.y = request.y
        msg.pose.pose.orientation.z = math.sin(request.yaw / 2)
        msg.pose.pose.orientation.w = math.cos(request.yaw / 2)
        # Conservative planar covariance: x/y ~0.25m sigma, yaw ~15deg sigma.
        msg.pose.covariance[0] = 0.0625
        msg.pose.covariance[7] = 0.0625
        msg.pose.covariance[35] = math.radians(15.0) ** 2
        self._initial_pose_publisher.publish(msg)
        return CommandResult(accepted=True, message="Initial pose published")

    async def teleop(self, request: TeleopRequest) -> CommandResult:
        if self._node is None or not hasattr(self, "_teleop_publisher"):
            return CommandResult(accepted=False, message="ROS unavailable")
        msg = self._twist_type()
        msg.header.frame_id = "base_link"
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.twist.linear.x = request.linear_x
        msg.twist.angular.z = request.angular_z
        self._teleop_publisher.publish(msg)
        return CommandResult(accepted=True, message="Teleop command published")

    def reset_navigation_readiness(self) -> None:
        self._odom_seen.clear()
        self._scan_seen.clear()
        self._map_seen.clear()
        self._amcl_seen.clear()
        with self._readiness_lock:
            self._readiness = NavigationReadiness(
                ready=False,
                phase="starting",
                message="Waiting for a fresh navigation stack",
                updated_at_ns=str(time.time_ns()),
            )

    async def _wait_event(self, event: threading.Event, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while not event.is_set():
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.1)
        return True

    def _can_transform(self, target: str, source: str) -> bool:
        if not hasattr(self, "_tf_buffer"):
            return False
        try:
            from rclpy.duration import Duration
            from rclpy.time import Time

            return bool(
                self._tf_buffer.can_transform(
                    target, source, Time(), timeout=Duration(seconds=0.05)
                )
            )
        except Exception:
            return False

    def _tf_ready(self) -> bool:
        return self._can_transform("map", "base_link")

    def _odom_tf_ready(self) -> bool:
        return self._can_transform("odom", "base_link")

    async def _wait_transform(self, target: str, source: str, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while not self._can_transform(target, source):
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.1)
        return True

    async def _wait_tf(self, timeout: float) -> bool:
        return await self._wait_transform("map", "base_link", timeout)

    async def _wait_service(self, client, timeout: float = 3.0) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while not client.service_is_ready():
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(0.1)
        return True

    async def _lifecycle_state(self, name: str) -> str:
        client = getattr(self, "_lifecycle_get_clients", {}).get(name)
        if client is None or not await self._wait_service(client, 1.5):
            return "unavailable"
        future = client.call_async(self._GetState.Request())
        try:
            result = await self._await_ros(future, 2.0)
        except TimeoutError:
            return "unavailable"
        return result.current_state.label or "unknown"

    async def _manager_is_active(self, manager: str, timeout: float = 3.0) -> bool:
        client = getattr(self, "_lifecycle_manager_active_clients", {}).get(manager)
        if client is None or not await self._wait_service(client, timeout):
            return False
        future = client.call_async(self._Trigger.Request())
        try:
            response = await self._await_ros(future, timeout)
        except TimeoutError:
            return False
        return bool(response.success)

    def _nav_action_ready(self) -> bool:
        client = getattr(self, "_navigate_to_pose_client", None)
        if client is None:
            return False
        try:
            return bool(client.server_is_ready())
        except Exception:
            return False

    async def navigation_readiness(self) -> NavigationReadiness:
        names = (
            "map_server",
            "amcl",
            "controller_server",
            "behavior_server",
            "planner_server",
            "bt_navigator",
        )

        # Nav2's lifecycle managers own startup via autostart. RobotOps only
        # observes functional readiness. This avoids a second lifecycle
        # controller racing Nav2's own manager.
        nav2_active = await self._manager_is_active("nav2", 0.35)
        raw_states = {name: await self._lifecycle_state(name) for name in names}

        odom_available = self._odom_seen.is_set()
        scan_available = self._scan_seen.is_set()
        odom_to_base = self._odom_tf_ready()
        map_available = self._map_seen.is_set()
        map_to_base = self._tf_ready()
        localized = map_to_base
        nav_action_ready = self._nav_action_ready()

        # If service-state diagnostics are temporarily unavailable, infer only
        # display state from stronger functional signals. They are not readiness
        # gates.
        if nav2_active:
            for name in names:
                if raw_states[name] == "unavailable":
                    raw_states[name] = "active"
        else:
            if map_available and localized:
                for name in ("map_server", "amcl"):
                    if raw_states[name] == "unavailable":
                        raw_states[name] = "operational"
            if nav_action_ready:
                for name in (
                    "controller_server",
                    "behavior_server",
                    "planner_server",
                    "bt_navigator",
                ):
                    if raw_states[name] == "unavailable":
                        raw_states[name] = "operational"
        states = [LifecycleNodeStatus(name=name, state=raw_states[name]) for name in names]

        # navigate_to_pose is hosted by bt_navigator. With a single ordered Nav2
        # lifecycle manager, its availability means the earlier controller,
        # planner and behavior servers have already activated successfully.
        ready = (
            odom_available
            and scan_available
            and odom_to_base
            and map_available
            and localized
            and nav_action_ready
        )
        if ready:
            phase = "ready"
            message = "Navigation is ready"
        elif not odom_available:
            phase = "waiting_odom"
            message = "Waiting for robot odometry"
        elif not scan_available:
            phase = "waiting_scan"
            message = "Waiting for LiDAR scan"
        elif not odom_to_base:
            phase = "waiting_odom_tf"
            message = "Waiting for odom → base_link transform"
        elif not map_available:
            phase = "waiting_map"
            message = "Waiting for the saved map"
        elif not localized:
            phase = "waiting_localization"
            message = "Waiting for AMCL localization"
        elif not nav_action_ready:
            phase = "starting_navigation"
            message = "Waiting for Nav2 navigate_to_pose action"
        else:
            phase = "activating"
            message = "Waiting for Nav2 readiness"
        readiness = NavigationReadiness(
            ready=ready,
            phase=phase,
            message=message,
            odom_available=odom_available,
            scan_available=scan_available,
            odom_to_base=odom_to_base,
            map_available=map_available,
            localized=localized,
            map_to_base=map_to_base,
            lifecycle_nodes=states,
            updated_at_ns=str(time.time_ns()),
        )
        with self._readiness_lock:
            self._readiness = readiness
        return readiness

    async def prepare_navigation(self, request: InitialPoseRequest) -> NavigationReadiness:
        del request  # Simulation spawn pose is supplied to AMCL at launch.
        if self._mode != RuntimeMode.SIM:
            return NavigationReadiness(
                phase="manual_localization",
                message="Automatic localization is enabled for simulation only",
                updated_at_ns=str(time.time_ns()),
            )

        # Lifecycle managers autostart the stack. RobotOps waits for fresh robot
        # data, localization TF and the functional Nav2 action server only.
        await self._wait_event(self._odom_seen, 25.0)
        await self._wait_event(self._scan_seen, 25.0)
        await self._wait_transform("odom", "base_link", 15.0)
        await self._wait_event(self._map_seen, 20.0)
        await self._wait_tf(25.0)

        deadline = asyncio.get_running_loop().time() + 25.0
        while not self._nav_action_ready():
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.1)
        return await self.navigation_readiness()

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(timeout_sec=5.0)
        if self._thread is not None:
            self._thread.join(timeout=6.0)
