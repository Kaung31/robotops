"""Diagnostic boundary and failure-evidence regression fixtures."""

import copy
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_evidence import (  # noqa: E402
    CLOCK_STATUS,
    OUTPUT_MONITOR,
    SCAN_STATUS,
    EvidenceJournal,
    assess_diagnostic_window,
    diagnostic_level,
)


@pytest.mark.parametrize("value", [0, 1, 2, 3, b"\x00", b"\x01", b"\x02", b"\x03"])
def test_diagnostic_standard_levels(value):
    assert diagnostic_level(value) == (value[0] if isinstance(value, bytes) else value)


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        -1,
        4,
        255,
        1.0,
        "1",
        None,
        b"",
        b"\x00\x01",
        b"\x04",
        bytearray([1]),
        memoryview(b"\x01"),
    ],
)
def test_invalid_diagnostic_levels(value):
    with pytest.raises(ValueError):
        diagnostic_level(value)


@pytest.mark.parametrize("level", range(4))
def test_actual_jazzy_wire_diagnostic(level):
    from diagnostic_msgs.msg import DiagnosticStatus
    from rclpy.serialization import deserialize_message, serialize_message

    decoded = deserialize_message(
        serialize_message(DiagnosticStatus(level=bytes([level]))), DiagnosticStatus
    )
    assert diagnostic_level(decoded.level) == level
    assert (
        diagnostic_level(getattr(DiagnosticStatus, ("OK", "WARN", "ERROR", "STALE")[level]))
        == level
    )


def rows():
    def row(t, level=0, reason="fresh", age=0.1):
        return {
            "stamp_ns": t,
            "status": [
                {
                    "name": CLOCK_STATUS,
                    "hardware_id": OUTPUT_MONITOR,
                    "level": 0,
                    "message": "advancing",
                    "values": {},
                },
                {
                    "name": SCAN_STATUS,
                    "hardware_id": OUTPUT_MONITOR,
                    "level": level,
                    "message": reason,
                    "values": {
                        "advancing_samples": "2",
                        "receipt_age_seconds": str(age),
                        "stamp_age_seconds": str(age),
                        "warn_seconds": "0.5",
                    },
                },
            ],
        }

    return [
        row(1_900_000_000),
        row(2_700_000_000, 1, "age_warning", 0.7),
        row(3_400_000_000),
        row(3_600_000_000),
    ]


def assess(value):
    return assess_diagnostic_window(
        value, 2_000_000_000, 3_000_000_000, 3_100_000_000, 4_000_000_000
    )


def test_window_accepts_genuine_drop_and_recovery():
    result = assess(rows())
    assert result["degraded_ns"] == [2_700_000_000]


@pytest.mark.parametrize(
    "defect",
    [
        "startup_stale",
        "wrong_monitor",
        "wrong_name",
        "outside_window",
        "healthy_during",
        "clock_failed",
        "recovery_stale",
        "no_recovery",
        "one_recovery",
        "no_prehealth",
        "nan_age",
        "too_young",
        "wrong_threshold",
        "duplicate_identity",
    ],
)
def test_window_rejects_false_evidence(defect):
    value = copy.deepcopy(rows())
    scan = value[1]["status"][1]
    if defect == "startup_stale":
        value[1]["stamp_ns"] = 1_000_000_000
        scan.update(level=3, message="not_observed")
    if defect == "wrong_monitor":
        scan["hardware_id"] = "other"
    if defect == "wrong_name":
        scan["name"] = "other/scan"
    if defect == "outside_window":
        value[1]["stamp_ns"] = 3_050_000_000
    if defect == "healthy_during":
        scan.update(level=0, message="fresh")
    if defect == "clock_failed":
        value[1]["status"][0]["level"] = 3
    if defect == "recovery_stale":
        value[-1]["status"][1].update(level=3, message="receipt_timeout")
    if defect == "no_recovery":
        value = value[:2]
    if defect == "one_recovery":
        value = value[:3]
    if defect == "no_prehealth":
        value = value[1:]
    if defect == "nan_age":
        scan["values"]["stamp_age_seconds"] = "nan"
        scan["values"]["receipt_age_seconds"] = "nan"
    if defect == "too_young":
        scan["values"].update(receipt_age_seconds=".1", stamp_age_seconds=".1")
    if defect == "wrong_threshold":
        scan["values"]["warn_seconds"] = "0.1"
    if defect == "duplicate_identity":
        value[1]["status"].append(copy.deepcopy(scan))
    with pytest.raises((AssertionError, ValueError)):
        assess(value)


