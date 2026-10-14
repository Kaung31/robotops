#!/usr/bin/env python3
"""Warehouse v2 (narrow aisle): offline descriptor checks, SDF/analytic map generation.

Never starts robotics processes. warehouse_v1 and its pinned generator
(scripts/warehouse_scenario.py) are left untouched; this generator is separate so the
v2 identity does not depend on v1's frozen bytes. Rasterization uses the same
conservative rule as v1: a cell is occupied if its interior intersects any box.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORLD_ID = "warehouse_v2"
DESCRIPTOR = ROOT / "ros2_ws/src/robot_simulation/config/warehouse_v2.json"
WORLD = ROOT / "ros2_ws/src/robot_simulation/worlds/warehouse_v2.sdf"
ROBOT_SIM_URDF = ROOT / "ros2_ws/src/robot_simulation/urdf/gazebo.urdf.xacro"
V1_BOXES = ("south_wall", "north_wall", "west_wall", "east_wall", "rack_1", "rack_2", "rack_3")
CLOSURES = ("closure_west", "closure_aisle_2", "closure_east")
EPS = 1e-9


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _exact(value: object, keys: set[str], where: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{where}: expected exactly {sorted(keys)}")
    return value


def _numbers(value: object, count: int, where: str, positive: bool = False) -> list[float]:
    if (
        not isinstance(value, list)
        or len(value) != count
        or any(
            type(v) not in (float, int) or not math.isfinite(v) or (positive and v <= 0)
            for v in value
        )
    ):
        raise ValueError(f"{where}: invalid finite values")
    return value


def bounds(box: dict) -> tuple[float, float, float, float]:
    (cx, cy, _), (sx, sy, _) = box["centre_m"], box["size_m"]
    return cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2


def load_descriptor(path: Path = DESCRIPTOR, v1_path: Path | None = None) -> dict:
    """Strictly validate the v2 descriptor, including that v1's geometry is kept exactly."""
    raw = path.read_bytes()
    d = json.loads(raw)
    _exact(
        d,
        {"schema_version", "world_id", "provenance", "derived_from", "physics", "map"}
        | {"boxes", "aisle"},
        "descriptor",
    )
    if type(d["schema_version"]) is not int or d["schema_version"] != 2:
        raise ValueError("Unknown descriptor schema")
    if d["world_id"] != WORLD_ID or not isinstance(d["provenance"], str):
        raise ValueError("Unknown world/provenance")
    origin = _exact(
        d["derived_from"], {"world_id", "descriptor_path", "descriptor_sha256"}, "derived_from"
    )
    v1_path = v1_path or ROOT / origin["descriptor_path"]
    v1_raw = v1_path.read_bytes()
    if origin["world_id"] != "warehouse_v1" or sha(v1_raw) != origin["descriptor_sha256"]:
        raise ValueError("warehouse_v1 descriptor differs from the recorded derivation source")
    v1 = json.loads(v1_raw)
    if d["physics"] != v1["physics"] or d["map"] != v1["map"]:
        raise ValueError("Physics and map frame must match warehouse_v1")
    _numbers(
        list(_exact(d["physics"], {"max_step_size_s", "real_time_factor"}, "physics").values()),
        2,
        "physics",
        True,
    )
    m = _exact(d["map"], {"resolution_m", "origin_m", "width", "height"}, "map")
    _numbers([m["resolution_m"]], 1, "map.resolution_m", True)
    _numbers(m["origin_m"], 2, "map.origin_m")
    if any(type(m[k]) is not int or not 1 <= m[k] <= 2048 for k in ("width", "height")):
        raise ValueError("Map dimensions out of bounds")
    if not isinstance(d["boxes"], list):
        raise ValueError("boxes must be a list")
    names = [b.get("name") if isinstance(b, dict) else None for b in d["boxes"]]
    if names != [*V1_BOXES, *CLOSURES]:
        raise ValueError(f"Expected boxes {[*V1_BOXES, *CLOSURES]} in order")
    if d["boxes"][: len(V1_BOXES)] != v1["boxes"]:
        raise ValueError("warehouse_v1 walls and racks must be kept exactly")
    for b in d["boxes"]:
        _exact(b, {"name", "centre_m", "size_m"}, "box")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", b["name"]):
            raise ValueError("Invalid model name")
        _numbers(b["centre_m"], 3, b["name"])
        _numbers(b["size_m"], 3, b["name"], True)
        if abs(b["centre_m"][2] - b["size_m"][2] / 2) > EPS:
            raise ValueError("Obstacles must rest on floor")
        x_lo, x_hi, y_lo, y_hi = bounds(b)
        ox, oy = m["origin_m"]
        if (
            x_lo < ox - EPS
            or y_lo < oy - EPS
            or x_hi > ox + m["width"] * m["resolution_m"] + EPS
            or y_hi > oy + m["height"] * m["resolution_m"] + EPS
        ):
            raise ValueError(f"{b['name']} is outside the map")
    a = _exact(
        d["aisle"], {"id", "axis", "between", "corridor_m", "low_side", "high_side"}, "aisle"
    )
    if a["id"] != "aisle_1" or a["axis"] != "y" or a["between"] != ["rack_1", "rack_2"]:
        raise ValueError("v2 measures warehouse_v1's aisle_1 along y")
    if (a["low_side"], a["high_side"]) != ("south", "north"):
        raise ValueError("Aisle sides must be south/north")
    c = _exact(a["corridor_m"], {"x", "y"}, "aisle.corridor_m")
    _numbers(c["x"], 2, "corridor x")
    _numbers(c["y"], 2, "corridor y")
    boxes = {b["name"]: b for b in d["boxes"]}
    west, east = bounds(boxes["rack_1"]), bounds(boxes["rack_2"])
    if not (
        abs(c["x"][0] - west[1]) < EPS
        and abs(c["x"][1] - east[0]) < EPS
        and abs(c["y"][0] - west[2]) < EPS
        and abs(c["y"][1] - west[3]) < EPS
        and west[2:] == east[2:]
    ):
        raise ValueError("Aisle corridor must be exactly the free space between its racks")
    return d


