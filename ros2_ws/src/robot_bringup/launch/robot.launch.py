"""Compose stable robot interfaces with an explicitly selected backend."""

from pathlib import Path
from tempfile import TemporaryDirectory

import xacro
import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
    RegisterEventHandler,
    Shutdown,
)
from launch.event_handlers import OnProcessExit, OnShutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from robot_control.configuration import controller_parameters


def start_robot(context: LaunchContext) -> list:
    mode = LaunchConfiguration("mode").perform(context)
    # Mode selection is confined to composition. Unsupported modes start nothing.
    adapters = {
        "mock": ("robot_bringup", "mock", False),
        "sim": ("robot_simulation", "gazebo", True),
    }
    if mode not in adapters:
        raise ValueError(f"Unsupported mode '{mode}'; only mock and sim are implemented")
    package, adapter, sim_time = adapters[mode]
    share = Path(get_package_share_directory(package))
    control = Path(get_package_share_directory("robot_control"))
    geometry = Path(LaunchConfiguration("geometry_file").perform(context)).resolve(strict=True)
    config = controller_parameters(control / "config/controllers.yaml", geometry, sim_time)
    temporary = TemporaryDirectory(prefix="robotops-control-")
    controllers_file = Path(temporary.name) / "controllers.yaml"
    controllers_file.write_text(yaml.safe_dump(config))
    try:
        description = xacro.process_file(
            str(share / "urdf" / f"{adapter}.urdf.xacro"),
            mappings={
                "geometry_file": str(geometry),
                "controllers_file": str(controllers_file),
                "sensors": LaunchConfiguration("sensors").perform(context),
            },
        ).toxml()
    except Exception:
        temporary.cleanup()
        raise

    def cleanup(_event, _context):
        temporary.cleanup()
        return []

    def check_spawner(event, _context):
        if event.returncode != 0:
            return [Shutdown(reason=f"Controller activation failed (exit {event.returncode})")]
        return []

    spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=[
            "joint_state_broadcaster",
            "drive_controller",
            "--activate-as-group",
            "--controller-manager-timeout",
            "45",
            "--switch-timeout",
            "30",
            "--param-file",
            str(controllers_file),
            "--controller-ros-args",
            "-r drive_controller/odom:=odom",
        ],
        output="screen",
    )
    diagnostics = []
    if LaunchConfiguration("diagnostics").perform(context) == "true":
        streams = ["odom"]
        if mode == "sim" and LaunchConfiguration("sensors").perform(context) == "true":
            streams.extend(["scan", "imu"])
        diagnostics.append(
            Node(
                package="robot_diagnostics",
                executable="freshness_monitor",
                parameters=[{"use_sim_time": sim_time, "enabled_streams": streams}],
                output="screen",
                # Observability failure must not shut down the robot stack.
            )
        )
    return [
        RegisterEventHandler(OnShutdown(on_shutdown=cleanup)),
        RegisterEventHandler(OnProcessExit(target_action=spawner, on_exit=check_spawner)),
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            parameters=[
                {
                    "robot_description": ParameterValue(description, value_type=str),
                    "use_sim_time": sim_time,
                }
            ],
            output="screen",
            on_exit=Shutdown(reason="Robot state publisher exited"),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(share / "launch" / f"{adapter}.launch.py")),
            launch_arguments={
                "controllers_file": str(controllers_file),
                "gui": LaunchConfiguration("gui"),
                "headless_rendering": LaunchConfiguration("headless_rendering"),
                "world": LaunchConfiguration("world"),
                "spawn_z": str(
                    config["drive_controller"]["ros__parameters"]["wheel_radius"] + 0.02
                ),
            }.items(),
        ),
        Node(
            package="twist_mux",
            executable="twist_mux",
            name="twist_mux",
            parameters=[str(control / "config/mux.yaml"), {"use_sim_time": sim_time}],
            remappings=[("cmd_vel_out", "cmd_vel/selected")],
            output="screen",
            on_exit=Shutdown(reason="Command mux exited"),
        ),
        Node(
            package="robot_control",
            executable="command_guard",
            name="command_guard",
            parameters=[str(control / "config/guard.yaml"), {"use_sim_time": sim_time}],
            remappings=[("input", "cmd_vel/selected"), ("output", "drive_controller/cmd_vel")],
            output="screen",
            on_exit=Shutdown(reason="Command guard exited"),
        ),
        spawner,
        *diagnostics,
    ]


def generate_launch_description() -> LaunchDescription:
    description = Path(get_package_share_directory("robot_description"))
    return LaunchDescription(
        [
            DeclareLaunchArgument("mode", default_value="mock"),
            DeclareLaunchArgument(
                "world",
                default_value="control_pad",
                choices=["control_pad", "mapping_lab", "warehouse_v1"],
            ),
            DeclareLaunchArgument("sensors", default_value="true", choices=["true", "false"]),
            DeclareLaunchArgument(
                "diagnostics",
                default_value=EnvironmentVariable("ROBOTOPS_DIAGNOSTICS", default_value="false"),
                choices=["true", "false"],
            ),
            DeclareLaunchArgument(
                "headless_rendering", default_value="true", choices=["true", "false"]
            ),
            DeclareLaunchArgument("gui", default_value="false", choices=["true", "false"]),
            DeclareLaunchArgument(
                "geometry_file", default_value=str(description / "config/geometry.yaml")
            ),
            OpaqueFunction(function=start_robot),
        ]
    )
