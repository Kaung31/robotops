"""Both adapters must expose the same ros2_control wheel contract."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import xacro

SRC = Path(__file__).resolve().parents[2]


def expand(package: str, model: str) -> ET.Element:
    return ET.fromstring(
        xacro.process_file(
            str(SRC / package / "urdf" / model),
            mappings={
                "description_dir": str(SRC / "robot_description"),
                "controllers_file": "/tmp/robotops-test-controllers.yaml",
            },
        ).toxml()
    )


def test_backend_interface_parity() -> None:
    mock = expand("robot_bringup", "mock.urdf.xacro")
    sim = expand("robot_simulation", "gazebo.urdf.xacro")
    for model, plugin in (
        (mock, "mock_components/GenericSystem"),
        (sim, "gz_ros2_control/GazeboSimSystem"),
    ):
        control = model.find("ros2_control")
        assert control.find("hardware/plugin").text == plugin
        joints = control.findall("joint")
        assert {j.attrib["name"] for j in joints} == {"left_wheel_joint", "right_wheel_joint"}
        for joint in joints:
            assert [v.attrib["name"] for v in joint.findall("command_interface")] == ["velocity"]
            assert {v.attrib["name"] for v in joint.findall("state_interface")} == {
                "position",
                "velocity",
            }
    assert ET.tostring(mock.find("ros2_control/joint")) == ET.tostring(
        sim.find("ros2_control/joint")
    )
    for tag in ("link", "joint"):
        assert [ET.tostring(v) for v in mock.findall(tag)] == [
            ET.tostring(v) for v in sim.findall(tag)
        ]
    assert mock.find("gazebo") is None
    assert mock.find("ros2_control/hardware/param[@name='calculate_dynamics']").text == "true"


def test_sim_requires_controller_config() -> None:
    with pytest.raises(xacro.XacroException, match="controllers_file"):
        xacro.process_file(
            str(SRC / "robot_simulation/urdf/gazebo.urdf.xacro"),
            mappings={"description_dir": str(SRC / "robot_description")},
        )
