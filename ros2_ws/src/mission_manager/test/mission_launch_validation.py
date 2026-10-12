"""Unsupported runtime modes must not create a mission node."""

import importlib.util
from pathlib import Path

import pytest
from launch import LaunchContext

SPEC = importlib.util.spec_from_file_location(
    "mission_launch", Path(__file__).resolve().parents[1] / "launch/mission.launch.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("mode", ["replay", "real", "unknown"])
def test_unsupported_mode(mode):
    context = LaunchContext()
    context.launch_configurations["mode"] = mode
    with pytest.raises(ValueError):
        module.start(context)


@pytest.mark.parametrize("provided", [False, True])
def test_launch_provenance_overrides_are_explicit_and_optional(monkeypatch, provided):
    context = LaunchContext()
    values = dict(
        environment="mapping_lab", navigation_profile="smac_dwb", map_file="/tmp/lab.yaml"
    )
    context.launch_configurations.update(mode="sim", config_file="/tmp/mission.yaml")
    context.launch_configurations.update({k: v if provided else "" for k, v in values.items()})
    captured = {}

    def node(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(module, "Node", node)
    assert len(module.start(context)) == 1
    parameters = captured["parameters"][1]
    assert parameters == dict(
        runtime_mode="sim", use_sim_time=True, **(values if provided else {})
    )
