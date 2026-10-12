#!/usr/bin/env python3
"""Read-only R2a-H1 derived reassessment. Imports ROS types, never initializes ROS."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros2_ws/src/fault_injection/test"))
from routing_evidence import assess_routing_files  # noqa: E402


def reassess(trial: Path, mission_id: str, nav_goal_id: str) -> dict:
    from action_msgs.msg import GoalStatusArray
    from rclpy.serialization import deserialize_message
    from sensor_msgs.msg import LaserScan

    files = sorted(p for p in trial.rglob("*") if p.is_file())
    hashes = {str(p.relative_to(trial)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    records = [
        json.loads(line) for line in (trial / "observations.jsonl").read_text().splitlines()
    ]
    if [r["sequence"] for r in records] != list(range(1, len(records) + 1)):
        raise ValueError("Incomplete journal sequence")
    if not any(r["kind"] == "harness_exception" for r in records):
        raise ValueError("Expected preserved failed/incomplete trial journal")
    streams = {"raw": [], "output": []}
    consumers = {
        n: {"received_stamps_ns": [], "ready_stamps_ns": []}
        for n in ("controller_server", "planner_server")
    }
    executing = set()
    for row in records:
        if row["kind"] in ("scan_observation", "nav_status"):
            cdr = base64.b64decode(row["cdr_base64"], validate=True)
            if hashlib.sha256(cdr).hexdigest() != row["cdr_sha256"]:
                raise ValueError("Journal CDR digest mismatch")
            if row["kind"] == "scan_observation":
                scan = deserialize_message(cdr, LaserScan)
                t = scan.header.stamp.sec * 10**9 + scan.header.stamp.nanosec
                if t != row["stamp_ns"]:
                    raise ValueError("Journal sensor timestamp disagrees with CDR")
                streams[row["stream"]].append(
                    {
                        "stamp_ns": t,
                        "receipt_ros_ns": row["receipt_ros_ns"],
                        "frame": scan.header.frame_id,
                        "cdr_sha256": row["cdr_sha256"],
                    }
                )
            else:
                status = deserialize_message(cdr, GoalStatusArray)
                executing.update(
                    bytes(s.goal_info.goal_id.uuid).hex()
                    for s in status.status_list
                    if s.status == 2
                )
        if row["kind"] == "consumer_filter":
            server = row["server"]
            if (
                server not in consumers
                or row["frame"] != "lidar_link"
                or row["target_frame"]
                != {"controller_server": "odom", "planner_server": "map"}[server]
            ):
                raise ValueError("Unexpected consumer identity/frame")
            key = {"Added message": "received_stamps_ns", "Message ready": "ready_stamps_ns"}[
                row["event"]
            ]
            consumers[server][key].append(row["stamp_ns"])
    if nav_goal_id not in executing:
        raise ValueError("Expected Nav2 UUID lacks independent EXECUTING status")
    plan = json.loads((trial / "runtime/relay/plan.json").read_text())
    diagnostics = [r for r in records if r["kind"] == "diagnostic"]
    clocks = [r["ros_ns"] for r in records if r["kind"] == "clock"]
    topology = [r["graph"] for r in records if r["kind"] == "topology"]
    if len(topology) != 1:
        raise ValueError("Missing/ambiguous recorded sensor graph")
    owner = {k: plan[k] for k in ("experiment_id", "trial_id", "session_id")}
    owner.update(mission_id=mission_id, nav_goal_id=nav_goal_id)
    assessment = assess_routing_files(
        trial / "runtime",
        streams=streams,
        consumers=consumers,
        diagnostics=diagnostics,
        topology=topology[0],
        clocks=clocks,
        owner=owner,
        end_ns=max(r.get("receipt_ros_ns", 0) for r in records),
    )
    if any(
        hashlib.sha256(p.read_bytes()).hexdigest() != hashes[str(p.relative_to(trial))]
        for p in files
    ):
        raise RuntimeError("Source evidence changed during assessment")
    return {
        "kind": "robotops.r2a_h1_derived_reassessment",
        "original_verdict": "FAILED/INCOMPLETE",
        "qualification_changed": False,
        "scope": "saved evidence only; no ROS node or trial executed",
        "expected_owner": owner,
        "source_file_hashes": hashes,
        "assessor_sha256": hashlib.sha256(
            (ROOT / "ros2_ws/src/fault_injection/test/routing_evidence.py").read_bytes()
        ).hexdigest(),
        "loader_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "end_time_basis": (
            "latest recorded ROS receipt; decimated clock observer may lag; no invented endpoint"
        ),
        "assessment": assessment,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--nav-goal-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trial = args.trial.resolve(strict=True)
    output = args.output.resolve()
    if output.is_relative_to(trial):
        raise ValueError("Derived output must be outside original evidence directory")
    report = reassess(trial, args.mission_id, args.nav_goal_id)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(report["assessment"]["assessment_status"], "derived only; historical verdict unchanged")


if __name__ == "__main__":
    main()
