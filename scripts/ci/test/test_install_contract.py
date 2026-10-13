"""Installation checks must reject absent markers and changed installed resources."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ci_install", Path(__file__).resolve().parents[1] / "verify_ros_install.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.fixture
def installed(tmp_path):
    source = tmp_path / "src"
    package = source / "example"
    package.mkdir(parents=True)
    (package / "package.xml").write_text("<package><name>example</name></package>")
    (package / "config").mkdir()
    (package / "config/settings.yaml").write_text("enabled: true\n")
    install = tmp_path / "install"
    share = install / "example/share"
    marker = share / "ament_index/resource_index/packages/example"
    marker.parent.mkdir(parents=True)
    marker.touch()
    destination = share / "example"
    (destination / "config").mkdir(parents=True)
    (destination / "package.xml").write_bytes((package / "package.xml").read_bytes())
    (destination / "config/settings.yaml").write_bytes(
        (package / "config/settings.yaml").read_bytes()
    )
    return source, install, destination, marker


def test_valid_installation(installed):
    source, install, _, _ = installed
    assert module.verify_resources(source, install) == (1, 1)


@pytest.mark.parametrize("target", ["package.xml", "config/settings.yaml"])
def test_changed_installed_bytes_rejected(installed, target):
    source, install, destination, _ = installed
    (destination / target).write_text("tampered")
    with pytest.raises(RuntimeError, match="differs"):
        module.verify_resources(source, install)


def test_missing_ament_marker_rejected(installed):
    source, install, _, marker = installed
    marker.unlink()
    with pytest.raises(RuntimeError, match="ament marker"):
        module.verify_resources(source, install)


def test_empty_source_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="No source packages"):
        module.verify_resources(tmp_path / "src", tmp_path / "install")
