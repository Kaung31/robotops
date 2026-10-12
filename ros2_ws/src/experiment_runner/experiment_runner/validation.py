"""Deterministic localization-based final-pose validation; no ROS dependencies."""

import hashlib
import json
import math
from pathlib import Path

DEFAULT_POLICY = {
    "xy_tolerance_m": 0.20,
    "yaw_tolerance_rad": 0.25,
    "tf_max_age_s": 1.0,
    "localization_max_age_s": 5.0,
    "max_xy_variance_m2": 0.25,
    "max_yaw_variance_rad2": 0.25,
}


def policy_for(config: dict) -> dict:
    policy = config.get("validation", DEFAULT_POLICY)
    if not isinstance(policy, dict) or set(policy) != set(DEFAULT_POLICY):
        raise ValueError("validation requires exactly the documented policy fields")
    for key, value in policy.items():
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"validation.{key} must be finite and positive")
    if policy["yaw_tolerance_rad"] > math.pi:
        raise ValueError("validation yaw tolerance must not exceed pi")
    return dict(policy)


def content_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pose_value(position, orientation) -> dict:
    """Reject invalid rotations rather than silently normalizing corrupt evidence."""
    values = [position.x, position.y, orientation.x, orientation.y, orientation.z, orientation.w]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Nonfinite pose")
    norm = sum(v * v for v in values[2:])
    if abs(norm - 1.0) > 0.001:
        raise ValueError("Quaternion is not normalized")
    x, y, z, w = values[2:]
    return dict(
        x=position.x, y=position.y, yaw=math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    )


def validate_final(
    policy: dict,
    goal: dict,
    snapshot: dict,
    provenance: dict,
    outcome: str,
    action_status: int | None,
) -> dict:
    """No missing evidence can yield a passing verdict. ROS outcome stays separate."""
    result = dict(
        schema_version=1,
        scope="localization_final_pose_only; collision and physical ground truth not assessed",
        policy=policy,
        commanded_final_goal=dict(goal),
        snapshot=snapshot,
        provenance=provenance,
        ros_outcome=outcome,
        action_status=action_status,
        xy_error_m=None,
        yaw_error_rad=None,
        reasons=[],
    )
    reasons = result["reasons"]
    if outcome in (
        "pending",
        "interrupted",
        "termination_unconfirmed",
        "cancellation_unconfirmed",
    ) or (action_status not in (4, 5, 6) and outcome != "rejected"):
        result.update(verdict="INCONCLUSIVE", reasons=["Terminal mission outcome is unconfirmed"])
        return result
    if outcome != "succeeded" or action_status != 4:
        result.update(verdict="MISSION_FAILED", reasons=["ROS mission did not succeed"])
        return result
    try:
        if provenance.get("state") != "confirmed":
            raise ValueError("Trial/map/parameter/recording provenance is not confirmed")
        now, dispatch = snapshot["observed_ros_ns"], snapshot["dispatch_ros_ns"]
        if now <= dispatch or dispatch <= 0 or snapshot.get("clock_regressed"):
            raise ValueError("ROS clock did not advance within this trial or regressed")

        def fresh(sample, frame, child, maximum, postdate=0.0):
            if sample.get("frame") != frame or sample.get("child") != child:
                raise ValueError(f"Incorrect frame for {frame}->{child}")
            stamp = sample["stamp_ns"] - postdate * 1e9
            age = (now - stamp) / 1e9
            receipt = sample["receipt_age_s"]
            if not all(math.isfinite(v) for v in (stamp, age, receipt)):
                raise ValueError("Nonfinite evidence timestamp")
            if stamp < dispatch or not 0 <= age <= maximum or not 0 <= receipt <= maximum:
                raise ValueError(f"Stale, future or previous-trial {frame}->{child} evidence")

        transforms = snapshot["tf"]
        fresh(transforms["map_base"], "map", "base_link", policy["tf_max_age_s"])
        fresh(transforms["odom_base"], "odom", "base_link", policy["tf_max_age_s"])
        postdate = snapshot["amcl_transform_tolerance_s"]
        if not math.isfinite(postdate) or postdate < 0:
            raise ValueError("AMCL transform post-dating setting unavailable")
        fresh(transforms["map_odom"], "map", "odom", policy["tf_max_age_s"], postdate)
        localization = snapshot["localization"]
        fresh(localization, "map", None, policy["localization_max_age_s"])
        covariance = localization["covariance"]
        if len(covariance) != 36 or not all(math.isfinite(v) for v in covariance):
            raise ValueError("Localization covariance unavailable or nonfinite")
        if any(covariance[i] < 0 for i in (0, 7, 35)):
            raise ValueError("Negative localization variance")
        if max(covariance[0], covariance[7]) > policy["max_xy_variance_m2"]:
            raise ValueError("Localization XY uncertainty exceeds policy")
        if covariance[35] > policy["max_yaw_variance_rad2"]:
            raise ValueError("Localization yaw uncertainty exceeds policy")
        pose = transforms["map_base"]["pose"]
        if not all(math.isfinite(pose[k]) and math.isfinite(goal[k]) for k in ("x", "y", "yaw")):
            raise ValueError("Nonfinite final pose or goal")
        xy = math.hypot(pose["x"] - goal["x"], pose["y"] - goal["y"])
        yaw = abs(
            math.atan2(math.sin(pose["yaw"] - goal["yaw"]), math.cos(pose["yaw"] - goal["yaw"]))
        )
        result.update(xy_error_m=xy, yaw_error_rad=yaw)
        if xy > policy["xy_tolerance_m"]:
            reasons.append("Final XY error exceeds RobotOps tolerance")
        if yaw > policy["yaw_tolerance_rad"]:
            reasons.append("Final yaw error exceeds RobotOps tolerance")
        result["verdict"] = "POSE_REJECTED" if reasons else "POSE_VERIFIED"
    except (KeyError, TypeError, ValueError) as error:
        result.update(verdict="INCONCLUSIVE", reasons=[str(error)])
    return result


