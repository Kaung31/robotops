"""Fail closed before constructing ROS processes for unsupported runtime modes."""

import importlib.util
from pathlib import Path

import pytest
from launch import LaunchContext

SPEC = importlib.util.spec_from_file_location(
    "robot_launch", Path(__file__).resolve().parents[1] / "launch/robot.launch.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("mode", ["real", "replay", "", "invalid"])
def test_unsupported_mode_starts_nothing(mode: str) -> None:
    context = LaunchContext()
    context.launch_configurations["mode"] = mode
    with pytest.raises(ValueError, match="Unsupported mode"):
        module.start_robot(context)


@pytest.mark.parametrize(
    "mode,sensors,enabled,expected",
    [
        ("mock", "true", "false", None),
        ("mock", "true", "true", ["odom"]),
        ("sim", "false", "true", ["odom"]),
        ("sim", "true", "true", ["odom", "scan", "imu"]),
    ],
)
def test_optional_diagnostics_composition(monkeypatch, mode, sensors, enabled, expected):
    captured = []
    real_node = module.Node

    def capture(**kwargs):
        captured.append(kwargs)
        return real_node(**kwargs)

    monkeypatch.setattr(module, "Node", capture)
    context = LaunchContext()
    context.launch_configurations.update(
        {
            "mode": mode,
            "sensors": sensors,
            "diagnostics": enabled,
            "gui": "false",
            "headless_rendering": "true",
            "world": "control_pad",
            "geometry_file": str(
                Path(__file__).resolve().parents[2] / "robot_description/config/geometry.yaml"
            ),
        }
    )
    module.start_robot(context)
    observers = [kwargs for kwargs in captured if kwargs["package"] == "robot_diagnostics"]
    if expected is None:
        assert not observers
    else:
        assert len(observers) == 1
        assert observers[0]["parameters"] == [
            {"use_sim_time": mode == "sim", "enabled_streams": expected}
        ]
        assert "on_exit" not in observers[0]


def test_diagnostics_default_is_off_with_explicit_environment_opt_in(monkeypatch):
    argument = next(
        action
        for action in module.generate_launch_description().entities
        if getattr(action, "name", None) == "diagnostics"
    )
    monkeypatch.delenv("ROBOTOPS_DIAGNOSTICS", raising=False)
    assert "".join(part.perform(LaunchContext()) for part in argument.default_value) == "false"
    monkeypatch.setenv("ROBOTOPS_DIAGNOSTICS", "true")
    assert "".join(part.perform(LaunchContext()) for part in argument.default_value) == "true"
