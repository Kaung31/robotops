"""Reports preserve experimental outcomes while auditing durable local evidence."""

import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from robotops_backend.app import create_app
from robotops_backend.campaigns.models import CampaignDefinition, TrialEvidence
from robotops_backend.campaigns.reports import ArtifactReader, build_report, digest, render_html
from robotops_backend.campaigns.repository import (
    CampaignConflict,
    CampaignStorageError,
    SQLiteCampaignRepository,
)
from robotops_backend.orchestrator import StackOrchestrator


@pytest.fixture
def completed(tmp_path):
    root = tmp_path / "artifacts"
    root.mkdir()
    repo = SQLiteCampaignRepository(root / "campaigns.sqlite3")
    repo.initialize()
    record, _ = repo.create(
        CampaignDefinition.model_validate(
            dict(
                name='<script>alert("x")</script>',
                world="mapping_lab",
                map_id="lab",
                profiles=["navfn_rpp"],
                repetitions=1,
                waypoints=[dict(x=0, y=0, yaw=0)],
                start=dict(x=0, y=0, yaw=0),
            )
        )
    )
    record = repo.claim(record.id, "owner")
    trial = record.trials[0]
    directory = root / "run"
    (directory / "telemetry").mkdir(parents=True)
    files = {
        "metadata.json": b"{}",
        "result.json": b"{}",
        "metadata.yaml": b"bag",
        "telemetry/test.mcap": b"MCAP",
    }
    import hashlib

    hashes = {}
    for name, data in files.items():
        path = directory / ("telemetry/metadata.yaml" if name == "metadata.yaml" else name)
        path.write_bytes(data)
        hashes[name] = hashlib.sha256(data).hexdigest()
    contact = root / "contacts.json"
    contact.write_text('{"frames": []}')
    config = dict(execution_context=dict(campaign_id=record.id, trial_id=trial.id))
    parameters = {"controller": "value"}
    evidence = TrialEvidence(
        manifest_path=str(root / "manifest.json"),
        experiment_id="experiment",
        mission_run_id="run",
        outcome="succeeded",
        metrics=dict(mission_ros_seconds=10, odom_path_metres=2),
        validation=dict(
            verdict="POSE_REJECTED",
            reasons=["Wrong pose"],
            provenance=dict(
                state="confirmed",
                config_sha256=digest(config),
                parameters_sha256=digest(parameters),
                artifact_sha256=hashes,
            ),
        ),
        collision=dict(
            verdict="CONTACT_DETECTED",
            contacts=[dict(body_a="robot", body_b="wall")],
            artifact=dict(
                path=str(contact), sha256=hashlib.sha256(contact.read_bytes()).hexdigest()
            ),
        ),
    )
    trial.state, trial.evidence = "succeeded", evidence
    record.state = "completed"
    record.termination_confirmed = record.cleanup_confirmed = True
    record = repo.save_owned(record, "owner", "completed", release=True)
    manifest = dict(
        experiment_id="experiment",
        config=config,
        trials=[
            dict(
                run_id="run",
                outcome=evidence.outcome,
                metrics=evidence.metrics,
                validation=evidence.validation,
                collision=evidence.collision,
                parameters=parameters,
                artifact_directory=str(directory),
            )
        ],
    )
    Path(evidence.manifest_path).write_text(json.dumps(manifest))
    return repo, record, root


def test_snapshot_persistence_idempotency_and_separate_results(completed):
    repo, record, root = completed
    report = repo.save_report(build_report(record, root))
    assert report.integrity[0].state == "VERIFIED"
    assert report.profiles[0].ros_success_rate == 1
    assert report.profiles[0].pose_verdicts == {"POSE_REJECTED": 1}
    assert report.profiles[0].contact_verdicts == {"CONTACT_DETECTED": 1}
    assert report.profiles[0].duration_seconds.samples == 1
    assert repo.save_report(build_report(record, root)) == report
    reopened = SQLiteCampaignRepository(repo.path)
    reopened.initialize()
    assert reopened.get_report(record.id, report.id) == report
    assert reopened.get(record.id) == record and reopened.lease() is None
    assert reopened.reports(record.id) == [report]
    with pytest.raises(KeyError):
        reopened.get_report("another-campaign", report.id)


def test_parallel_generations_reuse_one_report(completed):
    repo, record, root = completed
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(lambda _: repo.save_report(build_report(record, root)), range(8)))
    assert all(r == reports[0] for r in reports)
    assert len(repo.reports(record.id)) == 1


