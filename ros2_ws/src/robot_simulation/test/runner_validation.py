"""Invalid server arguments fail explicitly without starting a simulator."""

import subprocess
from pathlib import Path

import pytest
from ament_index_python.packages import get_package_prefix


@pytest.mark.parametrize("arguments", [[], ["missing.sdf", "false"], ["missing.sdf", "maybe"]])
def test_invalid_arguments(arguments):
    executable = (
        Path(get_package_prefix("robot_simulation")) / "lib/robot_simulation/gazebo_runner"
    )
    result = subprocess.run(
        [str(executable), *arguments], capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 1
    assert "gazebo_runner:" in result.stderr
