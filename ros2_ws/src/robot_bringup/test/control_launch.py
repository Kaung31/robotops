"""One live command contract exercised unchanged on mock and Gazebo backends."""

import math
import os
import time
import unittest
from pathlib import Path

import launch_testing
import launch_testing.actions
import launch_testing.asserts
import rclpy
from ament_index_python.packages import get_package_share_directory
from controller_manager_msgs.srv import ListControllers, ListHardwareInterfaces
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from geometry_msgs.msg import TwistStamped
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from nav_msgs.msg import Odometry
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState
from tf2_msgs.msg import TFMessage

MODE = os.environ.get("ROBOTOPS_TEST_MODE", "mock")


def generate_test_description():
    path = Path(get_package_share_directory("robot_bringup")) / "launch/robot.launch.py"
    return LaunchDescription(
        [
            SetEnvironmentVariable("GZ_PARTITION", f"robotops_test_{os.getpid()}"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(str(path)),
                launch_arguments={
                    "mode": MODE,
                    "gui": "false",
                    "sensors": "false",
                    "diagnostics": "true",
                }.items(),
            ),
            launch_testing.actions.ReadyToTest(),
        ]
    )


def yaw(rotation) -> float:
    return math.atan2(
        2 * (rotation.w * rotation.z + rotation.x * rotation.y),
        1 - 2 * (rotation.y**2 + rotation.z**2),
    )


class TestControlContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node(
            "control_contract_test",
            parameter_overrides=[Parameter("use_sim_time", value=MODE == "sim")],
        )

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def wait(self, predicate, reason: str, timeout: float = 30.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.05)
            if predicate():
                return
        self.fail(reason)

    def service(self, service_type, name):
        client = self.node.create_client(service_type, name)
        self.assertTrue(client.wait_for_service(timeout_sec=50), name)
        future = client.call_async(service_type.Request())
        self.wait(future.done, f"No response from {name}")
        result = future.result()
        self.node.destroy_client(client)
        return result

    def test_control_contract(self):
        controllers = self.service(ListControllers, "/controller_manager/list_controllers")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and {
            c.name for c in controllers.controller if c.state == "active"
        } != {"drive_controller", "joint_state_broadcaster"}:
            rclpy.spin_once(self.node, timeout_sec=0.1)
            controllers = self.service(ListControllers, "/controller_manager/list_controllers")
        self.assertEqual(
            {c.name for c in controllers.controller if c.state == "active"},
            {"drive_controller", "joint_state_broadcaster"},
        )

        interfaces = self.service(
            ListHardwareInterfaces, "/controller_manager/list_hardware_interfaces"
        )
        self.assertEqual(
            {i.name for i in interfaces.command_interfaces if i.is_claimed},
            {"left_wheel_joint/velocity", "right_wheel_joint/velocity"},
        )
        self.assertEqual(
            {i.name for i in interfaces.state_interfaces if i.is_available},
            {
                f"{side}_wheel_joint/{state}"
                for side in ("left", "right")
                for state in ("position", "velocity")
            },
        )
        odom, joints, transforms, truth, output = [], [], [], [], []
        subscriptions = [
            self.node.create_subscription(Odometry, "/odom", odom.append, 10),
            self.node.create_subscription(
                JointState, "/joint_states", joints.append, qos_profile_sensor_data
            ),
            self.node.create_subscription(TFMessage, "/tf", transforms.append, 10),
            self.node.create_subscription(
                TwistStamped, "/drive_controller/cmd_vel", output.append, 10
            ),
        ]
        if MODE == "sim":
            subscriptions.append(
                self.node.create_subscription(
                    TFMessage, "/simulation/ground_truth", truth.append, 10
                )
            )
        publishers = {
            source: self.node.create_publisher(TwistStamped, f"/cmd_vel/{source}", 10)
            for source in ("test", "teleop", "autonomy")
        }
        self.wait(
            lambda: odom and joints and transforms and self.node.get_clock().now().nanoseconds > 0,
            "Missing odometry/joint states/TF/clock",
        )
        self.wait(
            lambda: all(p.get_subscription_count() == 1 for p in publishers.values()),
            "Command sources must each feed the mux",
        )
        self.assertEqual(self.node.count_publishers("/drive_controller/cmd_vel"), 1)
        self.assertEqual(self.node.count_publishers("/odom"), 1)
        self.assertEqual(self.node.count_publishers("/joint_states"), 1)
        self.assertEqual(odom[-1].header.frame_id, "odom")
        self.assertEqual(odom[-1].child_frame_id, "base_link")
        self.assertEqual(set(joints[-1].name), {"left_wheel_joint", "right_wheel_joint"})

        def drive(seconds, sources, stale=False, future=False):
            start = self.node.get_clock().now().nanoseconds
            wall_end = time.monotonic() + max(20, seconds * 5)
            while (self.node.get_clock().now().nanoseconds - start) / 1e9 < seconds:
                self.assertLess(time.monotonic(), wall_end, "ROS clock stopped advancing")
                for source, (linear, angular) in sources.items():
                    msg = TwistStamped()
                    msg.header.stamp = self.node.get_clock().now().to_msg()
                    if stale:
                        msg.header.stamp.sec = max(1, msg.header.stamp.sec - 5)
                    if future:
                        msg.header.stamp.sec += 60
                    msg.header.frame_id = "base_link"
                    msg.twist.linear.x, msg.twist.angular.z = linear, angular
                    publishers[source].publish(msg)
                rclpy.spin_once(self.node, timeout_sec=0.04)
                # Bound the publisher rate even when queued telemetry is immediately ready.
                time.sleep(0.01)

        def model_pose():
            for message in reversed(truth):
                for transform in message.transforms:
                    if transform.child_frame_id == "robotops":
                        return transform.transform
            return None

        drive(0.6, {})  # let initial contacts and wheel feedback settle
        if MODE == "sim":
            self.wait(lambda: model_pose() is not None, "Missing simulator model truth")
            truth_start = model_pose()
        start = odom[-1].pose.pose
        initial_joints = list(joints[-1].position)
        drive(2.0, {"test": (0.2, 0.0)})
        self.assertGreater(odom[-1].pose.pose.position.x - start.position.x, 0.20)
        self.assertTrue(
            all(
                end > begin + 1.0
                for begin, end in zip(initial_joints, joints[-1].position, strict=False)
            )
        )
        if MODE == "sim":
            self.assertGreater(model_pose().translation.x - truth_start.translation.x, 0.15)

        # Fresh high-priority teleop zeros override a still-active test command.
        drive(1.0, {"test": (0.2, 0.0), "teleop": (0.0, 0.0)})
        self.assertAlmostEqual(output[-1].twist.linear.x, 0.0)
        self.assertLess(abs(odom[-1].twist.twist.linear.x), 0.02)
        # Once teleop expires, the continuing lower-priority source regains control.
        drive(1.0, {"test": (0.2, 0.0)})
        self.assertGreater(odom[-1].twist.twist.linear.x, 0.1)
        drive(1.2, {})
        self.assertLess(abs(odom[-1].twist.twist.linear.x), 0.02)
        self.assertTrue(all(abs(v) < 0.1 for v in joints[-1].velocity))

        # Fresh transport with stale stamps must not defeat the controller watchdog.
        drive(0.6, {"test": (0.2, 0.0)}, stale=True)
        self.assertLess(abs(odom[-1].twist.twist.linear.x), 0.02)
        drive(0.6, {"test": (0.2, 0.0)}, future=True)
        self.assertLess(abs(odom[-1].twist.twist.linear.x), 0.02)
        drive(0.6, {"test": (float("nan"), 0.0)})
        self.assertLess(abs(odom[-1].twist.twist.linear.x), 0.02)
        self.assertEqual(output[-1].twist.linear.x, 0.0)
        heading = yaw(odom[-1].pose.pose.orientation)
        if MODE == "sim":
            truth_heading = yaw(model_pose().rotation)
        drive(2.0, {"test": (0.0, 0.5)})
        self.assertGreater(yaw(odom[-1].pose.pose.orientation) - heading, 0.5)
        if MODE == "sim":
            self.assertGreater(yaw(model_pose().rotation) - truth_heading, 0.35)
        drive(1.2, {})
        self.assertLess(abs(odom[-1].twist.twist.angular.z), 0.03)
        base_transforms = [
            tf for msg in transforms for tf in msg.transforms if tf.child_frame_id == "base_link"
        ]
        self.assertTrue(base_transforms)
        self.assertTrue(all(tf.header.frame_id == "odom" for tf in base_transforms))
        # Only controller_manager/drive_controller and robot_state_publisher own /tf.
        self.assertEqual(self.node.count_publishers("/tf"), 2)
        for publisher in publishers.values():
            self.node.destroy_publisher(publisher)
        for subscription in subscriptions:
            self.node.destroy_subscription(subscription)

    def test_opt_in_diagnostics_observe_odometry_only(self):
        received = []
        expected = {"robotops/clock", "robotops/freshness/odom"}

        def observe(message):
            statuses = [item for item in message.status if item.name in expected]
            if statuses:
                received.append(statuses)

        subscription = self.node.create_subscription(DiagnosticArray, "diagnostics", observe, 10)
        try:
            self.wait(
                lambda: bool(received)
                and {item.name for item in received[-1]} == expected
                and all(item.level == DiagnosticStatus.OK for item in received[-1]),
                "No fresh odometry diagnostics",
                timeout=30,
            )
            self.assertEqual(
                {item.name for item in received[-1]},
                expected,
            )
        finally:
            self.node.destroy_subscription(subscription)


@launch_testing.post_shutdown_test()
class TestShutdown(unittest.TestCase):
    def test_clean_exit(self, proc_info):
        launch_testing.asserts.assertExitCodes(proc_info)