def test_journal_survives_later_assertion(tmp_path):
    path = tmp_path / "observations.jsonl"
    journal = EvidenceJournal(path)
    with pytest.raises(AssertionError):
        try:
            journal.record("raw_scan", stamp_ns=123)
            journal.record("diagnostic", level=1)
            raise AssertionError("later check failed")
        finally:
            journal.close()
    assert [r["kind"] for r in map(json.loads, path.read_text().splitlines())] == [
        "raw_scan",
        "diagnostic",
    ]
    with pytest.raises(FileExistsError):
        EvidenceJournal(path)


def test_journal_survives_forced_process_kill(tmp_path):
    path = tmp_path / "killed.jsonl"
    code = (
        "from probe_evidence import EvidenceJournal; from pathlib import Path; import sys,time; "
        'j=EvidenceJournal(Path(sys.argv[1])); j.record("before_kill",stamp_ns=42); '
        'print("ready",flush=True); time.sleep(30)'
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(path)],
        cwd=Path(__file__).parent,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        os.kill(process.pid, signal.SIGKILL)
        assert process.wait(timeout=5) == -signal.SIGKILL
        assert json.loads(path.read_text())["stamp_ns"] == 42
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def test_observation_callbacks_use_actual_ros_clock_and_diagnostic_type(tmp_path):
    import rclpy
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
    from probe_session import ObservedNavigationSession
    from rclpy.context import Context
    from rclpy.node import Node
    from rosgraph_msgs.msg import Clock

    context = Context()
    rclpy.init(context=context)
    node = Node("probe_boundary_test", context=context)
    path = tmp_path / "callbacks.jsonl"
    try:
        with EvidenceJournal(path) as journal:
            session = ObservedNavigationSession.__new__(ObservedNavigationSession)
            session.node = node
            session.journal = journal
            receipt = session.record_message("/clock", Clock(), "clock", ros_ns=0)
            message = DiagnosticArray(
                status=[
                    DiagnosticStatus(
                        name=SCAN_STATUS,
                        hardware_id=OUTPUT_MONITOR,
                        level=b"\x01",
                        message="age_warning",
                        values=[KeyValue(key="receipt_age_seconds", value="0.7")],
                    )
                ]
            )
            records = []
            session.diagnostics(records, "/fault_probe/diagnostics", message)
            assert records[0]["status"][0]["level"] == 1
            assert type(records[0]["receipt_ros_ns"]) is int
        saved = list(map(json.loads, path.read_text().splitlines()))
        assert [r["kind"] for r in saved] == ["clock", "diagnostic_wire", "diagnostic"]
        assert saved[0]["cdr_base64"] and saved[1]["cdr_base64"]
        assert saved[0]["receipt_ros_ns"] == receipt and type(receipt) is int
    finally:
        node.destroy_node()
        context.shutdown()


def test_consumer_receipt_and_child_failure_are_persisted_before_assertions(tmp_path):
    from probe_session import ObservedNavigationSession

    log = tmp_path / "pipeline.log"
    log.write_text(
        "[controller_server-3] [DEBUG] MessageFilter [target=odom ]: "
        "Added message in frame lidar_link at time 5.800, count now 0\n"
        "[planner_server-4] [DEBUG] MessageFilter [target=map ]: "
        "Message ready in frame lidar_link at time 5.800, count now 0\n"
        "[ERROR] [controller_server-3]: process has died [exit code -6]\n"
    )
    path = tmp_path / "consumer.jsonl"
    with EvidenceJournal(path) as journal:
        session = ObservedNavigationSession.__new__(ObservedNavigationSession)
        session.journal = journal
        session.logs = [(log, None)]
        session.offsets = {}
        session.child_failure_lines = []
        session.capture_logs()
        session.capture_logs()
    records = list(map(json.loads, path.read_text().splitlines()))
    assert len(records) == 3
    assert records[0]["stamp_ns"] == 5_800_000_000
    assert records[1]["event"] == "Message ready"
    assert records[2]["kind"] == "child_process_exit_log"
    assert len(session.child_failure_lines) == 1


