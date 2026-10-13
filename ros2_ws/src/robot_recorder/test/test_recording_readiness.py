"""Recorder readiness and shutdown fixtures; no subprocess or ROS initialization."""

import json
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as S

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robot_recorder.recording import (  # noqa: E402
    ACCOUNTING_MARKERS,
    Recorder,
    load_recording_config,
    loss_accounting,
)


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("Real recorder prohibited")
    )
    r = Recorder.__new__(Recorder)
    r.directory = tmp_path
    r.name = "owned"
    r.use_sim_time = True
    r.config = {
        "topics": ["/map", "/clock"],
        "required_topics": ["/map"],
        "startup_topics": ["/map"],
        "qos": {"/map": {"durability": "transient_local"}},
    }
    r.process = S(poll=lambda: None, returncode=None)
    (tmp_path / "recorder.log").write_text(
        "Recording...\nSim time /clock found, starting recording.\nSubscribed to topic '/clock'\n"
    )
    (tmp_path / "telemetry").mkdir()
    (tmp_path / "telemetry/bag.mcap").write_bytes(b"\x89MCAP0\r\n")
    return r


def endpoint(node="owned", durability=1, kind="T"):
    return S(node_name=node, topic_type=kind, qos_profile=S(durability=durability))


def assess(r, subs=None, pubs=None, compatible=lambda p, s: True):
    return r.startup_status(
        subs or (lambda t: [endpoint()] * (2 if t == "/clock" and r.use_sim_time else 1)),
        pubs or (lambda t: [endpoint("publisher")]),
        compatible,
    )


def test_ready_is_capability_only_not_final_coverage(recorder):
    s = assess(recorder)
    assert s["ready"] and s["coverage"] == "NOT_YET_VERIFIED"
    assert "/clock" in s["topics"]


@pytest.mark.parametrize(
    "change,expected",
    [
        ("publisher", "publisher_missing"),
        ("subscription", "subscription_missing_or_ambiguous"),
        ("duplicate", "subscription_missing_or_ambiguous"),
        ("type", "type_mismatch"),
        ("qos", "qos_incompatible_or_unknown"),
        ("volatile", "durable_history_not_requested"),
        ("clock", "clock_not_received"),
        ("storage", "storage_not_open"),
        ("writer", "writer_not_started"),
    ],
)
def test_startup_failure_is_specific(recorder, change, expected):
    kw = {}
    if change == "publisher":
        kw["pubs"] = lambda t: []
    if change == "subscription":
        kw["subs"] = lambda t: [endpoint("unrelated")]
    if change == "duplicate":
        kw["subs"] = lambda t: [endpoint(), endpoint()]
    if change == "type":
        kw["pubs"] = lambda t: [endpoint("publisher", kind="wrong")]
    if change == "qos":
        kw["compatible"] = lambda p, s: False
    if change == "volatile":
        kw["subs"] = lambda t: [endpoint(durability=2)]
    if change in ("clock", "writer"):
        (recorder.directory / "recorder.log").write_text(
            "Recording..." if change == "clock" else ""
        )
    if change == "storage":
        (recorder.directory / "telemetry/bag.mcap").unlink()
    s = assess(recorder, **kw)
    assert not s["ready"] and any(expected in c for c in s["causes"])


def test_storage_is_open_before_the_mcap_header_is_flushed(recorder):
    # rosbag2 creates the .mcap file on open; the header reaches disk with the first chunk.
    (recorder.directory / "telemetry/bag.mcap").write_bytes(b"")
    assert assess(recorder)["ready"]
    (recorder.directory / "telemetry/bag.mcap").write_bytes(b"SQLite format 3\0")
    s = assess(recorder)
    assert not s["ready"] and "recorder.storage_not_open" in s["causes"]


@pytest.mark.parametrize("missing", ["writer", "clock", "subscriptions", "publishers"])
def test_empty_storage_file_alone_never_makes_the_recorder_ready(recorder, missing):
    (recorder.directory / "telemetry/bag.mcap").write_bytes(b"")
    log = recorder.directory / "recorder.log"
    kw = {}
    if missing == "writer":
        log.write_text(log.read_text().replace("Recording...\n", ""))
    if missing == "clock":
        log.write_text(log.read_text().replace("Sim time /clock found, starting recording.\n", ""))
    if missing == "subscriptions":
        kw["subs"] = lambda t: []
    if missing == "publishers":
        kw["pubs"] = lambda t: []
    s = assess(recorder, **kw)
    assert s["storage_open"] and not s["ready"]


