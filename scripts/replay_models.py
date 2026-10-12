"""Private playback v1 schemas and pure coordinate/time validation helpers."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NS = Annotated[str, Field(pattern=r"^[0-9]+$")]
SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ID = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,128}$")]
Finite = Annotated[float, Field(allow_inf_nan=False)]
Offset = Annotated[int, Field(ge=0, le=2**53 - 1)]
Vec3 = Annotated[list[Finite], Field(min_length=3, max_length=3)]
Quat = Annotated[list[Finite], Field(min_length=4, max_length=4)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Transform(Strict):
    position: Vec3
    quaternion: Quat

    @model_validator(mode="after")
    def normalized(self):
        if abs(sum(x * x for x in self.quaternion) - 1) > 1e-6:
            raise ValueError("Non-normalized quaternion")
        return self


class Ref(Strict):
    source_ref: Literal["mcap"] = "mcap"
    topic: Literal["/tf", "/tf_static", "/odom", "/scan"]
    ordinal: Annotated[int, Field(ge=1)]
    ros_ns: NS
    cdr_sha256: SHA
    transform_index: Annotated[int, Field(ge=0)] | None = None


class Pose(Strict):
    segment_id: ID | None
    ros_ns: NS
    offset_us: Offset
    frame: Literal["map"] = "map"
    source_kind: Literal["localized_tf"] = "localized_tf"
    transform: Transform | None
    quality: Literal["SUPPORTED_TF", "TF_UNAVAILABLE"]
    anchor: Ref
    tf_refs: list[Ref]

    @model_validator(mode="after")
    def quality_matches(self):
        if (self.quality == "SUPPORTED_TF") != (self.transform is not None):
            raise ValueError("Pose quality conflicts with data")
        if (self.transform is not None) != (self.segment_id is not None):
            raise ValueError("Pose segment conflicts with validity")
        return self


class Scan(Strict):
    segment_id: ID | None
    ros_ns: NS
    offset_us: Offset
    frame: Literal["lidar_link"] = "lidar_link"
    angle_min_rad: Finite
    angle_increment_rad: Finite
    range_min_m: Finite
    range_max_m: Finite
    original_ray_count: Literal[360] = 360
    selected_indices: list[Annotated[int, Field(ge=0, lt=360)]]
    ranges_m: list[Finite | None]
    validity: list[Literal["valid", "no_return", "invalid_nan", "out_of_bounds"]]
    map_base: Transform | None
    base_lidar: Transform | None
    map_quality: Literal["SUPPORTED_TF", "TF_UNAVAILABLE"]
    anchor: Ref
    tf_refs: list[Ref]

    @model_validator(mode="after")
    def consistent(self):
        if not len(self.selected_indices) == len(self.ranges_m) == len(self.validity):
            raise ValueError("Scan index/range/quality lengths differ")
        if self.selected_indices != sorted(set(self.selected_indices)):
            raise ValueError("Scan indices must be unique and ordered")
        if self.range_min_m < 0 or self.range_max_m <= self.range_min_m:
            raise ValueError("Invalid range bounds")
        for value, reason in zip(self.ranges_m, self.validity, strict=True):
            if reason == "valid":
                if value is None or not self.range_min_m <= value <= self.range_max_m:
                    raise ValueError("Invalid valid ray")
            elif value is not None:
                raise ValueError("Invalid ray must be null")
        if (self.map_quality == "SUPPORTED_TF") != (self.map_base is not None):
            raise ValueError("Scan TF quality mismatch")
        if (self.map_base is not None) != (self.segment_id is not None):
            raise ValueError("Scan segment mismatch")
        return self


class PoseChunk(Strict):
    schema_version: Literal[1] = 1
    kind: Literal["robotops.playback_poses"] = "robotops.playback_poses"
    samples: list[Pose]


class ScanChunk(Strict):
    schema_version: Literal[1] = 1
    kind: Literal["robotops.playback_scans"] = "robotops.playback_scans"
    samples: list[Scan]


class Asset(Strict):
    path: Annotated[
        str, Field(pattern=r"^(poses-[0-9]{3}\.json\.gz|scans-[0-9]{3}\.json\.gz|map\.pgm\.gz)$")
    ]
    kind: Literal["poses", "scans", "map"]
    schema_version: Literal[1] = 1
    bytes: Annotated[int, Field(gt=0, le=1024 * 1024)]
    sha256: SHA
    start_ros_ns: NS | None
    end_ros_ns: NS | None


class Source(Strict):
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
    ]
    sha256: SHA
    integrity: Literal["VERIFIED"] = "VERIFIED"
    scope: Literal["original_bound", "audit_snapshot_only"]


class Identity(Strict):
    campaign_id: ID
    experiment_id: ID
    trial_id: ID
    run_id: ID
    report_id: SHA
    robot_model: Literal["robotops_base"]
    mode: Literal["sim"] = "sim"
    environment: Literal["mapping_lab"]
    profile: Literal["navfn_rpp"]
    map_id: Literal["control_pad_v1"]
    original_config_sha256: SHA
    original_parameters_sha256: SHA
    software_revision: None = None
    software_revision_reason: Literal["UNAVAILABLE_IN_ORIGINAL"] = "UNAVAILABLE_IN_ORIGINAL"


class Config(Strict):
    pose_period_ns: Literal[50000000] = 50000000
    scan_stride: Literal[2] = 2
    ray_stride: Literal[4] = 4
    pose_gap_ns: Literal[100000000] = 100000000
    tf_bracket_gap_ns: Literal[250000000] = 250000000
    extrapolate: Literal[False] = False
    display_samples_are_authoritative_metrics: Literal[False] = False


class Exporter(Strict):
    version: Literal["p2.n0.v1"] = "p2.n0.v1"
    code_sha256: SHA
    config_sha256: SHA
    config: Config


class Time(Strict):
    domain: Literal["recorded_ros_simulation"] = "recorded_ros_simulation"
    epoch: Literal[0] = 0
    mission_start_ns: NS
    mission_end_ns: NS
    dispatch_ns: NS
    final_observation_ns: NS
    recorded_start_ns: NS
    recorded_end_ns: NS
    offset_origin_ns: NS
    wall_mapping: None = None


class Gap(Strict):
    start_ros_ns: NS
    end_ros_ns: NS
    reason: Literal[
        "UNRECORDED_HEAD",
        "UNRECORDED_TAIL",
        "TF_UNAVAILABLE",
        "POSE_GAP",
        "DISPLAY_POSE_HEAD",
        "DISPLAY_POSE_TAIL",
    ]


class Segment(Strict):
    id: ID
    epoch: Literal[0] = 0
    start_ros_ns: NS
    end_ros_ns: NS
    start_us: Offset
    end_us: Offset
    frame: Literal["map"] = "map"
    interpolate_within_max_gap_ns: Literal[100000000] = 100000000
    interpolate_across_segments: Literal[False] = False


class Coverage(Strict):
    full_mission_replay: Literal[False] = False
    gaps: list[Gap]
    source_scans: Annotated[int, Field(ge=0)]
    source_scans_without_map_tf: Annotated[int, Field(ge=0)]
    unavailable_scan_stamps_ns: list[NS]
    missing_channels: list[
        Literal[
            "AMCL_POSE", "GAZEBO_POSE_TRUTH", "NAV2_ACTION_EVENTS", "PLANNED_PATH", "FAULT_EVENTS"
        ]
    ]


class Scene(Strict):
    map_asset: Literal["map.pgm.gz"] = "map.pgm.gz"
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    resolution_m: Finite
    origin: Vec3
    encoding: Literal["P5_GRAY8_TOP_DOWN"] = "P5_GRAY8_TOP_DOWN"
    occupied_threshold: Finite
    free_threshold: Finite
    negate: Literal[0] = 0
    frame_chain: Literal["map->odom->base_link->lidar_link"] = "map->odom->base_link->lidar_link"
    coordinates: Literal["ROS_RIGHT_HANDED_METRES_Z_UP"] = "ROS_RIGHT_HANDED_METRES_Z_UP"
    visual_model: None = None
    visual_model_reason: Literal["NO_CURATED_VISUAL_ASSET"] = "NO_CURATED_VISUAL_ASSET"


class Metric(Strict):
    name: Literal["mission_ros_seconds", "odom_path_metres", "xy_error_m", "yaw_error_rad"]
    value: Finite | None
    unit: Literal["s", "m", "rad"]
    source_ref: Literal["report"] = "report"
    pointer: Annotated[
        str, Field(pattern=r"^/campaign/trials/0/evidence/(metrics|validation)/[a-z_]+$")
    ]
    quality: Literal["ORIGINAL_VERIFIED"] = "ORIGINAL_VERIFIED"


class Policy(Strict):
    xy_tolerance_m: Finite
    yaw_tolerance_rad: Finite
    tf_max_age_s: Finite
    localization_max_age_s: Finite
    max_xy_variance_m2: Finite
    max_yaw_variance_rad2: Finite


class XYTheta(Strict):
    x: Finite
    y: Finite
    yaw: Finite


class Original(Strict):
    source_ref: Literal["report"] = "report"
    sanitized_derivative_not_original_report: Literal[True] = True
    ros_outcome: Literal["succeeded"]
    action_status: None = None
    action_status_reason: Literal["NOT_RECORDED_IN_SOURCE_REPORT"] = (
        "NOT_RECORDED_IN_SOURCE_REPORT"
    )
    pose_verdict: Literal["POSE_VERIFIED"]
    pose_policy: Policy
    commanded_final_goal: XYTheta
    final_localized_pose: XYTheta
    final_pose_ros_ns: NS
    final_observed_ros_ns: NS
    final_pose_is_playback_sample: Literal[False] = False
    contact_verdict: Literal["NO_CONTACT_OBSERVED"]
    contact_start_ros_ns: NS
    contact_end_ros_ns: NS
    contact_frame_count: Annotated[int, Field(gt=0)]
    contact_count: Annotated[int, Field(ge=0)]
    contact_scope: Literal["ADAPTER_MONITORED_GEOMETRY_ONLY"] = "ADAPTER_MONITORED_GEOMETRY_ONLY"
    universal_collision_freedom_assessable: Literal[False] = False


class Manifest(Strict):
    schema_version: Literal[1] = 1
    kind: Literal["robotops.recorded_playback"] = "robotops.recorded_playback"
    dataset_id: Literal["N0"] = "N0"
    exporter: Exporter
    source_identity: Identity
    sources: list[Source]
    assets: list[Asset]
    time: Time
    segments: list[Segment]
    coverage: Coverage
    scene: Scene
    metrics: list[Metric]
    original_validation: Original
    navigation_events: list[None] = Field(default_factory=list, max_length=0)
    limitations: list[
        Literal[
            "PARTIAL_MISSION_RECORDING",
            "INITIAL_TF_GAP",
            "LOCALIZED_TF_NOT_PHYSICAL_TRUTH",
            "NO_NAV2_EVENT_RECONSTRUCTION",
            "DISPLAY_DOWNSAMPLED",
            "NO_ORIGINAL_GIT_REVISION",
            "HASHES_NOT_SIGNATURES",
            "SCOPED_CONTACT_OBSERVATION_ONLY",
        ]
    ]
    publication_review: Literal["PRIVATE_NOT_APPROVED_FOR_UPLOAD"] = (
        "PRIVATE_NOT_APPROVED_FOR_UPLOAD"
    )

    @model_validator(mode="after")
    def intervals_and_metrics(self):
        t = self.time
        if (
            not int(t.mission_start_ns)
            < int(t.recorded_start_ns)
            < int(t.recorded_end_ns)
            < int(t.mission_end_ns)
        ):
            raise ValueError("N0 partial mission time bounds inconsistent")
        if t.offset_origin_ns != t.recorded_start_ns:
            raise ValueError("Offset clock origin mismatch")
        last = -1
        for segment in self.segments:
            a, b = int(segment.start_ros_ns), int(segment.end_ros_ns)
            if not last < a <= b or not int(t.recorded_start_ns) <= a <= b <= int(
                t.recorded_end_ns
            ):
                raise ValueError("Invalid/overlapping playback segments")
            if segment.start_us != offset_us(
                a, int(t.offset_origin_ns)
            ) or segment.end_us != offset_us(b, int(t.offset_origin_ns)):
                raise ValueError("Segment offset mismatch")
            last = b
        for gap in self.coverage.gaps:
            if (
                not int(t.mission_start_ns)
                <= int(gap.start_ros_ns)
                <= int(gap.end_ros_ns)
                <= int(t.mission_end_ns)
            ):
                raise ValueError("Invalid gap interval")
        expected = {
            "mission_ros_seconds": ("s", "metrics"),
            "odom_path_metres": ("m", "metrics"),
            "xy_error_m": ("m", "validation"),
            "yaw_error_rad": ("rad", "validation"),
        }
        if {m.name for m in self.metrics} != set(expected) or len(self.metrics) != len(expected):
            raise ValueError("N0 metrics incomplete or duplicated")
        for metric in self.metrics:
            unit, category = expected[metric.name]
            if (
                metric.unit != unit
                or metric.pointer != f"/campaign/trials/0/evidence/{category}/{metric.name}"
                or metric.value is None
            ):
                raise ValueError("Metric provenance/unit conflict")
        return self


def offset_us(stamp: int, origin: int) -> int:
    if type(stamp) is not int or type(origin) is not int or stamp < origin:
        raise ValueError("Invalid ROS time offset")
    result = (stamp - origin) // 1000
    if result > 2**53 - 1:
        raise ValueError("Unsafe JavaScript relative offset")
    return result


def pixel_center(u, v, width, height, resolution, origin):
    if not 0 <= u < width or not 0 <= v < height:
        raise ValueError("Pixel outside map")
    x, y = resolution * (u + 0.5), resolution * (height - v - 0.5)
    c, s = math.cos(origin[2]), math.sin(origin[2])
    return [origin[0] + c * x - s * y, origin[1] + s * x + c * y]


def three_vector(vector):
    x, y, z = vector
    return [x, z, -y]


def three_quaternion(quaternion):
    x, y, z, w = quaternion
    return [x, z, -y, w]


def threshold_status(value, threshold, *, evidence_valid=True):
    """Offline contract fixture helper; no visitor UI or authoritative verdict writes."""
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or threshold < 0:
        raise ValueError("Invalid nonnegative finite analytical threshold")
    if not evidence_valid or type(value) not in (int, float) or not math.isfinite(value):
        return "UNKNOWN"
    return "PASS" if value <= threshold else "FAIL"
