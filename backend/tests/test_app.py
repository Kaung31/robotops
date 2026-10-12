from fastapi.testclient import TestClient
from robotops_backend.app import create_app
from robotops_backend.models import (
    CommandResult,
    ControlOptions,
    InitialPoseRequest,
    MapArtifact,
    MapSaveResult,
    MissionCancellation,
    MissionRequest,
    MissionSubmission,
    NavigationProfile,
    NavigationReadiness,
    RuntimeMode,
    StackMode,
    StackRequest,
    StackState,
    StackStatus,
    WorldOption,
)
from robotops_backend.state import TelemetryStore


class FakeGateway:
    def __init__(self, telemetry: TelemetryStore, mode: RuntimeMode = RuntimeMode.SIM):
        self.telemetry = telemetry
        self._mode = mode
        self.started = False
        self.closed = False
        self.submitted: list[MissionRequest] = []
        self.canceled: list[str] = []
        self.readiness = NavigationReadiness()
        self.prepare_calls = 0

    @property
    def mode(self) -> RuntimeMode:
        return self._mode

    def start(self) -> None:
        self.started = True
        self.telemetry.set_mode(self._mode)

    def close(self) -> None:
        self.closed = True

    async def submit_mission(self, request: MissionRequest) -> MissionSubmission:
        self.submitted.append(request)
        return MissionSubmission(request_id="req-1", accepted=True, message="accepted")

    async def cancel_mission(self, request_id: str) -> MissionCancellation:
        self.canceled.append(request_id)
        return MissionCancellation(request_id=request_id, confirmed=True, message="canceled")

    async def set_initial_pose(self, request) -> CommandResult:
        return CommandResult(accepted=True, message="pose set")

    async def teleop(self, request) -> CommandResult:
        return CommandResult(accepted=True, message="teleop")

    def reset_navigation_readiness(self) -> None:
        self.readiness = NavigationReadiness(phase="starting", message="starting")

    async def prepare_navigation(self, request) -> NavigationReadiness:
        self.prepare_calls += 1
        self.readiness = NavigationReadiness(
            ready=True,
            phase="ready",
            message="Navigation is ready",
            map_available=True,
            localized=True,
            map_to_base=True,
            lifecycle_nodes=[],
        )
        return self.readiness

    async def navigation_readiness(self) -> NavigationReadiness:
        return self.readiness


class FakeOrchestrator:
    def __init__(self):
        self.current = StackStatus()
        self.started: list[StackRequest] = []
        self.closed = False
        self.rviz_open_calls = 0
        self.rviz_close_calls = 0

    def options(self) -> ControlOptions:
        return ControlOptions(
            worlds=[WorldOption(id="mapping_lab", label="Mapping Lab", difficulty="medium")],
            navigation_profiles=[
                NavigationProfile(
                    id="navfn_rpp",
                    label="NavFn + RPP",
                    planner="NavFn",
                    controller="RPP",
                )
            ],
            maps=[MapArtifact(id="lab", label="Lab", yaml_path="artifacts/maps/lab.yaml")],
        )

    def status(self) -> StackStatus:
        return self.current

    def start(self, request: StackRequest) -> StackStatus:
        self.started.append(request)
        self.current = StackStatus(
            state=StackState.RUNNING,
            mode=request.mode,
            world=request.world,
            map_id=request.map_id,
            navigation_profile=request.navigation_profile,
            processes=["robot", "navigation", "mission"],
            rviz_running=request.open_rviz,
        )
        return self.current

    def open_rviz(self) -> StackStatus:
        if self.current.state != StackState.RUNNING:
            raise RuntimeError("A running RobotOps stack is required before opening RViz")
        self.rviz_open_calls += 1
        self.current.rviz_running = True
        self.current.rviz_error = None
        return self.current

    def close_rviz(self) -> StackStatus:
        self.rviz_close_calls += 1
        self.current.rviz_running = False
        self.current.rviz_error = None
        return self.current

    def stop(self) -> StackStatus:
        self.current = StackStatus(state=StackState.STOPPED)
        return self.current

    def save_map(self, request) -> MapSaveResult:
        return MapSaveResult(
            map=MapArtifact(
                id=request.name,
                label=request.name.title(),
                yaml_path=f"artifacts/maps/{request.name}.yaml",
            ),
            message="Map saved",
        )

    def close(self) -> None:
        self.closed = True


def test_health_and_robot_state_do_not_fake_connection():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    app = create_app(gateway, telemetry)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok", "gateway_mode": "sim"}
        robot = client.get("/api/v1/robot").json()
        assert robot["runtime_mode"] == "sim"
        assert robot["connection"] == "disconnected"
    assert gateway.started and gateway.closed


def test_mission_and_cancel_use_gateway():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    app = create_app(gateway, telemetry)
    with TestClient(app) as client:
        telemetry.publish(runtime_mode=RuntimeMode.SIM)
        response = client.post(
            "/api/v1/missions",
            json={"label": "go", "waypoints": [{"x": 1.0, "y": 2.0, "yaw": 0.0}], "record": True},
        )
        assert response.status_code == 202
        assert response.json()["request_id"] == "req-1"
        assert len(gateway.submitted) == 1
        response = client.delete("/api/v1/missions/req-1")
        assert response.status_code == 200
        assert response.json()["confirmed"] is True
        assert gateway.canceled == ["req-1"]


