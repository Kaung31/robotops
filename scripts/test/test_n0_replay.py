"""Offline P2 schema, provenance, coordinate, privacy, integrity and budget regressions."""

import copy
import gzip
import json
import math
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_n0_replay import audit, close_transform, compose  # noqa: E402
from export_n0_replay import (  # noqa: E402
    REPORT,
    ROOT,
    bracket,
    build,
    canonical,
    decompress_bounded,
    export,
    pgm,
    sanitize_range,
    segments,
    sha,
    source_bytes,
    validate_bundle,
    validate_clock,
    verify_sources,
)
from replay_models import (  # noqa: E402
    Manifest,
    PoseChunk,
    ScanChunk,
    Transform,
    offset_us,
    pixel_center,
    three_quaternion,
    three_vector,
    threshold_status,
)


@pytest.fixture(scope="module")
def bundle():
    return build(ROOT)[0]


def rehash_manifest(payloads, manifest):
    payloads["manifest.json"] = canonical(manifest)
    payloads["dataset.sha256"] = (sha(payloads["manifest.json"]) + "  manifest.json\n").encode()


def test_complete_independent_decoded_source_audit(bundle):
    result = audit(ROOT, bundle)
    assert result["pose_samples_compared"] > 300
    assert result["scan_samples_compared"] == 98
    assert result["indexed_ranges_compared"] == 98 * 90
    assert len(result["source_tf_unavailable_scan_stamps_ns"]) == 5
    assert result["metrics_exact_source_pointer_comparison"]


def test_repeat_build_byte_identical(bundle):
    assert build(ROOT)[0] == bundle


def test_coverage_is_not_full_mission_and_final_pose_not_animated(bundle):
    manifest = validate_bundle(bundle)
    assert manifest.time.mission_start_ns == "4031000000"
    assert manifest.time.mission_end_ns == "24699000000"
    assert manifest.time.recorded_start_ns == "4748000000"
    assert manifest.time.recorded_end_ns == "24347000000"
    assert not manifest.coverage.full_mission_replay
    assert manifest.coverage.unavailable_scan_stamps_ns == [
        str(t) for t in range(4_800_000_000, 5_300_000_000, 100_000_000)
    ]
    assert {g.reason for g in manifest.coverage.gaps} >= {
        "UNRECORDED_HEAD",
        "UNRECORDED_TAIL",
        "TF_UNAVAILABLE",
    }
    assert manifest.navigation_events == []
    assert not manifest.original_validation.final_pose_is_playback_sample
    assert manifest.original_validation.final_pose_ros_ns == "24780000000"


@pytest.mark.parametrize(
    "defect",
    [
        "unknown_version",
        "extra_field",
        "unsafe_path",
        "backslash",
        "url",
        "time_integer",
        "time_float",
        "unknown_kind",
        "invalid_metric_unit",
        "missing_metric",
        "segment_reset",
        "false_verdict",
        "invented_event",
    ],
)
def test_schema_rejects_semantic_tampering(bundle, defect):
    payloads = copy.deepcopy(bundle)
    m = json.loads(payloads["manifest.json"])
    if defect == "unknown_version":
        m["schema_version"] = 2
    if defect == "extra_field":
        m["private_token"] = "secret"
    if defect == "unsafe_path":
        m["assets"][0]["path"] = "../map.pgm.gz"
    if defect == "backslash":
        m["assets"][0]["path"] = "a\\map.pgm.gz"
    if defect == "url":
        m["assets"][0]["path"] = "https://example.com/map.pgm.gz"
    if defect == "time_integer":
        m["time"]["mission_start_ns"] = 4031000000
    if defect == "time_float":
        m["time"]["mission_start_ns"] = "4.031e9"
    if defect == "unknown_kind":
        m["kind"] = "CampaignReport"
    if defect == "invalid_metric_unit":
        m["metrics"][0]["unit"] = "rad"
    if defect == "missing_metric":
        m["metrics"].pop()
    if defect == "segment_reset":
        m["segments"][0]["end_ros_ns"] = "0"
    if defect == "false_verdict":
        m["original_validation"]["contact_verdict"] = "COLLISION_FREE"
    if defect == "invented_event":
        m["navigation_events"] = [{"kind": "nav2_started"}]
    rehash_manifest(payloads, m)
    with pytest.raises((ValueError, ValidationError)):
        validate_bundle(payloads)


