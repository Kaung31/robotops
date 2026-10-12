"""Offline journal failure/durability/ordering tests; never initialize ROS."""

import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from warehouse_qualification.journal import (  # noqa: E402
    BufferedJournal,
    EvidenceFailure,
    critical_event,
)
from warehouse_qualification.observer import QualificationObserver  # noqa: E402
from warehouse_qualification.runtime import stop_runner  # noqa: E402


def wait_durable(journal):
    with journal.condition:
        assert journal.condition.wait_for(
            lambda: journal.accepted == journal.written or journal.error, timeout=5
        )
    journal.check()


def test_batch_acknowledgement_waits_for_fsync_and_keeps_inflight_budget(tmp_path):
    entered, release = threading.Event(), threading.Event()
    batches = []

    def disk(rows):
        batches.append(rows)
        entered.set()
        assert release.wait(2)

    j = BufferedJournal(tmp_path / "batch", persist_batch=disk, batch_records=8)
    try:
        for i in range(8):
            assert j.submit("raw", index=i)
        assert entered.wait(1)
        assert j.status()["written"] == 0
        assert j.status()["accepted_not_durable"] == 8
        assert j.status()["pending_bytes"] > 0
    finally:
        release.set()
        result = j.close()
    assert result["complete"] and result["durable_batches"] == 1
    assert [json.loads(row)["index"] for row in batches[0]] == list(range(8))


def test_batch_writer_failure_never_acknowledges_partial_batch(tmp_path):
    touched = []

    def disk(rows):
        touched.append(rows[0])
        raise OSError("fsync failed after partial write")

    j = BufferedJournal(tmp_path / "batch", persist_batch=disk)
    for i in range(10):
        j.submit("raw", index=i)
    result = j.close()
    assert touched and result["written"] == 0 and result["accepted_not_durable"] == 10
    assert not result["complete"]


@pytest.mark.parametrize("limit", [{"storage_bytes": 300}, {"storage_records": 2}])
def test_storage_budget_failure_is_sticky(tmp_path, limit):
    j = BufferedJournal(tmp_path / "bounded", **limit)
    for i in range(20):
        j.submit("raw", index=i)
    result = j.close()
    assert result["generated"] == result["accepted"] + result["dropped"] == 20
    assert result["rejected_by_reason"]["storage_budget_exhausted"] == 1
    assert not result["complete"]


def test_main_failure_cannot_hide_real_runner_cancellation_and_exit(tmp_path):
    j = BufferedJournal(tmp_path / "events")
    j.reject("required observation lost")

    class Child:
        pid = 42
        code = None

        def poll(self):
            return self.code

        def send_signal(self, sig):
            self.signal = sig

        def wait(self, timeout):
            self.code = 2  # Realistic interrupted runner, never a clean exit.

    child = Child()
    assert not stop_runner(child, j)
    critical_event(j, "robot_stop_verified")
    critical_event(j, "cleanup_observed", exits=[0, 0, 0])
    result = j.close()
    assert not result["complete"] and j.lifecycle.status()["complete"]
    rows = [
        json.loads(line) for line in (tmp_path / "events.lifecycle.jsonl").read_text().splitlines()
    ]
    assert [r["kind"] for r in rows] == [
        "runner_cancellation_requested",
        "runner_exit",
        "robot_stop_verified",
        "cleanup_observed",
    ]
    assert rows[1]["returncode"] == 2 and rows[1]["forced"] is False
    assert [r["sequence"] for r in rows] == [1, 2, 3, 4]


def test_lifecycle_failure_blocks_and_does_not_throw_through_cleanup(tmp_path, monkeypatch):
    j = BufferedJournal(tmp_path / "events")
    monkeypatch.setattr(
        j.lifecycle.stream,
        "write",
        lambda row: (_ for _ in ()).throw(OSError("critical disk failed")),
    )
    assert critical_event(j, "runner_exit", returncode=0)
    status = j.lifecycle.close()
    assert not status["complete"] and "critical disk failed" in status["error"]
    with pytest.raises(EvidenceFailure, match="critical disk failed"):
        j.check()
    assert not critical_event(j, "cleanup_observed")
    j.close()


def test_lifecycle_budget_is_independent_bounded_and_failure_visible(tmp_path):
    j = BufferedJournal(tmp_path / "events")
    for i in range(513):
        critical_event(j, "event", index=i)
    j.close()
    result = j.lifecycle.status()
    assert result["accepted"] == 512 and result["dropped"] == 1
    assert not result["complete"]


def test_tf_evaluates_every_call_logs_transition_without_sampling_raw_edges(tmp_path):
    j = BufferedJournal(tmp_path / "events")
    o = QualificationObserver(j)
    now = 2_000_000_000
    o.clock(now, now)
    for parent, child, stamp in [("map", "odom", now + 500_000_000), ("odom", "base_link", now)]:
        o.tf(
            parent,
            child,
            stamp,
            receipt_ros_ns=now,
            receipt_monotonic_ns=now,
            callback_wall_ns=now,
            middleware_received_wall_ns=now,
        )
    for i in range(200):
        assert o.assess_tf(now + i, now + i, now)["ready"]
    assert not o.assess_tf(now + 1_000_000_001, now + 1_000_000_001, now)["ready"]
    j.close()
    rows = [json.loads(s) for s in (tmp_path / "events").read_text().splitlines()]
    assert len([r for r in rows if r["kind"] == "tf_edge"]) == 2
    assessments = [r for r in rows if r["kind"] == "tf_assessment"]
    assert len(assessments) == 2 and assessments[-1]["ready"] is False
    assert o.assessment_status()["evaluated"] == 201
    assert o.assessment_status()["coalesced"] == 199


