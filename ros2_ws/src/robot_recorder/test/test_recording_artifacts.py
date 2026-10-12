"""Artifacts and recording validation run without ROS."""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from robot_recorder.artifacts import RunStore, atomic_json  # noqa: E402
from robot_recorder.recording import inspect_bag, load_recording_config  # noqa: E402


def test_runs_never_overwrite_or_use_label_as_path(tmp_path):
    first = RunStore(tmp_path, {"label": "../../escape"})
    second = RunStore(tmp_path, {"label": "../../escape"})
    assert first.directory != second.directory
    assert first.directory.parent == second.directory.parent == tmp_path
    first.start(100)
    assert json.loads((first.directory / "metadata.json").read_text())["started_ros_ns"] == 100
    first.event("preparing", 123)
    first.finish({"outcome": "failed", "recording": None})
    assert json.loads((first.directory / "result.json").read_text())["run_id"] == first.run_id
    assert json.loads((first.directory / "events.jsonl").read_text())["ros_ns"] == 123
    assert not (tmp_path.parent / "escape").exists()


def test_nonfinite_json_cannot_replace_valid_result(tmp_path):
    path = tmp_path / "result.json"
    atomic_json(path, {"value": 1})
    with pytest.raises(ValueError):
        atomic_json(path, {"value": float("nan")})
    assert json.loads(path.read_text()) == {"value": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_recording_defaults_are_valid():
    data = load_recording_config(Path(__file__).resolve().parents[1] / "config/recording.yaml")
    assert data["qos"]["tf_static"]["durability"] == "transient_local"
    assert data["qos"]["scan"]["reliability"] == "best_effort"
    assert "diagnostics" in data["topics"]
    assert "diagnostics" not in data["required_topics"]
    assert data["qos"]["diagnostics"] == {
        "reliability": "reliable",
        "durability": "volatile",
        "depth": 10,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"topics": ["--all"]},
        {"required_topics": ["missing"]},
        {"topics": ["odom", "odom"]},
        {"qos": {"odom": {"depth": 0}}},
    ],
)
def test_bad_recording_config(tmp_path, change):
    data = {"topics": ["odom"], "required_topics": ["odom"], "qos": {}}
    data.update(change)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        load_recording_config(path)


def test_bag_missing_required_data_is_failure(tmp_path):
    magic = b"\x89MCAP0\r\n"
    (tmp_path / "part.mcap").write_bytes(magic + magic)
    data = {
        "rosbag2_bagfile_information": {
            "storage_identifier": "mcap",
            "relative_file_paths": ["part.mcap"],
            "topics_with_message_count": [],
        }
    }
    (tmp_path / "metadata.yaml").write_text(yaml.safe_dump(data))
    with pytest.raises(RuntimeError, match="Required telemetry"):
        inspect_bag(tmp_path, ["/odom"])
    (tmp_path / "part.mcap").write_bytes(magic + b"incomplete")
    with pytest.raises(RuntimeError, match="incomplete"):
        inspect_bag(tmp_path, [])


def test_map_references_detect_changes(tmp_path):
    from robot_recorder.artifacts import map_reference

    assert map_reference("") is None
    image = tmp_path / "map.pgm"
    image.write_bytes(b"P5\n1 1\n255\n\xff")
    map_file = tmp_path / "map.yaml"
    map_file.write_text("image: map.pgm\n")
    before = map_reference(str(map_file))
    image.write_bytes(b"P5\n1 1\n255\n\x00")
    after = map_reference(str(map_file))
    assert before["yaml_sha256"] == after["yaml_sha256"]
    assert before["image_sha256"] != after["image_sha256"]
    image.unlink()
    with pytest.raises(FileNotFoundError):
        map_reference(str(map_file))


def test_absent_optional_diagnostics_does_not_invalidate_recording(tmp_path):
    config = load_recording_config(Path(__file__).resolve().parents[1] / "config/recording.yaml")
    magic = b"\x89MCAP0\r\n"
    (tmp_path / "part.mcap").write_bytes(magic + magic)
    counts = [
        {"topic_metadata": {"name": name}, "message_count": 1}
        for name in config["required_topics"]
    ]
    data = {
        "rosbag2_bagfile_information": {
            "storage_identifier": "mcap",
            "relative_file_paths": ["part.mcap"],
            "topics_with_message_count": counts,
        }
    }
    (tmp_path / "metadata.yaml").write_text(yaml.safe_dump(data))
    assert "diagnostics" not in inspect_bag(tmp_path, config["required_topics"])["topic_counts"]
