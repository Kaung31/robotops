"""Warehouse v2 (narrow aisle) offline contracts. No launch, ROS node or robot command."""

import ast
import copy
import hashlib
import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path

import pytest
from robotops_backend.campaigns.models import CampaignDefinition

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts")]
import nav2_costmap_model as model  # noqa: E402
import warehouse_v2_scenario as v2  # noqa: E402

V1_DESCRIPTOR = ROOT / "ros2_ws/src/robot_simulation/config/warehouse_v1.json"
V1_MATRIX = json.loads((ROOT / "benchmarks/warehouse_v1/matrix.json").read_bytes())
PLAN = json.loads((ROOT / "benchmarks/warehouse_v2/plan.json").read_bytes())
AISLE = (2.4, 3.6, 1.5, 5.5)


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def descriptor():
    return v2.load_descriptor()


@pytest.fixture(scope="module")
def costmaps(descriptor):
    settings = model.composed_footprint_settings()
    v1 = json.loads(V1_DESCRIPTOR.read_bytes())
    return {
        "v1": model.build(v2.occupancy(v1), v1["map"], settings)[0],
        "v2": model.build(v2.occupancy(descriptor), descriptor["map"], settings)[0],
    }


def test_warehouse_v1_sources_still_match_their_frozen_pins():
    scenario = V1_MATRIX["scenario"]
    for key in ("descriptor", "world"):
        pin = scenario[key]
        assert hashlib.sha256((ROOT / pin["path"]).read_bytes()).hexdigest() == pin["sha256"]


def test_v2_keeps_v1_geometry_exactly_and_only_adds_closures(descriptor, tmp_path):
    v1 = json.loads(V1_DESCRIPTOR.read_bytes())
    assert descriptor["boxes"][:7] == v1["boxes"]
    assert [b["name"] for b in descriptor["boxes"][7:]] == list(v2.CLOSURES)
    assert descriptor["map"] == v1["map"] and descriptor["physics"] == v1["physics"]
    tampered = copy.deepcopy(json.loads(v2.DESCRIPTOR.read_bytes()))
    tampered["boxes"][4]["size_m"][0] = 0.7  # Widen aisle_1 by narrowing rack_1.
    path = tmp_path / "warehouse_v2.json"
    path.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="kept exactly"):
        v2.load_descriptor(path)


def test_generator_conventions_reproduce_v1_pinned_outputs():
    """Fed v1 geometry, the v2 generator yields v1's pinned world and analytic map."""
    v1 = json.loads(V1_DESCRIPTOR.read_bytes())
    yaml, pgm = v2.map_bytes(v1)
    pins = {k: V1_MATRIX["scenario"][k]["sha256"] for k in ("world", "map_yaml", "map_image")}
    assert v2.sha(v2.world_bytes(v1)) == pins["world"]
    assert (v2.sha(yaml), v2.sha(pgm)) == (pins["map_yaml"], pins["map_image"])


def test_committed_world_is_the_generated_world_with_the_contact_floor(descriptor):
    world = v2.world_bytes(descriptor)
    assert v2.WORLD.read_bytes() == world
    assert v2.support_floor(world, v2.ROBOT_SIM_URDF.read_bytes()) == (
        "control_pad_floor::floor::floor_collision"
    )


def test_generate_writes_a_new_directory_only(tmp_path):
    meta = v2.generate(v2.DESCRIPTOR, tmp_path / "out")
    assert meta["map_image_sha256"] == PLAN["scenario"]["map_image_sha256"]
    with pytest.raises(FileExistsError):
        v2.generate(v2.DESCRIPTOR, tmp_path / "out")


def test_the_aisle_is_the_only_route_between_south_and_north(descriptor):
    assert v2.free_gaps_across_band(descriptor) == [(2.4, 3.6)]
    assert v2.reachable(descriptor, (0.0, 0.0), (3.0, 7.0))
    # Even a point squeezing diagonally between cells cannot bypass a blocked aisle.
    assert not v2.reachable(descriptor, (0.0, 0.0), (3.0, 7.0), blocked=[AISLE])
    v1 = json.loads(V1_DESCRIPTOR.read_bytes())
    assert v2.reachable(v1, (0.0, 0.0), (3.0, 7.0), blocked=[AISLE])  # v1's bypass


def test_route_poses_are_in_open_space_on_the_intended_sides(descriptor, costmaps):
    mission = PLAN["mission"]
    poses = [mission["start"], *mission["waypoints"]]
    assert [p["y"] > 5.5 for p in poses] == [False, False, True, False, False]
    for p in poses:
        assert v2.clearance(descriptor, p["x"], p["y"]) >= 1.4
        assert costmaps["v2"].at(p["x"], p["y"]) == 0  # Beyond inflation: no cost.


