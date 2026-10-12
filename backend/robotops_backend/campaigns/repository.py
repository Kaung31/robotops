"""Transactional local metadata; MCAP and media remain outside the database."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .models import CampaignDefinition, CampaignEvent, CampaignRecord, PlannedTrial
from .report_models import CampaignReport


class CampaignConflict(Exception):
    pass


class CampaignStorageError(Exception):
    pass


class CampaignRepository(Protocol):
    def initialize(self) -> None: ...
    def create(
        self, definition: CampaignDefinition, key: str | None
    ) -> tuple[CampaignRecord, bool]: ...
    def find_by_key(self, key: str) -> CampaignRecord | None: ...
    def get(self, campaign_id: str) -> CampaignRecord: ...
    def history(self, limit: int, offset: int) -> list[CampaignRecord]: ...
    def events(self, campaign_id: str, after: int, limit: int) -> list[CampaignEvent]: ...
    def cancel(self, campaign_id: str) -> CampaignRecord: ...
    def lease(self) -> dict[str, str] | None: ...
    def claim(self, campaign_id: str, owner: str) -> CampaignRecord: ...
    def save_owned(
        self, record: CampaignRecord, owner: str, kind: str, release: bool = False
    ) -> CampaignRecord: ...
    def recover(self) -> None: ...
    def reconcile(self, campaign_id: str) -> CampaignRecord: ...
    def save_report(self, report: CampaignReport) -> CampaignReport: ...
    def reports(self, campaign_id: str, limit: int = 20) -> list[CampaignReport]: ...
    def get_report(self, campaign_id: str, report_id: str) -> CampaignReport: ...


class SQLiteCampaignRepository:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def _connection(self):
        connection = None
        try:
            connection = sqlite3.connect(self.path, timeout=5)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        except (sqlite3.Error, OSError) as exc:
            raise CampaignStorageError("Campaign storage unavailable") from exc
        finally:
            if connection is not None:
                connection.close()

    def initialize(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CampaignStorageError("Cannot create campaign storage directory") from exc
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise CampaignStorageError(f"Unsupported campaign database version {version}")
            db.execute(
                "CREATE TABLE IF NOT EXISTS campaigns ("
                "id TEXT PRIMARY KEY, request_key TEXT UNIQUE, digest TEXT NOT NULL, "
                "record TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS campaign_events ("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                "campaign_id TEXT NOT NULL REFERENCES campaigns(id), "
                "at TEXT NOT NULL, kind TEXT NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS campaign_events_by_campaign "
                "ON campaign_events(campaign_id, sequence)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS runtime_lease ("
                "id INTEGER PRIMARY KEY CHECK(id=1), campaign_id TEXT NOT NULL "
                "REFERENCES campaigns(id), owner TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS campaign_reports ("
                "id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id), "
                "payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS reports_by_campaign ON campaign_reports(campaign_id)"
            )
            db.execute("PRAGMA user_version=3")

    @staticmethod
    def _decode_report(row) -> CampaignReport:
        if row is None:
            raise KeyError("Report not found")
        try:
            report = CampaignReport.model_validate_json(row["payload"])
            payload = report.model_dump(mode="json", exclude={"id", "created_at"})
            digest = hashlib.sha256(
                json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            ).hexdigest()
            if digest != report.id:
                raise ValueError("Report fingerprint differs")
            return report
        except ValueError as exc:
            raise CampaignStorageError("Stored report is invalid") from exc

    def save_report(self, report: CampaignReport) -> CampaignReport:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._decode(
                db.execute(
                    "SELECT record FROM campaigns WHERE id=?", (report.campaign.id,)
                ).fetchone()
            )
            if current != report.campaign:
                raise CampaignConflict("Campaign changed during report generation; generate again")
            if current.state not in ("completed", "failed", "canceled", "interrupted"):
                raise CampaignConflict("Only finalized campaigns can have reports")
            db.execute(
                "INSERT OR IGNORE INTO campaign_reports VALUES (?, ?, ?)",
                (report.id, report.campaign.id, report.model_dump_json()),
            )
            return self._decode_report(
                db.execute(
                    "SELECT payload FROM campaign_reports WHERE id=?", (report.id,)
                ).fetchone()
            )

    def reports(self, campaign_id: str, limit: int = 20) -> list[CampaignReport]:
        with self._connection() as db:
            self._decode(
                db.execute("SELECT record FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            )
            return [
                self._decode_report(row)
                for row in db.execute(
                    "SELECT payload FROM campaign_reports WHERE campaign_id=? "
                    "ORDER BY rowid DESC LIMIT ?",
                    (campaign_id, limit),
                )
            ]

    def get_report(self, campaign_id: str, report_id: str) -> CampaignReport:
        with self._connection() as db:
            return self._decode_report(
                db.execute(
                    "SELECT payload FROM campaign_reports WHERE campaign_id=? AND id=?",
                    (campaign_id, report_id),
                ).fetchone()
            )

    @staticmethod
    def _decode(row) -> CampaignRecord:
        if row is None:
            raise KeyError("Campaign not found")
        try:
            return CampaignRecord.model_validate_json(row["record"])
        except ValueError as exc:
            raise CampaignStorageError("Stored campaign record is invalid") from exc

    def create(
        self, definition: CampaignDefinition, key: str | None = None
    ) -> tuple[CampaignRecord, bool]:
        payload = json.dumps(definition.model_dump(mode="json"), sort_keys=True, allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        now = datetime.now(UTC)
        record = CampaignRecord(
            id=uuid4().hex,
            created_at=now,
            updated_at=now,
            definition=definition,
            trials=[
                PlannedTrial(id=uuid4().hex, profile=profile, repetition=repetition)
                for profile in definition.profiles
                for repetition in range(1, definition.repetitions + 1)
            ],
        )
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if key is not None:
                existing = db.execute(
                    "SELECT * FROM campaigns WHERE request_key=?", (key,)
                ).fetchone()
                if existing is not None:
                    if existing["digest"] != digest:
                        raise CampaignConflict(
                            "Idempotency key already used for another definition"
                        )
                    return self._decode(existing), False
            db.execute(
                "INSERT INTO campaigns VALUES (?, ?, ?, ?)",
                (record.id, key, digest, record.model_dump_json()),
            )
            db.execute(
                "INSERT INTO campaign_events(campaign_id, at, kind) VALUES (?, ?, 'created')",
                (record.id, now.isoformat()),
            )
        return record, True

    def find_by_key(self, key: str) -> CampaignRecord | None:
        with self._connection() as db:
            row = db.execute("SELECT record FROM campaigns WHERE request_key=?", (key,)).fetchone()
            return None if row is None else self._decode(row)

    def get(self, campaign_id: str) -> CampaignRecord:
        with self._connection() as db:
            return self._decode(
                db.execute("SELECT record FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            )

    def history(self, limit: int = 20, offset: int = 0) -> list[CampaignRecord]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT record FROM campaigns ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [self._decode(row) for row in rows]

    def events(self, campaign_id: str, after: int = 0, limit: int = 100) -> list[CampaignEvent]:
        with self._connection() as db:
            self._decode(
                db.execute("SELECT record FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            )
            try:
                return [
                    CampaignEvent.model_validate(dict(row))
                    for row in db.execute(
                        "SELECT * FROM campaign_events WHERE campaign_id=? AND sequence>? "
                        "ORDER BY sequence LIMIT ?",
                        (campaign_id, after, limit),
                    ).fetchall()
                ]
            except ValueError as exc:
                raise CampaignStorageError("Stored campaign event is invalid") from exc

    def cancel(self, campaign_id: str) -> CampaignRecord:
        # Active cancellation persists intent; only the owning worker touches ROS.
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._decode(
                db.execute("SELECT record FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            )
            if record.state == "canceled":
                return record
            if record.state in ("queued", "running", "canceling"):
                if not record.cancel_requested:
                    record.cancel_requested = True
                    record.state = "canceling"
                    self._write(db, record, "cancel_requested")
                return record
            if record.state != "draft":
                raise CampaignConflict("Finalized campaign cannot be canceled")
            record.state = "canceled"
            record.updated_at = datetime.now(UTC)
            for trial in record.trials:
                trial.state = "canceled"
            db.execute(
                "UPDATE campaigns SET record=? WHERE id=?", (record.model_dump_json(), campaign_id)
            )
            db.execute(
                "INSERT INTO campaign_events(campaign_id, at, kind) VALUES (?, ?, 'canceled')",
                (campaign_id, record.updated_at.isoformat()),
            )
            return record

    @staticmethod
    def _write(db, record: CampaignRecord, kind: str) -> None:
        record.updated_at = datetime.now(UTC)
        db.execute(
            "UPDATE campaigns SET record=? WHERE id=?", (record.model_dump_json(), record.id)
        )
        db.execute(
            "INSERT INTO campaign_events(campaign_id, at, kind) VALUES (?, ?, ?)",
            (record.id, record.updated_at.isoformat(), kind),
        )

    def lease(self) -> dict[str, str] | None:
        with self._connection() as db:
            row = db.execute("SELECT campaign_id, owner FROM runtime_lease WHERE id=1").fetchone()
            return dict(row) if row else None

    def claim(self, campaign_id: str, owner: str) -> CampaignRecord:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._decode(
                db.execute("SELECT record FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            )
            if record.state != "draft":
                raise CampaignConflict("Only an unstarted draft can execute; no automatic retries")
            if db.execute("SELECT 1 FROM runtime_lease").fetchone():
                raise CampaignConflict("Runtime already owned or awaiting reconciliation")
            db.execute("INSERT INTO runtime_lease VALUES (1, ?, ?)", (campaign_id, owner))
            record.state = "queued"
            self._write(db, record, "started")
            return record

    def save_owned(
        self, record: CampaignRecord, owner: str, kind: str, release: bool = False
    ) -> CampaignRecord:
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT campaign_id, owner FROM runtime_lease WHERE id=1").fetchone()
            if row is None or row["campaign_id"] != record.id or row["owner"] != owner:
                raise CampaignConflict("Campaign worker no longer owns the runtime")
            current = self._decode(
                db.execute("SELECT record FROM campaigns WHERE id=?", (record.id,)).fetchone()
            )
            record.cancel_requested = current.cancel_requested
            if current.cancel_requested and record.state in ("queued", "running"):
                record.state = "canceling"
            self._write(db, record, kind)
            if release:
                if not (record.termination_confirmed and record.cleanup_confirmed):
                    raise CampaignConflict("Cannot release ownership without confirmed cleanup")
                db.execute("DELETE FROM runtime_lease WHERE id=1")
            return record

    def recover(self) -> None:
        # Caller must first hold the runtime file lock: another live worker must
        # never be mistaken for a crashed worker by a second backend process.
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            lease = db.execute("SELECT campaign_id FROM runtime_lease WHERE id=1").fetchone()
            if lease is None:
                return
            record = self._decode(
                db.execute(
                    "SELECT record FROM campaigns WHERE id=?", (lease["campaign_id"],)
                ).fetchone()
            )
            if record.state == "interrupted":
                return
            record.state = "interrupted"
            record.error = (
                "Worker stopped without confirmed completion; reconcile runtime before reuse"
            )
            record.termination_confirmed = False
            record.cleanup_confirmed = False
            for trial in record.trials:
                if trial.state in ("starting", "running"):
                    trial.state = "interrupted"
            self._write(db, record, "interrupted")

    def reconcile(self, campaign_id: str) -> CampaignRecord:
        # Caller verifies the runtime lock is available and robot telemetry absent.
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT campaign_id FROM runtime_lease WHERE id=1").fetchone()
            record = self._decode(
                db.execute("SELECT record FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            )
            if row is None or row["campaign_id"] != campaign_id or record.state != "interrupted":
                raise CampaignConflict("No interrupted runtime ownership to reconcile")
            db.execute("DELETE FROM runtime_lease WHERE id=1")
            # Reconciliation releases ownership; it does not invent a mission result.
            self._write(db, record, "reconciled")
            return record
