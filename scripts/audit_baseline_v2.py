#!/usr/bin/env python3
"""Independent decoded-source comparisons for approved private N0/N2 v2 assets."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

from export_baseline_v2 import APPROVED, validate_bundle
from export_n0_replay import ROOT


def multiply(a, b):
    x, y, z, w = a
    u, v, s, t = b
    return [
        w * u + x * t + y * s - z * v,
        w * v - x * s + y * t + z * u,
        w * s + x * v - y * u + z * t,
        w * t - x * u - y * v - z * s,
    ]


def compose(a, b):
    """T_map_base = T_map_odom * T_odom_base; independently check direction."""
    qa, qb = a["quaternion"], b["quaternion"]
    x, y, z = b["position"]
    rotated = multiply(multiply(qa, [x, y, z, 0.0]), [-qa[0], -qa[1], -qa[2], qa[3]])[:3]
    return {
        "position": [u + v for u, v in zip(a["position"], rotated, strict=True)],
        "quaternion": multiply(qa, qb),
    }


def values(transform):
    t, q = transform.translation, transform.rotation
    return {"position": [t.x, t.y, t.z], "quaternion": [q.x, q.y, q.z, q.w]}


def close_transform(actual, expected):
    for key in ("position", "quaternion"):
        matches = all(
            math.isclose(a, b, rel_tol=0, abs_tol=1e-10)
            for a, b in zip(actual[key], expected[key], strict=True)
        )
        if key == "quaternion":
            # q and -q encode exactly the same rotation; TF2 may choose either sign.
            matches = matches or all(
                math.isclose(a, -b, rel_tol=0, abs_tol=1e-10)
                for a, b in zip(actual[key], expected[key], strict=True)
            )
        if not matches:
            raise ValueError("Decoded TF/source composition mismatch: " + key)


def audit(root: Path, payloads):
    import rosbag2_py
    import tf2_py
    from rclpy.duration import Duration
    from rclpy.serialization import deserialize_message
    from rclpy.time import Time
    from rosidl_runtime_py.utilities import get_message

    manifest = validate_bundle(payloads)
    pin = APPROVED[manifest.dataset_id]
    REPORT, REPORT_SHA, RUN_ID = pin["report"], pin["report_sha"], pin["run"]
    mcap = root / f"artifacts/runs/{RUN_ID}/telemetry/telemetry_0.mcap"
    source_hashes = {s.id: s.sha256 for s in manifest.sources}
    if (
        hashlib.sha256((root / REPORT).read_bytes()).hexdigest() != REPORT_SHA
        or source_hashes["report"] != REPORT_SHA
    ):
        raise ValueError("Independent report hash mismatch")
    if hashlib.sha256(mcap.read_bytes()).hexdigest() != source_hashes["mcap"]:
        raise ValueError("Independent recording hash mismatch")
    original_report = json.loads((root / REPORT).read_bytes())
    for metric in manifest.metrics:
        source = original_report
        for part in metric.pointer.lstrip("/").split("/"):
            source = source[int(part)] if isinstance(source, list) else source[part]
        if metric.value != source:
            raise ValueError("Metric differs from exact source pointer")
    validation = original_report["campaign"]["trials"][0]["evidence"]["validation"]
    original = manifest.original_validation
    trial = original_report["campaign"]["trials"][manifest.source_trial_index]
    if trial["id"] != pin["trial"] or trial["evidence"]["mission_run_id"] != RUN_ID:
        raise ValueError("Source trial association mismatch")
    runner_path = Path(trial["evidence"]["manifest_path"])
    if (
        not runner_path.is_relative_to(root / "artifacts")
        or runner_path.resolve() != runner_path
        or hashlib.sha256(runner_path.read_bytes()).hexdigest() != source_hashes["runner_manifest"]
    ):
        raise ValueError("Runner snapshot hash mismatch")
    runner = json.loads(runner_path.read_bytes())
    if runner["trials"][0].get("action_status") != validation.get("action_status"):
        raise ValueError("Mission action source conflict")
    c = manifest.conditions
    definition = original_report["campaign"]["definition"]
    if (
        [w.model_dump() for w in c.waypoints] != definition["waypoints"]
        or c.measured_runner_start.model_dump() != runner["trials"][0]["start_pose"]
        or c.campaign_repetitions != definition["repetitions"]
    ):
        raise ValueError("Experiment conditions differ from source")
    run_result_path = root / f"artifacts/runs/{RUN_ID}/result.json"
    if hashlib.sha256(run_result_path.read_bytes()).hexdigest() != source_hashes["run_result"]:
        raise ValueError("Result source hash mismatch")
    result = json.loads(run_result_path.read_bytes())
    if (manifest.time.mission_start_ns, manifest.time.mission_end_ns) != (
        str(result["started_ros_ns"]),
        str(result["ended_ros_ns"]),
    ):
        raise ValueError("Mission time bounds differ from result")
    required_gaps = {
        ("UNRECORDED_HEAD", manifest.time.mission_start_ns, manifest.time.recorded_start_ns),
        ("UNRECORDED_TAIL", manifest.time.recorded_end_ns, manifest.time.mission_end_ns),
    }
    if not required_gaps.issubset(
        {(g.reason, g.start_ros_ns, g.end_ros_ns) for g in manifest.coverage.gaps}
    ):
        raise ValueError("Unrecorded mission coverage changed")
    if (
        c.requested_start.model_dump() != {k: definition["start"][k] for k in ("x", "y", "yaw")}
        or c.start_position_tolerance_m != definition["start"]["position_tolerance"]
        or c.start_yaw_tolerance_rad != definition["start"]["yaw_tolerance"]
    ):
        raise ValueError("Start conditions changed")
    if runner["random_seed"] is not None or runner["trials"][0]["software_revision"] is not None:
        raise ValueError("Unexpected original seed/revision")
    status = validation.get("action_status")
    if (
        type(status) is not int
        or status != 4
        or original.action_status != status
        or original.mission_action.quality != "AVAILABLE"
    ):
        raise ValueError("Original mission-action status mismatch")
    if (
        original.ros_outcome != trial["evidence"]["outcome"]
        or original.commanded_final_goal.model_dump() != validation["commanded_final_goal"]
    ):
        raise ValueError("Original mission outcome/goal changed")
    if (
        original.final_pose_ros_ns != str(validation["snapshot"]["tf"]["map_base"]["stamp_ns"])
        or original.final_observed_ros_ns != str(validation["snapshot"]["observed_ros_ns"])
        or original.pose_policy.model_dump() != validation["policy"]
        or original.pose_verdict != validation["verdict"]
        or original.final_localized_pose.model_dump()
        != validation["snapshot"]["tf"]["map_base"]["pose"]
    ):
        raise ValueError("Original validation changed")
    collision = original_report["campaign"]["trials"][0]["evidence"]["collision"]
    if (
        original.contact_count != len(collision["contacts"])
        or original.contact_verdict != collision["verdict"]
        or original.contact_frame_count != collision["frame_count"]
        or int(original.contact_start_ros_ns) != collision["start_ns"]
        or int(original.contact_end_ros_ns) != collision["end_ns"]
    ):
        raise ValueError("Contact result/coverage changed")
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(
            uri=str(root / f"artifacts/runs/{RUN_ID}/telemetry"), storage_id="mcap"
        ),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    types = {t.name: get_message(t.type) for t in reader.get_all_topics_and_types()}
    counts, messages, clocks = {}, {}, []
    tf = tf2_py.BufferCore(Duration(seconds=300))
    while reader.has_next():
        topic, raw, _ = reader.read_next()
        counts[topic] = counts.get(topic, 0) + 1
        if topic not in {"/tf", "/tf_static", "/scan", "/odom", "/clock", "/map"}:
            continue
        message = deserialize_message(raw, types[topic])
        messages[(topic, counts[topic])] = (message, hashlib.sha256(raw).hexdigest())
        if topic == "/clock":
            clocks.append(message.clock.sec * 10**9 + message.clock.nanosec)
        if topic in ("/tf", "/tf_static"):
            for transform in message.transforms:
                (tf.set_transform_static if topic == "/tf_static" else tf.set_transform)(
                    transform, "independent_n0_audit"
                )
    del reader
    if [str(clocks[0]), str(clocks[-1])] != [
        manifest.time.recorded_start_ns,
        manifest.time.recorded_end_ns,
    ]:
        raise ValueError("Recording clock bounds mismatch")
    checked_poses, checked_scans, checked_rays, checked_refs = 0, 0, 0, 0
    for asset in manifest.assets:
        if asset.kind == "map":
            raw = gzip.decompress(payloads[asset.path])
            header = f"P5\n{manifest.scene.width} {manifest.scene.height}\n255\n".encode()
            if not raw.startswith(header):
                raise ValueError("Map header mismatch")
            pixels = raw[len(header) :]
            maps = [msg for (topic, _), (msg, _) in messages.items() if topic == "/map"]
            if len(maps) != 1:
                raise ValueError("Ambiguous source map")
            grid = maps[0]
            scene = manifest.scene
            if (
                (grid.info.width, grid.info.height) != (scene.width, scene.height)
                or grid.header.frame_id != "map"
                or abs(grid.info.resolution - scene.resolution_m) > 1e-8
            ):
                raise ValueError("Map metadata mismatch")
            q = grid.info.origin.orientation
            if [grid.info.origin.position.x, grid.info.origin.position.y, 0.0] != scene.origin or [
                q.x,
                q.y,
                q.z,
                q.w,
            ] != [0.0, 0.0, 0.0, 1.0]:
                raise ValueError("Map origin mismatch")
            if len(pixels) != scene.width * scene.height:
                raise ValueError("Map pixels length mismatch")
            for index, value in enumerate(grid.data):
                col = index % scene.width
                row = scene.height - 1 - index // scene.width
                occupancy = (255 - pixels[row * scene.width + col]) / 255
                expected = (
                    100
                    if occupancy > scene.occupied_threshold
                    else 0
                    if occupancy < scene.free_threshold
                    else -1
                )
                if value != expected:
                    raise ValueError("Source map pixel mismatch")
            continue
        rows = json.loads(gzip.decompress(payloads[asset.path]))["samples"]
        for row in rows:
            t = int(row["ros_ns"])
            anchor = row["anchor"]
            source, digest = messages[(anchor["topic"], anchor["ordinal"])]
            if (
                digest != anchor["cdr_sha256"]
                or t != source.header.stamp.sec * 10**9 + source.header.stamp.nanosec
            ):
                raise ValueError("Anchor identity/stamp mismatch")
            dynamic = {}
            for ref in row["tf_refs"]:
                message, digest = messages[(ref["topic"], ref["ordinal"])]
                transform = message.transforms[ref["transform_index"]]
                stamp = transform.header.stamp.sec * 10**9 + transform.header.stamp.nanosec
                if digest != ref["cdr_sha256"] or str(stamp) != ref["ros_ns"]:
                    raise ValueError("TF source reference mismatch")
                if ref["topic"] == "/tf":
                    key = (transform.header.frame_id, transform.child_frame_id)
                    dynamic.setdefault(key, []).append(stamp)
                checked_refs += 1
            for stamps in dynamic.values():
                if not min(stamps) <= t <= max(stamps) or max(stamps) - min(stamps) > 250_000_000:
                    raise ValueError("Source TF bracket invalid")
            try:
                a = tf.lookup_transform_core("map", "odom", Time(nanoseconds=t)).transform
                b = tf.lookup_transform_core("odom", "base_link", Time(nanoseconds=t)).transform
                expected = compose(values(a), values(b))
            except tf2_py.TransformException:
                expected = None
            actual = row["transform"] if asset.kind == "poses" else row["map_base"]
            if (expected is None) != (actual is None):
                raise ValueError("TF availability misrepresented")
            if expected is not None:
                close_transform(actual, expected)
                if set(dynamic) != {("map", "odom"), ("odom", "base_link")}:
                    raise ValueError("Missing TF edge provenance")
            if asset.kind == "poses":
                checked_poses += 1
            else:
                close_transform(
                    row["base_lidar"],
                    values(
                        tf.lookup_transform_core(
                            "base_link", "lidar_link", Time(nanoseconds=t)
                        ).transform
                    ),
                )
                if (
                    row["angle_min_rad"] != source.angle_min
                    or row["angle_increment_rad"] != source.angle_increment
                ):
                    raise ValueError("Scan angular geometry changed")
                for index, value in zip(row["selected_indices"], row["ranges_m"], strict=True):
                    if value != source.ranges[index]:
                        raise ValueError("Scan range differs from original indexed ray")
                    checked_rays += 1
                checked_scans += 1
    unavailable = []
    for (topic, _ordinal), (message, _digest) in messages.items():
        if topic != "/scan":
            continue
        t = message.header.stamp.sec * 10**9 + message.header.stamp.nanosec
        try:
            tf.lookup_transform_core("map", "base_link", Time(nanoseconds=t))
        except tf2_py.TransformException:
            unavailable.append(str(t))
    if unavailable != manifest.coverage.unavailable_scan_stamps_ns:
        raise ValueError("Source initial TF gaps not preserved")
    return {
        "kind": "robotops.private_v2_source_audit",
        "dataset": manifest.dataset_id,
        "map_cells_compared": manifest.scene.width * manifest.scene.height,
        "mission_action_status_compared": True,
        "pose_samples_compared": checked_poses,
        "scan_samples_compared": checked_scans,
        "indexed_ranges_compared": checked_rays,
        "tf_refs_compared": checked_refs,
        "source_tf_unavailable_scan_stamps_ns": unavailable,
        "metrics_exact_source_pointer_comparison": True,
        "original_policy_pose_contact_preserved": True,
        "nav2_events_reconstructed": False,
        "ground_truth_claimed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payloads = {p.name: p.read_bytes() for p in args.dataset.iterdir() if p.is_file()}
    report = audit(ROOT, payloads)
    if args.output.absolute().parent != ROOT / "artifacts/p4b-export-20261011":
        raise ValueError("Audit output must remain private")
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
