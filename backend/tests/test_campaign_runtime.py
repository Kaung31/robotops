import asyncio
import json
from types import SimpleNamespace

import pytest
from robotops_backend.campaigns import runtime as runtime_module
from robotops_backend.campaigns.runtime import SimulationTrialRuntime
from robotops_backend.models import (
    ConnectionState,
    ProcessExit,
    ShutdownReport,
    StackState,
    StackStatus,
)


class FakeOrchestrator:
    def __init__(self, shutdown):
        self.shutdown = shutdown
        self.stops = 0

    def stop(self):
        self.stops += 1
        return StackStatus(state=StackState.STOPPED, shutdown=self.shutdown)


def make_runtime(tmp_path, shutdown, monkeypatch):
    async def no_wait(_):
        return None

    monkeypatch.setattr(runtime_module.asyncio, "sleep", no_wait)
    gateway = SimpleNamespace(reset_navigation_readiness=lambda: None)
    telemetry = SimpleNamespace(
        latest=lambda: SimpleNamespace(connection=ConnectionState.DISCONNECTED)
    )
    runtime = SimulationTrialRuntime(FakeOrchestrator(shutdown), gateway, tmp_path, telemetry)
    runtime._trial_directory = tmp_path
    return runtime


CRASH = ShutdownReport(
    clean=False,
    processes=[
        ProcessExit(
            name="robot",
            exit_code=0,
            signal_path="group",
            child_failures=["gazebo_runner-2 exit -11"],
            display_lost=True,
        )
    ],
)


@pytest.mark.parametrize(
    ("shutdown", "confirmed"),
    [(ShutdownReport(clean=True), True), (CRASH, False), (None, True)],
)
def test_cleanup_requires_a_clean_exit_report(tmp_path, monkeypatch, shutdown, confirmed):
    runtime = make_runtime(tmp_path, shutdown, monkeypatch)
    assert asyncio.run(runtime.stop()) is confirmed
    written = tmp_path / "shutdown.json"
    assert written.exists() is (shutdown is not None)
    if shutdown is not None:
        assert json.loads(written.read_text())["clean"] is shutdown.clean


def test_retried_stop_cannot_mask_a_teardown_crash(tmp_path, monkeypatch):
    # The orchestrator keeps the last report until the next start; a second stop
    # (the campaign finalizer's retry) must still refuse to confirm cleanup.
    runtime = make_runtime(tmp_path, CRASH, monkeypatch)
    assert asyncio.run(runtime.stop()) is False
    assert asyncio.run(runtime.stop()) is False
    assert runtime.orchestrator.stops == 2
