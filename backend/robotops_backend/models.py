from __future__ import annotations

from enum import Enum
from math import isfinite

from pydantic import BaseModel, Field, field_validator, model_validator


class RuntimeMode(str, Enum):
    MOCK = "mock"
    SIM = "sim"
    REPLAY = "replay"
    REAL = "real"
    UNKNOWN = "unknown"


class ConnectionState(str, Enum):
    CONNECTED = "connected"
    STALE = "stale"
    DISCONNECTED = "disconnected"


class Pose2D(BaseModel):
    x: float
    y: float
    yaw: float

    @field_validator("x", "y", "yaw")
    @classmethod
    def finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("pose values must be finite")
        return value


class MapSnapshot(BaseModel):
    frame_id: str = "map"
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)
    resolution: float = Field(default=0.0, ge=0.0)
    origin: Pose2D = Field(default_factory=lambda: Pose2D(x=0, y=0, yaw=0))
    data: list[int] = Field(default_factory=list)

    @field_validator("data")
    @classmethod
    def occupancy_values(cls, values: list[int]) -> list[int]:
        if any(v < -1 or v > 100 for v in values):
            raise ValueError("occupancy values must be in [-1, 100]")
        return values

    @model_validator(mode="after")
    def dimensions_match_data(self):
        if len(self.data) != self.width * self.height:
            raise ValueError("occupancy data length must equal width * height")
        if self.width > 0 and self.height > 0 and self.resolution <= 0:
            raise ValueError("non-empty maps require positive resolution")
        return self


class ScanPoint(BaseModel):
    x: float
    y: float

    @field_validator("x", "y")
    @classmethod
    def finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("scan points must be finite")
        return value


class RobotSnapshot(BaseModel):
    robot_id: str = "robot-01"
    runtime_mode: RuntimeMode = RuntimeMode.UNKNOWN
    connection: ConnectionState = ConnectionState.DISCONNECTED
    source_timestamp_ns: str | None = None
    received_monotonic_ns: str | None = None
    pose: Pose2D | None = None
    map: MapSnapshot | None = None
    scan: list[ScanPoint] = Field(default_factory=list)
    global_path: list[Pose2D] = Field(default_factory=list)
    local_path: list[Pose2D] = Field(default_factory=list)
    mission_state: str | None = None
    mission_run_id: str | None = None


class Waypoint(BaseModel):
    x: float
    y: float
    yaw: float = 0.0

    @field_validator("x", "y", "yaw")
    @classmethod
    def finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("waypoint values must be finite")
        return value


class MissionRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    waypoints: list[Waypoint] = Field(min_length=1, max_length=100)
    record: bool = True


class MissionSubmission(BaseModel):
    request_id: str
    accepted: bool
    message: str


class MissionCancellation(BaseModel):
    request_id: str
    confirmed: bool
    message: str


class StackMode(str, Enum):
    MAPPING = "mapping"
    NAVIGATION = "navigation"


class StackState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class WorldOption(BaseModel):
    id: str
    label: str
    difficulty: str


class NavigationProfile(BaseModel):
    id: str
    label: str
    planner: str
    controller: str


class MapArtifact(BaseModel):
    id: str
    label: str
    yaml_path: str
    world_id: str | None = None
    created_at_ns: str | None = None
    resolution: float | None = None
    width: int | None = None
    height: int | None = None
    preview_url: str | None = None
    is_latest: bool = False


class ControlOptions(BaseModel):
    worlds: list[WorldOption]
    navigation_profiles: list[NavigationProfile]
    maps: list[MapArtifact]


class StackRequest(BaseModel):
    mode: StackMode
    runtime_mode: RuntimeMode = RuntimeMode.SIM
    world: str = "mapping_lab"
    map_id: str | None = None
    navigation_profile: str | None = None
    headless_rendering: bool = False
    open_rviz: bool = False


class StackStatus(BaseModel):
    state: StackState = StackState.STOPPED
    mode: StackMode | None = None
    runtime_mode: RuntimeMode = RuntimeMode.SIM
    world: str | None = None
    map_id: str | None = None
    navigation_profile: str | None = None
    processes: list[str] = Field(default_factory=list)
    started_at_ns: str | None = None
    stopped_at_ns: str | None = None
    error: str | None = None
    rviz_running: bool = False
    rviz_error: str | None = None


class MapSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    overwrite: bool = False


class MapSaveResult(BaseModel):
    map: MapArtifact
    message: str


class InitialPoseRequest(BaseModel):
    x: float
    y: float
    yaw: float = 0.0

    @field_validator("x", "y", "yaw")
    @classmethod
    def finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("initial pose values must be finite")
        return value


class TeleopRequest(BaseModel):
    linear_x: float = Field(default=0.0, ge=-0.20, le=0.20)
    angular_z: float = Field(default=0.0, ge=-0.50, le=0.50)

    @field_validator("linear_x", "angular_z")
    @classmethod
    def finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("teleop values must be finite")
        return value


class LifecycleNodeStatus(BaseModel):
    name: str
    state: str


class NavigationReadiness(BaseModel):
    ready: bool = False
    phase: str = "idle"
    message: str = "Navigation stack is not running"
    odom_available: bool = False
    scan_available: bool = False
    odom_to_base: bool = False
    map_available: bool = False
    localized: bool = False
    map_to_base: bool = False
    lifecycle_nodes: list[LifecycleNodeStatus] = Field(default_factory=list)
    updated_at_ns: str | None = None


class CommandResult(BaseModel):
    accepted: bool
    message: str
