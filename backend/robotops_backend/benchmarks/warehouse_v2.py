"""warehouse_v2 analytic map binding for navigation. No robot command paths."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .warehouse import digest, file_bytes

WORLD_ID = "warehouse_v2"
SCENARIO = "ros2_ws/src/robot_simulation/config/warehouse_v2.json"
WORLD = "ros2_ws/src/robot_simulation/worlds/warehouse_v2.sdf"


def validate_warehouse_v2_map(root: Path, yaml_path: Path) -> None:
    """Accept only the generated analytic map, hash-bound to the v2 descriptor and world.

    The aisle validator and clearance measurements assume this exact geometry, so a
    SLAM map saved in the world is refused for navigation.
    """
    relative = yaml_path.relative_to(root).as_posix()
    metadata = json.loads(file_bytes(root, relative.removesuffix(".yaml") + ".robotops.json"))
    if (metadata.get("world_id"), metadata.get("map_id"), metadata.get("map_source")) != (
        WORLD_ID,
        WORLD_ID,
        "ANALYTIC_COLLISION_GEOMETRY_NOT_SLAM",
    ):
        raise ValueError("warehouse_v2 requires its analytic map with explicit association")
    content = yaml.safe_load(file_bytes(root, relative))
    if content.get("image") != yaml_path.with_suffix(".pgm").name:
        raise ValueError("warehouse_v2 map image must match its bound image file")
    for key, path in {
        "geometry_sha256": SCENARIO,
        "world_sha256": WORLD,
        "map_yaml_sha256": relative,
        "map_image_sha256": relative.removesuffix(".yaml") + ".pgm",
    }.items():
        if metadata.get(key) != digest(file_bytes(root, path)):
            raise ValueError(f"warehouse_v2 association hash mismatch: {key}")
