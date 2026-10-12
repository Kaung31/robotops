from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .campaigns.api import campaign_router
from .campaigns.ownership import RuntimeOwnership
from .campaigns.repository import (
    CampaignConflict,
    CampaignRepository,
    CampaignStorageError,
    SQLiteCampaignRepository,
)
from .campaigns.runtime import SimulationTrialRuntime
from .campaigns.service import CampaignService, TrialRuntime
from .gateway import RobotGateway, UnavailableGateway
from .models import (
    CommandResult,
    ConnectionState,
    ControlOptions,
    InitialPoseRequest,
    MapSaveRequest,
    MapSaveResult,
    MissionCancellation,
    MissionRequest,
    MissionSubmission,
    NavigationReadiness,
    RobotSnapshot,
    RuntimeMode,
    StackMode,
    StackRequest,
    StackStatus,
    TeleopRequest,
)
from .orchestrator import StackOrchestrator
from .state import TelemetryStore


def _gateway_from_environment(telemetry: TelemetryStore) -> RobotGateway:
    gateway = os.getenv("ROBOTOPS_GATEWAY", "unavailable").strip().lower()
    if gateway != "ros":
        return UnavailableGateway(telemetry)
    mode = RuntimeMode(os.getenv("ROBOTOPS_RUNTIME_MODE", "sim").strip().lower())
    from .ros_gateway import RosGateway

    return RosGateway(telemetry, mode)


