"""Offline synthetic fixtures only. No ROS node, launch, simulator or mission."""

import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from warehouse_qualification.journal import (  # noqa: E402
    BufferedJournal,
    EvidenceFailure,
    save_summary,
    shutdown_summary,
)
from warehouse_qualification.observer import TF_MAX_AGE_NS, QualificationObserver  # noqa: E402


@pytest.fixture
def journal(tmp_path):
    j = BufferedJournal(tmp_path / "events.jsonl")
    yield j
    j.close()


def test_durable_exclusive_snapshot(tmp_path):
    path = tmp_path / "events.jsonl"
    j = BufferedJournal(path)
    original = {"a": [1]}
    assert j.submit("one", value=original)
    original["a"].append(2)
    assert j.submit("two")
    result = j.close()
    assert result["complete"] and result["written"] == 2
    rows = [json.loads(s) for s in path.read_text().splitlines()]
    assert rows[0]["value"] == {"a": [1]}
    assert [r["sequence"] for r in rows] == [1, 2]
    with pytest.raises(FileExistsError):
        BufferedJournal(path)
    assert not j.submit("late")
    assert j.status()["dropped"] == 1
    assert not j.status()["complete"]


def test_callbacks_do_not_wait_for_disk_and_overflow_is_fatal(tmp_path):
    entered, release = threading.Event(), threading.Event()
    threads = []

    def persist(_):
        threads.append(threading.get_ident())
        entered.set()
        assert release.wait(2)

    j = BufferedJournal(tmp_path / "unused", capacity=2, persist=persist)
    try:
        assert j.submit("one")
        assert entered.wait(1)
        assert j.submit("two")
        assert not j.submit("three")
        with pytest.raises(EvidenceFailure, match="overflow"):
            j.check()
        assert j.status()["peak_pending"] == 2
        assert all(t != threading.get_ident() for t in threads)
    finally:
        release.set()
        status = j.close()
    assert status["accepted"] == status["written"] == 2 and status["dropped"] == 1
    assert not status["complete"]


@pytest.mark.parametrize(
    "settings,payload",
    [
        ({"max_record_bytes": 128}, "x" * 200),
        ({"byte_capacity": 128}, "x" * 200),
    ],
)
def test_record_and_byte_bounds(tmp_path, settings, payload):
    j = BufferedJournal(tmp_path / "events", **settings)
    assert not j.submit("large", payload=payload)
    result = j.close()
    assert result["dropped"] == 1 and result["peak_bytes"] == 0


@pytest.mark.parametrize("fields", [{"value": float("nan")}, {"value": object()}, {"sequence": 2}])
def test_encoding_failures(journal, fields):
    assert not journal.submit("invalid", **fields)
    with pytest.raises(EvidenceFailure):
        journal.check()


def test_write_failure_and_accepted_not_durable(tmp_path):
    def fail(_):
        raise OSError("disk full")

    j = BufferedJournal(tmp_path / "unused", persist=fail)
    assert j.submit("accepted")
    status = j.close()
    assert "disk full" in status["error"]
    assert status["accepted_not_durable"] == 1 and not status["complete"]
    with pytest.raises(EvidenceFailure):
        j.check()


