"""Recorder readiness and shutdown fixtures; no subprocess or ROS initialization."""

import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as S

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robot_recorder.recording import Recorder, load_recording_config  # noqa: E402


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
        "Recording...\nSim time /clock found, starting recording.\n"
    )
    (tmp_path / "telemetry").mkdir()
    (tmp_path / "telemetry/bag.mcap").write_bytes(b"\x89MCAP0\r\n")
    return r


def endpoint(node="owned", durability=1, kind="T"):
    return S(node_name=node, topic_type=kind, qos_profile=S(durability=durability))


def assess(r, subs=None, pubs=None, compatible=lambda p, s: True):
    return r.startup_status(
        subs or (lambda t: [endpoint()]), pubs or (lambda t: [endpoint("publisher")]), compatible
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
        f.write("Number of messages lost on the transport layer: 1\n")
    with pytest.raises(RuntimeError, match="transport loss"):
        recorder.stop()
    assert recorder.log.closed


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
