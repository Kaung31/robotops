#!/usr/bin/env python3
"""Offline original SDF/analytic-map generation. Never starts robotics processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def exact(value: dict, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"Expected exactly {sorted(keys)}")


def numbers(value: object, count: int, positive: bool = False) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != count
        or any(
            type(v) not in (float, int) or not math.isfinite(v) or (positive and v <= 0)
            for v in value
        )
    ):
        raise ValueError("Invalid finite geometry values")
    return value


def load_geometry(path: Path) -> dict:
    d = json.loads(path.read_bytes())
    exact(d, {"schema_version", "world_id", "provenance", "physics", "map", "boxes"})
    if type(d["schema_version"]) is not int or d["schema_version"] != 1:
        raise ValueError("Unknown geometry schema")
    if d["world_id"] != "warehouse_v1" or not isinstance(d["provenance"], str):
        raise ValueError("Unknown world/provenance")
    exact(d["physics"], {"max_step_size_s", "real_time_factor"})
    numbers(list(d["physics"].values()), 2, True)
    exact(d["map"], {"resolution_m", "origin_m", "width", "height"})
    m = d["map"]
    numbers([m["resolution_m"]], 1, True)
    numbers(m["origin_m"], 2)
    if any(type(m[k]) is not int or not 1 <= m[k] <= 2048 for k in ("width", "height")):
        raise ValueError("Map dimensions out of bounds")
    if not isinstance(d["boxes"], list) or len(d["boxes"]) != 7:
        raise ValueError("Warehouse needs four walls and three racks")
    names = set()
    for b in d["boxes"]:
        exact(b, {"name", "centre_m", "size_m"})
        if not isinstance(b["name"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", b["name"]):
            raise ValueError("Invalid model name")
        if b["name"] in names:
            raise ValueError("Duplicate model")
        names.add(b["name"])
        numbers(b["centre_m"], 3)
        numbers(b["size_m"], 3, True)
        if abs(b["centre_m"][2] - b["size_m"][2] / 2) > 1e-9:
            raise ValueError("Obstacles must rest on floor")
        for axis, cells in enumerate((m["width"], m["height"])):
            lo = b["centre_m"][axis] - b["size_m"][axis] / 2
            hi = b["centre_m"][axis] + b["size_m"][axis] / 2
            origin = m["origin_m"][axis]
            if lo < origin - 1e-9 or hi > origin + cells * m["resolution_m"] + 1e-9:
                raise ValueError("Obstacle outside map boundaries")
    if names != {
        "south_wall",
        "north_wall",
        "west_wall",
        "east_wall",
        "rack_1",
        "rack_2",
        "rack_3",
    }:
        raise ValueError("Unexpected warehouse models")
    return d


def world_bytes(d: dict) -> bytes:
    root = ET.Element("sdf", version="1.9")
    world = ET.SubElement(root, "world", name=d["world_id"])
    physics = ET.SubElement(world, "physics", name="fixed_step", type="ignored")
    ET.SubElement(physics, "max_step_size").text = str(d["physics"]["max_step_size_s"])
    ET.SubElement(physics, "real_time_factor").text = str(d["physics"]["real_time_factor"])
    for system in ("Physics", "UserCommands", "SceneBroadcaster", "Sensors", "Imu"):
        filename = re.sub(r"(?<!^)(?=[A-Z])", "-", system).lower()
        plugin = ET.SubElement(
            world,
            "plugin",
            filename=f"gz-sim-{filename}-system",
            name=f"gz::sim::systems::{system}",
        )
        if system == "Sensors":
            ET.SubElement(plugin, "render_engine").text = "ogre2"
    ET.SubElement(world, "gravity").text = "0 0 -9.81"
    light = ET.SubElement(world, "light", name="sun", type="directional")
    ET.SubElement(light, "pose").text = "4 3.5 10 0 0 0"
    ET.SubElement(light, "diffuse").text = "0.9 0.9 0.9 1"
    ET.SubElement(light, "direction").text = "-0.3 0.2 -1"
    # Keep the existing adapter's exact support-floor identity. Names change only;
    # the warehouse plane pose, dimensions and physical properties remain original.
    floor = ET.SubElement(world, "model", name="control_pad_floor")
    ET.SubElement(floor, "static").text = "true"
    ET.SubElement(floor, "pose").text = "4 3.5 0 0 0 0"
    link = ET.SubElement(floor, "link", name="floor")
    for kind in ("collision", "visual"):
        obj = ET.SubElement(link, kind, name=f"floor_{kind}")
        plane = ET.SubElement(ET.SubElement(obj, "geometry"), "plane")
        ET.SubElement(plane, "normal").text = "0 0 1"
        ET.SubElement(plane, "size").text = "16 14"
    for b in d["boxes"]:
        model = ET.SubElement(world, "model", name=b["name"])
        ET.SubElement(model, "static").text = "true"
        ET.SubElement(model, "pose").text = " ".join(map(str, b["centre_m"])) + " 0 0 0"
        link = ET.SubElement(model, "link", name="body")
        for kind in ("collision", "visual"):
            obj = ET.SubElement(link, kind, name=kind)
            box = ET.SubElement(ET.SubElement(obj, "geometry"), "box")
            ET.SubElement(box, "size").text = " ".join(map(str, b["size_m"]))
            if kind == "visual":
                material = ET.SubElement(obj, "material")
                for colour in ("ambient", "diffuse"):
                    ET.SubElement(material, colour).text = "0.4 0.5 0.6 1"
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def validate_support_floor(world_bytes: bytes, robot_bytes: bytes) -> str:
    """Bind the generated plane identity to the unchanged adapter policy."""
    configured = ET.fromstring(robot_bytes).findtext(
        './/plugin[@name="robot_simulation::ContactEvidence"]/floor'
    )
    floors = []
    for model in ET.fromstring(world_bytes).findall(".//world/model"):
        for link in model.findall("link"):
            for collision in link.findall("collision"):
                if collision.find("geometry/plane") is not None:
                    floors.append(
                        "::".join(
                            (model.attrib["name"], link.attrib["name"], collision.attrib["name"])
                        )
                    )
    if not configured or floors != [configured]:
        raise ValueError("Warehouse support-floor identity differs from contact adapter policy")
    return configured


def map_bytes(d: dict) -> tuple[bytes, bytes]:
    m = d["map"]
    w, h, res = m["width"], m["height"], m["resolution_m"]
    ox, oy = m["origin_m"]
    pixels = bytearray([254]) * (w * h)
    # Conservatively occupy any cell whose interior intersects collision geometry.
    for iy in range(h):
        for ix in range(w):
            x0, y0 = ox + ix * res, oy + iy * res
            if any(
                x0 < b["centre_m"][0] + b["size_m"][0] / 2 - 1e-9
                and x0 + res > b["centre_m"][0] - b["size_m"][0] / 2 + 1e-9
                and y0 < b["centre_m"][1] + b["size_m"][1] / 2 - 1e-9
                and y0 + res > b["centre_m"][1] - b["size_m"][1] / 2 + 1e-9
                for b in d["boxes"]
            ):
                pixels[(h - 1 - iy) * w + ix] = 0  # PGM row zero is north.
    pgm = f"P5\n{w} {h}\n255\n".encode() + pixels
    yaml = (
        f"image: warehouse_v1.pgm\nmode: trinary\nresolution: {res}\n"
        f"origin: [{ox}, {oy}, 0.0]\nnegate: 0\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\n"
    ).encode()
    return yaml, pgm


def clearance(d: dict, x: float, y: float) -> float:
    """Distance to an occupied rectangle; negative is inside an obstacle."""
    distances = []
    for b in d["boxes"]:
        dx = abs(x - b["centre_m"][0]) - b["size_m"][0] / 2
        dy = abs(y - b["centre_m"][1]) - b["size_m"][1] / 2
        distances.append(math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0))
    return min(distances)


def generate(descriptor: Path, output: Path) -> dict:
    d = load_geometry(descriptor)
    world = world_bytes(d)
    yaml, pgm = map_bytes(d)
    meta = {
        "schema_version": 1,
        "world_id": "warehouse_v1",
        "map_id": "warehouse_v1",
        "qualification": "OFFLINE_ONLY_RUNTIME_UNQUALIFIED",
        "provenance": d["provenance"],
        "map_source": "ANALYTIC_COLLISION_GEOMETRY_NOT_SLAM",
        "geometry_sha256": sha(descriptor.read_bytes()),
        "world_sha256": sha(world),
        "map_yaml_sha256": sha(yaml),
        "map_image_sha256": sha(pgm),
        "resolution": d["map"]["resolution_m"],
        "width": d["map"]["width"],
        "height": d["map"]["height"],
    }
    output.mkdir(parents=True, exist_ok=False)  # No overwrite, including historical artifacts.
    for name, data in {
        "warehouse_v1.sdf": world,
        "warehouse_v1.yaml": yaml,
        "warehouse_v1.pgm": pgm,
        "warehouse_v1.robotops.json": canonical(meta),
    }.items():
        (output / name).write_bytes(data)
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.descriptor, args.output), indent=2))


if __name__ == "__main__":
    main()
