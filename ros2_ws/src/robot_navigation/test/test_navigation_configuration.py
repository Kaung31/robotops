"""Portable Nav2 configuration, geometry and command-contract regressions."""

import importlib.util
import math
from pathlib import Path

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
GEOMETRY = PACKAGE.parent / "robot_description/config/geometry.yaml"
SPEC = importlib.util.spec_from_file_location(
    "navigation_config", PACKAGE / "robot_navigation/navigation_config.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("profile", module.PROFILES)
def test_profile_contract(profile: str) -> None:
    params = module.navigation_parameters(PACKAGE / "config", profile, GEOMETRY, True)
    controller = params["controller_server"]["ros__parameters"]
    assert controller["enable_stamped_cmd_vel"] is True
    assert controller["publish_zero_velocity"] is True
    assert params["behavior_server"]["ros__parameters"]["enable_stamped_cmd_vel"] is True
    assert params["planner_server"]["ros__parameters"]["GridBased"]["allow_unknown"] is False
    for name in ("local_costmap", "global_costmap"):
        costmap = params[name][name]["ros__parameters"]
        assert costmap["use_sim_time"] is True
        assert costmap["robot_base_frame"] == "base_link"
        assert 0.30 < costmap["robot_radius"] < 0.31
        assert costmap["obstacle_layer"]["scan"]["topic"] == "scan"
        assert costmap["obstacle_layer"]["scan"]["expected_update_rate"] > 0
    assert params["bt_navigator"]["ros__parameters"]["odom_topic"] == "odom"
    assert params["controller_server"]["ros__parameters"]["use_sim_time"] is True


def test_invalid_profile_is_rejected_before_reading_files() -> None:
    with pytest.raises(ValueError, match="profile"):
        module.navigation_parameters(Path("/missing"), "../../unknown", GEOMETRY, False)


def test_geometry_override_encloses_wider_robot(tmp_path: Path) -> None:
    geometry = yaml.safe_load(GEOMETRY.read_text())
    geometry["wheel_separation"] = 0.8
    path = tmp_path / "geometry.yaml"
    path.write_text(yaml.safe_dump(geometry))
    params = module.navigation_parameters(PACKAGE / "config", "smac_dwb", path, False)
    radius = params["global_costmap"]["global_costmap"]["ros__parameters"]["robot_radius"]
    assert radius >= math.hypot(0.24, 0.415)
    assert params["local_costmap"]["local_costmap"]["ros__parameters"]["use_sim_time"] is False


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, "wide"])
def test_invalid_geometry(tmp_path: Path, value: object) -> None:
    geometry = yaml.safe_load(GEOMETRY.read_text())
    geometry["wheel_separation"] = value
    path = tmp_path / "geometry.yaml"
    path.write_text(yaml.safe_dump(geometry))
    with pytest.raises(ValueError, match="wheel_separation"):
        module.navigation_parameters(PACKAGE / "config", "navfn_rpp", path, False)


def test_sensor_topic_parent_namespace():
    sensor_topic = module.sensor_topic

    assert sensor_topic("scan") == "/scan"
    assert sensor_topic("fault_probe/scan", "/robot") == "/robot/fault_probe/scan"
    assert sensor_topic("/sensor/scan", "/robot") == "/sensor/scan"
    for topic in ("", "~scan", "scan/", "../scan", "a//scan", "https://scan", "/1scan"):
        with pytest.raises(ValueError):
            sensor_topic(topic)