def world_bytes(d: dict) -> bytes:
    """Same SDF structure as warehouse_v1, under the v2 world name."""
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
    # The contact adapter excludes exactly this support-floor identity.
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
                # Closures are drawn darker so the blocked routes are visible.
                colour = "0.25 0.28 0.32 1" if b["name"] in CLOSURES else "0.4 0.5 0.6 1"
                for name in ("ambient", "diffuse"):
                    ET.SubElement(material, name).text = colour
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def support_floor(world: bytes, robot_xacro: bytes) -> str:
    """The world's only plane must be the floor the contact adapter excludes."""
    configured = ET.fromstring(robot_xacro).findtext(
        './/plugin[@name="robot_simulation::ContactEvidence"]/floor'
    )
    floors = [
        "::".join((model.attrib["name"], link.attrib["name"], collision.attrib["name"]))
        for model in ET.fromstring(world).findall(".//world/model")
        for link in model.findall("link")
        for collision in link.findall("collision")
        if collision.find("geometry/plane") is not None
    ]
    if not configured or floors != [configured]:
        raise ValueError("Support-floor identity differs from the contact adapter policy")
    return configured


def occupancy(d: dict) -> bytearray:
    """Row-major grid (row 0 = south), 1 where a cell's interior intersects a box."""
    m = d["map"]
    w, h, res = m["width"], m["height"], m["resolution_m"]
    ox, oy = m["origin_m"]
    grid = bytearray(w * h)
    for b in d["boxes"]:
        x_lo, x_hi, y_lo, y_hi = bounds(b)
        ix0, ix1 = max(0, int((x_lo - ox) / res) - 1), min(w, int((x_hi - ox) / res) + 2)
        iy0, iy1 = max(0, int((y_lo - oy) / res) - 1), min(h, int((y_hi - oy) / res) + 2)
        for iy in range(iy0, iy1):
            y0 = oy + iy * res
            if not (y0 < y_hi - EPS and y0 + res > y_lo + EPS):
                continue
            for ix in range(ix0, ix1):
                x0 = ox + ix * res
                if x0 < x_hi - EPS and x0 + res > x_lo + EPS:
                    grid[iy * w + ix] = 1
    return grid


def map_bytes(d: dict) -> tuple[bytes, bytes]:
    m = d["map"]
    w, h, res = m["width"], m["height"], m["resolution_m"]
    ox, oy = m["origin_m"]
    grid = occupancy(d)
    pixels = bytearray(w * h)
    for iy in range(h):
        for ix in range(w):
            # PGM row zero is north; occupied is black, free is white (trinary).
            pixels[(h - 1 - iy) * w + ix] = 0 if grid[iy * w + ix] else 254
    pgm = f"P5\n{w} {h}\n255\n".encode() + pixels
    yaml = (
        f"image: {d['world_id']}.pgm\nmode: trinary\nresolution: {res}\n"
        f"origin: [{ox}, {oy}, 0.0]\nnegate: 0\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\n"
    ).encode()
    return yaml, pgm


