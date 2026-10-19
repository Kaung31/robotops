"""Gazebo-only process, entity and transport adapter."""

import os
from pathlib import Path

from ament_index_python.packages import get_package_prefix, get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    OpaqueFunction,
    RegisterEventHandler,
    Shutdown,
)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    share = Path(get_package_share_directory("robot_simulation"))
    plugin_path = os.pathsep.join(
        filter(
            None,
            [
                os.environ.get("GZ_SIM_SYSTEM_PLUGIN_PATH", ""),
                str(Path(get_package_prefix("gz_ros2_control")) / "lib"),
                str(Path(get_package_prefix("robot_simulation")) / "lib"),
            ],
        )
    )
    spawn = Node(
        package="ros_gz_sim",
        executable="create",
        output="screen",
        arguments=[
            "-world",
            LaunchConfiguration("world"),
            "-name",
            "robotops",
            "-topic",
            "robot_description",
            "-z",
            LaunchConfiguration("spawn_z"),
        ],
    )

    def check_spawn(event, _context):
        if event.returncode != 0:
            return [Shutdown(reason=f"Gazebo entity creation failed (exit {event.returncode})")]
        return []

    def server(context):
        command = [
            str(
                Path(get_package_prefix("robot_simulation")) / "lib/robot_simulation/gazebo_runner"
            ),
            str(share / "worlds" / f"{LaunchConfiguration('world').perform(context)}.sdf"),
            LaunchConfiguration("headless_rendering").perform(context),
        ]
        return [
            ExecuteProcess(
                cmd=command,
                additional_env={"GZ_SIM_SYSTEM_PLUGIN_PATH": plugin_path},
                output="screen",
                on_exit=Shutdown(reason="Gazebo server exited"),
            )
        ]

    return LaunchDescription(
        [
            DeclareLaunchArgument("gui", default_value="false"),
            DeclareLaunchArgument("spawn_z"),
            DeclareLaunchArgument(
                "world",
                default_value="control_pad",
                choices=["control_pad", "mapping_lab", "warehouse_v1", "warehouse_v2"],
            ),
            DeclareLaunchArgument(
                "headless_rendering", default_value="true", choices=["true", "false"]
            ),
            OpaqueFunction(function=server),
            ExecuteProcess(
                cmd=["gz", "sim", "-g"],
                condition=IfCondition(LaunchConfiguration("gui")),
                output="screen",
            ),
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name="simulation_bridge",
                parameters=[{"config_file": str(share / "config/bridge.yaml")}],
                output="screen",
                on_exit=Shutdown(reason="Gazebo bridge exited"),
            ),
            RegisterEventHandler(OnProcessExit(target_action=spawn, on_exit=check_spawn)),
            spawn,
        ]
    )
