"""Offline timing contract prototype. Not wired into the live qualification path."""

from __future__ import annotations

from probe_evidence import assess_diagnostic_window
from routing_evidence import (
    FRESH_NS,
    MIN_SAMPLES,
    EvidenceProblem,
    observations,
    ordered_diagnostics,
)


def compare_timing(*, raw, output, consumers, start_ns, stop_ns, count, decisions=None):
    """Compare unlike counters without inventing relay receipt/decision timestamps.

    Optional decision fixtures describe a proposed future contract, NOT existing
    v2 relay evidence. Complete decisions must be independently keyed to raw CDR.
    Identical same-stamp callbacks remain ambiguous without ingress identifiers.
    """
    report = {"status": "INCONCLUSIVE", "reasons": [], "comparison": []}
    try:
        assert all(type(x) is int for x in (start_ns, stop_ns, count))
        assert 0 < start_ns < stop_ns and count >= MIN_SAMPLES
        raw_index = observations(raw, "raw", [])
        out_index = observations(output, "output", [])
        assert len(raw_index) == len(raw), "Duplicate raw identity cannot count callbacks"
        assert len(out_index) == len(output), "Duplicate output identity cannot count callbacks"
        assert len(consumers) == 2, "Both consumer observations required"
        assert all(
            raw_index[t]["cdr_sha256"] == out_index[t]["cdr_sha256"]
            for t in raw_index.keys() & out_index
        ), "Conflicting output payload"
        missing = raw_index.keys() - out_index.keys()
        report["acquisition_window_missing_count"] = sum(start_ns <= t < stop_ns for t in missing)
        report["sealed_callback_effect_count"] = count
        report["comparison"] = [
            {
                "stamp_ns": t,
                "cdr_sha256": raw_index[t]["cdr_sha256"],
                "observer_receipt_ros_ns": raw_index[t]["receipt_ros_ns"],
                "relay_receipt_ros_ns": None,
                "relay_processing_ros_ns": None,
                "relay_decision": "UNAVAILABLE",
                "header_inside_window": start_ns <= t < stop_ns,
                "output_observed": t in out_index,
                "ready_consumers": [n for n, stamps in consumers.items() if t in stamps],
            }
            for t in sorted(missing)
        ]
        if decisions is None:
            report["reasons"].append(
                "No per-message relay decisions; observer receipt is not relay time"
            )
            return report
        assert len(decisions) == len(raw), "Incomplete decision/observer correspondence"
        assert [d["sequence"] for d in decisions] == list(range(1, len(decisions) + 1))
        assert {d["epoch"] for d in decisions} == {0}, "Clock epoch changed"
        assert [d["processing_ns"] for d in decisions] == sorted(
            d["processing_ns"] for d in decisions
        ), "Processing clock regression"
        seen, affected = set(), 0
        for d in decisions:
            t, receipt, processing = d["stamp_ns"], d["receipt_ns"], d["processing_ns"]
            assert all(type(v) is int for v in (t, receipt, processing))
            assert 0 < t <= receipt <= processing, "Invalid relay time domain"
            assert t in raw_index and t not in seen, "Unmatched/duplicate ingress identity"
            seen.add(t)
            assert d["cdr_sha256"] == raw_index[t]["cdr_sha256"], "Wrong relay message identity"
            assert type(d["suppressed"]) is bool
            active = start_ns <= processing < stop_ns
            assert d["suppressed"] == active, "Decision conflicts with processing-time policy"
            if d["suppressed"]:
                affected += 1
                assert t not in out_index and not any(t in s for s in consumers.values()), (
                    "Suppressed message delivered downstream"
                )
            elif t not in out_index:
                # Both costmaps corroborate delivery even when output observer loses it.
                assert all(t in s for s in consumers.values()), "Unexplained out-of-window loss"
        assert affected == count, "Sealed count disagrees with independently matched decisions"
        report["status"] = "SUPPORTED_FIXTURE_CONTRACT"
    except (AssertionError, KeyError, TypeError, ValueError, EvidenceProblem) as exc:
        report["reasons"].append(str(exc))
    return report


def recovery_observations(
    *, streams, consumers, diagnostics, restored_ns, start_ns, stop_ns, end_ns
):
    """Separate saved-data recovery observations from unresolved fault qualification."""
    report = {"status": "UNKNOWN", "qualification_changed": False, "reasons": []}
    try:
        raw = observations(streams["raw"], "raw", [])
        output = observations(streams["output"], "output", [])
        assert set(consumers) == {"controller_server", "planner_server"}
        assert all(raw[t]["cdr_sha256"] == output[t]["cdr_sha256"] for t in raw.keys() & output)
        hi = min(max(raw), max(output)) - 200_000_000
        common = sorted(
            t
            for t in raw.keys() & output
            if restored_ns + 200_000_000 < t <= hi
            and all(t in s for s in consumers.values())
            and all(rows[t]["receipt_ros_ns"] - t <= FRESH_NS for rows in (raw, output))
        )
        report["fresh_matching_both_consumer_stamps_ns"] = common
        assert len(common) >= MIN_SAMPLES, "Insufficient downstream recovery"
        ordered = ordered_diagnostics(diagnostics, end_ns, [])
        assert ordered[-1]["stamp_ns"] >= end_ns - 1_000_000_000, "Missing diagnostic tail"
        report["diagnostics"] = assess_diagnostic_window(
            ordered, start_ns, stop_ns, restored_ns, end_ns
        )
        report["status"] = "SUPPORTED_SCOPED_RECOVERY_OBSERVATIONS"
    except (AssertionError, KeyError, TypeError, ValueError, EvidenceProblem) as exc:
        report["reasons"].append(str(exc))
    return report
