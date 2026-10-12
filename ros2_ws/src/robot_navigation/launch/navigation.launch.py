"""Saved-map Nav2 bringup with one ordered lifecycle manager.

Localization and navigation servers intentionally share one lifecycle manager so
Nav2 owns a single deterministic configure/activate sequence. This mirrors the
Nav2 bringup pattern and prevents localization/navigation managers racing each
other during simulation startup.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, RegisterEventHandler, Shutdown
from launch.conditions import IfCondition
from launch.event_handlers import OnShutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from robot_navigation.map_config import validate_saved_map
from robot_navigation.navigation_config import PROFILES, navigation_parameters, sensor_topic


def navigation(context: LaunchContext) -> list:
    profile = LaunchConfiguration("profile").perform(context)
    if profile not in PROFILES:
        raise ValueError(f"Unknown navigation profile '{profile}'")

    map_file = validate_saved_map(LaunchConfiguration("map_file").perform(context))
    geometry = Path(LaunchConfiguration("geometry_file").perform(context)).resolve(strict=True)
    clock = LaunchConfiguration("use_sim_time").perform(context)
    if clock not in ("true", "false"):
        raise ValueError("use_sim_time must be true or false")
    use_sim_time = clock == "true"

    autostart = LaunchConfiguration("autostart").perform(context)
    if autostart not in ("true", "false"):
        raise ValueError("autostart must be true or false")
    autostart_enabled = autostart == "true"

    share = Path(get_package_share_directory("robot_navigation"))
    parameters = navigation_parameters(share / "config", profile, geometry, use_sim_time)
    bt_xml = Path(LaunchConfiguration("bt_xml").perform(context)).resolve(strict=True)
    if not bt_xml.is_file():
        raise ValueError("bt_xml must be a behavior-tree XML file")
    parameters["bt_navigator"]["ros__parameters"]["default_nav_to_pose_bt_xml"] = str(bt_xml)
    temporary = TemporaryDirectory(prefix="robotops-nav-")
    params_file = Path(temporary.name) / "navigation.yaml"
    params_file.write_text(yaml.safe_dump(parameters))

    def cleanup(_event, _context):
        temporary.cleanup()
        return []

    clock_params = {"use_sim_time": use_sim_time}
    tf_remaps = [("/tf", "tf"), ("/tf_static", "tf_static")]

    # Costmaps are child nodes with their own namespaces. Resolve shared sensor
    # and map topics in the parent namespace, rather than /local_costmap/scan.
    namespace = context.launch_configurations.get("ros_namespace", "").strip("/")
    prefix = f"/{namespace}" if namespace else ""
    scan_topic = sensor_topic(
        context.launch_configurations.get("costmap_scan_topic", "scan"), namespace
    )
    shared_topics = [("scan", scan_topic), ("map", f"{prefix}/map")]
    filter_debug = context.launch_configurations.get("sensor_filter_debug", "false")
    if filter_debug not in ("true", "false"):
        raise ValueError("sensor_filter_debug must be true or false")

    nav_servers = {
        "controller_server": "nav2_controller",
        "planner_server": "nav2_planner",
        "behavior_server": "nav2_behaviors",
        "bt_navigator": "nav2_bt_navigator",
    }
    lifecycle_nodes = ["map_server", "amcl", *nav_servers.keys()]

    return [
        RegisterEventHandler(OnShutdown(on_shutdown=cleanup)),
        Node(
            package="nav2_map_server",
            executable="map_server",
            name="map_server",
            parameters=[
                str(share / "config/localization.yaml"),
                clock_params,
                {"yaml_filename": str(map_file)},
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
                clock_params,
                {
                    "set_initial_pose": True,
                    "always_reset_initial_pose": True,
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
            remappings=tf_remaps,
            output="screen",
            on_exit=Shutdown(reason="AMCL exited"),
        ),
        *[
            Node(
                package=package,
                executable=name,
                name=name,
                parameters=[str(params_file)],
                arguments=(
                    ["--ros-args", "--log-level", "tf2_ros_message_filter:=debug"]
                    if filter_debug == "true"
                    else []
                ),
                # Nav2 BT sequences, tracking and recovery actions all feed the
                # autonomy input; only the existing command guard drives the base.
                remappings=[
                    ("cmd_vel", "cmd_vel/autonomy"),
                    *tf_remaps,
                    *shared_topics,
                ],
                output="screen",
                on_exit=Shutdown(reason=f"Navigation process {name} exited"),
            )
            for name, package in nav_servers.items()
        ],
        Node(
            package="nav2_lifecycle_manager",
            executable="lifecycle_manager",
            name="lifecycle_manager_nav2",
            parameters=[
                {
                    "use_sim_time": use_sim_time,
                    "autostart": autostart_enabled,
                    "node_names": lifecycle_nodes,
                    "bond_timeout": 5.0,
                    "attempt_respawn_reconnection": False,
                }
            ],
            output="screen",
            on_exit=Shutdown(reason="Nav2 lifecycle manager exited"),
        ),
        Node(
            package="rviz2",
            executable="rviz2",
            parameters=[clock_params],
            arguments=["-d", str(share / "rviz/navigation.rviz")],
            condition=IfCondition(LaunchConfiguration("rviz")),
            output="screen",
        ),
    ]


def generate_launch_description() -> LaunchDescription:
    description = Path(get_package_share_directory("robot_description"))
    navigator = Path(get_package_share_directory("nav2_bt_navigator"))
    return LaunchDescription(
        [
            DeclareLaunchArgument("map_file", description="Absolute path to a saved map YAML"),
            DeclareLaunchArgument("profile", default_value="navfn_rpp"),
            DeclareLaunchArgument("costmap_scan_topic", default_value="scan"),
            DeclareLaunchArgument(
                "sensor_filter_debug", default_value="false", choices=["true", "false"]
            ),
            DeclareLaunchArgument(
                "bt_xml",
                default_value=str(
                    navigator
                    / "behavior_trees"
                    / "navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml"
                ),
                description="Nav2 behavior tree; retain valid paths across final alignment",
            ),
            DeclareLaunchArgument(
                "geometry_file", default_value=str(description / "config/geometry.yaml")
            ),
            DeclareLaunchArgument(
                "use_sim_time", default_value="false", choices=["true", "false"]
            ),
            DeclareLaunchArgument("rviz", default_value="false", choices=["true", "false"]),
            DeclareLaunchArgument("autostart", default_value="true", choices=["true", "false"]),
            DeclareLaunchArgument("initial_pose_x", default_value="0.0"),
            DeclareLaunchArgument("initial_pose_y", default_value="0.0"),
            DeclareLaunchArgument("initial_pose_yaw", default_value="0.0"),
            OpaqueFunction(function=navigation),
        ]
    )
