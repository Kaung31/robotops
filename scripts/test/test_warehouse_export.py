"""Private Warehouse Benchmark v1 export tests; never mutate historical evidence."""

import copy
import gzip
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_warehouse_v1 as wh
from audit_warehouse_v1 import audit, privacy_scan
from export_n0_replay import ROOT, canonical, sha
from replay_models import PoseChunk, ScanChunk
from replay_v2_models import ManifestV2
from replay_warehouse_models import W03_TEARDOWN, WarehouseManifest

pytest.importorskip("rosbag2_py")
# launch_testing imports modules during collection hooks. Raising a module-level
# skip there aborts collection of sibling ordinary tests. Keep the same private
# availability condition as test marks so every ordinary fixture still collects.
pytestmark = pytest.mark.skipif(
    not (ROOT / wh.RESULTS).is_dir(), reason="private warehouse evidence unavailable"
)


@pytest.fixture(scope="module", params=["W01", "W03"])
def bundle(request):
    return request.param, wh.build(ROOT, request.param)[0]


def rehash(payloads, m):
    payloads["manifest.json"] = canonical(m)
    payloads["dataset.sha256"] = (sha(payloads["manifest.json"]) + "  manifest.json\n").encode()


def test_independent_source_audit(bundle):
    name, payloads = bundle
    r = audit(ROOT, payloads)
    assert r["dataset"] == name
    scans = sum(
        len(json.loads(gzip.decompress(v))["samples"])
        for k, v in payloads.items()
        if k.startswith("scans-")
    )
    assert r["pose_samples_compared"] > 2000 and r["scan_samples_compared"] == scans > 600
    assert r["indexed_ranges_compared"] == r["scan_samples_compared"] * 90
    assert r["full_mission_replay"] is True
    assert r["teardown"] == (
        "CRASHED_AFTER_EVIDENCE_FINALIZED" if name == "W03" else "NO_CHILD_FAILURE_LOGGED"
    )
    assert r["privacy"]["hits"] == 0


def test_determinism(bundle):
    name, payloads = bundle
    assert wh.build(ROOT, name)[0] == payloads


def test_originals_disclosures_and_window(bundle):
    name, payloads = bundle
    m = wh.validate_bundle(payloads)
    assert m.benchmark.qualification == "NOT_QUALIFIED"
    assert m.benchmark.execution_path == "NORMAL_BACKEND_CAMPAIGN"
    assert m.original_validation.pose_verdict == "POSE_VERIFIED"
    assert m.original_validation.contact_verdict == "NO_CONTACT_OBSERVED"
    assert m.recorder_loss.transport_lost_messages == 0
    crashed = name == "W03"
    assert (m.teardown.detail == W03_TEARDOWN) is crashed
    assert ("TEARDOWN_CRASH_AFTER_FINALIZATION" in m.limitations) is crashed
    assert m.teardown.original_campaign_cleanup_confirmed is True  # original record kept
    t = m.time
    assert int(t.recorded_start_ns) < int(t.mission_start_ns)
    assert int(t.mission_end_ns) <= int(t.recorded_end_ns) <= int(t.result_finalized_ns)
    duration = [x.value for x in m.metrics if x.name == "mission_ros_seconds"][0]
    assert (int(t.mission_end_ns) - int(t.mission_start_ns)) / 1e9 == duration
    assert {s.id: s.scope for s in m.sources}["launch_log"] == "private_log_not_exported"
    assert len(m.conditions.waypoints) == 5


def flip_teardown(m):
    # Internally consistent, but contradicts the reviewed launch log either way.
    if m["teardown"]["status"] == "NO_CHILD_FAILURE_LOGGED":
        m["teardown"].update(status="CRASHED_AFTER_EVIDENCE_FINALIZED", detail=W03_TEARDOWN)
        m["limitations"].append("TEARDOWN_CRASH_AFTER_FINALIZATION")
    else:
        m["teardown"].update(status="NO_CHILD_FAILURE_LOGGED", detail=None)
        m["limitations"].remove("TEARDOWN_CRASH_AFTER_FINALIZATION")


def mutate(payloads, change):
    p = copy.deepcopy(payloads)
    m = json.loads(p["manifest.json"])
    change(m)
    rehash(p, m)
    return p


@pytest.mark.parametrize(
    "change",
    [
        lambda m: m.update(schema_version=2),
        lambda m: m.update(dataset_id="W07"),
        lambda m: m.update(extra="/home/private"),
        lambda m: m["benchmark"].update(qualification="QUALIFIED"),
        lambda m: m["benchmark"].update(execution_path="W4_PERMISSION"),
        lambda m: m["benchmark"].update(slot="W02"),
        lambda m: flip_teardown(m),
        lambda m: m["limitations"].remove("EXPLORATORY_BENCHMARK_NOT_QUALIFIED"),
        lambda m: m["coverage"].update(full_mission_replay=False),
        lambda m: m["metrics"][0].update(unit="ms"),
        lambda m: m["metrics"][0].update(pointer="/graphics"),
        lambda m: m["metrics"][0].update(value=1.0) or m["metrics"].append(dict(m["metrics"][0])),
        lambda m: m["sources"][0].update(scope="private_log_not_exported"),
        lambda m: m["sources"][0].update(sha256="0" * 64),
        lambda m: m["source_identity"].update(run_id="0" * 32),
        lambda m: m["conditions"].update(
            profile="smac_dwb" if m["conditions"]["profile"] == "navfn_rpp" else "navfn_rpp"
        ),
        lambda m: m["recorder_loss"].update(transport_lost_messages=1),
        lambda m: m["original_report_limitations"].append("see /home/private/log"),
        lambda m: m["original_validation"].update(pose_verdict="POSE_REJECTED"),
        lambda m: m["time"].update(mission_end_ns=str(int(m["time"]["recorded_end_ns"]) + 1)),
        lambda m: m.update(publication_review="APPROVED"),
    ],
)
def test_manifest_rejections(bundle, change):
    _, payloads = bundle
    with pytest.raises((ValueError, ValidationError)):
        wh.validate_bundle(mutate(payloads, change))


