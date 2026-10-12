"""One lifespan-owned worker; ROS remains the authority for mission results."""

import asyncio
import logging
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from ..models import ConnectionState
from ..state import TelemetryStore
from .models import CampaignDefinition, CampaignRecord, PlannedTrial
from .ownership import RuntimeOwnership
from .repository import CampaignConflict, CampaignRepository
from .runtime import CampaignInterrupted, CancelCheck, TrialExecution

logger = logging.getLogger(__name__)


class TrialRuntime(Protocol):
    def supports(self, mode: str) -> bool: ...
    async def idle(self) -> bool: ...
    async def prepare(
        self, definition: CampaignDefinition, profile: str, canceled: CancelCheck
    ) -> None: ...
    async def stop(self) -> bool: ...
    async def execute(
        self,
        definition: CampaignDefinition,
        trial: PlannedTrial,
        directory: Path,
        baseline: Path | None,
        map_baseline: Path | None,
        canceled: CancelCheck,
        lease_fd: int,
    ) -> TrialExecution: ...


class CampaignService:
    def __init__(
        self,
        repository: CampaignRepository,
        ownership: RuntimeOwnership,
        runtime: TrialRuntime,
        telemetry: TelemetryStore,
        root: Path,
        enabled: bool = False,
    ):
        self.repository = repository
        self.ownership = ownership
        self.runtime = runtime
        self.telemetry = telemetry
        self.root = root
        self.enabled = enabled
        self.owner = uuid4().hex
        self.task: asyncio.Task | None = None
        self.active_id: str | None = None
        self.stopping = False

    async def startup(self) -> None:
        try:
            fd = await asyncio.to_thread(self.ownership.acquire)
        except CampaignConflict:
            return  # A live owner (possibly its child runner) still holds the lock.
        try:
            await asyncio.to_thread(self.repository.recover)
        finally:
            self.ownership.release(fd)

    async def shutdown(self) -> None:
        self.stopping = True
        if self.task is not None:
            if self.active_id is not None:
                try:
                    await asyncio.to_thread(self.repository.cancel, self.active_id)
                except CampaignConflict:
                    pass  # Already finalized between the shutdown check and write.
                except Exception:
                    logger.exception("Could not persist shutdown cancellation")
            # Do not cancel the asyncio task: let the ROS runner confirm termination.
            await asyncio.shield(self.task)

    async def start(self, campaign_id: str) -> CampaignRecord:
        if not self.enabled:
            raise NotImplementedError("Backend campaign execution is not enabled")
        if self.active_id == campaign_id and self.task is not None and not self.task.done():
            return await asyncio.to_thread(self.repository.get, campaign_id)
        fd = await asyncio.to_thread(self.ownership.acquire)
        claimed = False
        try:
            record = await asyncio.to_thread(self.repository.get, campaign_id)
            if not self.runtime.supports(record.definition.runtime_mode):
                raise NotImplementedError("No execution adapter for this runtime mode")
            if (
                self.stopping
                or not await self.runtime.idle()
                or self.telemetry.latest().connection == ConnectionState.CONNECTED
            ):
                raise CampaignConflict("Stop the existing runtime before starting a campaign")
            record = await asyncio.to_thread(self.repository.claim, campaign_id, self.owner)
            claimed = True
            self.active_id = campaign_id
            self.task = asyncio.create_task(self._run(record, fd), name=f"campaign-{campaign_id}")
            return record
        finally:
            if not claimed:
                self.ownership.release(fd)

    async def reconcile(self, campaign_id: str) -> CampaignRecord:
        fd = await asyncio.to_thread(self.ownership.acquire)
        try:
            if (
                not await self.runtime.idle()
                or self.telemetry.latest().connection == ConnectionState.CONNECTED
            ):
                raise CampaignConflict(
                    "Stop the runtime and wait for telemetry to disconnect first"
                )
            # A child may have held the lock during startup and exited since.
            await asyncio.to_thread(self.repository.recover)
            return await asyncio.to_thread(self.repository.reconcile, campaign_id)
        finally:
            self.ownership.release(fd)

    async def _run(self, record: CampaignRecord, fd: int) -> None:
        termination = True
        cleanup = True
        current: PlannedTrial | None = None
        baselines: dict[str, Path] = {}
        map_baseline: Path | None = None

        async def canceled() -> bool:
            saved = await asyncio.to_thread(self.repository.get, record.id)
            record.cancel_requested = saved.cancel_requested
            return self.stopping or saved.cancel_requested

        async def save(kind: str, release: bool = False) -> None:
            await asyncio.to_thread(self.repository.save_owned, record, self.owner, kind, release)

        try:
            record.state = "running"
            for current in record.trials:
                if await canceled():
                    raise CampaignInterrupted("Campaign canceled before the next trial")
                current.state = "starting"
                await save("trial_started")
                cleanup = False
                try:
                    await self.runtime.prepare(record.definition, current.profile, canceled)
                    if await canceled():
                        raise CampaignInterrupted("Campaign canceled before mission dispatch")
                    current.state = "running"
                    await save("trial_started")
                    # Persist dispatch intent before entering an adapter that can send a goal.
                    termination = False
                    result = await self.runtime.execute(
                        record.definition,
                        current,
                        self.root / "artifacts/campaigns" / record.id / current.id,
                        baselines.get(current.profile),
                        map_baseline,
                        canceled,
                        fd,
                    )
                    termination = result.termination_confirmed
                    current.evidence = result.evidence
                    if result.succeeded:
                        current.state = "succeeded"
                        baselines[current.profile] = Path(result.evidence.manifest_path)
                        map_baseline = map_baseline or baselines[current.profile]
                    else:
                        current.state = "canceled" if await canceled() else "failed"
                        raise RuntimeError(
                            result.error or "ROS runner did not confirm a successful trial"
                        )
                    await save("trial_finished")
                finally:
                    cleanup = await self.runtime.stop()
                if not cleanup:
                    raise RuntimeError("Runtime cleanup could not be confirmed")
            record.state = "canceled" if await canceled() else "completed"
        except CampaignInterrupted as exc:
            record.state = "canceled"
            record.error = str(exc)
        except (Exception, asyncio.CancelledError) as exc:
            record.state = "canceled" if self.stopping or record.cancel_requested else "failed"
            record.error = str(exc) or "Worker interrupted"
            logger.warning("Campaign %s stopped: %s", record.id, record.error)
        finally:
            try:
                if not cleanup:
                    try:
                        cleanup = await self.runtime.stop()
                    except Exception:
                        logger.exception("Campaign %s cleanup failed", record.id)
                record.termination_confirmed = termination
                record.cleanup_confirmed = cleanup
                if not (termination and cleanup):
                    record.state = "interrupted"
                for trial in record.trials:
                    if trial.state in ("starting", "running"):
                        trial.state = (
                            "interrupted"
                            if record.state == "interrupted"
                            else ("canceled" if record.state == "canceled" else "failed")
                        )
                    elif trial.state == "planned":
                        trial.state = "canceled"
                # A cancel racing with finalization is retained by the repository.
                await save(record.state, release=termination and cleanup)
            except Exception:
                # An uncommitted final state leaves the durable lease quarantined.
                logger.exception("Campaign %s finalization failed; ownership retained", record.id)
            finally:
                self.ownership.release(fd)
                self.active_id = None
