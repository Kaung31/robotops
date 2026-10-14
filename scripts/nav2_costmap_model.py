#!/usr/bin/env python3
"""Offline model of RobotOps' Nav2 global costmap and planner path costs.

Purpose: explain and bound navigation behaviour in analytic warehouse worlds without
launching Nav2. Two parts with different standing:

* Footprint and costmap: reproduces Nav2 Jazzy's formulas (16-point footprint from
  robot_radius, footprint_padding, inscribed radius, InflationLayer cost curve) from
  the actual RobotOps configuration. These are deterministic geometric results; the
  live published footprint and costmap should still confirm them.
* Path cost: simplified Dijkstra searches with NavFn-like and Smac2D-like cell costs.
  These are MODELS of planner preference, not the planners. They support hypotheses
  only and never replace recorded trajectories.
"""

from __future__ import annotations

import heapq
import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NAV_CONFIG = ROOT / "ros2_ws/src/robot_navigation/config"
GEOMETRY = ROOT / "ros2_ws/src/robot_description/config/geometry.yaml"
LETHAL, INSCRIBED = 254, 253
NAVFN_NEUTRAL, NAVFN_FACTOR = 50.0, 0.8  # nav2_navfn_planner COST_NEUTRAL / COST_FACTOR


def composed_footprint_settings(profile: str = "navfn_rpp") -> dict:
    """robot_radius from the real composer plus the global costmap's inflation settings."""
    sys.path.insert(0, str(ROOT / "ros2_ws/src/robot_navigation"))
    from robot_navigation.navigation_config import navigation_parameters

    params = navigation_parameters(NAV_CONFIG, profile, GEOMETRY, use_sim_time=True)
    g = params["global_costmap"]["global_costmap"]["ros__parameters"]
    local = params["local_costmap"]["local_costmap"]["ros__parameters"]
    settings = dict(
        robot_radius=g["robot_radius"],
        footprint_padding=g["footprint_padding"],
        resolution=g["resolution"],
        inflation_radius=g["inflation_layer"]["inflation_radius"],
        cost_scaling_factor=g["inflation_layer"]["cost_scaling_factor"],
    )
    for key in ("robot_radius", "footprint_padding", "resolution"):
        if local[key] != settings[key]:
            raise ValueError(f"Local and global costmaps differ in {key}")
    if local["inflation_layer"] != g["inflation_layer"]:
        raise ValueError("Local and global inflation differ")
    return settings


def physical_extent(geometry_path: Path = GEOMETRY) -> dict:
    """Planar bounds of the URDF collision primitives in base_link (see base.xacro)."""
    g = yaml.safe_load(geometry_path.read_text())
    chassis_x = (
        -g["chassis_length"] / 10 - g["chassis_length"] / 2,
        -g["chassis_length"] / 10 + g["chassis_length"] / 2,
    )
    wheel_y = g["wheel_separation"] / 2 + g["wheel_width"] / 2
    caster_x = -g["chassis_length"] / 2 + g["caster_radius"]
    x_min = min(chassis_x[0], -g["wheel_radius"], caster_x - g["caster_radius"])
    x_max = max(
        chassis_x[1],
        g["wheel_radius"],
        g["lidar_radius"],
        g["chassis_length"] / 4 + g["imu_size"] / 2,
    )
    y_max = max(g["chassis_width"] / 2, wheel_y)
    corners = [(x, y) for x in (x_min, x_max) for y in (-y_max, y_max)]
    # Box corners over-approximate the round wheels; chassis corners dominate anyway.
    return dict(
        x_min=x_min,
        x_max=x_max,
        y_half=y_max,
        width=2 * y_max,
        length=x_max - x_min,
        circumscribed_radius=max(math.hypot(x, y) for x, y in corners),
    )


def footprint_from_radius(radius: float, padding: float) -> list[tuple[float, float]]:
    """nav2_costmap_2d makeFootprintFromRadius (16 points) followed by padFootprint."""

    def sign0(v: float) -> int:
        return (v > 0) - (v < 0)

    points = []
    for i in range(16):
        angle = i * 2 * math.pi / 16
        x, y = math.cos(angle) * radius, math.sin(angle) * radius
        points.append((x + sign0(x) * padding, y + sign0(y) * padding))
    return points


def footprint_radii(points: list[tuple[float, float]]) -> tuple[float, float]:
    """nav2_costmap_2d calculateMinAndMaxDistances: (inscribed, circumscribed)."""

    def to_segment(x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, -(x0 * dx + y0 * dy) / (dx * dx + dy * dy)))
        return math.hypot(x0 + t * dx, y0 + t * dy)

    low, high = math.inf, 0.0
    for i, (x0, y0) in enumerate(points):
        x1, y1 = points[(i + 1) % len(points)]
        vertex, edge = math.hypot(x0, y0), to_segment(x0, y0, x1, y1)
        low, high = min(low, vertex, edge), max(high, vertex, edge)
    return low, high


