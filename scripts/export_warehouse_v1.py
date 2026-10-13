#!/usr/bin/env python3
"""Pinned private Warehouse Benchmark v1 exporter (W01–W06); offline, no ROS graph or controls."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from export_baseline_v2 import mission_action
from export_n0_replay import (
    ROOT,
    canonical,
    decompress_bounded,
    display_samples,
    pgm,
    ros_ns,
    sha,
    source_bytes,
    transform_value,
    validate_clock,
)
from replay_models import Config, PoseChunk, ScanChunk, offset_us
from replay_warehouse_models import SLOTS, W03_TEARDOWN, WarehouseManifest

OUTPUT_ROOT = "artifacts/warehouse-lab-20261013"
RESULTS = "artifacts/warehouse-benchmark-20261012/results"
MATRIX = (
    "benchmarks/warehouse_v1/matrix.json",
    "9d2be2ecc6f60b55736f97f215801d21f1866aa8268baef543f93bb40acaa456",
)
MAP_PINS = {
    "map_yaml": (
        "artifacts/maps/warehouse_v1.yaml",
        "b2d1d5f501dfcd48dad0164d08656542b820abb141650216c51db5ce5446b2c3",
    ),
    "map_image": (
        "artifacts/maps/warehouse_v1.pgm",
        "1eb988b083d384dd94f4e44e0370effc9e26755c899896bda51f7446829199e9",
    ),
}
PARAMETERS_SHA = {
    "navfn_rpp": "f6840191f81165c028820fa2b4930031bffa03e88acb41022ccc9bb2d54773bd",
    "smac_dwb": "596a5200cc2e59c1a61b6de6f83690ab819277759d91dc10798a78bd9ed80c2a",
}
# The 1 kHz /clock alone contributes ~141k messages to a warehouse recording.
INPUT_MESSAGE_BUDGET = 250_000
CHILD_DIED = re.compile(r"\[ERROR\] \[([^\]]+)\]: process has died \[pid \d+, exit code (-?\d+)")
TRANSPORT_LOSS = re.compile(r"Number of messages lost on the transport layer: (\d+)")
LOSS_MARKERS = (
    "Event publisher thread: Started",
    "Recording stopped",
    "Event publisher thread: Exited",
)
LIMITATIONS = [
    "EXPLORATORY_BENCHMARK_NOT_QUALIFIED",
    "THREE_TRIALS_PER_CONFIGURATION",
    "PROFILE_BUNDLES_NOT_SINGLE_ALGORITHMS",
    "SINGLE_WORLD_AND_START",
    "SIMULATION_TIME_ONE_HOST",
    "LOCALIZED_TF_NOT_PHYSICAL_TRUTH",
    "NO_NAV2_EVENT_RECONSTRUCTION",
    "DISPLAY_DOWNSAMPLED",
    "NO_ORIGINAL_GIT_REVISION",
    "HASHES_NOT_SIGNATURES",
    "SCOPED_CONTACT_OBSERVATION_ONLY",
]
APPROVED = {
    "W01": dict(
        campaign="46fd6f8c4e4747dbaf2e0d690f3cff34",
        trial="7fcfc1078d3845e1ab9ce2a5cb68f238",
        run="39fb7bf2ef7d4f5aa1e7561a2042dc6b",
        experiment="c04e52d477ca472f866e0c5fa2e612bc",
        profile="navfn_rpp",
        report_id="869cafe1d5f7f01b9b3f0cfe3d03d309671b085397c72659973ae0bd5ab3db14",
        launch_log=(
            "artifacts/logs/orchestrator/1791836723-robot.log",
            "d70c270521f0342eae9a5f8b8111e3f5748d3633ca04ce36a321d7cd3427d520",
        ),
        recorder_log="5ea419e57b1eac3e0345796fdc3d7164558cd4d001635d52c7999420f6677c4b",
        teardown_failures=[],
        sources=dict(
            report="b414dade3b6fcbc66573ce83724fec9613e59dda2d46c80ce78d910d4c126167",
            runner_manifest="fc332572329802dfecbb998ff55f81b3d5ebfba70f1c49c6538bb901109987dc",
            run_metadata="5e8b0146c3f445fa0ca8ce098c9de9431b7c9a1e09028a47811b37dbe6b74080",
            bag_metadata="3048c2fdf30efcdf491a5c23d2f6350f7f75ff4af0c988e15d0b981317f054f9",
            run_result="eeababba04f29b5db064819c023df44a4c142904f0836d5ef02399f3d43a89af",
            mcap="4bda6be678d51bb0e860c49e8114b83411664de03dfc765a389190c1f29dbc2a",
            contacts="10fe98c27595af8f2f252fb2f8ba24c1de4cab165ec77654a1efaa4252e38142",
        ),
    ),
    "W02": dict(
        campaign="fbb8f2ea20f34ee1a0bdd8cc6fd43b48",
        trial="13af9f02a5b847818ca5b75b3988be31",
        run="a18d2c8c825b46bd95c7e37ad4762856",
        experiment="d6f94fd30e8e4105810ec4366bbe1608",
        profile="smac_dwb",
        report_id="7c0bd4d2fb0aea291d9aa4592a2daeb81f911fe66008585661016aafa63745f2",
        launch_log=(
            "artifacts/logs/orchestrator/1791837023-robot.log",
            "0cac398c45f1d5b4b7d86b9a4aa729353ddbd53627a7d45f9f9c5529cfd634cc",
        ),
        recorder_log="d3ba537057110d934f97153c6fab184dc3763d03d3129f40e950f813b824bf98",
        teardown_failures=[],
        sources=dict(
            report="2285f0bf7e03f227a55521faac7163eaca03c1c7e8d08e657da186c981926680",
            runner_manifest="933d1afdcc943d744cf7d761613b62886620335dd67a111d6e657e7ba4dded79",
            run_metadata="304056b8c33f047477a8003cd0fcb0f5c9170e18063cc72516844c78a9813727",
            bag_metadata="8ac89a468e588cc1626a6b9e28aa6bc3ffbeaf4f5c5889a07def68edc5e0e733",
            run_result="dae41c13c5c9db4358c88e19bad2d8585eff127b23a7166681a3be93f7aab6df",
            mcap="0e14ca604499a668cf3fbd19e15f91a5f64cb142fc2863a07d96878d6e63e5c4",
            contacts="db5d9bbe2f24f7ded83e9f48b7edf0297a523345c07bb1431c79b24821ce385a",
        ),
    ),
    "W03": dict(
        campaign="bb0012683a99451b828e0b04c36e5546",
        trial="10a260b7c3ca4aa3a40fdd15e8cdaa0e",
        run="ca866526404648f5a57591a21406226b",
        experiment="c6cfdf63369443eda797511be6a524d3",
        profile="smac_dwb",
        report_id="c8370ad6c9411b443ef73c58edaab92a5374de3a122be3d1a1aaf66d9b9f7fa8",
        launch_log=(
            "artifacts/logs/orchestrator/1791837282-robot.log",
            "67dc41f3fced11f05e03f318208fa8091ec6e7a31d154c435860369412a464c4",
        ),
        recorder_log="12759ae9275f9f08481b0d73c31a0795ce79b0da5a361f4dc02cb28c99211c2f",
        teardown_failures=[("twist_mux-5", "-2"), ("gazebo_runner-2", "-11")],
        sources=dict(
            report="3202c0ed771359ec1c9a605d7f6bb3f0a9c5fe06490b06471ee2c51d35113312",
            runner_manifest="33ad16dc433fc85e94ff8ab788039dbfa51a55cc7fe978772803294e9dbed24a",
            run_metadata="ea35d246424fd9034e57d45ba985ece9ec83772d954c84bfaa114214d815264b",
            bag_metadata="59328f36f04f3783a483b9fc0d9d47fe2371f40469a0c8d51c023ac7eb477e26",
            run_result="57504457a58a0a78c3bfc49d85ffcf47bf1f89ea08fabbad44ea71535f473f1b",
            mcap="47a1250023b7fd15521a082369cb8c72870eefe0111139909bdee8f26ed1773c",
            contacts="8c775d931ee8861cb01ebd0a6362d0e4c75d6d72f5182d236c5ef699c8ce13ff",
        ),
    ),
    "W04": dict(
        campaign="b8e0d236b44b4489877331aad6377eb0",
        trial="e51661a5d3114a0e9e185da86b24297d",
        run="33bc3f4ebef941afb55c98fc47e3da43",
        experiment="c2830c419a194eb6a65316d7b5d6220f",
        profile="navfn_rpp",
        report_id="51e222e4ae3c97f11d6ce39dcd885665bf62ac822775871aeba5c4364bb93976",
        launch_log=(
            "artifacts/logs/orchestrator/1791837441-robot.log",
            "bc360dab6c9530c2add59c7caf2ccc6a97f5c857c8d194bdb13948e9ec3ca72e",
        ),
        recorder_log="607379e8c5acd29d7b9a5fcc7faa9308d89956a434b75ee5aa8210f009d748fb",
        teardown_failures=[],
        sources=dict(
            report="20d4b5e2e810dea003425808c3a5720870e9bb06197fd74763c54647b95831a4",
            runner_manifest="89c437189b154e6800cd397590e6e6bbae150ad2bc5097a206a4884747176b04",
            run_metadata="ca36fe039ad9128ef8dbcb5c538f3017822d1e7eff08c07790ce91c042108753",
            bag_metadata="289e73a05aba4dda22ad30402109dd53b76384f94980f20889801a016f4d1cfc",
            run_result="33a796a7cbe60e9d9a25e7f290b54edf1eb6b8a25a387e9e177742084f62ed8f",
            mcap="2d8dcaa5fbd893c35c76de4a34ed3572e7e21315475fdb025a7e6515a7ec4d05",
            contacts="ad3143d37de631cdec75100f4865936a31c56366a40cdc8aa22de53c7015fed5",
        ),
    ),
    "W05": dict(
        campaign="908e04a613b9433b8ece52664b816b2c",
        trial="807f99063d5e4d6e9c4d78d391361c1c",
        run="552859aa1395479da67c61e65b07c204",
        experiment="47a2662523b84c86b026f876bb64fc03",
        profile="navfn_rpp",
        report_id="ef359c0c79f55e592fdecae2127ea7977089e4816fde02589fccb6851e64f1da",
        launch_log=(
            "artifacts/logs/orchestrator/1791837604-robot.log",
            "69a449f4fc313e43c1de62052c2d47963f921b9cb951670fb0f46ac23c94a0ad",
        ),
        recorder_log="8c35ed594828354a196a9ace83ae13c8160c18b7f17aafb83da130f750a46ba6",
        teardown_failures=[],
        sources=dict(
            report="b08695b8840756a89ab8d9bc7d7967fd0087671f482bbc391fa38baee1e01089",
            runner_manifest="9d439130f766ff3c094bde8de1a78bae74c055fc0ad77c5c9ab4cca8ee3e8e06",
            run_metadata="7c4b16409656f9802465df60917eca61a4eed77cbd72f0d613bfa9264aa0a50d",
            bag_metadata="1d3c1c3e60161d7c90d689f18adc978b8858e6441d0efbdf210615f78f0a92ee",
            run_result="94bc13f672b900142fd002d9cb64aaf3e97b60dadd31dab953a04c3141176f9d",
            mcap="cb616eac5e12ace2df6bf493ef5bd4eea597e12213aebee8a77af193998795c3",
            contacts="172152f24eb1c706ebfa108e33a3399a0fdad94754665649673505953a629fda",
        ),
    ),
    "W06": dict(
        campaign="57cbadeac8244c70a4fa38d4ca3fb6b2",
        trial="27d412204f4543839b7bbb0bce27e738",
        run="cfdf627021f9490ea89ef9f21d4cc140",
        experiment="b4826afcdbae42a3af183eb61820aceb",
        profile="smac_dwb",
        report_id="5c80daf91225142a7f0f23105129fb760f51cf9fb47237248f14d5ff3696af0d",
        launch_log=(
            "artifacts/logs/orchestrator/1791837767-robot.log",
            "01da4adcbc2766b4d684b2df770acc61a4efa293dddcfaa2afef1f52e1cf437d",
        ),
        recorder_log="87695fe99da3153ba1cb93856fee32a7d8bdaa3cc236037647cfea3e0d07ef10",
        teardown_failures=[],
        sources=dict(
            report="5aafe06d1143f6bb4549e502ef8d7630a15e808d7933300847a1104dc38d08f4",
            runner_manifest="ecbc086cd9573a64f72dfc102fe75ad0d705c4789fb23e271e336b9d6e7fe6dc",
            run_metadata="f5a03832a97797b0af4d2f1644dd00328e95d8f0de120fffcdbee54ce4307f57",
            bag_metadata="5bdb2a5c1ab0c54f989100060238f1944bf601c5193d6a175ce18b65a5aa6eb0",
            run_result="eb7a23f588cfd700a0acf1231bf942428ebd4aa907cbd9e50576d7b9bd31068f",
            mcap="3dabe77f4fe8f1de27249106bf4b7132c0f15fb161189df62cd188ebb28a3e06",
            contacts="2ca8456b2c3b3ebda7f17ef6a1733ad9659e47ab16b96504440c5c0bc3b7fd13",
        ),
    ),
}
SOURCE_SCOPES = {
    "report": "original_bound",
    "runner_manifest": "audit_snapshot_only",
    "run_metadata": "original_bound",
    "run_result": "original_bound",
    "bag_metadata": "original_bound",
    "mcap": "original_bound",
    "contacts": "original_bound",
    "map_yaml": "original_bound",
    "map_image": "original_bound",
    "matrix": "original_bound",
    "recorder_log": "private_log_not_exported",
    "launch_log": "private_log_not_exported",
}


def pinned_sources(dataset: str) -> dict[str, str]:
    pin = APPROVED[dataset]
    return {
        **pin["sources"],
        "map_yaml": MAP_PINS["map_yaml"][1],
        "map_image": MAP_PINS["map_image"][1],
        "matrix": MATRIX[1],
        "recorder_log": pin["recorder_log"],
        "launch_log": pin["launch_log"][1],
    }


def teardown_assessment(log_text: str) -> list[tuple[str, str]]:
    """Child exits that launch reported as deaths; display loss counts as a failure."""
    failures = CHILD_DIED.findall(log_text)
    if "XIO:" in log_text and not failures:
        raise ValueError("Display loss without a reported child exit is unclassified")
    return failures


def loss_assessment(log_text: str) -> dict:
    reported = [int(n) for n in TRANSPORT_LOSS.findall(log_text)]
    return dict(
        accounting_complete=all(marker in log_text for marker in LOSS_MARKERS),
        transport_lost_messages=sum(reported),
        loss_reports=len(reported),
    )


def verify_sources(root: Path, dataset: str):
    sys.path.insert(0, str(root / "backend"))
    from robotops_backend.campaigns.report_models import CampaignReport
    from robotops_backend.campaigns.reports import ArtifactReader, digest, trial_integrity

    if dataset not in APPROVED:
        raise ValueError("Unapproved dataset")
    pin, expected = APPROVED[dataset], pinned_sources(dataset)
    report_path = root / RESULTS / f"report-{pin['campaign']}.json"
    raw = source_bytes(root, report_path)
    if sha(raw) != expected["report"]:
        raise ValueError("Report pin mismatch")
    report = CampaignReport.model_validate_json(raw)
    if (
        report.id != pin["report_id"]
        or digest(report.model_dump(mode="json", exclude={"id", "created_at"})) != report.id
        or digest(report.campaign.model_dump(mode="json")) != report.source_sha256
    ):
        raise ValueError("Report identity mismatch")
    campaign = report.campaign
    if (
        campaign.id != pin["campaign"]
        or len(campaign.trials) != 1
        or campaign.state != "completed"
        or not campaign.termination_confirmed
        or not campaign.cleanup_confirmed
    ):
        raise ValueError("Unexpected campaign record")
    trial = campaign.trials[0]
    if (
        trial.id != pin["trial"]
        or trial.profile != pin["profile"]
        or trial.state != "succeeded"
        or trial.evidence.mission_run_id != pin["run"]
        or trial.evidence.experiment_id != pin["experiment"]
    ):
        raise ValueError("Trial/run association mismatch")
    integrity = trial_integrity(campaign, trial, ArtifactReader(root / "artifacts"))
    if integrity.state != "VERIFIED":
        raise ValueError("Unverified source chain")
    locations = {"report": (report_path, expected["report"])}
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
        locations[kind] = (path, check.actual_sha256)
    run_dir = root / "artifacts/runs" / pin["run"]
    if locations["mcap"][0] != run_dir / "telemetry/telemetry_0.mcap":
        raise ValueError("Recording identity mismatch")
    for key, (name, _) in {**MAP_PINS, "matrix": MATRIX}.items():
        locations[key] = (root / name, sha(source_bytes(root, root / name)))
    locations["recorder_log"] = (run_dir / "recorder.log", None)
    locations["launch_log"] = (root / pin["launch_log"][0], None)
    for key in ("recorder_log", "launch_log"):
        path = locations[key][0]
        locations[key] = (path, sha(source_bytes(root, path)))
    if {k: v[1] for k, v in locations.items()} != expected:
        raise ValueError("Approved source inventory mismatch")

    matrix = json.loads(source_bytes(root, locations["matrix"][0]))
    [planned] = [t for t in matrix["trials"] if t["slot"] == dataset]
    runner = json.loads(source_bytes(root, locations["runner_manifest"][0]))
    meta = json.loads(source_bytes(root, locations["run_metadata"][0]))
    saved = runner["trials"][0]
    definition = campaign.definition.model_dump(mode="json")
    validation = trial.evidence.validation
    provenance = validation["provenance"]
    mission = matrix["mission"]
    if (
        planned["profile"] != pin["profile"]
        or definition["world"] != matrix["scenario"]["id"]
        or definition["map_id"] != "warehouse_v1"
        or definition["waypoints"] != mission["waypoints"]
        or definition["start"]
        != {
            k: mission["start"][k]
            for k in ("x", "y", "yaw", "position_tolerance", "yaw_tolerance")
        }
        or definition["repetitions"] != 1
        or validation["policy"] != mission["validation_policy"]
    ):
        raise ValueError("Campaign definition differs from the frozen matrix")
    if (
        len(runner["trials"]) != 1
        or saved["run_id"] != pin["run"]
        or runner["config"]["execution_context"]
        != {"campaign_id": campaign.id, "trial_id": pin["trial"]}
        or runner["config"]["mission"]["waypoints"] != mission["waypoints"]
        or saved["parameters"] != saved["parameters_after"]
        or provenance["state"] != "confirmed"
        or provenance["parameters_sha256"] != PARAMETERS_SHA[pin["profile"]]
        or runner["random_seed"] is not None
        or runner["fault_configuration"] is not None
        or meta["fault_configuration"] is not None
        or meta["software_revision"] is not None
        or saved["software_revision"] is not None
    ):
        raise ValueError("Unexpected source configuration")
    if (
        meta["settings"]["navigation_profile"] != pin["profile"]
        or meta["settings"]["runtime_mode"] != "sim"
        or meta["settings"]["environment"] != "warehouse_v1"
        or meta["map"]["yaml_sha256"] != MAP_PINS["map_yaml"][1]
        or meta["map"]["image_sha256"] != MAP_PINS["map_image"][1]
    ):
        raise ValueError("Map/profile mismatch")
    launch = source_bytes(root, locations["launch_log"][0]).decode("utf-8", "replace")
    if teardown_assessment(launch) != pin["teardown_failures"]:
        raise ValueError("Teardown assessment differs from the reviewed launch log")
    loss = loss_assessment(source_bytes(root, locations["recorder_log"][0]).decode())
    if loss != dict(accounting_complete=True, transport_lost_messages=0, loss_reports=0):
        raise ValueError("Recorder loss accounting incomplete or lossy")
    return report.model_dump(mode="json"), locations, runner, planned


def read_bag(root: Path, locations):
    """Decode the pinned MCAP once; identical rules to the N0 reader, larger input budget."""
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
    clocks, poses, scans, grids = [], [], [], []
    static = {}
    while reader.has_next():
        topic, raw, _log_ns = reader.read_next()
        counts[topic] += 1
        if sum(counts.values()) > INPUT_MESSAGE_BUDGET:
            raise ValueError("Input message budget exceeded")
        if topic not in {"/clock", "/odom", "/scan", "/tf", "/tf_static", "/map"}:
            continue
        message = deserialize_message(raw, types[topic])
        if topic == "/clock":
            clocks.append(ros_ns(message.clock))
        elif topic == "/map":
            grids.append(message)
        elif topic in ("/tf", "/tf_static"):
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
                    tf.set_transform_static(transform, "private_warehouse_export")
                else:
                    edges[key].append((ros_ns(transform.header.stamp), ref))
                    tf.set_transform(transform, "private_warehouse_export")
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
            raise ValueError("Duplicate/reordered acquisition")
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
    }


def check_map(data, pixels, width, height, map_yaml):
    if len(data["grids"]) != 1:
        raise ValueError("Ambiguous map")
    grid = data["grids"][0]
    origin = [float(x) for x in map_yaml["origin"]]
    if (
        grid.header.frame_id != "map"
        or grid.info.width != width
        or grid.info.height != height
        or abs(grid.info.resolution - map_yaml["resolution"]) > 1e-8
        or abs(grid.info.origin.position.x - origin[0]) > 1e-9
        or abs(grid.info.origin.position.y - origin[1]) > 1e-9
        or origin[2] != 0
    ):
        raise ValueError("Source map metadata mismatch")
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
    return origin


def coverage_gaps(poses, intervals, t0, t1, finalized):
    if not intervals:
        raise ValueError("No supported trajectory")
    gaps = []
    if int(intervals[0]["start_ros_ns"]) > t0:
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
    last = [p for p in poses if p["quality"] == "SUPPORTED_TF"][-1]["ros_ns"]
    if int(last) < t1:
        gaps.append({"start_ros_ns": last, "end_ros_ns": str(t1), "reason": "DISPLAY_POSE_TAIL"})
    if t1 < finalized:
        gaps.append(
            {"start_ros_ns": str(t1), "end_ros_ns": str(finalized), "reason": "UNRECORDED_TAIL"}
        )
    return gaps


def code_digest():
    here = Path(__file__)
    return sha(
        canonical(
            {
                p.name: sha(p.read_bytes())
                for p in (
                    here,
                    here.with_name("replay_warehouse_models.py"),
                    here.with_name("replay_v2_models.py"),
                    here.with_name("replay_models.py"),
                    here.with_name("export_n0_replay.py"),
                    here.with_name("export_baseline_v2.py"),
                )
            }
        )
    )


def build(root: Path, dataset: str):
    import yaml

    report, locations, runner, planned = verify_sources(root, dataset)
    data, config = read_bag(root, locations), Config()
    poses, scans, intervals, unavailable = display_samples(data, config)
    width, height, pixels, map_bytes = pgm(source_bytes(root, locations["map_image"][0]))
    map_yaml = yaml.safe_load(source_bytes(root, locations["map_yaml"][0]))
    origin = check_map(data, pixels, width, height, map_yaml)
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
    goal, pose = validation["commanded_final_goal"], final["pose"]
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
    started, ended = result["started_ros_ns"], result["mission_ended_ros_ns"]
    duration = evidence["metrics"]["mission_ros_seconds"]
    if (ended - started) / 10**9 != duration or result["elapsed_ros_seconds"] != duration:
        raise ValueError("Original duration mismatch")
    if result["outcome"] != "succeeded" or result["completed_waypoints"] != 5:
        raise ValueError("Original mission result mismatch")
    t0, t1 = data["clocks"][0], data["clocks"][-1]
    gaps = coverage_gaps(poses, intervals, t0, t1, result["ended_ros_ns"])
    inside = [
        g
        for g in gaps
        if g["reason"] in ("TF_UNAVAILABLE", "POSE_GAP")
        and int(g["end_ros_ns"]) > started
        and int(g["start_ros_ns"]) < ended
    ]
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
    pin = APPROVED[dataset]
    crashed = bool(pin["teardown_failures"])
    start = definition["start"]
    manifest = WarehouseManifest(
        dataset_id=dataset,
        exporter={
            "code_sha256": code_digest(),
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
            {"id": key, "kind": key, "sha256": value[1], "scope": SOURCE_SCOPES[key]}
            for key, value in sorted(locations.items())
        ],
        assets=assets,
        time={
            "mission_start_ns": str(started),
            "mission_end_ns": str(ended),
            "result_finalized_ns": str(result["ended_ros_ns"]),
            "dispatch_ns": str(validation["snapshot"]["dispatch_ros_ns"]),
            "final_observation_ns": str(validation["snapshot"]["observed_ros_ns"]),
            "recorded_start_ns": str(t0),
            "recorded_end_ns": str(t1),
            "offset_origin_ns": str(t0),
        },
        segments=intervals,
        coverage={
            "full_mission_replay": not inside,
            "gaps": gaps,
            "source_scans": len(data["scans"]),
            "source_scans_without_map_tf": len(unavailable),
            "unavailable_scan_stamps_ns": unavailable,
            "missing_channels": [
                "AMCL_POSE",
                "GAZEBO_POSE_TRUTH",
                "NAV2_ACTION_EVENTS",
                "PLANNED_PATH",
                "COSTMAPS",
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
        original_report_limitations=report["limitations"],
        conditions={
            "profile": trial["profile"],
            "waypoints": definition["waypoints"],
            "parameters_sha256": validation["provenance"]["parameters_sha256"],
            "map_yaml_sha256": locations["map_yaml"][1],
            "map_image_sha256": locations["map_image"][1],
            "requested_start": {k: start[k] for k in ("x", "y", "yaw")},
            "start_position_tolerance_m": start["position_tolerance"],
            "start_yaw_tolerance_rad": start["yaw_tolerance"],
            "measured_runner_start": runner["trials"][0]["start_pose"],
        },
        benchmark={
            "slot": dataset,
            "pair": planned["pair"],
            "profile_trial": planned["profile_trial"],
            "matrix_sha256": locations["matrix"][1],
        },
        teardown={
            "status": "CRASHED_AFTER_EVIDENCE_FINALIZED" if crashed else "NO_CHILD_FAILURE_LOGGED",
            "detail": W03_TEARDOWN if crashed else None,
        },
        recorder_loss={
            "accounting_complete": True,
            "transport_lost_messages": 0,
            "loss_reports": 0,
        },
        limitations=LIMITATIONS + (["TEARDOWN_CRASH_AFTER_FINALIZATION"] if crashed else []),
    )
    payloads["manifest.json"] = canonical(manifest.model_dump())
    payloads["dataset.sha256"] = (sha(payloads["manifest.json"]) + "  manifest.json\n").encode()
    validate_bundle(payloads)
    # Original sources must still match after all decoding and derivation.
    for path, expected in locations.values():
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
    manifest = WarehouseManifest.model_validate_json(payloads["manifest.json"])
    dataset = manifest.dataset_id
    pin, identity = APPROVED[dataset], manifest.source_identity
    if (
        identity.campaign_id != pin["campaign"]
        or identity.trial_id != pin["trial"]
        or identity.run_id != pin["run"]
        or identity.experiment_id != pin["experiment"]
        or identity.report_id != pin["report_id"]
        or identity.profile != pin["profile"]
    ):
        raise ValueError("Unapproved source identity")
    sources = {s.id: s for s in manifest.sources}
    if {k: v.sha256 for k, v in sources.items()} != pinned_sources(dataset):
        raise ValueError("Source inventory pin mismatch")
    if any(s.scope != SOURCE_SCOPES[s.id] for s in manifest.sources):
        raise ValueError("Source binding scope conflict")
    crashed = bool(pin["teardown_failures"])
    if (
        manifest.conditions.parameters_sha256 != PARAMETERS_SHA[pin["profile"]]
        or (manifest.teardown.status == "CRASHED_AFTER_EVIDENCE_FINALIZED") != crashed
        or manifest.limitations
        != LIMITATIONS + (["TEARDOWN_CRASH_AFTER_FINALIZATION"] if crashed else [])
    ):
        raise ValueError("Unapproved conditions, limitations or teardown disclosure")
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
    expected_names = {"poses": 0, "scans": 0}
    for asset in manifest.assets:
        content = payloads[asset.path]
        if len(content) != asset.bytes or sha(content) != asset.sha256:
            raise ValueError("Asset integrity mismatch")
        total += len(content)
        raw = decompress_bounded(content)
        if asset.kind == "map":
            w, h, _pixels, _sanitized = pgm(raw)
            if (w, h) != (manifest.scene.width, manifest.scene.height):
                raise ValueError("Map dimensions mismatch")
            continue
        if asset.path != f"{asset.kind}-{expected_names[asset.kind]:03}.json.gz":
            raise ValueError("Chunk names must be contiguous")
        expected_names[asset.kind] += 1
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
    if not all(expected_names.values()):
        raise ValueError("Missing pose or scan chunks")
    if (
        total > 5 * 1024 * 1024
        or len(payloads["manifest.json"]) + len(payloads["map.pgm.gz"]) > 250 * 1024
    ):
        raise ValueError("Scenario/initial transfer budget exceeded")
    return manifest


def private_directory(root: Path) -> Path:
    allowed = root / OUTPUT_ROOT
    if allowed.is_symlink() or not allowed.parent.is_dir() or allowed.parent.is_symlink():
        raise ValueError("Private output root must be a real directory")
    allowed.mkdir(mode=0o700, exist_ok=True)
    if allowed.resolve() != allowed:
        raise ValueError("Private output root must not traverse symlinks")
    return allowed


def export(root: Path, dataset: str, output: Path):
    allowed = private_directory(root)
    output = output.absolute()
    names = {f"dataset-{dataset.lower()}-{suffix}" for suffix in ("final", "repeat")}
    if dataset not in APPROVED or output.parent != allowed or output.name not in names:
        raise ValueError("Unapproved private output")
    if output.exists() or output.is_symlink():
        raise FileExistsError("Never overwrite evidence or follow output symlinks")
    payloads, receipt = build(root, dataset)
    output.mkdir(mode=0o700)
    for name, content in sorted(payloads.items()):
        with (output / name).open("xb") as stream:
            stream.write(content)
    return {
        "dataset": dataset,
        "manifest_sha256": sha(payloads["manifest.json"]),
        "asset_bytes": {k: len(v) for k, v in sorted(payloads.items())},
        **receipt,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=SLOTS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    args = parser.parse_args()
    allowed = private_directory(ROOT)
    if (
        args.audit_output.absolute().parent != allowed
        or args.audit_output.exists()
        or args.audit_output.is_symlink()
    ):
        raise ValueError("Audit must be a new private receipt")
    receipt = export(ROOT, args.dataset, args.output)
    with args.audit_output.open("x") as stream:
        json.dump(receipt, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps({"dataset": receipt["dataset"], "manifest_sha256": receipt["manifest_sha256"]})
    )


if __name__ == "__main__":
    main()
