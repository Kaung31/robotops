"""Recorded two-waypoint mission against actual Gazebo sensors and Nav2."""

import hashlib
import json
import sys
from pathlib import Path

import rosbag2_py
import yaml
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_prefix
from geometry_msgs.msg import PoseStamped
from rclpy.action import ActionClient
from rclpy.serialization import deserialize_message
from robotops_interfaces.action import ExecuteMission
from tf2_msgs.msg import TFMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "robot_navigation/test"))
from mapping_system import create_saved_map  # noqa: E402
from navigation_system import NavigationSession  # noqa: E402


def test_recorded_mission(tmp_path: Path) -> None:
    mapping = tmp_path / "mapping"
    mapping.mkdir()
    map_file = create_saved_map(mapping)
    image = map_file.parent / yaml.safe_load(map_file.read_text())["image"]
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (map_file, image)]
    with NavigationSession(tmp_path / "navigation", map_file, "navfn_rpp") as session:
        session.initialize()
        executable = (
            Path(get_package_prefix("mission_manager")) / "lib/mission_manager/mission_server"
        )
        session.start(
            "mission",
            [
                str(executable),
                "--ros-args",
                "-p",
                "runtime_mode:=sim",
                "-p",
                "use_sim_time:=true",
                "-p",
                f"artifact_root:={tmp_path / 'runs'}",
                "-p",
                "environment:=mapping_lab",
                "-p",
                f"map_file:={map_file}",
                "-p",
                "navigation_profile:=navfn_rpp",
            ],
        )
        client = ActionClient(session.node, ExecuteMission, "missions/execute")
        assert client.wait_for_server(timeout_sec=15)
        request = ExecuteMission.Goal(label="mapping_lab_round_trip", record=True)
        for x, y in ((1.0, 0.3), (0.0, 0.0)):
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.pose.position.x, pose.pose.position.y = x, y
            pose.pose.orientation.w = 1.0
            request.waypoints.append(pose)
        future = client.send_goal_async(request)
        session.wait(future.done, "No mission response", 10)
        assert future.result().accepted
        result = future.result().get_result_async()
        session.wait(result.done, "Recorded mission did not finish", 150)
        reply = result.result()
        assert reply.status == GoalStatus.STATUS_SUCCEEDED, reply.result
        assert reply.result.completed_waypoints == 2
        session.assert_stopped()
        pose = session.truth_pose().translation
        assert (pose.x**2 + pose.y**2) ** 0.5 < 0.35
        directory = Path(reply.result.artifact_directory)
        metadata = json.loads((directory / "metadata.json").read_text())
        assert metadata["map"]["yaml_sha256"] == hashes[0]
        assert metadata["map"]["image_sha256"] == hashes[1]
        record = json.loads((directory / "result.json").read_text())
        assert record["outcome"] == "succeeded"
        assert record["elapsed_ros_seconds"] > 0
        counts = record["recording"]["topic_counts"]
        assert all(
            counts.get(t, 0) > 0
            for t in ("/scan", "/imu/data", "/map", "/tf_static", "/odom", "/clock")
        )
        reader = rosbag2_py.SequentialReader()
        reader.open(
            rosbag2_py.StorageOptions(uri=str(directory / "telemetry"), storage_id="mcap"),
            rosbag2_py.ConverterOptions("cdr", "cdr"),
        )
        actual = 0
        edges = set()
        while reader.has_next():
            topic, data, _stamp = reader.read_next()
            if topic == "/tf":
                for transform in deserialize_message(data, TFMessage).transforms:
                    edges.add((transform.header.frame_id, transform.child_frame_id))
            actual += 1
        assert {
            ("map", "odom"),
            ("odom", "base_link"),
            ("base_link", "left_wheel_link"),
            ("base_link", "right_wheel_link"),
        } <= edges
        for path, _stream in session.logs:
            assert "incompatible QoS" not in path.read_text()
        assert actual == sum(counts.values())
        del reader
        print(
            f"Recorded mission succeeded: {actual} messages, "
            f"{record['elapsed_ros_seconds']:.2f} ROS seconds"
        )
        client.destroy()
    assert (
        "exception was never retrieved"
        not in (tmp_path / "navigation/localization-mission.log").read_text()
    )
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (map_file, image)] == hashes
