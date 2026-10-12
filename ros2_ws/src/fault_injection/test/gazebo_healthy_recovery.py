"""ONE normal, non-injected baseline; cannot reset or consume the route guard."""

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from action_msgs.msg import GoalStatus, GoalStatusArray
from ament_index_python.packages import get_package_prefix
from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import PoseStamped
from rclpy.action import ActionClient
from rclpy.qos import DurabilityPolicy, QoSProfile
from rclpy.time import Time
from robotops_interfaces.action import ExecuteMission

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gazebo_routing import filter_stamps, graph  # noqa: E402
from probe_evidence import CLOCK_STATUS, SCAN_STATUS, EvidenceJournal  # noqa: E402
from probe_session import ObservedNavigationSession  # noqa: E402


def test_default_route_recovery_baseline(tmp_path):
    map_file = Path(os.environ.get("ROBOTOPS_FAULT_TEST_MAP", ""))
    if not map_file.is_file():
        pytest.skip("Qualified mapping_lab map required")
    root = Path(__file__).resolve().parents[4]
    guard = (
        root
        / "artifacts/r2a-p2-20261011/routed-live/test_real_routed_dropout0/runtime/routing.guard"
    )
    original = guard.read_bytes()
    before = guard.stat()
    with EvidenceJournal(tmp_path / "observations.jsonl") as journal:
        journal.record(
            "preserved_quarantine",
            sha256=hashlib.sha256(original).hexdigest(),
            mtime_ns=before.st_mtime_ns,
            inode=before.st_ino,
        )
        with ObservedNavigationSession(
            tmp_path / "navigation", map_file, "navfn_rpp", journal
        ) as session:
            session.initialize()
            topology = graph(session.node)
            journal.record("topology", graph=topology)
            assert len(topology["/scan"]["publishers"]) == 1
            assert not topology["/fault_probe/scan"]["publishers"]
            assert "scan_fault_relay" not in session.node.get_node_names()
            assert {"amcl", "local_costmap", "global_costmap"} <= {
                e["node"] for e in topology["/scan"]["subscribers"]
            }
            assert all(m.header.frame_id == "lidar_link" for m in session.scan)
            assert session.poses and session.poses[-1].header.frame_id == "map"
            tf = session.buffer.lookup_transform("map", "base_link", Time())
            journal.record(
                "localized_tf",
                frame=tf.header.frame_id,
                child=tf.child_frame_id,
                stamp_ns=tf.header.stamp.sec * 10**9 + tf.header.stamp.nanosec,
                x=tf.transform.translation.x,
                y=tf.transform.translation.y,
            )
            diagnostics = []
            session.subscriptions.append(
                session.node.create_subscription(
                    DiagnosticArray,
                    "/baseline_probe/diagnostics",
                    lambda m: session.diagnostics(diagnostics, "/baseline_probe/diagnostics", m),
                    20,
                )
            )
            monitor = (
                Path(get_package_prefix("robot_diagnostics"))
                / "lib/robot_diagnostics/freshness_monitor"
            )
            session.start(
                "baseline-monitor",
                [
                    str(monitor),
                    "--ros-args",
                    "-p",
                    "use_sim_time:=true",
                    "-p",
                    "enabled_streams:=[scan]",
                    "-p",
                    "hardware_id:=r2a_baseline_raw",
                    "-r",
                    "__node:=baseline_scan_monitor",
                    "-r",
                    "diagnostics:=/baseline_probe/diagnostics",
                ],
            )

            def fresh():
                if not diagnostics:
                    return False
                statuses = {
                    s["name"]: s
                    for s in diagnostics[-1]["status"]
                    if s["hardware_id"] == "r2a_baseline_raw"
                }
                return (
                    set(statuses) == {CLOCK_STATUS, SCAN_STATUS}
                    and all(s["level"] == 0 for s in statuses.values())
                    and statuses[SCAN_STATUS]["message"] == "fresh"
                )

            session.wait(fresh, "Healthy raw diagnostic monitor not fresh", 10)
            mission_exe = (
                Path(get_package_prefix("mission_manager")) / "lib/mission_manager/mission_server"
            )
            session.start(
                "mission",
                [
                    str(mission_exe),
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
            request = ExecuteMission.Goal(label="r2a_healthy_recovery_preparation", record=False)
            for x, y in ((0.8, 0.2), (0.0, 0.0)):
                pose = PoseStamped()
                pose.header.frame_id = "map"
                pose.pose.position.x = x
                pose.pose.position.y = y
                pose.pose.orientation.w = 1.0
                request.waypoints.append(pose)
            nav_statuses = []

            def nav_status(message):
                session.record_message(
                    "/navigate_to_pose/_action/status", message, "nav2_action_status"
                )
                nav_statuses.extend(s.status for s in message.status_list)

            session.subscriptions.append(
                session.node.create_subscription(
                    GoalStatusArray,
                    "/navigate_to_pose/_action/status",
                    nav_status,
                    QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL),
                )
            )
            future = client.send_goal_async(
                request,
                feedback_callback=lambda m: session.record_message(
                    "/missions/execute/_action/feedback", m, "mission_feedback"
                ),
            )
            session.wait(future.done, "Mission acceptance timeout", 10)
            handle = future.result()
            assert handle.accepted
            journal.record("mission_accepted", mission_id=bytes(handle.goal_id.uuid).hex())
            result = handle.get_result_async()
            session.wait(result.done, "Healthy mission timeout", 80)
            journal.record(
                "mission_result",
                status=result.result().status,
                completed_waypoints=result.result().result.completed_waypoints,
            )
            assert result.result().status == GoalStatus.STATUS_SUCCEEDED
            assert result.result().result.completed_waypoints == 2
            assert GoalStatus.STATUS_EXECUTING in nav_statuses
            journal.record("nav2_execution_observed", statuses=nav_statuses)
            session.assert_stopped()
            journal.record("robot_stop_assertions_passed")
            assert fresh()
            log = (session.directory / "localization-pipeline.log").read_text()
            consumers = {
                server: len(filter_stamps(log, server, target, "Message ready"))
                for server, target in [("controller_server", "odom"), ("planner_server", "map")]
            }
            assert all(count >= 10 for count in consumers.values())
            journal.record("healthy_consumer_checks_passed", message_ready_counts=consumers)
            client.destroy()
        assert guard.read_bytes() == original
        now = guard.stat()
        assert (now.st_ino, now.st_mtime_ns, now.st_mode) == (
            before.st_ino,
            before.st_mtime_ns,
            before.st_mode,
        )
        summary = {
            "mission_status": result.result().status,
            "completed_waypoints": 2,
            "sensor_route": "default_scan_no_relay",
            "graph": topology,
            "consumer_ready_counts": consumers,
            "guard_sha256": hashlib.sha256(original).hexdigest(),
            "guard_unchanged": True,
            "all_owned_processes_exited_zero": all(p.poll() == 0 for p in session.processes),
        }
        journal.record("healthy_baseline_verified", **summary)
        (tmp_path / "healthy-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
