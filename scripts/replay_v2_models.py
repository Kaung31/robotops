"""Private N0/N2-only v2 envelope; unchanged v1 pose/scan chunk semantics."""

from typing import Annotated, Literal

from pydantic import Field, model_validator
from replay_models import SHA, Exporter, Manifest, Original, Strict, XYTheta


class ExporterV2(Exporter):
    version: Literal["p4b.baselines.v2"] = "p4b.baselines.v2"


class MissionAction(Strict):
    owner: Literal["mission_manager"] = "mission_manager"
    observer: Literal["experiment_runner"] = "experiment_runner"
    action_type: Literal["robotops_interfaces/action/ExecuteMission"] = (
        "robotops_interfaces/action/ExecuteMission"
    )
    action_name: Literal["missions/execute"] = "missions/execute"
    scope: Literal["SAVED_MISSION_ACTION_RESULT_SNAPSHOT"] = "SAVED_MISSION_ACTION_RESULT_SNAPSHOT"
    source_ref: Literal["report"] = "report"
    pointer: Literal["/campaign/trials/0/evidence/validation/action_status"] = (
        "/campaign/trials/0/evidence/validation/action_status"
    )
    runner_source_ref: Literal["runner_manifest"] = "runner_manifest"
    runner_pointer: Literal["/trials/0/action_status"] = "/trials/0/action_status"
    quality: Literal["AVAILABLE", "MISSING", "INVALID", "CONFLICT"]
    status_name: Literal["STATUS_SUCCEEDED"] | None
    event_time_ns: None = None
    nav2_execution_start_assessable: Literal[False] = False
    recorded_action_stream: Literal[False] = False


class OriginalV2(Original):
    action_status: Annotated[int, Field(ge=0, le=6)] | None = None
    action_status_reason: Literal["AVAILABLE", "MISSING", "INVALID", "CONFLICT"]
    mission_action: MissionAction

    @model_validator(mode="after")
    def action_consistency(self):
        a = self.mission_action
        if self.action_status_reason != a.quality:
            raise ValueError("Action quality conflict")
        if a.quality == "AVAILABLE":
            if self.action_status != 4 or a.status_name != "STATUS_SUCCEEDED":
                raise ValueError("Successful baseline action evidence conflict")
        elif self.action_status is not None or a.status_name is not None:
            raise ValueError("Unavailable action must not carry a status")
        return self


class Conditions(Strict):
    classification: Literal["OBSERVATIONAL_REPEATED_BASELINES"] = (
        "OBSERVATIONAL_REPEATED_BASELINES"
    )
    robot_model: Literal["robotops_base"] = "robotops_base"
    environment: Literal["mapping_lab"] = "mapping_lab"
    map_id: Literal["control_pad_v1"] = "control_pad_v1"
    profile: Literal["navfn_rpp"] = "navfn_rpp"
    waypoints: list[XYTheta] = Field(min_length=2, max_length=2)
    parameters_sha256: SHA
    map_yaml_sha256: SHA
    map_image_sha256: SHA
    requested_start: XYTheta
    start_position_tolerance_m: float = Field(ge=0, allow_inf_nan=False)
    start_yaw_tolerance_rad: float = Field(ge=0, allow_inf_nan=False)
    measured_runner_start: XYTheta
    campaign_repetitions: Literal[1, 2]
    trial_index: Literal[0] = 0
    software_revision: None = None
    random_seed: None = None
    exact_localization_initial_state: Literal["UNPROVEN"] = "UNPROVEN"
    host_resource_conditions: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    historical_world_binary_identity: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    recording_coverage: Literal["PER_DATASET_SEE_TIME_AND_COVERAGE"] = (
        "PER_DATASET_SEE_TIME_AND_COVERAGE"
    )
    controlled_algorithm_ab: Literal[False] = False
    causal_performance_claim: Literal[False] = False
    statistical_reliability_claim: Literal[False] = False


class ManifestV2(Manifest):
    schema_version: Literal[2] = 2
    dataset_id: Literal["N0", "N2"]
    exporter: ExporterV2
    original_validation: OriginalV2
    conditions: Conditions
    source_trial_index: Literal[0] = 0

    @model_validator(mode="after")
    def conditions_consistent(self):
        c = self.conditions
        i = self.source_identity
        if c.parameters_sha256 != i.original_parameters_sha256:
            raise ValueError("Parameter provenance conflict")
        hashes = {s.id: s.sha256 for s in self.sources}
        if c.map_yaml_sha256 != hashes.get("map_yaml") or c.map_image_sha256 != hashes.get(
            "map_image"
        ):
            raise ValueError("Map provenance conflict")
        if c.waypoints[-1] != self.original_validation.commanded_final_goal:
            raise ValueError("Mission goal conflict")
        return self
