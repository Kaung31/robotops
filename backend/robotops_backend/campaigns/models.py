"""Immutable inputs and durable identities, independent of robot transport."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from ..models import Waypoint

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CampaignPose(Waypoint):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class StartCondition(CampaignPose):
    position_tolerance: float = Field(default=0.35, gt=0, le=10)
    yaw_tolerance: float = Field(default=0.4, gt=0, le=3.141592653589793)


class CampaignTimeouts(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    response: float = Field(default=15, ge=1, le=120)
    trial: float = Field(default=180, ge=1, le=3600)
    cancel: float = Field(default=30, ge=1, le=120)


class CampaignDefinition(StrictModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    name: str = Field(min_length=1, max_length=80)
    runtime_mode: Literal["mock", "sim"] = "sim"
    robot_model: Literal["robotops_base"] = "robotops_base"
    world: Identifier
    map_id: Identifier
    profiles: list[Identifier] = Field(min_length=1, max_length=8)
    repetitions: StrictInt = Field(default=1, ge=1, le=100)
    waypoints: list[CampaignPose] = Field(min_length=1, max_length=100)
    start: StartCondition  # Explicit start contract; never inferred from a browser pose.
    timeouts: CampaignTimeouts = Field(default_factory=CampaignTimeouts)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Campaign name cannot be blank")
        return value

    @model_validator(mode="after")
    def bounded_trials(self):
        if len(set(self.profiles)) != len(self.profiles):
            raise ValueError("Navigation profiles must be unique")
        if len(self.profiles) * self.repetitions > 100:
            raise ValueError("A campaign may contain at most 100 trials")
        return self


class TrialEvidence(StrictModel):
    manifest_path: str
    experiment_id: str
    mission_run_id: str | None = None
    outcome: str
    metrics: dict[str, object] = Field(default_factory=dict)
    validation: dict[str, object] | None = None
    collision: dict[str, object] | None = None


class PlannedTrial(StrictModel):
    id: str
    profile: str
    repetition: int
    state: Literal[
        "planned", "starting", "running", "succeeded", "failed", "canceled", "interrupted"
    ] = "planned"
    evidence: TrialEvidence | None = None


class CampaignRecord(StrictModel):
    schema_version: Literal[1] = 1
    id: str
    state: Literal[
        "draft", "queued", "running", "canceling", "completed", "failed", "canceled", "interrupted"
    ] = "draft"
    cancel_requested: bool = False
    error: str | None = None
    termination_confirmed: bool | None = None
    cleanup_confirmed: bool | None = None
    created_at: datetime
    updated_at: datetime
    definition: CampaignDefinition
    trials: list[PlannedTrial]


class CampaignEvent(StrictModel):
    sequence: int
    campaign_id: str
    at: datetime
    kind: Literal[
        "created",
        "canceled",
        "started",
        "trial_started",
        "trial_finished",
        "cancel_requested",
        "completed",
        "failed",
        "interrupted",
        "reconciled",
    ]


class CampaignRuntimeStatus(StrictModel):
    worker_active: bool
    execution_enabled: bool
    supported_modes: list[Literal["mock", "sim"]]
    campaign_id: str | None
