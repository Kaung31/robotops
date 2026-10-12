"""Select SLAM mapping OR saved-map localization; consume only standard ROS topics."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, Shutdown
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from robot_navigation.map_config import validate_saved_map


def pipeline(context: LaunchContext) -> list:
    workflow = LaunchConfiguration("workflow").perform(context)
    if workflow not in ("mapping", "localization"):
        raise ValueError("workflow must be mapping or localization")
    map_file = LaunchConfiguration("map_file").perform(context)
    if workflow == "localization":
        map_file = str(validate_saved_map(map_file))
    elif map_file:
        raise ValueError("map_file belongs to localization; mapping starts a new SLAM map")
    share = Path(get_package_share_directory("robot_navigation"))
    clock = {"use_sim_time": ParameterValue(LaunchConfiguration("use_sim_time"), value_type=bool)}
    manager_autostart = ParameterValue(LaunchConfiguration("autostart"), value_type=bool)
    if workflow == "mapping":
        nodes = [
            Node(
                package="robot_navigation",
                executable="slam_runner",
                name="slam_toolbox",
                parameters=[str(share / "config/slam.yaml"), clock],
                output="screen",
                on_exit=Shutdown(reason="SLAM exited"),
            )
        ]
        managed = ["slam_toolbox"]
    else:
        nodes = [
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                parameters=[
                    str(share / "config/localization.yaml"),
                    clock,
                    {"yaml_filename": map_file},
                ],
                output="screen",
                on_exit=Shutdown(reason="Map server exited"),
            ),
            Node(
                package="nav2_amcl",
                executable="amcl",
                name="amcl",
                parameters=[
                    str(share / "config/localization.yaml"),
                    clock,
                    {
                        "set_initial_pose": True,
                        "initial_pose.x": ParameterValue(
                            LaunchConfiguration("initial_pose_x"), value_type=float
                        ),
                        "initial_pose.y": ParameterValue(
                            LaunchConfiguration("initial_pose_y"), value_type=float
                        ),
                        "initial_pose.yaw": ParameterValue(
                            LaunchConfiguration("initial_pose_yaw"), value_type=float
                        ),
                    },
                ],
                output="screen",
                on_exit=Shutdown(reason="AMCL exited"),
            ),
        ]
        managed = ["map_server", "amcl"]
    return [
        *nodes,
        Node(
            package="nav2_lifecycle_manager",
            executable="lifecycle_manager",
            name="map_lifecycle_manager",
            parameters=[
                clock,
                {
                    "autostart": manager_autostart,
                    "node_names": managed,
                    # SLAM Jazzy bond destruction can create timers after rcl shutdown.
                    # Process exit supervision remains active for both workflows.
                    "bond_timeout": 0.0 if workflow == "mapping" else 5.0,
                    "attempt_respawn_reconnection": False,
                },
            ],
            output="screen",
            on_exit=Shutdown(reason="Map lifecycle manager exited"),
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            parameters=[clock],
            arguments=["-d", str(share / "rviz/mapping.rviz")],
            condition=IfCondition(LaunchConfiguration("rviz")),
            output="screen",
        ),
    ]


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription(
        [
            DeclareLaunchArgument("workflow", default_value="mapping"),
            DeclareLaunchArgument("map_file", default_value=""),
            DeclareLaunchArgument(
                "use_sim_time", default_value="false", choices=["true", "false"]
            ),
            DeclareLaunchArgument("rviz", default_value="false", choices=["true", "false"]),
            DeclareLaunchArgument("autostart", default_value="true", choices=["true", "false"]),
            DeclareLaunchArgument("initial_pose_x", default_value="0.0"),
            DeclareLaunchArgument("initial_pose_y", default_value="0.0"),
            DeclareLaunchArgument("initial_pose_yaw", default_value="0.0"),
            OpaqueFunction(function=pipeline),
        ]
    )