def create_app(
    gateway: RobotGateway | None = None,
    telemetry: TelemetryStore | None = None,
    orchestrator: StackOrchestrator | None = None,
    campaign_repository: CampaignRepository | None = None,
    campaign_runtime: TrialRuntime | None = None,
    campaign_execution: bool | None = None,
) -> FastAPI:
    store = telemetry or TelemetryStore()
    robot_gateway = gateway or _gateway_from_environment(store)
    stack_orchestrator = orchestrator or StackOrchestrator()
    repo_root = Path(os.getenv("ROBOTOPS_REPO_ROOT", str(Path(__file__).resolve().parents[2])))
    campaigns = campaign_repository or SQLiteCampaignRepository(
        Path(os.getenv("ROBOTOPS_CAMPAIGN_DB", str(repo_root / "artifacts/campaigns.sqlite3")))
    )

    ownership = RuntimeOwnership(repo_root / "artifacts/runtime.lock", campaigns)
    service = CampaignService(
        campaigns,
        ownership,
        campaign_runtime
        or SimulationTrialRuntime(stack_orchestrator, robot_gateway, repo_root, store),
        store,
        repo_root,
        enabled=campaign_execution
        if campaign_execution is not None
        else os.getenv("ROBOTOPS_CAMPAIGN_EXECUTION") == "1",
    )

    async def manual_operation():
        fd = await asyncio.to_thread(ownership.acquire_manual)
        try:
            yield
        finally:
            ownership.release(fd)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.to_thread(campaigns.initialize)
        app.state.telemetry = store
        app.state.gateway = robot_gateway
        app.state.orchestrator = stack_orchestrator
        app.state.campaign_repository = campaigns
        robot_gateway.start()
        app.state.campaign_service = service
        try:
            await service.startup()
            yield
        finally:
            try:
                await service.shutdown()
            finally:
                try:
                    await asyncio.to_thread(stack_orchestrator.close)
                finally:
                    robot_gateway.close()

    app = FastAPI(title="RobotOps API", version="0.1.0", lifespan=lifespan)
    app.include_router(
        campaign_router(campaigns, stack_orchestrator.options, service, repo_root / "artifacts")
    )

    @app.exception_handler(CampaignConflict)
    async def ownership_conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CampaignStorageError)
    async def storage_failure(request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/api/v1/health")
    async def health() -> dict:
        return {"status": "ok", "gateway_mode": robot_gateway.mode.value}

    @app.get("/api/v1/robot", response_model=RobotSnapshot)
    async def robot() -> RobotSnapshot:
        return store.latest()

    @app.get("/api/v1/control/options", response_model=ControlOptions)
    async def control_options() -> ControlOptions:
        return stack_orchestrator.options()

    @app.get("/api/v1/control/stack", response_model=StackStatus)
    async def stack_status() -> StackStatus:
        return stack_orchestrator.status()

    @app.post(
        "/api/v1/control/stack",
        response_model=StackStatus,
        status_code=202,
        dependencies=[Depends(manual_operation)],
    )
    async def start_stack(request: StackRequest) -> StackStatus:
        if request.runtime_mode == RuntimeMode.REAL:
            raise HTTPException(
                status_code=501, detail="Physical robot orchestration is not implemented"
            )
        if request.runtime_mode == RuntimeMode.REPLAY:
            raise HTTPException(
                status_code=409, detail="Replay is read-only and uses a separate workflow"
            )
        try:
            if request.mode == StackMode.NAVIGATION:
                robot_gateway.reset_navigation_readiness()
            started = stack_orchestrator.start(request)
            if request.mode == StackMode.NAVIGATION and request.runtime_mode == RuntimeMode.SIM:
                # Simulation worlds currently spawn robotops_base at map pose 0,0,0.
                # Real hardware deliberately does not use this automatic assumption.
                await robot_gateway.prepare_navigation(InitialPoseRequest(x=0.0, y=0.0, yaw=0.0))
            return started
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete(
        "/api/v1/control/stack",
        response_model=StackStatus,
        dependencies=[Depends(manual_operation)],
    )
    async def stop_stack() -> StackStatus:
        result = stack_orchestrator.stop()
        robot_gateway.reset_navigation_readiness()
        return result

    @app.post("/api/v1/control/rviz", response_model=StackStatus, status_code=202)
    async def open_rviz() -> StackStatus:
        try:
            return stack_orchestrator.open_rviz()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/api/v1/control/rviz", response_model=StackStatus)
    async def close_rviz() -> StackStatus:
        return stack_orchestrator.close_rviz()

    @app.get("/api/v1/navigation/readiness", response_model=NavigationReadiness)
    async def navigation_readiness() -> NavigationReadiness:
        stack = stack_orchestrator.status()
        if stack.state.value != "running" or stack.mode != StackMode.NAVIGATION:
            return NavigationReadiness()
        return await robot_gateway.navigation_readiness()

    @app.post(
        "/api/v1/navigation/prepare",
        response_model=NavigationReadiness,
        dependencies=[Depends(manual_operation)],
    )
    async def prepare_navigation() -> NavigationReadiness:
        stack = stack_orchestrator.status()
        if stack.state.value != "running" or stack.mode != StackMode.NAVIGATION:
            raise HTTPException(status_code=409, detail="A running navigation stack is required")
        if stack.runtime_mode != RuntimeMode.SIM:
            raise HTTPException(
                status_code=409, detail="Automatic localization is simulation-only"
            )
        return await robot_gateway.prepare_navigation(InitialPoseRequest(x=0.0, y=0.0, yaw=0.0))

    @app.get("/api/v1/maps/{map_id}/preview.svg")
    async def map_preview(map_id: str) -> Response:
        try:
            svg = stack_orchestrator.map_preview_svg(map_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=svg,
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )

    @app.post(
        "/api/v1/maps/save",
        response_model=MapSaveResult,
        status_code=201,
        dependencies=[Depends(manual_operation)],
    )
    async def save_map(request: MapSaveRequest) -> MapSaveResult:
        try:
            return stack_orchestrator.save_map(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post(
        "/api/v1/localization/initial-pose",
        response_model=CommandResult,
        dependencies=[Depends(manual_operation)],
    )
    async def set_initial_pose(request: InitialPoseRequest) -> CommandResult:
        live = store.latest()
        if live.runtime_mode == RuntimeMode.REPLAY:
            raise HTTPException(status_code=409, detail="Replay mode is read-only")
        if live.connection != ConnectionState.CONNECTED:
            raise HTTPException(status_code=409, detail="Fresh robot telemetry is required")
        try:
            result = await robot_gateway.set_initial_pose(request)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not result.accepted:
            raise HTTPException(status_code=503, detail=result.message)
        return result

    @app.post(
        "/api/v1/teleop", response_model=CommandResult, dependencies=[Depends(manual_operation)]
    )
    async def teleop(request: TeleopRequest) -> CommandResult:
        live = store.latest()
        if live.runtime_mode == RuntimeMode.REPLAY:
            raise HTTPException(status_code=409, detail="Replay mode is read-only")
        if live.connection != ConnectionState.CONNECTED:
            raise HTTPException(status_code=409, detail="Fresh robot telemetry is required")
        try:
            result = await robot_gateway.teleop(request)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not result.accepted:
            raise HTTPException(status_code=503, detail=result.message)
        return result

    @app.post(
        "/api/v1/missions",
        dependencies=[Depends(manual_operation)],
        response_model=MissionSubmission,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def submit_mission(request: MissionRequest) -> MissionSubmission:
        live = store.latest()
        if live.runtime_mode == RuntimeMode.REPLAY:
            raise HTTPException(status_code=409, detail="Replay mode is read-only")
        if live.connection != ConnectionState.CONNECTED:
            raise HTTPException(status_code=409, detail="Fresh robot telemetry is required")
        stack = stack_orchestrator.status()
        if stack.state.value == "running" and stack.mode == StackMode.NAVIGATION:
            readiness = await robot_gateway.navigation_readiness()
            if not readiness.ready:
                raise HTTPException(status_code=409, detail=readiness.message)
        try:
            result = await robot_gateway.submit_mission(request)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if not result.accepted:
            raise HTTPException(status_code=503, detail=result.message)
        return result

    @app.delete(
        "/api/v1/missions/{request_id}",
        response_model=MissionCancellation,
        dependencies=[Depends(manual_operation)],
    )
    async def cancel_mission(request_id: str) -> MissionCancellation:
        if store.latest().runtime_mode == RuntimeMode.REPLAY:
            raise HTTPException(status_code=409, detail="Replay mode is read-only")
        try:
            return await robot_gateway.cancel_mission(request_id)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.websocket("/api/v1/telemetry/ws")
    async def telemetry_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            async for snapshot in store.subscribe():
                await websocket.send_text(snapshot.model_dump_json())
        except WebSocketDisconnect:
            return

    web_dist = Path(
        os.getenv(
            "ROBOTOPS_WEB_DIST",
            str(Path(__file__).resolve().parents[2] / "web" / "dist"),
        )
    )
    if web_dist.is_dir():
        # Mount last so /api routes and the telemetry WebSocket keep priority.
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app


app = create_app()
