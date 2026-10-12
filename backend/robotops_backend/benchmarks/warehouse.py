"""Strict offline warehouse matrix and evidence references. No robot command paths."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ..campaigns.models import CampaignDefinition, CampaignPose, CampaignTimeouts, StartCondition

SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
UUID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
ORDER = ("navfn_rpp", "smac_dwb", "smac_dwb", "navfn_rpp", "navfn_rpp", "smac_dwb")
SCENARIO = "ros2_ws/src/robot_simulation/config/warehouse_v1.json"
WORLD = "ros2_ws/src/robot_simulation/worlds/warehouse_v1.sdf"
MAP = "artifacts/maps/warehouse_v1"
SHARED = (
    "ros2_ws/src/robot_navigation/config/navigation.yaml",
    "ros2_ws/src/robot_navigation/config/localization.yaml",
    "ros2_ws/src/robot_navigation/robot_navigation/navigation_config.py",
    "ros2_ws/src/robot_navigation/launch/navigation.launch.py",
    "ros2_ws/src/robot_description/config/geometry.yaml",
    "ros2_ws/src/robot_description/urdf/base.xacro",
    "ros2_ws/src/robot_control/config/controllers.yaml",
    "ros2_ws/src/robot_control/config/mux.yaml",
    "ros2_ws/src/robot_control/config/guard.yaml",
    "ros2_ws/src/robot_recorder/config/recording.yaml",
    "ros2_ws/src/mission_manager/config/mission.yaml",
    "ros2_ws/src/robot_simulation/config/bridge.yaml",
    "ros2_ws/src/robot_simulation/urdf/gazebo.urdf.xacro",
    "ros2_ws/src/robot_simulation/launch/gazebo.launch.py",
    "ros2_ws/src/robot_bringup/launch/robot.launch.py",
    "ros2_ws/src/robot_simulation/src/gazebo_runner.cpp",
    "scripts/warehouse_scenario.py",
)
WAYPOINTS = [
    {"x": 3.0, "y": 0.0, "yaw": math.pi / 2},
    {"x": 3.0, "y": 7.0, "yaw": 0.0},
    {"x": 5.0, "y": 7.0, "yaw": -math.pi / 2},
    {"x": 5.0, "y": 0.0, "yaw": math.pi},
    {"x": 0.0, "y": 0.0, "yaw": 0.0},
]
START = {"x": 0.0, "y": 0.0, "yaw": 0.0, "position_tolerance": 0.35, "yaw_tolerance": 0.4}
TIMEOUTS = {"response": 15.0, "trial": 600.0, "cancel": 30.0}
POLICY = {
    "xy_tolerance_m": 0.2,
    "yaw_tolerance_rad": 0.25,
    "tf_max_age_s": 1.0,
    "localization_max_age_s": 5.0,
    "max_xy_variance_m2": 0.25,
    "max_yaw_variance_rad2": 0.25,
}


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def confined_file(root: Path, relative: str, limit: int) -> Path:
    p = Path(relative)
    if p.is_absolute() or not p.parts or any(v in (".", "..") for v in p.parts):
        raise ValueError("Expected a bounded relative file path")
    root = root.resolve(strict=True)
    path = root / p
    if any((root / Path(*p.parts[:n])).is_symlink() for n in range(1, len(p.parts) + 1)):
        raise ValueError("Symlink not allowed")
    path.resolve(strict=True).relative_to(root)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Not a bounded regular configuration file")
    return path


def file_bytes(root: Path, relative: str) -> bytes:
    return confined_file(root, relative, 16 * 1024 * 1024).read_bytes()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class FilePin(Strict):
    path: str
    sha256: SHA

    def verify(self, root: Path) -> None:
        limit = 8 * 1024**3 if self.path.startswith("artifacts/") else 16 * 1024 * 1024
        path = confined_file(root, self.path, limit)
        hashed = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                hashed.update(chunk)
        if hashed.hexdigest() != self.sha256:
            raise ValueError(f"Hash mismatch: {self.path}")


class Profile(Strict):
    source: FilePin
    effective_parameters_sha256: SHA
    provenance: Literal["UNKNOWN_PUBLIC_INCLUSION_HELD"]


class Scenario(Strict):
    id: Literal["warehouse_v1"]
    qualification: Literal["OFFLINE_ONLY_RUNTIME_UNQUALIFIED"]
    descriptor: FilePin
    world: FilePin
    map_yaml: FilePin
    map_image: FilePin
    map_metadata: FilePin
    seed: None = None
    initial_conditions: Literal["REQUESTED_ONLY_NOT_OBSERVED"]
    stochastic_determinism: Literal["UNQUALIFIED_SEEDS_UNKNOWN"]


class Mission(Strict):
    frame: Literal["map"]
    position_unit: Literal["m"]
    yaw_unit: Literal["rad"]
    waypoints: list[CampaignPose]
    start: StartCondition
    timeouts: CampaignTimeouts
    validation_policy: dict[str, float]

    @model_validator(mode="after")
    def approved(self):
        if (
            [v.model_dump() for v in self.waypoints] != WAYPOINTS
            or self.start.model_dump() != START
            or self.timeouts.model_dump() != TIMEOUTS
            or self.validation_policy != POLICY
        ):
            raise ValueError("Mission/policy differs from approved warehouse specification")
        return self


class Slot(Strict):
    slot: Literal["W01", "W02", "W03", "W04", "W05", "W06"]
    profile: Literal["navfn_rpp", "smac_dwb"]
    profile_trial: Annotated[StrictInt, Field(ge=1, le=3)]
    pair: Annotated[StrictInt, Field(ge=1, le=3)]
    state: Literal["PLANNED"]
    config_ref: str
    config_sha256: SHA


class WarehouseMatrix(Strict):
    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    id: Literal["warehouse-navigation-v1"]
    authority: Literal["OFFLINE_PLAN_NOT_EXECUTION_AUTHORIZATION"]
    comparison: Literal["PLANNER_CONTROLLER_BUNDLES_N3_NO_SUPERIORITY_CLAIM"]
    execution_approved: bool
    publication_approved: bool
    scenario: Scenario
    mission: Mission
    profiles: dict[str, Profile]
    shared: list[FilePin]
    trials: list[Slot] = Field(min_length=6, max_length=6)
    failure_policy: Literal["STOP_NO_AUTOMATIC_RETRY_OR_REPLACEMENT"]
    reset_policy: Literal["FRESH_OWNED_STACK_PER_SLOT"]

    @model_validator(mode="after")
    def exact_matrix(self):
        if self.execution_approved or self.publication_approved:
            raise ValueError("Offline matrix cannot authorise execution/publication")
        if set(self.profiles) != {"navfn_rpp", "smac_dwb"}:
            raise ValueError("Exactly two approved profiles required")
        if [p.path for p in self.shared] != list(SHARED):
            raise ValueError("Shared source inventory differs")
        refs = [s.config_ref for s in self.trials]
        if len(set(refs)) != 6:
            raise ValueError("Duplicate configuration reference")
        counts: dict[str, int] = {}
        for i, s in enumerate(self.trials):
            counts[s.profile] = counts.get(s.profile, 0) + 1
            if (
                s.slot != f"W{i + 1:02d}"
                or s.profile != ORDER[i]
                or s.profile_trial != counts[s.profile]
                or s.pair != i // 2 + 1
                or s.config_ref != f"benchmarks/warehouse_v1/campaigns/{s.slot}.json"
            ):
                raise ValueError("Slots/order/profile trial identities differ")
        paths = {
            "descriptor": SCENARIO,
            "world": WORLD,
            "map_yaml": MAP + ".yaml",
            "map_image": MAP + ".pgm",
            "map_metadata": MAP + ".robotops.json",
        }
        for name, path in paths.items():
            if getattr(self.scenario, name).path != path:
                raise ValueError("Unexpected scenario/configuration path")
        for name, p in self.profiles.items():
            if p.source.path != f"ros2_ws/src/robot_navigation/config/profiles/{name}.yaml":
                raise ValueError("Profile source identity mismatch")
        return self


def validate_warehouse_map(root: Path, yaml_path: Path) -> None:
    """Require explicit association/hash binding for warehouse only; legacy maps unchanged."""
    relative = yaml_path.relative_to(root).as_posix()
    metadata = json.loads(file_bytes(root, relative.removesuffix(".yaml") + ".robotops.json"))
    if (
        metadata.get("world_id") != "warehouse_v1"
        or metadata.get("map_id") != "warehouse_v1"
        or metadata.get("map_source") != "ANALYTIC_COLLISION_GEOMETRY_NOT_SLAM"
    ):
        raise ValueError("Warehouse requires explicit analytic map/world association")
    import yaml

    content = yaml.safe_load(file_bytes(root, relative))
    if content.get("image") != yaml_path.with_suffix(".pgm").name:
        raise ValueError("Warehouse map image must match its bound image file")
    for key, path in {
        "geometry_sha256": SCENARIO,
        "world_sha256": WORLD,
        "map_yaml_sha256": relative,
        "map_image_sha256": relative.removesuffix(".yaml") + ".pgm",
    }.items():
        if metadata.get(key) != digest(file_bytes(root, path)):
            raise ValueError(f"Warehouse association hash mismatch: {key}")


def parameters(root: Path) -> dict[str, dict]:
    """Existing pure composer; never imports rclpy or starts ROS."""
    source = root / "ros2_ws/src/robot_navigation/robot_navigation/navigation_config.py"
    spec = importlib.util.spec_from_file_location("warehouse_navigation_parameters", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = root / "ros2_ws/src/robot_navigation/config"
    geometry = root / "ros2_ws/src/robot_description/config/geometry.yaml"
    return {p: module.navigation_parameters(config, p, geometry, True) for p in set(ORDER)}


def validate_parameters(values: dict[str, dict]) -> None:
    shared = []
    for profile in ("navfn_rpp", "smac_dwb"):
        value = json.loads(canonical(values[profile]))
        del value["planner_server"]["ros__parameters"]["GridBased"]
        del value["controller_server"]["ros__parameters"]["FollowPath"]
        shared.append(value)
    if shared[0] != shared[1]:
        raise ValueError("Shared effective navigation parameters differ")


def campaign(slot: str, profile: str, mission: Mission) -> CampaignDefinition:
    return CampaignDefinition(
        name=f"warehouse-navigation-v1-{slot}",
        runtime_mode="sim",
        robot_model="robotops_base",
        world="warehouse_v1",
        map_id="warehouse_v1",
        profiles=[profile],
        repetitions=1,
        waypoints=mission.waypoints,
        start=mission.start,
        timeouts=mission.timeouts,
    )


def validate_matrix(root: Path, path: Path) -> WarehouseMatrix:
    m = WarehouseMatrix.model_validate_json(path.read_bytes())
    for pin in [
        m.scenario.descriptor,
        m.scenario.world,
        m.scenario.map_yaml,
        m.scenario.map_image,
        m.scenario.map_metadata,
        *m.shared,
        *[p.source for p in m.profiles.values()],
    ]:
        pin.verify(root)
    validate_warehouse_map(root, root / m.scenario.map_yaml.path)
    # This pure generator is hash-pinned above; compare actual bytes with one geometry source.
    spec = importlib.util.spec_from_file_location(
        "warehouse_geometry", root / "scripts/warehouse_scenario.py"
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    geometry = generator.load_geometry(root / SCENARIO)
    generator.validate_support_floor(
        file_bytes(root, WORLD),
        file_bytes(root, "ros2_ws/src/robot_simulation/urdf/gazebo.urdf.xacro"),
    )
    map_yaml, image = generator.map_bytes(geometry)
    expected = {
        WORLD: generator.world_bytes(geometry),
        MAP + ".yaml": map_yaml,
        MAP + ".pgm": image,
    }
    for relative, data in expected.items():
        if file_bytes(root, relative) != data:
            raise ValueError("World/map differs from deterministic geometry generation")
    effective = parameters(root)
    validate_parameters(effective)
    for name, value in effective.items():
        if digest(canonical(value)) != m.profiles[name].effective_parameters_sha256:
            raise ValueError("Effective parameter hash mismatch")
    for slot in m.trials:
        content = file_bytes(root, slot.config_ref)
        if digest(content) != slot.config_sha256:
            raise ValueError("Campaign configuration hash mismatch")
        proposal = CampaignDefinition.model_validate_json(content)
        if proposal != campaign(slot.slot, slot.profile, m.mission):
            raise ValueError("Campaign does not match matrix scenario/map/profile/mission")
    return m


class Observations(Strict):
    original_outcome: Literal["UNAVAILABLE", "succeeded", "failed", "canceled", "interrupted"]
    final_xy_m: float | None
    final_yaw_rad: float | None
    duration_ros_s: float | None
    odometry_m: float | None
    recording_coverage: Literal["UNAVAILABLE", "UNKNOWN", "PARTIAL", "COMPLETE"]
    initial_conditions: Literal["UNAVAILABLE", "UNKNOWN", "OBSERVED"]
    random_seed: None = None
    gaps: list[str]

    @model_validator(mode="after")
    def availability(self):
        values = [self.final_xy_m, self.final_yaw_rad, self.duration_ros_s, self.odometry_m]
        if any(v is not None and v < 0 for v in values):
            raise ValueError("Negative metric")
        if self.original_outcome == "UNAVAILABLE" and any(v is not None for v in values):
            raise ValueError("Unavailable observations cannot carry measurements")
        return self


class EvidenceSlot(Strict):
    slot: Literal["W01", "W02", "W03", "W04", "W05", "W06"]
    state: Literal["PLANNED", "NOT_RUN", "ATTEMPTED"]
    reason: str | None
    campaign_id: UUID | None
    trial_id: UUID | None
    experiment_id: str | None
    mission_run_id: UUID | None
    files: list[FilePin]
    availability: Literal["UNAVAILABLE", "INCOMPLETE", "UNASSESSED"]
    observations: Observations

    @model_validator(mode="after")
    def honest(self):
        ids = [self.campaign_id, self.trial_id, self.experiment_id, self.mission_run_id]
        if len({p.path for p in self.files}) != len(self.files):
            raise ValueError("Duplicate evidence reference")
        if self.state != "ATTEMPTED":
            if (
                any(v is not None for v in ids)
                or self.files
                or self.availability != "UNAVAILABLE"
                or self.observations.original_outcome != "UNAVAILABLE"
                or self.observations.recording_coverage != "UNAVAILABLE"
                or self.observations.initial_conditions != "UNAVAILABLE"
                or self.observations.gaps
            ):
                raise ValueError("Unexecuted slot cannot contain runtime evidence")
        elif self.availability == "UNAVAILABLE" and self.files:
            raise ValueError("Unavailable evidence cannot contain files")
        if self.state in ("NOT_RUN", "ATTEMPTED") and not self.reason:
            raise ValueError("Non-planned state requires an explanation")
        if self.availability == "UNASSESSED" and (not all(ids) or not self.files):
            raise ValueError("Evidence references incomplete; use INCOMPLETE")
        # Populated measurements require a future source-to-index audit, not manual input.
        if self.observations.original_outcome != "UNAVAILABLE":
            raise ValueError("Original measurement import is deferred to qualified evidence audit")
        return self


class EvidenceIndex(Strict):
    schema_version: Annotated[StrictInt, Field(ge=1, le=1)]
    matrix_sha256: SHA
    qualification: Literal["UNASSESSED_NO_EXPERIMENT_VERDICT"]
    slots: list[EvidenceSlot] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def unique(self):
        if [s.slot for s in self.slots] != [f"W{i:02d}" for i in range(1, 7)]:
            raise ValueError("Evidence index must retain all six unique ordered slots")
        for field in ("campaign_id", "trial_id", "experiment_id", "mission_run_id"):
            ids = [getattr(s, field) for s in self.slots if getattr(s, field) is not None]
            if len(set(ids)) != len(ids):
                raise ValueError("Runtime identity reused across slots")
        return self


def validate_evidence_index(root: Path, path: Path, matrix_path: Path) -> EvidenceIndex:
    validate_matrix(root, matrix_path)
    index = EvidenceIndex.model_validate_json(path.read_bytes())
    if index.matrix_sha256 != digest(matrix_path.read_bytes()):
        raise ValueError("Evidence index matrix hash mismatch")
    for slot in index.slots:
        for pin in slot.files:
            if not pin.path.startswith("artifacts/"):
                raise ValueError("Original evidence must remain private")
            pin.verify(root)
    return index
