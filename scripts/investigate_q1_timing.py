#!/usr/bin/env python3
"""Read-only Q1-T1 derivation; imports message decoders but never initializes ROS."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros2_ws/src/fault_injection/test"))
from assess_r2a_saved_evidence import reassess  # noqa: E402
from routing_evidence import sealed_window  # noqa: E402
from timing_evidence import compare_timing, recovery_observations  # noqa: E402


def investigate(trial: Path) -> dict:
    owner = {
        "mission_id": "0fa984ea84744da0be6c1913990dfc5e",
        "nav_goal_id": "df77fa5620314202940db798ff0bed06",
    }
    original = json.loads((trial / "routing-evidence-assessment.json").read_text())
    assert original["assessment_status"] == "INCONCLUSIVE" and original["recovery"] == "UNKNOWN"
    checked = reassess(trial, **owner)
    rows = [json.loads(line) for line in (trial / "observations.jsonl").read_text().splitlines()]
    for row in rows:
        if "cdr_base64" in row:
            assert (
                hashlib.sha256(base64.b64decode(row["cdr_base64"], validate=True)).hexdigest()
                == row["cdr_sha256"]
            )
    streams = {
        n: [r for r in rows if r["kind"] == "scan_observation" and r["stream"] == n]
        for n in ("raw", "output")
    }
    consumers = {
        n: {
            r["stamp_ns"]
            for r in rows
            if r["kind"] == "consumer_filter"
            and r["server"] == n
            and r["event"] == "Message ready"
        }
        for n in ("controller_server", "planner_server")
    }
    relay = trial / "runtime/relay"
    plan = json.loads((relay / "plan.json").read_text())
    events = [json.loads(line) for line in (relay / "events.jsonl").read_text().splitlines()]
    window = sealed_window(
        *((relay / name).read_bytes() for name in ("plan.json", "events.jsonl", "seal.json")),
        checked["expected_owner"],
    )
    execution_ns = next(e["ros_time_ns"] for e in events if e["state"] == "execution_started")
    requested_start = execution_ns + plan["delay_ns"]
    requested_stop = requested_start + plan["duration_ns"]
    clocks = [r["ros_ns"] for r in rows if r["kind"] == "clock"]
    comparison = compare_timing(
        raw=streams["raw"],
        output=streams["output"],
        consumers=consumers,
        start_ns=requested_start,
        stop_ns=requested_stop,
        count=window["affected_samples"],
    )
    for item in comparison["comparison"]:
        item["epoch_from_lifecycle"] = 0
        item["observer_clock_before_ns"] = max(
            (c for c in clocks if c <= item["observer_receipt_ros_ns"]), default=None
        )
        item["observer_clock_after_ns"] = min(
            (c for c in clocks if c >= item["observer_receipt_ros_ns"]), default=None
        )
    recovery = recovery_observations(
        streams=streams,
        consumers=consumers,
        diagnostics=[r for r in rows if r["kind"] == "diagnostic"],
        start_ns=window["start_ns"],
        stop_ns=window["stop_ns"],
        restored_ns=window["restored_ns"],
        end_ns=max(r.get("receipt_ros_ns", 0) for r in rows),
    )
    raw_stamps = [r["stamp_ns"] for r in streams["raw"]]
    return {
        "kind": "robotops.q1_t1_derived_only",
        "original_qualification": "INCONCLUSIVE",
        "original_recovery": "UNKNOWN",
        "qualification_changed": False,
        "requested_processing_interval_ns": [requested_start, requested_stop],
        "observed_lifecycle_window": window,
        "timing": comparison,
        "recovery_observations": recovery,
        "clock_observations_monotonic": all(
            a <= b for a, b in zip(clocks, clocks[1:], strict=False)
        ),
        "raw_duplicate_headers": len(raw_stamps) - len(set(raw_stamps)),
        "raw_callback_header_regressions": sum(
            a > b for a, b in zip(raw_stamps, raw_stamps[1:], strict=False)
        ),
        "source_file_hashes": checked["source_file_hashes"],
        "code_hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (
                Path(__file__),
                ROOT / "ros2_ws/src/fault_injection/test/timing_evidence.py",
                ROOT / "ros2_ws/src/fault_injection/test/routing_evidence.py",
                ROOT / "scripts/assess_r2a_saved_evidence.py",
            )
        },
        "limitations": [
            "Relay per-sample receipt/processing timestamps and ingress IDs were not recorded",
            "8.000 s is a supported boundary candidate, "
            "not a confirmed identity of the eleventh relay callback",
            "Observer receipt cannot substitute for relay receipt",
            "Existing live verifier and historical UNKNOWN remain unchanged",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trial = args.trial.resolve(strict=True)
    if args.output.resolve().is_relative_to(trial):
        raise ValueError("Derived report must be outside original trial")
    report = investigate(trial)
    for name, digest in report["source_file_hashes"].items():
        assert hashlib.sha256((trial / name).read_bytes()).hexdigest() == digest
    with args.output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print("Derived timing INCONCLUSIVE; original qualification/recovery unchanged")


if __name__ == "__main__":
    main()