def test_w03_disclosure_cannot_be_dropped():
    payloads = wh.build(ROOT, "W03")[0]

    def hide(m):
        m["teardown"].update(status="NO_CHILD_FAILURE_LOGGED", detail=None)
        m["limitations"].remove("TEARDOWN_CRASH_AFTER_FINALIZATION")

    with pytest.raises(ValueError, match="teardown"):
        wh.validate_bundle(mutate(payloads, hide))


@pytest.mark.parametrize("defect", ["bytes", "missing", "renamed", "extra"])
def test_asset_rejections(bundle, defect):
    _, payloads = bundle
    p = dict(payloads)
    if defect == "bytes":
        data = bytearray(p["poses-001.json.gz"])
        data[len(data) // 2] ^= 0xFF
        p["poses-001.json.gz"] = bytes(data)
    if defect == "missing":
        del p["scans-000.json.gz"]
    if defect == "renamed":
        p["poses-999.json.gz"] = p.pop("poses-001.json.gz")
    if defect == "extra":
        p["notes.txt"] = b"private"
    with pytest.raises(ValueError):
        wh.validate_bundle(p)


def test_privacy_and_size(bundle):
    _, payloads = bundle
    m = wh.validate_bundle(payloads)
    assert privacy_scan(payloads)["hits"] == 0
    data = b"".join(gzip.decompress(v) if k.endswith(".gz") else v for k, v in payloads.items())
    for token in (b"recorder.log", b"robot.log", b"orchestrator", b"execution_context"):
        assert token not in data
    assert sum(map(len, payloads.values())) <= 5 * 1024 * 1024
    assert len(payloads["manifest.json"]) + len(payloads["map.pgm.gz"]) <= 250 * 1024
    assert all(a.bytes <= 1024 * 1024 for a in m.assets)
    assert m.publication_review == "PRIVATE_NOT_APPROVED_FOR_UPLOAD"


def test_strictly_separate_from_baselines(bundle):
    _, payloads = bundle
    with pytest.raises(ValidationError):
        ManifestV2.model_validate_json(payloads["manifest.json"])


@pytest.mark.parametrize("name", ["report", "mcap", "launch_log", "recorder_log", "matrix"])
def test_tampered_source_is_rejected(monkeypatch, name):
    original = wh.source_bytes
    targets = {
        "report": "report-",
        "mcap": ".mcap",
        "launch_log": "-robot.log",
        "recorder_log": "recorder.log",
        "matrix": "matrix.json",
    }

    def tampered(root, path):
        data = original(root, path)
        return data + b"\n" if targets[name] in Path(path).name else data

    monkeypatch.setattr(wh, "source_bytes", tampered)
    with pytest.raises(ValueError):
        wh.verify_sources(ROOT, "W02")


def test_teardown_and_loss_assessment_rules():
    crash = (
        "[ERROR] [twist_mux-5]: process has died [pid 2, exit code -2, cmd 'x'].\n"
        "[gazebo_runner-2] XIO:  fatal IO error\n"
        "[ERROR] [gazebo_runner-2]: process has died [pid 3, exit code -11, cmd 'y'].\n"
    )
    assert wh.teardown_assessment(crash) == [("twist_mux-5", "-2"), ("gazebo_runner-2", "-11")]
    assert wh.teardown_assessment("[INFO] process has finished cleanly") == []
    with pytest.raises(ValueError):
        wh.teardown_assessment("[gazebo_runner-2] XIO:  fatal IO error\n")
    assert not wh.loss_assessment("Recording stopped")["accounting_complete"]
    assert wh.loss_assessment("".join(m + "\n" for m in wh.LOSS_MARKERS)) == dict(
        accounting_complete=True, transport_lost_messages=0, loss_reports=0
    )


def test_unapproved_dataset_and_output_rules(tmp_path):
    with pytest.raises(ValueError):
        wh.verify_sources(ROOT, "N0")
    with pytest.raises(ValueError):
        wh.export(ROOT, "W01", tmp_path / "dataset-w01-final")
    with pytest.raises(ValueError):
        wh.export(ROOT, "W01", ROOT / wh.OUTPUT_ROOT / "dataset-w02-final")


def test_existing_output_is_never_overwritten():
    existing = ROOT / wh.OUTPUT_ROOT / "dataset-w01-final"
    if not existing.exists():
        pytest.skip("private export not generated")
    before = {p.name: p.read_bytes() for p in existing.iterdir()}
    with pytest.raises(FileExistsError):
        wh.export(ROOT, "W01", existing)
    assert {p.name: p.read_bytes() for p in existing.iterdir()} == before


def test_schema_artifact_matches_models():
    expected = {
        c.__name__: c.model_json_schema() for c in (WarehouseManifest, PoseChunk, ScanChunk)
    }
    text = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    assert (ROOT / "scripts/replay-schema-warehouse-v1.json").read_text() == text
    assert (ROOT / "web/src/replay/schema-warehouse-v1.json").read_text() == text
