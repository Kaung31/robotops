"""ROS-only scheduling regression; run with the built workspace sourced.

Portable pytest runs skip this module. No simulator or external Nav2 is needed.
"""

import asyncio
import threading
import time

import pytest


def test_readiness_responses_run_while_sensor_group_is_busy():
    pytest.importorskip("rclpy")
    pytest.importorskip("robotops_interfaces.action")
    from lifecycle_msgs.srv import GetState
    from nav_msgs.msg import Odometry
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from robotops_backend.models import MapSnapshot, Pose2D, RuntimeMode
    from robotops_backend.ros_gateway import RosGateway
    from robotops_backend.state import TelemetryStore
    from std_srvs.srv import Trigger

    store = TelemetryStore()
    store.publish(
        map=MapSnapshot(
            width=180,
            height=180,
            resolution=0.05,
            origin=Pose2D(x=0, y=0, yaw=0),
            data=[0] * 32400,
        )
    )
    gateway = RosGateway(store, RuntimeMode.MOCK)
    sensor_entered = threading.Event()
    release_sensor = threading.Event()
    original_odom = gateway._odom

    def busy_odom(msg):
        original_odom(msg)  # Exercise the actual cached-map telemetry workload.
        sensor_entered.set()
        # Hold the group deterministically rather than relying on CPU speed.
        release_sensor.wait(timeout=10)

    gateway._odom = busy_odom
    gateway.start()
    server = Node("readiness_callback_test")
    executor = SingleThreadedExecutor()
    executor.add_node(server)

    def lifecycle(_request, response):
        response.current_state.id = 3
        response.current_state.label = "active"
        return response

    def manager(_request, response):
        response.success = True
        return response

    server.create_service(GetState, "/amcl/get_state", lifecycle)
    server.create_service(Trigger, "/lifecycle_manager_nav2/is_active", manager)
    publisher = server.create_publisher(Odometry, "odom", 10)
    thread = threading.Thread(target=executor.spin)
    thread.start()
    try:
        client = gateway._lifecycle_get_clients["amcl"]
        manager_client = gateway._lifecycle_manager_active_clients["nav2"]
        assert client.wait_for_service(timeout_sec=5)
        assert manager_client.wait_for_service(timeout_sec=5)
        deadline = time.monotonic() + 5
        while publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        publisher.publish(Odometry())
        assert sensor_entered.wait(timeout=5)
        response = asyncio.run(gateway._await_ros(client.call_async(GetState.Request()), 1))
        assert response.current_state.label == "active"
        response = asyncio.run(gateway._await_ros(manager_client.call_async(Trigger.Request()), 1))
        assert response.success
        assert not release_sensor.is_set()
    finally:
        release_sensor.set()
        executor.shutdown(timeout_sec=5)
        thread.join(timeout=5)
        server.destroy_node()
        gateway.close()
