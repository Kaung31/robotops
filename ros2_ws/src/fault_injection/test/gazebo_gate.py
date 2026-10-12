"""Bounded real Nav2/mission signal probe; relay sink never feeds robot navigation."""

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
from action_msgs.msg import GoalStatus, GoalStatusArray
from ament_index_python.packages import get_package_prefix
from geometry_msgs.msg import PoseStamped
from rclpy.action import ActionClient
from rclpy.qos import DurabilityPolicy, QoSProfile
from robotops_interfaces.action import ExecuteMission
from robotops_interfaces.msg import FaultLifecycleEvent
from robotops_interfaces.srv import FaultControlV2

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "robot_navigation/test"))
from navigation_system import NavigationSession  # noqa: E402


def test_real_owned_execution_gate(tmp_path):
    map_file = Path(os.environ.get("ROBOTOPS_FAULT_TEST_MAP", ""))
    if not map_file.is_file():
        pytest.skip("Supply an existing qualified mapping_lab map via ROBOTOPS_FAULT_TEST_MAP")
    with NavigationSession(tmp_path / "navigation", map_file, "navfn_rpp") as session:
        session.initialize()
        relay = (
            Path(get_package_prefix("fault_injection")) / "lib/fault_injection/scan_fault_relay"
        )
        evidence = tmp_path / "owned"
        guard = tmp_path / "recovery.guard"
        session.start(
            "relay",
            [
                str(relay),
                "--ros-args",
                "-p",
                "mode:=sim",
                "-p",
                "use_sim_time:=true",
                "-p",
                "lifecycle_mode:=owned_v2",
                "-p",
                "experiment_id:=gazebo_probe",
                "-p",
                "trial_id:=trial",
                "-p",
                "fault_type:=dropout",
                "-p",
                "delay_seconds:=0.2",
                "-p",
                "duration_seconds:=0.3",
                "-p",
                f"evidence_directory:={evidence}",
                "-p",
                f"recovery_guard_path:={guard}",
                "-r",
                "scan_input:=/scan",
                "-r",
                "scan_output:=/r1_probe_scan",
            ],
        )
        lifecycle, statuses = [], []
        durable = QoSProfile(depth=32, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        session.subscriptions.extend(
            [
                session.node.create_subscription(
                    FaultLifecycleEvent, "fault_lifecycle_events", lifecycle.append, durable
                ),
                session.node.create_subscription(
                    GoalStatusArray, "navigate_to_pose/_action/status", statuses.append, durable
                ),
            ]
        )
        control = session.node.create_client(FaultControlV2, "fault_control")
        assert control.wait_for_service(timeout_sec=10)
        session.wait(lambda: lifecycle, "No requested lifecycle evidence", 10)
        session.spin_for(0.3)
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
        request = ExecuteMission.Goal(label="r1_gate_probe", record=False)
        for x, y in ((0.8, 0.2), (0.0, 0.0)):
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.pose.position.x, pose.pose.position.y = x, y
            pose.pose.orientation.w = 1.0
            request.waypoints.append(pose)
        future = client.send_goal_async(request)
        session.wait(future.done, "Mission response timeout", 10)
        handle = future.result()
        assert handle.accepted
        result = handle.get_result_async()
        plan = json.loads((evidence / "plan.json").read_text())

        def command(operation, nav=""):
            req = FaultControlV2.Request(
                operation=operation,
                experiment_id="gazebo_probe",
                trial_id="trial",
                session_id=plan["session_id"],
                plan_sha256=hashlib.sha256((evidence / "plan.json").read_bytes()).hexdigest(),
                mission_id=bytes(handle.goal_id.uuid).hex(),
                nav_goal_id=nav,
            )
            response = control.call_async(req)
            session.wait(response.done, "Fault owner response timeout", 5)
            return response.result()

        assert command(1).accepted
        session.wait(
            lambda: statuses and any(s.status == 2 for s in statuses[-1].status_list),
            "No actual Nav2 executing status",
            15,
        )
        nav = next(s for s in statuses[-1].status_list if s.status == 2)
        assert command(2, bytes(nav.goal_info.goal_id.uuid).hex()).accepted
        session.wait(
            lambda: any(e.evidence.state == "recovery_verified" for e in lifecycle),
            "Real Nav2 signal / sink restoration not confirmed",
            15,
        )
        session.wait(result.done, "Normal two-waypoint mission did not finish", 90)
        assert result.result().status == GoalStatus.STATUS_SUCCEEDED
        assert result.result().result.completed_waypoints == 2
        session.assert_stopped()
        assert sum(e.evidence.state == "execution_started" for e in lifecycle) == 1
        assert sum(e.evidence.state == "effect_observed" for e in lifecycle) == 1
        assert not command(1).accepted and not guard.exists()
        assert session.node.count_publishers("/scan") == 1
        assert session.node.count_publishers("/r1_probe_scan") == 1
        (tmp_path / "gate-summary.json").write_text(
            json.dumps(
                {
                    "mission_status": result.result().status,
                    "completed_waypoints": 2,
                    "states": [e.evidence.state for e in lifecycle],
                    "robot_scan_remapped": False,
                    "guard_released": not guard.exists(),
                },
                indent=2,
            )
            + "\n"
        )
        client.destroy()
