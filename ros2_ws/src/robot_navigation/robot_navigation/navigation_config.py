"""Compose Nav2 profiles and derive a conservative footprint without ROS imports."""

import math
import re
from pathlib import Path

import yaml

PROFILES = ("navfn_rpp", "smac_dwb")


def sensor_topic(topic: str, namespace: str = "") -> str:
    """Resolve a shared sensor in the parent namespace, not a costmap child."""
    if not re.fullmatch(r"/?[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*", topic):
        raise ValueError("costmap_scan_topic must be a plain ROS topic name")
    return (
        topic
        if topic.startswith("/")
        else "/" + "/".join(part for part in (namespace.strip("/"), topic) if part)
    )


def navigation_parameters(
    config_dir: Path, profile: str, geometry_file: Path, use_sim_time: bool
) -> dict:
    if profile not in PROFILES:
        raise ValueError(f"Unknown navigation profile '{profile}'; choose one of {PROFILES}")
    config = yaml.safe_load((config_dir / "navigation.yaml").read_text())
    plugins = yaml.safe_load((config_dir / "profiles" / f"{profile}.yaml").read_text())
    for server, params in plugins.items():
        config[server]["ros__parameters"].update(params["ros__parameters"])
    geometry = yaml.safe_load(geometry_file.read_text())
    keys = (
        "chassis_length",
        "chassis_width",
        "wheel_radius",
        "wheel_width",
        "wheel_separation",
        "caster_radius",
        "lidar_radius",
        "imu_size",
    )
    for key in keys:
        value = geometry[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 1e6:
            raise ValueError(f"{key} must be finite, positive and below 1e6")
    # Enclose all projected URDF primitives, including the rearward chassis offset.
    half_x = max(
        0.6 * geometry["chassis_length"],
        geometry["wheel_radius"],
        geometry["lidar_radius"],
        abs(-geometry["chassis_length"] / 2 + geometry["caster_radius"])
        + geometry["caster_radius"],
        geometry["chassis_length"] / 4 + geometry["imu_size"] / 2,
    )
    half_y = max(
        geometry["chassis_width"] / 2,
        (geometry["wheel_separation"] + geometry["wheel_width"]) / 2,
        geometry["caster_radius"],
        geometry["lidar_radius"],
        geometry["imu_size"] / 2,
    )
    radius = math.hypot(half_x, half_y)
    for name in ("local_costmap", "global_costmap"):
        config[name][name]["ros__parameters"]["robot_radius"] = radius

    def set_clock(value: dict) -> None:
        for key, child in value.items():
            if key == "ros__parameters":
                child["use_sim_time"] = use_sim_time
            elif isinstance(child, dict):
                set_clock(child)

    set_clock(config)
    return config
