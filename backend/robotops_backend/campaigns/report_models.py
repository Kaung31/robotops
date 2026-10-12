"""Versioned report snapshots; original robot verdicts remain in the campaign."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from .models import CampaignRecord, StrictModel


class ArtifactCheck(StrictModel):
    reference: str
    state: Literal["VERIFIED", "MISSING", "MISMATCH", "UNAVAILABLE", "UNTRUSTED"]
    expected_sha256: str | None = None
    actual_sha256: str | None = None
    reason: str | None = None


class TrialIntegrity(StrictModel):
    trial_id: str
    state: Literal["VERIFIED", "ISSUES", "UNAVAILABLE"]
    reasons: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactCheck] = Field(default_factory=list)


class MetricSummary(StrictModel):
    mean: float | None
    samples: int


class ProfileReport(StrictModel):
    profile: str
    requested: int
    attempted: int
    ros_successes: int
    ros_success_rate: float | None
    duration_seconds: MetricSummary
    odom_metres: MetricSummary
    pose_verdicts: dict[str, int]
    contact_verdicts: dict[str, int]


class CampaignReport(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: datetime
    source_sha256: str
    campaign: CampaignRecord
    profiles: list[ProfileReport]
    integrity: list[TrialIntegrity]
    limitations: list[str]