class Costmap:
    """Static-layer + InflationLayer costs on an occupancy grid (row 0 = south)."""

    def __init__(self, grid, width, height, resolution, origin, inscribed, settings):
        self.w, self.h, self.res = width, height, resolution
        self.ox, self.oy = origin
        self.inscribed = inscribed
        radius_cells = math.ceil(settings["inflation_radius"] / resolution - 1e-9)
        offsets = [
            (dx, dy, math.hypot(dx, dy))
            for dx in range(-radius_cells, radius_cells + 1)
            for dy in range(-radius_cells, radius_cells + 1)
            if math.hypot(dx, dy) <= radius_cells
        ]
        self.distance = [math.inf] * (width * height)
        for k, occupied in enumerate(grid):
            if not occupied:
                continue
            x, y = k % width, k // width
            # Interior obstacle cells cannot be nearer to free space than boundary ones.
            if all(
                grid[(y + dy) * width + x + dx]
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= x + dx < width and 0 <= y + dy < height
            ):
                self.distance[k] = 0.0
                continue
            for dx, dy, d in offsets:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and d < self.distance[ny * width + nx]:
                    self.distance[ny * width + nx] = d
        csf = settings["cost_scaling_factor"]
        self.cost = bytearray(width * height)
        for k, d in enumerate(self.distance):
            if d == 0:
                self.cost[k] = LETHAL
            elif d == math.inf:
                self.cost[k] = 0
            elif d * resolution <= inscribed:
                self.cost[k] = INSCRIBED
            else:  # InflationLayer::computeCost, truncated to unsigned char.
                self.cost[k] = int((INSCRIBED - 1) * math.exp(-csf * (d * resolution - inscribed)))

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return math.floor((x - self.ox) / self.res), math.floor((y - self.oy) / self.res)

    def centre(self, ix: int, iy: int) -> tuple[float, float]:
        return self.ox + (ix + 0.5) * self.res, self.oy + (iy + 0.5) * self.res

    def at(self, x: float, y: float) -> int:
        ix, iy = self.cell(x, y)
        return self.cost[iy * self.w + ix]

    def plan(self, start, goal, model: str):
        """Cheapest non-lethal cell path under a planner cost model.

        navfn: 16-connected, cost (50 + 0.8 c) / 50 per metre, approximating NavFn's
        interpolated wavefront. smac: 8-connected, (1 + 2.0 c / 252) per metre as in
        Smac 2D with cost_travel_multiplier 2.0. Returns (cost, length_m, points).
        """
        if model == "navfn":
            moves = [
                (dx, dy)
                for dx in range(-2, 3)
                for dy in range(-2, 3)
                if (dx, dy) != (0, 0) and math.gcd(abs(dx), abs(dy)) == 1
            ]

            def weight(c):
                return (NAVFN_NEUTRAL + NAVFN_FACTOR * c) / NAVFN_NEUTRAL
        elif model == "smac":
            moves = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]

            def weight(c):
                return 1.0 + 2.0 * c / (INSCRIBED - 1)
        else:
            raise ValueError("model must be navfn or smac")
        w, cost = self.w, self.cost
        start_cell, goal_cell = self.cell(*start), self.cell(*goal)
        for x, y in (start_cell, goal_cell):
            if cost[y * w + x] >= INSCRIBED:
                raise ValueError("Start or goal is in collision")
        best = {start_cell: 0.0}
        previous = {}
        queue = [(0.0, start_cell)]
        while queue:
            d, (x, y) = heapq.heappop(queue)
            if (x, y) == goal_cell:
                break
            if d > best[(x, y)]:
                continue
            for dx, dy in moves:
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < self.h) or cost[ny * w + nx] >= INSCRIBED:
                    continue
                # A knight move must not cut a lethal corner.
                if abs(dx) == 2 or abs(dy) == 2:
                    mx, my = (
                        x + int(math.copysign(1, dx)) * (dx != 0),
                        y + int(math.copysign(1, dy)) * (dy != 0),
                    )
                    if cost[my * w + mx] >= INSCRIBED:
                        continue
                nd = d + math.hypot(dx, dy) * self.res * weight(cost[ny * w + nx])
                if nd < best.get((nx, ny), math.inf):
                    best[(nx, ny)] = nd
                    previous[(nx, ny)] = (x, y)
                    heapq.heappush(queue, (nd, (nx, ny)))
        if goal_cell not in best:
            raise ValueError("No non-lethal path")
        cells = [goal_cell]
        while cells[-1] != start_cell:
            cells.append(previous[cells[-1]])
        points = [self.centre(*c) for c in reversed(cells)]
        length = sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
        return best[goal_cell], length, points


def build(grid, map_spec: dict, settings: dict | None = None) -> tuple[Costmap, dict]:
    settings = settings or composed_footprint_settings()
    if abs(settings["resolution"] - map_spec["resolution_m"]) > 1e-12:
        raise ValueError("Costmap and map resolutions differ")
    points = footprint_from_radius(settings["robot_radius"], settings["footprint_padding"])
    inscribed, circumscribed = footprint_radii(points)
    costmap = Costmap(
        grid,
        map_spec["width"],
        map_spec["height"],
        map_spec["resolution_m"],
        map_spec["origin_m"],
        inscribed,
        settings,
    )
    return costmap, dict(settings, inscribed_radius=inscribed, circumscribed_radius=circumscribed)


def cross_section(costmap: Costmap, y: float, x_lo: float, x_hi: float) -> list[tuple]:
    """(cell-centre x, cost) across an aisle at height y."""
    iy = costmap.cell(0.0, y)[1]
    ix_lo, ix_hi = costmap.cell(x_lo, y)[0], costmap.cell(x_hi, y)[0]
    return [
        (costmap.centre(ix, iy)[0], costmap.cost[iy * costmap.w + ix])
        for ix in range(ix_lo, ix_hi + 1)
    ]
