"""Publish the backend-independent description; synthetic joint states are opt-in."""

from pathlib import Path

import xacro
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def description_nodes(context: LaunchContext) -> list[Node]:
    """Expand installed resources without shell interpolation."""
    share = Path(get_package_share_directory("robot_description"))
    geometry_file = LaunchConfiguration("geometry_file").perform(context)
    robot_xml = xacro.process_file(
        str(share / "urdf" / "robot.urdf.xacro"),
        mappings={"geometry_file": geometry_file},
    ).toxml()
    parameters = {
        "robot_description": ParameterValue(robot_xml, value_type=str),
        "use_sim_time": ParameterValue(LaunchConfiguration("use_sim_time"), value_type=bool),
    }
    return [
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            remappings=[("/tf", "tf"), ("/tf_static", "tf_static")],
            parameters=[parameters],
            output="screen",
        ),
        Node(
            package="joint_state_publisher",
            executable="joint_state_publisher",
            name="preview_joint_state_publisher",
            parameters=[parameters],
            condition=IfCondition(LaunchConfiguration("publish_preview_joint_states")),
            output="screen",
        ),
    ]


def generate_launch_description() -> LaunchDescription:
    share = Path(get_package_share_directory("robot_description"))
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "geometry_file", default_value=str(share / "config" / "geometry.yaml")
            ),
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument(
                "publish_preview_joint_states",
                default_value="false",
                description="Synthetic wheel states for preview only; disable with hardware.",
            ),
            OpaqueFunction(function=description_nodes),
        ]
    )
