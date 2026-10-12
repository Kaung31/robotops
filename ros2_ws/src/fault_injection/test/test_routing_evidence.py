"""Offline R2a-H1 fixtures; no ROS initialization or processes."""

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_evidence import CLOCK_STATUS, OUTPUT_MONITOR, SCAN_STATUS  # noqa: E402
from routing_evidence import STATES, assess_routing  # noqa: E402

NS = 1_000_000_000


def wire(value):
    return json.dumps(value, sort_keys=True).encode()


def reseal(fixture, events=None, plan=None):
    if plan is not None:
        fixture["plan_bytes"] = wire(plan)
    if events is None:
        events = [json.loads(line) for line in fixture["events_bytes"].splitlines()]
    plan_hash = hashlib.sha256(fixture["plan_bytes"]).hexdigest()
    for e in events:
        e["plan_sha256"] = plan_hash
    fixture["events_bytes"] = b"\n".join(wire(e) for e in events) + b"\n"
    fixture["seal_bytes"] = wire(
        {
            "termination": "closed",
            "schema_version": 2,
            "event_count": len(events),
            "plan_sha256": plan_hash,
            "events_sha256": hashlib.sha256(fixture["events_bytes"]).hexdigest(),
        }
    )


def diagnostic(t, level=0, reason="fresh", age=0.1, last=None):
    return {
        "stamp_ns": int(t * NS),
        "status": [
            {"name": CLOCK_STATUS, "hardware_id": OUTPUT_MONITOR, "level": 0},
            {
                "name": SCAN_STATUS,
                "hardware_id": OUTPUT_MONITOR,
                "level": level,
                "message": reason,
                "values": {
                    "advancing_samples": "2",
                    "warn_seconds": "0.5",
                    "receipt_age_seconds": str(age),
                    "stamp_age_seconds": str(age),
                    "stamp_ns": str(int((t - age if last is None else last) * NS)),
                },
            },
        ],
    }


@pytest.fixture
def evidence():
    owner = {
        "experiment_id": "experiment",
        "trial_id": "trial",
        "session_id": "session",
        "mission_id": "a" * 32,
        "nav_goal_id": "b" * 32,
    }
    plan = {
        **{k: owner[k] for k in ("experiment_id", "trial_id", "session_id")},
        "schema_version": 2,
        "mode": "sim",
        "fault_type": "dropout",
        "target": "scan",
        "input_topic": "/scan",
        "output_topic": "/fault_probe/scan",
        "delay_ns": NS // 2,
        "duration_ns": NS,
    }
    times = [0, 1.3, 1.4, 1.5, 2, 2.01, 3, 3, 3.1]
    events = [
        {
            **owner,
            "state": state,
            "sequence": i + 1,
            "clock_epoch": 0,
            "ros_time_ns": int(times[i] * NS),
            "applied_confirmed": state == "effect_observed",
            "affected_samples": 10 if i >= 6 else 1 if i == 5 else 0,
            "recovery_verified": state == "recovery_verified",
        }
        for i, state in enumerate(STATES)
    ]
    raw = [
        {
            "stamp_ns": i * 100_000_000,
            "receipt_ros_ns": i * 100_000_000 + 10_000_000,
            "frame": "lidar_link",
            "cdr_sha256": hashlib.sha256(str(i).encode()).hexdigest(),
        }
        for i in range(10, 101)
    ]
    output = [copy.deepcopy(r) for r in raw if not 2 * NS <= r["stamp_ns"] < 3 * NS]

    def endpoint(node):
        return {
            "node": node,
            "reliability": "BEST_EFFORT",
            "durability": "VOLATILE",
            "namespace": {
                "local_costmap": "/local_costmap",
                "global_costmap": "/global_costmap",
            }.get(node, "/"),
            "type": "sensor_msgs/msg/LaserScan",
        }

    fixture = {
        "owner": owner,
        "plan_bytes": wire(plan),
        "events_bytes": b"",
        "seal_bytes": b"",
        "streams": {"raw": raw, "output": output},
        "consumers": {
            n: {
                "received_stamps_ns": [r["stamp_ns"] for r in output],
                "ready_stamps_ns": [r["stamp_ns"] for r in output],
            }
            for n in ("controller_server", "planner_server")
        },
        "topology": {
            "/scan": {
                "publishers": [endpoint("simulation_bridge")],
                "subscribers": [endpoint("amcl"), endpoint("scan_fault_relay")],
            },
            "/fault_probe/scan": {
                "publishers": [endpoint("scan_fault_relay")],
                "subscribers": [
                    endpoint(n) for n in ("local_costmap", "global_costmap", "output_scan_monitor")
                ],
            },
        },
        "diagnostics": [
            diagnostic(1.9),
            diagnostic(2.7, 1, "age_warning", 0.7),
            diagnostic(3.4),
            diagnostic(3.6),
            diagnostic(9.8),
            diagnostic(9.9),
        ],
        "clocks": [i * 100_000_000 for i in range(101)],
        "end_ns": 10 * NS,
    }
    reseal(fixture, events)
    return fixture


