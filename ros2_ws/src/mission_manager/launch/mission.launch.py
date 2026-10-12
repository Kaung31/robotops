"""Compose a mission server; the mode selects time policy only at this boundary."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def start(context: LaunchContext) -> list:
    mode = LaunchConfiguration("mode").perform(context)
    clocks = {"mock": False, "sim": True}
    if mode not in clocks:
        raise ValueError("Mission launch supports mock/sim only; replay and real are disabled")
    provenance = {}
    for name in ("environment", "navigation_profile", "map_file"):
        value = LaunchConfiguration(name).perform(context)
        if value:
            provenance[name] = value
    return [
        Node(
            package="mission_manager",
            executable="mission_server",
            name="mission_manager",
            parameters=[
                LaunchConfiguration("config_file"),
                {"runtime_mode": mode, "use_sim_time": clocks[mode], **provenance},
            ],
            output="screen",
            sigterm_timeout="30",
            sigkill_timeout="5",
        )
    ]


def generate_launch_description() -> LaunchDescription:
    share = Path(get_package_share_directory("mission_manager"))
    return LaunchDescription(
        [
            DeclareLaunchArgument("mode", default_value="mock"),
            DeclareLaunchArgument("config_file", default_value=str(share / "config/mission.yaml")),
            DeclareLaunchArgument("environment", default_value=""),
            DeclareLaunchArgument("navigation_profile", default_value=""),
            DeclareLaunchArgument("map_file", default_value=""),
            OpaqueFunction(function=start),
        ]
    )
