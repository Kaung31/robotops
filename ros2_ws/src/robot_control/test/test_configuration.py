"""Test geometry-derived control parameters independently of ROS."""

import importlib.util
from pathlib import Path

import pytest
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "configuration", PACKAGE / "robot_control/configuration.py"
)
configuration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(configuration)
CONFIG = PACKAGE / "config/controllers.yaml"


@pytest.mark.parametrize("sim_time", [False, True])
def test_shared_geometry_and_time(tmp_path: Path, sim_time: bool) -> None:
    geometry = tmp_path / "geometry.yaml"
    geometry.write_text("wheel_radius: 0.12\nwheel_separation: 0.48\n")
    params = configuration.controller_parameters(CONFIG, geometry, sim_time)
    drive = params["drive_controller"]["ros__parameters"]
    assert drive["wheel_radius"] == 0.12
    assert drive["wheel_separation"] == 0.48
    assert drive["position_feedback"] and not drive["open_loop"]
    assert drive["enable_odom_tf"]
    assert 0 < drive["cmd_vel_timeout"] <= 0.5
    assert all(node["ros__parameters"]["use_sim_time"] == sim_time for node in params.values())
    # No mutation of the stored shared profile.
    assert (
        "wheel_radius"
        not in yaml.safe_load(CONFIG.read_text())["drive_controller"]["ros__parameters"]
    )


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "wrong", True])
def test_invalid_geometry(tmp_path: Path, value: object) -> None:
    geometry = tmp_path / "geometry.yaml"
    geometry.write_text(yaml.safe_dump({"wheel_radius": value, "wheel_separation": 0.4}))
    with pytest.raises(ValueError, match="wheel_radius"):
        configuration.controller_parameters(CONFIG, geometry, False)


def test_mux_priorities_and_timeout() -> None:
    params = yaml.safe_load((PACKAGE / "config/mux.yaml").read_text())["twist_mux"][
        "ros__parameters"
    ]
    assert params["use_stamped"]
    topics = params["topics"]
    assert (
        topics["teleop"]["priority"] > topics["test"]["priority"] > topics["autonomy"]["priority"]
    )
    assert len({t["topic"] for t in topics.values()}) == 3
    assert all(0 < t["timeout"] <= 0.5 and not t["topic"].startswith("/") for t in topics.values())