def clearance(d: dict, x: float, y: float) -> float:
    """Analytic distance from a point to the nearest box; negative inside one."""
    distances = []
    for b in d["boxes"]:
        dx = abs(x - b["centre_m"][0]) - b["size_m"][0] / 2
        dy = abs(y - b["centre_m"][1]) - b["size_m"][1] / 2
        distances.append(math.hypot(max(dx, 0), max(dy, 0)) + min(max(dx, dy), 0))
    return min(distances)


def free_gaps_across_band(d: dict) -> list[tuple[float, float]]:
    """Free x-intervals inside the walls across the full aisle band (exact, analytic).

    Only boxes spanning the whole band can close it; a gap here is any opening a point
    robot could use to get from the south area to the north area.
    """
    y_lo, y_hi = d["aisle"]["corridor_m"]["y"]
    boxes = {b["name"]: bounds(b) for b in d["boxes"]}
    inner_lo, inner_hi = boxes["west_wall"][1], boxes["east_wall"][0]
    spans = sorted(
        (max(b[0], inner_lo), min(b[1], inner_hi))
        for b in boxes.values()
        if b[2] <= y_lo + EPS and b[3] >= y_hi - EPS and b[1] > inner_lo and b[0] < inner_hi
    )
    gaps, cursor = [], inner_lo
    for lo, hi in spans:
        if lo > cursor + EPS:
            gaps.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < inner_hi - EPS:
        gaps.append((cursor, inner_hi))
    return gaps


def cell_of(d: dict, x: float, y: float) -> tuple[int, int]:
    m = d["map"]
    return (
        math.floor((x - m["origin_m"][0]) / m["resolution_m"]),
        math.floor((y - m["origin_m"][1]) / m["resolution_m"]),
    )


def reachable(d: dict, start: tuple[float, float], goal: tuple[float, float], blocked=()) -> bool:
    """8-connected flood fill over free cells; `blocked` adds axis-aligned rectangles.

    8-connectivity lets a point slip diagonally between cells, so a negative answer
    is conservative: not even a point robot can get through.
    """
    m = d["map"]
    w, h, res = m["width"], m["height"], m["resolution_m"]
    ox, oy = m["origin_m"]
    grid = occupancy(d)
    for x_lo, x_hi, y_lo, y_hi in blocked:
        for iy in range(h):
            cy = oy + (iy + 0.5) * res
            if y_lo - res / 2 <= cy <= y_hi + res / 2:
                for ix in range(w):
                    cx = ox + (ix + 0.5) * res
                    if x_lo - res / 2 <= cx <= x_hi + res / 2:
                        grid[iy * w + ix] = 1
    s, g = cell_of(d, *start), cell_of(d, *goal)
    if grid[s[1] * w + s[0]] or grid[g[1] * w + g[0]]:
        return False
    seen = bytearray(w * h)
    seen[s[1] * w + s[0]] = 1
    queue = deque([s])
    while queue:
        x, y = queue.popleft()
        if (x, y) == g:
            return True
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    k = ny * w + nx
                    if not grid[k] and not seen[k]:
                        seen[k] = 1
                        queue.append((nx, ny))
    return False


PLAN = ROOT / "benchmarks/warehouse_v2/plan.json"
PROFILES = ("navfn_rpp", "smac_dwb")
SHARED = (
    "ros2_ws/src/robot_navigation/config/navigation.yaml",
    "ros2_ws/src/robot_navigation/config/localization.yaml",
    "ros2_ws/src/robot_navigation/robot_navigation/navigation_config.py",
    "ros2_ws/src/robot_navigation/launch/navigation.launch.py",
    "ros2_ws/src/robot_description/config/geometry.yaml",
    "ros2_ws/src/robot_description/urdf/base.xacro",
    "ros2_ws/src/robot_control/config/controllers.yaml",
    "ros2_ws/src/robot_control/config/mux.yaml",
    "ros2_ws/src/robot_control/config/guard.yaml",
    "ros2_ws/src/robot_recorder/config/recording_validation.yaml",
    "ros2_ws/src/mission_manager/config/mission.yaml",
    "ros2_ws/src/robot_simulation/config/bridge.yaml",
    "ros2_ws/src/robot_simulation/urdf/gazebo.urdf.xacro",
    "ros2_ws/src/robot_simulation/src/gazebo_runner.cpp",
    "ros2_ws/src/experiment_runner/experiment_runner/aisle_traversal.py",
    "ros2_ws/src/experiment_runner/experiment_runner/footprint_clearance.py",
    "ros2_ws/src/experiment_runner/experiment_runner/ground_truth.py",
    "scripts/assess_warehouse_v2_trial.py",
)