def test_footprint_and_inflation_follow_the_composed_configuration():
    settings = model.composed_footprint_settings()
    assert settings["robot_radius"] == pytest.approx(math.hypot(0.24, 0.185))
    inscribed, circumscribed = model.footprint_radii(
        model.footprint_from_radius(settings["robot_radius"], settings["footprint_padding"])
    )
    assert inscribed == pytest.approx(0.3118, abs=1e-4)
    assert circumscribed == pytest.approx(0.3242, abs=1e-4)
    physical = model.physical_extent()
    assert (physical["width"], physical["length"]) == pytest.approx((0.37, 0.40))
    # Any non-lethal centre lets the whole robot turn in place without touching a face.
    assert physical["circumscribed_radius"] < inscribed
    footprint = PLAN["clearance_footprint_m"]
    assert (footprint["x_min"], footprint["x_max"], footprint["y_max"]) == pytest.approx(
        (physical["x_min"], physical["x_max"], physical["y_half"])
    )


def test_aisle_cross_section_is_constrained_but_traversable(costmaps):
    for name in ("v1", "v2"):
        section = model.cross_section(costmaps[name], 3.5, 2.4, 3.575)  # Free cell centres.
        assert len(section) == 24 and max(c for _, c in section) < model.LETHAL  # 1.2 m.
        assert model.cross_section(costmaps[name], 3.5, 2.375, 3.625)[0][1] == model.LETHAL
        passable = [x for x, cost in section if cost < model.INSCRIBED]
        assert passable[0] == pytest.approx(2.725) and passable[-1] == pytest.approx(3.275)
        costs = [cost for _, cost in section]
        assert min(costs) == 106 and 0 not in costs  # Never free of inflation cost.


def test_cost_models_reproduce_v1_perimeter_choice_and_v2_forces_the_aisle(costmaps):
    """Planner MODELS, not Nav2: they match the recorded v1 routes (x ~ 0.9 m)."""
    for planner in ("navfn", "smac"):
        cost, _, points = costmaps["v1"].plan((3.0, 0.0), (3.0, 7.0), planner)
        lane = [x for x, y in points if abs(y - 3.525) < 0.03]
        assert lane == [pytest.approx(0.975)]  # West of rack_1, just beyond inflation.
        aisle_cost = sum(
            costmaps["v1"].plan(a, b, planner)[0]
            for a, b in (((3.0, 0.0), (3.0, 3.5)), ((3.0, 3.5), (3.0, 7.0)))
        )
        assert aisle_cost > cost
        forced, length, points = costmaps["v2"].plan((3.0, 0.0), (3.0, 7.0), planner)
        assert forced == pytest.approx(aisle_cost)
        assert length == pytest.approx(7.0, abs=0.06)
        assert all(abs(x - 3.0) <= 0.05 for x, y in points if 1.5 <= y <= 5.5)


def test_plan_pins_the_current_checkout_as_a_new_identity():
    assert v2.check_plan(ROOT) == []
    assert PLAN["execution_approved"] is False and PLAN["publication_approved"] is False
    v1_profiles = {p: V1_MATRIX["profiles"][p]["source"]["sha256"] for p in v2.PROFILES}
    assert all(PLAN["profiles"][p]["source"]["sha256"] != v1_profiles[p] for p in v2.PROFILES)
    pinned = {p["path"] for p in PLAN["shared"]}
    assert set(LAUNCH_FILES) | {"backend/robotops_backend/benchmarks/warehouse_v2.py"} <= pinned


LAUNCH_FILES = (
    "ros2_ws/src/robot_bringup/launch/robot.launch.py",
    "ros2_ws/src/robot_simulation/launch/gazebo.launch.py",
)


