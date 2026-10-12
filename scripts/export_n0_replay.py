#!/usr/bin/env python3
"""Private, pinned N0 offline exporter. No ROS initialization or robot commands."""

from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
import re
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

from replay_models import Config, Manifest, PoseChunk, ScanChunk, Transform, offset_us

ROOT = Path(__file__).resolve().parents[1]
REPORT = "artifacts/valid-path-campaigns-20261010/pair-0-off-report.json"
REPORT_SHA = "ce9861b1e1e2ef61a796741dab5f3e07595d85eb92d2a607e6356b21202f4797"
RUN_ID = "0e618a992f084033b1b7d817ae226b55"
PINS = {
    "mcap": (
        f"artifacts/runs/{RUN_ID}/telemetry/telemetry_0.mcap",
        "705400651ac4c2988977fe1a892fa2023477fabbd3619ca4eb1ec961145f0c59",
    ),
    "map_yaml": (
        "artifacts/maps/control_pad_v1.yaml",
        "b39f2ed0bbc8f900711fa8715f3f31c2dbfbed4ed1d10190113e2b9cb15773fa",
    ),
    "map_image": (
        "artifacts/maps/control_pad_v1.pgm",
        "6ad0062c20e30cd812a7b389258b6d95b532af2625194347638e1ae0341b43fe",
    ),
}


