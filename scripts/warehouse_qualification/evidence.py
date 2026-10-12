"""Read-only verification of closed W3 evidence; no ROS or process entry points.

Sequences are local to each file. Monotonic timestamps share a host clock, not
a global event order; callback timestamps may precede admission in other threads.
Writer-start timestamps describe batches, not individual fsync completion times.
Durability requires the writer's fsync acknowledgement AND successful read-back.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from .journal import EvidenceFailure

CONTRACT = {
    "version": "w3-two-stream-v1",
    "observation_file": "observations.jsonl",
    "lifecycle_file": "observations.jsonl.lifecycle.jsonl",
    "summary_file": "observer-shutdown.json",
    "sequence_scope": "independent_contiguous_one_based_per_stream",
    "durability": "closed_fsync_acknowledged_zero_loss_and_read_back",
    "required_observation_kinds": [
        "tf_edge",
        "tf_assessment",
        "contact_policy_observation",
        "warehouse_lidar_geometry",
        "original_result",
    ],
    "required_lifecycle_kinds": [
        "runner_start_requested",
        "runner_started",
        "runner_exit",
        "robot_stop_verified",
        "cleanup_observed",
        "observer_terminal_status",
        "observation_journal_closed",
    ],
}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceFailure(reason)


def _read(path: Path, timestamp: str, limit: int, max_rows: int) -> tuple[dict, dict]:
    """Stream bounded records, retaining only terminal/mission receipts."""
    digest = hashlib.sha256()
    counts: Counter = Counter()
    retained = {}
    first = last = None
    size = total = 0
    with path.open("rb") as stream:
        while line := stream.readline(limit + 1):
            total += 1
            require(total <= max_rows, f"Stream record budget exceeded: {path}")
            require(
                len(line) <= limit and line.endswith(b"\n"), f"Truncated/oversized row: {path}"
            )
            digest.update(line)
            size += len(line)
            require(
                size <= (2 * 1024 * 1024 if max_rows == 512 else 1024**3),
                f"Stream byte budget exceeded: {path}",
            )
            row = json.loads(line)
            require(isinstance(row, dict), f"Invalid record: {path}")
            require(
                type(row.get("sequence")) is int and row["sequence"] == total,
                f"Noncontiguous local sequence: {path}",
            )
            stamp = row.get(timestamp)
            require(type(stamp) is int and stamp >= 0, f"Invalid {timestamp}: {path}")
            first = stamp if first is None else min(first, stamp)
            last = stamp if last is None else max(last, stamp)
            if timestamp == "callback_monotonic_ns":
                writer = row.get("writer_started_monotonic_ns")
                require(
                    type(writer) is int and writer >= stamp, f"Invalid batch timestamp: {path}"
                )
            kind = row.get("kind")
            require(isinstance(kind, str) and bool(kind), f"Invalid kind: {path}")
            counts[kind] += 1
            require(len(counts) <= 64, f"Unbounded record kinds: {path}")
            if kind in CONTRACT["required_lifecycle_kinds"] or kind == "original_result":
                retained[kind] = row
    require(total > 0, f"Empty evidence stream: {path}")
    return {
        "sha256": digest.hexdigest(),
        "records": total,
        "bytes": size,
        "counts": dict(counts),
        "timestamp_min_ns": first,
        "timestamp_max_ns": last,
        "sequence_scope": "this_file_only",
    }, retained


def _account(status: dict, inventory: dict) -> None:
    require(
        all(
            type(status.get(k)) is int and status[k] >= 0
            for k in ("accepted", "written", "dropped", "accepted_not_durable")
        ),
        "Invalid evidence accounting metadata",
    )
    require(
        status.get("complete") is True
        and status.get("closed") is True
        and status.get("writer_alive") is False,
        "Writer not completely closed",
    )
    require(
        status.get("error") is None and status.get("critical_error") is None,
        "Evidence writer error",
    )
    require(
        type(status.get("accepted")) is int
        and status["accepted"] == status.get("written") == inventory["records"]
        and status.get("dropped") == 0
        and status.get("accepted_not_durable") == 0,
        "Evidence loss or durable accounting mismatch",
    )


def verify_evidence(directory: Path, original: dict | None, original_sha256: str | None) -> dict:
    """Raise on missing, inconsistent or failed evidence; never infer qualification.

    Existing live semantic gates, original verdicts, MCAP validation and process
    ownership checks remain independent requirements.
    """
    summary = json.loads((directory / CONTRACT["summary_file"]).read_text())
    observation, raw = _read(
        directory / CONTRACT["observation_file"],
        "callback_monotonic_ns",
        256 * 1024 + 1024,
        2_000_000,
    )
    lifecycle, terminal = _read(directory / CONTRACT["lifecycle_file"], "monotonic_ns", 8192, 512)
    require(
        not lifecycle["counts"].get("readiness_failure", 0),
        "Established readiness failure retained; qualification blocked",
    )
    status = summary["evidence"]
    critical = summary["critical_lifecycle"]
    _account(status, observation)
    _account(critical, lifecycle)
    require(
        status.get("generated") == status["accepted"]
        and status.get("generated_by_kind") == observation["counts"]
        and not status.get("rejected_by_reason")
        and status.get("pending_bytes") == 0,
        "Generated/admitted observations differ",
    )
    require(critical.get("bytes") == lifecycle["bytes"], "Lifecycle byte accounting differs")
    for stream, kinds in (
        (observation, "required_observation_kinds"),
        (lifecycle, "required_lifecycle_kinds"),
    ):
        require(
            all(stream["counts"].get(k, 0) > 0 for k in CONTRACT[kinds]),
            f"Required receipts missing: {kinds}",
        )
    require(
        all(lifecycle["counts"][k] == 1 for k in CONTRACT["required_lifecycle_kinds"]),
        "Duplicate terminal/start receipts",
    )
    require(
        observation["counts"]["original_result"] == 1
        and original is not None
        and raw["original_result"].get("manifest") == original
        and raw["original_result"].get("sha256") == original_sha256,
        "Original mission receipt differs",
    )
    require(
        terminal["observation_journal_closed"].get("status") == status,
        "Observation close receipt differs from summary",
    )
    runner = terminal["runner_exit"]
    require(
        type(terminal["runner_started"].get("pid")) is int
        and terminal["runner_started"]["pid"] > 0
        and runner.get("pid") == terminal["runner_started"]["pid"]
        and type(runner.get("returncode")) is int
        and runner["returncode"] == 0
        and runner.get("forced") is False
        and runner.get("cancellation_observation_error") is None,
        "Runner exit uncertain or failed",
    )
    cleanup = terminal["cleanup_observed"]
    require(
        cleanup.get("completed") is True
        and bool(cleanup.get("exits"))
        and all(type(code) is int and code == 0 for code in cleanup["exits"])
        and cleanup.get("failed_children") == [],
        "Cleanup incomplete",
    )
    require(
        terminal["observer_terminal_status"].get("faults") == []
        and summary.get("observer_and_cleanup_complete") is True,
        "Observer or cleanup failed",
    )
    derived = summary["derived_tf_assessments"]
    require(
        derived == terminal["observer_terminal_status"].get("derived_tf")
        and all(
            type(derived.get(k)) is int and derived[k] >= 0
            for k in ("evaluated", "emission_attempts", "coalesced")
        )
        and derived["evaluated"] == derived["emission_attempts"] + derived["coalesced"]
        and derived["emission_attempts"] == observation["counts"]["tf_assessment"],
        "Derived TF coalescing accounting differs",
    )
    require(
        not any(
            "forced_shutdown" in k or k == "robot_stop_unverified" for k in lifecycle["counts"]
        ),
        "Forced or unverified shutdown",
    )
    order = [terminal[k]["sequence"] for k in CONTRACT["required_lifecycle_kinds"]]
    require(order == sorted(order), "Lifecycle receipt order differs")
    return {
        "complete": True,
        "contract": CONTRACT["version"],
        "observation": observation,
        "lifecycle": lifecycle,
    }
