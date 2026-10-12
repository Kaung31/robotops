"""Mission worker fixtures: no node construction, executor or real recorder."""

import sys
from pathlib import Path
from types import SimpleNamespace as S

import pytest

# Needs a sourced ROS workspace; colcon runs it as `recording_preparation`.
pytest.importorskip("rclpy")

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1]),
    str(Path(__file__).resolve().parents[2] / "robot_recorder"),
]
from mission_manager import server  # noqa: E402


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(server.rclpy, "init", lambda *a, **k: pytest.fail("ROS prohibited"))
    monkeypatch.setattr(server.rclpy, "create_node", lambda *a, **k: pytest.fail("ROS prohibited"))
    import subprocess

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("Process prohibited"))


def test_preparation_waits_for_full_recorder_readiness_and_does_not_start_mission(monkeypatch):
    calls = []
    statuses = iter(
        [
            {"ready": False, "causes": ["recorder./map.publisher_missing"]},
            {"ready": True, "causes": []},
        ]
    )
    recorder = S(startup_status=lambda *a: next(statuses))
    monkeypatch.setattr(server, "Recorder", lambda *a: recorder)
    monkeypatch.setattr(server.time, "sleep", lambda _: calls.append("wait"))
    fake = S(
        settings={"startup_timeout": 15},
        navigator=S(server_is_ready=lambda: True),
        now_ns=lambda: 10,
        check=lambda g: None,
        store=S(
            directory=Path("/unused"),
            run_id="fixture",
            event=lambda *a, **k: calls.append(a[0]),
            start=lambda *a: pytest.fail("premature start"),
        ),
        recording_config={},
        get_parameter=lambda n: S(value=True),
        get_subscriptions_info_by_topic=lambda _: [],
        get_publishers_info_by_topic=lambda _: [],
        transition=lambda *a: calls.append(a[1]),
    )
    server.MissionServer.prepare(fake, S(request=S(record=True)))
    assert calls == ["wait", "recorder_ready", "recording"]


def test_preparation_cancellation_skips_goal_and_preserves_recorder_cleanup_ownership(monkeypatch):
    recorder = S(startup_status=lambda *a: pytest.fail("canceled readiness query"))
    monkeypatch.setattr(server, "Recorder", lambda *a: recorder)

    def cancel(g):
        raise server.MissionCanceled("canceled during preparation")

    fake = S(
        settings={"startup_timeout": 15},
        navigator=S(server_is_ready=lambda: True),
        now_ns=lambda: 10,
        check=cancel,
        store=S(directory=Path("/unused"), run_id="fixture"),
        recording_config={},
        get_parameter=lambda n: S(value=True),
    )
    with pytest.raises(server.MissionCanceled):
        server.MissionServer.prepare(fake, S(request=S(record=True)))
    assert fake.recorder is recorder  # execute_owned retains responsibility for stop.


@pytest.mark.parametrize(
    "prepare_fail,stop_fail,cancel_unconfirmed",
    [(False, False, False), (True, False, False), (False, True, False), (False, False, True)],
)
def test_worker_timings_and_failure_verdicts(
    monkeypatch, tmp_path, prepare_fail, stop_fail, cancel_unconfirmed
):
    clock = [100.0]
    persisted = {}
    events = []
    monkeypatch.setattr(server.time, "monotonic", lambda: clock[0])

    def advance(seconds):
        clock[0] += seconds

    class Store:
        def __init__(self, *a):
            self.run_id = "new"
            self.directory = tmp_path / "new"

        def start(self, ns):
            persisted["start"] = ns

        def event(self, *a, **k):
            events.append(a)

        def finish(self, r):
            persisted["result"] = r.copy()

    monkeypatch.setattr(server, "RunStore", Store)

    def prepare(g):
        fake.recorder = S(stop=stop)
        advance(5)
        if prepare_fail:
            raise server.MissionCanceled("startup interrupted")

    def navigate(g, p):
        fake.nav_pending = object() if cancel_unconfirmed else None
        advance(2)

    def stop():
        advance(3)
        if stop_fail:
            raise RuntimeError("recorder incomplete coverage")
        return {"format": "mcap"}

    fake = S(
        settings={"map_file": "", "software_revision": "", "artifact_root": str(tmp_path)},
        recording_config={},
        nav_pending=object() if cancel_unconfirmed else None,
        stopping=S(is_set=lambda: False),
        faulted=False,
        now_ns=lambda: int(clock[0] * 10**9),
        get_parameter=lambda n: S(value=True),
        prepare=prepare,
        navigate=navigate,
        check=lambda g: None,
        transition=lambda *a: None,
        cancel_navigation=lambda: not cancel_unconfirmed,
        get_logger=lambda: S(info=lambda m: None),
        recorder=S(stop=stop),
    )
    goal = S(
        request=S(label="fixture", waypoints=[server.PoseStamped()], record=True),
        is_cancel_requested=prepare_fail,
        succeed=lambda: None,
        canceled=lambda: None,
        abort=lambda: None,
    )
    result = server.MissionServer.execute_owned(fake, goal)
    saved = persisted["result"]
    assert saved["preparation_wall_seconds"] == 5
    assert saved["elapsed_wall_seconds"] == (None if prepare_fail else 2)
    assert saved["elapsed_ros_seconds"] == (None if prepare_fail else 2)
    assert saved["total_elapsed_wall_seconds"] == (8 if prepare_fail else 10)
    if prepare_fail:
        assert "start" not in persisted and result.outcome == "canceled"
    elif stop_fail:
        assert result.outcome == "failed"
    elif cancel_unconfirmed:
        assert result.outcome == "cancellation_unconfirmed" and fake.faulted
    else:
        assert result.outcome == "succeeded"