def composed_parameters_sha256(profile: str, root: Path = ROOT) -> str:
    """Hash of the effective Nav2 parameters the composer produces for a profile."""
    import sys

    sys.path.insert(0, str(root / "ros2_ws/src/robot_navigation"))
    from robot_navigation.navigation_config import navigation_parameters

    params = navigation_parameters(
        root / "ros2_ws/src/robot_navigation/config",
        profile,
        root / "ros2_ws/src/robot_description/config/geometry.yaml",
        use_sim_time=True,
    )
    return sha(json.dumps(params, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def identities(root: Path = ROOT) -> dict:
    """Current scenario/configuration identity. A changed value means a new benchmark id."""
    d = load_descriptor(root / "ros2_ws/src/robot_simulation/config/warehouse_v2.json")
    yaml, pgm = map_bytes(d)

    def pin(relative: str) -> dict:
        return {"path": relative, "sha256": sha((root / relative).read_bytes())}

    return {
        "scenario": {
            "descriptor": pin("ros2_ws/src/robot_simulation/config/warehouse_v2.json"),
            "world": pin("ros2_ws/src/robot_simulation/worlds/warehouse_v2.sdf"),
            "generator": pin("scripts/warehouse_v2_scenario.py"),
            "map_yaml_sha256": sha(yaml),
            "map_image_sha256": sha(pgm),
        },
        "profiles": {
            p: {
                "source": pin(f"ros2_ws/src/robot_navigation/config/profiles/{p}.yaml"),
                "composed_parameters_sha256": composed_parameters_sha256(p, root),
            }
            for p in PROFILES
        },
        "shared": [pin(relative) for relative in SHARED],
    }


def check_plan(root: Path = ROOT, plan_path: Path | None = None) -> list[str]:
    """Differences between the plan's pinned identities and the current checkout."""
    plan = json.loads((plan_path or root / "benchmarks/warehouse_v2/plan.json").read_bytes())
    current = identities(root)
    differences = [
        f"scenario.{key}"
        for key, value in current["scenario"].items()
        if plan["scenario"].get(key) != value
    ]
    for profile, value in current["profiles"].items():
        if plan["profiles"].get(profile) != value:
            differences.append(f"profiles.{profile}")
    if set(plan["profiles"]) != set(current["profiles"]):
        differences.append("profiles (set)")
    pinned = {p["path"]: p["sha256"] for p in plan["shared"]}
    for p in current["shared"]:
        if pinned.get(p["path"]) != p["sha256"]:
            differences.append(f"shared {p['path']}")
    if set(pinned) != {p["path"] for p in current["shared"]}:
        differences.append("shared (set)")
    return differences


def generate(descriptor: Path, output: Path) -> dict:
    d = load_descriptor(descriptor)
    world = world_bytes(d)
    support_floor(world, ROBOT_SIM_URDF.read_bytes())
    yaml, pgm = map_bytes(d)
    meta = {
        "schema_version": 1,
        "world_id": WORLD_ID,
        "map_id": WORLD_ID,
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
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite, including artifacts/maps.
    for name, data in {
        f"{WORLD_ID}.sdf": world,
        f"{WORLD_ID}.yaml": yaml,
        f"{WORLD_ID}.pgm": pgm,
        f"{WORLD_ID}.robotops.json": canonical(meta),
    }.items():
        (output / name).write_bytes(data)
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    gen = commands.add_parser("generate", help="write SDF, map and metadata to a new directory")
    gen.add_argument("--descriptor", type=Path, default=DESCRIPTOR)
    gen.add_argument("--output", type=Path, required=True, help="new directory only")
    commands.add_parser("identities", help="print the current identity block")
    commands.add_parser("check", help="compare the plan's pins with the current checkout")
    args = parser.parse_args()
    if args.command == "generate":
        print(json.dumps(generate(args.descriptor, args.output), indent=2))
    elif args.command == "identities":
        print(json.dumps(identities(), indent=2))
    else:
        differences = check_plan()
        print("\n".join(differences) or "Plan identities match the current checkout")
        raise SystemExit(1 if differences else 0)


if __name__ == "__main__":
    main()