def test_mission_start_requires_fresh_telemetry_but_cancel_remains_available():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    app = create_app(gateway, telemetry)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/missions",
            json={"label": "go", "waypoints": [{"x": 1, "y": 0, "yaw": 0}], "record": True},
        )
        assert response.status_code == 409
        assert gateway.submitted == []
        response = client.delete("/api/v1/missions/existing")
        assert response.status_code == 200
        assert gateway.canceled == ["existing"]


def test_replay_rejects_mutating_commands_before_gateway():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry, RuntimeMode.REPLAY)
    app = create_app(gateway, telemetry)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/missions",
            json={"label": "no", "waypoints": [{"x": 0, "y": 0, "yaw": 0}], "record": True},
        )
        assert response.status_code == 409
        assert gateway.submitted == []
        response = client.delete("/api/v1/missions/anything")
        assert response.status_code == 409
        assert gateway.canceled == []


def test_websocket_sends_latest_then_update():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    app = create_app(gateway, telemetry)
    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/telemetry/ws") as socket:
            first = socket.receive_json()
            assert first["runtime_mode"] == "sim"
            assert first["connection"] == "disconnected"
            telemetry.publish(runtime_mode=RuntimeMode.SIM)
            second = socket.receive_json()
            assert second["connection"] == "connected"


class TimeoutGateway(FakeGateway):
    async def submit_mission(self, request: MissionRequest) -> MissionSubmission:
        raise TimeoutError("ROS response timed out")

    async def cancel_mission(self, request_id: str) -> MissionCancellation:
        raise TimeoutError("ROS cancellation timed out")


def test_gateway_timeouts_are_reported_as_gateway_timeouts():
    telemetry = TelemetryStore()
    gateway = TimeoutGateway(telemetry)
    app = create_app(gateway, telemetry)
    with TestClient(app) as client:
        telemetry.publish(runtime_mode=RuntimeMode.SIM)
        response = client.post(
            "/api/v1/missions",
            json={"label": "go", "waypoints": [{"x": 1, "y": 0, "yaw": 0}], "record": True},
        )
        assert response.status_code == 504
        response = client.delete("/api/v1/missions/existing")
        assert response.status_code == 504


def test_built_web_can_be_served_same_origin(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text(
        "<html><body>robotops-web</body></html>", encoding="utf-8"
    )
    monkeypatch.setenv("ROBOTOPS_WEB_DIST", str(tmp_path))
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    app = create_app(gateway, telemetry)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "robotops-web" in response.text
        assert client.get("/api/v1/health").status_code == 200


def test_control_center_options_start_stop_and_map_save():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    orchestrator = FakeOrchestrator()
    app = create_app(gateway, telemetry, orchestrator)
    with TestClient(app) as client:
        options = client.get("/api/v1/control/options")
        assert options.status_code == 200
        assert options.json()["navigation_profiles"][0]["id"] == "navfn_rpp"
        response = client.post(
            "/api/v1/control/stack",
            json={
                "mode": "navigation",
                "runtime_mode": "sim",
                "world": "mapping_lab",
                "map_id": "lab",
                "navigation_profile": "navfn_rpp",
                "headless_rendering": False,
                "open_rviz": True,
            },
        )
        assert response.status_code == 202
        assert response.json()["state"] == "running"
        assert response.json()["rviz_running"] is True
        assert orchestrator.started[0].mode == StackMode.NAVIGATION
        assert orchestrator.started[0].open_rviz is True
        closed_rviz = client.delete("/api/v1/control/rviz")
        assert closed_rviz.status_code == 200
        assert closed_rviz.json()["rviz_running"] is False
        opened_rviz = client.post("/api/v1/control/rviz")
        assert opened_rviz.status_code == 202
        assert opened_rviz.json()["rviz_running"] is True
        assert orchestrator.rviz_open_calls == 1
        assert orchestrator.rviz_close_calls == 1
        saved = client.post("/api/v1/maps/save", json={"name": "new_map", "overwrite": False})
        assert saved.status_code == 201
        assert saved.json()["map"]["id"] == "new_map"
        stopped = client.delete("/api/v1/control/stack")
        assert stopped.status_code == 200
        assert stopped.json()["state"] == "stopped"
    assert orchestrator.closed


def test_rviz_requires_running_stack():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    orchestrator = FakeOrchestrator()
    app = create_app(gateway, telemetry, orchestrator)
    with TestClient(app) as client:
        response = client.post("/api/v1/control/rviz")
        assert response.status_code == 409
        assert "running RobotOps stack" in response.json()["detail"]


def test_initial_pose_and_bounded_teleop_use_gateway():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    app = create_app(gateway, telemetry, FakeOrchestrator())
    with TestClient(app) as client:
        telemetry.publish(runtime_mode=RuntimeMode.SIM)
        pose = client.post(
            "/api/v1/localization/initial-pose", json={"x": 0.0, "y": 0.0, "yaw": 0.0}
        )
        assert pose.status_code == 200
        teleop = client.post("/api/v1/teleop", json={"linear_x": 0.12, "angular_z": 0.0})
        assert teleop.status_code == 200
        unsafe = client.post("/api/v1/teleop", json={"linear_x": 1.0, "angular_z": 0.0})
        assert unsafe.status_code == 422


def test_replay_rejects_control_mutations():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry, RuntimeMode.REPLAY)
    app = create_app(gateway, telemetry, FakeOrchestrator())
    with TestClient(app) as client:
        pose = client.post(
            "/api/v1/localization/initial-pose", json={"x": 0.0, "y": 0.0, "yaw": 0.0}
        )
        assert pose.status_code == 409
        teleop = client.post("/api/v1/teleop", json={"linear_x": 0.0, "angular_z": 0.0})
        assert teleop.status_code == 409