def canonical(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_range(value, minimum, maximum):
    reason = (
        "invalid_nan"
        if math.isnan(value)
        else "no_return"
        if value == math.inf
        else "out_of_bounds"
        if not math.isfinite(value) or not minimum <= value <= maximum
        else "valid"
    )
    return (value if reason == "valid" else None), reason


def source_bytes(root: Path, path: Path) -> bytes:
    """Reject symlink components and unexpected bulk inputs; never open for writing."""
    relative = path.absolute().relative_to(root.absolute())
    current = root.absolute()
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Symlink source forbidden")
    if not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Source missing or oversized")
    return path.read_bytes()


def verify_sources(root: Path):
    """Reuse canonical artifact verification without importing live backend services."""
    sys.path.insert(0, str(root / "backend"))
    from robotops_backend.campaigns.report_models import CampaignReport
    from robotops_backend.campaigns.reports import ArtifactReader, digest, trial_integrity

    report_bytes = source_bytes(root, root / REPORT)
    if sha(report_bytes) != REPORT_SHA:
        raise ValueError("N0 report pin mismatch")
    report = CampaignReport.model_validate_json(report_bytes)
    if digest(report.model_dump(mode="json", exclude={"id", "created_at"})) != report.id:
        raise ValueError("Report identity mismatch")
    if digest(report.campaign.model_dump(mode="json")) != report.source_sha256:
        raise ValueError("Campaign identity mismatch")
    if len(report.campaign.trials) != 1:
        raise ValueError("N0-only exporter requires one trial")
    trial = report.campaign.trials[0]
    integrity = trial_integrity(report.campaign, trial, ArtifactReader(root / "artifacts"))
    if integrity.state != "VERIFIED" or trial.evidence.mission_run_id != RUN_ID:
        raise ValueError("N0 source evidence no longer VERIFIED")
    locations = {"report": (root / REPORT, REPORT_SHA, "original_bound")}
    for key, (name, expected) in PINS.items():
        if sha(source_bytes(root, root / name)) != expected:
            raise ValueError("N0 source pin mismatch: " + key)
        locations[key] = (root / name, expected, "original_bound")
    for check in integrity.artifacts:
        path = Path(check.reference)
        kind = {
            "manifest.json": "runner_manifest",
            "metadata.json": "run_metadata",
            "result.json": "run_result",
            "metadata.yaml": "bag_metadata",
        }.get(path.name, "contacts" if path.name.startswith("contacts-") else "mcap")
        if sha(source_bytes(root, path)) != check.actual_sha256:
            raise ValueError("Artifact changed since verification")
        locations[kind] = (
            path,
            check.actual_sha256,
            "audit_snapshot_only" if kind == "runner_manifest" else "original_bound",
        )
    return report.model_dump(mode="json"), locations


def ros_ns(stamp) -> int:
    if not 0 <= stamp.nanosec < 10**9 or stamp.sec < 0:
        raise ValueError("Invalid ROS timestamp")
    return stamp.sec * 10**9 + stamp.nanosec


def transform_value(transform):
    t, q = transform.translation, transform.rotation
    return Transform(position=[t.x, t.y, t.z], quaternion=[q.x, q.y, q.z, q.w]).model_dump()


def pgm(data: bytes):
    # P5 header tokens support comments; binary payload begins after maxval separator.
    tokens, index = [], 0
    while len(tokens) < 4:
        while index < len(data) and data[index] in b" \r\n\t":
            index += 1
        if data[index : index + 1] == b"#":
            index = data.index(b"\n", index) + 1
            continue
        end = index
        while end < len(data) and data[end] not in b" \r\n\t":
            end += 1
        tokens.append(data[index:end])
        index = end
    if tokens[0] != b"P5" or tokens[3] != b"255":
        raise ValueError("Only bounded P5 gray8 source supported")
    width, height = int(tokens[1]), int(tokens[2])
    if width <= 0 or height <= 0 or width * height > 1_000_000:
        raise ValueError("Invalid map dimensions")
    if data[index : index + 2] == b"\r\n":
        index += 2
    else:
        index += 1
    pixels = data[index:]
    if len(pixels) != width * height:
        raise ValueError("Map payload length mismatch")
    sanitized = f"P5\n{width} {height}\n255\n".encode() + pixels
    return width, height, pixels, sanitized


def bracket(series, t: int, max_gap: int):
    """Inclusive exact samples; interpolate only across bounded actual source brackets."""
    times = [row[0] for row in series]
    if any(a >= b for a, b in zip(times, times[1:], strict=False)):
        raise ValueError("Conflicting/reordered TF timestamps")
    i = bisect.bisect_left(times, t)
    if i < len(times) and times[i] == t:
        return [series[i][1]]
    if i == 0 or i == len(times) or times[i] - times[i - 1] > max_gap:
        raise ValueError("TF_UNAVAILABLE")
    return [series[i - 1][1], series[i][1]]


def validate_clock(clocks):
    if not clocks or any(type(t) is not int or t <= 0 for t in clocks):
        raise ValueError("Missing/invalid clock")
    if any(a >= b or b - a > 100_000_000 for a, b in zip(clocks, clocks[1:], strict=False)):
        raise ValueError("N0 exporter refuses paused/reset/missing clock coverage")


def decompress_bounded(content):
    decoder = zlib.decompressobj(wbits=31)
    raw = decoder.decompress(content, 8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024 or not decoder.eof or decoder.unused_data:
        raise ValueError("Expanded asset too large, incomplete or concatenated")
    return raw


def read_bag(root: Path, locations):
    import rosbag2_py
    import tf2_py
    import yaml
    from rclpy.duration import Duration
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(locations["mcap"][0].parent), storage_id="mcap"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    types = {topic.name: get_message(topic.type) for topic in reader.get_all_topics_and_types()}
    counts, edges = Counter(), defaultdict(list)
    tf = tf2_py.BufferCore(Duration(seconds=300))
    clocks, poses, scans, grids, raw_tfs = [], [], [], [], []
    static = {}
    while reader.has_next():
        topic, raw, _log_ns = reader.read_next()
        counts[topic] += 1
        if sum(counts.values()) > 100_000:
            raise ValueError("Input message budget exceeded")
        if topic not in {"/clock", "/odom", "/scan", "/tf", "/tf_static", "/map"}:
            continue
        message = deserialize_message(raw, types[topic])
        if topic == "/clock":
            clocks.append(ros_ns(message.clock))
            continue
        if topic == "/map":
            grids.append(message)
            continue
        if topic in ("/tf", "/tf_static"):
            for index, transform in enumerate(message.transforms):
                transform_value(transform.transform)
                key = (transform.header.frame_id, transform.child_frame_id)
                ref = {
                    "topic": topic,
                    "ordinal": counts[topic],
                    "ros_ns": str(ros_ns(transform.header.stamp)),
                    "cdr_sha256": sha(raw),
                    "transform_index": index,
                }
                if topic == "/tf_static":
                    if key in static:
                        raise ValueError("Duplicate static TF not supported")
                    static[key] = ref
                    tf.set_transform_static(transform, "private_n0_export")
                else:
                    edges[key].append((ros_ns(transform.header.stamp), ref))
                    tf.set_transform(transform, "private_n0_export")
                raw_tfs.append((topic, transform))
        else:
            t = ros_ns(message.header.stamp)
            anchor = {
                "topic": topic,
                "ordinal": counts[topic],
                "ros_ns": str(t),
                "cdr_sha256": sha(raw),
            }
            (poses if topic == "/odom" else scans).append((t, message, anchor))
    del reader
    meta = yaml.safe_load(source_bytes(root, locations["bag_metadata"][0]))[
        "rosbag2_bagfile_information"
    ]
    expected = {
        r["topic_metadata"]["name"]: r["message_count"]
        for r in meta["topics_with_message_count"]
        if r["message_count"]
    }
    if counts != expected or sum(counts.values()) != meta["message_count"]:
        raise ValueError("Bag source counts mismatch")
    validate_clock(clocks)
    for series in (poses, scans):
        if not series or any(a[0] >= b[0] for a, b in zip(series, series[1:], strict=False)):
            raise ValueError(
                "Duplicate/reordered acquisition requires explicit future epoch handling"
            )
        if any(not clocks[0] <= t <= clocks[-1] for t, _, _ in series):
            raise ValueError("Acquisition outside recorded clock association")
    for key in (("map", "odom"), ("odom", "base_link")):
        times = [x[0] for x in edges[key]]
        if not times or any(a >= b for a, b in zip(times, times[1:], strict=False)):
            raise ValueError("Dynamic TF order/identity conflict")
    if ("base_link", "lidar_link") not in static:
        raise ValueError("Missing static LiDAR transform")
    return {
        "tf": tf,
        "edges": edges,
        "static": static,
        "clocks": clocks,
        "poses": poses,
        "scans": scans,
        "grids": grids,
        "counts": dict(counts),
        "raw_tfs": raw_tfs,
    }


def map_transform(data, t, config):
    from rclpy.time import Time

    refs = []
    for key in (("map", "odom"), ("odom", "base_link")):
        refs.extend(bracket(data["edges"][key], t, config.tf_bracket_gap_ns))
    transform = data["tf"].lookup_transform_core("map", "base_link", Time(nanoseconds=t))
    return transform_value(transform.transform), refs


def segments(times, origin, max_gap):
    if any(type(t) is not int or t < origin for t in times) or any(
        a >= b for a, b in zip(times, times[1:], strict=False)
    ):
        raise ValueError("Reset/duplicate/reordered trajectory cannot share an epoch")
    result = []
    for t in times:
        if not result or t - int(result[-1]["end_ros_ns"]) > max_gap:
            result.append(
                {
                    "id": f"segment{len(result)}",
                    "start_ros_ns": str(t),
                    "end_ros_ns": str(t),
                    "start_us": offset_us(t, origin),
                    "end_us": offset_us(t, origin),
                }
            )
        else:
            result[-1]["end_ros_ns"] = str(t)
            result[-1]["end_us"] = offset_us(t, origin)
    return result


def select_segment(t, intervals):
    return next(
        (s["id"] for s in intervals if int(s["start_ros_ns"]) <= t <= int(s["end_ros_ns"])), None
    )


def display_samples(data, config):
    from rclpy.time import Time

    origin = data["clocks"][0]
    available, evaluated = [], []
    for t, message, anchor in data["poses"]:
        if message.header.frame_id != "odom" or message.child_frame_id != "base_link":
            raise ValueError("Unexpected odometry frame")
        try:
            value, refs = map_transform(data, t, config)
        except ValueError:
            value, refs = None, []
        if value is not None:
            available.append(t)
        evaluated.append((t, value, refs, anchor))
    intervals = segments(available, origin, config.pose_gap_ns)
    poses, last = [], None
    for t, value, refs, anchor in evaluated:
        if last is not None and t - last < config.pose_period_ns:
            continue
        last = t
        poses.append(
            {
                "segment_id": select_segment(t, intervals) if value is not None else None,
                "ros_ns": str(t),
                "offset_us": offset_us(t, origin),
                "transform": value,
                "quality": "SUPPORTED_TF" if value else "TF_UNAVAILABLE",
                "anchor": anchor,
                "tf_refs": refs,
            }
        )
    scans, unavailable = [], []
    for i, (t, message, anchor) in enumerate(data["scans"]):
        if message.header.frame_id != "lidar_link" or len(message.ranges) != 360:
            raise ValueError("Unexpected scan frame/geometry")
        base_lidar = transform_value(
            data["tf"]
            .lookup_transform_core("base_link", "lidar_link", Time(nanoseconds=t))
            .transform
        )
        try:
            value, refs = map_transform(data, t, config)
        except ValueError:
            value, refs = None, []
            unavailable.append(str(t))
        if i % config.scan_stride:
            continue
        indices = list(range(0, 360, config.ray_stride))
        ranges, reasons = [], []
        for index in indices:
            v = message.ranges[index]
            range_value, reason = sanitize_range(v, message.range_min, message.range_max)
            ranges.append(range_value)
            reasons.append(reason)
        scans.append(
            {
                "segment_id": select_segment(t, intervals) if value is not None else None,
                "ros_ns": str(t),
                "offset_us": offset_us(t, origin),
                "angle_min_rad": message.angle_min,
                "angle_increment_rad": message.angle_increment,
                "range_min_m": message.range_min,
                "range_max_m": message.range_max,
                "selected_indices": indices,
                "ranges_m": ranges,
                "validity": reasons,
                "map_base": value,
                "base_lidar": base_lidar,
                "map_quality": "SUPPORTED_TF" if value else "TF_UNAVAILABLE",
                "anchor": anchor,
                "tf_refs": refs + [data["static"][("base_link", "lidar_link")]],
            }
        )
    return poses, scans, intervals, unavailable


def build(root: Path):
    import yaml

    report, locations = verify_sources(root)
    data, config = read_bag(root, locations), Config()
    poses, scans, intervals, unavailable = display_samples(data, config)
    width, height, pixels, map_bytes = pgm(source_bytes(root, locations["map_image"][0]))
    map_yaml = yaml.safe_load(source_bytes(root, locations["map_yaml"][0]))
    if len(data["grids"]) != 1:
        raise ValueError("Ambiguous map")
    grid = data["grids"][0]
    origin = [float(x) for x in map_yaml["origin"]]
    if (
        grid.header.frame_id != "map"
        or grid.info.width != width
        or grid.info.height != height
        or abs(grid.info.resolution - map_yaml["resolution"]) > 1e-8
    ):
        raise ValueError("Source map metadata mismatch")
    if (
        abs(grid.info.origin.position.x - origin[0]) > 1e-9
        or abs(grid.info.origin.position.y - origin[1]) > 1e-9
        or origin[2] != 0
    ):
        raise ValueError("N0 map origin mismatch")
    if map_yaml["negate"] != 0 or map_yaml["mode"] != "trinary":
        raise ValueError("Unexpected map encoding")
    for index, occupancy in enumerate(grid.data):
        u, v = index % width, height - 1 - index // width
        p = (255 - pixels[v * width + u]) / 255
        expected = (
            100 if p > map_yaml["occupied_thresh"] else 0 if p < map_yaml["free_thresh"] else -1
        )
        if occupancy != expected:
            raise ValueError("Recorded occupancy differs from source map pixels")
    payloads = {"map.pgm.gz": gzip.compress(map_bytes, mtime=0)}
    assets = [
        {
            "path": "map.pgm.gz",
            "kind": "map",
            "bytes": len(payloads["map.pgm.gz"]),
            "sha256": sha(payloads["map.pgm.gz"]),
            "start_ros_ns": None,
            "end_ros_ns": None,
        }
    ]
    for kind, rows, model in (("poses", poses, PoseChunk), ("scans", scans, ScanChunk)):
        for i in range(0, len(rows), 100):
            subset = rows[i : i + 100]
            name = f"{kind}-{i // 100:03}.json.gz"
            payloads[name] = gzip.compress(canonical(model(samples=subset).model_dump()), mtime=0)
            assets.append(
                {
                    "path": name,
                    "kind": kind,
                    "bytes": len(payloads[name]),
                    "sha256": sha(payloads[name]),
                    "start_ros_ns": subset[0]["ros_ns"],
                    "end_ros_ns": subset[-1]["ros_ns"],
                }
            )
    trial = report["campaign"]["trials"][0]
    evidence = trial["evidence"]
    validation, collision = evidence["validation"], evidence["collision"]
    result = json.loads(source_bytes(root, locations["run_result"][0]))
    final = validation["snapshot"]["tf"]["map_base"]
    goal = validation["commanded_final_goal"]
    pose = final["pose"]
    if not math.isclose(
        math.hypot(pose["x"] - goal["x"], pose["y"] - goal["y"]),
        validation["xy_error_m"],
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise ValueError("Original position metric mismatch")
    yaw_error = abs(
        math.atan2(math.sin(pose["yaw"] - goal["yaw"]), math.cos(pose["yaw"] - goal["yaw"]))
    )
    if not math.isclose(yaw_error, validation["yaw_error_rad"], rel_tol=0, abs_tol=1e-12):
        raise ValueError("Original yaw metric mismatch")
    if (result["ended_ros_ns"] - result["started_ros_ns"]) / 10**9 != evidence["metrics"][
        "mission_ros_seconds"
    ]:
        raise ValueError("Original duration mismatch")
    t0, t1 = data["clocks"][0], data["clocks"][-1]
    gaps = [
        {
            "start_ros_ns": str(result["started_ros_ns"]),
            "end_ros_ns": str(t0),
            "reason": "UNRECORDED_HEAD",
        },
        {
            "start_ros_ns": str(t1),
            "end_ros_ns": str(result["ended_ros_ns"]),
            "reason": "UNRECORDED_TAIL",
        },
    ]
    if not intervals:
        raise ValueError("No supported trajectory")
    gaps.append(
        {
            "start_ros_ns": str(t0),
            "end_ros_ns": intervals[0]["start_ros_ns"],
            "reason": "TF_UNAVAILABLE",
        }
    )
    for a, b in zip(intervals, intervals[1:], strict=False):
        gaps.append(
            {
                "start_ros_ns": a["end_ros_ns"],
                "end_ros_ns": b["start_ros_ns"],
                "reason": "POSE_GAP",
            }
        )
    valid_poses = [p for p in poses if p["quality"] == "SUPPORTED_TF"]
    gaps.append(
        {
            "start_ros_ns": valid_poses[-1]["ros_ns"],
            "end_ros_ns": str(t1),
            "reason": "DISPLAY_POSE_TAIL",
        }
    )
    metrics = [
        {
            "name": name,
            "value": evidence[category][name],
            "unit": unit,
            "pointer": f"/campaign/trials/0/evidence/{category}/{name}",
        }
        for name, unit, category in (
            ("mission_ros_seconds", "s", "metrics"),
            ("odom_path_metres", "m", "metrics"),
            ("xy_error_m", "m", "validation"),
            ("yaw_error_rad", "rad", "validation"),
        )
    ]
    definition = report["campaign"]["definition"]
    code_digest = sha(
        canonical(
            {
                p.name: sha(p.read_bytes())
                for p in (Path(__file__), Path(__file__).with_name("replay_models.py"))
            }
        )
    )
    manifest = Manifest(
        exporter={
            "code_sha256": code_digest,
            "config_sha256": sha(canonical(config.model_dump())),
            "config": config,
        },
        source_identity={
            "campaign_id": report["campaign"]["id"],
            "experiment_id": evidence["experiment_id"],
            "trial_id": trial["id"],
            "run_id": evidence["mission_run_id"],
            "report_id": report["id"],
            "robot_model": definition["robot_model"],
            "environment": definition["world"],
            "profile": trial["profile"],
            "map_id": definition["map_id"],
            "original_config_sha256": validation["provenance"]["config_sha256"],
            "original_parameters_sha256": validation["provenance"]["parameters_sha256"],
        },
        sources=[
            {"id": key, "kind": key, "sha256": value[1], "scope": value[2]}
            for key, value in sorted(locations.items())
        ],
        assets=assets,
        time={
            "mission_start_ns": str(result["started_ros_ns"]),
            "mission_end_ns": str(result["ended_ros_ns"]),
            "dispatch_ns": str(validation["snapshot"]["dispatch_ros_ns"]),
            "final_observation_ns": str(validation["snapshot"]["observed_ros_ns"]),
            "recorded_start_ns": str(t0),
            "recorded_end_ns": str(t1),
            "offset_origin_ns": str(t0),
        },
        segments=intervals,
        coverage={
            "gaps": gaps,
            "source_scans": len(data["scans"]),
            "source_scans_without_map_tf": len(unavailable),
            "unavailable_scan_stamps_ns": unavailable,
            "missing_channels": [
                "AMCL_POSE",
                "GAZEBO_POSE_TRUTH",
                "NAV2_ACTION_EVENTS",
                "PLANNED_PATH",
                "FAULT_EVENTS",
            ],
        },
        scene={
            "width": width,
            "height": height,
            "resolution_m": float(map_yaml["resolution"]),
            "origin": origin,
            "occupied_threshold": float(map_yaml["occupied_thresh"]),
            "free_threshold": float(map_yaml["free_thresh"]),
        },
        metrics=metrics,
        original_validation={
            "ros_outcome": evidence["outcome"],
            "pose_verdict": validation["verdict"],
            "pose_policy": validation["policy"],
            "commanded_final_goal": goal,
            "final_localized_pose": pose,
            "final_pose_ros_ns": str(final["stamp_ns"]),
            "final_observed_ros_ns": str(validation["snapshot"]["observed_ros_ns"]),
            "contact_verdict": collision["verdict"],
            "contact_start_ros_ns": str(collision["start_ns"]),
            "contact_end_ros_ns": str(collision["end_ns"]),
            "contact_frame_count": collision["frame_count"],
            "contact_count": len(collision["contacts"]),
        },
        limitations=[
            "PARTIAL_MISSION_RECORDING",
            "INITIAL_TF_GAP",
            "LOCALIZED_TF_NOT_PHYSICAL_TRUTH",
            "NO_NAV2_EVENT_RECONSTRUCTION",
            "DISPLAY_DOWNSAMPLED",
            "NO_ORIGINAL_GIT_REVISION",
            "HASHES_NOT_SIGNATURES",
            "SCOPED_CONTACT_OBSERVATION_ONLY",
        ],
    )
    payloads["manifest.json"] = canonical(manifest.model_dump())
    payloads["dataset.sha256"] = (sha(payloads["manifest.json"]) + "  manifest.json\n").encode()
    validate_bundle(payloads)
    # Ensure original sources still match after all decoding and derivation.
    for path, expected, _scope in locations.values():
        if sha(source_bytes(root, path)) != expected:
            raise ValueError("Source changed during export")
    return payloads, {
        "source_counts": data["counts"],
        "pose_display_samples": len(poses),
        "scan_display_samples": len(scans),
        "tf_unavailable_source_scans": unavailable,
        "source_paths_private": {key: str(v[0]) for key, v in locations.items()},
    }


def validate_bundle(payloads):
    manifest = Manifest.model_validate_json(payloads["manifest.json"])
    if (
        payloads["dataset.sha256"]
        != (sha(payloads["manifest.json"]) + "  manifest.json\n").encode()
    ):
        raise ValueError("Manifest hash mismatch")
    if set(payloads) != {"manifest.json", "dataset.sha256"} | {a.path for a in manifest.assets}:
        raise ValueError("Unknown or missing assets")
    if len({a.path for a in manifest.assets}) != len(manifest.assets):
        raise ValueError("Duplicate assets")
    total = len(payloads["manifest.json"])
    origin = int(manifest.time.offset_origin_ns)
    previous_by_kind = {"poses": -1, "scans": -1}
    for asset in manifest.assets:
        content = payloads[asset.path]
        if len(content) != asset.bytes or sha(content) != asset.sha256:
            raise ValueError("Asset integrity mismatch")
        if len(content) > 1024 * 1024:
            raise ValueError("Chunk budget exceeded")
        total += len(content)
        raw = decompress_bounded(content)
        if asset.kind == "map":
            w, h, _pixels, _sanitized = pgm(raw)
            if (w, h) != (manifest.scene.width, manifest.scene.height):
                raise ValueError("Map dimensions mismatch")
            continue
        chunk = (PoseChunk if asset.kind == "poses" else ScanChunk).model_validate_json(raw)
        previous = previous_by_kind[asset.kind]
        for row in chunk.samples:
            t = int(row.ros_ns)
            if t <= previous or row.offset_us != offset_us(t, origin):
                raise ValueError("Sample order/offset mismatch")
            if not int(manifest.time.recorded_start_ns) <= t <= int(manifest.time.recorded_end_ns):
                raise ValueError("Sample outside recording")
            previous = t
            if row.segment_id is not None:
                segment = next((s for s in manifest.segments if s.id == row.segment_id), None)
                if segment is None or not int(segment.start_ros_ns) <= t <= int(
                    segment.end_ros_ns
                ):
                    raise ValueError("Invalid sample segment")
        previous_by_kind[asset.kind] = previous
        if not chunk.samples or (asset.start_ros_ns, asset.end_ros_ns) != (
            chunk.samples[0].ros_ns,
            chunk.samples[-1].ros_ns,
        ):
            raise ValueError("Chunk time bounds mismatch")
    if (
        total > 5 * 1024 * 1024
        or len(payloads["manifest.json"]) + len(payloads["map.pgm.gz"]) > 250 * 1024
    ):
        raise ValueError("Scenario/initial transfer budget exceeded")
    return manifest


def export(root: Path, output: Path):
    output = output.absolute()
    allowed = root / "artifacts/p2-n0-20261011"
    if output.parent != allowed or not re.fullmatch(r"dataset(?:-[a-z0-9]+)*", output.name):
        raise ValueError("Output must be a new approved private dataset directory")
    if output.exists() or output.is_symlink() or allowed.is_symlink():
        raise FileExistsError("Never overwrite existing evidence or follow output symlink")
    payloads, audit = build(root)
    output.mkdir(mode=0o700)
    for name, content in sorted(payloads.items()):
        with (output / name).open("xb") as stream:
            stream.write(content)
    return {
        "manifest_sha256": sha(payloads["manifest.json"]),
        "asset_bytes": {name: len(content) for name, content in payloads.items()},
        **audit,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.audit_output.absolute().parent != ROOT / "artifacts/p2-n0-20261011"
        or args.audit_output.exists()
    ):
        raise ValueError("Audit must be new and private outside bundle")
    audit = export(ROOT, args.output)
    with args.audit_output.open("x") as stream:
        json.dump(audit, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {"manifest_sha256": audit["manifest_sha256"], "asset_bytes": audit["asset_bytes"]}
        )
    )


if __name__ == "__main__":
    main()
