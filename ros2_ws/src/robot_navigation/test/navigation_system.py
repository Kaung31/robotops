"""Both Nav2 profiles use the same SLAM-produced map and public command path."""

import hashlib
import json
import math
import os
import signal
import subprocess
import time
from collections import deque
from pathlib import Path

import pytest
import rclpy
import yaml
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped, TwistStamped
from mapping_system import Session, create_saved_map, yaw
from nav2_msgs.action import ComputePathToPose, NavigateToPose
from nav_msgs.msg import Odometry
from nav_msgs.msg import Path as RosPath
from rcl_interfaces.srv import GetParameters
from rclpy.action import ActionClient
from rclpy.time import Time
from robot_navigation.navigation_config import PROFILES
from robotops_interfaces.msg import ContactEvidence


class NavigationSession(Session):
    def __init__(self, directory: Path, map_file: Path, profile: str):
        directory.mkdir()
        super().__init__(directory, "localization", map_file)
        self.domain_id += 1 + PROFILES.index(profile)
        self.profile = profile
        self.velocities, self.odometry = deque(maxlen=1000), deque(maxlen=50)

    def pipeline_command(self) -> list[str]:
        return [
            "ros2",
            "launch",
            "robot_navigation",
            "navigation.launch.py",
            f"map_file:={self.map_file}",
            f"profile:={self.profile}",
            "use_sim_time:=true",
        ]

    def __enter__(self):
        super().__enter__()
        self.subscriptions.extend(
            [
                self.node.create_subscription(
                    TwistStamped, "/cmd_vel/autonomy", lambda msg: self.velocities.append(msg), 10
                ),
                self.node.create_subscription(
                    Odometry, "/odom", lambda msg: self.odometry.append(msg), 10
                ),
            ]
        )
        self.teleop = self.node.create_publisher(TwistStamped, "/cmd_vel/teleop", 10)
        self.navigator = ActionClient(self.node, NavigateToPose, "/navigate_to_pose")
        self.planner = ActionClient(self.node, ComputePathToPose, "/compute_path_to_pose")
        return self

    def initialize(self):
        self.validate_sensors()
        self.active("amcl")
        self.active("map_server")
        self.wait(lambda: self.initial_pose.get_subscription_count() > 0, "No AMCL subscriber")
        pose = PoseWithCovarianceStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = self.node.get_clock().now().to_msg()
        pose.pose.pose.orientation.w = 1.0
        pose.pose.covariance[0] = pose.pose.covariance[7] = 0.05
        pose.pose.covariance[35] = 0.05
        self.initial_pose.publish(pose)
        self.wait(
            lambda: self.poses and self.buffer.can_transform("map", "base_link", Time()),
            "No localization",
        )
        for name in ("controller_server", "planner_server", "behavior_server", "bt_navigator"):
            self.active(name)
        assert self.navigator.wait_for_server(timeout_sec=10)
        assert self.planner.wait_for_server(timeout_sec=10)

    def parameter(self, node: str, name: str) -> str:
        client = self.node.create_client(GetParameters, f"/{node}/get_parameters")
        assert client.wait_for_service(timeout_sec=5)
        request = GetParameters.Request(names=[name])
        future = client.call_async(request)
        self.wait(future.done, f"No parameter {node}/{name}", 5)
        value = future.result().values[0].string_value
        self.node.destroy_client(client)
        return value

    def goal(self, x: float, y: float):
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = x, y
        goal.pose.pose.orientation.w = 1.0
        future = self.navigator.send_goal_async(goal)
        self.wait(future.done, "No goal response", 10)
        handle = future.result()
        assert handle.accepted
        return handle

    def spin_for(self, seconds: float, hold_teleop: bool = False) -> None:
        start = self.node.get_clock().now().nanoseconds
        deadline = time.monotonic() + max(15, seconds * 10)
        while (self.node.get_clock().now().nanoseconds - start) / 1e9 < seconds:
            assert time.monotonic() < deadline, "ROS clock stalled"
            if hold_teleop:
                zero = TwistStamped()
                zero.header.frame_id = "base_link"
                zero.header.stamp = self.node.get_clock().now().to_msg()
                self.teleop.publish(zero)
            rclpy.spin_once(self.node, timeout_sec=0.02)
            time.sleep(0.01)

    def assert_stopped(self) -> None:
        self.spin_for(1.5)
        assert self.odometry
        assert all(
            abs(msg.twist.twist.linear.x) < 0.025 and abs(msg.twist.twist.angular.z) < 0.04
            for msg in list(self.odometry)[-5:]
        ), "Robot did not stop"
        start = self.truth_pose().translation
        self.spin_for(0.5)
        end = self.truth_pose().translation
        assert math.hypot(end.x - start.x, end.y - start.y) < 0.03


