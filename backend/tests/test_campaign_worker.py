"""Ownership, cancellation and restart semantics without a robot."""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from robotops_backend.app import create_app
from robotops_backend.campaigns.models import CampaignDefinition, TrialEvidence
from robotops_backend.campaigns.ownership import RuntimeOwnership
from robotops_backend.campaigns.repository import CampaignConflict, SQLiteCampaignRepository
from robotops_backend.campaigns.runtime import CampaignInterrupted, TrialExecution
from robotops_backend.campaigns.service import CampaignService
from robotops_backend.state import TelemetryStore

from .test_campaigns import DefinitionOnlyOrchestrator, definition


class Runtime:
    def __init__(self, wait=False, confirmed=True, clean=True):
        self.wait = wait
        self.confirmed = confirmed
        self.clean = clean
        self.calls = []
        self.entered = asyncio.Event()
        self.preparing = False
        self.stops = 0

    def supports(self, mode):
        return mode == "sim"

    async def idle(self):
        return True

    async def prepare(self, definition, profile, canceled):
        if self.preparing:
            self.entered.set()
            while not await canceled():
                await asyncio.sleep(0.01)
            raise CampaignInterrupted("Canceled during startup")

    async def stop(self):
        self.stops += 1
        return self.clean

    async def execute(
        self, definition, trial, directory, baseline, map_baseline, canceled, lease_fd
    ):
        os.fstat(lease_fd)
        self.calls.append((trial.profile, baseline, map_baseline))
        self.entered.set()
        if self.wait:
            while not await canceled():
                await asyncio.sleep(0.01)
        return TrialExecution(
            TrialEvidence(
                manifest_path=str(directory / "manifest.json"),
                experiment_id=trial.id,
                outcome="canceled" if self.wait else "succeeded",
            ),
            succeeded=not self.wait,
            termination_confirmed=self.confirmed,
        )


def setup(tmp_path, runtime=None):
    repo = SQLiteCampaignRepository(tmp_path / "campaigns.sqlite3")
    repo.initialize()
    lock = RuntimeOwnership(tmp_path / "runtime.lock", repo)
    service = CampaignService(repo, lock, runtime or Runtime(), TelemetryStore(), tmp_path, True)
    record, _ = repo.create(CampaignDefinition.model_validate(definition()))
    return repo, lock, service, record


def test_success_carries_profile_and_map_baselines_and_releases(tmp_path):
    async def run():
        repo, lock, service, record = setup(tmp_path)
        await service.start(record.id)
        await service.task
        saved = repo.get(record.id)
        assert saved.state == "completed"
        assert all(t.state == "succeeded" for t in saved.trials)
        assert saved.termination_confirmed and saved.cleanup_confirmed
        assert repo.lease() is None
        calls = service.runtime.calls
        assert calls[0][1:] == (None, None)
        first = Path(saved.trials[0].evidence.manifest_path)
        assert calls[1][1:] == (first, first)
        assert calls[2][1:] == (None, first)
        assert calls[3][1:] == (Path(saved.trials[2].evidence.manifest_path), first)
        fd = lock.acquire_manual()
        lock.release(fd)
        with pytest.raises(CampaignConflict):
            await service.start(record.id)

    asyncio.run(run())


@pytest.mark.parametrize("preparing", [False, True])
def test_cancel_waits_for_termination_and_cleanup(tmp_path, preparing):
    async def run():
        runtime = Runtime(wait=True)
        runtime.preparing = preparing
        repo, lock, service, record = setup(tmp_path, runtime)
        await service.start(record.id)
        await runtime.entered.wait()
        assert (await service.start(record.id)).id == record.id
        with pytest.raises(CampaignConflict):
            lock.acquire_manual()
        repo.cancel(record.id)
        await service.task
        saved = repo.get(record.id)
        assert saved.state == "canceled"
        assert len(runtime.calls) == (0 if preparing else 1)
        assert saved.termination_confirmed and saved.cleanup_confirmed
        assert runtime.stops and repo.lease() is None

    asyncio.run(run())


@pytest.mark.parametrize("confirmed,clean", [(False, True), (True, False)])
def test_uncertain_termination_or_cleanup_quarantines_runtime(tmp_path, confirmed, clean):
    async def run():
        runtime = Runtime(wait=not confirmed, confirmed=confirmed, clean=clean)
        repo, lock, service, record = setup(tmp_path, runtime)
        await service.start(record.id)
        await runtime.entered.wait()
        if not confirmed:
            repo.cancel(record.id)
        await service.task
        assert repo.get(record.id).state == "interrupted"
        assert repo.lease() is not None
        with pytest.raises(CampaignConflict):
            lock.acquire_manual()
        await service.reconcile(record.id)
        assert repo.lease() is None
        assert repo.get(record.id).state == "interrupted"
        assert repo.events(record.id)[-1].kind == "reconciled"

    asyncio.run(run())


