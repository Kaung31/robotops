"""Actual experiment CLI -> mission server -> controlled Nav2, with real MCAP."""

import copy
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
import rclpy
import yaml
from ament_index_python.packages import get_package_prefix
from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped
from nav_msgs.msg import Odometry
from rclpy.parameter import Parameter
from rclpy.qos import qos_profile_sensor_data
from tf2_msgs.msg import TFMessage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mission_manager/test"))
from experiment_runner.model import load  # noqa: E402
from experiment_runner.runner import PARAMETER_NODES  # noqa: E402
from mission_integration import Rig, wait_for  # noqa: E402


class ExperimentRig(Rig):
    def telemetry(self):
        msg = Odometry()
        msg.header.stamp = self.node.get_clock().now().to_msg()
        msg.header.frame_id, msg.child_frame_id = "odom", "base_link"
        msg.pose.pose.orientation.w = 1.0
        self.odom.publish(msg)
        if hasattr(self, "tf"):
            transform = TransformStamped()
            transform.header.stamp = copy.deepcopy(msg.header.stamp)
            transform.header.frame_id, transform.child_frame_id = "map", "odom"
            transform.transform.rotation.w = 1.0
            transform.transform.translation.x = getattr(self, "start_x", 0.0)
            # Raw map->odom is deliberately post-dated.
            ns = transform.header.stamp.nanosec + 500_000_000
            transform.header.stamp.sec += ns // 10**9
            transform.header.stamp.nanosec = ns % 10**9
            base = TransformStamped()
            base.header.stamp = msg.header.stamp
            base.header.frame_id, base.child_frame_id = "odom", "base_link"
            base.transform.rotation.w = 1.0
            self.tf.publish(TFMessage(transforms=[transform, base]))
            if not getattr(self, "missing_localization", False):
                pose = PoseWithCovarianceStamped()
                pose.header.stamp = msg.header.stamp
                pose.header.frame_id = "map"
                pose.pose.pose.orientation.w = 1.0
                self.amcl.publish(pose)


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "bad_start",
        "bad_settings",
        "abort",
        "interrupt",
        "drift",
        "second_start",
        "uncertain",
        "wrong_final",
        "missing_localization",
    ],
)
def test_experiment(tmp_path, case):
    domain = 180 + [
        "success",
        "bad_start",
        "bad_settings",
        "abort",
        "interrupt",
        "drift",
        "second_start",
        "uncertain",
        "wrong_final",
        "missing_localization",
    ].index(case)
    (tmp_path / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    map_file = tmp_path / "map.yaml"
    map_file.write_text("image: map.pgm\n")
    rig = ExperimentRig(
        tmp_path,
        domain,
        {"abort": "abort", "interrupt": "hold", "uncertain": "refuse_cancel"}.get(case, "success"),
        mission_parameters={"map_file": str(map_file)},
    )
    nodes = []
    process = None
    try:
        rig.amcl = rig.node.create_publisher(
            PoseWithCovarianceStamped,
            "amcl_pose",
            qos_profile_sensor_data if case == "wrong_final" else 10,
        )
        rig.missing_localization = case == "missing_localization"
        rig.tf = rig.node.create_publisher(TFMessage, "tf", 10)
        for name in PARAMETER_NODES:
            if name == "mission_manager":
                continue
            node = rclpy.create_node(name)
            if name == "map_server":
                node.declare_parameter("yaml_filename", str(map_file))
            if name == "amcl":
                node.declare_parameter("transform_tolerance", 0.5)
            node.declare_parameter("test_setting", 1)
            node.declare_parameter("unset_limit", float("nan"))
            rig.executor.add_node(node)
            nodes.append(node)
        config = load(Path(__file__).resolve().parents[1] / "config/round_trip.yaml")
        config["expected"].update(
            runtime_mode="mock", environment="unspecified", navigation_profile="unspecified"
        )
        if case in ("wrong_final", "missing_localization"):
            config["repetitions"] = 1
        if case == "bad_start":
            config["start"]["x"] = 10.0
        if case == "bad_settings":
            config["expected"]["robot_model"] = "wrong_robot"
        config_file = tmp_path / "experiment.yaml"
        config_file.write_text(yaml.safe_dump(config))
        executable = (
            Path(get_package_prefix("experiment_runner")) / "lib/experiment_runner/experiment"
        )
        with (tmp_path / "experiment.log").open("w") as output:
            process = subprocess.Popen(
                [
                    str(executable),
                    "run",
                    str(config_file),
                    "--output",
                    str(tmp_path / "experiments"),
                ],
                env=dict(os.environ, ROS_DOMAIN_ID=str(domain)),
                stdout=output,
                stderr=subprocess.STDOUT,
            )
            if case in ("interrupt", "drift", "second_start", "uncertain", "wrong_final"):
                wait_for(lambda: rig.goals, 30)
                if case in ("interrupt", "uncertain"):
                    process.send_signal(signal.SIGINT)
                elif case == "wrong_final":
                    rig.start_x = 0.3
                elif case == "second_start":
                    wait_for(lambda: len(rig.goals) == 2, 30)
                    rig.start_x = 10.0
                else:
                    nodes[0].set_parameters([Parameter("test_setting", value=2)])
            status = process.wait(timeout=65)
        manifests = list((tmp_path / "experiments").glob("*/manifest.json"))
        assert len(manifests) == 1
        data = json.loads(manifests[0].read_text())
        # This controlled rig has no contact adapter. ROS success/pose verification
        # must never manufacture collision-free evidence.
        assert all(t["collision"]["verdict"] == "UNKNOWN" for t in data["trials"])
        assert status == (
            0 if case in ("success", "wrong_final", "missing_localization") else 1
        ), (tmp_path / "experiment.log").read_text()
        if case == "success":
            assert data["state"] == "completed"
            assert len(data["trials"]) == 2
            assert len({t["run_id"] for t in data["trials"]}) == 2
            assert all(t["metrics"]["odom_path_metres"] == 0 for t in data["trials"])
            assert all(t["metrics"]["mission_ros_seconds"] > 0 for t in data["trials"])
            assert len(rig.goals) == 4
            assert all(t["validation"]["verdict"] == "POSE_VERIFIED" for t in data["trials"])
        elif case in ("wrong_final", "missing_localization"):
            assert data["state"] == "completed"
            trial = data["trials"][0]
            assert trial["outcome"] == "succeeded"
            expected = "POSE_REJECTED" if case == "wrong_final" else "INCONCLUSIVE"
            assert trial["validation"]["verdict"] == expected, trial["validation"]
            assert len(rig.goals) == 2
        elif case in ("bad_start", "bad_settings"):
            assert not rig.goals
            assert not data["trials"]
        elif case == "interrupt":
            assert data["state"] == "interrupted"
            assert data["termination_confirmed"]
            assert data["trials"][0]["run_id"]
            assert Path(data["trials"][0]["artifact_directory"], "result.json").exists()
            assert rig.cancels
            assert len(rig.goals) == 1
        elif case == "second_start":
            assert len(data["trials"]) == 1
            assert data["trials"][0]["outcome"] == "succeeded"
            assert len(rig.goals) == 2
        elif case == "uncertain":
            assert not data["termination_confirmed"]
            assert data["trials"][0]["outcome"] == "termination_unconfirmed"
            assert data["trials"][0]["validation"]["verdict"] == "INCONCLUSIVE"
            assert len(rig.goals) == 1
        elif case == "drift":
            assert data["trials"][0]["outcome"] == "invalid_conditions"
            assert len(data["trials"]) == 1
        else:
            assert data["trials"][0]["outcome"] == "failed"
            assert len(data["trials"]) == 1
        assert "Traceback" not in (tmp_path / "experiment.log").read_text()
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for node in nodes:
            rig.executor.remove_node(node)
            node.destroy_node()
        rig.close()


def test_result_transport_failure_is_persisted(tmp_path):
    from types import SimpleNamespace

    from experiment_runner.runner import ExperimentRunner
    from rclpy.task import Future

    rclpy.init(domain_id=188)
    config = load(Path(__file__).resolve().parents[1] / "config/round_trip.yaml")
    node = ExperimentRunner(config, tmp_path)
    original = node.client
    failed = Future()
    failed.set_exception(RuntimeError("result transport failed"))
    accepted = Future()
    accepted.set_result(SimpleNamespace(accepted=True, get_result_async=lambda: failed))
    node.client = SimpleNamespace(
        server_is_ready=lambda: True, send_goal_async=lambda *a, **kw: accepted
    )
    node.preflight = lambda: {"parameters": {}}
    try:
        assert not node.execute()
        manifest = json.loads((node.directory / "manifest.json").read_text())
        assert manifest["state"] == "failed"
        assert not manifest["termination_confirmed"]
        assert manifest["trials"][0]["outcome"] == "termination_unconfirmed"
        assert manifest["trials"][0]["result_error"] == "result transport failed"
        assert manifest["trials"][0]["validation"]["verdict"] == "INCONCLUSIVE"
    finally:
        node.client = original
        node.close()
        rclpy.shutdown()