def test_ten_scan_dropout_and_recovery(evidence):
    report = assess_routing(**evidence)
    assert report["assessment_status"] == "SUPPORTED", report
    assert report["recovery"] == "VERIFIED"
    assert len(report["intentional_stamps_ns"]) == 10
    assert len(report["recovery_sample_stamps_ns"]) >= 5
    assert not report["historical_verdict_changed"]


def test_late_observer_omission_is_corroborated_not_fault(evidence):
    baseline = assess_routing(**evidence)
    evidence["streams"]["output"] = [
        r for r in evidence["streams"]["output"] if r["stamp_ns"] != 9.5 * NS
    ]
    report = assess_routing(**evidence)
    assert report["assessment_status"] == "SUPPORTED", report
    assert report["intentional_stamps_ns"] == baseline["intentional_stamps_ns"]
    assert report["classification"][-1] == {
        "stamp_ns": int(9.5 * NS),
        "category": "OBSERVER_ONLY_OMISSION",
    }
    assert report["window"] == baseline["window"]


def remove_delivery(evidence, stamps):
    evidence["streams"]["output"] = [
        r for r in evidence["streams"]["output"] if r["stamp_ns"] not in stamps
    ]
    for consumer in evidence["consumers"].values():
        for key in consumer:
            consumer[key] = [s for s in consumer[key] if s not in stamps]


def test_positive_starvation_evidence_marks_unexpected_loss(evidence):
    remove_delivery(evidence, set(range(7 * NS, 8 * NS, 100_000_000)))
    evidence["diagnostics"].append(diagnostic(7.7, 2, "receipt_timeout", 0.8, 6.9))
    evidence["diagnostics"].sort(key=lambda r: r["stamp_ns"])
    report = assess_routing(**evidence)
    assert report["assessment_status"] == "FAIL", report
    assert any(
        r["category"] == "CONFIRMED_UNEXPECTED_DELIVERY_LOSS" for r in report["classification"]
    )


@pytest.mark.parametrize("one_consumer", [False, True])
def test_omission_without_independent_corroboration_is_unknown(evidence, one_consumer):
    remove_delivery(evidence, {7 * NS})
    if one_consumer:
        for key in evidence["consumers"]["planner_server"]:
            evidence["consumers"]["planner_server"][key].append(7 * NS)
    report = assess_routing(**evidence)
    assert report["assessment_status"] == "INCONCLUSIVE", report
    assert {"stamp_ns": 7 * NS, "category": "UNKNOWN"} in report["classification"]


@pytest.mark.parametrize("consumer", ["both", "controller_server", "planner_server"])
def test_no_or_one_costmap_recovery_cannot_pass(evidence, consumer):
    for n in evidence["consumers"]:
        if consumer == "both" or n == consumer:
            for key in evidence["consumers"][n]:
                evidence["consumers"][n][key] = [
                    s for s in evidence["consumers"][n][key] if s < 3 * NS
                ]
    report = assess_routing(**evidence)
    assert report["assessment_status"] != "SUPPORTED"
    assert report["recovery"] == "UNKNOWN"


@pytest.mark.parametrize(
    "defect",
    [
        "time",
        "mission",
        "nav",
        "effect",
        "count",
        "seal",
        "epoch",
        "sequence",
        "not_restored",
        "wrong_sensor",
    ],
)
def test_invalid_sealed_contract_never_passes(evidence, defect):
    events = [json.loads(line) for line in evidence["events_bytes"].splitlines()]
    if defect == "time":
        events[6]["ros_time_ns"] += NS
    if defect == "mission":
        events[4]["mission_id"] = "other"
    if defect == "nav":
        events[4]["nav_goal_id"] = "other"
    if defect == "effect":
        events[5]["applied_confirmed"] = False
    if defect == "count":
        events[-1]["affected_samples"] -= 1
    if defect == "epoch":
        events[-1]["clock_epoch"] = 1
    if defect == "sequence":
        events[-1]["sequence"] -= 1
    if defect == "not_restored":
        events[-1]["recovery_verified"] = False
    reseal(evidence, events)
    if defect == "seal":
        evidence["events_bytes"] += b"\n"
    if defect == "wrong_sensor":
        plan = json.loads(evidence["plan_bytes"])
        plan["input_topic"] = "/other"
        reseal(evidence, plan=plan)
    assert assess_routing(**evidence)["assessment_status"] != "SUPPORTED"


