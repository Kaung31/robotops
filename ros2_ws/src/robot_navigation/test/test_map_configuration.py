"""Map-file validation and simulator/ROS sensor contracts without ROS."""

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xacro
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
SRC = PACKAGE.parent
SPEC = importlib.util.spec_from_file_location(
    "map_config", PACKAGE / "robot_navigation/map_config.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.fixture
def map_yaml(tmp_path: Path) -> Path:
    (tmp_path / "image.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    data = {
        "image": "image.pgm",
        "resolution": 0.05,
        "origin": [0.0, 0.0, 0.0],
        "free_thresh": 0.25,
        "occupied_thresh": 0.65,
        "negate": 0,
    }
    path = tmp_path / "map.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_valid_relative_map_image(map_yaml: Path) -> None:
    assert module.validate_saved_map(str(map_yaml)) == map_yaml


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("image", "missing.pgm"),
        ("resolution", 0),
        ("resolution", float("nan")),
        ("origin", [0, 0]),
        ("origin", [0, 0, float("inf")]),
        ("occupied_thresh", -1),
        ("free_thresh", 0.9),
        ("negate", 4),
        ("mode", "unknown"),
    ],
)
def test_invalid_map(map_yaml: Path, key: str, value: object) -> None:
    data = yaml.safe_load(map_yaml.read_text())
    data[key] = value
    map_yaml.write_text(yaml.safe_dump(data))
    with pytest.raises((ValueError, FileNotFoundError)):
        module.validate_saved_map(str(map_yaml))


def test_missing_map_file() -> None:
    with pytest.raises(ValueError, match="required"):
        module.validate_saved_map("")


def test_sensor_frames_topics_and_world() -> None:
    root = ET.fromstring(
        xacro.process_file(
            str(SRC / "robot_simulation/urdf/gazebo.urdf.xacro"),
            mappings={
                "description_dir": str(SRC / "robot_description"),
                "controllers_file": "/tmp/test.yaml",
            },
        ).toxml()
    )
    lidar = root.find("gazebo[@reference='lidar_link']/sensor")
    imu = root.find("gazebo[@reference='imu_link']/sensor")
    assert lidar.attrib["type"] == "gpu_lidar"
    assert lidar.find("gz_frame_id").text == "lidar_link"
    assert imu.attrib["type"] == "imu" and imu.find("gz_frame_id").text == "imu_link"
    bridge = yaml.safe_load((SRC / "robot_simulation/config/bridge.yaml").read_text())
    for topic, msg_type in (("scan", "LaserScan"), ("imu/data", "Imu")):
        entry = next(v for v in bridge if v["ros_topic_name"] == topic)
        assert entry["direction"] == "GZ_TO_ROS"
        assert entry["qos_profile"] == "SENSOR_DATA"
        assert entry["ros_type_name"] == f"sensor_msgs/msg/{msg_type}"
    world = ET.parse(SRC / "robot_simulation/worlds/mapping_lab.sdf").getroot().find("world")
    assert world.attrib["name"] == "mapping_lab"
    assert len(world.findall("model")) == 8
    assert world.find(".//include") is None  # no remotely fetched tutorial assets