def test_second_worker_cannot_recover_live_owner_then_recovery_never_retries(tmp_path):
    async def run():
        repo, lock, service, record = setup(tmp_path)
        fd = lock.acquire()
        repo.claim(record.id, "dead-owner")
        await service.startup()
        assert repo.get(record.id).state == "queued"
        lock.release(fd)
        await service.startup()
        assert repo.get(record.id).state == "interrupted"
        assert repo.lease() is not None and service.task is None
        with pytest.raises(CampaignConflict):
            await service.start(record.id)
        await service.reconcile(record.id)

    asyncio.run(run())


def test_transactional_claim_fencing_cancel_merge_and_schema_migration(tmp_path):
    repo, lock, service, record = setup(tmp_path)
    other, _ = repo.create(record.definition)

    def claim(item):
        try:
            return repo.claim(item.id, item.id)
        except CampaignConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [record, other]))
    winner = next(r for r in results if r is not None)
    assert sum(r is not None for r in results) == 1
    with pytest.raises(CampaignConflict):
        repo.save_owned(winner, "wrong-owner", "trial_started")
    repo.cancel(winner.id)
    winner.state = "running"
    repo.save_owned(winner, winner.id, "trial_started")
    assert repo.get(winner.id).state == "canceling"
    assert repo.get(winner.id).cancel_requested
    with pytest.raises(CampaignConflict):
        repo.save_owned(winner, winner.id, "failed", release=True)
    assert repo.lease() is not None
    import sqlite3

    with sqlite3.connect(repo.path) as db:
        db.execute("PRAGMA user_version=1")
    repo.initialize()
    assert repo.get(winner.id).cancel_requested


def test_api_ownership_guards_robot_mutations_but_keeps_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOTOPS_REPO_ROOT", str(tmp_path))
    runtime = Runtime(wait=True)
    repo, lock, service, record = setup(tmp_path, runtime)
    app = create_app(
        campaign_repository=repo,
        campaign_runtime=runtime,
        campaign_execution=True,
        orchestrator=DefinitionOnlyOrchestrator(repo_root=tmp_path),
    )
    with TestClient(app) as client:
        location = f"/api/v1/campaigns/{record.id}"
        assert client.post(location + "/start").status_code == 202
        assert client.post(location + "/start").status_code == 202
        assert client.get("/api/v1/campaigns/runtime").json()["worker_active"]
        for method, path, data in [
            ("post", "/control/stack", {"mode": "navigation", "runtime_mode": "sim"}),
            ("delete", "/control/stack", None),
            ("post", "/navigation/prepare", None),
            ("post", "/maps/save", {"name": "test"}),
            ("post", "/localization/initial-pose", {"x": 0, "y": 0, "yaw": 0}),
            ("post", "/teleop", {"linear_x": 0, "angular_z": 0}),
            ("post", "/missions", {"waypoints": [{"x": 1, "y": 0, "yaw": 0}]}),
            ("delete", "/missions/test", None),
        ]:
            response = client.request(method, "/api/v1" + path, json=data)
            assert response.status_code == 409, (path, response.text)
        assert client.get("/api/v1/robot").status_code == 200
        assert client.get(location).status_code == 200
        assert client.delete("/api/v1/control/rviz").status_code == 200
        assert client.post(location + "/cancel").status_code == 200
    assert repo.get(record.id).state == "canceled"
    assert repo.lease() is None


def test_inherited_lock_survives_parent_descriptor_close(tmp_path):
    import subprocess
    import sys

    repo, lock, service, record = setup(tmp_path)
    fd = lock.acquire()
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; print('ready',flush=True); sys.stdin.read()"],
        pass_fds=(fd,),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        lock.release(fd)
        with pytest.raises(CampaignConflict):
            lock.acquire()
    finally:
        child.communicate(timeout=5)
    fresh = lock.acquire()
    lock.release(fresh)


