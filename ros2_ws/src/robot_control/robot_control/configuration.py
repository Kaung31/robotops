"""Build controller parameters from the same geometry used by the URDF."""

import math
from pathlib import Path

import yaml


def controller_parameters(config_file: Path, geometry_file: Path, use_sim_time: bool) -> dict:
    parameters = yaml.safe_load(config_file.read_text())
    geometry = yaml.safe_load(geometry_file.read_text())
    drive = parameters["drive_controller"]["ros__parameters"]
    for key in ("wheel_radius", "wheel_separation"):
        value = geometry[key]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{key} must be a finite positive number")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be a finite positive number")
        drive[key] = float(value)
    for node in parameters.values():
        node["ros__parameters"]["use_sim_time"] = use_sim_time
    return parameters
