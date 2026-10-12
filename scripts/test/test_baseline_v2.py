"""Private v2 qualification and rejection tests; never mutate historical evidence."""

import copy
import gzip
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_baseline_v2 as v2
from audit_baseline_v2 import audit
from export_n0_replay import ROOT, bracket, canonical, offset_us, sha, validate_clock
from replay_models import Manifest, pixel_center
from replay_v2_models import OriginalV2


@pytest.fixture(scope="module", params=["N0", "N2"])
def bundle(request):
    return request.param, v2.build(ROOT, request.param)[0]


def rehash(payloads, m):
    payloads["manifest.json"] = canonical(m)
    payloads["dataset.sha256"] = (sha(payloads["manifest.json"]) + "  manifest.json\n").encode()


def test_independent_source_correspondence(bundle):
    name, payloads = bundle
    r = audit(ROOT, payloads)
    assert r["dataset"] == name and r["map_cells_compared"] == 31641
    assert r["mission_action_status_compared"]
    assert r["pose_samples_compared"] > 300 and r["scan_samples_compared"] == (
        98 if name == "N0" else 99
    )
    assert r["indexed_ranges_compared"] == r["scan_samples_compared"] * 90
    assert len(r["source_tf_unavailable_scan_stamps_ns"]) == 5


def test_determinism(bundle):
    name, payloads = bundle
    assert v2.build(ROOT, name)[0] == payloads


def test_source_selection(bundle):
    name, payloads = bundle
    m = v2.validate_bundle(payloads)
    report, locations, runner = v2.verify_sources(ROOT, name)
    assert m.source_identity.trial_id == v2.APPROVED[name]["trial"]
    assert m.source_identity.run_id == v2.APPROVED[name]["run"]
    assert len(report["campaign"]["trials"]) == v2.APPROVED[name]["count"]
    assert runner["trials"][0]["run_id"] == m.source_identity.run_id
    assert sha(locations["mcap"][0].read_bytes()) == v2.APPROVED[name]["mcap_sha"]


@pytest.mark.parametrize("index", [1, -1, True, "0", None])
def test_wrong_trial_index(index):
    with pytest.raises(ValueError):
        v2.verify_sources(ROOT, "N2", trial_index=index)


@pytest.mark.parametrize("defect", ["run", "trial", "report_sha", "mcap_sha"])
def test_wrong_source_identity(monkeypatch, defect):
    pins = copy.deepcopy(v2.APPROVED)
    pins["N2"][defect] = "0" * 64
    monkeypatch.setattr(v2, "APPROVED", pins)
    with pytest.raises(ValueError):
        v2.verify_sources(ROOT, "N2")


def test_tampered_source_bytes(monkeypatch):
    original = v2.source_bytes
    monkeypatch.setattr(
        v2,
        "source_bytes",
        lambda root, path: original(root, path) + b" "
        if path.name.endswith("report.json")
        else original(root, path),
    )
    with pytest.raises(ValueError):
        v2.verify_sources(ROOT, "N2")


@pytest.mark.parametrize(
    "status,runner,quality",
    [
        (4, 4, "AVAILABLE"),
        (None, 4, "MISSING"),
        (4, None, "MISSING"),
        ("4", 4, "INVALID"),
        (True, 4, "INVALID"),
        (4.0, 4, "INVALID"),
        (-1, 4, "INVALID"),
        (7, 4, "INVALID"),
        (5, 4, "CONFLICT"),
        (5, 5, "CONFLICT"),
    ],
)
def test_action_evidence(status, runner, quality, bundle):
    _, p = bundle
    m = json.loads(p["manifest.json"])
    o = m["original_validation"]
    o.update(v2.mission_action(status, runner))
    parsed = OriginalV2.model_validate(o)
    assert parsed.action_status_reason == quality
    assert parsed.action_status == (4 if quality == "AVAILABLE" else None)
    assert parsed.mission_action.scope == "SAVED_MISSION_ACTION_RESULT_SNAPSHOT"
    assert parsed.mission_action.action_type == "robotops_interfaces/action/ExecuteMission"
    assert parsed.mission_action.owner == "mission_manager"
    assert parsed.mission_action.observer == "experiment_runner"
    assert not parsed.mission_action.recorded_action_stream
    assert parsed.mission_action.event_time_ns is None


