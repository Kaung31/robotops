"""Adversarial final-pose evidence cannot turn missing data into success."""

import copy
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "robot_recorder"))
from experiment_runner.validation import (
    DEFAULT_POLICY,
    artifact_provenance,
    content_hash,
    policy_for,
    pose_value,
    validate_final,
)


def snapshot():
    def sample(frame, child, stamp=9_900_000_000):
        return dict(frame=frame, child=child, stamp_ns=stamp, receipt_age_s=0.1)

    return dict(
        observed_ros_ns=10_000_000_000,
        dispatch_ros_ns=5_000_000_000,
        clock_regressed=False,
        amcl_transform_tolerance_s=0.5,
        tf=dict(
            map_base=dict(sample("map", "base_link"), pose=dict(x=0, y=0, yaw=math.pi)),
            odom_base=sample("odom", "base_link"),
            map_odom=sample("map", "odom", 10_400_000_000),
        ),
        localization=dict(sample("map", None), covariance=[0.0] * 36),
    )


def verdict(data=None, provenance=None, outcome="succeeded", status=4):
    return validate_final(
        DEFAULT_POLICY,
        dict(x=0, y=0, yaw=-math.pi),
        data or snapshot(),
        provenance or {"state": "confirmed"},
        outcome,
        status,
    )


def test_wraparound_and_independent_xy_yaw_rejection():
    assert verdict()["verdict"] == "POSE_VERIFIED"
    data = snapshot()
    data["tf"]["map_base"]["pose"].update(x=0.21, yaw=0)
    result = verdict(data)
    assert result["verdict"] == "POSE_REJECTED"
    assert result["xy_error_m"] == 0.21 and result["yaw_error_rad"] == math.pi
    assert len(result["reasons"]) == 2
    assert result["ros_outcome"] == "succeeded"


@pytest.mark.parametrize("kind", ["map_base", "map_odom", "odom_base", "localization"])
@pytest.mark.parametrize(
    "fault", ["missing", "old_stamp", "old_receipt", "future", "wrong_frame", "previous_trial"]
)
def test_freshness_requires_both_clocks_and_current_trial(kind, fault):
    data = snapshot()
    container = data if kind == "localization" else data["tf"]
    sample = container[kind]
    if fault == "missing":
        del container[kind]
    elif fault == "old_stamp":
        sample["stamp_ns"] = 6_000_000_000 if kind != "localization" else 1
    elif fault == "old_receipt":
        sample["receipt_age_s"] = 9
    elif fault == "future":
        sample["stamp_ns"] = 20_000_000_000
    elif fault == "wrong_frame":
        sample["frame"] = "wrong_frame"
    else:
        sample["stamp_ns"] = 4_000_000_000
    assert verdict(data)["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "fault",
    [
        "paused",
        "regressed",
        "high_xy",
        "high_yaw",
        "negative",
        "nan",
        "missing_covariance",
        "missing_postdate",
        "bad_pose",
    ],
)
def test_clock_and_localization_health(fault):
    data = snapshot()
    if fault == "paused":
        data["observed_ros_ns"] = data["dispatch_ros_ns"]
    elif fault == "regressed":
        data["clock_regressed"] = True
    elif fault == "missing_covariance":
        del data["localization"]["covariance"]
    elif fault == "missing_postdate":
        data["amcl_transform_tolerance_s"] = None
    elif fault == "bad_pose":
        data["tf"]["map_base"]["pose"]["x"] = float("nan")
    else:
        index, value = {
            "high_xy": (0, 0.26),
            "high_yaw": (35, 0.26),
            "negative": (7, -0.1),
            "nan": (0, float("nan")),
        }[fault]
        data["localization"]["covariance"][index] = value
    assert verdict(data)["verdict"] == "INCONCLUSIVE"


def test_missing_provenance_and_ros_failure_cannot_pass():
    assert verdict(provenance={"state": "unconfirmed"})["verdict"] == "INCONCLUSIVE"
    for outcome, status in [("canceled", 5), ("failed", 6), ("succeeded", 6)]:
        assert verdict(outcome=outcome, status=status)["verdict"] == "MISSION_FAILED"
    for outcome, status in [
        ("pending", None),
        ("termination_unconfirmed", None),
        ("cancellation_unconfirmed", 6),
    ]:
        assert verdict(outcome=outcome, status=status)["verdict"] == "INCONCLUSIVE"