@pytest.mark.parametrize("defect", ["manifest", "asset", "missing", "extra", "wrong_size"])
def test_hash_size_and_asset_list_integrity(bundle, defect):
    payloads = copy.deepcopy(bundle)
    if defect == "manifest":
        payloads["manifest.json"] += b" "
    if defect == "asset":
        payloads["map.pgm.gz"] += b"x"
    if defect == "missing":
        payloads.pop("map.pgm.gz")
    if defect == "extra":
        payloads["unapproved.json"] = b"{}"
    if defect == "wrong_size":
        m = json.loads(payloads["manifest.json"])
        m["assets"][0]["bytes"] += 1
        rehash_manifest(payloads, m)
    with pytest.raises((ValueError, ValidationError)):
        validate_bundle(payloads)


def test_allowlist_excludes_known_private_source_fields(bundle):
    data = b"".join(gzip.decompress(v) if k.endswith(".gz") else v for k, v in bundle.items())
    for token in (
        b"/home/",
        b"kai",
        b"127.0.0.1",
        b"artifact_directory",
        b"manifest_path",
        b"accepted_utc",
        b"Nav2 valid-path qualification",
        b"password",
        b"token",
    ):
        assert token not in data
    # Original source really contains excluded content; this is not an empty fixture check.
    assert b"/home/kai/" in (ROOT / REPORT).read_bytes()
    assert (
        json.loads(bundle["manifest.json"])["publication_review"]
        == "PRIVATE_NOT_APPROVED_FOR_UPLOAD"
    )


def test_size_and_sampling_budgets(bundle):
    manifest = validate_bundle(bundle)
    assert len(bundle["manifest.json"]) + len(bundle["map.pgm.gz"]) <= 250 * 1024
    assert sum(len(v) for v in bundle.values()) <= 5 * 1024 * 1024
    assert all(a.bytes <= 1024 * 1024 for a in manifest.assets)
    poses = [
        p
        for a in manifest.assets
        if a.kind == "poses"
        for p in json.loads(gzip.decompress(bundle[a.path]))["samples"]
    ]
    assert all(
        int(b["ros_ns"]) - int(a["ros_ns"]) >= 50_000_000
        for a, b in zip(poses, poses[1:], strict=False)
    )


def test_exact_ns_above_javascript_safe_integer():
    stamp = 1_791_722_000_123_456_789
    assert offset_us(stamp, stamp - 12_345) == 12
    assert str(stamp) != str(int(float(stamp)))
    with pytest.raises(ValueError):
        offset_us(2**63, 0)
    with pytest.raises(ValueError):
        offset_us(1, 2)


@pytest.mark.parametrize("clocks", [[], [1, 1], [2, 1], [1, 100_000_002], [1, 1.5]])
def test_clock_pause_reset_missing_and_wrong_type_fail_closed(clocks):
    with pytest.raises(ValueError):
        validate_clock(clocks)


def test_tf_brackets_no_extrapolation_or_large_gap():
    data = [(100, "a"), (200, "b")]
    assert bracket(data, 100, 100) == ["a"]
    assert bracket(data, 150, 100) == ["a", "b"]
    for t in (99, 201):
        with pytest.raises(ValueError):
            bracket(data, t, 100)
    with pytest.raises(ValueError):
        bracket(data, 150, 99)
    with pytest.raises(ValueError):
        bracket([(200, "a"), (100, "b")], 150, 100)


def test_pose_gaps_and_reset_never_join():
    result = segments([100, 150, 400, 450], 100, 100)
    assert len(result) == 2
    assert result[0]["end_ros_ns"] == "150"
    for stamps in ([100, 100], [150, 100]):
        with pytest.raises(ValueError):
            segments(stamps, 100, 100)


def test_map_corners_origin_and_positive_yaw():
    assert pixel_center(0, 1, 3, 2, 1.0, [0, 0, 0]) == [0.5, 0.5]
    assert pixel_center(2, 0, 3, 2, 1.0, [0, 0, 0]) == [2.5, 1.5]
    assert pixel_center(0, 1, 3, 2, 1.0, [0, 0, math.pi / 2]) == pytest.approx([-0.5, 0.5])
    with pytest.raises(ValueError):
        pixel_center(3, 0, 3, 2, 1.0, [0, 0, 0])


