"""ros2_control mock hardware adapter; common composition lives in robot.launch.py."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("controllers_file"),
            Node(
                package="controller_manager",
                executable="ros2_control_node",
                parameters=[LaunchConfiguration("controllers_file")],
                output="screen",
                on_exit=Shutdown(reason="Mock controller manager exited"),
            ),
        ]
    )
