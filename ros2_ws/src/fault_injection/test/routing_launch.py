"""Guarded probe composition rejects unsafe reuse before starting ROS nodes."""

import importlib.util
from pathlib import Path

import pytest
from launch import LaunchContext

SPEC = importlib.util.spec_from_file_location(
    "probe_launch", Path(__file__).resolve().parents[1] / "launch/nav2_probe.launch.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("mode", ["real", "replay", "mock", ""])
def test_non_sim_does_not_create_guard(tmp_path, mode):
    context = LaunchContext()
    context.launch_configurations.update(mode=mode, runtime_directory=str(tmp_path))
    with pytest.raises(ValueError):
        module.probe(context)
    assert not list(tmp_path.iterdir())


def test_uncertain_route_cannot_restart(tmp_path, monkeypatch):
    guard = tmp_path / "routing.guard"
    guard.write_text("quarantine\n")
    monkeypatch.setattr(
        module, "Node", lambda **_: pytest.fail("Started process with existing quarantine")
    )
    context = LaunchContext()
    context.launch_configurations.update(mode="sim", runtime_directory=str(tmp_path))
    with pytest.raises(FileExistsError):
        module.probe(context)
    assert guard.read_text() == "quarantine\n"


def test_local_uncertainty_must_not_be_bypassed(tmp_path):
    (tmp_path / "recovery.guard").write_text("prior-session\n")
    context = LaunchContext()
    context.launch_configurations.update(mode="sim", runtime_directory=str(tmp_path))
    with pytest.raises(FileExistsError):
        module.probe(context)
    assert (tmp_path / "recovery.guard").read_text() == "prior-session\n"


def test_probe_enables_input_watchdog_and_exit_shutdown_without_unlock(tmp_path, monkeypatch):
    from launch.actions import Shutdown

    captured = []
    monkeypatch.setattr(module, "get_package_share_directory", lambda _: str(tmp_path))
    monkeypatch.setattr(module, "Node", lambda **kwargs: captured.append(kwargs) or object())
    context = LaunchContext()
    context.launch_configurations.update(
        mode="sim",
        runtime_directory=str(tmp_path),
        map_file=str(tmp_path / "map.yaml"),
        experiment_id="probe",
        trial_id="trial",
        profile="navfn_rpp",
    )
    module.probe(context)
    params = captured[0]["parameters"][0]
    assert params["lifecycle_mode"] == "owned_v2"
    assert params["input_timeout_seconds"] == 2.0 and params["input_startup_seconds"] == 15.0
    assert isinstance(captured[0]["on_exit"], Shutdown)
    assert (tmp_path / "routing.guard").exists()
