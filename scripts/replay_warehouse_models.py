"""Private Warehouse Benchmark v1 playback envelope (W01–W06).

Pose and scan chunks keep the v1 semantics unchanged. The envelope differs from
N0/N2: these recordings cover the whole navigation window, the benchmark is
exploratory (not qualified), and teardown/recorder accounting are disclosed.
"""

from typing import Annotated, Literal

from pydantic import Field, model_validator
from replay_models import (
    ID,
    NS,
    SHA,
    Asset,
    Config,
    Exporter,
    Gap,
    Metric,
    Scene,
    Segment,
    Strict,
    XYTheta,
    offset_us,
)
from replay_v2_models import OriginalV2

SLOTS = ("W01", "W02", "W03", "W04", "W05", "W06")
Slot = Literal["W01", "W02", "W03", "W04", "W05", "W06"]
Profile = Literal["navfn_rpp", "smac_dwb"]
W03_TEARDOWN = (
    "After the trial's evidence was finalized and hashed, stack teardown lost its X "
    "display; gazebo_runner exited -11 (SIGSEGV) and twist_mux exited -2."
)
LIMITATIONS = Literal[
    "EXPLORATORY_BENCHMARK_NOT_QUALIFIED",
    "THREE_TRIALS_PER_CONFIGURATION",
    "PROFILE_BUNDLES_NOT_SINGLE_ALGORITHMS",
    "SINGLE_WORLD_AND_START",
    "SIMULATION_TIME_ONE_HOST",
    "LOCALIZED_TF_NOT_PHYSICAL_TRUTH",
    "NO_NAV2_EVENT_RECONSTRUCTION",
    "DISPLAY_DOWNSAMPLED",
    "NO_ORIGINAL_GIT_REVISION",
    "HASHES_NOT_SIGNATURES",
    "SCOPED_CONTACT_OBSERVATION_ONLY",
    "TEARDOWN_CRASH_AFTER_FINALIZATION",
]


class ExporterWarehouse(Exporter):
    version: Literal["warehouse.v1"] = "warehouse.v1"


class WarehouseSource(Strict):
    id: ID
    kind: Literal[
        "report",
        "mcap",
        "run_metadata",
        "run_result",
        "bag_metadata",
        "runner_manifest",
        "contacts",
        "map_yaml",
        "map_image",
        "matrix",
        "recorder_log",
        "launch_log",
    ]
    sha256: SHA
    integrity: Literal["VERIFIED"] = "VERIFIED"
    # Logs are hashed for traceability only; their content is never exported.
    scope: Literal["original_bound", "audit_snapshot_only", "private_log_not_exported"]


class WarehouseIdentity(Strict):
    campaign_id: ID
    experiment_id: ID
    trial_id: ID
    run_id: ID
    report_id: SHA
    robot_model: Literal["robotops_base"]
    mode: Literal["sim"] = "sim"
    environment: Literal["warehouse_v1"]
    profile: Profile
    map_id: Literal["warehouse_v1"]
    original_config_sha256: SHA
    original_parameters_sha256: SHA
    software_revision: None = None
    software_revision_reason: Literal["UNAVAILABLE_IN_ORIGINAL"] = "UNAVAILABLE_IN_ORIGINAL"


class WarehouseTime(Strict):
    domain: Literal["recorded_ros_simulation"] = "recorded_ros_simulation"
    epoch: Literal[0] = 0
    # mission_start_ns..mission_end_ns is the original duration metric's interval
    # (mission start to navigation end); finalization ends at result_finalized_ns.
    mission_start_ns: NS
    mission_end_ns: NS
    result_finalized_ns: NS
    dispatch_ns: NS
    final_observation_ns: NS
    recorded_start_ns: NS
    recorded_end_ns: NS
    offset_origin_ns: NS
    wall_mapping: None = None


class WarehouseCoverage(Strict):
    navigation_window_recorded: Literal[True] = True
    full_mission_replay: bool
    gaps: list[Gap]
    source_scans: Annotated[int, Field(ge=0)]
    source_scans_without_map_tf: Annotated[int, Field(ge=0)]
    unavailable_scan_stamps_ns: list[NS]
    missing_channels: list[
        Literal[
            "AMCL_POSE",
            "GAZEBO_POSE_TRUTH",
            "NAV2_ACTION_EVENTS",
            "PLANNED_PATH",
            "COSTMAPS",
            "FAULT_EVENTS",
        ]
    ]


