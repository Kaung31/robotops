"""Persistence/API regression tests run without ROS or a simulator."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from robotops_backend.app import create_app
from robotops_backend.campaigns.models import CampaignDefinition
from robotops_backend.campaigns.repository import (
    CampaignConflict,
    CampaignStorageError,
    SQLiteCampaignRepository,
)
from robotops_backend.models import ControlOptions, MapArtifact, NavigationProfile, WorldOption
from robotops_backend.orchestrator import StackOrchestrator


def definition(**changes):
    data = dict(
        name="Saved round trip",
        runtime_mode="sim",
        world="mapping_lab",
        map_id="lab",
        profiles=["navfn_rpp", "smac_dwb"],
        repetitions=2,
        waypoints=[dict(x=0.8, y=0.5, yaw=0), dict(x=0, y=0, yaw=0)],
        start=dict(x=0, y=0, yaw=0),
    )
    data.update(changes)
    return data


@pytest.fixture
def repository(tmp_path):
    repo = SQLiteCampaignRepository(tmp_path / "campaigns.sqlite3")
    repo.initialize()
    return repo


class DefinitionOnlyOrchestrator(StackOrchestrator):
    def options(self):
        return ControlOptions(
            worlds=[WorldOption(id="mapping_lab", label="Lab", difficulty="medium")],
            maps=[]
            if getattr(self, "missing_maps", False)
            else [
                MapArtifact(id="lab", label="Lab", yaml_path="lab.yaml", world_id="mapping_lab")
            ],
            navigation_profiles=[
                NavigationProfile(id=p, label=p, planner=p, controller=p)
                for p in ("navfn_rpp", "smac_dwb")
            ],
        )

    def start(self, request):
        raise AssertionError("Definition API must not start a robot")

    def stop(self):
        raise AssertionError("Definition API must not stop a robot")

    def close(self):
        pass


def client_for(repo, tmp_path):
    return TestClient(
        create_app(
            orchestrator=DefinitionOnlyOrchestrator(repo_root=tmp_path),
            campaign_repository=repo,
        )
    )


def test_ids_order_and_records_survive_reopening(repository):
    config = CampaignDefinition.model_validate(definition())
    record, created = repository.create(config, "request-1")
    assert created and record.state == "draft"
    assert [(t.profile, t.repetition) for t in record.trials] == [
        ("navfn_rpp", 1),
        ("navfn_rpp", 2),
        ("smac_dwb", 1),
        ("smac_dwb", 2),
    ]
    assert len({record.id, *(t.id for t in record.trials)}) == 5
    reopened = SQLiteCampaignRepository(repository.path)
    reopened.initialize()
    assert reopened.get(record.id) == record
    assert reopened.create(config, "request-1") == (record, False)
    assert [e.kind for e in reopened.events(record.id)] == ["created"]
    assert reopened.history() == [record]


def test_parallel_retries_create_one_record_and_event(repository):
    config = CampaignDefinition.model_validate(definition())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: repository.create(config, "same-key"), range(16)))
    assert len({record.id for record, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert len(repository.history()) == 1
    assert len(repository.events(results[0][0].id)) == 1
    with pytest.raises(CampaignConflict):
        repository.create(CampaignDefinition.model_validate(definition(repetitions=1)), "same-key")


def test_cancel_is_atomic_idempotent_and_preserves_definition(repository):
    record, _ = repository.create(CampaignDefinition.model_validate(definition()))
    canceled = repository.cancel(record.id)
    assert canceled.state == "canceled"
    assert all(t.state == "canceled" for t in canceled.trials)
    assert canceled.definition == record.definition
    assert repository.cancel(record.id) == canceled
    events = repository.events(record.id)
    assert [e.kind for e in events] == ["created", "canceled"]
    assert repository.events(record.id, after=events[0].sequence) == events[1:]
    assert repository.events(record.id, after=events[-1].sequence) == []


def test_failed_event_insert_rolls_back_record(repository):
    with sqlite3.connect(repository.path) as db:
        db.execute(
            "CREATE TRIGGER fail_event BEFORE INSERT ON campaign_events "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(CampaignStorageError):
        repository.create(CampaignDefinition.model_validate(definition()))
    assert repository.history() == []


def test_unknown_database_version_fails_without_rewriting(repository):
    with sqlite3.connect(repository.path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(CampaignStorageError, match="Unsupported"):
        repository.initialize()
    with sqlite3.connect(repository.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


@pytest.mark.parametrize(
    "changes",
    [
        {"runtime_mode": "replay"},
        {"runtime_mode": "real"},
        {"runtime_mode": "unknown"},
        {"name": "   "},
        {"repetitions": True},
        {"repetitions": "2"},
        {"repetitions": 0},
        {"repetitions": 51},
        {"profiles": []},
        {"profiles": ["navfn_rpp", "navfn_rpp"]},
        {"map_id": "../map"},
        {"waypoints": []},
        {"waypoints": [dict(x=float("nan"), y=0, yaw=0)]},
        {"waypoints": [dict(x=True, y=0, yaw=0)]},
        {"start": dict(x=0, y=0, yaw=0, position_tolerance=0)},
        {"start": dict(x=0, y=0, yaw=0, yaw_tolerance=float("inf"))},
        {"timeouts": {"trial": 3601}},
        {"timeouts": {"trial": True}},
        {"faults": {}},
        {"robot_model": "other"},
    ],
)
def test_definition_rejects_invalid_configuration(changes):
    with pytest.raises(ValidationError):
        CampaignDefinition.model_validate(definition(**changes))


def test_api_retries_history_events_and_restart(repository, tmp_path):
    headers = {"Idempotency-Key": "api-create-1"}
    with client_for(repository, tmp_path) as client:
        response = client.post("/api/v1/campaigns", json=definition(), headers=headers)
        assert response.status_code == 201
        record = response.json()
        location = response.headers["location"]
        assert location.endswith(record["id"])
        assert (
            client.post("/api/v1/campaigns", json=definition(), headers=headers).json() == record
        )
        assert (
            client.post(
                "/api/v1/campaigns", json=definition(repetitions=1), headers=headers
            ).status_code
            == 409
        )
        assert client.post(location + "/cancel").json()["state"] == "canceled"
        assert client.post(location + "/cancel").status_code == 200
    with client_for(SQLiteCampaignRepository(repository.path), tmp_path) as client:
        saved = client.get(location).json()
        assert saved["state"] == "canceled"
        assert [t["id"] for t in saved["trials"]] == [t["id"] for t in record["trials"]]
        assert client.get("/api/v1/campaigns?limit=1").json() == [saved]
        events = client.get(location + "/events?limit=1").json()
        later = client.get(location + "/events", params={"after": events[0]["sequence"]}).json()
        assert [e["kind"] for e in events + later] == ["created", "canceled"]
        assert client.get("/api/v1/campaigns?offset=1").json() == []
        assert client.post(location + "/start").status_code == 501


def test_api_validates_environment_and_pagination(repository, tmp_path):
    with client_for(repository, tmp_path) as client:
        for changes in (
            {"world": "missing"},
            {"map_id": "missing"},
            {"profiles": ["missing"]},
            {"runtime_mode": "replay"},
        ):
            assert client.post("/api/v1/campaigns", json=definition(**changes)).status_code == 422
        for suffix in ("/missing", "/missing/events"):
            assert client.get("/api/v1/campaigns" + suffix).status_code == 404
        assert client.post("/api/v1/campaigns/missing/cancel").status_code == 404
        assert client.get("/api/v1/campaigns?limit=101").status_code == 422
        assert client.get("/api/v1/campaigns?offset=999999999999999999999").status_code == 422
        assert (
            client.get("/api/v1/campaigns/missing/events?after=999999999999999999999").status_code
            == 422
        )
        assert client.get("/api/v1/campaigns/missing/events?after=-1").status_code == 422
        assert (
            client.post(
                "/api/v1/campaigns", json=definition(), headers={"Idempotency-Key": "bad key"}
            ).status_code
            == 422
        )
        assert repository.history() == []


def test_api_storage_failure_returns_503(repository, tmp_path):
    with client_for(repository, tmp_path) as client:
        with sqlite3.connect(repository.path) as db:
            db.execute("DROP TABLE campaigns")
        assert client.get("/api/v1/campaigns").status_code == 503


def test_idempotent_retry_returns_saved_definition_even_if_map_removed(repository, tmp_path):
    orchestrator = DefinitionOnlyOrchestrator(repo_root=tmp_path)
    app = create_app(orchestrator=orchestrator, campaign_repository=repository)
    with TestClient(app) as client:
        headers = {"Idempotency-Key": "stable"}
        first = client.post("/api/v1/campaigns", json=definition(), headers=headers)
        assert first.status_code == 201
        orchestrator.missing_maps = True
        assert (
            client.post("/api/v1/campaigns", json=definition(), headers=headers).status_code == 200
        )


def test_cancel_failure_rolls_back_state_and_parallel_cancel_emits_once(repository):
    record, _ = repository.create(CampaignDefinition.model_validate(definition()))
    with sqlite3.connect(repository.path) as db:
        db.execute(
            "CREATE TRIGGER fail_cancel BEFORE INSERT ON campaign_events "
            "WHEN NEW.kind='canceled' BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
    with pytest.raises(CampaignStorageError):
        repository.cancel(record.id)
    assert repository.get(record.id).state == "draft"
    assert all(t.state == "planned" for t in repository.get(record.id).trials)
    with sqlite3.connect(repository.path) as db:
        db.execute("DROP TRIGGER fail_cancel")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: repository.cancel(record.id), range(16)))
    assert all(r == results[0] for r in results)
    assert [e.kind for e in repository.events(record.id)] == ["created", "canceled"]


def test_distinct_requests_history_order_and_corrupt_record(repository):
    config = CampaignDefinition.model_validate(definition())
    first, _ = repository.create(config)
    second, _ = repository.create(config)
    assert first.id != second.id
    assert repository.history(limit=1) == [second]
    assert repository.history(limit=1, offset=1) == [first]
    assert repository.find_by_key("absent") is None
    with sqlite3.connect(repository.path) as db:
        db.execute("UPDATE campaigns SET record='{}' WHERE id=?", (second.id,))
    with pytest.raises(CampaignStorageError, match="invalid"):
        repository.get(second.id)


def test_corrupt_event_returns_storage_error(repository, tmp_path):
    record, _ = repository.create(CampaignDefinition.model_validate(definition()))
    with client_for(repository, tmp_path) as client:
        with sqlite3.connect(repository.path) as db:
            db.execute("UPDATE campaign_events SET kind='unrecognized'")
        assert client.get(f"/api/v1/campaigns/{record.id}/events").status_code == 503
