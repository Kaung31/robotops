"""Strict configuration and offline metrics; usable without ROS."""

import copy
import json
import math
from pathlib import Path
from statistics import mean

import yaml

from experiment_runner.validation import policy_for


def finite(value, name: str, positive: bool = False) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def fields(value, expected: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{name} requires exactly {sorted(expected)}")


def validate(data: dict) -> dict:
    fields(
        data,
        {"name", "repetitions", "expected", "mission", "start", "timeouts"}
        | (set(data) & {"validation", "execution_context"} if isinstance(data, dict) else set()),
        "experiment",
    )
    policy_for(data)
    if "execution_context" in data:
        fields(data["execution_context"], {"campaign_id", "trial_id"}, "execution_context")
        if any(
            not isinstance(v, str) or len(v) != 32 or any(c not in "0123456789abcdef" for c in v)
            for v in data["execution_context"].values()
        ):
            raise ValueError("Execution context requires server UUID hex identities")
    if not isinstance(data["name"], str) or not 1 <= len(data["name"].strip()) <= 80:
        raise ValueError("name must contain 1–80 characters")
    if type(data["repetitions"]) is not int or not 1 <= data["repetitions"] <= 100:
        raise ValueError("repetitions must be an integer from 1 to 100")
    fields(
        data["expected"],
        {"runtime_mode", "robot_model", "environment", "navigation_profile"},
        "expected",
    )
    if any(not isinstance(v, str) or not v.strip() for v in data["expected"].values()):
        raise ValueError("expected settings must be nonempty strings")
    if data["expected"]["runtime_mode"] not in ("mock", "sim"):
        raise ValueError("Only mock/sim experiments are enabled; replay and real are disabled")
    fields(data["mission"], {"waypoints"}, "mission")
    poses = data["mission"]["waypoints"]
    if not isinstance(poses, list) or not 1 <= len(poses) <= 100:
        raise ValueError("mission needs 1–100 waypoints")
    for pose in poses:
        fields(pose, {"x", "y", "yaw"}, "waypoint")
        for key, value in pose.items():
            finite(value, key)
    fields(data["start"], {"x", "y", "yaw", "position_tolerance", "yaw_tolerance"}, "start")
    for key, value in data["start"].items():
        finite(value, key, positive=key.endswith("tolerance"))
    fields(data["timeouts"], {"response", "trial", "cancel"}, "timeouts")
    for key, value in data["timeouts"].items():
        finite(value, key, positive=True)
    return copy.deepcopy(data)


def load(path: Path) -> dict:
    return validate(yaml.safe_load(path.read_text()))


def check_start(start: dict, x: float, y: float, yaw: float) -> None:
    for value in (x, y, yaw):
        finite(value, "observed start pose")
    distance = math.hypot(x - start["x"], y - start["y"])
    angle = abs(math.atan2(math.sin(yaw - start["yaw"]), math.cos(yaw - start["yaw"])))
    if distance > start["position_tolerance"] or angle > start["yaw_tolerance"]:
        raise ValueError(f"Start pose outside tolerances: {distance:.3f} m, {angle:.3f} rad")


def path_length(samples) -> float:
    """Integrate planar odometry positions; never bridge resets or frame changes."""
    previous = None
    distance = 0.0
    count = 0
    for stamp, frame, child, x, y in samples:
        finite(x, "odometry x")
        finite(y, "odometry y")
        if stamp <= 0 or not frame or not child:
            raise ValueError("Odometry needs positive timestamps and named frames")
        if previous is not None:
            t, f, c, px, py = previous
            if stamp <= t or (frame, child) != (f, c):
                raise ValueError("Odometry timestamps must increase and frames must remain fixed")
            distance += math.hypot(x - px, y - py)
        previous = stamp, frame, child, x, y
        count += 1
    if count < 2:
        raise ValueError("At least two odometry samples are required")
    return distance


def report(manifest: dict) -> dict:
    trials = manifest["trials"]
    successes = [t for t in trials if t.get("outcome") == "succeeded"]
    durations = [
        t["metrics"]["mission_ros_seconds"]
        for t in successes
        if t.get("metrics", {}).get("mission_ros_seconds") is not None
    ]
    distances = [
        t["metrics"]["odom_path_metres"]
        for t in successes
        if t.get("metrics", {}).get("odom_path_metres") is not None
    ]
    return {
        "schema_version": 1,
        "experiment_id": manifest["experiment_id"],
        "state": manifest["state"],
        "attempted_trials": len(trials),
        "requested_trials": manifest["config"]["repetitions"],
        "successful_trials": len(successes),
        "success_rate": len(successes) / len(trials) if trials else None,
        "pose_verified_trials": sum(
            t.get("validation", {}).get("verdict") == "POSE_VERIFIED" for t in trials
        ),
        "validation_note": "ROS success rate is separate from localization-based pose validation",
        "contact_verdict_counts": {
            verdict: sum(
                t.get("collision", {}).get("verdict", "UNVALIDATED") == verdict for t in trials
            )
            for verdict in ("NO_CONTACT_OBSERVED", "CONTACT_DETECTED", "UNKNOWN", "UNVALIDATED")
        },
        "successful_mean_mission_ros_seconds": mean(durations) if durations else None,
        "duration_sample_count": len(durations),
        "successful_mean_odom_path_metres": mean(distances) if distances else None,
        "path_sample_count": len(distances),
    }


def comparison(paths: list[Path]) -> dict:
    manifests = [json.loads(p.read_text()) for p in paths]
    if len(manifests) < 2:
        raise ValueError("Comparison requires at least two experiment manifests")

    def conditions(m):
        config = m["config"]
        expected = config["expected"]
        return (
            expected["robot_model"],
            expected["runtime_mode"],
            expected["environment"],
            config["mission"],
            config["start"],
            m.get("map_hashes"),
            m.get("validation_policy") if m.get("validation_version") else None,
        )

    if any(not m.get("map_hashes") for m in manifests):
        raise ValueError("Comparison requires observed saved-map hashes")
    if any(m["state"] in ("running", "interrupted") for m in manifests):
        raise ValueError(
            "A running/interrupted manifest cannot be compared as a finalized experiment"
        )
    if any(conditions(m) != conditions(manifests[0]) for m in manifests[1:]):
        raise ValueError("Robot, mode, environment, mission, start or map conditions differ")
    return {
        "schema_version": 1,
        "reports": [report(m) for m in manifests],
        "manifests": [str(p.resolve()) for p in paths],
        "note": (
            "Observed trials, not statistical significance; inspect parameter snapshots "
            "and missing provenance."
        ),
    }


def parameter_json(value):
    """Preserve ROS unset-limit sentinels without invalid JSON or NaN inequality."""
    if isinstance(value, float) and not math.isfinite(value):
        return {"ros_nonfinite_double": str(value)}
    if isinstance(value, bytes):
        return {"ros_bytes_hex": value.hex()}
    if isinstance(value, list):
        return [parameter_json(item) for item in value]
    return value


def load_baseline(path: Path, config: dict) -> dict:
    """Carry conditions across fresh-stack, one-trial runner invocations."""
    manifest = json.loads(path.read_text())
    if manifest.get("state") != "completed" or len(manifest.get("trials", [])) != 1:
        raise ValueError("Baseline requires one completed trial")
    prior = manifest["config"]
    if manifest.get("validation_version") and manifest.get("validation_policy") != policy_for(
        config
    ):
        raise ValueError("Baseline validation policy differs")
    for key in ("expected", "mission", "start"):
        if prior.get(key) != config[key]:
            raise ValueError(f"Baseline {key} differs from requested experiment")
    trial = manifest["trials"][0]
    parameters = trial.get("parameters")
    if not parameters or parameters != trial.get("parameters_after"):
        raise ValueError("Baseline parameter evidence is missing or inconsistent")
    hashes = manifest.get("map_hashes")
    if not hashes or set(hashes) != {"yaml_sha256", "image_sha256"}:
        raise ValueError("Baseline requires saved-map hashes")
    return {"parameters": parameters, "map_hashes": hashes, "source": str(path.resolve())}


def load_map_baseline(path: Path, config: dict) -> dict:
    manifest = json.loads(path.read_text())
    prior = manifest["config"]
    if manifest.get("validation_version") and manifest.get("validation_policy") != policy_for(
        config
    ):
        raise ValueError("Baseline validation policy differs")
    expected = {k: v for k, v in config["expected"].items() if k != "navigation_profile"}
    observed = {k: v for k, v in prior["expected"].items() if k != "navigation_profile"}
    if expected != observed or any(prior[k] != config[k] for k in ("mission", "start")):
        raise ValueError("Campaign map baseline conditions differ")
    hashes = manifest.get("map_hashes")
    if (
        manifest.get("state") != "completed"
        or not hashes
        or set(hashes) != {"yaml_sha256", "image_sha256"}
    ):
        raise ValueError("Campaign map baseline is incomplete")
    return {"parameters": None, "map_hashes": hashes, "source": str(path.resolve())}
