"""Portable model contracts; no running ROS graph is needed."""

import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xacro
import yaml

PACKAGE = Path(__file__).resolve().parents[1]
MODEL = PACKAGE / "urdf" / "robot.urdf.xacro"
CONFIG = PACKAGE / "config" / "geometry.yaml"


def expand(geometry_file: Path | None = None) -> ET.Element:
    mappings = {"geometry_file": str(geometry_file)} if geometry_file else {}
    return ET.fromstring(xacro.process_file(str(MODEL), mappings=mappings).toxml())


def vector(element: ET.Element, attribute: str) -> list[float]:
    return [float(v) for v in element.attrib[attribute].split()]


@pytest.fixture(params=[False, True], ids=["default", "alternate"])
def model(request: pytest.FixtureRequest, tmp_path: Path) -> tuple[ET.Element, dict]:
    config = yaml.safe_load(CONFIG.read_text())
    if request.param:
        config.update(wheel_radius=0.10, wheel_separation=0.42, chassis_length=0.50)
        path = tmp_path / "geometry with spaces.yaml"
        path.write_text(yaml.safe_dump(config))
        return expand(path), config
    return expand(), config


def test_tree_and_interfaces(model: tuple[ET.Element, dict]) -> None:
    root, _ = model
    links = [link.attrib["name"] for link in root.findall("link")]
    joints = root.findall("joint")
    assert len(links) == len(set(links)) == 7
    assert len({j.attrib["name"] for j in joints}) == len(joints) == len(links) - 1
    parents = {j.find("child").attrib["link"]: j.find("parent").attrib["link"] for j in joints}
    assert len(parents) == len(joints)
    assert set(links) - parents.keys() == {"base_link"}
    for child in parents:
        seen = set()
        while child != "base_link":
            assert child not in seen
            seen.add(child)
            child = parents[child]
            assert child in links
    assert {j.attrib["name"] for j in joints if j.attrib["type"] != "fixed"} == {
        "left_wheel_joint",
        "right_wheel_joint",
    }
    for name in ("lidar", "imu"):
        joint = root.find(f"joint[@name='{name}_joint']")
        assert joint.attrib["type"] == "fixed"
        assert joint.find("parent").attrib["link"] == "base_link"
        assert joint.find("child").attrib["link"] == f"{name}_link"
    assert not {"map", "odom"} & set(links)
    assert root.find("link[@name='base_link']/inertial") is None
    assert root.find("ros2_control") is None
    assert root.find("gazebo") is None
    assert root.find(".//plugin") is None
    assert "xacro:" not in ET.tostring(root, encoding="unicode")


def test_wheels_and_ground_clearance(model: tuple[ET.Element, dict]) -> None:
    root, g = model
    for side, sign in (("left", 1), ("right", -1)):
        joint = root.find(f"joint[@name='{side}_wheel_joint']")
        assert joint.attrib["type"] == "continuous"
        assert vector(joint.find("origin"), "xyz") == pytest.approx(
            [0, sign * g["wheel_separation"] / 2, 0]
        )
        # Positive rotation around +Y rolls both wheels forward (+X).
        assert vector(joint.find("axis"), "xyz") == [0, 1, 0]
        wheel = root.find(f"link[@name='{side}_wheel_link']")
        for kind in ("visual", "collision"):
            cylinder = wheel.find(f"{kind}/geometry/cylinder")
            assert float(cylinder.attrib["radius"]) == g["wheel_radius"]
            assert float(cylinder.attrib["length"]) == g["wheel_width"]
            assert vector(wheel.find(f"{kind}/origin"), "rpy") == pytest.approx(
                [math.pi / 2, 0, 0]
            )
        inertia = wheel.find("inertial/inertia")
        assert float(inertia.attrib["izz"]) == pytest.approx(
            g["wheel_mass"] * g["wheel_radius"] ** 2 / 2
        )
        assert vector(wheel.find("inertial/origin"), "rpy") == pytest.approx([math.pi / 2, 0, 0])
    caster_z = vector(root.find("joint[@name='caster_joint']/origin"), "xyz")[2]
    assert caster_z - g["caster_radius"] == pytest.approx(-g["wheel_radius"])
    chassis_z = vector(root.find("joint[@name='chassis_joint']/origin"), "xyz")[2]
    assert chassis_z - g["chassis_height"] / 2 > -g["wheel_radius"]
    assert g["wheel_separation"] > g["chassis_width"] + g["wheel_width"]
    for name, half_height in (("lidar", g["lidar_height"] / 2), ("imu", g["imu_size"] / 2)):
        sensor_z = vector(root.find(f"joint[@name='{name}_joint']/origin"), "xyz")[2]
        assert sensor_z - half_height == pytest.approx(chassis_z + g["chassis_height"] / 2)


def test_physical_links(model: tuple[ET.Element, dict]) -> None:
    root, _ = model
    for link in root.findall("link"):
        if link.attrib["name"] == "base_link":
            continue
        assert link.find("visual/geometry") is not None
        assert link.find("collision/geometry") is not None
        assert float(link.find("inertial/mass").attrib["value"]) > 0
        inertia = link.find("inertial/inertia").attrib
        diagonal = [float(inertia[key]) for key in ("ixx", "iyy", "izz")]
        assert all(math.isfinite(v) and v > 0 for v in diagonal)
        assert all(float(inertia[key]) == 0 for key in ("ixy", "ixz", "iyz"))
        # Principal moments must satisfy the physical triangle inequalities.
        assert 2 * max(diagonal) <= sum(diagonal) + 1e-12


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("wheel_radius", 0, "finite positive"),
        ("chassis_mass", -1, "finite positive"),
        ("wheel_mass", float("nan"), "finite positive"),
        ("wheel_mass", float("inf"), "finite positive"),
        ("wheel_separation", 0.20, "Wheel separation"),
        ("caster_radius", 0.04, "Caster must fit"),
        ("chassis_length", 0.08, "Chassis length"),
    ],
)
def test_invalid_geometry(tmp_path: Path, key: str, value: float, message: str) -> None:
    config = yaml.safe_load(CONFIG.read_text())
    config[key] = value
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(xacro.XacroException, match=message):
        expand(path)


def test_missing_geometry_file(tmp_path: Path) -> None:
    with pytest.raises(xacro.XacroException, match="No such file"):
        expand(tmp_path / "missing.yaml")


def test_cli_relative_input_path(tmp_path: Path) -> None:
    # Python API tests use absolute paths; also exercise the ordinary CLI form.
    output = tmp_path / "robot.urdf"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import xacro; xacro.main()",
            os.path.relpath(MODEL, tmp_path),
            "-o",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert ET.parse(output).getroot().attrib["name"] == "robotops_base"


def test_missing_geometry_key(tmp_path: Path) -> None:
    config = yaml.safe_load(CONFIG.read_text())
    del config["wheel_radius"]
    path = tmp_path / "missing-key.yaml"
    path.write_text(yaml.safe_dump(config))
    with pytest.raises(xacro.XacroException, match="wheel_radius"):
        expand(path)
