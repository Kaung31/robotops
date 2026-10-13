"""Simulation orchestration adapter and existing ROS experiment CLI bridge."""

import asyncio
import json
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ..gateway import RobotGateway
from ..models import (
    ConnectionState,
    InitialPoseRequest,
    RuntimeMode,
    StackMode,
    StackRequest,
    StackState,
)
from ..orchestrator import StackOrchestrator
from ..state import TelemetryStore
from .models import CampaignDefinition, PlannedTrial, TrialEvidence

CancelCheck = Callable[[], Awaitable[bool]]


class CampaignInterrupted(Exception):
    pass


@dataclass
class TrialExecution:
    evidence: TrialEvidence
    succeeded: bool
    termination_confirmed: bool
    error: str | None = None


class SimulationTrialRuntime:
    """Only this adapter contains simulation startup assumptions."""

    def __init__(
        self,
        orchestrator: StackOrchestrator,
        gateway: RobotGateway,
        root: Path,
        telemetry: TelemetryStore,
    ):
        self.orchestrator = orchestrator
        self.gateway = gateway
        self.root = root
        self.telemetry = telemetry
        self._trial_directory: Path | None = None

    def supports(self, mode: str) -> bool:
        return mode == RuntimeMode.SIM and self.gateway.mode == RuntimeMode.SIM

    async def idle(self) -> bool:
        return (await asyncio.to_thread(self.orchestrator.status)).state == StackState.STOPPED

    async def prepare(
        self, definition: CampaignDefinition, profile: str, canceled: CancelCheck
    ) -> None:
        self._trial_directory = None
        self.gateway.reset_navigation_readiness()
        await asyncio.to_thread(
            self.orchestrator.start,
            StackRequest(
                mode=StackMode.NAVIGATION,
                runtime_mode=RuntimeMode.SIM,
                world=definition.world,
                map_id=definition.map_id,
                navigation_profile=profile,
                headless_rendering=False,
                open_rviz=False,
            ),
        )
        if await canceled():
            raise CampaignInterrupted("Canceled during stack startup")
        spawn = self.orchestrator.SIM_SPAWNS[definition.world]
        prepare = asyncio.create_task(
            self.gateway.prepare_navigation(
                InitialPoseRequest(x=spawn[0], y=spawn[1], yaw=spawn[2])
            )
        )
        deadline = time.monotonic() + 75
        try:
            while not prepare.done():
                if await canceled():
                    raise CampaignInterrupted("Canceled during navigation preparation")
                if time.monotonic() > deadline:
                    raise TimeoutError("Navigation preparation timed out")
                await asyncio.sleep(0.2)
            await prepare
            while time.monotonic() < deadline:
                if await canceled():
                    raise CampaignInterrupted("Canceled while waiting for navigation")
                stack = await asyncio.to_thread(self.orchestrator.status)
                if stack.state != StackState.RUNNING:
                    raise RuntimeError("Campaign stack stopped or failed during preparation")
                readiness = await self.gateway.navigation_readiness()
                if (
                    readiness.ready
                    and readiness.lifecycle_nodes
                    and all(node.state == "active" for node in readiness.lifecycle_nodes)
                ):
                    return
                await asyncio.sleep(0.4)
            raise TimeoutError("Navigation did not become active")
        finally:
            if not prepare.done():
                prepare.cancel()
                await asyncio.gather(prepare, return_exceptions=True)

    async def stop(self) -> bool:
        status = await asyncio.to_thread(self.orchestrator.stop)
        self.gateway.reset_navigation_readiness()
        if status.shutdown is not None and self._trial_directory is not None:
            (self._trial_directory / "shutdown.json").write_text(
                status.shutdown.model_dump_json(indent=2) + "\n"
            )
        # The report persists until the next stack start, so a retry cannot hide a crash.
        exited_cleanly = status.shutdown is None or status.shutdown.clean
        # Match the existing restart quiet period; no new trial can overlap teardown.
        await asyncio.sleep(1.7)
        deadline = time.monotonic() + 5
        while self.telemetry.latest().connection == ConnectionState.CONNECTED:
            if time.monotonic() >= deadline:
                return False  # An orphan or external publisher still owns live state.
            await asyncio.sleep(0.2)
        return status.state == StackState.STOPPED and not status.processes and exited_cleanly

    async def execute(
        self,
        definition: CampaignDefinition,
        trial: PlannedTrial,
        directory: Path,
        baseline: Path | None,
        map_baseline: Path | None,
        canceled: CancelCheck,
        lease_fd: int,
    ) -> TrialExecution:
        directory.mkdir(parents=True, exist_ok=False)
        self._trial_directory = directory
        software = (await asyncio.to_thread(self.orchestrator.status)).software
        (directory / "software.json").write_text(
            json.dumps(software or {"available": False, "reason": "not recorded"}, indent=2) + "\n"
        )
        config = dict(
            name=definition.name,
            execution_context={"campaign_id": directory.parent.name, "trial_id": trial.id},
            repetitions=1,
            expected=dict(
                runtime_mode=definition.runtime_mode,
                robot_model=definition.robot_model,
                environment=definition.world,
                navigation_profile=trial.profile,
            ),
            mission={"waypoints": [p.model_dump() for p in definition.waypoints]},
            start=definition.start.model_dump(),
            timeouts=definition.timeouts.model_dump(),
        )
        config_path = directory / "config.json"
        config_path.write_text(json.dumps(config, allow_nan=False))
        output = directory / "runner"
        args = [
            sys.executable,
            "-c",
            "from experiment_runner.cli import main; raise SystemExit(main())",
            "run",
            str(config_path),
            "--output",
            str(output),
        ]
        if baseline:
            args.extend(["--baseline", str(baseline)])
        if map_baseline:
            args.extend(["--map-baseline", str(map_baseline)])
        forced = False
        with (directory / "runner.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=self.root,
                stdout=log,
                stderr=log,
                start_new_session=True,
                pass_fds=(lease_fd,),
            )
            waiter = asyncio.create_task(process.wait())
            deadline = (
                time.monotonic()
                + definition.timeouts.response * 24
                + definition.timeouts.trial
                + 30
            )
            interrupt_at = None
            try:
                while not waiter.done():
                    if interrupt_at is None and (await canceled() or time.monotonic() > deadline):
                        with suppress(ProcessLookupError):
                            process.send_signal(signal.SIGINT)
                        interrupt_at = time.monotonic()
                    if (
                        interrupt_at is not None
                        and time.monotonic() - interrupt_at > definition.timeouts.cancel + 10
                    ):
                        forced = True
                        with suppress(ProcessLookupError):
                            process.kill()
                    await asyncio.wait({waiter}, timeout=0.2)
            finally:
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.send_signal(signal.SIGINT)
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(waiter), definition.timeouts.cancel + 10
                        )
                    except TimeoutError:
                        forced = True
                        with suppress(ProcessLookupError):
                            process.kill()
                        await waiter
            code = await waiter
        manifests = list(output.glob("*/manifest.json"))
        if len(manifests) != 1:
            raise RuntimeError("Runner did not produce one manifest; termination is uncertain")
        manifest_path = manifests[0]
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("config") != config or len(manifest.get("trials", [])) > 1:
            raise ValueError("Runner evidence does not match this trial")
        saved = (manifest.get("trials") or [{}])[0]
        succeeded = (
            code == 0
            and manifest["state"] == "completed"
            and saved.get("outcome") == "succeeded"
            and saved.get("action_status") == 4
        )
        confirmed = not forced and (succeeded or manifest.get("termination_confirmed") is True)
        return TrialExecution(
            evidence=TrialEvidence(
                manifest_path=str(manifest_path),
                experiment_id=manifest["experiment_id"],
                mission_run_id=saved.get("run_id"),
                outcome=saved.get("outcome", "failed"),
                metrics=saved.get("metrics", {}),
                validation=saved.get("validation"),
                collision=saved.get("collision"),
            ),
            succeeded=succeeded,
            termination_confirmed=confirmed,
            error=manifest.get("error"),
        )