def test_stuck_writer_close_is_bounded_and_unclean(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def blocked(_):
        entered.set()
        release.wait(2)

    j = BufferedJournal(tmp_path / "unused", persist=blocked)
    try:
        j.submit("one")
        assert entered.wait(1)
        result = j.close(0.01)
        assert result["writer_alive"] and not result["complete"]
        assert "deadline" in result["error"]
    finally:
        release.set()
        j.worker.join(1)
    assert not j.close()["complete"]  # Timeout is sticky even after late write.


def edge(observer, parent, child, stamp, receipt_ros=2_000_000_000, mono=2_000_000_000, delay=0):
    observer.tf(
        parent,
        child,
        stamp,
        receipt_ros_ns=receipt_ros,
        receipt_monotonic_ns=mono,
        callback_wall_ns=10_000_000_000,
        middleware_received_wall_ns=None if delay is None else 10_000_000_000 - delay,
    )


def fresh(observer):
    observer.clock(2_000_000_000, 2_000_000_000)
    edge(observer, "map", "odom", 2_500_000_000)  # AMCL postdating is explicitly documented.
    edge(observer, "odom", "base_link", 2_000_000_000)


def test_tf_edges_equality_static_and_missing(journal):
    o = QualificationObserver(journal)
    assert not o.assess_tf(2_000_000_000, 2_000_000_000, None)["ready"]
    fresh(o)
    result = o.assess_tf(2_000_000_000, 2_000_000_000, 1_000_000_000)
    assert result["ready"] and result["buffer_age_ns"] == TF_MAX_AGE_NS
    assert not o.assess_tf(2_000_000_001, 2_000_000_000, 1_000_000_000)["ready"]
    o.tf(
        "base_link",
        "lidar_link",
        0,
        receipt_ros_ns=2_000_000_000,
        receipt_monotonic_ns=2_000_000_000,
        callback_wall_ns=1,
        static=True,
    )
    assert not o.faults
    assert not o.assess_tf(2_000_000_000, 2_000_000_000, 2_000_000_001)["ready"]


def test_buffer_lag_is_not_automatically_upstream_failure(journal):
    o = QualificationObserver(journal)
    fresh(o)
    result = o.assess_tf(2_000_000_000, 2_000_000_000, 500_000_000)
    assert result["buffer_observer_discrepancy"] and not result["ready"]


def test_callback_backlog_and_upstream_ambiguity(journal):
    o = QualificationObserver(journal)
    fresh(o)
    edge(o, "odom", "base_link", 2_000_000_000, delay=500_000_000)
    result = o.assess_tf(2_000_000_000, 2_000_000_000, 2_000_000_000)
    assert "OBSERVER_CALLBACK_DELAY" in result["edges"]["odom->base_link"]["classification"]
    assert not result["ready"]
    other = QualificationObserver(journal)
    other.clock(2_000_000_000, 2_000_000_000)
    edge(other, "map", "odom", 500_000_000, delay=0)
    edge(other, "odom", "base_link", 500_000_000, delay=None)
    result = other.assess_tf(2_000_000_000, 2_000_000_000, 500_000_000)
    flags = result["edges"]["odom->base_link"]["classification"]
    assert "MIDDLEWARE_RECEIPT_TIME_UNAVAILABLE" in flags
    assert "OLD_STAMP_AT_CALLBACK_UPSTREAM_OR_TRANSPORT_UNRESOLVED" in flags
    assert not result["ready"]


def test_clock_reset_tf_regression_missing_clock_and_silence(journal):
    o = QualificationObserver(journal)
    fresh(o)
    assert not o.assess_tf(2_000_000_000, 3_000_000_001, 2_000_000_000)["ready"]
    o.clock(1_000_000_000, 2_100_000_000)
    with pytest.raises(EvidenceFailure, match="clock regressed"):
        o.check()
    other = QualificationObserver(journal)
    edge(other, "map", "odom", 2_000_000_000)
    edge(other, "map", "odom", 1_000_000_000)
    assert any("edge regressed" in f for f in other.faults)
    with pytest.raises(EvidenceFailure):
        other.check()


def frame(sequence=1, complete=True, contacts=None):
    return dict(
        source_id="synthetic",
        sequence=sequence,
        start_ns=sequence * 50_000_000,
        end_ns=(sequence + 1) * 50_000_000,
        physics_steps=50,
        coverage_complete=complete,
        monitored_bodies=["wheel"],
        support_pairs=["wheel|floor"],
        contacts=contacts or [],
    )


def test_startup_contact_anomaly_stops_before_ready(journal):
    o = QualificationObserver(journal)
    o.contact(frame(complete=False), 1)
    assert not o.ready(1)
    o.contact(frame(2, contacts=[{"body_a": "wheel", "body_b": "wall"}]), 2)
    with pytest.raises(EvidenceFailure, match="Unexpected non-support contact"):
        o.check()


def test_contact_settling_coverage_discontinuity_and_absence(journal):
    o = QualificationObserver(journal)
    assert not o.ready(1)
    o.contact(frame(complete=False), 1)
    assert not o.ready(1)
    o.contact(frame(2), 2)
    assert o.ready(2)
    assert not o.ready(250_000_003)
    o.contact(frame(3, complete=False), 3)
    with pytest.raises(EvidenceFailure, match="coverage lost"):
        o.check()
    other = QualificationObserver(journal)
    other.contact(frame(), 1)
    other.contact(frame(3), 2)
    with pytest.raises(EvidenceFailure, match="continuity"):
        other.check()


def test_shutdown_exception_independent_of_cleanup_and_write_failure(tmp_path):
    def summary(**updates):
        values = dict(
            exception=None,
            cleanup_completed=True,
            exits=[0, 0],
            failed_children=[],
            robot_stop_verified=True,
            journal={"complete": True},
        )
        values.update(updates)
        return shutdown_summary(**values)

    assert summary()["observer_and_cleanup_complete"]
    failed = summary(exception="AssertionError: TF stale")
    assert (
        failed["clean_process_shutdown_verified"] and not failed["observer_and_cleanup_complete"]
    )
    assert not summary(exits=[0, None])["clean_process_shutdown_verified"]
    assert not summary(failed_children=["gazebo died"])["observer_and_cleanup_complete"]
    assert not summary(journal={"complete": False})["observer_and_cleanup_complete"]
    save_summary(tmp_path / "summary.json", failed)
    with pytest.raises(FileExistsError):
        save_summary(tmp_path / "summary.json", failed)
    with pytest.raises(OSError):
        save_summary(tmp_path / "missing" / "summary.json", failed)


@pytest.fixture
def ros_session_module():
    pytest.importorskip("rclpy")
    sys.path.insert(0, str(ROOT / "ros2_ws/src/robot_navigation/test"))
    spec = importlib.util.spec_from_file_location(
        "w3_session_offline", ROOT / "ros2_ws/src/robot_navigation/test/warehouse_session.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actual_ros_fixtures_no_nodes(ros_session_module, tmp_path, monkeypatch):
    m = ros_session_module
    from geometry_msgs.msg import TransformStamped
    from tf2_msgs.msg import TFMessage

    # Fail loudly if any fixture tries to initialise ROS or create a real node.
    monkeypatch.setattr(
        pytest.importorskip("rclpy"),
        "init",
        lambda *a, **k: pytest.fail("ROS initialisation prohibited"),
    )
    s = m.WarehouseQualificationSession(
        tmp_path / "session", Path("/unused/map.yaml"), "navfn_rpp"
    )
    callbacks = {}

    class Node:
        def get_clock(self):
            return SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=2_000_000_000))

        def create_subscription(self, kind, topic, callback, qos):
            callbacks[topic] = callback
            return callback

    s.node = Node()
    s.subscriptions = []
    s.attach()
    info = SimpleNamespace(received_timestamp=0, source_timestamp=0, publisher_gid=bytes(24))
    transform = TransformStamped()
    transform.header.frame_id = "map"
    transform.child_frame_id = "odom"
    transform.header.stamp.sec = 2
    transform.transform.rotation.w = 1.0
    callbacks["/tf"](TFMessage(transforms=[transform]), info)
    contact = m.ContactEvidence()
    contact.source_id = "synthetic"
    contact.sequence = 1
    contact.start_ns = 1
    contact.end_ns = 50_000_001
    contact.physics_steps = 50
    contact.monitored_bodies = s.observer.expected_bodies
    contact.support_pairs = s.observer.expected_support_pairs
    contact.coverage_complete = True
    callbacks["/validation/contacts"](contact, info)
    assert s.observer.contact_ready
    assert s.observer.edges[("map", "odom")].stamp_ns == 2_000_000_000
    # Fault callback is sticky and never escapes the executor callback.
    s.safe_callback(lambda message, info: (_ for _ in ()).throw(ValueError("bad fixture")))(
        None, info
    )
    with pytest.raises(EvidenceFailure, match="bad fixture"):
        s.observer.check()
    result = s.journal.close()
    assert result["complete"]
    rows = [
        json.loads(line)
        for line in (tmp_path / "session/observations.jsonl").read_text().splitlines()
    ]
    assert any(r["kind"] == "tf_edge" and r["middleware_received_wall_ns"] is None for r in rows)
    assert any(r.get("cdr_base64") for r in rows)


