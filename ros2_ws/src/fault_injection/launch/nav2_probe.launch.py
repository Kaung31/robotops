"""Opt-in attended sim probe; no backend/campaign wiring or automatic unlock."""

import json
import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
    Shutdown,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def probe(context):
    config = context.launch_configurations
    if config["mode"] != "sim":
        raise ValueError("Nav2 fault probe requires explicit mode=sim")
    runtime = Path(config["runtime_directory"])
    if (
        not runtime.is_absolute()
        or runtime.resolve(strict=True) != runtime
        or not runtime.is_dir()
    ):
        raise ValueError("runtime_directory must be an existing canonical absolute directory")
    # Separate from R1 local relay restoration. Never auto-unlock on launch exit.
    guard = runtime / "routing.guard"
    if (runtime / "recovery.guard").exists() or (runtime / "recovery.guard").is_symlink():
        raise FileExistsError("Prior relay recovery remains unverified; do not bypass its lock")
    fd = os.open(guard, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            {"kind": "robotops.r2a_route_guard", "downstream_recovery": "unverified"}, stream
        )
        stream.write("\n")
    nav = Path(get_package_share_directory("robot_navigation")) / "launch/navigation.launch.py"
    return [
        Node(
            package="fault_injection",
            executable="scan_fault_relay",
            parameters=[
                {
                    "mode": "sim",
                    "use_sim_time": True,
                    "lifecycle_mode": "owned_v2",
                    "experiment_id": config["experiment_id"],
                    "trial_id": config["trial_id"],
                    "fault_type": "dropout",
                    "delay_seconds": 0.5,
                    "duration_seconds": 1.0,
                    "input_timeout_seconds": 2.0,
                    "input_startup_seconds": 15.0,
                    "evidence_directory": str(runtime / "relay"),
                    "recovery_guard_path": str(runtime / "recovery.guard"),
                }
            ],
            remappings=[("scan_input", "scan"), ("scan_output", "fault_probe/scan")],
            output="screen",
            on_exit=Shutdown(
                reason="Owned probe relay exited; downstream recovery requires review"
            ),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(nav)),
            launch_arguments={
                "map_file": config["map_file"],
                "profile": config["profile"],
                "use_sim_time": "true",
                "rviz": "false",
                "costmap_scan_topic": "fault_probe/scan",
                "sensor_filter_debug": "true",
            }.items(),
        ),
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("mode", description="Explicit sim required"),
            DeclareLaunchArgument(
                "runtime_directory", description="Existing private scope; locks block reuse"
            ),
            DeclareLaunchArgument("experiment_id"),
            DeclareLaunchArgument("trial_id"),
            DeclareLaunchArgument("map_file"),
            DeclareLaunchArgument("profile", default_value="navfn_rpp"),
            OpaqueFunction(function=probe),
        ]
    )
