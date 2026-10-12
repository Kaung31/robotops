"""Exercise installed launch resources and ROS topic/TF contracts on Jazzy."""

import math
import time
import unittest
from pathlib import Path

import launch_testing
import launch_testing.actions
import launch_testing.asserts
import rclpy
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import PushRosNamespace
from rcl_interfaces.srv import GetParameters
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from tf2_msgs.msg import TFMessage


def generate_test_description():
    path = Path(get_package_share_directory("robot_description")) / "launch/description.launch.py"

    def include(namespace: str, **arguments: str) -> GroupAction:
        return GroupAction(
            [
                PushRosNamespace(namespace),
                IncludeLaunchDescription(
                    PythonLaunchDescriptionSource(str(path)),
                    launch_arguments=arguments.items(),
                ),
            ]
        )

    return LaunchDescription(
        [
            include("external"),
            include("preview", publish_preview_joint_states="true"),
            include("clocked", use_sim_time="true", publish_preview_joint_states="true"),
            launch_testing.actions.ReadyToTest(),
        ]
    )


class TestDescription(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rclpy.init()
        cls.node = rclpy.create_node("description_contract_test")

    @classmethod
    def tearDownClass(cls):
        cls.node.destroy_node()
        rclpy.shutdown()

    def wait_for(self, predicate, message: str, timeout: float = 15.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.1)
            if predicate():
                return
        self.fail(message)

    def test_topics_tf_and_clock_parameters(self):
        durable = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        # Wait for the publisher before subscribing: this checks late-joiner durability.
        self.wait_for(
            lambda: self.node.count_publishers("/external/tf_static") == 1,
            "Missing namespaced static TF publisher",
        )
        static, dynamic, descriptions, preview_states = {}, {}, [], []
        subscriptions = [
            self.node.create_subscription(
                TFMessage,
                "/external/tf_static",
                lambda msg: static.update({tf.child_frame_id: tf for tf in msg.transforms}),
                durable,
            ),
            self.node.create_subscription(
                TFMessage,
                "/external/tf",
                lambda msg: dynamic.update({tf.child_frame_id: tf for tf in msg.transforms}),
                10,
            ),
            self.node.create_subscription(
                String, "/external/robot_description", descriptions.append, durable
            ),
            self.node.create_subscription(
                JointState, "/preview/joint_states", preview_states.append, qos_profile_sensor_data
            ),
        ]
        self.wait_for(
            lambda: {"chassis_link", "caster_link", "lidar_link", "imu_link"} <= static.keys()
            and descriptions
            and preview_states,
            "Description, static TF, or opt-in preview joint states were not received",
        )
        self.assertEqual(set(static), {"chassis_link", "caster_link", "lidar_link", "imu_link"})
        self.assertTrue(all(tf.header.frame_id == "base_link" for tf in static.values()))
        self.assertIn('name="robotops_base"', descriptions[-1].data)
        self.assertEqual(set(preview_states[-1].name), {"left_wheel_joint", "right_wheel_joint"})
        self.assertTrue(all(value == 0.0 for value in preview_states[-1].position))
        self.assertEqual(self.node.count_publishers("/external/joint_states"), 0)
        self.assertFalse(dynamic, "Default launch must not invent wheel states")

        publisher = self.node.create_publisher(JointState, "/external/joint_states", 10)
        self.wait_for(lambda: publisher.get_subscription_count() > 0, "No joint-state subscriber")

        def send_and_check():
            msg = JointState()
            msg.header.stamp = self.node.get_clock().now().to_msg()
            msg.name = ["left_wheel_joint", "right_wheel_joint"]
            msg.position = [0.6, -0.4]
            publisher.publish(msg)
            return {"left_wheel_link", "right_wheel_link"} <= dynamic.keys()

        self.wait_for(send_and_check, "Joint states did not produce dynamic wheel TF")
        for side, angle in (("left", 0.6), ("right", -0.4)):
            tf = dynamic[f"{side}_wheel_link"]
            self.assertEqual(tf.header.frame_id, "base_link")
            self.assertAlmostEqual(tf.transform.rotation.y, math.sin(angle / 2), places=6)
            self.assertAlmostEqual(tf.transform.rotation.w, math.cos(angle / 2), places=6)

        for target, expected in (
            ("external/robot_state_publisher", False),
            ("clocked/robot_state_publisher", True),
            ("clocked/preview_joint_state_publisher", True),
        ):
            client = self.node.create_client(GetParameters, f"/{target}/get_parameters")
            self.assertTrue(client.wait_for_service(timeout_sec=10))
            future = client.call_async(GetParameters.Request(names=["use_sim_time"]))
            self.wait_for(future.done, f"No parameter response from {target}")
            self.assertEqual(future.result().values[0].bool_value, expected)
            self.node.destroy_client(client)
        self.node.destroy_publisher(publisher)
        for subscription in subscriptions:
            self.node.destroy_subscription(subscription)


@launch_testing.post_shutdown_test()
class TestShutdown(unittest.TestCase):
    def test_clean_exit(self, proc_info):
        launch_testing.asserts.assertExitCodes(proc_info)