def test_shutdown_cancels_cooperatively_and_external_telemetry_blocks_reuse(tmp_path):
    async def run():
        repo, lock, service, record = setup(tmp_path, Runtime(wait=True))
        service.telemetry.publish()
        with pytest.raises(CampaignConflict):
            await service.start(record.id)
        service.telemetry.mark_disconnected()
        await service.start(record.id)
        await service.runtime.entered.wait()
        await service.shutdown()
        assert repo.get(record.id).state == "canceled"
        assert repo.lease() is None
        # Crash recovery may be deferred until a child releases the process lock.
        other, _ = repo.create(record.definition)
        repo.claim(other.id, "orphan")
        service.telemetry.publish()
        with pytest.raises(CampaignConflict):
            await service.reconcile(other.id)
        assert repo.lease() is not None
        service.telemetry.mark_disconnected()
        await service.reconcile(other.id)
        assert repo.get(other.id).state == "interrupted"
        assert repo.lease() is None

    asyncio.run(run())


def test_startup_storage_failure_closes_gateway_and_orchestrator(tmp_path, monkeypatch):
    from robotops_backend.campaigns.repository import CampaignStorageError
    from robotops_backend.gateway import UnavailableGateway

    monkeypatch.setenv("ROBOTOPS_REPO_ROOT", str(tmp_path))
    repo, lock, service, record = setup(tmp_path)
    closed = []
    store = TelemetryStore()
    gateway = UnavailableGateway(store)
    orchestrator = DefinitionOnlyOrchestrator(repo_root=tmp_path)

    def fail():
        raise CampaignStorageError("Injected recovery failure")

    monkeypatch.setattr(repo, "recover", fail)
    monkeypatch.setattr(gateway, "close", lambda: closed.append("gateway"))
    monkeypatch.setattr(orchestrator, "close", lambda: closed.append("orchestrator"))
    app = create_app(
        gateway=gateway, telemetry=store, orchestrator=orchestrator, campaign_repository=repo
    )
    with pytest.raises(CampaignStorageError):
        with TestClient(app):
            pass
    assert closed == ["orchestrator", "gateway"]
    fd = lock.acquire()
    lock.release(fd)


def test_runtime_discovery_is_independent_of_history_page(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOTOPS_REPO_ROOT", str(tmp_path))
    repo, lock, service, record = setup(tmp_path)
    for _ in range(22):
        repo.create(record.definition)
    repo.claim(record.id, "orphan")
    lock = RuntimeOwnership(tmp_path / "artifacts/runtime.lock", repo)
    fd = lock.acquire()  # Simulate a child retaining ownership during startup.
    try:
        app = create_app(
            campaign_repository=repo,
            campaign_runtime=Runtime(),
            campaign_execution=True,
            orchestrator=DefinitionOnlyOrchestrator(repo_root=tmp_path),
        )
        with TestClient(app) as client:
            assert record.id not in {r["id"] for r in client.get("/api/v1/campaigns").json()}
            status = client.get("/api/v1/campaigns/runtime").json()
            assert status == dict(
                campaign_id=record.id,
                execution_enabled=True,
                supported_modes=["sim"],
                worker_active=False,
            )
            assert client.get(f"/api/v1/campaigns/{record.id}").json()["state"] == "queued"
    finally:
        lock.release(fd)


def test_pose_verdict_is_persisted_separately_from_ros_success(tmp_path):
    class RejectedPoseRuntime(Runtime):
        async def execute(self, *args, **kwargs):
            result = await super().execute(*args, **kwargs)
            result.evidence.validation = {
                "schema_version": 1,
                "verdict": "POSE_REJECTED",
                "ros_outcome": "succeeded",
                "xy_error_m": 0.3,
                "reasons": ["Final XY error exceeds RobotOps tolerance"],
            }
            result.evidence.collision = {
                "schema_version": 1,
                "verdict": "CONTACT_DETECTED",
                "contacts": [{"body_a": "robot", "body_b": "wall"}],
            }
            return result

    async def run():
        repo, lock, service, record = setup(tmp_path, RejectedPoseRuntime())
        await service.start(record.id)
        await service.task
        reopened = SQLiteCampaignRepository(repo.path)
        reopened.initialize()
        saved = reopened.get(record.id)
        assert saved.state == "completed" and repo.lease() is None
        assert all(t.state == "succeeded" for t in saved.trials)
        assert all(t.evidence.validation["verdict"] == "POSE_REJECTED" for t in saved.trials)
        assert all(t.evidence.collision["verdict"] == "CONTACT_DETECTED" for t in saved.trials)
        assert (
            saved.model_dump(mode="json")["trials"][0]["evidence"]["validation"]["xy_error_m"]
            == 0.3
        )

    asyncio.run(run())