def test_originals_and_coverage(bundle):
    name, p = bundle
    m = v2.validate_bundle(p)
    r = json.loads((ROOT / v2.APPROVED[name]["report"]).read_bytes())
    e = r["campaign"]["trials"][0]["evidence"]
    for metric in m.metrics:
        value = r
        for part in metric.pointer.strip("/").split("/"):
            value = value[int(part)] if isinstance(value, list) else value[part]
        assert metric.value == value
    assert m.original_validation.pose_policy.model_dump() == e["validation"]["policy"]
    assert m.original_validation.pose_verdict == e["validation"]["verdict"]
    assert m.original_validation.contact_verdict == e["collision"]["verdict"]
    assert m.original_validation.ros_outcome == e["outcome"]
    assert {g.reason for g in m.coverage.gaps} >= {
        "UNRECORDED_HEAD",
        "UNRECORDED_TAIL",
        "TF_UNAVAILABLE",
    }
    assert all(not s.interpolate_across_segments for s in m.segments)
    assert m.navigation_events == [] and not m.original_validation.final_pose_is_playback_sample
    assert m.conditions.classification == "OBSERVATIONAL_REPEATED_BASELINES"
    assert m.conditions.software_revision is None and m.conditions.random_seed is None


@pytest.mark.parametrize(
    "defect",
    [
        "version",
        "extra",
        "identity",
        "status",
        "scope",
        "event",
        "metric",
        "goal",
        "conditions",
        "source",
        "time",
        "gap",
        "path",
        "duplicate_source",
        "missing_source",
        "policy",
    ],
)
def test_manifest_rejections(bundle, defect):
    _, p = bundle
    p = copy.deepcopy(p)
    m = json.loads(p["manifest.json"])
    if defect == "version":
        m["schema_version"] = 1
    elif defect == "extra":
        m["private_path"] = "/home/private"
    elif defect == "identity":
        m["source_identity"]["run_id"] = "wrong"
    elif defect == "status":
        m["original_validation"]["action_status"] = True
    elif defect == "scope":
        m["original_validation"]["mission_action"]["scope"] = "NAV2_EVENT"
    elif defect == "event":
        m["navigation_events"] = [{"event": "started"}]
    elif defect == "metric":
        m["metrics"][0]["unit"] = "rad"
    elif defect == "goal":
        m["conditions"]["waypoints"][-1]["x"] = 1.0
    elif defect == "conditions":
        m["conditions"]["controlled_algorithm_ab"] = True
    elif defect == "source":
        m["sources"][0]["sha256"] = "0" * 64
    elif defect == "time":
        m["time"]["recorded_start_ns"] = int(m["time"]["recorded_start_ns"])
    elif defect == "gap":
        m["segments"][0]["end_ros_ns"] = "0"
    elif defect == "path":
        m["assets"][0]["path"] = "https://example.com/map.gz"
    elif defect == "duplicate_source":
        m["sources"].append(m["sources"][0])
    elif defect == "missing_source":
        m["sources"].pop()
    elif defect == "policy":
        m["original_validation"]["pose_policy"]["xy_tolerance_m"] = "0.2"
    rehash(p, m)
    with pytest.raises((ValueError, ValidationError)):
        v2.validate_bundle(p)


@pytest.mark.parametrize("defect", ["asset", "manifest", "missing", "extra", "oversize"])
def test_asset_rejections(bundle, defect):
    _, p = bundle
    p = copy.deepcopy(p)
    if defect == "asset":
        p["map.pgm.gz"] += b"x"
    elif defect == "manifest":
        p["manifest.json"] += b" "
    elif defect == "missing":
        p.pop("map.pgm.gz")
    elif defect == "extra":
        p["raw.mcap"] = b"x"
    elif defect == "oversize":
        m = json.loads(p["manifest.json"])
        m["assets"][0]["bytes"] = 1024 * 1024 + 1
        rehash(p, m)
    with pytest.raises(ValueError):
        v2.validate_bundle(p)


def test_privacy_size(bundle):
    _, p = bundle
    m = v2.validate_bundle(p)
    data = b"".join(gzip.decompress(v) if k.endswith(".gz") else v for k, v in p.items())
    for token in (
        b"/home/",
        b"kai",
        b"127.0.0.1",
        b"http:",
        b"https:",
        b"password",
        b"accepted_utc",
        b"manifest_path",
        b"artifact_directory",
    ):
        assert token not in data
    assert sum(map(len, p.values())) <= 5 * 1024 * 1024
    assert len(p["manifest.json"]) + len(p["map.pgm.gz"]) <= 250 * 1024
    assert all(a.bytes <= 1024 * 1024 for a in m.assets)
    assert m.publication_review == "PRIVATE_NOT_APPROVED_FOR_UPLOAD"