@pytest.fixture(scope="module")
def saved_map(tmp_path_factory):
    path = create_saved_map(tmp_path_factory.mktemp("navigation-map"))
    return path


@pytest.mark.parametrize("profile", PROFILES)
def test_goal_cancel_and_arbitration(tmp_path: Path, saved_map: Path, profile: str) -> None:
    image = saved_map.parent / yaml.safe_load(saved_map.read_text())["image"]
    digests = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (saved_map, image)]
    with NavigationSession(tmp_path / profile, saved_map, profile) as session:
        session.initialize()
        expected = {
            "navfn_rpp": (
                "nav2_navfn_planner::NavfnPlanner",
                "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController",
            ),
            "smac_dwb": ("nav2_smac_planner::SmacPlanner2D", "dwb_core::DWBLocalPlanner"),
        }
        assert session.parameter("planner_server", "GridBased.plugin") == expected[profile][0]
        assert session.parameter("controller_server", "FollowPath.plugin") == expected[profile][1]
        session.validate_tf_publishers()
        assert session.node.count_publishers("/drive_controller/cmd_vel") == 1
        assert dict(session.node.get_topic_names_and_types())["/cmd_vel/autonomy"] == [
            "geometry_msgs/msg/TwistStamped"
        ]
        scan_subscribers = {
            endpoint.node_name
            for endpoint in session.node.get_subscriptions_info_by_topic("/scan")
        }
        assert {"amcl", "local_costmap", "global_costmap"} <= scan_subscribers
        assert any(
            endpoint.node_name == "global_costmap"
            for endpoint in session.node.get_subscriptions_info_by_topic("/map")
        )
        grid_message = session.maps[-1]
        grid = bytes(value + 1 for value in grid_message.data)
        # Pick a cell that SLAM actually marked occupied near the shelf. The
        # planner must reject it, exercising obstacle costs rather than bounds.
        info = grid_message.info
        cells = [
            (
                info.origin.position.x + (i % info.width + 0.5) * info.resolution,
                info.origin.position.y + (i // info.width + 0.5) * info.resolution,
            )
            for i, value in enumerate(grid_message.data)
            if value >= 65
        ]
        blocked = min(cells, key=lambda p: math.hypot(p[0] - 2.6, p[1] - 1.6))
        request = ComputePathToPose.Goal()
        request.goal.header.frame_id = "map"
        request.goal.pose.position.x, request.goal.pose.position.y = blocked
        request.goal.pose.orientation.w = 1.0
        request.planner_id = "GridBased"
        future = session.planner.send_goal_async(request)
        session.wait(future.done, "Planner did not accept request", 10)
        assert future.result().accepted
        planned = future.result().get_result_async()
        session.wait(planned.done, "Occupied-goal plan timed out", 10)
        assert planned.result().status == GoalStatus.STATUS_ABORTED
        assert not planned.result().result.path.poses
        session.assert_stopped()

        # Override a running goal with a stream of high-priority zero commands.
        handle = session.goal(1.4, 0.6)
        session.wait(
            lambda: any(abs(v.twist.linear.x) > 0.03 for v in session.velocities),
            "No nonzero autonomous control",
            30,
        )
        session.spin_for(1.5, hold_teleop=True)
        assert abs(session.odometry[-1].twist.twist.linear.x) < 0.025
        cancel = handle.cancel_goal_async()
        session.wait(cancel.done, "Cancellation timed out", 10)
        assert cancel.result().goals_canceling
        result = handle.get_result_async()
        session.wait(result.done, "Canceled goal did not finish", 10)
        assert result.result().status == GoalStatus.STATUS_CANCELED
        session.assert_stopped()

        handle = session.goal(1.4, 0.6)
        result = handle.get_result_async()
        session.wait(result.done, "Navigation goal timed out", 100)
        assert result.result().status == GoalStatus.STATUS_SUCCEEDED, result.result()
        session.assert_stopped()
        truth = session.truth_pose().translation
        error = math.hypot(truth.x - 1.4, truth.y - 0.6)
        assert error < 0.35, f"Independent goal position error: {error:.3f} m"
        heading_error = abs(yaw(session.truth_pose().rotation))
        assert heading_error < 0.4
        print(
            f"{profile}: succeeded; ground-truth goal error={error:.3f} m, "
            f"heading error={heading_error:.3f} rad"
        )
        assert len(session.velocities) > 10
        assert all(
            v.header.frame_id == "base_link"
            and Time.from_msg(v.header.stamp).nanoseconds > 0
            and math.isfinite(v.twist.linear.x)
            and math.isfinite(v.twist.angular.z)
            for v in session.velocities
        )

        # An out-of-map goal must terminate as failure, not report success or move.
        handle = session.goal(100.0, 100.0)
        result = handle.get_result_async()
        session.wait(result.done, "Out-of-map goal did not fail", 20)
        assert result.result().status == GoalStatus.STATUS_ABORTED
        session.assert_stopped()
        assert bytes(value + 1 for value in session.maps[-1].data) == grid
        session.validate_tf_publishers()
        # Stopping navigation during a goal must leave the independently running base stopped.
        session.velocities.clear()
        session.goal(0.0, 0.0)
        session.wait(
            lambda: any(
                abs(v.twist.angular.z) > 0.1 or abs(v.twist.linear.x) > 0.03
                for v in session.velocities
            ),
            "Return goal did not command motion",
            20,
        )
        pipeline = session.processes[-1]
        pipeline.send_signal(signal.SIGINT)
        assert pipeline.wait(timeout=15) == 0
        session.assert_stopped()
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (saved_map, image)] == digests


