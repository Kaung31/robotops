"""Signal shutdown must join SLAM workers while their ROS context is valid."""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
import rclpy
from ament_index_python.packages import get_package_prefix, get_package_share_directory
from lifecycle_msgs.msg import Transition
from lifecycle_msgs.srv import ChangeState, GetState


@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("sim_time", [False, True])
@pytest.mark.parametrize("active", [False, True])
def test_shutdown(tmp_path: Path, stop_signal: int, sim_time: bool, active: bool) -> None:
    executable = Path(get_package_prefix("robot_navigation")) / "lib/robot_navigation/slam_runner"
    config = Path(get_package_share_directory("robot_navigation")) / "config/slam.yaml"
    # A fresh domain for each process avoids stale discovery between fast restarts.
    domain = 130 + int(active) * 4 + int(sim_time) * 2 + int(stop_signal == signal.SIGTERM)
    rclpy.init(domain_id=domain)
    node = rclpy.create_node("shutdown_test")
    state = node.create_client(GetState, "/slam_toolbox/get_state")
    change = node.create_client(ChangeState, "/slam_toolbox/change_state")
    log_path = tmp_path / "slam.log"
    with log_path.open("w") as stream:
        process = subprocess.Popen(
            [
                str(executable),
                "--ros-args",
                "--params-file",
                str(config),
                "-p",
                f"use_sim_time:={str(sim_time).lower()}",
            ],
            env=dict(os.environ, ROS_DOMAIN_ID=str(domain)),
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            assert state.wait_for_service(timeout_sec=15), log_path.read_text()
            if active:
                assert change.wait_for_service(timeout_sec=5)
                for transition in (
                    Transition.TRANSITION_CONFIGURE,
                    Transition.TRANSITION_ACTIVATE,
                ):
                    request = ChangeState.Request()
                    request.transition.id = transition
                    future = change.call_async(request)
                    rclpy.spin_until_future_complete(node, future, timeout_sec=10)
                    assert future.done() and future.result().success, log_path.read_text()
                # Exercise worker sleep, with /clock intentionally absent in sim-time cases.
                time.sleep(0.13)
            process.send_signal(stop_signal)
            assert process.wait(timeout=5) == 0, log_path.read_text()
            output = log_path.read_text()
            assert "context cannot be slept" not in output
            if active:
                assert "Deactivating" in output and "Cleaning up" in output
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            node.destroy_node()
            rclpy.shutdown()
