"""Headless end-to-end proof: sensor data -> SLAM -> saved map -> restarted AMCL."""

import hashlib
import math
import os
import signal
import subprocess
import time
from collections import deque
from pathlib import Path
from uuid import uuid4

import rclpy
import yaml
from geometry_msgs.msg import PoseWithCovarianceStamped, TwistStamped
from lifecycle_msgs.srv import GetState
from nav_msgs.msg import OccupancyGrid
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import Imu, LaserScan
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer, TransformListener


def yaw(q) -> float:
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y**2 + q.z**2))


class Session:
    """Own processes, ROS subscriptions and cleanup for one robot/map session."""

    def __init__(self, directory: Path, workflow: str, map_file: Path | None = None):
        self.directory = directory
        self.domain_id = int(os.environ.get("ROS_DOMAIN_ID", "0"))
        self.partition = f"robotops_map_{os.getpid()}_{uuid4().hex}"
        self.workflow = workflow
        self.map_file = map_file
        self.processes = []
        self.logs = []
        self.scan, self.imu, self.maps = deque(maxlen=20), deque(maxlen=100), deque(maxlen=5)
        self.poses, self.truth = deque(maxlen=20), deque(maxlen=20)

    def __enter__(self):
        rclpy.init(domain_id=self.domain_id)
        self.node = rclpy.create_node(
            "mapping_system_test", parameter_overrides=[Parameter("use_sim_time", value=True)]
        )
        self.buffer = Buffer(node=self.node)
        self.listener = TransformListener(self.buffer, self.node)
        durable = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.subscriptions = [
            self.node.create_subscription(
                LaserScan, "/scan", lambda msg: self.scan.append(msg), qos_profile_sensor_data
            ),
            self.node.create_subscription(
                Imu, "/imu/data", lambda msg: self.imu.append(msg), qos_profile_sensor_data
            ),
            self.node.create_subscription(
                OccupancyGrid, "/map", lambda msg: self.maps.append(msg), durable
            ),
            self.node.create_subscription(
                PoseWithCovarianceStamped,
                "/amcl_pose",
                lambda msg: self.poses.append(msg),
                durable,
            ),
            self.node.create_subscription(
                TFMessage, "/simulation/ground_truth", lambda msg: self.truth.append(msg), 10
            ),
        ]
        self.command = self.node.create_publisher(TwistStamped, "/cmd_vel/test", 10)
        self.initial_pose = self.node.create_publisher(
            PoseWithCovarianceStamped, "/initialpose", 10
        )
        self.start(
            "base",
            [
                "ros2",
                "launch",
                "robot_bringup",
                "robot.launch.py",
                "mode:=sim",
                "world:=mapping_lab",
                "sensors:=true",
                "gui:=false",
                "headless_rendering:=false",
            ],
        )
        self.start("pipeline", self.pipeline_command())
        return self

    def pipeline_command(self) -> list[str]:
        args = [
            "ros2",
            "launch",
            "robot_navigation",
            "map.launch.py",
            f"workflow:={self.workflow}",
            "use_sim_time:=true",
        ]
        if self.map_file:
            args.append(f"map_file:={self.map_file}")
        return args

    def start(self, label: str, command: list[str]) -> None:
        log = self.directory / f"{self.workflow}-{label}.log"
        stream = log.open("w")
        self.logs.append((log, stream))
        env = dict(
            os.environ,
            GZ_PARTITION=self.partition,
            ROS_DOMAIN_ID=str(self.domain_id),
            LIBGL_ALWAYS_SOFTWARE="1",
            # Ogre probes EGL GPUs even in GLX mode; use only the Xvfb software renderer.
            __EGL_VENDOR_LIBRARY_FILENAMES="/dev/null",
        )
        self.processes.append(
            subprocess.Popen(
                command, stdout=stream, stderr=subprocess.STDOUT, env=env, start_new_session=True
            )
        )

    def __exit__(self, exc_type, _exc, _tb):
        statuses = []
        for process in reversed(self.processes):
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                statuses.append(process.wait(timeout=15))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
                statuses.append(-9)
        self.listener.unregister()
        self.node.destroy_node()
        rclpy.shutdown()
        for path, stream in self.logs:
            stream.close()
            if exc_type or any(status != 0 for status in statuses):
                print(f"\n--- {path} ---\n{path.read_text()[-16000:]}")
        if not exc_type:
            assert all(status == 0 for status in statuses), f"Shutdown exit codes: {statuses}"
            for path, _stream in self.logs:
                assert "process has died" not in path.read_text(), path.read_text()[-12000:]

    def wait(self, predicate, reason: str, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert all(p.poll() is None for p in self.processes), "A launch process exited early"
            rclpy.spin_once(self.node, timeout_sec=0.05)
            if predicate():
                return
        raise AssertionError(reason)

    def active(self, name: str) -> None:
        client = self.node.create_client(GetState, f"/{name}/get_state")
        assert client.wait_for_service(timeout_sec=45), name
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            future = client.call_async(GetState.Request())
            self.wait(future.done, f"No lifecycle reply from {name}", 5)
            if future.result().current_state.id == 3:
                self.node.destroy_client(client)
                return
            rclpy.spin_once(self.node, timeout_sec=0.1)
        raise AssertionError(f"{name} did not activate")

    def drive(self, seconds: float, linear: float = 0.0, angular: float = 0.0) -> None:
        start = self.node.get_clock().now().nanoseconds
        deadline = time.monotonic() + max(30, seconds * 8)
        while (self.node.get_clock().now().nanoseconds - start) / 1e9 < seconds:
            assert time.monotonic() < deadline, "ROS clock stalled"
            msg = TwistStamped()
            msg.header.stamp = self.node.get_clock().now().to_msg()
            msg.header.frame_id = "base_link"
            msg.twist.linear.x, msg.twist.angular.z = linear, angular
            self.command.publish(msg)
            rclpy.spin_once(self.node, timeout_sec=0.02)
            time.sleep(0.005)

    def validate_tf_publishers(self) -> None:
        expected = {"robot_state_publisher", "drive_controller"}
        expected.add("slam_toolbox" if self.workflow == "mapping" else "amcl")
        publishers = self.node.get_publishers_info_by_topic("/tf")
        names = [endpoint.node_name for endpoint in publishers]
        # SLAM Toolbox creates multiple TF endpoints within the same node.
        assert set(names) == expected, names
        nodes = self.node.get_node_names()
        assert all(nodes.count(name) == 1 for name in expected), nodes
        assert self.buffer.can_transform("map", "odom", Time())
        assert self.buffer.can_transform("odom", "base_link", Time())

    def truth_pose(self):
        for message in reversed(self.truth):
            for transform in message.transforms:
                if transform.child_frame_id == "robotops":
                    return transform.transform
        return None

    def map_to_base(self):
        return self.buffer.lookup_transform("map", "base_link", Time()).transform

    def validate_sensors(self) -> None:
        self.wait(lambda: len(self.scan) >= 5 and len(self.imu) >= 10, "Missing LiDAR/IMU data")
        scan, imu = self.scan[-2], self.imu[-1]
        assert scan.header.frame_id == "lidar_link"
        assert imu.header.frame_id == "imu_link"
        assert len(scan.ranges) == 360
        assert Time.from_msg(scan.header.stamp).nanoseconds > 0
        assert Time.from_msg(imu.header.stamp).nanoseconds > 0
        assert self.scan[-1].header.stamp != self.scan[0].header.stamp
        forward = round(-scan.angle_min / scan.angle_increment)
        assert 4.7 < scan.ranges[forward] < 5.3, "East wall should be about 5 m from spawn"
        assert math.isfinite(imu.angular_velocity.z)
        acceleration = imu.linear_acceleration
        assert 8.5 < math.sqrt(acceleration.x**2 + acceleration.y**2 + acceleration.z**2) < 11
        stamp = Time.from_msg(scan.header.stamp)
        self.wait(
            lambda: self.buffer.can_transform("base_link", "lidar_link", stamp),
            "Sensor TF missing at scan timestamp",
        )
        assert self.node.count_publishers("/scan") == 1
        assert self.node.count_publishers("/imu/data") == 1


def create_saved_map(tmp_path: Path) -> Path:
    with Session(tmp_path, "mapping") as session:
        session.validate_sensors()
        session.active("slam_toolbox")
        session.wait(
            lambda: session.maps and session.buffer.can_transform("map", "base_link", Time()),
            "SLAM did not publish map and TF",
        )
        assert "amcl" not in session.node.get_node_names()
        first_stamp = session.maps[-1].header.stamp
        first_data = list(session.maps[-1].data)
        first_known = sum(value >= 0 for value in session.maps[-1].data)
        session.drive(3.0, linear=0.2)
        session.drive(2.0, angular=0.4)
        session.drive(2.0, linear=0.15)
        session.drive(1.5)
        session.wait(lambda: session.maps[-1].header.stamp != first_stamp, "Map stopped updating")
        grid = session.maps[-1]
        assert grid.header.frame_id == "map"
        assert abs(grid.info.resolution - 0.05) < 1e-6
        assert sum(value == 0 for value in grid.data) > 1000
        assert sum(value >= 65 for value in grid.data) > 100
        assert sum(value >= 0 for value in grid.data) >= first_known
        assert list(grid.data) != first_data, "Motion did not change occupancy data"
        session.validate_tf_publishers()
        assert session.node.count_publishers("/map") == 1
        saved = subprocess.run(
            [
                "ros2",
                "run",
                "nav2_map_server",
                "map_saver_cli",
                "-f",
                str(tmp_path / "lab"),
                "--ros-args",
                "-p",
                "use_sim_time:=true",
                "-p",
                "save_map_timeout:=10.0",
            ],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        assert saved.returncode == 0, saved.stdout + saved.stderr

    return tmp_path / "lab.yaml"


def test_mapping_save_restart_localization(tmp_path: Path) -> None:
    create_saved_map(tmp_path)
    map_file = tmp_path / "lab.yaml"
    metadata = yaml.safe_load(map_file.read_text())
    image = map_file.parent / metadata["image"]
    assert image.read_bytes().startswith(b"P5")
    assert image.stat().st_size > 1000
    digests = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (map_file, image)]
    with Session(tmp_path, "localization", map_file) as session:
        session.validate_sensors()
        session.active("map_server")
        session.active("amcl")
        session.wait(
            lambda: session.maps and session.initial_pose.get_subscription_count() > 0,
            "Saved map or initial-pose subscription missing",
        )
        assert "slam_toolbox" not in session.node.get_node_names()
        initial = PoseWithCovarianceStamped()
        initial.header.frame_id = "map"
        initial.header.stamp = session.node.get_clock().now().to_msg()
        initial.pose.pose.orientation.w = 1.0
        initial.pose.covariance[0] = initial.pose.covariance[7] = 0.1
        initial.pose.covariance[35] = 0.1
        session.initial_pose.publish(initial)
        session.wait(
            lambda: session.poses
            and session.truth_pose() is not None
            and session.buffer.can_transform("map", "base_link", Time()),
            "AMCL did not localize",
        )
        first_pose_stamp = session.poses[-1].header.stamp
        saved_grid = bytes(value + 1 for value in session.maps[-1].data)
        session.drive(3.0, linear=0.15)
        session.drive(1.0, angular=0.25)
        session.drive(1.0)
        session.wait(
            lambda: session.poses[-1].header.stamp != first_pose_stamp,
            "AMCL pose stopped updating during motion",
        )
        session.validate_tf_publishers()
        estimate, truth = session.map_to_base(), session.truth_pose()
        position_error = math.hypot(
            estimate.translation.x - truth.translation.x,
            estimate.translation.y - truth.translation.y,
        )
        angle_error = math.atan2(
            math.sin(yaw(estimate.rotation) - yaw(truth.rotation)),
            math.cos(yaw(estimate.rotation) - yaw(truth.rotation)),
        )
        assert position_error < 0.35, f"AMCL error {position_error:.3f} m"
        assert abs(angle_error) < 0.25, f"AMCL yaw error {angle_error:.3f} rad"
        assert math.hypot(truth.translation.x, truth.translation.y) > 0.25
        assert bytes(value + 1 for value in session.maps[-1].data) == saved_grid
        assert session.node.count_publishers("/map") == 1
        print(f"AMCL position error={position_error:.3f} m, yaw error={angle_error:.3f} rad")
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (map_file, image)] == digests
