"""Verify this worktree's installed package/resource identities without starting ROS."""

from __future__ import annotations

import argparse
import importlib.util
import os
import xml.etree.ElementTree as ET
from pathlib import Path

RESOURCE_DIRECTORIES = ("config", "launch", "urdf", "worlds", "rviz")
PYTHON_PACKAGES = (
    "robot_control",
    "robot_navigation",
    "mission_manager",
    "robot_recorder",
    "experiment_runner",
    "robot_diagnostics",
    "robotops_interfaces.msg",
    "robotops_interfaces.action",
)


def verify_resources(source: Path, install: Path) -> tuple[int, int]:
    packages = 0
    resources = 0
    for manifest in sorted(source.glob("*/package.xml")):
        model = ET.parse(manifest).getroot()
        name = model.findtext("name")
        if not name:
            raise ValueError(f"Missing package name: {manifest}")
        prefix = install / name
        marker = prefix / "share/ament_index/resource_index/packages" / name
        if not marker.is_file():
            raise RuntimeError(f"Missing installed ament marker: {marker}")
        installed_manifest = prefix / "share" / name / "package.xml"
        if installed_manifest.read_bytes() != manifest.read_bytes():
            raise RuntimeError(f"Installed manifest differs: {name}")
        packages += 1
        for directory in RESOURCE_DIRECTORIES:
            for original in sorted((manifest.parent / directory).rglob("*")):
                if not original.is_file() or "__pycache__" in original.parts:
                    continue
                relative = original.relative_to(manifest.parent)
                installed = prefix / "share" / name / relative
                if installed.read_bytes() != original.read_bytes():
                    raise RuntimeError(f"Installed resource differs: {name}/{relative}")
                resources += 1
    if not packages or not resources:
        raise RuntimeError("No source packages/resources were verified")
    return packages, resources


def verify_python(install: Path) -> None:
    for package in PYTHON_PACKAGES:
        spec = importlib.util.find_spec(package)
        if spec is None or spec.origin is None:
            raise RuntimeError(f"Installed Python package unavailable: {package}")
        if not Path(spec.origin).resolve().is_relative_to(install.resolve()):
            raise RuntimeError(f"Python package resolved outside this installation: {package}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    args = parser.parse_args()
    root = args.repository.resolve()
    install = root / "ros2_ws/install"
    if Path.cwd().resolve().is_relative_to(root):
        raise RuntimeError("Run installation verification outside the source tree (e.g. /tmp)")
    prefixes = [Path(p).resolve() for p in os.environ.get("AMENT_PREFIX_PATH", "").split(":") if p]
    for manifest in (root / "ros2_ws/src").glob("*/package.xml"):
        name = ET.parse(manifest).getroot().findtext("name")
        if name is None or (install / name).resolve() not in prefixes:
            raise RuntimeError(f"This worktree's package is absent from AMENT_PREFIX_PATH: {name}")
    packages, resources = verify_resources(root / "ros2_ws/src", install)
    verify_python(install)
    print(f"Verified {packages} installed packages, {resources} resources and Python imports")


if __name__ == "__main__":
    main()
