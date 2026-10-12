"""Two recorded trials on one persistent Gazebo/Nav2 stack."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import rclpy
import yaml
from ament_index_python.packages import get_package_prefix

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "robot_navigation/test"))
from mapping_system import create_saved_map  # noqa: E402
from navigation_system import NavigationSession  # noqa: E402


def test_repeated_recorded_missions(tmp_path):
    mapping = tmp_path / "mapping"
    mapping.mkdir()
    map_file = create_saved_map(mapping)
    with NavigationSession(tmp_path / "navigation", map_file, "navfn_rpp") as session:
        session.initialize()
        mission = (
            Path(get_package_prefix("mission_manager")) / "lib/mission_manager/mission_server"
        )
        session.start(
            "mission",
            [
                str(mission),
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
        executable = (
            Path(get_package_prefix("experiment_runner")) / "lib/experiment_runner/experiment"
        )
        config = Path(__file__).resolve().parents[1] / "config/round_trip.yaml"
        with (tmp_path / "experiment.log").open("w") as output:
            process = subprocess.Popen(
                [str(executable), "run", str(config), "--output", str(tmp_path / "experiments")],
                env=dict(os.environ, ROS_DOMAIN_ID=str(session.domain_id)),
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 180
                while process.poll() is None and time.monotonic() < deadline:
                    assert all(p.poll() is None for p in session.processes)
                    rclpy.spin_once(session.node, timeout_sec=0.05)
                assert process.poll() == 0, (tmp_path / "experiment.log").read_text()
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=35)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        manifest = json.loads(next((tmp_path / "experiments").glob("*/manifest.json")).read_text())
        assert manifest["state"] == "completed", manifest
        assert len(manifest["trials"]) == 2
        assert len({t["run_id"] for t in manifest["trials"]}) == 2
        assert len({t["artifact_directory"] for t in manifest["trials"]}) == 2
        assert all(t["outcome"] == "succeeded" for t in manifest["trials"])
        assert all(1.5 < t["metrics"]["odom_path_metres"] < 4 for t in manifest["trials"])
        assert all(t["metrics"]["mission_ros_seconds"] > 0 for t in manifest["trials"])
        assert all(not t["metrics"]["unavailable"] for t in manifest["trials"])
        session.assert_stopped()
        assert session.node.count_publishers("/drive_controller/cmd_vel") == 1
        image = map_file.parent / yaml.safe_load(map_file.read_text())["image"]
        assert image.exists()
        print(json.dumps([t["metrics"] for t in manifest["trials"]]))