class WarehouseConditions(Strict):
    classification: Literal["EXPLORATORY_BENCHMARK_V1"] = "EXPLORATORY_BENCHMARK_V1"
    robot_model: Literal["robotops_base"] = "robotops_base"
    environment: Literal["warehouse_v1"] = "warehouse_v1"
    map_id: Literal["warehouse_v1"] = "warehouse_v1"
    profile: Profile
    waypoints: list[XYTheta] = Field(min_length=5, max_length=5)
    parameters_sha256: SHA
    map_yaml_sha256: SHA
    map_image_sha256: SHA
    requested_start: XYTheta
    start_position_tolerance_m: float = Field(ge=0, allow_inf_nan=False)
    start_yaw_tolerance_rad: float = Field(ge=0, allow_inf_nan=False)
    measured_runner_start: XYTheta
    campaign_repetitions: Literal[1] = 1
    trial_index: Literal[0] = 0
    software_revision: None = None
    random_seed: None = None
    fault_configuration: None = None
    exact_localization_initial_state: Literal["UNPROVEN"] = "UNPROVEN"
    host_resource_conditions: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    historical_install_identity: Literal["NOT_ESTABLISHED"] = "NOT_ESTABLISHED"
    controlled_algorithm_ab: Literal[False] = False
    causal_performance_claim: Literal[False] = False
    statistical_reliability_claim: Literal[False] = False


class Benchmark(Strict):
    id: Literal["warehouse-navigation-v1"] = "warehouse-navigation-v1"
    slot: Slot
    pair: Annotated[int, Field(ge=1, le=3)]
    profile_trial: Annotated[int, Field(ge=1, le=3)]
    order: Literal["AB_BA_AB"] = "AB_BA_AB"
    matrix_sha256: SHA
    adoption: Literal["EXPLORATORY_ADOPTED_WITH_LIMITATIONS"] = (
        "EXPLORATORY_ADOPTED_WITH_LIMITATIONS"
    )
    # Ran through the normal backend campaign path; the W3 qualification harness
    # did not pass and no W4 execution permission is represented here.
    execution_path: Literal["NORMAL_BACKEND_CAMPAIGN"] = "NORMAL_BACKEND_CAMPAIGN"
    qualification: Literal["NOT_QUALIFIED"] = "NOT_QUALIFIED"


class Teardown(Strict):
    """Post-trial stack shutdown, assessed later from the private launch log."""

    status: Literal["NO_CHILD_FAILURE_LOGGED", "CRASHED_AFTER_EVIDENCE_FINALIZED"]
    detail: Literal[W03_TEARDOWN] | None
    assessment: Literal["OFFLINE_LAUNCH_LOG_REVIEW"] = "OFFLINE_LAUNCH_LOG_REVIEW"
    log_association: Literal["STACK_START_PRECEDES_MISSION_SAME_SLOT"] = (
        "STACK_START_PRECEDES_MISSION_SAME_SLOT"
    )
    log_source_ref: Literal["launch_log"] = "launch_log"
    original_campaign_cleanup_confirmed: Literal[True] = True
    original_cleanup_check_included_exit_status: Literal[False] = False
    evidence_finalized_before_teardown: Literal[True] = True

    @model_validator(mode="after")
    def detail_matches(self):
        if (self.status == "CRASHED_AFTER_EVIDENCE_FINALIZED") != (self.detail is not None):
            raise ValueError("Teardown detail conflicts with status")
        return self


class RecorderLoss(Strict):
    assessment: Literal["OFFLINE_RECORDER_LOG_REVIEW"] = "OFFLINE_RECORDER_LOG_REVIEW"
    log_source_ref: Literal["recorder_log"] = "recorder_log"
    accounting_complete: Literal[True]
    transport_lost_messages: Literal[0]
    loss_reports: Literal[0]


ReportLimitation = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^/\\<>]*$")]


