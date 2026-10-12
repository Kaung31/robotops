"""Read-only, per-run ROS observation for final-pose validation."""

import math
import time

from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from tf2_msgs.msg import TFMessage

from experiment_runner.validation import pose_value


def stamp_ns(stamp) -> int:
    return stamp.sec * 10**9 + stamp.nanosec


class FinalObservation:
    def __init__(self, node, buffer):
        self.node, self.buffer = node, buffer
        self.transforms = {}
        self.localization = None
        # Volatile best-effort accepts both reliable and sensor-style publishers.
        # No retained AMCL sample is trusted as a current-trial observation.
        self.tf_subscription = node.create_subscription(TFMessage, "tf", self.on_tf, 100)
        self.pose_subscription = node.create_subscription(
            PoseWithCovarianceStamped, "amcl_pose", self.on_pose, qos_profile_sensor_data
        )

    def on_tf(self, message):
        for transform in message.transforms:
            pair = (transform.header.frame_id, transform.child_frame_id)
            if pair not in (("map", "odom"), ("odom", "base_link")):
                continue
            self.transforms[pair] = dict(
                stamp_ns=stamp_ns(transform.header.stamp),
                frame=pair[0],
                child=pair[1],
                received_monotonic=time.monotonic(),
            )

    def on_pose(self, message):
        try:
            if not all(math.isfinite(v) for v in message.pose.covariance):
                raise ValueError("Nonfinite localization covariance")
            self.localization = dict(
                stamp_ns=stamp_ns(message.header.stamp),
                frame=message.header.frame_id,
                child=None,
                received_monotonic=time.monotonic(),
                covariance=list(message.pose.covariance),
                pose=pose_value(message.pose.pose.position, message.pose.pose.orientation),
            )
        except ValueError as error:
            self.localization = {"error": str(error)}

    def capture(self, dispatch_ns: int, parameters: dict, clock_regressed: bool) -> dict:
        now = time.monotonic()

        def age(sample):
            value = dict(sample or {})
            if "received_monotonic" in value:
                value["receipt_age_s"] = now - value.pop("received_monotonic")
            return value

        result = dict(
            dispatch_ros_ns=dispatch_ns,
            observed_ros_ns=self.node.get_clock().now().nanoseconds,
            clock_regressed=clock_regressed,
            tf={},
            localization=age(self.localization),
            amcl_topic=self.node.resolve_topic_name("amcl_pose"),
            amcl_transform_tolerance_s=parameters.get("amcl", {}).get("transform_tolerance"),
        )
        for key, pair in (("map_odom", ("map", "odom")), ("odom_base", ("odom", "base_link"))):
            result["tf"][key] = age(self.transforms.get(pair))
        try:
            transform = self.buffer.lookup_transform("map", "base_link", Time())
            result["tf"]["map_base"] = dict(
                stamp_ns=stamp_ns(transform.header.stamp),
                frame="map",
                child="base_link",
                receipt_age_s=max(
                    result["tf"][key]["receipt_age_s"] for key in ("map_odom", "odom_base")
                ),
                pose=pose_value(transform.transform.translation, transform.transform.rotation),
            )
        except Exception as error:
            result["tf"]["map_base"] = {"error": str(error)}
        return result
