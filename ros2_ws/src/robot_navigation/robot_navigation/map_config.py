"""Validate saved-map inputs before starting lifecycle nodes."""

import math
from pathlib import Path

import yaml


def validate_saved_map(filename: str) -> Path:
    if not filename:
        raise ValueError("map_file is required for localization")
    path = Path(filename).expanduser().resolve(strict=True)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("image"), str):
        raise ValueError("map_file must be a map YAML with an image path")
    image = (path.parent / data["image"]).resolve(strict=True)
    if not image.is_file() or image.stat().st_size == 0:
        raise ValueError("Map image must be a nonempty file")
    resolution = data.get("resolution")
    if type(resolution) not in (float, int) or not math.isfinite(resolution) or resolution <= 0:
        raise ValueError("Map resolution must be finite and positive")
    origin = data.get("origin")
    if (
        not isinstance(origin, list)
        or len(origin) != 3
        or not all(type(v) in (float, int) and math.isfinite(v) for v in origin)
    ):
        raise ValueError("Map origin must contain finite x, y, yaw")
    for key in ("free_thresh", "occupied_thresh"):
        value = data.get(key)
        if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{key} must be between 0 and 1")
    if data["free_thresh"] >= data["occupied_thresh"]:
        raise ValueError("free_thresh must be smaller than occupied_thresh")
    if data.get("mode", "trinary") not in ("trinary", "scale", "raw"):
        raise ValueError("Unsupported occupancy map mode")
    if data.get("negate") not in (0, 1):
        raise ValueError("Map negate must be 0 or 1")
    return path