def test_harness_dispatch_and_cleanup_paths(ros_session_module, tmp_path, monkeypatch):
    m = ros_session_module
    s = m.WarehouseQualificationSession(tmp_path / "session", Path("/unused/map"), "navfn_rpp")
    requests = []
    monkeypatch.setattr(s, "attach", lambda: setattr(s, "attached", True))
    monkeypatch.setattr(
        m.NavigationSession, "start", lambda self, label, cmd: requests.append(cmd)
    )
    s.processes = [SimpleNamespace(pid=123, poll=lambda: 0)]
    s.start("base", ["mode:=sim", "world:=mapping_lab"])
    assert requests == [["mode:=sim", "world:=warehouse_v1", "diagnostics:=false"]]
    assert s.attached
    assert not any("fault" in arg for arg in requests[0])
    s.node = object()
    s.logs = []
    monkeypatch.setattr(s, "_terminate_owned", lambda: None)
    s.__exit__(AssertionError, AssertionError("stale"), None)
    summary = json.loads((tmp_path / "session/observer-shutdown.json").read_text())
    assert (
        summary["clean_process_shutdown_verified"] and not summary["observer_and_cleanup_complete"]
    )
    assert summary["exception"] == "stale"


def test_harness_cleanup_failure_and_missing_node(ros_session_module, tmp_path, monkeypatch):
    m = ros_session_module
    s = m.WarehouseQualificationSession(tmp_path / "session", Path("/unused/map"), "navfn_rpp")
    s.processes = [SimpleNamespace(poll=lambda: None)]
    s.logs = []
    s.node = object()
    monkeypatch.setattr(
        s, "_stop_assessment", lambda: (_ for _ in ()).throw(ValueError("no stop evidence"))
    )
    monkeypatch.setattr(
        s,
        "_terminate_owned",
        lambda *args: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )
    with pytest.raises(RuntimeError, match="cleanup failed"):
        s.__exit__(ValueError, ValueError("startup"), None)
    summary = json.loads((tmp_path / "session/observer-shutdown.json").read_text())
    assert not summary["clean_process_shutdown_verified"] and not summary["cleanup_completed"]
    assert "cleanup failed" in summary["exception"] and not summary["robot_stop_verified"]