@pytest.mark.parametrize("profile", PROFILES)
def test_valid_path_retention_obstacle_replan_and_goal_update(
    tmp_path: Path, saved_map: Path, profile: str
) -> None:
    with NavigationSession(tmp_path / profile, saved_map, profile) as session:
        session.initialize()
        plans, contacts = [], []
        session.subscriptions.extend(
            [
                session.node.create_subscription(RosPath, "/plan", plans.append, 10),
                session.node.create_subscription(
                    ContactEvidence, "/validation/contacts", contacts.append, 100
                ),
            ]
        )
        assert Path(session.parameter("bt_navigator", "default_nav_to_pose_bt_xml")).name == (
            "navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml"
        )
        old = session.goal(1.4, 0.6)
        session.wait(lambda: bool(plans), "No initial global plan", 10)
        # Hold the robot using the public higher-priority mux input. Planning
        # continues; an unchanged valid path should survive multiple 1 Hz checks.
        session.spin_for(3.0, hold_teleop=True)
        assert len(plans) == 1, "Valid path was needlessly replaced"
        initial = plans[-1]
        point = initial.poses[len(initial.poses) * 2 // 3].pose.position
        sdf = (
            '<sdf version="1.9"><model name="replan_block"><static>true</static>'
            f'<pose>{point.x} {point.y} 0.3 0 0 0</pose><link name="body">'
            '<collision name="collision"><geometry><box><size>0.3 0.3 0.6</size>'
            '</box></geometry></collision><visual name="visual"><geometry><box>'
            "<size>0.3 0.3 0.6</size></box></geometry></visual></link></model></sdf>"
        )
        spawned = subprocess.run(
            [
                "gz",
                "service",
                "-s",
                "/world/mapping_lab/create",
                "--reqtype",
                "gz.msgs.EntityFactory",
                "--reptype",
                "gz.msgs.Boolean",
                "--timeout",
                "5000",
                "--req",
                "sdf: " + json.dumps(sdf),
            ],
            env=dict(os.environ, GZ_PARTITION=session.partition),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert spawned.returncode == 0 and "data: true" in spawned.stdout, spawned
        deadline = time.monotonic() + 20
        while len(plans) == 1 and time.monotonic() < deadline:
            session.spin_for(0.2, hold_teleop=True)
        assert len(plans) > 1, "New physical obstacle did not trigger replanning"
        assert [p.pose for p in plans[-1].poses] != [p.pose for p in initial.poses]
        # A changed active goal must not retain the old valid destination.
        changed = session.goal(0.0, 0.8)
        result = changed.get_result_async()
        session.wait(result.done, "Updated goal timed out", 100)
        assert result.result().status == GoalStatus.STATUS_SUCCEEDED
        previous = old.get_result_async()
        session.wait(previous.done, "Preempted goal did not terminate", 10)
        assert previous.result().status != GoalStatus.STATUS_SUCCEEDED
        session.assert_stopped()
        truth = session.truth_pose().translation
        assert math.hypot(truth.x, truth.y - 0.8) < 0.35
        assert len(contacts) >= 10 and all(f.coverage_complete for f in contacts)
        assert not any(f.contacts for f in contacts), "Unexpected physical contact"
