"""Compare localized poses with simulator ground truth at aligned timestamps.

Each estimate is compared with ground truth interpolated at the estimate's own
stamp. Comparing the latest sample of each stream instead misreads motion between
the two stamps as error: an 86 ms offset at 0.25 m/s looks like ~21 mm. Truth is
interpolated only between bracketing samples at most max_gap_ns apart and is never
extrapolated; anything else is UNAVAILABLE. Pure logic: no ROS imports.
"""

from __future__ import annotations

import math
from bisect import bisect_left

Pose = tuple[int, float, float, float]  # (stamp_ns, x, y, yaw)


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def _to_map(pose: tuple[float, float, float], world_to_map: tuple[float, float, float]):
    """Express a world-frame truth pose in the map frame: map = world_to_map ∘ world."""
    dx, dy, dyaw = world_to_map
    x, y, yaw = pose
    c, s = math.cos(dyaw), math.sin(dyaw)
    return dx + c * x - s * y, dy + s * x + c * y, _wrap(dyaw + yaw)


def truth_at(truth: list[Pose], stamp: int, max_gap_ns: int):
    """Truth (x, y, yaw) at stamp, or None without a close enough bracketing pair."""
    times = [sample[0] for sample in truth]
    index = bisect_left(times, stamp)
    if index < len(truth) and times[index] == stamp:
        return truth[index][1:]
    if index == 0 or index == len(truth):
        return None
    before, after = truth[index - 1], truth[index]
    if after[0] - before[0] > max_gap_ns:
        return None
    f = (stamp - before[0]) / (after[0] - before[0])
    return (
        before[1] + f * (after[1] - before[1]),
        before[2] + f * (after[2] - before[2]),
        _wrap(before[3] + f * _wrap(after[3] - before[3])),
    )


def aligned_errors(
    estimates: list[Pose],
    truth: list[Pose],
    *,
    world_to_map: tuple[float, float, float],
    max_gap_ns: int = 100_000_000,
) -> list[dict]:
    """Per-estimate XY/yaw error against truth at the same stamp.

    world_to_map must be stated by the caller (identity only when the map frame is
    known to coincide with the simulator world frame); it is never assumed.
    """
    if max_gap_ns <= 0:
        raise ValueError("max_gap_ns must be positive")
    ordered = sorted(truth)
    rows = []
    for stamp, x, y, yaw in estimates:
        reference = truth_at(ordered, stamp, max_gap_ns)
        if reference is None:
            rows.append(dict(stamp_ns=stamp, status="UNAVAILABLE"))
            continue
        rx, ry, ryaw = _to_map(reference, world_to_map)
        rows.append(
            dict(
                stamp_ns=stamp,
                status="ALIGNED",
                xy_error_m=math.hypot(x - rx, y - ry),
                yaw_error_rad=abs(_wrap(yaw - ryaw)),
            )
        )
    return rows


def summarize(rows: list[dict]) -> dict:
    aligned = [row for row in rows if row["status"] == "ALIGNED"]
    return dict(
        estimates=len(rows),
        aligned=len(aligned),
        unavailable=len(rows) - len(aligned),
        max_xy_error_m=max((r["xy_error_m"] for r in aligned), default=None),
        max_yaw_error_rad=max((r["yaw_error_rad"] for r in aligned), default=None),
        final=rows[-1] if rows else None,
    )
