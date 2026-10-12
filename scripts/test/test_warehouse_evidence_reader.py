"""Offline durable-file fixtures; no ROS initialization or real child processes."""

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "backend")]
from warehouse_qualification import driver, evidence  # noqa: E402
from warehouse_qualification.journal import BufferedJournal, critical_event  # noqa: E402


@pytest.fixture
def streams(tmp_path, request):
    original = {"state": "completed", "trials": []}
    digest = "a" * 64
    journal = BufferedJournal(tmp_path / "observations.jsonl")
    for kind in evidence.CONTRACT["required_observation_kinds"]:
        if kind == "original_result":
            journal.submit(kind, manifest=original, sha256=digest)
        else:
            journal.submit(kind)
    if getattr(request, "param", None) is not None:
        journal.submit("readiness_assessment", ready=True, causes=[])
        if request.param:
            critical_event(
                journal, "readiness_failure", assessment={"causes": ["amcl.moving_pose_stale"]}
            )
    derived = {"evaluated": 8, "emission_attempts": 1, "coalesced": 7}
    critical_event(journal, "runner_start_requested", command=["fixture"])
    critical_event(journal, "runner_started", pid=123)
    critical_event(
        journal,
        "runner_exit",
        pid=123,
        returncode=0,
        forced=False,
        cancellation_observation_error=None,
    )
    critical_event(journal, "robot_stop_verified")
    critical_event(journal, "cleanup_observed", completed=True, exits=[0], failed_children=[])
    critical_event(journal, "observer_terminal_status", faults=[], derived_tf=derived)
    status = journal.close(close_lifecycle=False)
    critical_event(journal, "observation_journal_closed", status=status)
    lifecycle = journal.lifecycle.close()
    summary = {
        "evidence": status,
        "critical_lifecycle": lifecycle,
        "derived_tf_assessments": derived,
        "observer_and_cleanup_complete": True,
    }
    (tmp_path / "observer-shutdown.json").write_text(json.dumps(summary))
    return tmp_path, original, digest


def rewrite(path, change):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    change(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_independent_sequences_and_batch_timestamps(streams):
    result = evidence.verify_evidence(*streams)
    assert result["complete"]
    assert result["observation"]["records"] == 5
    assert result["lifecycle"]["records"] == 7
    assert result["observation"]["sequence_scope"] == result["lifecycle"]["sequence_scope"]
    assert result["observation"]["sha256"] != result["lifecycle"]["sha256"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_main",
        "missing_lifecycle",
        "truncated",
        "sequence",
        "timestamp",
        "missing_receipt",
        "forced",
        "runner_unknown",
        "runner_pid",
        "cleanup_unknown",
        "fault",
        "accounting",
        "overflow",
        "lifecycle_failure",
        "writer_alive",
        "original",
        "close_receipt",
        "derived_accounting",
    ],
)
def test_incomplete_evidence_always_blocks(streams, mutation):
    directory, original, digest = streams
    main = directory / "observations.jsonl"
    lifecycle = directory / "observations.jsonl.lifecycle.jsonl"
    summary_path = directory / "observer-shutdown.json"
    summary = json.loads(summary_path.read_text())
    if mutation.startswith("missing_") and mutation != "missing_receipt":
        (main if mutation == "missing_main" else lifecycle).unlink()
    elif mutation == "truncated":
        main.write_bytes(main.read_bytes()[:-1])
    elif mutation == "sequence":
        rewrite(lifecycle, lambda rows: rows[0].update(sequence=2))
    elif mutation == "timestamp":
        rewrite(main, lambda rows: rows[0].update(writer_started_monotonic_ns=0))
    elif mutation == "missing_receipt":
        rewrite(lifecycle, lambda rows: rows[3].update(kind="unrelated"))
    elif mutation in ("forced", "runner_unknown", "runner_pid"):
        fields = (
            {"forced": True}
            if mutation == "forced"
            else ({"returncode": None} if mutation == "runner_unknown" else {"pid": 999})
        )
        rewrite(lifecycle, lambda rows: rows[2].update(fields))
    elif mutation == "cleanup_unknown":
        rewrite(lifecycle, lambda rows: rows[4].update(exits=[None]))
    elif mutation == "fault":
        rewrite(lifecycle, lambda rows: rows[5].update(faults=["stale TF"]))
    elif mutation == "original":
        original = {"rewritten": True}
    elif mutation == "close_receipt":
        rewrite(lifecycle, lambda rows: rows[-1].update(status={}))
    elif mutation == "accounting":
        summary["evidence"]["written"] -= 1
    elif mutation == "overflow":
        summary["evidence"]["dropped"] = 1
    elif mutation == "lifecycle_failure":
        summary["critical_lifecycle"]["error"] = "fsync failed"
    elif mutation == "writer_alive":
        summary["critical_lifecycle"]["writer_alive"] = True
    elif mutation == "derived_accounting":
        summary["derived_tf_assessments"]["coalesced"] = 999
        rewrite(lifecycle, lambda rows: rows[5]["derived_tf"].update(coalesced=999))
    # Preserve byte accounting for semantic mutations so the tests reach the
    # actual runner/cleanup/receipt checks, rather than only a size mismatch.
    if lifecycle.exists():
        summary["critical_lifecycle"]["bytes"] = lifecycle.stat().st_size
    summary_path.write_text(json.dumps(summary))
    with pytest.raises((RuntimeError, OSError, ValueError, KeyError)):
        evidence.verify_evidence(directory, original, digest)


@pytest.mark.parametrize(
    "field", ["attempt_set", "evidence_contract", "historical_claims", "execution_approved"]
)
def test_old_or_incomplete_plan_contract_refused(field):
    plan = {
        "attempt_set": driver.ATTEMPT_SET,
        "attempt_policy": copy.deepcopy(driver.ATTEMPT_POLICY),
        "evidence_contract": copy.deepcopy(evidence.CONTRACT),
        "historical_claims": dict.fromkeys(driver.HISTORICAL_CLAIMS, "a" * 64),
        "execution_approved": False,
    }
    driver.validate_contract(plan)
    plan.pop(field)
    with pytest.raises(RuntimeError):
        driver.validate_contract(plan)


@pytest.mark.parametrize("key", sorted(driver.REQUIRED_SHUTDOWN))
@pytest.mark.parametrize("mode", ["missing", "false"])
def test_incomplete_shutdown_cannot_pass_new_contract(key, mode):
    shutdown = dict.fromkeys(driver.REQUIRED_SHUTDOWN, True)
    assert driver.shutdown_complete(shutdown)
    if mode == "missing":
        shutdown.pop(key)
    else:
        shutdown[key] = False
    assert not driver.shutdown_complete(shutdown)


@pytest.mark.parametrize("streams", [False, True], indirect=True)
def test_readiness_diagnostics_preserve_stream_compatibility_and_fail_closed(streams, request):
    if request.node.callspec.params["streams"]:
        with pytest.raises(RuntimeError, match="readiness failure retained"):
            evidence.verify_evidence(*streams)
    else:
        result = evidence.verify_evidence(*streams)
        assert result["complete"] and result["observation"]["records"] == 6
