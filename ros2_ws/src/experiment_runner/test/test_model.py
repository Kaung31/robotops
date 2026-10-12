"""Configuration, start conditions and measured summaries without ROS."""

import copy
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_runner.model import check_start, comparison, load, path_length, report, validate

CONFIG = Path(__file__).resolve().parents[1] / "config/round_trip.yaml"


def test_example_and_deep_copy():
    config = load(CONFIG)
    other = validate(config)
    other["mission"]["waypoints"][0]["x"] = 99
    assert config["mission"]["waypoints"][0]["x"] == 1


@pytest.mark.parametrize("value", [0, 101, True, 1.5, "2"])
def test_bad_repetitions(value):
    config = load(CONFIG)
    config["repetitions"] = value
    with pytest.raises(ValueError):
        validate(config)


@pytest.mark.parametrize("mode", ["replay", "real", "unknown"])
def test_disabled_modes(mode):
    config = load(CONFIG)
    config["expected"]["runtime_mode"] = mode
    with pytest.raises(ValueError):
        validate(config)


def test_unknown_fields_and_nonfinite_values():
    config = load(CONFIG)
    config["faults"] = []
    with pytest.raises(ValueError):
        validate(config)
    del config["faults"]
    config["mission"]["waypoints"][0]["yaw"] = float("nan")
    with pytest.raises(ValueError):
        validate(config)


def test_start_pose_wraparound_and_distance():
    start = dict(x=0, y=0, yaw=math.pi, position_tolerance=0.1, yaw_tolerance=0.1)
    check_start(start, 0, 0, -math.pi)
    with pytest.raises(ValueError):
        check_start(start, 1, 0, math.pi)
    with pytest.raises(ValueError):
        check_start(start, 0, 0, 0)


def test_measured_distance_and_invalid_samples():
    samples = [
        (1, "odom", "base_link", 0, 0),
        (2, "odom", "base_link", 3, 4),
        (3, "odom", "base_link", 3, 0),
    ]
    assert path_length(samples) == 9
    for bad in (
        [],
        samples[:1],
        samples[::-1],
        [samples[0], samples[0]],
        [samples[0], (2, "map", "base_link", 3, 4)],
    ):
        with pytest.raises(ValueError):
            path_length(bad)


def manifest():
    return dict(
        experiment_id="one",
        state="failed",
        config=load(CONFIG),
        map_hashes={"yaml": "a", "image": "b"},
        trials=[
            {
                "outcome": "succeeded",
                "metrics": {"mission_ros_seconds": 4.0, "odom_path_metres": 3.0},
            },
            {"outcome": "failed"},
        ],
    )


def test_report_keeps_failures_and_missing_measurements():
    data = manifest()
    result = report(data)
    assert result["success_rate"] == 0.5
    assert result["successful_mean_mission_ros_seconds"] == 4
    assert result["path_sample_count"] == 1
    assert result["contact_verdict_counts"]["UNVALIDATED"] == 2
    data["trials"][0]["collision"] = {"verdict": "CONTACT_DETECTED"}
    assert report(data)["contact_verdict_counts"]["CONTACT_DETECTED"] == 1
    assert report(data)["success_rate"] == 0.5
    data["trials"] = []
    assert report(data)["success_rate"] is None


def test_comparison_accepts_profiles_but_rejects_different_conditions(tmp_path):
    first = manifest()
    second = copy.deepcopy(first)
    second["config"]["expected"]["navigation_profile"] = "smac_dwb"
    paths = [tmp_path / "a.json", tmp_path / "b.json"]
    paths[0].write_text(json.dumps(first))
    paths[1].write_text(json.dumps(second))
    assert len(comparison(paths)["reports"]) == 2
    second["config"]["mission"]["waypoints"][0]["x"] = 4
    paths[1].write_text(json.dumps(second))
    with pytest.raises(ValueError):
        comparison(paths)
    for unfinished_state in ("running", "interrupted"):
        second = copy.deepcopy(first)
        second["state"] = unfinished_state
        paths[1].write_text(json.dumps(second))
        with pytest.raises(ValueError):
            comparison(paths)


def test_parameter_sentinels_remain_explicit_and_comparable():
    from experiment_runner.model import parameter_json

    first = parameter_json([float("nan"), float("inf"), float("-inf"), b"a"])
    assert first == parameter_json([float("nan"), float("inf"), float("-inf"), b"a"])
    assert json.loads(json.dumps(first, allow_nan=False)) == first
    assert first[0] != "nan"


def test_restart_baseline_preserves_conditions_and_rejects_drift(tmp_path):
    from experiment_runner.model import load_baseline, load_map_baseline

    config = load(CONFIG)
    parameters = {"planner_server": {"planner": "navfn"}}
    data = dict(
        state="completed",
        config=config,
        map_hashes={"yaml_sha256": "a", "image_sha256": "b"},
        trials=[dict(parameters=parameters, parameters_after=parameters)],
    )
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(data))
    baseline = load_baseline(path, config)
    assert baseline["parameters"] == parameters
    changed = copy.deepcopy(config)
    changed["expected"]["navigation_profile"] = "smac_dwb"
    assert load_map_baseline(path, changed)["map_hashes"] == data["map_hashes"]
    with pytest.raises(ValueError, match="expected"):
        load_baseline(path, changed)
    changed["mission"]["waypoints"][0]["x"] += 1
    with pytest.raises(ValueError, match="conditions"):
        load_map_baseline(path, changed)
    for change in [
        {"state": "failed"},
        {"trials": []},
        {"map_hashes": None},
        {"trials": [dict(parameters=parameters, parameters_after={})]},
    ]:
        path.write_text(json.dumps(dict(data, **change)))
        with pytest.raises(ValueError):
            load_baseline(path, config)


def test_validation_policy_and_execution_context_are_strict_and_optional():
    from experiment_runner.validation import DEFAULT_POLICY

    data = load(CONFIG)
    data["validation"] = dict(DEFAULT_POLICY, xy_tolerance_m=0.05)
    data["execution_context"] = {"campaign_id": "a" * 32, "trial_id": "b" * 32}
    assert validate(data)["validation"]["xy_tolerance_m"] == 0.05
    data["execution_context"]["trial_id"] = "../../other"
    with pytest.raises(ValueError):
        validate(data)
    with pytest.raises(ValueError):
        validate(None)


def test_baseline_compares_stored_validation_policy_not_current_defaults(tmp_path):
    from experiment_runner.model import load_baseline
    from experiment_runner.validation import DEFAULT_POLICY

    data = dict(
        state="completed",
        validation_version=1,
        validation_policy=dict(DEFAULT_POLICY, xy_tolerance_m=0.01),
        config=load(CONFIG),
        map_hashes={"yaml_sha256": "a", "image_sha256": "b"},
        trials=[dict(parameters={"test": 1}, parameters_after={"test": 1})],
    )
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="policy"):
        load_baseline(path, load(CONFIG))
