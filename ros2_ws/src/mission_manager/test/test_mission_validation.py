"""Request contracts reject unsafe or unsupported poses without ROS."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mission_manager.model import positive_seconds, validate_mission  # noqa: E402

POSE = dict(frame="map", x=1.0, y=0.0, z=0.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0)


def test_valid_ordered_mission():
    validate_mission("demo", [POSE, dict(POSE, x=-1.0)])


@pytest.mark.parametrize(
    "change",
    [
        {"frame": "odom"},
        {"x": float("nan")},
        {"qw": 0.0},
        {"z": 1.0},
        {"qx": 0.1},
        {"y": float("inf")},
    ],
)
def test_invalid_pose(change):
    with pytest.raises(ValueError):
        validate_mission("demo", [dict(POSE, **change)])


@pytest.mark.parametrize(
    "label,poses", [("", [POSE]), ("x" * 81, [POSE]), ("demo", []), ("demo", [POSE] * 101)]
)
def test_invalid_mission(label, poses):
    with pytest.raises(ValueError):
        validate_mission(label, poses)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), float("inf")])
def test_timeout_validation(value):
    with pytest.raises(ValueError):
        positive_seconds(value, "timeout")
