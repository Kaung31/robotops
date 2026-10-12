from __future__ import annotations

from typing import Protocol

from .models import (
    CommandResult,
    InitialPoseRequest,
    MissionCancellation,
    MissionRequest,
    MissionSubmission,
    NavigationReadiness,
    RuntimeMode,
    TeleopRequest,
)
from .state import TelemetryStore


class RobotGateway(Protocol):
    @property
    def mode(self) -> RuntimeMode: ...

    def start(self) -> None: ...

    def close(self) -> None: ...

    async def submit_mission(self, request: MissionRequest) -> MissionSubmission: ...

    async def cancel_mission(self, request_id: str) -> MissionCancellation: ...

    async def set_initial_pose(self, request: InitialPoseRequest) -> CommandResult: ...

    async def teleop(self, request: TeleopRequest) -> CommandResult: ...

    def reset_navigation_readiness(self) -> None: ...

    async def prepare_navigation(self, request: InitialPoseRequest) -> NavigationReadiness: ...

    async def navigation_readiness(self) -> NavigationReadiness: ...


class UnavailableGateway:
    def __init__(self, telemetry: TelemetryStore):
        self.telemetry = telemetry

    @property
    def mode(self) -> RuntimeMode:
        return RuntimeMode.UNKNOWN

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def submit_mission(self, request: MissionRequest) -> MissionSubmission:
        return MissionSubmission(
            request_id="unavailable", accepted=False, message="ROS gateway is unavailable"
        )

    async def cancel_mission(self, request_id: str) -> MissionCancellation:
        return MissionCancellation(
            request_id=request_id, confirmed=False, message="ROS gateway is unavailable"
        )

    async def set_initial_pose(self, request: InitialPoseRequest) -> CommandResult:
        return CommandResult(accepted=False, message="ROS gateway is unavailable")

    async def teleop(self, request: TeleopRequest) -> CommandResult:
        return CommandResult(accepted=False, message="ROS gateway is unavailable")

    def reset_navigation_readiness(self) -> None:
        return None

    async def prepare_navigation(self, request: InitialPoseRequest) -> NavigationReadiness:
        return NavigationReadiness(phase="unavailable", message="ROS gateway is unavailable")

    async def navigation_readiness(self) -> NavigationReadiness:
        return NavigationReadiness(phase="unavailable", message="ROS gateway is unavailable")
