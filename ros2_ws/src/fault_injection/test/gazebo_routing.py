"""Attended bounded R2a probe; explicitly run under Xvfb, never a campaign."""

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest
from action_msgs.msg import GoalStatus, GoalStatusArray
from ament_index_python.packages import get_package_prefix
from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import PoseStamped
from rclpy.action import ActionClient
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from rclpy.serialization import serialize_message
from robotops_interfaces.action import ExecuteMission
from robotops_interfaces.msg import FaultLifecycleEvent
from robotops_interfaces.srv import FaultControlV2
from sensor_msgs.msg import LaserScan

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_evidence import OUTPUT_MONITOR, EvidenceJournal  # noqa: E402
from probe_session import ObservedNavigationSession  # noqa: E402
from routing_evidence import assess_routing_files  # noqa: E402


def stamp(message):
    return message.header.stamp.sec * 10**9 + message.header.stamp.nanosec


def graph(node):
    def endpoint(e):
        return {
            "node": e.node_name,
            "namespace": e.node_namespace,
            "type": e.topic_type,
            "reliability": e.qos_profile.reliability.name,
            "durability": e.qos_profile.durability.name,
            "depth": e.qos_profile.depth,
        }

    return {
        topic: {
            "publishers": [endpoint(e) for e in node.get_publishers_info_by_topic(topic)],
            "subscribers": [endpoint(e) for e in node.get_subscriptions_info_by_topic(topic)],
        }
        for topic in ("/scan", "/fault_probe/scan", "/fault_probe/diagnostics")
    }


class RoutedSession(ObservedNavigationSession):
    def __init__(self, directory, map_file, runtime, journal):
        self.runtime = runtime
        super().__init__(directory, map_file, "navfn_rpp", journal)

    def pipeline_command(self):
        return [
            "ros2",
            "launch",
            "fault_injection",
            "nav2_probe.launch.py",
            "mode:=sim",
            f"runtime_directory:={self.runtime}",
            f"map_file:={self.map_file}",
            "experiment_id:=r2a_probe",
            "trial_id:=trial",
        ]


def filter_stamps(log, server, target, event):
    pattern = (
        rf"\[{server}-\d+\].*MessageFilter \[target={target}[^\]]*\]: "
        rf"{event} in frame lidar_link at time ([0-9.]+)"
    )
    return {round(float(t) * 10**9) for t in re.findall(pattern, log)}


def test_real_routed_dropout(tmp_path):
    with EvidenceJournal(tmp_path / "observations.jsonl") as journal:
        _run_routed_dropout(tmp_path, journal)


