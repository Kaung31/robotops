"""New W3 qualification coordinator. Import/test never starts a runtime.

No live CLI is provided. A separately approved, hash-bound execution permission
is required by the concrete adapter. Historical W3 claims are never reused.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .evidence import CONTRACT
from .geometry import qualified
from .journal import save_summary

PROFILES = ("navfn_rpp", "smac_dwb")
ATTEMPT_SET = "warehouse-w3-requalification-v4"
GUARD = "artifacts/r2a-q1-20261011/live/test_real_routed_dropout0/runtime/routing.guard"
ORIGINAL_CLAIM = "artifacts/warehouse-w3-20261012/navfn_rpp-attempt.claim"
HISTORICAL_CLAIMS = (
    ORIGINAL_CLAIM,
    "artifacts/warehouse-w3-requalification-v1/navfn_rpp.claim.json",
    "artifacts/warehouse-w3-requalification-v2/navfn_rpp.claim.json",
    "artifacts/warehouse-w3-requalification-v3/navfn_rpp.claim.json",
)
REQUIRED_SHUTDOWN = {
    "runner_clean",
    "critical_lifecycle_complete",
    "two_stream_readback_complete",
    "cleanup_no_exception",
    "observer_and_cleanup_complete",
    "recording_integrity_and_original_immutability",
    "no_remaining_robotics_processes",
}
ATTEMPT_POLICY = {
    "navfn_rpp": 1,
    "smac_dwb": 1,
    "smac_requires": "navfn_qualified_and_verified_shutdown",
    "retries": 0,
}


def validate_contract(plan: dict) -> None:
    if (
        plan.get("execution_approved") is not False
        or plan.get("attempt_set") != ATTEMPT_SET
        or plan.get("evidence_contract") != CONTRACT
        or plan.get("attempt_policy") != ATTEMPT_POLICY
        or set(plan.get("historical_claims", {})) != set(HISTORICAL_CLAIMS)
    ):
        raise RuntimeError("Fresh attempt-set and reviewed two-stream plan required")


def verify_history(root: Path, plan: dict) -> None:
    for path, digest in plan["historical_claims"].items():
        if sha(root / path) != digest:
            raise RuntimeError(f"Historical consumed claim changed: {path}")


def shutdown_complete(shutdown: dict | None) -> bool:
    return bool(
        shutdown
        and REQUIRED_SHUTDOWN <= shutdown.keys()
        and all(value is True for value in shutdown.values())
    )


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(path: Path) -> dict:
    stat = path.stat()
    return {
        "sha256": sha(path),
        "stat": [stat.st_ino, stat.st_mtime_ns, stat.st_mode, stat.st_size],
    }


class ReadOnlyLease:
    """Use the existing ownership gate without initializing/migrating the DB."""

    def __init__(self, path: Path):
        self.path = path

    def lease(self):
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=1)) as db:
            rows = db.execute("SELECT * FROM runtime_lease").fetchall()
        return rows or None


class Runtime(Protocol):
    def preflight(self) -> dict: ...
    def open(self, lock_fd: int) -> None: ...
    def gates(self) -> dict: ...
    def run(self) -> dict: ...
    def close(self, exception: BaseException | None) -> dict: ...


def execute(root: Path, profile: str, ownership, runtime: Runtime, plan: dict) -> dict:
    """One consumed attempt; exceptions never cause replacement or dispatch retry.

    The adapter must check owner permission in preflight. Ownership is acquired
    before all preflight checks and retained through recording/launch teardown.
    """
    if profile not in PROFILES:
        raise ValueError("Unsupported qualification profile")
    directory = root / "artifacts" / ATTEMPT_SET
    lock = ownership.acquire_manual()
    error = None
    opened = False
    consumed = False
    result = {
        "profile": profile,
        "attempt_set": ATTEMPT_SET,
        "evidence_contract": CONTRACT["version"],
        "qualified": False,
        "attempted": False,
        "original_result": None,
        "shutdown": None,
    }
    try:
        validate_contract(plan)
        verify_history(root, plan)
        if identity(root / GUARD) != plan["guard"]:
            raise RuntimeError("Routing guard identity changed")
        if sha(root / ORIGINAL_CLAIM) != plan["original_claim_sha256"]:
            raise RuntimeError("Original consumed attempt changed")
        directory.mkdir(exist_ok=True)
        if (directory / f"{profile}.claim.json").exists():
            raise FileExistsError("Attempt already consumed; no silent retry")
        if profile == "smac_dwb":
            first = json.loads((directory / "navfn_rpp-result.json").read_text())
            first_claim = json.loads((directory / "navfn_rpp.claim.json").read_text())
            if (
                first.get("qualified") is not True
                or not qualified(first.get("original_result") or {})
                or first.get("attempt_set") != ATTEMPT_SET
                or first.get("profile") != "navfn_rpp"
                or first.get("evidence_contract") != CONTRACT["version"]
                or first_claim.get("attempt_set") != ATTEMPT_SET
                or first_claim.get("plan_sha256") != plan["plan_sha256"]
                or not shutdown_complete(first.get("shutdown"))
                or first.get("claim_sha256") != sha(directory / "navfn_rpp.claim.json")
                or first.get("plan_sha256") != plan["plan_sha256"]
            ):
                raise RuntimeError("NavFn qualification and verified shutdown required")
        result["preflight"] = runtime.preflight()
        # Exclusive durable claim precedes ROS initialization or process startup.
        claim = directory / f"{profile}.claim.json"
        save_summary(
            claim,
            {
                "profile": profile,
                "attempt_set": ATTEMPT_SET,
                "evidence_contract": CONTRACT["version"],
                "plan_sha256": plan["plan_sha256"],
                "original_claim_sha256": plan["original_claim_sha256"],
                "policy": "ONE_ATTEMPT_NO_RETRY",
            },
        )
        consumed = result["attempted"] = True
        # Directory metadata must also reach durable storage. A failure leaves
        # the exclusive claim in place and forbids another startup.
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        result.update(claim_sha256=sha(claim), plan_sha256=plan["plan_sha256"])
        opened = True  # Partial startup must also receive close.
        runtime.open(lock)
        result["gates"] = runtime.gates()
        if not result["gates"] or any(v is not True for v in result["gates"].values()):
            raise RuntimeError("Qualification dispatch gate incomplete")
        result["original_result"] = runtime.run()
        if not qualified(result["original_result"]):
            raise RuntimeError("Original independent mission/pose/contact result did not qualify")
    except BaseException as exc:
        error = exc
    finally:
        try:
            if opened:
                result["shutdown"] = runtime.close(error)
            if identity(root / GUARD) != plan["guard"]:
                raise RuntimeError("Routing guard identity changed during assessment")
            if sha(root / ORIGINAL_CLAIM) != plan["original_claim_sha256"]:
                raise RuntimeError("Historical attempt changed during assessment")
            verify_history(root, plan)
            if opened and not shutdown_complete(result["shutdown"]):
                raise RuntimeError("Shutdown/evidence/recording verification incomplete")
        except BaseException as cleanup_error:
            result["cleanup_error"] = f"{type(cleanup_error).__name__}: {cleanup_error}"
            if error is None:
                error = cleanup_error
        try:
            result["error"] = f"{type(error).__name__}: {error}" if error else None
            result["qualified"] = consumed and error is None
            # No failure before consumption can overwrite an existing result.
            if consumed:
                save_summary(directory / f"{profile}-result.json", result)
            elif directory.is_dir():
                save_summary(directory / f"{profile}-preflight-failure-{uuid4().hex}.json", result)
        finally:
            ownership.release(lock)
    if error is not None:
        raise RuntimeError("W3 stopped; preserve attempt and all evidence") from error
    return result


def prepare_plan(root: Path, output: Path, installed: dict | None = None) -> dict:
    """Offline-only source/integrity plan; execution permission is always false."""
    sys.path.insert(0, str(root / "backend"))
    from robotops_backend.benchmarks.warehouse import validate_matrix

    validate_matrix(root, root / "benchmarks/warehouse_v1/matrix.json")
    paths = []
    for relative in ("ros2_ws/src", "scripts/warehouse_qualification"):
        paths.extend(
            p for p in (root / relative).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    paths += [
        root / "backend/robotops_backend/campaigns/ownership.py",
        root / "backend/robotops_backend/benchmarks/warehouse.py",
        root / "benchmarks/warehouse_v1/matrix.json",
        root
        / "artifacts/warehouse-w3-preflight-correction-20261012/supplemental_process_check.py",
    ]
    plan = {
        "execution_approved": False,
        "installed": installed or {},
        "attempt_set": ATTEMPT_SET,
        "evidence_contract": CONTRACT,
        "historical_claims": {path: sha(root / path) for path in HISTORICAL_CLAIMS},
        "attempt_policy": ATTEMPT_POLICY,
        "guard": identity(root / GUARD),
        "original_claim_sha256": sha(root / ORIGINAL_CLAIM),
        "files": {str(p.relative_to(root)): sha(p) for p in sorted(paths)},
    }
    save_summary(output, plan)
    return {**plan, "plan_sha256": sha(output)}
