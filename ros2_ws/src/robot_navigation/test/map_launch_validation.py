"""Invalid workflow/map combinations must create no lifecycle processes."""

import importlib.util
from pathlib import Path

import pytest
from launch import LaunchContext

SPEC = importlib.util.spec_from_file_location(
    "map_launch", Path(__file__).resolve().parents[1] / "launch/map.launch.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize(
    ("workflow", "filename"),
    [
        ("unknown", ""),
        ("localization", ""),
        ("localization", "/missing/robotops/map.yaml"),
        ("mapping", "/some/map.yaml"),
    ],
)
def test_invalid_workflow(workflow: str, filename: str) -> None:
    context = LaunchContext()
    context.launch_configurations.update(workflow=workflow, map_file=filename)
    with pytest.raises((ValueError, FileNotFoundError)):
        module.pipeline(context)