class WarehouseManifest(Strict):
    schema_version: Literal[3] = 3
    kind: Literal["robotops.recorded_playback"] = "robotops.recorded_playback"
    dataset_id: Slot
    exporter: ExporterWarehouse
    source_identity: WarehouseIdentity
    sources: list[WarehouseSource]
    assets: list[Asset]
    time: WarehouseTime
    segments: list[Segment]
    coverage: WarehouseCoverage
    scene: Scene
    metrics: list[Metric]
    original_validation: OriginalV2
    original_report_limitations: list[ReportLimitation] = Field(min_length=1, max_length=20)
    conditions: WarehouseConditions
    benchmark: Benchmark
    teardown: Teardown
    recorder_loss: RecorderLoss
    source_trial_index: Literal[0] = 0
    navigation_events: list[None] = Field(default_factory=list, max_length=0)
    limitations: list[LIMITATIONS]
    publication_review: Literal["PRIVATE_NOT_APPROVED_FOR_UPLOAD"] = (
        "PRIVATE_NOT_APPROVED_FOR_UPLOAD"
    )

    @model_validator(mode="after")
    def consistent(self):
        t = self.time
        start, end = int(t.recorded_start_ns), int(t.recorded_end_ns)
        # Dispatch precedes recorder start and the final observation follows
        # finalization; only the original duration interval must be recorded.
        if not (
            int(t.dispatch_ns) <= start <= int(t.mission_start_ns) < int(t.mission_end_ns) <= end
            and end <= int(t.result_finalized_ns) <= int(t.final_observation_ns)
        ):
            raise ValueError("Navigation window must lie inside the recording")
        if t.offset_origin_ns != t.recorded_start_ns:
            raise ValueError("Offset clock origin mismatch")
        last = -1
        for segment in self.segments:
            a, b = int(segment.start_ros_ns), int(segment.end_ros_ns)
            if not last < a <= b or not start <= a <= b <= end:
                raise ValueError("Invalid/overlapping playback segments")
            if segment.start_us != offset_us(a, start) or segment.end_us != offset_us(b, start):
                raise ValueError("Segment offset mismatch")
            last = b
        for gap in self.coverage.gaps:
            if (
                not start
                <= int(gap.start_ros_ns)
                <= int(gap.end_ros_ns)
                <= int(t.result_finalized_ns)
            ):
                raise ValueError("Invalid gap interval")
            if gap.reason == "UNRECORDED_HEAD":
                raise ValueError("Warehouse recordings start before dispatch")
        expected = {
            "mission_ros_seconds": ("s", "metrics"),
            "odom_path_metres": ("m", "metrics"),
            "xy_error_m": ("m", "validation"),
            "yaw_error_rad": ("rad", "validation"),
        }
        if {m.name for m in self.metrics} != set(expected) or len(self.metrics) != len(expected):
            raise ValueError("Metrics incomplete or duplicated")
        for metric in self.metrics:
            unit, category = expected[metric.name]
            if (
                metric.unit != unit
                or metric.pointer != f"/campaign/trials/0/evidence/{category}/{metric.name}"
                or metric.value is None
            ):
                raise ValueError("Metric provenance/unit conflict")
        c, i = self.conditions, self.source_identity
        hashes = {s.id: s.sha256 for s in self.sources}
        if len(hashes) != len(self.sources) or any(s.kind != s.id for s in self.sources):
            raise ValueError("Duplicate or mislabelled source")
        if (
            c.parameters_sha256 != i.original_parameters_sha256
            or c.profile != i.profile
            or c.map_yaml_sha256 != hashes.get("map_yaml")
            or c.map_image_sha256 != hashes.get("map_image")
            or self.benchmark.matrix_sha256 != hashes.get("matrix")
        ):
            raise ValueError("Condition provenance conflict")
        if c.waypoints[-1] != self.original_validation.commanded_final_goal:
            raise ValueError("Mission goal conflict")
        if self.benchmark.slot != self.dataset_id:
            raise ValueError("Benchmark slot conflict")
        crashed = self.teardown.status == "CRASHED_AFTER_EVIDENCE_FINALIZED"
        if crashed != ("TEARDOWN_CRASH_AFTER_FINALIZATION" in self.limitations):
            raise ValueError("Teardown disclosure missing from limitations")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("Duplicate limitation")
        windows = [g for g in self.coverage.gaps if g.reason in ("TF_UNAVAILABLE", "POSE_GAP")]
        inside = [
            g
            for g in windows
            if int(g.end_ros_ns) > int(t.mission_start_ns)
            and int(g.start_ros_ns) < int(t.mission_end_ns)
        ]
        if self.coverage.full_mission_replay != (not inside):
            raise ValueError("Full replay claim conflicts with pose gaps")
        return self


__all__ = [
    "SLOTS",
    "W03_TEARDOWN",
    "Benchmark",
    "Config",
    "RecorderLoss",
    "Teardown",
    "WarehouseManifest",
]
