"""Pure validation for differential-drive mission requests."""

import math


def validate_mission(label: str, waypoints: list[dict], global_frame: str = "map") -> None:
    if not isinstance(label, str) or not label.strip() or len(label) > 80:
        raise ValueError("Mission label must contain 1–80 characters")
    if not 1 <= len(waypoints) <= 100:
        raise ValueError("Mission needs 1–100 waypoints")
    for pose in waypoints:
        if pose["frame"] != global_frame:
            raise ValueError(f"Every waypoint must be in {global_frame}")
        values = [pose[k] for k in ("x", "y", "z", "qx", "qy", "qz", "qw")]
        if not all(isinstance(v, float | int) and math.isfinite(v) for v in values):
            raise ValueError("Pose components must be finite numbers")
        if any(abs(pose[k]) > 1e-6 for k in ("z", "qx", "qy")):
            raise ValueError("Only planar differential-drive goals are supported")
        if not math.isclose(pose["qz"] ** 2 + pose["qw"] ** 2, 1.0, abs_tol=1e-3):
            raise ValueError("Goal orientation must be a unit quaternion")


def positive_seconds(value: float, name: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value
