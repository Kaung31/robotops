#!/usr/bin/env python3
"""Independent decoded-source comparisons for private N0 playback assets."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

from export_n0_replay import REPORT, REPORT_SHA, ROOT, RUN_ID, validate_bundle


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
    if (
        original.pose_policy.model_dump() != validation["policy"]
        or original.pose_verdict != validation["verdict"]
        or original.final_localized_pose.model_dump()
        != validation["snapshot"]["tf"]["map_base"]["pose"]
    ):
        raise ValueError("Original validation changed")
    collision = original_report["campaign"]["trials"][0]["evidence"]["collision"]
    if (
        original.contact_verdict != collision["verdict"]
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
        if topic not in {"/tf", "/tf_static", "/scan", "/odom", "/clock"}:
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
        "kind": "robotops.private_n0_source_audit",
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
    if args.output.absolute().parent != ROOT / "artifacts/p2-n0-20261011":
        raise ValueError("Audit output must remain private")
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