@pytest.mark.parametrize(
    "defect", ["duplicate", "out_of_order", "conflict", "delayed", "clock_reset", "missing_clock"]
)
def test_observation_order_and_clock_are_explicit(evidence, defect):
    raw = evidence["streams"]["raw"]
    if defect == "duplicate":
        raw.append(copy.deepcopy(raw[0]))
    if defect == "out_of_order":
        raw[0], raw[1] = raw[1], raw[0]
    if defect == "conflict":
        row = copy.deepcopy(raw[0])
        row["cdr_sha256"] = "0" * 64
        raw.append(row)
    if defect == "delayed":
        for row in evidence["streams"]["output"]:
            if row["stamp_ns"] > 3 * NS:
                row["receipt_ros_ns"] += NS
    if defect == "clock_reset":
        evidence["clocks"][50] = 0
    if defect == "missing_clock":
        evidence["clocks"] = []
    report = assess_routing(**evidence)
    if defect in ("duplicate", "out_of_order"):
        assert report["assessment_status"] == "SUPPORTED", report
        assert report["observation_issues"]
    else:
        assert report["assessment_status"] != "SUPPORTED"


@pytest.mark.parametrize(
    "defect",
    ["none", "no_degradation", "no_recovery", "wrong_monitor", "clock_failed", "incomplete"],
)
def test_incomplete_diagnostics_never_pass(evidence, defect):
    if defect == "none":
        evidence["diagnostics"] = []
    if defect == "no_degradation":
        evidence["diagnostics"][1] = diagnostic(2.7)
    if defect == "no_recovery":
        evidence["diagnostics"] = evidence["diagnostics"][:2]
    if defect == "wrong_monitor":
        for row in evidence["diagnostics"]:
            for s in row["status"]:
                s["hardware_id"] = "wrong"
    if defect == "clock_failed":
        evidence["diagnostics"][1]["status"][0]["level"] = 3
    if defect == "incomplete":
        for row in evidence["diagnostics"]:
            row["status"] = row["status"][1:]
    assert assess_routing(**evidence)["assessment_status"] != "SUPPORTED"


@pytest.mark.parametrize(
    "defect",
    [
        "route",
        "fault_delivery",
        "raw_incomplete",
        "payload",
        "no_post_output",
        "too_few_recovered",
    ],
)
def test_bypass_and_missing_sensor_evidence_never_pass(evidence, defect):
    if defect == "route":
        evidence["topology"]["/scan"]["subscribers"].append({"node": "local_costmap"})
    if defect == "fault_delivery":
        evidence["consumers"]["controller_server"]["received_stamps_ns"].append(2 * NS)
    if defect == "raw_incomplete":
        evidence["streams"]["raw"] = [
            r for r in evidence["streams"]["raw"] if r["stamp_ns"] != 2.5 * NS
        ]
    if defect == "payload":
        evidence["streams"]["output"][0]["cdr_sha256"] = "0" * 64
    if defect == "no_post_output":
        evidence["streams"]["output"] = evidence["streams"]["output"][:5]
    if defect == "too_few_recovered":
        for consumer in evidence["consumers"].values():
            for key in consumer:
                consumer[key] = [s for s in consumer[key] if s < 3 * NS or 4 * NS <= s < 4.4 * NS]
    assert assess_routing(**evidence)["assessment_status"] != "SUPPORTED"


