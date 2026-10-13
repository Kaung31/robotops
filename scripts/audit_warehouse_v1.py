#!/usr/bin/env python3
"""Independent decoded-source audit of private Warehouse Benchmark v1 datasets.

Re-reads each pinned source without the exporter's decoding path, compares every
exported sample with the original MCAP, re-derives disclosures from the private
logs, scans for private content and checks byte-identical repeat exports.
"""

from __future__ import annotations

import argparse
import getpass
import gzip
import hashlib
import json
import re
import socket
from pathlib import Path

from audit_baseline_v2 import close_transform, compose, values
from export_n0_replay import ROOT
from export_warehouse_v1 import APPROVED, MAP_PINS, MATRIX, OUTPUT_ROOT, RESULTS, validate_bundle

PRIVATE_TOKENS = (
    b"/home/",
    b"/tmp/",
    b"127.0.0.1",
    b"localhost",
    b"http:",
    b"https:",
    b"mailto:",
    b"password",
    b"token",
    b"secret",
    b"manifest_path",
    b"artifact_directory",
    b"accepted_utc",
    b"started_utc",
    b"created_utc",
    b".log",
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pointer(document, path: str):
    for part in path.lstrip("/").split("/"):
        document = document[int(part)] if isinstance(document, list) else document[part]
    return document


def privacy_scan(payloads) -> dict:
    tokens = [*PRIVATE_TOKENS, getpass.getuser().encode(), socket.gethostname().encode()]
    decoded = {k: gzip.decompress(v) if k.endswith(".gz") else v for k, v in payloads.items()}
    hits = sorted(
        {(name, t.decode()) for name, data in decoded.items() for t in tokens if t and t in data}
    )
    if hits:
        raise ValueError(f"Private content in export: {hits}")
    return {"files_scanned": len(decoded), "tokens_checked": len(tokens), "hits": 0}


def audit(root: Path, payloads):
    import rosbag2_py
    import tf2_py
    from rclpy.duration import Duration
    from rclpy.serialization import deserialize_message
    from rclpy.time import Time
    from rosidl_runtime_py.utilities import get_message

    manifest = validate_bundle(payloads)
    pin = APPROVED[manifest.dataset_id]
    hashes = {s.id: s.sha256 for s in manifest.sources}
    report_bytes = (root / RESULTS / f"report-{pin['campaign']}.json").read_bytes()
    run = root / "artifacts/runs" / pin["run"]
    checks = {
        "report": report_bytes,
        "run_result": (run / "result.json").read_bytes(),
        "run_metadata": (run / "metadata.json").read_bytes(),
        "bag_metadata": (run / "telemetry/metadata.yaml").read_bytes(),
        "mcap": (run / "telemetry/telemetry_0.mcap").read_bytes(),
        "recorder_log": (run / "recorder.log").read_bytes(),
        "launch_log": (root / pin["launch_log"][0]).read_bytes(),
        "matrix": (root / MATRIX[0]).read_bytes(),
        "map_yaml": (root / MAP_PINS["map_yaml"][0]).read_bytes(),
        "map_image": (root / MAP_PINS["map_image"][0]).read_bytes(),
    }
    for key, data in checks.items():
        if digest(data) != hashes[key]:
            raise ValueError(f"Independent source hash mismatch: {key}")
    report = json.loads(report_bytes)
    if report["id"] != manifest.source_identity.report_id:
        raise ValueError("Report identity changed")
    for metric in manifest.metrics:
        if metric.value != pointer(report, metric.pointer):
            raise ValueError("Metric differs from exact source pointer")
    if manifest.original_report_limitations != report["limitations"]:
        raise ValueError("Original report limitations changed")
    trial = report["campaign"]["trials"][0]
    evidence = trial["evidence"]
    validation, collision = evidence["validation"], evidence["collision"]
    runner_path = Path(evidence["manifest_path"])
    runner_bytes = runner_path.read_bytes()
    if (
        not runner_path.is_relative_to(root / "artifacts")
        or digest(runner_bytes) != hashes["runner_manifest"]
    ):
        raise ValueError("Runner snapshot hash mismatch")
    contacts = sorted(runner_path.parent.glob("contacts-*.json"))
    if len(contacts) != 1 or digest(contacts[0].read_bytes()) != hashes["contacts"]:
        raise ValueError("Contact evidence hash mismatch")
    runner = json.loads(runner_bytes)
    original = manifest.original_validation
    if (
        original.ros_outcome != evidence["outcome"]
        or original.pose_verdict != validation["verdict"]
        or original.pose_policy.model_dump() != validation["policy"]
        or original.commanded_final_goal.model_dump() != validation["commanded_final_goal"]
        or original.final_localized_pose.model_dump()
        != validation["snapshot"]["tf"]["map_base"]["pose"]
        or original.final_pose_ros_ns != str(validation["snapshot"]["tf"]["map_base"]["stamp_ns"])
        or original.action_status != validation["action_status"]
        or runner["trials"][0]["action_status"] != validation["action_status"]
        or original.contact_verdict != collision["verdict"]
        or original.contact_frame_count != collision["frame_count"]
        or original.contact_count != len(collision["contacts"])
        or int(original.contact_start_ros_ns) != collision["start_ns"]
        or int(original.contact_end_ros_ns) != collision["end_ns"]
    ):
        raise ValueError("Original verdict, policy or contact result changed")
    result = json.loads(checks["run_result"])
    t = manifest.time
    if (t.mission_start_ns, t.mission_end_ns, t.result_finalized_ns) != (
        str(result["started_ros_ns"]),
        str(result["mission_ended_ros_ns"]),
        str(result["ended_ros_ns"]),
    ):
        raise ValueError("Mission time bounds differ from result")
    if (int(t.mission_end_ns) - int(t.mission_start_ns)) / 1e9 != evidence["metrics"][
        "mission_ros_seconds"
    ]:
        raise ValueError("Duration interval differs from the original metric")
    matrix = json.loads(checks["matrix"])
    [planned] = [p for p in matrix["trials"] if p["slot"] == manifest.dataset_id]
    c = manifest.conditions
    if (
        [w.model_dump() for w in c.waypoints] != matrix["mission"]["waypoints"]
        or c.profile != planned["profile"]
        or manifest.benchmark.pair != planned["pair"]
        or manifest.benchmark.profile_trial != planned["profile_trial"]
        or c.measured_runner_start.model_dump() != runner["trials"][0]["start_pose"]
    ):
        raise ValueError("Conditions differ from matrix or runner")

    launch = checks["launch_log"].decode("utf-8", "replace")
    died = re.findall(r"process has died \[pid \d+, exit code (-?\d+)", launch)
    crashed = bool(died) or "XIO:" in launch
    if crashed != (manifest.teardown.status == "CRASHED_AFTER_EVIDENCE_FINALIZED"):
        raise ValueError("Teardown disclosure differs from the launch log")
    recorder = checks["recorder_log"].decode()
    lost = sum(
        int(n) for n in re.findall(r"messages lost on the transport layer: (\d+)", recorder)
    )
    complete = all(
        m in recorder
        for m in (
            "Event publisher thread: Started",
            "Recording stopped",
            "Event publisher thread: Exited",
        )
    )
    if not complete or lost:
        raise ValueError("Recorder loss disclosure differs from the recorder log")

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(run / "telemetry"), storage_id="mcap"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    types = {x.name: get_message(x.type) for x in reader.get_all_topics_and_types()}
    counts, messages, first_clock, last_clock = {}, {}, None, None
    tf = tf2_py.BufferCore(Duration(seconds=300))
    while reader.has_next():
        topic, raw, _ = reader.read_next()
        counts[topic] = counts.get(topic, 0) + 1
        if topic == "/clock":
            clock = deserialize_message(raw, types[topic]).clock
            stamp = clock.sec * 10**9 + clock.nanosec
            first_clock = stamp if first_clock is None else first_clock
            last_clock = stamp
            continue
        if topic not in {"/tf", "/tf_static", "/scan", "/odom", "/map"}:
            continue
        message = deserialize_message(raw, types[topic])
        messages[(topic, counts[topic])] = (message, digest(raw))
        if topic in ("/tf", "/tf_static"):
            for transform in message.transforms:
                (tf.set_transform_static if topic == "/tf_static" else tf.set_transform)(
                    transform, "independent_warehouse_audit"
                )
    del reader
    if [str(first_clock), str(last_clock)] != [t.recorded_start_ns, t.recorded_end_ns]:
        raise ValueError("Recording clock bounds mismatch")
    poses, scans, rays, refs = 0, 0, 0, 0
    for asset in manifest.assets:
        raw = gzip.decompress(payloads[asset.path])
        if asset.kind == "map":
            header = f"P5\n{manifest.scene.width} {manifest.scene.height}\n255\n".encode()
            pixels = raw[len(header) :]
            # The source PGM ends with exactly width*height gray8 pixels.
            if not raw.startswith(header) or pixels != checks["map_image"][-len(pixels) :]:
                raise ValueError("Map pixels differ from the pinned source image")
            grid = [m for (topic, _), (m, _) in messages.items() if topic == "/map"]
            if len(grid) != 1 or (grid[0].info.width, grid[0].info.height) != (
                manifest.scene.width,
                manifest.scene.height,
            ):
                raise ValueError("Map metadata mismatch")
            continue
        for row in json.loads(raw)["samples"]:
            stamp = int(row["ros_ns"])
            anchor = row["anchor"]
            source, source_digest = messages[(anchor["topic"], anchor["ordinal"])]
            if source_digest != anchor["cdr_sha256"] or stamp != (
                source.header.stamp.sec * 10**9 + source.header.stamp.nanosec
            ):
                raise ValueError("Anchor identity/stamp mismatch")
            dynamic = {}
            for ref in row["tf_refs"]:
                message, ref_digest = messages[(ref["topic"], ref["ordinal"])]
                transform = message.transforms[ref["transform_index"]]
                ref_stamp = transform.header.stamp.sec * 10**9 + transform.header.stamp.nanosec
                if ref_digest != ref["cdr_sha256"] or str(ref_stamp) != ref["ros_ns"]:
                    raise ValueError("TF source reference mismatch")
                if ref["topic"] == "/tf":
                    key = (transform.header.frame_id, transform.child_frame_id)
                    dynamic.setdefault(key, []).append(ref_stamp)
                refs += 1
            for stamps in dynamic.values():
                if (
                    not min(stamps) <= stamp <= max(stamps)
                    or max(stamps) - min(stamps) > 250_000_000
                ):
                    raise ValueError("Source TF bracket invalid")
            try:
                a = tf.lookup_transform_core("map", "odom", Time(nanoseconds=stamp)).transform
                b = tf.lookup_transform_core(
                    "odom", "base_link", Time(nanoseconds=stamp)
                ).transform
                expected = compose(values(a), values(b))
            except tf2_py.TransformException:
                expected = None
            actual = row["transform"] if asset.kind == "poses" else row["map_base"]
            if (expected is None) != (actual is None):
                raise ValueError("TF availability misrepresented")
            if expected is not None:
                close_transform(actual, expected)
            if asset.kind == "poses":
                poses += 1
                continue
            close_transform(
                row["base_lidar"],
                values(
                    tf.lookup_transform_core(
                        "base_link", "lidar_link", Time(nanoseconds=stamp)
                    ).transform
                ),
            )
            if (
                row["angle_min_rad"] != source.angle_min
                or row["angle_increment_rad"] != source.angle_increment
            ):
                raise ValueError("Scan angular geometry changed")
            for index, value in zip(row["selected_indices"], row["ranges_m"], strict=True):
                original_range = source.ranges[index]
                valid = source.range_min <= original_range <= source.range_max
                if (value != original_range) if valid else (value is not None):
                    raise ValueError("Scan range differs from original indexed ray")
                rays += 1
            scans += 1
    unavailable = []
    for (topic, _), (message, _) in messages.items():
        if topic != "/scan":
            continue
        stamp = message.header.stamp.sec * 10**9 + message.header.stamp.nanosec
        try:
            tf.lookup_transform_core("map", "base_link", Time(nanoseconds=stamp))
        except tf2_py.TransformException:
            unavailable.append(str(stamp))
    if unavailable != manifest.coverage.unavailable_scan_stamps_ns:
        raise ValueError("Source TF gaps not preserved")
    return {
        "kind": "robotops.private_warehouse_source_audit",
        "dataset": manifest.dataset_id,
        "manifest_sha256": digest(payloads["manifest.json"]),
        "independent_source_hashes": sorted(checks),
        "pose_samples_compared": poses,
        "scan_samples_compared": scans,
        "indexed_ranges_compared": rays,
        "tf_refs_compared": refs,
        "source_scans_without_map_tf": len(unavailable),
        "full_mission_replay": manifest.coverage.full_mission_replay,
        "teardown": manifest.teardown.status,
        "recorder_transport_lost_messages": lost,
        "metrics_exact_source_pointer_comparison": True,
        "original_verdicts_preserved": True,
        "privacy": privacy_scan(payloads),
        "files": {
            name: {"bytes": len(data), "sha256": digest(data)}
            for name, data in sorted(payloads.items())
        },
    }


def read_bundle(directory: Path):
    entries = list(directory.iterdir())
    if any(not p.is_file() or p.is_symlink() for p in entries):
        raise ValueError("Bundle must contain regular files only")
    return {p.name: p.read_bytes() for p in entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--repeat", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    allowed = ROOT / OUTPUT_ROOT
    if args.output.absolute().parent != allowed or args.output.exists():
        raise ValueError("Audit output must be a new private file")
    payloads = read_bundle(args.dataset)
    if read_bundle(args.repeat) != payloads:
        raise ValueError("Repeat export is not byte-identical")
    report = {**audit(ROOT, payloads), "repeat_export_byte_identical": True}
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "dataset",
                    "manifest_sha256",
                    "pose_samples_compared",
                    "scan_samples_compared",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