def artifact_provenance(directory: Path, trial: dict, manifest: dict) -> dict:
    """Bind local evidence by content, not just file names. No authenticity claim."""
    from robot_recorder.recording import inspect_bag

    try:
        metadata = json.loads((directory / "metadata.json").read_text())
        saved = json.loads((directory / "result.json").read_text())
        config = manifest["config"]
        if metadata["run_id"] != trial["run_id"] or saved["run_id"] != trial["run_id"]:
            raise ValueError("Run ID mismatch")
        if saved["outcome"] != trial["mission_outcome"]:
            raise ValueError("Recorded/action outcome mismatch")
        for key, value in config["expected"].items():
            if metadata["settings"].get(key) != value:
                raise ValueError(f"Mission setting mismatch: {key}")
        expected = []
        for pose in config["mission"]["waypoints"]:
            expected.append(
                dict(
                    frame="map",
                    x=float(pose["x"]),
                    y=float(pose["y"]),
                    z=0.0,
                    qx=0.0,
                    qy=0.0,
                    qz=math.sin(pose["yaw"] / 2),
                    qw=math.cos(pose["yaw"] / 2),
                )
            )
        if metadata["waypoints"] != expected or not metadata["recording_enabled"]:
            raise ValueError("Recorded mission definition mismatch")
        if trial["parameters"] != trial["parameters_after"]:
            raise ValueError("Parameters changed")
        for key, value in manifest["map_hashes"].items():
            if metadata["map"][key] != value or trial["map_hashes_after"][key] != value:
                raise ValueError("Map provenance mismatch")
        if (
            saved["started_ros_ns"] < trial["dispatch_ros_ns"]
            or saved["ended_ros_ns"] < saved["started_ros_ns"]
        ):
            raise ValueError("Recording timestamps do not belong to trial")
        bag = directory / "telemetry"
        actual = inspect_bag(bag, metadata["recording"]["required_topics"])
        if actual != saved["recording"]:
            raise ValueError("Finalized recording differs from mission result")
        hashes = {
            p.name: file_hash(p)
            for p in [
                directory / "metadata.json",
                directory / "result.json",
                bag / "metadata.yaml",
            ]
        }
        for p in sorted(bag.glob("*.mcap")):
            hashes[f"telemetry/{p.name}"] = file_hash(p)
        return dict(
            state="confirmed",
            run_id=trial["run_id"],
            mission_goal_id=trial["mission_goal_id"],
            experiment_id=manifest["experiment_id"],
            execution_context=config.get("execution_context"),
            config_sha256=content_hash(config),
            parameters_sha256=content_hash(trial["parameters"]),
            map_hashes=manifest["map_hashes"],
            artifact_sha256=hashes,
            software_revision=metadata.get("software_revision"),
        )
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, AttributeError) as error:
        return dict(state="unconfirmed", error=str(error))
