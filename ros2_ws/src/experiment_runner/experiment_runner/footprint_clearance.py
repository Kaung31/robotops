"""Minimum distance between the robot footprint and static boxes. Pure; no ROS imports.

Meaningful only with simulator ground truth, analytic world geometry and a footprint
that encloses the robot's collision primitives. With localized poses the number
would include localization error, so callers must not substitute them.
"""

from __future__ import annotations

import math

Pose = tuple[int, float, float, float]  # (stamp_ns, x, y, yaw) in the map frame
Rect = tuple[float, float, float, float]  # (x_min, x_max, y_min, y_max)


def corners(pose: Pose, footprint: Rect) -> list[tuple[float, float]]:
    """Footprint rectangle (base_link frame) placed at a pose, counter-clockwise."""
    _, px, py, yaw = pose
    c, s = math.cos(yaw), math.sin(yaw)
    x0, x1, y0, y1 = footprint
    return [
        (px + c * x - s * y, py + s * x + c * y)
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]


def _point_box(x: float, y: float, box: Rect) -> float:
    dx = max(box[0] - x, 0.0, x - box[1])
    dy = max(box[2] - y, 0.0, y - box[3])
    return math.hypot(dx, dy)


def _point_segment(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _inside_convex(p, polygon) -> bool:
    signs = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        signs.append((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]))
    return all(v >= 0 for v in signs) or all(v <= 0 for v in signs)


def _segments_cross(a, b, c, d) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return (orient(a, b, c) * orient(a, b, d) < 0) and (orient(c, d, a) * orient(c, d, b) < 0)


def distance(polygon: list[tuple[float, float]], box: Rect) -> float:
    """Distance between a convex polygon and an axis-aligned box; 0 when they overlap."""
    box_corners = [(box[0], box[2]), (box[1], box[2]), (box[1], box[3]), (box[0], box[3])]
    edges = list(zip(polygon, polygon[1:] + polygon[:1], strict=True))
    box_edges = list(zip(box_corners, box_corners[1:] + box_corners[:1], strict=True))
    if (
        any(_point_box(x, y, box) == 0.0 for x, y in polygon)
        or any(_inside_convex(p, polygon) for p in box_corners)
        or any(_segments_cross(*e, *f) for e in edges for f in box_edges)
    ):
        return 0.0
    # Disjoint convex shapes: the minimum is from a vertex of one to an edge of the other.
    return min(
        min(_point_box(x, y, box) for x, y in polygon),
        min(_point_segment(p, a, b) for p in box_corners for a, b in edges),
    )


def minimum_clearance(
    poses: list[Pose],
    footprint: Rect,
    boxes: dict[str, Rect],
    windows: list[tuple[int, int]] | None = None,
) -> dict:
    """Smallest footprint-to-box distance over poses, optionally only inside windows."""
    best = dict(clearance_m=None, stamp_ns=None, box=None, poses=0)
    for pose in poses:
        if windows is not None and not any(lo <= pose[0] <= hi for lo, hi in windows):
            continue
        best["poses"] += 1
        polygon = corners(pose, footprint)
        for name, box in boxes.items():
            d = distance(polygon, box)
            if best["clearance_m"] is None or d < best["clearance_m"]:
                best.update(clearance_m=d, stamp_ns=pose[0], box=name)
    return best