def test_650_second_accelerated_raw_workload_and_elevated_derivation(tmp_path):
    # 4x the retained average raw-event rate (~170/s); 650 controlled ROS seconds.
    # Producer/writer barriers every virtual 0.1 s deliberately remove disk speed
    # from this accounting/ordering test. Slow-store throughput is tested separately.
    written = []
    j = BufferedJournal(
        tmp_path / "events",
        persist_batch=lambda rows: written.extend(json.loads(row)["sequence"] for row in rows),
        batch_wait_s=0,
    )
    for tick in range(6500):
        for i in range(68):
            assert j.submit("synthetic_raw", ros_ns=tick * 100_000_000, index=i)
        wait_durable(j)
    result = j.close()
    assert result["complete"] and result["written"] == 442_000
    assert written == list(range(1, 442_001))
    assert result["peak_pending"] <= 68


def test_recovery_drains_but_never_forgives_overflow(tmp_path):
    release, entered = threading.Event(), threading.Event()

    def disk(rows):
        entered.set()
        release.wait(2)

    j = BufferedJournal(tmp_path / "events", capacity=2, persist_batch=disk, batch_wait_s=0)
    j.submit("raw")
    assert entered.wait(1)
    j.submit("raw")
    assert not j.submit("raw")
    release.set()
    result = j.close()
    assert result["written"] == 2 and result["dropped"] == 1
    assert result["rejected_by_reason"]["record_capacity_overflow"] == 1
    assert not result["complete"]


def test_real_fsync_call_count_matches_batches_and_reader_order(tmp_path, monkeypatch):
    from warehouse_qualification import journal as module

    calls = []
    actual = module.os.fsync

    def sync(fd):
        calls.append(fd)
        actual(fd)

    monkeypatch.setattr(module.os, "fsync", sync)
    j = BufferedJournal(tmp_path / "events")
    calls.clear()  # Directory creation barriers already completed.
    for i in range(256):
        assert j.submit("raw", index=i)
    result = j.close()
    assert result["complete"]
    assert len(calls) == result["durable_batches"]
    assert len(calls) < 256
    rows = [json.loads(line) for line in (tmp_path / "events").read_text().splitlines()]
    assert [r["sequence"] for r in rows] == list(range(1, 257))
    assert [r["index"] for r in rows] == list(range(256))


def test_slow_critical_fsync_does_not_block_safety_receipt_admission(tmp_path, monkeypatch):
    from warehouse_qualification import journal as module

    entered, release = threading.Event(), threading.Event()
    j = BufferedJournal(tmp_path / "events")
    fd = j.lifecycle.stream.fileno()
    actual = module.os.fsync

    def sync(target):
        if target == fd:
            entered.set()
            assert release.wait(2)
        actual(target)

    monkeypatch.setattr(module.os, "fsync", sync)
    try:
        assert critical_event(j, "runner_cancellation_requested")
        assert entered.wait(1)
        # Synchronous I/O here would deadlock until the test released storage.
        assert critical_event(j, "cleanup_observed")
        assert not j.lifecycle.close(0.01)["complete"]
    finally:
        release.set()
        j.close()
    assert j.lifecycle.status()["written"] == 2
    assert not j.lifecycle.status()["complete"]  # Deadline violation stays sticky.


def test_actual_fsync_failure_never_confirms_critical_durability(tmp_path, monkeypatch):
    from warehouse_qualification import journal as module

    j = BufferedJournal(tmp_path / "events")
    fd = j.lifecycle.stream.fileno()
    actual = module.os.fsync

    def sync(target):
        if target == fd:
            raise OSError("critical fsync failed")
        actual(target)

    monkeypatch.setattr(module.os, "fsync", sync)
    critical_event(j, "runner_exit", returncode=0)
    assert not j.close()["complete"]
    result = j.lifecycle.status()
    assert result["written"] == 0 and result["accepted_not_durable"] == 1
    assert not result["complete"]


def test_forced_runner_exit_survives_observation_failure_and_never_cleans(tmp_path):
    import subprocess

    j = BufferedJournal(tmp_path / "events")
    j.reject("lost raw observation")

    class Child:
        pid = 43
        code = None

        def poll(self):
            return self.code

        def send_signal(self, sig):
            pass

        def wait(self, timeout):
            if self.code is None:
                raise subprocess.TimeoutExpired("fixture", timeout)

    child = Child()
    assert not stop_runner(child, j, killpg=lambda pid, sig: setattr(child, "code", -9))
    assert not j.close()["complete"]
    rows = [
        json.loads(line) for line in (tmp_path / "events.lifecycle.jsonl").read_text().splitlines()
    ]
    assert [r["kind"] for r in rows] == [
        "runner_cancellation_requested",
        "runner_forced_shutdown",
        "runner_exit",
    ]
    assert rows[-1]["forced"] is True and rows[-1]["returncode"] == -9


def test_exclusive_summary_fsyncs_file_and_parent_directory(tmp_path, monkeypatch):
    from warehouse_qualification import journal as module

    synced = []
    actual = module.os.fsync

    def sync(fd):
        synced.append(fd)
        actual(fd)

    monkeypatch.setattr(module.os, "fsync", sync)
    module.save_summary(tmp_path / "summary.json", {"qualified": False})
    assert len(synced) == 2
    with pytest.raises(FileExistsError):
        module.save_summary(tmp_path / "summary.json", {"qualified": True})
    assert json.loads((tmp_path / "summary.json").read_text())["qualified"] is False