def test_registration_offers_warehouse_v2_with_the_plan_start_as_spawn():
    from robotops_backend.orchestrator import StackOrchestrator

    worlds = {w.id: w for w in StackOrchestrator.WORLDS}
    assert worlds["warehouse_v2"].difficulty == "medium"
    assert "warehouse_v1" in worlds
    start = PLAN["mission"]["start"]
    assert StackOrchestrator.SIM_SPAWNS["warehouse_v2"] == (start["x"], start["y"], start["yaw"])
    for relative in LAUNCH_FILES:
        tree = ast.parse((ROOT / relative).read_text())
        choices = [
            ast.literal_eval(k.value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            for k in n.keywords
            if k.arg == "choices" and isinstance(k.value, ast.List)
        ]
        assert any({"warehouse_v1", "warehouse_v2"} <= set(c) for c in choices)


def analytic_workspace(root: Path) -> Path:
    for path in (v2.DESCRIPTOR, v2.WORLD):
        target = root / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    v2.generate(v2.DESCRIPTOR, root / "artifacts/maps")
    return root


def test_warehouse_v2_navigates_only_on_its_hash_bound_analytic_map(tmp_path):
    from robotops_backend.orchestrator import StackOrchestrator

    workspace = analytic_workspace(tmp_path)  # conftest points the repo root here.
    o = StackOrchestrator(workspace)
    assert o._resolve_map("warehouse_v2", "warehouse_v2").is_file()
    with pytest.raises(ValueError, match="belongs to world"):
        o._resolve_map("warehouse_v2", "warehouse_v1")
    meta_path = workspace / "artifacts/maps/warehouse_v2.robotops.json"
    original = meta_path.read_bytes()
    # A map saved by SLAM in this world is associated with it, but not analytic.
    meta_path.write_text(json.dumps(dict(json.loads(original), map_source="SLAM_TOOLBOX")))
    with pytest.raises(ValueError, match="analytic map"):
        o._resolve_map("warehouse_v2", "warehouse_v2")
    meta_path.write_bytes(original)
    world = workspace / v2.WORLD.relative_to(ROOT)
    world.write_bytes(world.read_bytes() + b"<!-- edited -->\n")
    with pytest.raises(ValueError, match="hash mismatch: world_sha256"):
        o._resolve_map("warehouse_v2", "warehouse_v2")
    meta_path.unlink()
    with pytest.raises(ValueError, match="explicit"):
        o._resolve_map("warehouse_v2", "warehouse_v2")


def test_requirement_matches_the_descriptor_aisle(descriptor):
    corridor = descriptor["aisle"]["corridor_m"]
    requirement = PLAN["aisle_requirement"]
    assert requirement["corridor"] == {
        "axis": "y",
        "low": corridor["y"][0],
        "high": corridor["y"][1],
        "lateral": corridor["x"],
    }
    assert requirement["required"] == ["low_to_high", "high_to_low"]
    assert requirement["start_zone"] == "low" and requirement["require_ground_truth"]


def test_qualification_campaigns_are_valid_and_match_the_plan():
    mission = PLAN["mission"]
    for slot in PLAN["qualification"]:
        definition = CampaignDefinition.model_validate_json((ROOT / slot["campaign"]).read_bytes())
        assert (definition.world, definition.map_id) == ("warehouse_v2", "warehouse_v2")
        assert definition.profiles == [slot["profile"]] and definition.repetitions == 1
        dumped = definition.model_dump()
        assert dumped["waypoints"] == mission["waypoints"]
        assert dumped["start"] == mission["start"]
        assert dumped["timeouts"] == mission["timeouts"]
    order = PLAN["benchmark_order_proposed"]
    assert sorted(set(order)) == sorted(v2.PROFILES)
    assert order.count("navfn_rpp") == order.count("smac_dwb")


def test_trial_assessment_measures_a_synthetic_traversal(descriptor):
    assess = load_script("assess_warehouse_v2_trial")
    stamps = range(0, 80_050_000_000, 50_000_000)

    def at(t):  # 0.25 m/s: east to (3,0), north to (3,7), back, west home.
        s = t / 1e9 * 0.25
        legs = [((0, 0), (3, 0)), ((3, 0), (3, 7)), ((3, 7), (3, 0)), ((3, 0), (0, 0))]
        for a, b in legs:
            length = math.dist(a, b)
            if s <= length:
                f = s / length
                return (
                    a[0] + f * (b[0] - a[0]),
                    a[1] + f * (b[1] - a[1]),
                    math.atan2(b[1] - a[1], b[0] - a[0]),
                )
            s -= length
        return (0.0, 0.0, math.pi)

    truth = [(t, *at(t)) for t in stamps]
    localized = [(t, x + 0.02, y, yaw) for t, x, y, yaw in truth]
    window = (truth[0][0], truth[-1][0])
    result = assess.measure(
        PLAN, descriptor, window_ns=window, localized=localized, truth=truth, odom=localized
    )
    assert result["aisle_traversal"]["verdict"] == "TRAVERSAL_VERIFIED"
    assert result["aisle_footprint_clearance"]["clearance_m"] == pytest.approx(0.415)
    assert result["aisle_localization_error"]["max_xy_error_m"] == pytest.approx(0.02)
    assert result["ground_truth_path_length_m"] == pytest.approx(20.0, abs=0.01)
    without = assess.measure(
        PLAN, descriptor, window_ns=window, localized=localized, truth=None, odom=localized
    )
    assert without["aisle_traversal"]["verdict"] == "INCONCLUSIVE"
    assert without["footprint_clearance"] is None
    assert "footprint_clearance" in without["not_measurable"]