def test_concurrent_producers_order_and_budget(tmp_path):
    j = BufferedJournal(tmp_path / "concurrent.jsonl", capacity=1000)
    workers = [
        threading.Thread(target=lambda: [j.submit("sample", value=i) for i in range(30)])
        for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    status = j.close()
    assert status["complete"] and status["written"] == 120
    rows = [json.loads(line) for line in (tmp_path / "concurrent.jsonl").read_text().splitlines()]
    assert [row["sequence"] for row in rows] == list(range(1, 121))
    assert status["peak_bytes"] <= j.byte_capacity and status["peak_pending"] <= j.capacity


def test_contact_inventory_policy_is_not_reinterpreted(journal):
    o = QualificationObserver(
        journal, expected_bodies=["wheel"], expected_support_pairs=["wheel|correct_floor"]
    )
    o.contact(frame(), 1)
    with pytest.raises(EvidenceFailure, match="configured adapter policy"):
        o.check()


def test_summary_fsync_failure_propagates(tmp_path, monkeypatch):
    import warehouse_qualification.journal as module

    monkeypatch.setattr(
        module.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync failed"))
    )
    with pytest.raises(OSError, match="fsync failed"):
        save_summary(tmp_path / "summary.json", {"status": "incomplete"})


def test_synthetic_original_tf_age_reproduction(journal):
    # These are deliberately synthetic fresh edge fixtures, not recovered TF
    # telemetry. Original W3 did not journal individual edges and cannot prove them.
    o = QualificationObserver(journal)
    now = 4_868_000_000
    o.clock(now, 10_000_000_000)
    edge(o, "map", "odom", 5_300_000_000, receipt_ros=now, mono=10_000_000_000)
    edge(o, "odom", "base_link", 4_800_000_000, receipt_ros=now, mono=10_000_000_000)
    result = o.assess_tf(now, 10_000_000_000, 2_800_000_000)
    assert result["buffer_age_ns"] == 2_068_000_000
    assert result["buffer_observer_discrepancy"] and not result["ready"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("sequence", True),
        ("physics_steps", 0),
        ("start_ns", -1),
        ("end_ns", 1),
        ("coverage_complete", 1),
    ],
)
def test_malformed_contact_never_ready(journal, field, value):
    o = QualificationObserver(journal)
    sample = frame()
    sample[field] = value
    o.contact(sample, 1)
    with pytest.raises(EvidenceFailure, match="Malformed"):
        o.check()
    assert not o.contact_ready


def test_contact_silence_fails_supervision(journal):
    o = QualificationObserver(journal)
    o.contact(frame(), 1)
    with pytest.raises(EvidenceFailure, match="stream stopped"):
        o.check(250_000_002)


def test_queued_node_clock_cannot_make_stale_tf_pass(journal):
    o = QualificationObserver(journal)
    fresh(o)
    o.clock(4_000_000_000, 2_000_000_000)
    result = o.assess_tf(2_000_000_000, 2_000_000_000, 2_000_000_000)
    assert result["buffer_age_ns"] == 2_000_000_000
    assert result["node_vs_observed_clock_ns"] == -2_000_000_000
    assert not result["ready"]


@pytest.mark.parametrize("stamp_value", [True, 1.5, -1, 0])
def test_invalid_dynamic_tf_values_fail(journal, stamp_value):
    o = QualificationObserver(journal)
    edge(o, "map", "odom", stamp_value)
    with pytest.raises(EvidenceFailure, match="Malformed TF"):
        o.check()


def test_writer_stall_supervision_without_waiting_five_seconds(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def blocked(_):
        entered.set()
        release.wait(2)

    j = BufferedJournal(tmp_path / "unused", persist=blocked)
    try:
        j.submit("one")
        assert entered.wait(1)
        oldest = j.status()["oldest_pending_ns"]
        with pytest.raises(EvidenceFailure, match="durable progress"):
            j.check(oldest + 5_000_000_001)
    finally:
        release.set()
        status = j.close()
    assert not status["complete"]


def test_writer_timing_distinct_from_callback_timing(tmp_path):
    path = tmp_path / "timing.jsonl"
    j = BufferedJournal(path)
    j.submit("one")
    status = j.close()
    row = json.loads(path.read_text())
    assert row["writer_started_monotonic_ns"] >= row["callback_monotonic_ns"]
    assert status["max_queue_delay_ns"] >= 0 and status["max_persist_duration_ns"] > 0
    assert status["oldest_pending_ns"] is None