def test_existing_output_directory_is_never_reused(tmp_path, monkeypatch):
    # A pre-existing file must never stand in for storage the recorder opened.
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Recorder started"))
    (tmp_path / "telemetry").mkdir()
    (tmp_path / "telemetry/telemetry_0.mcap").write_bytes(b"")
    with pytest.raises(RuntimeError, match="already exists"):
        Recorder(tmp_path, "run", {"qos": {}, "topics": ["odom"]}, True)
    assert not (tmp_path / "recorder.log").exists()


def test_inspection_failure_is_never_ready(recorder):
    def broken(t):
        raise OSError("graph inspection failed")

    with pytest.raises(OSError):
        assess(recorder, pubs=broken)
    recorder.process = S(poll=lambda: 1, returncode=1)
    with pytest.raises(RuntimeError, match="exited unexpectedly"):
        assess(recorder)


def test_optional_startup_config_is_backward_compatible(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text("topics: [odom]\nrequired_topics: [odom]\nqos: {}\n")
    assert load_recording_config(p)["startup_topics"] == ["odom"]
    p.write_text("topics: [odom]\nrequired_topics: [odom]\nstartup_topics: [missing]\nqos: {}\n")
    with pytest.raises(ValueError):
        load_recording_config(p)


@pytest.mark.parametrize("early,forced", [(True, False), (False, True)])
def test_interrupted_or_forced_recorder_cannot_validate(recorder, early, forced):
    calls = []
    recorder.log = (recorder.directory / "dummy").open("w")

    def wait(timeout):
        if forced and timeout == 10:
            raise subprocess.TimeoutExpired("fixture", timeout)

    recorder.process = S(
        poll=lambda: 1 if early else None,
        returncode=1 if early else 0,
        send_signal=lambda s: calls.append(s),
        wait=wait,
        terminate=lambda: calls.append("terminate"),
    )
    with pytest.raises(RuntimeError, match="Recorder failed"):
        recorder.stop()
    assert recorder.log.closed
    if not early:
        assert calls == [signal.SIGINT, "terminate"]


def test_reported_transport_loss_cannot_be_certified_as_complete(recorder):
    recorder.log = (recorder.directory / "dummy").open("w")
    recorder.process = S(
        poll=lambda: None, returncode=0, send_signal=lambda s: None, wait=lambda timeout: None
    )
    with (recorder.directory / "recorder.log").open("a") as f:
        f.write("".join(m + "\n" for m in ACCOUNTING_MARKERS))
        f.write("Number of messages lost on the transport layer: 1\n")
    with pytest.raises(RuntimeError, match="transport loss"):
        recorder.stop()
    assert recorder.log.closed


@pytest.mark.parametrize("missing", ACCOUNTING_MARKERS)
def test_silent_log_without_complete_loss_accounting_fails_closed(recorder, missing):
    recorder.log = (recorder.directory / "dummy").open("w")
    recorder.process = S(
        poll=lambda: None, returncode=0, send_signal=lambda s: None, wait=lambda timeout: None
    )
    (recorder.directory / "recorder.log").write_text(
        "".join(m + "\n" for m in ACCOUNTING_MARKERS if m != missing)
    )
    with pytest.raises(RuntimeError, match="accounting incomplete"):
        recorder.stop()
    assert recorder.log.closed
    saved = json.loads((recorder.directory / "message_loss.json").read_text())
    assert saved["accounting_complete"] is False and saved["markers"][missing] is False


def test_complete_accounting_is_saved_beside_an_unchanged_bag_summary(recorder, monkeypatch):
    # Validators compare the summary with an independent re-inspection of the bag.
    import robot_recorder.recording as module

    summary = {"path": "telemetry", "format": "mcap", "bytes": 1, "topic_counts": {"/map": 1}}
    monkeypatch.setattr(module, "inspect_bag", lambda directory, required: dict(summary))
    recorder.log = (recorder.directory / "dummy").open("w")
    recorder.process = S(
        poll=lambda: None, returncode=0, send_signal=lambda s: None, wait=lambda timeout: None
    )
    (recorder.directory / "recorder.log").write_text("".join(m + "\n" for m in ACCOUNTING_MARKERS))
    assert recorder.stop() == summary
    saved = json.loads((recorder.directory / "message_loss.json").read_text())
    assert saved["accounting_complete"] and saved["transport_lost_messages"] == 0


def test_loss_accounting_is_explicit():
    complete = "".join(m + "\n" for m in ACCOUNTING_MARKERS)
    assert loss_accounting(complete) == dict(
        source="rosbag2 recorder log",
        transport_lost_messages=0,
        loss_reports=0,
        markers={m: True for m in ACCOUNTING_MARKERS},
        accounting_complete=True,
    )
    lossy = complete + (
        "[WARN] [1.0] [recorder_x]: Number of messages lost on the transport layer: 2\n"
        "[WARN] [2.0] [recorder_x]: Number of messages lost on the transport layer: 3\n"
    )
    assert loss_accounting(lossy)["transport_lost_messages"] == 5
    assert loss_accounting(lossy)["loss_reports"] == 2
    assert loss_accounting("")["accounting_complete"] is False


def test_actual_jazzy_qos_compatibility_has_no_unknown_success():
    qos = pytest.importorskip("rclpy.qos")
    pub = qos.QoSProfile(
        depth=1,
        durability=qos.DurabilityPolicy.TRANSIENT_LOCAL,
        liveliness=qos.LivelinessPolicy.AUTOMATIC,
    )
    sub = qos.QoSProfile(
        depth=1,
        durability=qos.DurabilityPolicy.TRANSIENT_LOCAL,
        liveliness=qos.LivelinessPolicy.AUTOMATIC,
    )
    assert qos.qos_check_compatible(pub, sub)[0] == qos.QoSCompatibility.OK
    pub.durability = qos.DurabilityPolicy.VOLATILE
    assert qos.qos_check_compatible(pub, sub)[0] != qos.QoSCompatibility.OK


@pytest.mark.parametrize("count", [0, 1, 3])
def test_sim_time_clock_needs_both_owned_readers(recorder, count):
    status = assess(recorder, subs=lambda t: [endpoint()] * (count if t == "/clock" else 1))
    assert not status["ready"]
    assert "subscription_missing_or_ambiguous" in status["topics"]["/clock"]["causes"]


def test_clock_reader_pair_cannot_hide_bad_qos(recorder):
    status = assess(
        recorder,
        subs=lambda t: [endpoint(), endpoint(durability=2)] if t == "/clock" else [endpoint()],
        compatible=lambda p, s: s.durability == 1,
    )
    assert not status["ready"]
    assert "qos_incompatible_or_unknown" in status["topics"]["/clock"]["causes"]


def test_clock_readers_without_recording_acknowledgement_are_not_ready(recorder):
    log = recorder.directory / "recorder.log"
    log.write_text(log.read_text().replace("Subscribed to topic '/clock'", ""))
    assert "recorder./clock.recording_subscription_not_acknowledged" in assess(recorder)["causes"]


@pytest.mark.parametrize(
    "sim_time,record_clock,expected",
    [(True, True, 2), (True, False, 1), (False, True, 1), (False, False, None)],
)
def test_clock_cardinality_depends_on_timesource_and_recording(
    recorder, sim_time, record_clock, expected
):
    recorder.use_sim_time = sim_time
    if not record_clock:
        recorder.config["topics"].remove("/clock")
        log = recorder.directory / "recorder.log"
        log.write_text(log.read_text().replace("Subscribed to topic '/clock'", ""))
    else:
        recorder.config["startup_topics"].append("/clock")
    status = assess(
        recorder,
        subs=lambda topic: [endpoint()] * (expected if topic == "/clock" else 1),
    )
    assert status["ready"]
    if expected is None:
        assert "/clock" not in status["topics"]
    else:
        assert status["topics"]["/clock"]["expected_subscriptions"] == expected
        assert status["topics"]["/clock"]["recorder_subscriptions"] == expected


def test_another_nodes_clock_reader_does_not_complete_owned_pair(recorder):
    status = assess(
        recorder,
        subs=lambda topic: [endpoint(), endpoint("other")] if topic == "/clock" else [endpoint()],
    )
    assert not status["ready"]
    assert status["topics"]["/clock"]["recorder_subscriptions"] == 1
    assert "subscription_missing_or_ambiguous" in status["topics"]["/clock"]["causes"]


def test_second_clock_reader_type_is_checked(recorder):
    status = assess(
        recorder,
        subs=lambda topic: [endpoint(), endpoint(kind="wrong")]
        if topic == "/clock"
        else [endpoint()],
    )
    assert not status["ready"]
    assert "type_mismatch" in status["topics"]["/clock"]["causes"]
