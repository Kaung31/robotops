"""CI-only map preparation cannot overwrite artifacts or accept identity drift."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "ci_fixtures", ROOT / "scripts/ci/prepare_ros_fixtures.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.fixture
def checkout(tmp_path):
    for relative in (
        "benchmarks/warehouse_v1/matrix.json",
        "ros2_ws/src/robot_simulation/config/warehouse_v1.json",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    return tmp_path


def test_recreated_inputs_match_exact_frozen_pins(checkout):
    module.prepare(checkout)
    matrix = json.loads((checkout / "benchmarks/warehouse_v1/matrix.json").read_bytes())
    for key in ("map_yaml", "map_image", "map_metadata"):
        pin = matrix["scenario"][key]
        data = (checkout / pin["path"]).read_bytes()
        assert module.hashlib.sha256(data).hexdigest() == pin["sha256"]
    assert len(list((checkout / "artifacts/maps").iterdir())) == 3


def test_existing_artifacts_are_untouched(checkout):
    directory = checkout / "artifacts"
    directory.mkdir()
    sentinel = directory / "existing.txt"
    sentinel.write_bytes(b"original")
    with pytest.raises(FileExistsError, match="no artifacts directory"):
        module.prepare(checkout)
    assert sentinel.read_bytes() == b"original"
    assert list(directory.iterdir()) == [sentinel]


def test_identity_drift_fails_before_writing_inputs(checkout):
    path = checkout / "benchmarks/warehouse_v1/matrix.json"
    matrix = json.loads(path.read_bytes())
    matrix["scenario"]["map_image"]["sha256"] = "0" * 64
    path.write_text(json.dumps(matrix))
    with pytest.raises(ValueError, match="frozen identity"):
        module.prepare(checkout)
    assert not (checkout / "artifacts").exists()
