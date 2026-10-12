"""Deterministic motion evidence fixtures; no ROS or child processes."""

import copy
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from warehouse_qualification.localisation import LocalisationReadiness  # noqa: E402

NS = 10**9
COV = [0.04, 0.04, 0.03]


def feed(policy, start, end, position=0.0, speed=0.0, source=None):
    for tick in range(round(start * 10), round(end * 10) + 1):
        for name in [source] if source else ["odom", "truth"]:
            policy.observe(
                name,
                tick * NS // 10,
                tick * NS // 10,
                position,
                0.0,
                0.0,
                speed if name == "odom" else None,
                0.0 if name == "odom" else None,
            )


def armed():
    p = LocalisationReadiness()
    feed(p, 1, 3)
    p.arm(3 * NS, 3 * NS, NS, COV)
    return p


def test_old_stationary_startup_pose_is_not_a_heartbeat_failure():
    p = armed()
    feed(p, 3.1, 8)
    s = p.assess(8 * NS, 8 * NS, NS, COV)
    assert s["ready"] and s["mode"] == "stationary_startup"
    assert s["pose_stamp_ns"] == NS and s["pose_age_ns"] == 7 * NS
    feed(p, 8.1, 34)
    assert "amcl.stationary_startup_expired" in p.assess(34 * NS, 34 * NS, NS, COV)["causes"]


def test_stationary_to_motion_has_bounded_real_update_handoff():
    p = armed()
    feed(p, 3.1, 8)
    feed(p, 8.1, 8.2, 0.01, 0.01)
    s = p.assess(82 * NS // 10, 82 * NS // 10, NS, COV)
    assert s["ready"] and s["mode"] == "awaiting_first_motion_update"
    missing = copy.deepcopy(p)
    assert p.assess(82 * NS // 10, 82 * NS // 10, int(8.15 * NS), COV)["ready"]
    feed(p, 8.3, 13.3, 0.01, 0.01)
    feed(missing, 8.3, 13.3, 0.01, 0.01)
    assert (
        "amcl.first_motion_update_missing"
        in missing.assess(int(13.3 * NS), int(13.3 * NS), NS, COV)["causes"]
    )
    assert (
        "amcl.moving_pose_stale"
        in p.assess(int(13.3 * NS), int(13.3 * NS), int(8.15 * NS), COV)["causes"]
    )
    assert p.assess(int(13.3 * NS), int(13.3 * NS), 13 * NS, COV)["ready"]


@pytest.mark.parametrize(
    "stamp,cov,valid",
    [
        (None, COV, True),
        (NS, [math.nan, 0, 0], True),
        (NS, [0.26, 0, 0], True),
        (NS, [-0.1, 0, 0], True),
        (NS, COV, False),
        (4 * NS, COV, True),
    ],
)
def test_initial_localisation_cannot_be_missing_invalid_or_future(stamp, cov, valid):
    p = LocalisationReadiness()
    feed(p, 1, 3)
    with pytest.raises(RuntimeError, match="initial_pose"):
        p.arm(3 * NS, 3 * NS, stamp, cov, valid)


@pytest.mark.parametrize("source", ["odom", "truth"])
def test_missing_stale_or_frozen_motion_metadata_fails_closed(source):
    p = armed()
    feed(p, 3.1, 8, source=source)
    s = p.assess(8 * NS, 8 * NS, NS, COV)
    assert not s["ready"] and any("stale" in c for c in s["causes"])
    p.observe(source, NS, 9 * NS, 0, 0, 0, 0, 0)
    assert not p.assess(9 * NS, 9 * NS, NS, COV)["ready"]


def test_no_initial_stationarity_from_incorrect_zero_twist():
    p = LocalisationReadiness()
    feed(p, 1, 2)
    feed(p, 2.1, 3, 0.1, 0.0)
    with pytest.raises(RuntimeError, match="motion_evidence"):
        p.arm(3 * NS, 3 * NS, NS, COV)


def test_contradictory_motion_and_lost_continuity_are_sticky():
    p = armed()
    feed(p, 3.1, 4, 0.1, 0.0, source="truth")
    feed(p, 3.1, 4, source="odom")
    assert "motion.odom_truth_disagreement" in p.assess(4 * NS, 4 * NS, NS, COV)["causes"]
    p = armed()
    feed(p, 5, 7)
    assert "motion.coverage_lost_after_arming" in p.assess(7 * NS, 7 * NS, NS, COV)["causes"]


def test_unarmed_policy_and_clock_regression_cannot_certify_localisation():
    p = LocalisationReadiness()
    feed(p, 1, 3)
    assert "amcl.initial_pose_missing" in p.assess(3 * NS, 3 * NS, NS, COV)["causes"]
    p = armed()
    p.observe("odom", 2 * NS, 4 * NS, 0, 0, 0, 0, 0)
    assert "motion.invalid_or_regressed" in p.assess(4 * NS, 4 * NS, NS, COV)["causes"]


def test_pose_stamp_regression_is_not_a_stationary_exemption():
    p = armed()
    feed(p, 3.1, 8)
    assert "amcl.pose_stamp_regressed" in p.assess(8 * NS, 8 * NS, NS // 2, COV)["causes"]
    assert "amcl.pose_stamp_regressed" in p.assess(8 * NS, 8 * NS, NS, COV)["causes"]


def test_first_motion_handoff_is_bounded_in_ros_and_wall_time():
    p = armed()
    feed(p, 3.1, 8)
    feed(p, 8.1, 8.2, 0.01, 0.01)
    p.samples["odom"].clear()
    p.samples["truth"].clear()
    for n in ("odom", "truth"):
        p.observe(n, 14 * NS, int(8.3 * NS), 0.01, 0.0, 0.0, 0.01, 0.0)
    assert (
        "amcl.first_motion_update_missing" in p.assess(14 * NS, int(8.3 * NS), NS, COV)["causes"]
    )


def test_nonfinite_motion_cannot_prove_stationarity():
    p = armed()
    p.observe("truth", 4 * NS, 4 * NS, 0.0, 0.0, math.nan)
    assert "motion.invalid_or_regressed" in p.assess(4 * NS, 4 * NS, NS, COV)["causes"]
