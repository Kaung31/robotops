"""Offline proposed-contract fixtures; no transport, fault activation or guard writes."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_routing_evidence import evidence as routing_fixture  # noqa: E402
from timing_evidence import compare_timing, recovery_observations  # noqa: E402


@pytest.fixture
def evidence():
    return routing_fixture.__wrapped__()


NS = 1_000_000_000


def fixture_case(stamp=NS, processing=2 * NS, suppressed=True):
    rows = [
        {
            "stamp_ns": stamp,
            "receipt_ros_ns": processing,
            "frame": "lidar_link",
            "cdr_sha256": "a" * 64,
        }
    ] + [
        {
            "stamp_ns": i * NS,
            "receipt_ros_ns": i * NS,
            "frame": "lidar_link",
            "cdr_sha256": str(i) * 64,
        }
        for i in range(3, 7)
    ]
    decisions = [
        {
            "sequence": i + 1,
            "epoch": 0,
            "stamp_ns": r["stamp_ns"],
            "receipt_ns": r["receipt_ros_ns"],
            "processing_ns": r["receipt_ros_ns"],
            "cdr_sha256": r["cdr_sha256"],
            "suppressed": suppressed if i == 0 else True,
        }
        for i, r in enumerate(rows)
    ]
    # Unique final sample forwarded, supplies a non-empty output observer.
    last = {
        "stamp_ns": 8 * NS,
        "receipt_ros_ns": 8 * NS,
        "frame": "lidar_link",
        "cdr_sha256": "f" * 64,
    }
    rows.append(last)
    decisions.append(
        {
            "sequence": 6,
            "epoch": 0,
            "stamp_ns": 8 * NS,
            "receipt_ns": 8 * NS,
            "processing_ns": 8 * NS,
            "cdr_sha256": "f" * 64,
            "suppressed": False,
        }
    )
    return {
        "raw": rows,
        "output": [last] + ([] if suppressed else [rows[0]]),
        "consumers": {
            n: [8 * NS] + ([] if suppressed else [stamp])
            for n in ("controller_server", "planner_server")
        },
        "start_ns": 2 * NS,
        "stop_ns": 7 * NS,
        "count": 5 if suppressed else 4,
        "decisions": decisions,
    }


@pytest.mark.parametrize("stamp,processing", [(2 * NS, 2 * NS), (NS, 2 * NS), (NS, 2 * NS + 5)])
def test_matching_preacquired_and_exact_activation(stamp, processing):
    data = fixture_case(stamp, processing)
    assert compare_timing(**data)["status"] == "SUPPORTED_FIXTURE_CONTRACT"


@pytest.mark.parametrize("processing", [7 * NS, 7 * NS + 100])
@pytest.mark.parametrize("stamp", [2 * NS, 7 * NS])
def test_inside_acquisition_processed_at_or_after_deactivation(processing, stamp):
    data = fixture_case(stamp, processing, False)
    # Supply a fifth suppressed message so the unchanged minimum-five gate holds.
    extra = copy.deepcopy(data["raw"][1])
    extra["stamp_ns"] = 6 * NS + 1
    extra["receipt_ros_ns"] = 6 * NS + 1
    data["raw"].insert(-1, extra)
    data["decisions"][0]["processing_ns"] = processing
    data["decisions"].insert(
        -1,
        {
            "epoch": 0,
            "stamp_ns": extra["stamp_ns"],
            "receipt_ns": extra["receipt_ros_ns"],
            "processing_ns": extra["receipt_ros_ns"],
            "cdr_sha256": extra["cdr_sha256"],
            "suppressed": True,
        },
    )
    data["decisions"].sort(key=lambda r: r["processing_ns"])
    for i, d in enumerate(data["decisions"]):
        d["sequence"] = i + 1
    data["count"] = 5
    assert compare_timing(**data)["status"] == "SUPPORTED_FIXTURE_CONTRACT"


@pytest.mark.parametrize(
    "defect",
    [
        "no_decisions",
        "duplicate",
        "incomplete",
        "wrong_hash",
        "bypass",
        "unexpected_suppression",
        "order",
        "clock_reset",
        "count",
        "late_receipt",
        "missing_output",
    ],
)
def test_invalid_or_insufficient_contract_never_supported(defect):
    data = fixture_case()
    if defect == "no_decisions":
        data["decisions"] = None
    if defect == "duplicate":
        data["raw"].append(copy.deepcopy(data["raw"][0]))
    if defect == "incomplete":
        data["raw"].pop(1)
    if defect == "wrong_hash":
        data["decisions"][0]["cdr_sha256"] = "0" * 64
    if defect == "bypass":
        data["consumers"]["planner_server"].append(NS)
    if defect == "unexpected_suppression":
        data["decisions"][-1]["suppressed"] = True
    if defect == "order":
        data["decisions"][2]["processing_ns"] = NS
    if defect == "clock_reset":
        data["decisions"][-1]["epoch"] = 1
    if defect == "count":
        data["count"] += 1
    if defect == "late_receipt":
        data["decisions"][0]["receipt_ns"] += NS
    if defect == "missing_output":
        data["output"] = []
    assert compare_timing(**data)["status"] == "INCONCLUSIVE"


def test_acquisition_count_not_equated_to_callback_count():
    data = fixture_case()
    data["decisions"] = None
    result = compare_timing(**data)
    assert result["acquisition_window_missing_count"] == 4
    assert result["sealed_callback_effect_count"] == 5
    assert result["comparison"][0]["relay_processing_ros_ns"] is None
    assert result["status"] == "INCONCLUSIVE"


def test_reordered_acquisition_with_monotonic_processing_is_explicitly_valid():
    data = fixture_case()
    data["raw"][1]["stamp_ns"] = NS // 2
    data["decisions"][1]["stamp_ns"] = NS // 2
    assert compare_timing(**data)["status"] == "SUPPORTED_FIXTURE_CONTRACT"


def test_both_consumers_can_corroborate_an_output_observer_omission():
    data = fixture_case()
    forwarded = copy.deepcopy(data["raw"][-1])
    forwarded["stamp_ns"] = 9 * NS
    forwarded["receipt_ros_ns"] = 9 * NS
    data["raw"].append(forwarded)
    data["decisions"].append(
        {
            "sequence": 7,
            "epoch": 0,
            "stamp_ns": 9 * NS,
            "receipt_ns": 9 * NS,
            "processing_ns": 9 * NS,
            "cdr_sha256": forwarded["cdr_sha256"],
            "suppressed": False,
        }
    )
    for stamps in data["consumers"].values():
        stamps.append(9 * NS)
    assert compare_timing(**data)["status"] == "SUPPORTED_FIXTURE_CONTRACT"


@pytest.mark.parametrize(
    "defect", [None, "no_downstream", "one_downstream", "missing_diagnostics", "payload_conflict"]
)
def test_recovery_is_independent_but_not_qualification(evidence, defect):
    data = copy.deepcopy(evidence)
    consumers = {n: v["ready_stamps_ns"] for n, v in data["consumers"].items()}
    if defect == "no_downstream":
        consumers = {n: [] for n in consumers}
    if defect == "one_downstream":
        consumers["controller_server"] = []
    if defect == "missing_diagnostics":
        data["diagnostics"] = []
    if defect == "payload_conflict":
        data["streams"]["output"][-1]["cdr_sha256"] = "0" * 64
    result = recovery_observations(
        streams=data["streams"],
        consumers=consumers,
        diagnostics=data["diagnostics"],
        start_ns=2 * NS,
        stop_ns=3 * NS,
        restored_ns=3_100_000_000,
        end_ns=data["end_ns"],
    )
    assert result["status"] == (
        "SUPPORTED_SCOPED_RECOVERY_OBSERVATIONS" if defect is None else "UNKNOWN"
    )
    assert not result["qualification_changed"]
