"""Aisle traversal is decided from recorded positions, never assumed or guessed."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_runner.aisle_traversal import (  # noqa: E402
    INCONCLUSIVE,
    NOT_MET,
    VERIFIED,
    analyse,
    assess,
)

# warehouse_v2's aisle_1 and the two rack blocks either side of it.
AISLE = dict(axis="y", low=1.5, high=5.5, lateral=[2.4, 3.6])
OBSTACLES = [(-2.0, 2.4, 1.5, 5.5), (3.6, 10.0, 1.5, 5.5)]
REQUIRED = ["low_to_high", "high_to_low"]
PERIOD = 50_000_000  # 20 Hz


def route(points, speed=0.25, start_ns=1_000_000_000):
    """Constant-speed polyline sampled at 20 Hz: [(stamp_ns, x, y), ...]."""
    samples, t = [(start_ns, *points[0])], start_ns
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        steps = max(1, math.ceil(math.dist((x0, y0), (x1, y1)) / (speed * PERIOD / 1e9)))
        for i in range(1, steps + 1):
            t += PERIOD
            samples.append((t, x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps))
    return samples


THROUGH = [(0.0, 0.0), (3.0, 0.0), (3.0, 7.0), (3.0, 0.0), (0.0, 0.0)]
PERIMETER = [
    (0.0, 0.0),
    (3.0, 0.0),
    (0.98, 1.0),
    (0.98, 6.0),
    (3.0, 7.0),
    (0.98, 6.0),
    (0.98, 1.0),
    (3.0, 0.0),
    (0.0, 0.0),
]


def window(samples):
    return samples[0][0], samples[-1][0]


def verdict(localized, truth="same", **kwargs):
    truth = localized if truth == "same" else truth
    kwargs.setdefault("obstacles", OBSTACLES)
    return assess(
        localized,
        AISLE,
        window_ns=window(localized),
        required=REQUIRED,
        start_zone="low",
        ground_truth=truth,
        **kwargs,
    )


def test_round_trip_through_the_aisle_is_verified_with_interpolated_gate_times():
    samples = route(THROUGH)
    result = verdict(samples)
    assert result["verdict"] == VERIFIED, result["reasons"]
    north, south = result["sources"]["localized"]["traversals"]
    assert (north["direction"], south["direction"]) == ("low_to_high", "high_to_low")
    # 3 m to the gate line at y=1.5, then 4 m of aisle, at 0.25 m/s.
    assert north["entry_ns"] == pytest.approx(1e9 + (3.0 + 1.5) / 0.25 * 1e9, abs=PERIOD)
    assert north["duration_s"] == pytest.approx(16.0, abs=0.1)
    assert north["path_length_m"] == pytest.approx(4.0, abs=0.02)
    assert north["max_lateral_offset_m"] == pytest.approx(0.0)
    assert north["min_centre_to_wall_m"] == pytest.approx(0.6)
    assert result["sources"]["ground_truth"]["traversals"] == [north, south]


def test_perimeter_bypass_like_warehouse_v1_fails_the_route_requirement():
    result = verdict(route(PERIMETER), obstacles=[])
    assert result["verdict"] == NOT_MET
    localized = result["sources"]["localized"]
    assert localized["traversals"] == []
    assert [b["direction"] for b in localized["bypasses"]] == ["low_to_high", "high_to_low"]


def test_entering_and_backing_out_is_reported_but_does_not_count():
    samples = route([(0.0, 0.0), (3.0, 0.0), (3.0, 2.5), (3.0, 0.5), (3.0, 7.0), (3.0, 0.0)])
    result = verdict(samples)
    assert result["verdict"] == VERIFIED
    [aborted] = result["sources"]["localized"]["aborted_entries"]
    assert aborted["side"] == "low"


@pytest.mark.parametrize(
    ("points", "end_zone"),
    [
        ([(0.0, 0.0), (3.0, 0.0), (3.0, 7.0)], "high"),  # never came back
        ([(0.0, 0.0), (3.0, 0.0), (3.0, 7.0), (3.0, 3.0)], "inside"),  # stopped in the aisle
    ],
)
def test_incomplete_routes_are_navigation_results_not_evidence_problems(points, end_zone):
    result = verdict(route(points))
    assert result["verdict"] == NOT_MET
    assert result["sources"]["localized"]["end_zone"] == end_zone


def test_jitter_at_a_gate_cannot_create_or_hide_a_crossing():
    points = [(0.0, 0.0), (3.0, 0.0), (3.0, 1.45)]
    for _ in range(10):
        points += [(3.0, 1.55), (3.0, 1.45)]
    samples = route(points + [(3.0, 7.0), (3.0, 0.0), (0.0, 0.0)])
    localized = verdict(samples)["sources"]["localized"]
    assert localized["zones"] == ["low", "inside", "high", "inside", "low"]
    assert localized["aborted_entries"] == []


def test_a_gap_makes_the_evidence_inconclusive():
    samples = route(THROUGH)
    del samples[300:310]
    result = verdict(samples)
    assert result["verdict"] == INCONCLUSIVE
    assert "Gap of" in result["reasons"][0]


def test_a_position_jump_makes_the_evidence_inconclusive():
    samples = route(THROUGH)
    t, x, y = samples[300]
    samples[300] = (t, x + 0.4, y)
    result = verdict(samples)
    assert result["verdict"] == INCONCLUSIVE
    assert "Position jump" in result["reasons"][0]


def test_a_position_inside_a_rack_makes_the_evidence_inconclusive():
    # Smooth (no jump) but straight through the west rack block.
    samples = route([(0.0, 0.0), (1.0, 0.0), (1.0, 7.0), (3.0, 7.0), (3.0, 0.0), (0.0, 0.0)])
    result = verdict(samples)
    assert result["verdict"] == INCONCLUSIVE
    assert "inside an obstacle" in result["reasons"][0]
    assert "jump" not in result["reasons"][0] and "Gap" not in result["reasons"][0]


def test_unordered_or_nonfinite_samples_are_rejected():
    samples = route(THROUGH)
    swapped = samples[:10] + [samples[11], samples[10]] + samples[12:]
    result = verdict(swapped, truth=None, require_ground_truth=False)
    assert result["verdict"] == INCONCLUSIVE and "time-ordered" in result["reasons"][0]
    samples[5] = (samples[5][0], math.nan, 0.0)
    result = verdict(samples, truth=None, require_ground_truth=False)
    assert result["verdict"] == INCONCLUSIVE and "nonfinite" in result["reasons"][0]


def test_ground_truth_is_required_by_default_and_never_preferred():
    samples = route(THROUGH)
    assert verdict(samples, truth=None)["verdict"] == INCONCLUSIVE
    assert verdict(samples, truth=None, require_ground_truth=False)["verdict"] == VERIFIED
    # Truth says the robot went round the outside: the sources disagree.
    bypass = route(PERIMETER)
    assert verdict(samples, truth=bypass, obstacles=[])["verdict"] == INCONCLUSIVE


def park(after_ns, seconds, x=0.0, y=0.0):
    return [(after_ns + i * PERIOD, x, y) for i in range(1, int(seconds * 20) + 1)]


def test_traversals_must_overlap_in_time_across_sources():
    # Same directions, but truth drives the route only after localized has finished it.
    drive = route(THROUGH)
    duration_s = (drive[-1][0] - drive[0][0]) / 1e9
    localized = drive + park(drive[-1][0], duration_s + 5)
    truth = [(drive[0][0], 0.0, 0.0)] + park(drive[0][0], duration_s + 5)
    truth += route(THROUGH, start_ns=truth[-1][0] + PERIOD)[1:]
    assert truth[-1][0] >= localized[-1][0] - 1e9
    sources = verdict(localized, truth=truth)
    assert sources["sources"]["localized"]["status"] == "COMPLETE"
    assert sources["sources"]["ground_truth"]["status"] == "COMPLETE"
    assert sources["verdict"] == INCONCLUSIVE
    assert sources["reasons"] == ["Localized and ground-truth trajectories disagree"]


def test_window_edges_may_be_missing_only_when_no_zone_change_was_possible():
    samples = route(THROUGH)
    start, end = window(samples)
    # One second missing at dispatch while parked 1.35 m from the gate band: acceptable.
    late = analyse(samples[20:], AISLE, window_ns=(start, end), obstacles=OBSTACLES)
    assert late["status"] == "COMPLETE"
    # The same gap ending next to the gate could hide a crossing.
    near = [s for s in samples if s[0] >= samples[0][0] + 17_000_000_000]
    assert near[0][2] > 1.2
    result = analyse(near, AISLE, window_ns=(start, end), obstacles=OBSTACLES)
    assert result["status"] == "INCOMPLETE"
    assert "mission-window edge" in result["problems"][0]


def test_a_gate_crossing_outside_the_opening_is_rejected():
    samples = route([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (3.0, 2.0), (3.0, 7.0)])
    result = analyse(samples, AISLE, window_ns=window(samples))
    assert result["status"] == "INCOMPLETE"
    assert "outside the corridor opening" in result["problems"][0]


def test_requirements_must_chain():
    samples = route(THROUGH)
    with pytest.raises(ValueError):
        assess(
            samples, AISLE, window_ns=window(samples), required=["high_to_low"], start_zone="low"
        )
    with pytest.raises(ValueError):
        assess(samples, AISLE, window_ns=window(samples), required=["sideways"], start_zone="low")
