#!/usr/bin/env python3
"""Offline, read-only assessment of one warehouse_v2 trial recording.

Usage (sourced ROS 2 Jazzy environment, nothing running):
  assess_warehouse_v2_trial.py <run_dir> <output.json>

<run_dir> is a mission run directory containing result.json and telemetry/ (MCAP).
The localized trajectory is the map->base_link transform looked up with tf2 at each
odometry stamp, only where both map->odom and odom->base_link have real samples
bracketing that stamp within 0.25 s (the Recorded Lab exporter's rule). Simulator
ground truth is read from simulation/ground_truth. The pinned requirement and
measurements come from benchmarks/warehouse_v2/plan.json.

Opens the recording read-only, starts no ROS graph or process, and writes exactly
one new file (never overwrites). `measure` is pure and unit-tested without ROS.
"""

from __future__ import annotations

import bisect
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ros2_ws/src/experiment_runner"))
from experiment_runner.aisle_traversal import assess  # noqa: E402
from experiment_runner.footprint_clearance import minimum_clearance  # noqa: E402
from experiment_runner.ground_truth import aligned_errors, summarize  # noqa: E402

PLAN = ROOT / "benchmarks/warehouse_v2/plan.json"
TF_BRACKET_GAP_NS = 250_000_000


def _path_length(samples) -> float:
    return sum(math.dist(a[1:3], b[1:3]) for a, b in zip(samples, samples[1:], strict=False))


def _boxes(descriptor: dict) -> dict:
    return {
        b["name"]: (
            b["centre_m"][0] - b["size_m"][0] / 2,
            b["centre_m"][0] + b["size_m"][0] / 2,
            b["centre_m"][1] - b["size_m"][1] / 2,
            b["centre_m"][1] + b["size_m"][1] / 2,
        )
        for b in descriptor["boxes"]
    }


def _within(samples, windows):
    return [s for s in samples if any(lo <= s[0] <= hi for lo, hi in windows)]


def measure(
    plan: dict,
    descriptor: dict,
    *,
    window_ns: tuple[int, int],
    localized: list[tuple[int, float, float, float]],
    truth: list[tuple[int, float, float, float]] | None,
    odom: list[tuple[int, float, float, float]],
) -> dict:
    """Aisle verdict plus the measurements that the available evidence supports.

    Clearance and localization error need ground truth; without it they are reported
    as not measurable rather than estimated from localized poses.
    """
    requirement = plan["aisle_requirement"]
    boxes = _boxes(descriptor)
    world_to_map = tuple(plan["scenario"]["world_to_map"])
    if truth is not None and world_to_map != (0.0, 0.0, 0.0):
        raise ValueError("Only an identity world_to_map is declared for warehouse_v2")
    traversal = assess(
        [s[:3] for s in localized],
        requirement["corridor"],
        window_ns=window_ns,
        required=requirement["required"],
        start_zone=requirement["start_zone"],
        obstacles=list(boxes.values()),
        ground_truth=None if truth is None else [s[:3] for s in truth],
        require_ground_truth=requirement["require_ground_truth"],
        policy=requirement["policy"],
    )
    in_window = [s for s in odom if window_ns[0] <= s[0] <= window_ns[1]]
    result = dict(
        schema_version=1,
        aisle_traversal=traversal,
        odometry_path_length_m=_path_length(in_window) if in_window else None,
        ground_truth_path_length_m=None,
        footprint_clearance=None,
        aisle_footprint_clearance=None,
        localization_error=None,
        aisle_localization_error=None,
        not_measurable=[],
    )
    if truth is None or traversal["sources"].get("ground_truth", {}).get("status") != "COMPLETE":
        result["not_measurable"] = [
            "ground_truth_path_length_m",
            "footprint_clearance",
            "localization_error",
        ]
        return result
    f = plan["clearance_footprint_m"]
    footprint = (f["x_min"], f["x_max"], f["y_min"], f["y_max"])
    mission_truth = [s for s in truth if window_ns[0] <= s[0] <= window_ns[1]]
    windows = [
        (t["entry_ns"], t["exit_ns"]) for t in traversal["sources"]["ground_truth"]["traversals"]
    ]
    rows = aligned_errors(
        [s for s in localized if window_ns[0] <= s[0] <= window_ns[1]],
        truth,
        world_to_map=world_to_map,
    )
    result.update(
        ground_truth_path_length_m=_path_length(mission_truth),
        footprint_clearance=minimum_clearance(mission_truth, footprint, boxes),
        aisle_footprint_clearance=(
            minimum_clearance(mission_truth, footprint, boxes, windows) if windows else None
        ),
        localization_error=summarize(rows),
        aisle_localization_error=(
            summarize([r for r in rows if any(lo <= r["stamp_ns"] <= hi for lo, hi in windows)])
            if windows
            else None
        ),
    )
    return result