@pytest.mark.parametrize("missing", [None, "plan.json", "events.jsonl", "seal.json"])
def test_existing_file_boundary_is_read_only_and_missing_is_inconclusive(
    evidence, tmp_path, missing
):
    from routing_evidence import assess_routing_files

    relay = tmp_path / "relay"
    relay.mkdir()
    data = copy.deepcopy(evidence)
    for name, key in (
        ("plan.json", "plan_bytes"),
        ("events.jsonl", "events_bytes"),
        ("seal.json", "seal_bytes"),
    ):
        content = data.pop(key)
        if name != missing:
            (relay / name).write_bytes(content)
    guard = tmp_path / "routing.guard"
    guard.write_bytes(b"held quarantine\n")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    report = assess_routing_files(tmp_path, **data)
    assert report["assessment_status"] == ("SUPPORTED" if missing is None else "INCONCLUSIVE")
    assert len(report["unavailable_relay_files"]) == int(missing is not None)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_missing_count_does_not_confirm_provisional_suppression(evidence):
    evidence["streams"]["raw"] = [
        r for r in evidence["streams"]["raw"] if r["stamp_ns"] != 2.5 * NS
    ]
    report = assess_routing(**evidence)
    assert report["assessment_status"] == "INCONCLUSIVE"
    assert not any(r["category"] == "INTENTIONAL_SUPPRESSION" for r in report["classification"])


def test_confirmed_unexpected_loss_is_not_hidden_by_incomplete_recovery(evidence):
    remove_delivery(evidence, set(range(7 * NS, 8 * NS, 100_000_000)))
    evidence["diagnostics"].append(diagnostic(7.7, 2, "receipt_timeout", 0.8, 6.9))
    evidence["diagnostics"].sort(key=lambda r: r["stamp_ns"])
    evidence["diagnostics"] = [r for r in evidence["diagnostics"] if r["stamp_ns"] < 8 * NS]
    report = assess_routing(**evidence)
    assert report["assessment_status"] == "FAIL"


@pytest.mark.parametrize("defect", ["namespace", "type", "unobserved_bypass", "bad_end"])
def test_sensor_identity_and_unpaired_bypass_fail_closed(evidence, defect):
    if defect == "namespace":
        evidence["topology"]["/fault_probe/scan"]["subscribers"][0]["namespace"] = "/rogue"
    if defect == "type":
        evidence["topology"]["/fault_probe/scan"]["publishers"][0]["type"] = "other/msg/Scan"
    if defect == "unobserved_bypass":
        evidence["consumers"]["planner_server"]["received_stamps_ns"].append(2_050_000_000)
    if defect == "bad_end":
        evidence["end_ns"] = None
    assert assess_routing(**evidence)["assessment_status"] != "SUPPORTED"


@pytest.mark.parametrize(
    "defect",
    [
        "ordered_duplicates",
        "out_of_order",
        "conflicting_duplicate",
        "stale_masked_by_delay",
        "missing_tail",
        "future_timestamp",
    ],
)
def test_diagnostic_order_coverage_and_conflicts(evidence, defect):
    diagnostics = evidence["diagnostics"]
    if defect == "ordered_duplicates":
        diagnostics.append(copy.deepcopy(diagnostics[-1]))
    if defect == "out_of_order":
        diagnostics[-1], diagnostics[-2] = diagnostics[-2], diagnostics[-1]
    if defect == "conflicting_duplicate":
        diagnostics.append(diagnostic(9.9, 3, "receipt_timeout", 1.0))
    if defect == "stale_masked_by_delay":
        diagnostics[-1] = diagnostic(9.9, 3, "receipt_timeout", 1.0)
        diagnostics.extend([diagnostic(3.4), diagnostic(3.6)])
    if defect == "missing_tail":
        evidence["diagnostics"] = diagnostics[:4]
    if defect == "future_timestamp":
        diagnostics.append(diagnostic(11))
    report = assess_routing(**evidence)
    if defect in ("ordered_duplicates", "out_of_order"):
        assert report["assessment_status"] == "SUPPORTED", report
        assert report["observation_issues"]
    else:
        assert report["assessment_status"] != "SUPPORTED", report


@pytest.mark.parametrize("corroborated", [True, False])
def test_boundary_margin_never_hides_an_observer_omission(evidence, corroborated):
    stamp = 9_900_000_000
    evidence["streams"]["output"] = [
        r for r in evidence["streams"]["output"] if r["stamp_ns"] != stamp
    ]
    if not corroborated:
        for consumer in evidence["consumers"].values():
            for key in consumer:
                consumer[key] = [s for s in consumer[key] if s != stamp]
    report = assess_routing(**evidence)
    assert stamp in report["boundary_unassessed_stamps_ns"]
    assert {
        "stamp_ns": stamp,
        "category": "OBSERVER_ONLY_OMISSION" if corroborated else "UNKNOWN",
    } in report["classification"]
    assert report["assessment_status"] == ("SUPPORTED" if corroborated else "INCONCLUSIVE")
