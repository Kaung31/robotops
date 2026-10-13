"""Portable Nav2 configuration, geometry and command-contract regressions."""

import hashlib
import importlib.util
import json
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


# Canonical parsed-value pins captured from accepted integration 8430110 before
# reconstruction. Dict order is irrelevant; scalar types/list order are significant.
ACCEPTED_CONFIG_VALUES = {
    "navigation.yaml": "dfd446025093e2790b653adac2e79a23d78de453361e2b49c6fc98d307d0f79a",
    "localization.yaml": "c0ccb155f59f3602ccc82c2dafb9bd1ed7c9def949157e7956c3f3d9e50e0425",
    "profiles/navfn_rpp.yaml": "3c3202cb6de499e143176535dbab4b8281291988c41f847d371d7e517313e129",
    "profiles/smac_dwb.yaml": "1e0bc38846920031f04890546876367a5d2b7e5b0e0ff98d795c646c6d7eef44",
    "slam.yaml": "03b601ed4d9f9cafc4619210a0302b761cf00b7f2bd9808e9b5d208f0964a478",
}
ACCEPTED_EFFECTIVE = {
    ("navfn_rpp", False): "73dd3e41748ec0b3d1ebd23c58d30a5ab1c988b60ac135aab1bc60406635e575",
    ("smac_dwb", False): "d7bb4eb083a8b787943a503b05a7ae301a8731dd2f7e595093d014dd097f8873",
    ("navfn_rpp", True): "aaa521b3c8981a3c3a60e60f562afa5ec696ae018f3ecc636748f1c34eef6f9e",
    ("smac_dwb", True): "509b4a28a4a07b034dbeeffc8d3b2c546b980f990394315fafea66fde23869e6",
}


def semantic_hash(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("filename,expected", ACCEPTED_CONFIG_VALUES.items())
def test_reconstruction_preserves_accepted_typed_values(filename, expected):
    assert semantic_hash(yaml.safe_load((PACKAGE / "config" / filename).read_bytes())) == expected


@pytest.mark.parametrize("key,expected", ACCEPTED_EFFECTIVE.items())
def test_reconstruction_preserves_composed_profile(key, expected):
    profile, clock = key
    value = module.navigation_parameters(PACKAGE / "config", profile, GEOMETRY, clock)
    assert semantic_hash(value) == expected