def test_journal_context_records_error_and_closes(tmp_path):
    path = tmp_path / "context-error.jsonl"
    with pytest.raises(RuntimeError, match="callback failure"):
        with EvidenceJournal(path) as journal:
            journal.record("before_error")
            with pytest.raises(ValueError):
                journal.record("invalid", number=float("nan"))
            raise RuntimeError("callback failure")
    assert journal.stream.closed
    saved = list(map(json.loads, path.read_text().splitlines()))
    assert [r["sequence"] for r in saved] == [1, 2]
    assert saved[-1]["kind"] == "harness_exception"


@pytest.mark.parametrize("mode", ["normal", "assertion", "forced_kill", "child_abort"])
def test_observer_runs_cleanup_and_persists_exit_evidence(tmp_path, monkeypatch, mode):
    from types import SimpleNamespace

    import mapping_system
    from probe_session import ObservedNavigationSession

    calls = []

    class Process:
        pid = 424242
        code = None

        def poll(self):
            return self.code

        def send_signal(self, value):
            calls.append(("signal", value))

        def wait(self, timeout):
            calls.append(("wait", timeout))
            if mode == "forced_kill" and self.code is None:
                raise subprocess.TimeoutExpired("fake-owned-process", timeout)
            self.code = -9 if mode == "forced_kill" else 0
            return self.code

    process = Process()

    def kill_group(pid, value):
        calls.append(("kill_group", pid, value))
        process.code = -9

    monkeypatch.setattr(mapping_system.os, "killpg", kill_group)
    monkeypatch.setattr(mapping_system.rclpy, "shutdown", lambda: calls.append("shutdown"))
    log = tmp_path / "pipeline.log"
    log.write_text(
        "[ERROR] [controller_server-3]: process has died [exit code -6]\n"
        if mode == "child_abort"
        else "[INFO] [controller_server-3]: process has finished cleanly [pid 123]\n"
    )
    stream = log.open("a")
    path = tmp_path / "cleanup.jsonl"
    with EvidenceJournal(path) as journal:
        session = ObservedNavigationSession.__new__(ObservedNavigationSession)
        session.journal, session.processes = journal, [process]
        session.logs, session.offsets, session.child_failure_lines = [(log, stream)], {}, []
        session.listener = SimpleNamespace(unregister=lambda: calls.append("unregister"))
        session.node = SimpleNamespace(destroy_node=lambda: calls.append("destroy_node"))
        if mode in ("forced_kill", "child_abort"):
            with pytest.raises(AssertionError):
                session.__exit__(None, None, None)
        elif mode == "assertion":
            session.__exit__(AssertionError, AssertionError("mission failed"), None)
        else:
            session.__exit__(None, None, None)
    assert stream.closed and journal.stream.closed
    assert calls[-3:] == ["unregister", "destroy_node", "shutdown"]
    assert ("signal", signal.SIGINT) in calls
    if mode == "forced_kill":
        assert ("kill_group", process.pid, signal.SIGKILL) in calls
    saved = list(map(json.loads, path.read_text().splitlines()))
    assert saved[-2]["kind"] == "owned_process_termination"
    assert saved[-2]["returncode"] == (-9 if mode == "forced_kill" else 0)
    assert saved[-1]["clean_shutdown_verified"] == (mode in ("normal", "assertion"))
    assert saved[-1]["cleanup_sequence_completed"] == (mode in ("normal", "assertion"))
    assert bool(saved[-1]["failed_child_exit_lines"]) == (mode == "child_abort")


def test_observer_partial_startup_calls_cleanup_before_propagating(tmp_path, monkeypatch):
    from probe_session import NavigationSession, ObservedNavigationSession

    calls = []

    def fail_start(session):
        session.node = object()
        raise RuntimeError("partial startup")

    def cleanup(session, kind, error, tb):
        calls.append((kind, str(error)))
        session.journal.record("offline_startup_cleanup")

    monkeypatch.setattr(NavigationSession, "__enter__", fail_start)
    monkeypatch.setattr(ObservedNavigationSession, "__exit__", cleanup)
    path = tmp_path / "startup.jsonl"
    with pytest.raises(RuntimeError, match="partial startup"):
        with EvidenceJournal(path) as journal:
            session = ObservedNavigationSession.__new__(ObservedNavigationSession)
            session.journal = journal
            session.__enter__()
    assert calls == [(RuntimeError, "partial startup")]
    assert [r["kind"] for r in map(json.loads, path.read_text().splitlines())] == [
        "offline_startup_cleanup",
        "harness_exception",
    ]
    assert journal.stream.closed
