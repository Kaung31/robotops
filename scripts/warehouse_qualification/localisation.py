"""Bounded stationary-startup policy; no ROS or fabricated pose timestamps."""

from __future__ import annotations

import math
from collections import deque

POSE_AGE_NS = 5_000_000_000
MOTION_FRESH_NS = 1_000_000_000
STATIONARY_WINDOW_NS = 1_000_000_000
# Two existing 15 s mission startup stages (action/clock, then recorder).
STARTUP_HOLD_NS = 30_000_000_000
# One tenth of the unchanged AMCL 0.05 m/rad filter thresholds.
STATIONARY_DELTA = 0.005
STATIONARY_SPEED = 0.005


def angle_delta(a: float, b: float) -> float:
    return abs(math.atan2(math.sin(a - b), math.cos(a - b)))


class LocalisationReadiness:
    def __init__(self) -> None:
        self.samples = {name: deque(maxlen=512) for name in ("odom", "truth")}
        self.anchor = {}
        self.initial_stamp = self.armed_mono = self.armed_ros = None
        self.last_pose_stamp = self.pose_fault = None
        self.motion_ros = self.motion_mono = None
        self.fault = None

    def observe(
        self,
        source: str,
        stamp_ns: int,
        mono_ns: int,
        x: float,
        y: float,
        heading: float,
        speed: float | None = None,
        turn: float | None = None,
    ) -> None:
        if stamp_ns == 0 and self.initial_stamp is None:
            return  # Startup clock has not begun; cannot count as motion evidence.
        values = (x, y, heading) if source == "truth" else (x, y, heading, speed, turn)
        previous = self.samples[source][-1] if self.samples[source] else None
        if (
            stamp_ns <= 0
            or any(v is None or not math.isfinite(v) for v in values)
            or (previous and (stamp_ns < previous[0] or mono_ns < previous[1]))
        ):
            self.fault = "motion.invalid_or_regressed"
            return
        if previous and self.initial_stamp is not None and mono_ns - previous[1] > MOTION_FRESH_NS:
            self.fault = "motion.coverage_lost_after_arming"
        if previous and stamp_ns == previous[0]:
            if tuple(values) != previous[2 : 2 + len(values)]:
                self.fault = "motion.contradictory_stamp"
            return
        sample = (stamp_ns, mono_ns, x, y, heading, speed, turn)
        self.samples[source].append(sample)
        if source in self.anchor:
            a = self.anchor[source]
            moved = math.hypot(x - a[2], y - a[3]) > STATIONARY_DELTA
            moved |= angle_delta(heading, a[4]) > STATIONARY_DELTA
            moved |= source == "odom" and (
                abs(speed) > STATIONARY_SPEED or abs(turn) > STATIONARY_SPEED
            )
            if moved and self.motion_ros is None:
                self.motion_ros, self.motion_mono = stamp_ns, mono_ns

    def arm(
        self,
        now_ros: int,
        now_mono: int,
        pose_stamp: int | None,
        covariance: list[float],
        pose_valid: bool = True,
    ) -> None:
        if not pose_valid or not self.valid_pose(now_ros, pose_stamp, covariance):
            raise RuntimeError(
                f"amcl.initial_pose_invalid_or_stale: now_ros_ns={now_ros}, "
                f"pose_stamp_ns={pose_stamp}, covariance={covariance}, "
                f"pose_valid={pose_valid}, pose_age_limit_ns={POSE_AGE_NS}, "
                "covariance_max=0.25"
            )
        # Must already have a continuous stationary history, never infer stop
        # from the absence of odometry or ground truth.
        status = self.motion_status(now_ros, now_mono)
        if not status["ready"] or not all(s["stationary"] for s in status["streams"].values()):
            raise RuntimeError(f"amcl.initial_motion_evidence: {status}")
        for name, samples in self.samples.items():
            self.anchor[name] = samples[-1]
        self.initial_stamp, self.armed_mono, self.armed_ros = pose_stamp, now_mono, now_ros
        self.last_pose_stamp = pose_stamp

    @staticmethod
    def valid_pose(now_ros: int, pose_stamp: int | None, covariance: list[float]) -> bool:
        return (
            pose_stamp is not None
            and pose_stamp > 0
            and 0 <= now_ros - pose_stamp <= POSE_AGE_NS
            and len(covariance) == 3
            and all(math.isfinite(v) and 0 <= v <= 0.25 for v in covariance)
        )

    def motion_status(self, now_ros: int, now_mono: int) -> dict:
        details, causes = {}, []
        for name, samples in self.samples.items():
            if not samples:
                causes.append(f"motion.{name}.missing")
                continue
            last = samples[-1]
            age, receipt_age = now_ros - last[0], now_mono - last[1]
            recent = [s for s in samples if last[1] - s[1] <= 2 * STATIONARY_WINDOW_NS]
            span = last[1] - recent[0][1]
            gaps = [b[1] - a[1] for a, b in zip(recent, recent[1:], strict=False)]
            distance = max(math.hypot(s[2] - recent[0][2], s[3] - recent[0][3]) for s in recent)
            rotation = max(angle_delta(s[4], recent[0][4]) for s in recent)
            stationary = distance <= STATIONARY_DELTA and rotation <= STATIONARY_DELTA
            if name == "odom":
                stationary &= all(
                    abs(s[5]) <= STATIONARY_SPEED and abs(s[6]) <= STATIONARY_SPEED for s in recent
                )
            details[name] = dict(
                stamp_ns=last[0],
                age_ns=age,
                receipt_age_ns=receipt_age,
                span_ns=span,
                max_gap_ns=max(gaps, default=0),
                displacement_m=distance,
                rotation_rad=rotation,
                stationary=stationary,
                speed_m_s=last[5],
                turn_rad_s=last[6],
            )
            if not (0 <= age <= MOTION_FRESH_NS and 0 <= receipt_age <= MOTION_FRESH_NS):
                causes.append(f"motion.{name}.stale")
            if span < STATIONARY_WINDOW_NS or any(g > MOTION_FRESH_NS for g in gaps):
                causes.append(f"motion.{name}.coverage")
        if self.fault:
            causes.append(self.fault)
        disagreement = None
        if len(self.anchor) == 2 and all(self.samples.values()):
            changes = {}
            for name, samples in self.samples.items():
                a, b = self.anchor[name], samples[-1]
                changes[name] = (math.hypot(b[2] - a[2], b[3] - a[3]), angle_delta(b[4], a[4]))
            disagreement = [
                abs(a - b) for a, b in zip(changes["odom"], changes["truth"], strict=True)
            ]
            if any(v > 0.02 for v in disagreement):
                causes.append("motion.odom_truth_disagreement")
        return dict(
            ready=not causes,
            causes=causes,
            streams=details,
            anchor_disagreement_m_rad=disagreement,
            anchor_disagreement_limit_m_rad=0.02,
            freshness_limit_ns=MOTION_FRESH_NS,
            window_ns=STATIONARY_WINDOW_NS,
            stationary_delta=STATIONARY_DELTA,
            stationary_speed=STATIONARY_SPEED,
        )

    def assess(
        self,
        now_ros: int,
        now_mono: int,
        pose_stamp: int | None,
        covariance: list[float],
        pose_valid: bool = True,
    ) -> dict:
        motion = self.motion_status(now_ros, now_mono)
        age = None if pose_stamp is None else now_ros - pose_stamp
        if pose_stamp is not None and self.last_pose_stamp is not None:
            if pose_stamp < self.last_pose_stamp:
                self.pose_fault = "amcl.pose_stamp_regressed"
            self.last_pose_stamp = max(self.last_pose_stamp, pose_stamp)
        causes = list(motion["causes"])
        if self.pose_fault:
            causes.append(self.pose_fault)
        if self.initial_stamp is None:
            causes.append("amcl.initial_pose_missing")
        pose_checks = {
            "amcl.pose_frame_or_value_invalid": pose_valid,
            "amcl.pose_missing": pose_stamp is not None,
            "amcl.pose_stamp_nonpositive": pose_stamp is not None and pose_stamp > 0,
            "amcl.pose_stamp_future": age is not None and age >= 0,
            "amcl.covariance_invalid": len(covariance) == 3
            and all(math.isfinite(v) and 0 <= v <= 0.25 for v in covariance),
        }
        causes.extend(name for name, passed in pose_checks.items() if not passed)
        mode = "fresh_pose"
        if self.motion_ros is None:
            hold = None if self.armed_mono is None else now_mono - self.armed_mono
            stationary = motion["ready"] and all(
                s["stationary"] for s in motion["streams"].values()
            )
            if not stationary:
                causes.append("amcl.stationarity_unproven")
            if age is not None and age > POSE_AGE_NS:
                mode = "stationary_startup"
                if (
                    hold is None
                    or not 0 <= hold <= STARTUP_HOLD_NS
                    or not 0 <= now_ros - self.armed_ros <= STARTUP_HOLD_NS
                ):
                    causes.append("amcl.stationary_startup_expired")
        else:
            # A stationary old estimate needs a bounded handoff when motion
            # begins: allow the existing 5 s update budget from first movement,
            # rather than rejecting before AMCL crosses its 0.05 m/rad trigger.
            if pose_stamp is not None and pose_stamp >= self.motion_ros:
                if age > POSE_AGE_NS:
                    causes.append("amcl.moving_pose_stale")
            elif (
                0 <= now_mono - self.motion_mono <= POSE_AGE_NS
                and 0 <= now_ros - self.motion_ros <= POSE_AGE_NS
            ):
                mode = "awaiting_first_motion_update"
            else:
                causes.append("amcl.first_motion_update_missing")
        return dict(
            ready=not causes,
            causes=causes,
            mode=mode,
            now_ros_ns=now_ros,
            now_monotonic_ns=now_mono,
            pose_stamp_ns=pose_stamp,
            pose_age_ns=age,
            covariance=[v if math.isfinite(v) else str(v) for v in covariance],
            covariance_max=0.25,
            pose_checks=pose_checks,
            pose_age_limit_ns=POSE_AGE_NS,
            startup_hold_limit_ns=STARTUP_HOLD_NS,
            initial_pose_stamp_ns=self.initial_stamp,
            armed_ros_ns=self.armed_ros,
            armed_monotonic_ns=self.armed_mono,
            motion_start_ros_ns=self.motion_ros,
            motion_start_monotonic_ns=self.motion_mono,
            motion=motion,
        )