def _yaw(q) -> float:
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def _ns(stamp) -> int:
    return stamp.sec * 1_000_000_000 + stamp.nanosec


def _bracketed(times: list[int], t: int) -> bool:
    i = bisect.bisect_left(times, t)
    if i < len(times) and times[i] == t:
        return True
    return 0 < i < len(times) and times[i] - times[i - 1] <= TF_BRACKET_GAP_NS


def read_recording(telemetry: Path, world_id: str):
    """(localized, truth, odom) from a finalized MCAP. Read-only; ROS required."""
    import rosbag2_py
    import tf2_py
    from rclpy.duration import Duration
    from rclpy.serialization import deserialize_message
    from rclpy.time import Time
    from rosidl_runtime_py.utilities import get_message

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(telemetry), storage_id="mcap"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    wanted = ("/tf", "/tf_static", "/odom", "/simulation/ground_truth")
    types = {
        t.name: get_message(t.type) for t in reader.get_all_topics_and_types() if t.name in wanted
    }
    buffer = tf2_py.BufferCore(Duration(seconds=3600))
    edges: dict[tuple[str, str], list[int]] = {("map", "odom"): [], ("odom", "base_link"): []}
    odom, truth = [], []
    while reader.has_next():
        topic, raw, _ = reader.read_next()
        if topic in ("/tf", "/tf_static"):
            for t in deserialize_message(raw, types[topic]).transforms:
                if topic == "/tf_static":
                    buffer.set_transform_static(t, "warehouse_v2_assessment")
                    continue
                buffer.set_transform(t, "warehouse_v2_assessment")
                key = (t.header.frame_id, t.child_frame_id)
                if key in edges:
                    edges[key].append(_ns(t.header.stamp))
        elif topic == "/odom":
            m = deserialize_message(raw, types[topic])
            if (m.header.frame_id, m.child_frame_id) != ("odom", "base_link"):
                raise ValueError("Unexpected odometry frames")
            p = m.pose.pose
            odom.append((_ns(m.header.stamp), p.position.x, p.position.y, _yaw(p.orientation)))
        elif topic == "/simulation/ground_truth":
            matches = [
                t
                for t in deserialize_message(raw, types[topic]).transforms
                if t.child_frame_id == "robotops"
            ]
            if len(matches) != 1 or matches[0].header.frame_id != world_id:
                raise ValueError("Ground truth does not identify the robot in this world")
            r = matches[0].transform
            truth.append(
                (_ns(matches[0].header.stamp), r.translation.x, r.translation.y, _yaw(r.rotation))
            )
    del reader
    for times in edges.values():
        times.sort()
    localized = []
    for stamp, *_ in odom:
        if not all(_bracketed(times, stamp) for times in edges.values()):
            continue
        try:
            t = buffer.lookup_transform_core("map", "base_link", Time(nanoseconds=stamp))
        except Exception:  # tf2 lookup/extrapolation errors leave a gap, judged later.
            continue
        tr = t.transform
        localized.append((stamp, tr.translation.x, tr.translation.y, _yaw(tr.rotation)))
    # Duplicate stamps would make "strictly ordered" fail; keep the last value per stamp.
    truth = sorted({s[0]: s for s in truth}.values()) if truth else None
    return sorted({s[0]: s for s in localized}.values()), truth, sorted(odom)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    run, output = Path(sys.argv[1]), Path(sys.argv[2])
    if output.exists():
        raise SystemExit(f"Refusing to overwrite {output}")
    plan = json.loads(PLAN.read_bytes())
    descriptor = json.loads((ROOT / plan["scenario"]["descriptor"]["path"]).read_bytes())
    saved = json.loads((run / "result.json").read_bytes())
    # Navigation window: dispatch to the mission's own end, not result finalization.
    window = (int(saved["started_ros_ns"]), int(saved["mission_ended_ros_ns"]))
    localized, truth, odom = read_recording(run / "telemetry", plan["scenario"]["world_id"])
    result = measure(
        plan, descriptor, window_ns=window, localized=localized, truth=truth, odom=odom
    )
    result["source"] = dict(run_dir=str(run), mission_run_id=saved.get("run_id"))
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(result["aisle_traversal"]["verdict"])


if __name__ == "__main__":
    main()