def test_navigation_start_auto_prepares_and_readiness_endpoint_reports_ready():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    orchestrator = FakeOrchestrator()
    app = create_app(gateway, telemetry, orchestrator)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/control/stack",
            json={
                "mode": "navigation",
                "runtime_mode": "sim",
                "world": "mapping_lab",
                "map_id": "lab",
                "navigation_profile": "navfn_rpp",
                "headless_rendering": False,
            },
        )
        assert response.status_code == 202
        assert gateway.prepare_calls == 1
        readiness = client.get("/api/v1/navigation/readiness")
        assert readiness.status_code == 200
        assert readiness.json()["ready"] is True


def test_mission_is_blocked_until_navigation_is_ready():
    telemetry = TelemetryStore()
    gateway = FakeGateway(telemetry)
    orchestrator = FakeOrchestrator()
    orchestrator.current = StackStatus(
        state=StackState.RUNNING, mode=StackMode.NAVIGATION, runtime_mode=RuntimeMode.SIM
    )
    gateway.readiness = NavigationReadiness(
        ready=False, phase="waiting_localization", message="Waiting for AMCL localization"
    )
    app = create_app(gateway, telemetry, orchestrator)
    with TestClient(app) as client:
        telemetry.publish(runtime_mode=RuntimeMode.SIM)
        response = client.post(
            "/api/v1/missions",
            json={"label": "go", "waypoints": [{"x": 1, "y": 0, "yaw": 0}], "record": True},
        )
        assert response.status_code == 409
        assert "AMCL" in response.json()["detail"]
        assert gateway.submitted == []


def test_prepare_navigation_observes_nav2_autostart_instead_of_driving_lifecycle():
    import asyncio
    import threading

    from robotops_backend.ros_gateway import RosGateway

    gateway = RosGateway.__new__(RosGateway)
    gateway._mode = RuntimeMode.SIM
    gateway._odom_seen = threading.Event()
    gateway._odom_seen.set()
    gateway._scan_seen = threading.Event()
    gateway._scan_seen.set()
    gateway._map_seen = threading.Event()
    gateway._map_seen.set()

    async def wait_tf(_timeout: float) -> bool:
        return True

    async def wait_transform(_target: str, _source: str, _timeout: float) -> bool:
        return True

    async def readiness() -> NavigationReadiness:
        return NavigationReadiness(ready=True, phase="ready", message="Navigation is ready")

    gateway._wait_transform = wait_transform
    gateway._wait_tf = wait_tf
    gateway._nav_action_ready = lambda: True
    gateway.navigation_readiness = readiness

    result = asyncio.run(gateway.prepare_navigation(InitialPoseRequest(x=0.0, y=0.0, yaw=0.0)))
    assert result.ready is True


def test_ros_gateway_never_drives_nav2_lifecycle_transitions():
    from pathlib import Path

    import robotops_backend.ros_gateway as ros_gateway

    source = Path(ros_gateway.__file__).read_text(encoding="utf-8")
    assert "ChangeState" not in source
    assert "ManageLifecycleNodes" not in source
    assert "_manager_startup" not in source


def test_localization_readiness_uses_functional_tf_and_nav_action():
    import asyncio
    import threading

    from robotops_backend.ros_gateway import RosGateway

    gateway = RosGateway.__new__(RosGateway)
    gateway._readiness_lock = threading.RLock()
    gateway._readiness = NavigationReadiness()
    gateway._odom_seen = threading.Event()
    gateway._odom_seen.set()
    gateway._scan_seen = threading.Event()
    gateway._scan_seen.set()
    gateway._map_seen = threading.Event()
    gateway._map_seen.set()
    gateway._amcl_seen = threading.Event()
    gateway._odom_tf_ready = lambda: True
    gateway._tf_ready = lambda: True
    gateway._nav_action_ready = lambda: True

    async def manager_active(name: str, timeout: float = 3.0) -> bool:
        return False

    async def state(name: str) -> str:
        return "unavailable"

    gateway._manager_is_active = manager_active
    gateway._lifecycle_state = state

    result = asyncio.run(gateway.navigation_readiness())
    assert result.localized is True
    assert result.ready is True
    assert all(item.state == "operational" for item in result.lifecycle_nodes)
