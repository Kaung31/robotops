"""Native process transport regressions; controlled publishers, isolated ROS domain."""

import signal
import subprocess
import time
from pathlib import Path

import pytest
import rclpy
from ament_index_python.packages import get_package_prefix
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from nav_msgs.msg import Odometry
from rcl_interfaces.srv import SetParameters
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import Imu, LaserScan


def executable():
    return str(
        Path(get_package_prefix("robot_diagnostics")) / "lib/robot_diagnostics/freshness_monitor"
    )


@pytest.fixture
def runtime(tmp_path):
    context = Context()
    rclpy.init(context=context)
    driver = Node("diagnostic_test_driver", context=context, namespace="diagnostics_test")
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(driver)
    received = []
    subscription = driver.create_subscription(DiagnosticArray, "diagnostics", received.append, 10)
    processes = []

    def start(parameters):
        args = [executable(), "--ros-args", "-r", "__ns:=/diagnostics_test"]
        for key, value in parameters.items():
            args.extend(["-p", f"{key}:={value}"])
        log = (tmp_path / f"monitor-{len(processes)}.log").open("w+")
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        processes.append((process, log))

    def until(predicate, action=lambda: None, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            action()
            executor.spin_once(timeout_sec=0.01)
            if predicate():
                return
        raise AssertionError("Timed out waiting for diagnostic transition")

    try:
        yield driver, received, start, until
    finally:
        for process, log in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            output = log.read()
            log.close()
            assert process.returncode == 0, output
        assert subscription is not None
        executor.shutdown()
        driver.destroy_node()
        context.shutdown()


@pytest.mark.parametrize(
    "reliability", [ReliabilityPolicy.BEST_EFFORT, ReliabilityPolicy.RELIABLE]
)
@pytest.mark.parametrize(
    "stream,topic,message_type",
    [
        ("scan", "scan", LaserScan),
        ("odom", "odom", Odometry),
        ("imu", "imu/data", Imu),
    ],
)
def test_dropout_frozen_stamp_recovery_and_read_only_graph(
    runtime, reliability, stream, topic, message_type
):
    driver, received, start, until = runtime
    start(
        {
            "enabled_streams": f"[{stream}]",
            "warn_seconds": 0.1,
            "error_seconds": 0.2,
            "publish_period_seconds": 0.02,
        }
    )
    publisher = driver.create_publisher(
        message_type, topic, QoSProfile(depth=10, reliability=reliability)
    )

    def emit(stamp=None):
        message = message_type()
        message.header.stamp = stamp or driver.get_clock().now().to_msg()
        publisher.publish(message)

    def status():
        return (
            next(s for s in received[-1].status if s.name == f"robotops/freshness/{stream}")
            if received
            else None
        )

    until(lambda: publisher.get_subscription_count() == 1)
    until(lambda: status() and status().level == DiagnosticStatus.OK, emit)
    assert len(received[-1].status) == 2
    until(lambda: status().message == "receipt_timeout")
    until(lambda: status().level == DiagnosticStatus.OK, emit)
    frozen = driver.get_clock().now().to_msg()
    until(lambda: status().message == "stamp_timeout", lambda: emit(frozen))
    assert status().level == DiagnosticStatus.ERROR
    until(lambda: status().level == DiagnosticStatus.OK, emit)
    outputs = dict(
        driver.get_publisher_names_and_types_by_node("robotops_diagnostics", "/diagnostics_test")
    )
    assert set(outputs) <= {"/diagnostics_test/diagnostics", "/parameter_events", "/rosout"}


def test_stopped_repeated_and_reset_sim_clock(runtime):
    driver, received, start, until = runtime
    start(
        {
            "enabled_streams": "[scan]",
            "use_sim_time": "true",
            "clock_stall_seconds": 0.15,
            "publish_period_seconds": 0.02,
        }
    )
    clock = driver.create_publisher(Clock, "/clock", 10)
    scan = driver.create_publisher(LaserScan, "scan", 10)

    def emit(seconds):
        message = Clock()
        message.clock.sec = seconds
        clock.publish(message)

    def reason():
        return received[-1].status[0].message if received else None

    until(lambda: reason() == "clock_uninitialized")
    until(lambda: received[-1].header.stamp.sec == 100, lambda: emit(100))
    message = LaserScan()
    message.header.stamp.sec = 100
    until(
        lambda: received[-1].status[1].message == "awaiting_advancing_samples",
        lambda: scan.publish(message),
    )
    before = len(received)
    until(lambda: reason() == "clock_not_advancing", lambda: emit(100))
    assert len(received) > before
    assert received[-1].status[1].message == "clock_not_advancing"
    until(lambda: received[-1].header.stamp.sec == 1, lambda: emit(1))
    assert received[-1].status[1].message == "not_observed"
    epoch = int(
        next(pair.value for pair in received[-1].status[0].values if pair.key == "clock_epoch")
    )
    client = driver.create_client(SetParameters, "robotops_diagnostics/set_parameters")
    until(lambda: client.service_is_ready())
    request = SetParameters.Request()
    request.parameters = [Parameter("use_sim_time", value=False).to_parameter_msg()]
    future = client.call_async(request)
    until(future.done)
    assert future.result().results[0].successful
    until(lambda: received[-1].header.stamp.sec > 1_000_000_000)
    assert received[-1].status[1].message == "not_observed"
    assert (
        int(
            next(pair.value for pair in received[-1].status[0].values if pair.key == "clock_epoch")
        )
        > epoch
    )


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("zero", "invalid_stamp"),
        ("future", "future_stamp"),
        ("past", "stamp_regressed"),
        ("bad_nanosec", "invalid_stamp"),
    ],
)
def test_bad_headers_and_recovery(runtime, fault, reason):
    driver, received, start, until = runtime
    start({"enabled_streams": "[scan]", "publish_period_seconds": 0.02})
    publisher = driver.create_publisher(LaserScan, "scan", 10)

    def emit(bad=False):
        message = LaserScan()
        message.header.stamp = driver.get_clock().now().to_msg()
        if bad:
            if fault == "zero":
                message.header.stamp.sec = message.header.stamp.nanosec = 0
            if fault == "future":
                message.header.stamp.sec += 10
            if fault == "past":
                message.header.stamp.sec -= 1
            if fault == "bad_nanosec":
                message.header.stamp.nanosec = 1_000_000_000
        publisher.publish(message)

    until(lambda: publisher.get_subscription_count() == 1)
    until(lambda: received and received[-1].status[1].level == DiagnosticStatus.OK, emit)
    # One regressing header is sufficient; repeated old stamps would progress again.
    emit(True)
    until(lambda: received[-1].status[1].message == reason)
    assert received[-1].status[1].level == DiagnosticStatus.ERROR
    until(lambda: received[-1].status[1].level == DiagnosticStatus.OK, emit)


@pytest.mark.parametrize(
    "parameter,value",
    [
        ("warn_seconds", -1.0),
        ("error_seconds", 0.1),
        ("publish_period_seconds", 0.0),
        ("enabled_streams", "[invalid]"),
        ("enabled_streams", "[scan,scan]"),
    ],
)
def test_invalid_configuration_exits_clearly(parameter, value):
    result = subprocess.run(
        [executable(), "--ros-args", "-p", f"{parameter}:={value}"],
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert "[ERROR]" in result.stderr
