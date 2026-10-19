"""Footprint clearance is exact rectangle-to-box geometry on given poses."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_runner.footprint_clearance import (  # noqa: E402
    corners,
    distance,
    minimum_clearance,
)

ROBOT = (-0.24, 0.16, -0.185, 0.185)  # warehouse_v2 plan footprint
RACKS = {"rack_1": (1.6, 2.4, 1.5, 5.5), "rack_2": (3.6, 4.4, 1.5, 5.5)}


def test_heading_up_the_aisle_centre_leaves_the_half_width_margin():
    pose = (0, 3.0, 3.5, math.pi / 2)
    assert min(distance(corners(pose, ROBOT), box) for box in RACKS.values()) == (
        pytest.approx(0.6 - 0.185)
    )


def test_rotation_uses_the_rotated_corners():
    pose = (0, 3.0, 3.5, 0.0)  # Facing east: front 0.16 m, rear 0.24 m.
    assert distance(corners(pose, ROBOT), RACKS["rack_1"]) == pytest.approx(0.6 - 0.24)
    assert distance(corners(pose, ROBOT), RACKS["rack_2"]) == pytest.approx(0.6 - 0.16)
    diagonal = (0, 3.0, 3.5, math.pi / 4)
    reach = max(abs(x - 3.0) for x, _ in corners(diagonal, ROBOT))
    assert distance(corners(diagonal, ROBOT), RACKS["rack_1"]) == pytest.approx(0.6 - reach)


def test_overlap_is_zero_including_edge_crossings_without_contained_corners():
    assert distance(corners((0, 2.3, 3.5, 0.0), ROBOT), RACKS["rack_1"]) == 0.0
    # A long thin footprint across a thin wall: edges cross, no corner inside.
    assert distance([(0, -1), (0.1, -1), (0.1, 1), (0, 1)], (-1, 1, -0.05, 0.05)) == 0.0


def test_minimum_over_poses_and_windows():
    poses = [(t, 3.0, 3.5, math.pi / 2) for t in range(0, 10)] + [(20, 2.8, 3.5, math.pi / 2)]
    whole = minimum_clearance(poses, ROBOT, RACKS)
    assert whole["clearance_m"] == pytest.approx(0.4 - 0.185)
    assert (whole["stamp_ns"], whole["box"], whole["poses"]) == (20, "rack_1", 11)
    windowed = minimum_clearance(poses, ROBOT, RACKS, windows=[(0, 9)])
    assert windowed["clearance_m"] == pytest.approx(0.415)
    assert windowed["poses"] == 10
