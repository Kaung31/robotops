#!/usr/bin/env python3
"""Pinned private N0/N2 v2 exporter; no live ROS initialization or controls."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

from export_n0_replay import (
    PINS,
    ROOT,
    canonical,
    decompress_bounded,
    display_samples,
    pgm,
    read_bag,
    sha,
    source_bytes,
)
from replay_models import Config, PoseChunk, ScanChunk, XYTheta, offset_us
from replay_v2_models import ManifestV2

APPROVED = {
    "N0": dict(
        report="artifacts/valid-path-campaigns-20261010/pair-0-off-report.json",
        report_sha="ce9861b1e1e2ef61a796741dab5f3e07595d85eb92d2a607e6356b21202f4797",
        trial="e48a6c6adc394d0393b433d0add4f98c",
        run="0e618a992f084033b1b7d817ae226b55",
        mcap_sha="705400651ac4c2988977fe1a892fa2023477fabbd3619ca4eb1ec961145f0c59",
        count=1,
    ),
    "N2": dict(
        report="artifacts/final-navigation-check-20261010/final-two-trial-report.json",
        report_sha="c442894e2c667ac1722bb44c71fd7297a9825721d793ac4a88a75c6667bed07d",
        trial="7928c75e7c88480fa6d6901550fac26c",
        run="b67b76d9ddfe4779b151704e71119c16",
        mcap_sha="aef67c46ef43eb4832652c7c83017be609ca617f26a943ce7c72d4d2e11bcfa2",
        count=2,
    ),
}
SOURCE_PINS = {
    "N0": {
        "sources": {
            "report": "ce9861b1e1e2ef61a796741dab5f3e07595d85eb92d2a607e6356b21202f4797",
            "runner_manifest": "606979942ecd207f74333aeda077302b7cef797358115d6e8a3d122044632097",
            "run_metadata": "753da541c31567f015a4a062651bdbec2d258aa69331704b1e45c87caf5a1832",
            "bag_metadata": "48ad5a966e9953be9f1ddc77ddad85d97f472006884c702c4149af14398799d6",
            "run_result": "276ee2862b300da9e3657360a1f8350c0340e097ee940ca47a8fc035a795bae4",
            "mcap": "705400651ac4c2988977fe1a892fa2023477fabbd3619ca4eb1ec961145f0c59",
            "contacts": "c9d092f273c03405b50ac29f3a1585fd2533cb17df1e28e0d6cee63efcf514e2",
            "map_yaml": "b39f2ed0bbc8f900711fa8715f3f31c2dbfbed4ed1d10190113e2b9cb15773fa",
            "map_image": "6ad0062c20e30cd812a7b389258b6d95b532af2625194347638e1ae0341b43fe",
        },
        "campaign": "62de882ebf624013ae72de2beaf7de46",
        "experiment": "15d2753fce0144c2a87306ad140bbb7a",
        "report_id": "88da4a2cff54eb30c92df2bb3387fe0e55a84b650af5404610db4116cd785711",
    },
    "N2": {
        "sources": {
            "report": "c442894e2c667ac1722bb44c71fd7297a9825721d793ac4a88a75c6667bed07d",
            "runner_manifest": "286fee0794b009c8cf9d1513dbc11a009eea85962896896c4ceda7253989265b",
            "run_metadata": "4b4411753b9526b9d65171197df5c60af745a28b59480fd8ae189a7f1a3a8c20",
            "bag_metadata": "b7f035bc18a1b47ac18d8a5413dcad2d4cd341a6414dcaf838880fae88cddb85",
            "run_result": "3b3453139d013fc2183c2abacd4af19d8e51a11a852a0936b28cf3064f8a8d5c",
            "mcap": "aef67c46ef43eb4832652c7c83017be609ca617f26a943ce7c72d4d2e11bcfa2",
            "contacts": "fdd51cb4c6e687cd174250febfa6d29865ae5a52adbdee158932441be8a9bb60",
            "map_yaml": "b39f2ed0bbc8f900711fa8715f3f31c2dbfbed4ed1d10190113e2b9cb15773fa",
            "map_image": "6ad0062c20e30cd812a7b389258b6d95b532af2625194347638e1ae0341b43fe",
        },
        "campaign": "fcce82032145477fa051925c0db44eef",
        "experiment": "993a7acc185749bebaf207f2072021b8",
        "report_id": "afd871052039f9731792dc6852f907461c584ebbdbc312739641b652280b8836",
    },
}
PARAMETERS_SHA = "3868b8270cef5c77d912b204b9a5f281193d33a6a4540b02aec3bcc1b886a68a"
WAYPOINTS = [{"x": 0.771351965, "y": 0.62327748, "yaw": 0.0}, {"x": 0.0, "y": 0.0, "yaw": 0.0}]


def mission_action(report_status, runner_status):
    values = (report_status, runner_status)
    if any(v is None for v in values):
        quality = "MISSING"
    elif any(type(v) is not int or v not in range(7) for v in values):
        quality = "INVALID"
    elif report_status != runner_status or report_status != 4:
        quality = "CONFLICT"
    else:
        quality = "AVAILABLE"
    return {
        "action_status": 4 if quality == "AVAILABLE" else None,
        "action_status_reason": quality,
        "mission_action": {
            "quality": quality,
            "status_name": "STATUS_SUCCEEDED" if quality == "AVAILABLE" else None,
        },
    }


def verify_sources(root: Path, dataset: str, *, trial_index: int = 0):
    sys.path.insert(0, str(root / "backend"))
    from robotops_backend.campaigns.report_models import CampaignReport
    from robotops_backend.campaigns.reports import ArtifactReader, digest, trial_integrity

    if dataset not in APPROVED or type(trial_index) is not int or trial_index != 0:
        raise ValueError("Unapproved dataset or trial index")
    pin = APPROVED[dataset]
    report_path = root / pin["report"]
    raw = source_bytes(root, report_path)
    if sha(raw) != pin["report_sha"]:
        raise ValueError("Report pin mismatch")
    report = CampaignReport.model_validate_json(raw)
    if (
        digest(report.model_dump(mode="json", exclude={"id", "created_at"})) != report.id
        or digest(report.campaign.model_dump(mode="json")) != report.source_sha256
    ):
        raise ValueError("Report identity mismatch")
    if len(report.campaign.trials) != pin["count"]:
        raise ValueError("Unexpected trial count")
    trial = report.campaign.trials[trial_index]
    if trial.id != pin["trial"] or trial.evidence.mission_run_id != pin["run"]:
        raise ValueError("Trial/run association mismatch")
    integrity = trial_integrity(report.campaign, trial, ArtifactReader(root / "artifacts"))
    if integrity.state != "VERIFIED":
        raise ValueError("Unverified source chain")
    locations = {"report": (report_path, pin["report_sha"], "original_bound")}
    for check in integrity.artifacts:
        path = Path(check.reference)
        kind = {
            "manifest.json": "runner_manifest",
            "metadata.json": "run_metadata",
            "result.json": "run_result",
            "metadata.yaml": "bag_metadata",
        }.get(path.name, "contacts" if path.name.startswith("contacts-") else "mcap")
        if kind in locations or sha(source_bytes(root, path)) != check.actual_sha256:
            raise ValueError("Duplicate or changed source")
        locations[kind] = (
            path,
            check.actual_sha256,
            "audit_snapshot_only" if kind == "runner_manifest" else "original_bound",
        )
    for key in ("map_yaml", "map_image"):
        name, expected = PINS[key]
        path = root / name
        if sha(source_bytes(root, path)) != expected:
            raise ValueError("Map pin mismatch")
        locations[key] = (path, expected, "original_bound")
    if (
        locations["mcap"][0] != root / f"artifacts/runs/{pin['run']}/telemetry/telemetry_0.mcap"
        or locations["mcap"][1] != pin["mcap_sha"]
    ):
        raise ValueError("Recording identity mismatch")
    if {k: v[1] for k, v in locations.items()} != SOURCE_PINS[dataset]["sources"]:
        raise ValueError("Approved source inventory mismatch")
    runner = json.loads(source_bytes(root, locations["runner_manifest"][0]))
    meta = json.loads(source_bytes(root, locations["run_metadata"][0]))
    saved = runner["trials"][0]
    definition = report.campaign.definition.model_dump(mode="json")
    provenance = trial.evidence.validation["provenance"]
    if (
        len(runner["trials"]) != 1
        or saved["run_id"] != pin["run"]
        or runner["config"]["execution_context"]
        != {"campaign_id": report.campaign.id, "trial_id": pin["trial"]}
        or runner["config"]["mission"]["waypoints"] != WAYPOINTS
        or definition["waypoints"] != WAYPOINTS
        or saved["parameters"] != saved["parameters_after"]
        or provenance["parameters_sha256"] != PARAMETERS_SHA
        or runner["random_seed"] is not None
        or runner["fault_configuration"] is not None
        or meta["fault_configuration"] is not None
        or meta["software_revision"] is not None
    ):
        raise ValueError("Unexpected source configuration")
    if (
        meta["settings"]["navigation_profile"] != "navfn_rpp"
        or meta["settings"]["runtime_mode"] != "sim"
        or meta["settings"]["environment"] != "mapping_lab"
        or meta["map"]["yaml_sha256"] != PINS["map_yaml"][1]
        or meta["map"]["image_sha256"] != PINS["map_image"][1]
    ):
        raise ValueError("Map/profile mismatch")
    return report.model_dump(mode="json"), locations, runner


def conditions(report, locations, runner):
    definition = report["campaign"]["definition"]
    start = definition["start"]
    return dict(
        waypoints=definition["waypoints"],
        parameters_sha256=PARAMETERS_SHA,
        map_yaml_sha256=locations["map_yaml"][1],
        map_image_sha256=locations["map_image"][1],
        requested_start={k: start[k] for k in ("x", "y", "yaw")},
        start_position_tolerance_m=start["position_tolerance"],
        start_yaw_tolerance_rad=start["yaw_tolerance"],
        measured_runner_start=runner["trials"][0]["start_pose"],
        campaign_repetitions=definition["repetitions"],
    )


def build(root: Path, dataset: str):
    import yaml

    report, locations, runner = verify_sources(root, dataset)
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
                for p in (
                    Path(__file__),
                    Path(__file__).with_name("replay_v2_models.py"),
                    Path(__file__).with_name("export_n0_replay.py"),
                    Path(__file__).with_name("replay_models.py"),
                )
            }
        )
    )
    manifest = ManifestV2(
        dataset_id=dataset,
        conditions=conditions(report, locations, runner),
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
            **mission_action(
                validation.get("action_status"), runner["trials"][0].get("action_status")
            ),
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
    manifest = ManifestV2.model_validate_json(payloads["manifest.json"])
    pin = APPROVED[manifest.dataset_id]
    identity = manifest.source_identity
    if (
        identity.trial_id != pin["trial"]
        or identity.run_id != pin["run"]
        or identity.campaign_id != SOURCE_PINS[manifest.dataset_id]["campaign"]
        or identity.experiment_id != SOURCE_PINS[manifest.dataset_id]["experiment"]
        or identity.report_id != SOURCE_PINS[manifest.dataset_id]["report_id"]
    ):
        raise ValueError("Unapproved source identity")
    sources = {s.id: s for s in manifest.sources}
    if len(sources) != len(manifest.sources) or set(sources) != {
        "report",
        "runner_manifest",
        "run_metadata",
        "run_result",
        "bag_metadata",
        "mcap",
        "contacts",
        "map_yaml",
        "map_image",
    }:
        raise ValueError("Incomplete or duplicate provenance")
    if {key: value.sha256 for key, value in sources.items()} != SOURCE_PINS[manifest.dataset_id][
        "sources"
    ]:
        raise ValueError("Source inventory pin mismatch")
    if any(
        s.scope != ("audit_snapshot_only" if s.id == "runner_manifest" else "original_bound")
        for s in manifest.sources
    ):
        raise ValueError("Source binding scope conflict")
    if (
        any(s.kind != s.id for s in manifest.sources)
        or sources["report"].sha256 != pin["report_sha"]
        or sources["mcap"].sha256 != pin["mcap_sha"]
    ):
        raise ValueError("Source pin mismatch")
    if (
        manifest.conditions.waypoints != [XYTheta(**w) for w in WAYPOINTS]
        or manifest.conditions.parameters_sha256 != PARAMETERS_SHA
        or manifest.conditions.campaign_repetitions != pin["count"]
    ):
        raise ValueError("Unapproved experiment conditions")
    if manifest.exporter.config_sha256 != sha(canonical(manifest.exporter.config.model_dump())):
        raise ValueError("Exporter config hash mismatch")
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


def export(root: Path, dataset: str, output: Path):
    allowed = root / "artifacts/p4b-export-20261011"
    output = output.absolute()
    if (
        dataset not in APPROVED
        or output.parent != allowed
        or output.name
        not in {f"dataset-{dataset.lower()}-{suffix}" for suffix in ("final", "repeat")}
    ):
        raise ValueError("Unapproved private output")
    if (
        output.exists()
        or output.is_symlink()
        or allowed.is_symlink()
        or allowed.resolve() != allowed
    ):
        raise FileExistsError("Never overwrite evidence or follow output symlinks")
    payloads, receipt = build(root, dataset)
    output.mkdir(mode=0o700)
    for name, content in sorted(payloads.items()):
        with (output / name).open("xb") as stream:
            stream.write(content)
    return {
        "dataset": dataset,
        "manifest_sha256": sha(payloads["manifest.json"]),
        "asset_bytes": {k: len(v) for k, v in payloads.items()},
        **receipt,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=tuple(APPROVED), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    allowed = ROOT / "artifacts/p4b-export-20261011"
    if (
        args.audit_output.absolute().parent != allowed
        or args.audit_output.exists()
        or args.audit_output.is_symlink()
        or allowed.resolve() != allowed
    ):
        raise ValueError("Audit must be a new private receipt")
    receipt = export(ROOT, args.dataset, args.output)
    with args.audit_output.open("x") as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
