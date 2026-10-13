"""Ground-truth comparison is time-aligned and never invents samples."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_runner.ground_truth import aligned_errors, summarize, truth_at  # noqa: E402

IDENTITY = (0.0, 0.0, 0.0)


def straight_line(speed=0.25, period_ns=20_000_000, count=200):
    return [(i * period_ns, speed * i * period_ns / 1e9, 0.0, 0.0) for i in range(count)]


def test_offset_latest_samples_are_not_misread_as_error():
    # The W3 v5 failure: latest odom and truth were 86 ms apart at 0.25 m/s.
    truth = straight_line(count=175)  # latest truth sample at 3.480 s
    stamp = 3_480_000_000 - 86_000_000
    estimate = (stamp, 0.25 * stamp / 1e9, 0.0, 0.0)
    naive = abs(truth[-1][1] - estimate[1])
    assert naive == pytest.approx(0.0215)  # latest-vs-latest "exceeds" a 20 mm bound
    [row] = aligned_errors([estimate], truth, world_to_map=IDENTITY)
    assert row["status"] == "ALIGNED"
    assert row["xy_error_m"] < 1e-9


def test_no_extrapolation_or_wide_gap_interpolation():
    truth = [(0, 0.0, 0.0, 0.0), (50_000_000, 0.1, 0.0, 0.0), (1_000_000_000, 1.0, 0.0, 0.0)]
    rows = aligned_errors(
        [
            (-1, 0.0, 0.0, 0.0),
            (25_000_000, 0.05, 0.0, 0.0),
            (500_000_000, 0.5, 0.0, 0.0),
            (2_000_000_000, 1.0, 0.0, 0.0),
        ],
        truth,
        world_to_map=IDENTITY,
    )
    assert [r["status"] for r in rows] == ["UNAVAILABLE", "ALIGNED", "UNAVAILABLE", "UNAVAILABLE"]
    summary = summarize(rows)
    assert summary["aligned"] == 1 and summary["unavailable"] == 3


def test_exact_stamp_and_yaw_wraparound():
    truth = [(0, 0.0, 0.0, 3.1), (10, 0.0, 0.0, -3.1)]
    assert truth_at(truth, 0, 100) == (0.0, 0.0, 3.1)
    _, _, yaw = truth_at(truth, 5, 100)
    assert abs(abs(yaw) - math.pi) < 1e-9  # interpolates across ±pi, not through zero


def test_world_to_map_must_be_applied():
    truth = [(0, 1.0, 0.0, 0.0), (10, 1.0, 0.0, 0.0)]
    [row] = aligned_errors([(5, 2.0, 0.0, 0.0)], truth, world_to_map=(1.0, 0.0, 0.0))
    assert row["xy_error_m"] < 1e-9
    with pytest.raises(TypeError):
        aligned_errors([(5, 2.0, 0.0, 0.0)], truth)  # frame relation is never assumed


def test_invalid_gap_is_rejected():
    with pytest.raises(ValueError):
        aligned_errors([], [], world_to_map=IDENTITY, max_gap_ns=0)