@pytest.mark.parametrize(
    "change", ["missing", "tamper", "manifest", "config", "parameter", "traversal", "fingerprint"]
)
def test_artifact_failures_preserve_outcome_and_original_snapshot(completed, change):
    repo, record, root = completed
    old = repo.save_report(build_report(record, root))
    if change == "missing":
        (root / "run/telemetry/test.mcap").unlink()
    elif change == "tamper":
        (root / "contacts.json").write_text("tampered")
    else:
        manifest_path = root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if change == "manifest":
            manifest["trials"][0]["outcome"] = "failed"
        elif change == "config":
            manifest["config"]["extra"] = True
        elif change == "parameter":
            manifest["trials"][0]["parameters"]["extra"] = True
        elif change == "traversal":
            manifest["trials"][0]["artifact_directory"] = str(root / "../outside")
        elif change == "fingerprint":
            record.trials[0].evidence.validation["provenance"]["artifact_sha256"][
                "result.json"
            ] = None
            manifest["trials"][0]["validation"] = record.trials[0].evidence.validation
        manifest_path.write_text(json.dumps(manifest))
    report = build_report(record, root)
    assert report.integrity[0].state == "ISSUES"
    assert report.id != old.id
    assert report.campaign.trials[0].evidence.outcome == "succeeded"
    assert repo.get_report(record.id, old.id) == old


def test_confined_reader_symlinks_special_files_and_budget(completed, tmp_path):
    _, _, root = completed
    outside = tmp_path / "outside"
    outside.write_text("private")
    (root / "link").symlink_to(outside)
    (root / "directory").symlink_to(tmp_path, target_is_directory=True)
    os.mkfifo(root / "pipe")
    reader = ArtifactReader(root)
    for reference in (
        outside,
        root / "link",
        root / "directory/outside",
        root / "pipe",
        root / "../outside",
    ):
        check, _ = reader.check(str(reference))
        assert check.state == "UNTRUSTED" and check.actual_sha256 is None
    check, _ = ArtifactReader(root, budget=1).check(str(root / "contacts.json"))
    assert check.state == "UNAVAILABLE" and "budget" in check.reason


@pytest.mark.parametrize("state", ["draft", "queued", "running", "canceling"])
def test_active_campaigns_cannot_generate_or_change_execution(completed, state):
    repo, record, root = completed
    record.state = state
    with pytest.raises(CampaignConflict):
        build_report(record, root)
    assert repo.get(record.id).state == "completed"


@pytest.mark.parametrize("state", ["failed", "canceled", "interrupted"])
def test_partial_and_historical_evidence_is_not_upgraded(completed, state):
    _, record, root = completed
    record.state = state
    record.trials[0].state = state if state != "failed" else "failed"
    record.trials[0].evidence = None
    report = build_report(record, root)
    assert report.integrity[0].state == "UNAVAILABLE"
    assert report.profiles[0].ros_success_rate == (None if state == "canceled" else 0)
    assert report.profiles[0].contact_verdicts == {"UNVALIDATED": 1}
    assert report.profiles[0].duration_seconds.mean is None


def test_generation_race_and_corrupt_saved_report(completed):
    repo, record, root = completed
    report = build_report(record, root)
    record.error = "changed"
    with sqlite3.connect(repo.path) as db:
        db.execute(
            "UPDATE campaigns SET record=? WHERE id=?", (record.model_dump_json(), record.id)
        )
    with pytest.raises(CampaignConflict, match="changed"):
        repo.save_report(report)
    current_report = repo.save_report(build_report(record, root))
    with sqlite3.connect(repo.path) as db:
        payload = current_report.model_dump(mode="json")
        payload["limitations"] = []
        db.execute("UPDATE campaign_reports SET payload=?", (json.dumps(payload),))
    with pytest.raises(CampaignStorageError):
        repo.get_report(record.id, current_report.id)


def test_migration_from_v2_preserves_campaign_events_and_lease(completed):
    repo, record, _ = completed
    with sqlite3.connect(repo.path) as db:
        db.execute("DROP TABLE campaign_reports")
        db.execute("PRAGMA user_version=2")
    repo.initialize()
    assert repo.get(record.id) == record
    assert len(repo.events(record.id)) == 3
    assert repo.lease() is None
    assert repo.reports(record.id) == []
    with sqlite3.connect(repo.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3


def test_report_api_downloads_and_escaping(completed, tmp_path, monkeypatch):
    repo, record, _ = completed
    monkeypatch.setenv("ROBOTOPS_REPO_ROOT", str(tmp_path))
    app = create_app(orchestrator=StackOrchestrator(repo_root=tmp_path), campaign_repository=repo)
    base = f"/api/v1/campaigns/{record.id}/reports"
    with TestClient(app) as client:
        assert client.get(base).json() == []
        response = client.post(base)
        assert response.status_code == 200
        report = response.json()
        assert report["integrity"][0]["state"] == "VERIFIED"
        assert client.post(base).json() == report
        assert client.get(base + "/" + report["id"]).json() == report
        for format in ("json", "html"):
            download = client.get(base + "/" + report["id"] + "/download?format=" + format)
            assert download.status_code == 200
            assert "attachment" in download.headers["content-disposition"]
            if format == "html":
                assert "<script>" not in download.text
                assert "&lt;script&gt;" in download.text
                assert "CONTACT_DETECTED" in download.text
                assert "sandbox" in download.headers["content-security-policy"]
            else:
                assert download.json() == report
        assert client.get(base + "/" + report["id"] + "/download?format=pdf").status_code == 422
        assert client.get(base + "/absent").status_code == 404
        assert client.get("/api/v1/campaigns/absent/reports").status_code == 404
        assert repo.get(record.id) == record
        assert "&lt;script&gt;" in render_html(repo.get_report(record.id, report["id"]))