def test_v1_preserved_and_strictly_separate(bundle):
    _, p = bundle
    with pytest.raises(ValidationError):
        Manifest.model_validate_json(p["manifest.json"])
    folder = ROOT / "artifacts/p2-n0-20261011/dataset-final"
    assert (
        sha((folder / "manifest.json").read_bytes())
        == "755424dae361089465281af6706e51852ed1aa221cffe9504434b0fb6419aab4"
    )
    legacy = Manifest.model_validate_json((folder / "manifest.json").read_bytes())
    assert legacy.original_validation.action_status is None
    if bundle[0] == "N0":
        for name, content in p.items():
            if name not in ("manifest.json", "dataset.sha256"):
                assert content == (folder / name).read_bytes()


def test_clock_tf_coordinate_boundaries():
    for clock in ([1, 1], [2, 1], [1, 200000000]):
        with pytest.raises(ValueError):
            validate_clock(clock)
    assert offset_us(1791722000123456789, 1791722000123444444) == 12
    with pytest.raises(ValueError):
        bracket([(100, {}), (400000000, {})], 200, 250000000)
    assert pixel_center(0, 0, 199, 159, 0.05, [-4.967, -3.969, 0]) == pytest.approx(
        [-4.942, 3.956]
    )


def test_no_historical_output_or_unapproved_dataset(tmp_path):
    with pytest.raises(ValueError):
        v2.export(ROOT, "N2", tmp_path / "dataset-n2-final")
    with pytest.raises(ValueError):
        v2.build(ROOT, "N3")


@pytest.mark.parametrize(
    "filename", ["metadata.json", "manifest.json", "metadata.yaml", "telemetry_0.mcap"]
)
def test_tampered_bound_sources(monkeypatch, filename):
    original = v2.source_bytes

    def read(root, path):
        value = original(root, path)
        return value + b" " if path.name == filename else value

    monkeypatch.setattr(v2, "source_bytes", read)
    with pytest.raises(ValueError):
        v2.verify_sources(ROOT, "N2")


@pytest.mark.parametrize("kind", ["poses", "scans", "map", "metric"])
def test_independent_audit_rejects_rehashed_data(bundle, kind):
    _, payloads = bundle
    payloads = copy.deepcopy(payloads)
    m = json.loads(payloads["manifest.json"])
    if kind == "metric":
        m["metrics"][0]["value"] += 1
    else:
        asset = next(a for a in m["assets"] if a["kind"] == kind)
        raw = gzip.decompress(payloads[asset["path"]])
        if kind == "map":
            raw = raw[:-1] + bytes([0 if raw[-1] else 254])
        else:
            chunk = json.loads(raw)
            if kind == "poses":
                next(r for r in chunk["samples"] if r["transform"])["transform"]["position"][
                    0
                ] += 1
            else:
                chunk["samples"][0]["ranges_m"][0] += 0.001
            raw = canonical(chunk)
        payloads[asset["path"]] = gzip.compress(raw, mtime=0)
        asset["sha256"] = sha(payloads[asset["path"]])
        asset["bytes"] = len(payloads[asset["path"]])
    rehash(payloads, m)
    with pytest.raises(ValueError):
        audit(ROOT, payloads)


def test_failed_build_creates_no_output(monkeypatch, tmp_path):
    parent = tmp_path / "artifacts/p4b-export-20261011"
    parent.mkdir(parents=True)
    target = parent / "dataset-n2-repeat"
    assert not target.exists()

    def fail(*args):
        raise ValueError("Evidence unavailable")

    monkeypatch.setattr(v2, "build", fail)
    with pytest.raises(ValueError):
        v2.export(tmp_path, "N2", target)
    assert not target.exists()


def test_schema_artifact_matches_models():
    from replay_models import PoseChunk, ScanChunk
    from replay_v2_models import ManifestV2

    expected = {c.__name__: c.model_json_schema() for c in (ManifestV2, PoseChunk, ScanChunk)}
    assert json.loads((ROOT / "scripts/replay-schema-v2.json").read_text()) == expected


def test_existing_output_is_never_overwritten(tmp_path):
    parent = tmp_path / "artifacts/p4b-export-20261011"
    target = parent / "dataset-n2-final"
    target.mkdir(parents=True)
    marker = target / "preserve"
    marker.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        v2.export(tmp_path, "N2", target)
    assert marker.read_bytes() == b"original"


def test_output_parent_symlink_rejected(tmp_path):
    (tmp_path / "artifacts").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = tmp_path / "artifacts/p4b-export-20261011"
    parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(FileExistsError):
        v2.export(tmp_path, "N2", parent / "dataset-n2-final")
    assert list(outside.iterdir()) == []