def _run_routed_dropout(tmp_path, journal):
    map_file = Path(os.environ.get("ROBOTOPS_FAULT_TEST_MAP", ""))
    if not map_file.is_file():
        pytest.skip("Supply qualified mapping_lab map via ROBOTOPS_FAULT_TEST_MAP")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    streams = {"raw": [], "output": []}
    lifecycle, statuses, diagnostics = [], [], []
    with RoutedSession(tmp_path / "navigation", map_file, runtime, journal) as session:
        session.initialize()
        durable = QoSProfile(depth=32, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        for name, topic in (("raw", "/scan"), ("output", "/fault_probe/scan")):

            def observe(msg, name=name, topic=topic):
                receipt_ros_ns = session.record_message(
                    topic if name == "output" else "/scan",
                    msg,
                    "scan_observation",
                    stream=name,
                    stamp_ns=stamp(msg),
                    frame=msg.header.frame_id,
                )
                streams[name].append(
                    {
                        "stamp_ns": stamp(msg),
                        "receipt_ros_ns": receipt_ros_ns,
                        "frame": msg.header.frame_id,
                        "cdr_sha256": hashlib.sha256(serialize_message(msg)).hexdigest(),
                    }
                )

            session.subscriptions.append(
                session.node.create_subscription(
                    LaserScan, topic, observe, qos_profile_sensor_data
                )
            )

        def on_lifecycle(message):
            session.record_message(
                "/fault_lifecycle_events",
                message,
                "lifecycle",
                state=message.evidence.state,
                ros_ns=message.evidence.ros_time_ns,
                mission_id=message.mission_id,
                nav_goal_id=message.nav_goal_id,
                recovery_verified=message.recovery_verified,
            )
            lifecycle.append(message)

        def on_status(message):
            session.record_message("/navigate_to_pose/_action/status", message, "nav_status")
            statuses.append(message)

        session.subscriptions.extend(
            [
                session.node.create_subscription(
                    FaultLifecycleEvent, "fault_lifecycle_events", on_lifecycle, durable
                ),
                session.node.create_subscription(
                    GoalStatusArray, "navigate_to_pose/_action/status", on_status, durable
                ),
                session.node.create_subscription(
                    DiagnosticArray,
                    "/fault_probe/diagnostics",
                    lambda m: session.diagnostics(diagnostics, "/fault_probe/diagnostics", m),
                    20,
                ),
            ]
        )
        monitor = (
            Path(get_package_prefix("robot_diagnostics"))
            / "lib/robot_diagnostics/freshness_monitor"
        )
        session.start(
            "output-monitor",
            [
                str(monitor),
                "--ros-args",
                "-p",
                "use_sim_time:=true",
                "-p",
                "enabled_streams:=[scan]",
                "-p",
                f"hardware_id:={OUTPUT_MONITOR}",
                "-r",
                "__node:=output_scan_monitor",
                "-r",
                "scan:=/fault_probe/scan",
                "-r",
                "diagnostics:=/fault_probe/diagnostics",
            ],
        )
        control = session.node.create_client(FaultControlV2, "fault_control")
        assert control.wait_for_service(timeout_sec=10)
        session.wait(
            lambda: lifecycle and len(streams["output"]) >= 10, "Pending relay not healthy", 10
        )
        topology = graph(session.node)
        journal.record("topology", graph=topology)
        assert (
            len(topology["/scan"]["publishers"])
            == len(topology["/fault_probe/scan"]["publishers"])
            == 1
        )
        raw_subs = {e["node"] for e in topology["/scan"]["subscribers"]}
        out_subs = {e["node"] for e in topology["/fault_probe/scan"]["subscribers"]}
        assert "amcl" in raw_subs and not {"local_costmap", "global_costmap"} & raw_subs
        assert {"local_costmap", "global_costmap", "output_scan_monitor"} <= out_subs
        assert "amcl" not in out_subs
        assert all(
            e["reliability"] == "BEST_EFFORT" and e["durability"] == "VOLATILE"
            for topic in ("/scan", "/fault_probe/scan")
            for e in topology[topic]["publishers"] + topology[topic]["subscribers"]
        )
        log_path = session.directory / "localization-pipeline.log"
        for server, target in (("controller_server", "odom"), ("planner_server", "map")):
            session.wait(
                lambda server=server, target=target: filter_stamps(
                    log_path.read_text(), server, target, "Message ready"
                ),
                f"No healthy {server} filter delivery",
                5,
            )
        assert not any(e.evidence.state == "effect_observed" for e in lifecycle)
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
        request = ExecuteMission.Goal(label="r2a_controlled_probe", record=False)
        for x, y in ((0.8, 0.2), (0.0, 0.0)):
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.pose.position.x = x
            pose.pose.position.y = y
            pose.pose.orientation.w = 1.0
            request.waypoints.append(pose)
        future = client.send_goal_async(request)
        session.wait(future.done, "Mission acceptance timeout", 10)
        handle = future.result()
        assert handle.accepted
        result = handle.get_result_async()
        plan = json.loads((runtime / "relay/plan.json").read_text())

        def command(operation, nav=""):
            req = FaultControlV2.Request(
                operation=operation,
                experiment_id="r2a_probe",
                trial_id="trial",
                session_id=plan["session_id"],
                plan_sha256=hashlib.sha256((runtime / "relay/plan.json").read_bytes()).hexdigest(),
                mission_id=bytes(handle.goal_id.uuid).hex(),
                nav_goal_id=nav,
            )
            response = control.call_async(req)
            session.wait(response.done, "Owner control timeout", 5)
            journal.record(
                "owner_control_response",
                operation=operation,
                accepted=response.result().accepted,
                state=response.result().state,
                recovery_verified=response.result().recovery_verified,
            )
            return response.result()

        assert command(1).accepted
        session.wait(
            lambda: statuses and any(s.status == 2 for s in statuses[-1].status_list),
            "No Nav2 executing goal",
            15,
        )
        nav = next(s for s in statuses[-1].status_list if s.status == 2)
        assert command(2, bytes(nav.goal_info.goal_id.uuid).hex()).accepted
        session.wait(
            lambda: any(e.evidence.state == "recovery_verified" for e in lifecycle),
            "Relay did not restore",
            15,
        )
        session.spin_for(1.0)
        session.wait(result.done, "Mission timeout", 80)
        journal.record(
            "mission_result",
            status=result.result().status,
            completed_waypoints=result.result().result.completed_waypoints,
        )
        assert result.result().status == GoalStatus.STATUS_SUCCEEDED
        assert result.result().result.completed_waypoints == 2
        session.assert_stopped()
        journal.record("robot_stop_assertions_passed")
        assert not command(1).accepted and not (runtime / "recovery.guard").exists()
        assert sum(e.evidence.state == "execution_started" for e in lifecycle) == 1
        assert sum(e.evidence.state == "effect_observed" for e in lifecycle) == 1
        # Freeze observation end before shutdown. Final consumer logs and seal are
        # evaluated only after all owned processes have finished; no global-gap heuristic.
        end_ns = session.node.get_clock().now().nanoseconds
        client.destroy()
    log = log_path.read_text()
    consumers = {
        server: {
            "received_stamps_ns": sorted(filter_stamps(log, server, target, "Added message")),
            "ready_stamps_ns": sorted(filter_stamps(log, server, target, "Message ready")),
        }
        for server, target in (("controller_server", "odom"), ("planner_server", "map"))
    }
    owner = {
        "experiment_id": "r2a_probe",
        "trial_id": "trial",
        "session_id": plan["session_id"],
        "mission_id": bytes(handle.goal_id.uuid).hex(),
        "nav_goal_id": bytes(nav.goal_info.goal_id.uuid).hex(),
    }
    assessment = assess_routing_files(
        runtime,
        streams=streams,
        consumers=consumers,
        diagnostics=diagnostics,
        topology=topology,
        clocks=session.clock_observations,
        owner=owner,
        end_ns=end_ns,
    )
    # Persist all classifications, including unknowns, BEFORE asserting qualification.
    journal.record("routing_evidence_assessment", **assessment)
    (tmp_path / "routing-evidence-assessment.json").write_text(
        json.dumps(assessment, indent=2) + "\n"
    )
    assert assessment["assessment_status"] == "SUPPORTED", assessment
    summary = {
        "graph": topology,
        "mission_id": owner["mission_id"],
        "nav_goal_id": owner["nav_goal_id"],
        "states": [e.evidence.state for e in lifecycle],
        "mission_status": result.result().status,
        "completed_waypoints": 2,
        "missing_output_stamps_ns": assessment["intentional_stamps_ns"],
        "consumer_filter_evidence": consumers,
        "independent_streams": streams,
        "diagnostics": diagnostics,
        "diagnostic_window": assessment["diagnostic_window"],
        "downstream_recovery_verified": True,
        "local_guard_released": True,
    }
    (tmp_path / "routing-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    # Never unlock on exception, crash, disconnect, failed observation or failed cleanup.
    (tmp_path / "clean-exit.json").write_text('{"all_owned_processes_exited_zero":true}\n')
    journal.record("qualified_for_owner_review", routing_guard_retained=True)