def test_tf_composition_laser_forward_and_three_rotation():
    a = {
        "position": [1.0, 2.0, 0.0],
        "quaternion": [0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)],
    }
    b = {"position": [1.0, 0.0, 0.0], "quaternion": [0.0, 0.0, 0.0, 1.0]}
    c = compose(a, b)
    assert c["position"] == pytest.approx([1.0, 3.0, 0.0])
    assert three_vector(c["position"]) == pytest.approx([1.0, 0.0, -3.0])
    assert three_quaternion(a["quaternion"]) == pytest.approx(
        [0.0, math.sin(math.pi / 4), 0.0, math.cos(math.pi / 4)]
    )
    with pytest.raises(ValidationError):
        Transform(position=[0.0] * 3, quaternion=[0.0] * 4)


def test_quaternion_sign_equivalence_preserves_rotation_checks():
    a = {"position": [0.0, 0.0, 0.0], "quaternion": [0.0, 0.0, 0.0, 1.0]}
    b = {"position": [0.0, 0.0, 0.0], "quaternion": [0.0, 0.0, 0.0, -1.0]}
    close_transform(a, b)
    b["quaternion"] = [0.0, 0.0, 1.0, 0.0]
    with pytest.raises(ValueError):
        close_transform(a, b)


@pytest.mark.parametrize(
    "value,reason",
    [
        (1.0, "valid"),
        (math.inf, "no_return"),
        (math.nan, "invalid_nan"),
        (-math.inf, "out_of_bounds"),
        (-1.0, "out_of_bounds"),
    ],
)
def test_invalid_rays_are_null_with_explicit_reason(value, reason):
    encoded, label = sanitize_range(value, 0.1, 5.0)
    assert label == reason
    assert (encoded is None) == (reason != "valid")


@pytest.mark.parametrize("threshold", [-1, math.nan, math.inf, True])
def test_invalid_analytical_thresholds_are_input_errors(threshold):
    with pytest.raises(ValueError):
        threshold_status(1.0, threshold)


def test_threshold_boundary_quality_and_original_verdict_immutability(bundle):
    original = copy.deepcopy(bundle)
    assert threshold_status(1.0, 1.0) == "PASS"
    assert threshold_status(1.0, 0.999) == "FAIL"
    assert threshold_status(1.0, 1.001) == "PASS"
    assert threshold_status(None, 10.0) == "UNKNOWN"
    assert threshold_status(1.0, 10.0, evidence_valid=False) == "UNKNOWN"
    assert abs(
        math.atan2(math.sin(math.pi - (-math.pi)), math.cos(math.pi - (-math.pi)))
    ) == pytest.approx(0.0)
    assert original == bundle


def test_unsafe_sources_and_output_never_overwrite(tmp_path):
    path = tmp_path / "source"
    path.write_bytes(b"private")
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(ValueError):
        source_bytes(tmp_path, link)
    with pytest.raises(ValueError):
        export(ROOT, tmp_path / "public")
    with pytest.raises(FileExistsError):
        export(ROOT, ROOT / "artifacts/p2-n0-20261011/dataset")
    (tmp_path / REPORT).parent.mkdir(parents=True)
    (tmp_path / REPORT).write_text("{}")
    with pytest.raises(ValueError, match="pin mismatch"):
        verify_sources(tmp_path)


def test_pgm_sanitization_and_bounded_decompression():
    assert pgm(b"P5\n# private source comment\n2 1\n255\n\x00\xff")[3] == b"P5\n2 1\n255\n\x00\xff"
    with pytest.raises(ValueError):
        pgm(b"P5\n2 1\n255\n\x00")
    with pytest.raises(ValueError):
        decompress_bounded(gzip.compress(b"x" * (8 * 1024 * 1024 + 1), mtime=0))
    with pytest.raises(ValueError):
        decompress_bounded(gzip.compress(b"x", mtime=0) + gzip.compress(b"y", mtime=0))


def test_checked_in_schema_matches_models():
    expected = {
        "schema_version": 1,
        "schemas": {
            "manifest": Manifest.model_json_schema(),
            "poses": PoseChunk.model_json_schema(),
            "scans": ScanChunk.model_json_schema(),
        },
    }
    assert json.loads((ROOT / "scripts/replay-schema-v1.json").read_bytes()) == expected
