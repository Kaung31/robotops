"""Controlled fault traces; no ROS runtime required."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robot_diagnostics.freshness import ERROR, OK, STALE, WARN, Monitor, Policy


def ready():
    monitor = Monitor(("scan",))
    monitor.observe("scan", 10_000_000_000, 10_000_000_000, 0.0)
    monitor.observe("scan", 10_100_000_000, 10_100_000_000, 0.1)
    assert monitor.evaluate(10_100_000_000, 0.1)["scan"].level == OK
    return monitor


def test_startup_missing_input_and_disabled_input():
    monitor = Monitor(("odom",))
    assert monitor.evaluate(0, 0)["clock"].reason == "clock_uninitialized"
    statuses = monitor.evaluate(1, 0.1)
    assert set(statuses) == {"clock", "odom"}
    assert statuses["odom"].reason == "not_observed"
    with pytest.raises(ValueError):
        monitor.observe("scan", 1, 1, 0.1)


@pytest.mark.parametrize("age,level", [(0.5, OK), (0.5001, WARN), (1, WARN), (1.0001, STALE)])
def test_dropout_boundaries(age, level):
    monitor = ready()
    assert monitor.evaluate(10_100_000_000 + round(age * 1e9), 0.1 + age)["scan"].level == level


def test_dropout_requires_two_new_samples_for_recovery():
    monitor = ready()
    assert monitor.evaluate(12_000_000_000, 2)["scan"].reason == "receipt_timeout"
    monitor.observe("scan", 12_000_000_000, 12_000_000_000, 2)
    assert monitor.evaluate(12_000_000_000, 2)["scan"].level == STALE
    monitor.observe("scan", 12_100_000_000, 12_100_000_000, 2.1)
    assert monitor.evaluate(12_100_000_000, 2.1)["scan"].level == OK


def test_repeated_stamp_receipts_do_not_mask_stale_data():
    monitor = ready()
    monitor.observe("scan", 10_100_000_000, 11_200_000_000, 1.2)
    status = monitor.evaluate(11_200_000_000, 1.2)["scan"]
    assert (status.level, status.reason) == (ERROR, "stamp_timeout")
    monitor.observe("scan", 11_300_000_000, 11_300_000_000, 1.3)
    assert monitor.evaluate(11_300_000_000, 1.3)["scan"].level == STALE
    monitor.observe("scan", 11_400_000_000, 11_400_000_000, 1.4)
    assert monitor.evaluate(11_400_000_000, 1.4)["scan"].level == OK


@pytest.mark.parametrize(
    "stamp,reason",
    [
        (0, "invalid_stamp"),
        (-1, "invalid_stamp"),
        (True, "invalid_stamp"),
        (float("nan"), "invalid_stamp"),
        (11_000_000_000, "future_stamp"),
        (10_000_000_000, "stamp_regressed"),
    ],
)
def test_bad_stamps_never_pass(stamp, reason):
    monitor = ready()
    monitor.observe("scan", stamp, 10_200_000_000, 0.2)
    status = monitor.evaluate(10_200_000_000, 0.2)["scan"]
    assert (status.level, status.reason) == (ERROR, reason)


def test_clock_pause_is_not_reported_as_sensor_dropout_and_resume_clears_history():
    monitor = ready()
    status = monitor.evaluate(10_100_000_000, 2.1001)
    assert status["clock"].level == STALE
    assert status["scan"].reason == "clock_not_advancing"
    epoch = status["clock"].values["clock_epoch"]
    status = monitor.evaluate(10_200_000_000, 2.2)
    assert status["scan"].reason == "not_observed"
    assert status["clock"].values["clock_epoch"] != epoch


@pytest.mark.parametrize("reset", [0, 1_000_000_000])
def test_reset_invalidates_old_epoch(reset):
    monitor = ready()
    monitor.evaluate(reset, 0.2)
    assert monitor.samples == {}
    monitor.observe("scan", 1_100_000_000, 1_100_000_000, 0.3)
    assert monitor.evaluate(1_100_000_000, 0.3)["scan"].level == STALE
    monitor.observe("scan", 1_200_000_000, 1_200_000_000, 0.4)
    assert monitor.evaluate(1_200_000_000, 0.4)["scan"].level == OK


@pytest.mark.parametrize(
    "change",
    [
        {"warn_seconds": 0},
        {"error_seconds": -1},
        {"future_seconds": float("nan")},
        {"clock_stall_seconds": float("inf")},
        {"warn_seconds": True},
        {"warn_seconds": 1},
    ],
)
def test_invalid_policy(change):
    with pytest.raises(ValueError):
        Policy(**change)


def test_independent_streams_and_invalid_stamp_recovery():
    monitor = Monitor(("scan", "odom"))
    for now in (10_000_000_000, 10_100_000_000):
        monitor.observe("scan", now, now, 0.1)
    statuses = monitor.evaluate(10_100_000_000, 0.1)
    assert statuses["scan"].level == OK
    assert statuses["odom"].level == STALE
    monitor.observe("scan", 0, 10_200_000_000, 0.2)
    monitor.observe("scan", 10_300_000_000, 10_300_000_000, 0.3)
    assert monitor.evaluate(10_300_000_000, 0.3)["scan"].level == STALE
    monitor.observe("scan", 10_400_000_000, 10_400_000_000, 0.4)
    assert monitor.evaluate(10_400_000_000, 0.4)["scan"].level == OK


@pytest.mark.parametrize("streams", [(), ("scan", "scan")])
def test_invalid_stream_selection(streams):
    with pytest.raises(ValueError):
        Monitor(streams)