def test_policy_is_strict_copied_and_rotation_invalidity_is_explicit():
    result = policy_for({})
    result["xy_tolerance_m"] = 9
    assert DEFAULT_POLICY["xy_tolerance_m"] == 0.2
    for value in [0, -1, True, float("nan"), "0.2"]:
        policy = dict(DEFAULT_POLICY, xy_tolerance_m=value)
        with pytest.raises(ValueError):
            policy_for({"validation": policy})
    with pytest.raises(ValueError):
        policy_for({"validation": {}})
    with pytest.raises(ValueError):
        policy_for({"validation": dict(DEFAULT_POLICY, yaw_tolerance_rad=4)})
    with pytest.raises(ValueError, match="normalized"):
        pose_value(SimpleNamespace(x=0, y=0), SimpleNamespace(x=0, y=0, z=0, w=0))
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def artifacts(tmp_path):
    bag = tmp_path / "telemetry"
    bag.mkdir()
    (bag / "test.mcap").write_bytes(b"\x89MCAP0\r\n" * 2)
    (bag / "metadata.yaml").write_text(
        yaml.safe_dump(
            dict(
                rosbag2_bagfile_information=dict(
                    storage_identifier="mcap",
                    relative_file_paths=["test.mcap"],
                    topics_with_message_count=[
                        dict(topic_metadata=dict(name="/odom"), message_count=1)
                    ],
                )
            )
        )
    )
    parameters = {"setting": 1}
    hashes = {"yaml_sha256": "yaml", "image_sha256": "image"}
    trial = dict(
        run_id="run",
        mission_goal_id="goal",
        mission_outcome="succeeded",
        parameters=parameters,
        parameters_after=parameters,
        map_hashes_after=hashes,
        dispatch_ros_ns=1,
    )
    manifest = dict(
        experiment_id="experiment",
        map_hashes=hashes,
        config=dict(
            expected={"runtime_mode": "mock"}, mission=dict(waypoints=[dict(x=0, y=0, yaw=0)])
        ),
    )
    metadata = dict(
        run_id="run",
        settings={"runtime_mode": "mock"},
        recording_enabled=True,
        recording=dict(required_topics=["/odom"]),
        map=hashes,
        waypoints=[dict(frame="map", x=0.0, y=0.0, z=0.0, qx=0.0, qy=0.0, qz=0.0, qw=1.0)],
    )
    saved = dict(
        run_id="run",
        outcome="succeeded",
        started_ros_ns=2,
        ended_ros_ns=3,
        recording=dict(path="telemetry", format="mcap", bytes=16, topic_counts={"/odom": 1}),
    )
    for name, data in [("metadata", metadata), ("result", saved)]:
        (tmp_path / f"{name}.json").write_text(json.dumps(data))
    return trial, manifest


def test_artifact_binding_and_content_changes(tmp_path):
    trial, manifest = artifacts(tmp_path)
    first = artifact_provenance(tmp_path, trial, manifest)
    assert first["state"] == "confirmed"
    assert len(first["artifact_sha256"]) == 4
    # Content hashes detect edits even when the binding fields remain unchanged.
    path = tmp_path / "metadata.json"
    data = json.loads(path.read_text())
    data["software_revision"] = "different"
    path.write_text(json.dumps(data))
    second = artifact_provenance(tmp_path, trial, manifest)
    assert first["artifact_sha256"] != second["artifact_sha256"]
    for key in ("run_id", "waypoints", "map", "recording_enabled", "settings"):
        changed = copy.deepcopy(data)
        changed[key] = None
        path.write_text(json.dumps(changed))
        assert artifact_provenance(tmp_path, trial, manifest)["state"] == "unconfirmed"
    path.write_text(json.dumps(data))
    (tmp_path / "telemetry/test.mcap").write_bytes(b"truncated")
    assert artifact_provenance(tmp_path, trial, manifest)["state"] == "unconfirmed"
