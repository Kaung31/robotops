"""Opt-in ROS/Gazebo regression for the backend's real rendered-robot stop path."""

import os
import signal
import time
from pathlib import Path

import pytest
import rclpy
from nav_msgs.msg import Odometry
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from robotops_backend.models import StackMode, StackRequest
from robotops_backend.orchestrator import StackOrchestrator
from robotops_interfaces.msg import ContactEvidence
from sensor_msgs.msg import LaserScan


@pytest.mark.parametrize("stop_kind", ["backend", "direct_int", "direct_term"])
def test_loaded_rendered_robot_shutdown(tmp_path, monkeypatch, stop_kind):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("ROS_DOMAIN_ID", "198")
    monkeypatch.setenv("GZ_PARTITION", f"loaded_shutdown_{os.getpid()}_{stop_kind}")
    monkeypatch.setenv("ROBOTOPS_USE_XVFB", "true")
    monkeypatch.setenv("ROBOTOPS_DIAGNOSTICS", "false")
    context = Context()
    rclpy.init(context=context, domain_id=198)
    node = rclpy.create_node("loaded_shutdown_observer", context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(node)
    counts = {"odom": 0, "scan": 0, "contacts": 0}

    def receive(key):
        def callback(message):
            if key != "contacts" or message.coverage_complete:
                counts[key] += 1

        return callback

    subscriptions = [
        node.create_subscription(Odometry, "odom", receive("odom"), qos_profile_sensor_data),
        node.create_subscription(LaserScan, "scan", receive("scan"), qos_profile_sensor_data),
        node.create_subscription(ContactEvidence, "validation/contacts", receive("contacts"), 100),
    ]
    orchestrator = StackOrchestrator(root)
    orchestrator.logs_dir = tmp_path
    request = StackRequest(mode=StackMode.MAPPING, world="mapping_lab", headless_rendering=False)
    name, command, env = orchestrator._commands(request, None)[0]
    try:
        orchestrator._start_process_locked(name, command, env)
        item = orchestrator._processes[name]
        deadline = time.monotonic() + 45
        while min(counts.values()) < 10 and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)
            assert item.process.poll() is None, item.log_path.read_text()
        assert min(counts.values()) >= 10, (counts, item.log_path.read_text())
        if stop_kind != "backend":
            candidates = []
            for entry in Path("/proc").iterdir():
                try:
                    args = (entry / "cmdline").read_bytes().split(b"\0")
                    if (
                        entry.name.isdigit()
                        and args[0].endswith(b"/gazebo_runner")
                        and os.getpgid(int(entry.name)) == item.process.pid
                    ):
                        candidates.append(int(entry.name))
                except OSError:
                    pass
            assert len(candidates) == 1, candidates
            os.kill(candidates[0], signal.SIGINT if stop_kind == "direct_int" else signal.SIGTERM)
            item.process.wait(timeout=20)
        orchestrator._stop_locked()
        log = item.log_path.read_text()
        assert item.process.returncode == 0, log
        assert "[gazebo_runner-2]: process has finished cleanly" in log, log
        assert "XIO:" not in log and "exit code -11" not in log, log
    finally:
        orchestrator._stop_locked()
        for subscription in subscriptions:
            node.destroy_subscription(subscription)
        executor.shutdown()
        node.destroy_node()
        context.shutdown()
