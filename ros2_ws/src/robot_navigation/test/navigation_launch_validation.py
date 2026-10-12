"""Invalid Nav2 launch input must fail before creating processes."""

import importlib.util
from pathlib import Path

import pytest
from launch import LaunchContext

SPEC = importlib.util.spec_from_file_location(
    "navigation_launch", Path(__file__).resolve().parents[1] / "launch/navigation.launch.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize(
    ("profile", "map_file"),
    [
        ("missing", ""),
        ("../../other", ""),
        ("navfn_rpp", ""),
        ("smac_dwb", "/missing/robotops.yaml"),
    ],
)
def test_invalid_input(profile: str, map_file: str) -> None:
    context = LaunchContext()
    context.launch_configurations.update(profile=profile, map_file=map_file)
    with pytest.raises((ValueError, FileNotFoundError)):
        module.navigation(context)


@pytest.mark.parametrize("directory", [False, True])
def test_invalid_behavior_tree_fails_before_creating_nodes(tmp_path, monkeypatch, directory):
    geometry = tmp_path / "geometry.yaml"
    geometry.touch()
    bt = tmp_path / ("directory" if directory else "missing.xml")
    if directory:
        bt.mkdir()
    monkeypatch.setattr(module, "validate_saved_map", lambda _: tmp_path / "map.yaml")
    monkeypatch.setattr(module, "navigation_parameters", lambda *_: {})

    def unexpected_node(*args, **kwargs):
        pytest.fail("Invalid tree created a ROS process")

    monkeypatch.setattr(module, "Node", unexpected_node)
    context = LaunchContext()
    context.launch_configurations.update(
        profile="navfn_rpp",
        map_file="map.yaml",
        geometry_file=str(geometry),
        use_sim_time="true",
        autostart="true",
        bt_xml=str(bt),
    )
    with pytest.raises((ValueError, FileNotFoundError)):
        module.navigation(context)
