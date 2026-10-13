"""W1/W2 offline contracts. No launch, ROS node, network or robot commands."""

import copy
import importlib.util
import json
import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from robotops_backend.benchmarks.warehouse import (
    EvidenceIndex,
    WarehouseMatrix,
    canonical,
    digest,
    parameters,
    validate_evidence_index,
    validate_matrix,
    validate_parameters,
)
from robotops_backend.orchestrator import StackOrchestrator

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "benchmarks/warehouse_v1/matrix.json"
SPEC = importlib.util.spec_from_file_location(
    "warehouse_scenario", ROOT / "scripts/warehouse_scenario.py"
)
scenario = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scenario)
DESCRIPTOR = ROOT / "ros2_ws/src/robot_simulation/config/warehouse_v1.json"


@pytest.fixture
def workspace(tmp_path):
    matrix = WarehouseMatrix.model_validate_json(MATRIX.read_bytes())
    pins = [
        matrix.scenario.descriptor,
        matrix.scenario.world,
        matrix.scenario.map_yaml,
        matrix.scenario.map_image,
        matrix.scenario.map_metadata,
        *matrix.shared,
        *[p.source for p in matrix.profiles.values()],
    ]
    files = [p.path for p in pins] + [s.config_ref for s in matrix.trials]
    files += ["benchmarks/warehouse_v1/matrix.json"]
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / relative
        if not source.is_file() and relative.startswith("artifacts/maps/warehouse_v1"):
            generated = tmp_path / "generated-map-fixture"
            if not generated.exists():
                scenario.generate(
                    ROOT / "ros2_ws/src/robot_simulation/config/warehouse_v1.json", generated
                )
            source = generated / target.name
        shutil.copyfile(source, target)
    # Current-source fixtures are new specifications, not the historical matrix.
    # Rebind only reconstructed YAML byte pins, retaining frozen effective hashes.
    current = matrix.model_dump(mode="json")
    reconstructed = {
        "ros2_ws/src/robot_navigation/config/navigation.yaml",
        "ros2_ws/src/robot_navigation/config/localization.yaml",
        "ros2_ws/src/robot_navigation/config/profiles/navfn_rpp.yaml",
        "ros2_ws/src/robot_navigation/config/profiles/smac_dwb.yaml",
    }
    for pin in [*current["shared"], *[p["source"] for p in current["profiles"].values()]]:
        if pin["path"] in reconstructed:
            pin["sha256"] = digest((tmp_path / pin["path"]).read_bytes())
    write_matrix(tmp_path, current)
    return tmp_path


def write_matrix(root, data):
    path = root / "benchmarks/warehouse_v1/matrix.json"
    path.write_bytes(canonical(data))
    return path


def test_generated_map_world_are_byte_reproducible_and_match_installed(tmp_path):
    for name in ("a", "b"):
        scenario.generate(DESCRIPTOR, tmp_path / name)
    for path in (tmp_path / "a").iterdir():
        assert path.read_bytes() == (tmp_path / "b" / path.name).read_bytes()
        installed = (
            ROOT
            / (
                "ros2_ws/src/robot_simulation/worlds"
                if path.suffix == ".sdf"
                else "artifacts/maps"
            )
            / path.name
        )
        if installed.is_file():
            assert path.read_bytes() == installed.read_bytes()
        else:
            # A source-only checkout recreates analytic map fixtures without private assets.
            matrix = WarehouseMatrix.model_validate_json(MATRIX.read_bytes())
            names = {
                "warehouse_v1.yaml": matrix.scenario.map_yaml,
                "warehouse_v1.pgm": matrix.scenario.map_image,
                "warehouse_v1.robotops.json": matrix.scenario.map_metadata,
            }
            assert digest(path.read_bytes()) == names[path.name].sha256
    with pytest.raises(FileExistsError):
        scenario.generate(DESCRIPTOR, tmp_path / "a")


def test_world_collision_visual_and_original_geometry():
    d = scenario.load_geometry(DESCRIPTOR)
    world = ET.fromstring(scenario.world_bytes(d)).find("world")
    assert world.attrib["name"] == "warehouse_v1"
    assert world.find(".//include") is None and world.find(".//uri") is None
    assert len(world.findall("model")) == 8
    for box in d["boxes"]:
        model = world.find(f"model[@name='{box['name']}']")
        assert model.findtext("static") == "true"
        assert list(map(float, model.findtext("pose").split()[:3])) == box["centre_m"]
        for kind in ("collision", "visual"):
            assert (
                list(map(float, model.findtext(f"link/{kind}/geometry/box/size").split()))
                == box["size_m"]
            )
    assert world.findtext("physics/max_step_size") == "0.001"


def test_raster_orientation_boundaries_and_every_obstacle_cell():
    d = scenario.load_geometry(DESCRIPTOR)
    _, pgm = scenario.map_bytes(d)
    _, dimensions, _, pixels = pgm.split(b"\n", 3)
    w, h = map(int, dimensions.split())
    assert (w, h) == (244, 204) and len(pixels) == w * h
    m = d["map"]
    for iy in range(h):
        for ix in range(w):
            x = m["origin_m"][0] + (ix + 0.5) * 0.05
            y = m["origin_m"][1] + (iy + 0.5) * 0.05
            occupied = any(
                abs(x - b["centre_m"][0]) < b["size_m"][0] / 2
                and abs(y - b["centre_m"][1]) < b["size_m"][1] / 2
                for b in d["boxes"]
            )
            assert (pixels[(h - 1 - iy) * w + ix] == 0) == occupied
    assert set(pixels) == {0, 254}
    assert all(p == 0 for p in pixels[:w]) and all(p == 0 for p in pixels[-w:])


def test_waypoints_nominal_footprint_and_nonlethal_inflation_clearance():
    d = scenario.load_geometry(DESCRIPTOR)
    effective = parameters(ROOT)
    radius = effective["navfn_rpp"]["local_costmap"]["local_costmap"]["ros__parameters"][
        "robot_radius"
    ]
    assert radius == pytest.approx(math.hypot(0.24, 0.185))
    matrix = WarehouseMatrix.model_validate_json(MATRIX.read_bytes())
    points = [(0.0, 0.0)] + [(p.x, p.y) for p in matrix.mission.waypoints]
    minimum = math.inf
    for start, end in zip(points, points[1:], strict=False):
        for n in range(1001):
            x = start[0] + (end[0] - start[0]) * n / 1000
            y = start[1] + (end[1] - start[1]) * n / 1000
            distance = scenario.clearance(d, x, y)
            minimum = min(minimum, distance)
            # Cell circumradius added conservatively for raster discretisation.
            assert distance > radius + 0.05 / math.sqrt(2)
    assert minimum == pytest.approx(0.6)
    assert scenario.clearance(d, 2, 3.5) < 0  # Rack centre is not a legal waypoint.
    inflation = effective["navfn_rpp"]["local_costmap"]["local_costmap"]["ros__parameters"][
        "inflation_layer"
    ]
    assert inflation["inflation_radius"] == 0.6
    # Inflation has soft costs outside inscribed radius; do NOT require zero-cost aisles.
    assert minimum > radius


@pytest.mark.parametrize("mutation", ["nan", "bool", "negative", "duplicate", "bounds", "extra"])
def test_invalid_geometry_rejected(tmp_path, mutation):
    d = json.loads(DESCRIPTOR.read_bytes())
    if mutation == "nan":
        d["boxes"][0]["centre_m"][0] = float("nan")
    if mutation == "bool":
        d["map"]["width"] = True
    if mutation == "negative":
        d["boxes"][0]["size_m"][0] = -1
    if mutation == "duplicate":
        d["boxes"][1]["name"] = d["boxes"][0]["name"]
    if mutation == "bounds":
        d["boxes"][0]["centre_m"][0] = 999
    if mutation == "extra":
        d["download_url"] = "unapproved"
    p = tmp_path / "geometry.json"
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError):
        scenario.load_geometry(p)


def test_strict_matrix_and_expected_campaigns(workspace):
    m = validate_matrix(workspace, workspace / "benchmarks/warehouse_v1/matrix.json")
    assert [s.profile for s in m.trials] == [
        "navfn_rpp",
        "smac_dwb",
        "smac_dwb",
        "navfn_rpp",
        "navfn_rpp",
        "smac_dwb",
    ]
    assert all(s.state == "PLANNED" for s in m.trials)
    for slot in m.trials:
        p = json.loads((workspace / slot.config_ref).read_bytes())
        assert p["profiles"] == [slot.profile] and p["repetitions"] == 1
        assert p["world"] == p["map_id"] == "warehouse_v1"
        assert p["waypoints"] == m.mission.model_dump()["waypoints"]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "order",
        "extra_slot",
        "missing_slot",
        "world",
        "profile",
        "map",
        "unit",
        "waypoint",
        "nan",
        "approval",
        "bool_version",
        "unknown_field",
        "missing_shared",
        "path",
    ],
)
def test_invalid_matrix_rejected(workspace, mutation):
    d = json.loads((workspace / "benchmarks/warehouse_v1/matrix.json").read_bytes())
    if mutation == "duplicate":
        d["trials"][1]["slot"] = "W01"
    if mutation == "order":
        d["trials"] = list(reversed(d["trials"]))
    if mutation == "extra_slot":
        d["trials"].append(copy.deepcopy(d["trials"][0]))
    if mutation == "missing_slot":
        d["trials"].pop()
    if mutation == "world":
        d["scenario"]["id"] = "mapping_lab"
    if mutation == "profile":
        d["trials"][0]["profile"] = "unknown"
    if mutation == "map":
        d["scenario"]["map_yaml"]["path"] = "artifacts/maps/lab.yaml"
    if mutation == "unit":
        d["mission"]["yaw_unit"] = "deg"
    if mutation == "waypoint":
        d["mission"]["waypoints"][0]["x"] = 2.0
    if mutation == "nan":
        d["mission"]["start"]["yaw"] = "NaN"
    if mutation == "approval":
        d["execution_approved"] = True
    if mutation == "bool_version":
        d["schema_version"] = True
    if mutation == "unknown_field":
        d["start_now"] = True
    if mutation == "missing_shared":
        d["shared"].pop()
    if mutation == "path":
        d["trials"][0]["config_ref"] = "../W01.json"
    with pytest.raises(ValueError):
        validate_matrix(workspace, write_matrix(workspace, d))


@pytest.mark.parametrize("mutation", ["missing", "hash", "symlink", "effective"])
def test_file_and_effective_parameter_integrity(workspace, mutation):
    d = json.loads((workspace / "benchmarks/warehouse_v1/matrix.json").read_bytes())
    p = workspace / d["profiles"]["navfn_rpp"]["source"]["path"]
    if mutation == "missing":
        p.unlink()
    if mutation == "hash":
        p.write_bytes(p.read_bytes() + b"\n# changed\n")
    if mutation == "symlink":
        content = p.read_bytes()
        p.unlink()
        target = workspace / "elsewhere.yaml"
        target.write_bytes(content)
        p.symlink_to(target)
    if mutation == "effective":
        d["profiles"]["navfn_rpp"]["effective_parameters_sha256"] = "0" * 64
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_matrix(workspace, write_matrix(workspace, d))


@pytest.mark.parametrize(
    "field,value",
    [("world", "mapping_lab"), ("map_id", "lab"), ("profiles", ["smac_dwb"]), ("repetitions", 3)],
)
def test_rehashed_wrong_campaign_still_rejected(workspace, field, value):
    d = json.loads((workspace / "benchmarks/warehouse_v1/matrix.json").read_bytes())
    s = d["trials"][0]
    p = workspace / s["config_ref"]
    proposal = json.loads(p.read_bytes())
    proposal[field] = value
    p.write_bytes(canonical(proposal))
    s["config_sha256"] = digest(p.read_bytes())
    with pytest.raises(ValueError, match="Campaign does not match"):
        validate_matrix(workspace, write_matrix(workspace, d))


def test_shared_effective_parameters_cannot_drift():
    values = parameters(ROOT)
    validate_parameters(values)
    values["smac_dwb"]["controller_server"]["ros__parameters"]["controller_frequency"] = 999.0
    with pytest.raises(ValueError, match="Shared effective"):
        validate_parameters(values)


def test_warehouse_map_selection_requires_association_and_hashes(workspace):
    o = StackOrchestrator(workspace)
    assert o._resolve_map("warehouse_v1", "warehouse_v1").is_file()
    assert "warehouse_v1" in o.SIM_SPAWNS
    with pytest.raises(ValueError):
        o._resolve_map("warehouse_v1", "mapping_lab")
    meta = workspace / "artifacts/maps/warehouse_v1.robotops.json"
    d = json.loads(meta.read_bytes())
    d["world_sha256"] = "0" * 64
    meta.write_bytes(canonical(d))
    with pytest.raises(ValueError, match="hash mismatch"):
        o._resolve_map("warehouse_v1", "warehouse_v1")
    meta.unlink()
    with pytest.raises(ValueError, match="explicit"):
        o._resolve_map("warehouse_v1", "warehouse_v1")


def test_legacy_unassociated_map_still_allowed(tmp_path):
    maps = tmp_path / "artifacts/maps"
    maps.mkdir(parents=True)
    (maps / "lab.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    (maps / "lab.yaml").write_text(
        "image: lab.pgm\nresolution: 0.05\norigin: [0,0,0]\n"
        "negate: 0\nfree_thresh: 0.196\noccupied_thresh: 0.65\n"
    )
    o = StackOrchestrator(tmp_path)
    assert o._resolve_map("lab", "mapping_lab").is_file()
    with pytest.raises(ValueError, match="explicit"):
        o._resolve_map("lab", "warehouse_v1")


def index_data(matrix_path=MATRIX):
    # No private fixture dependency: construct the exact initial index from public models.
    return {
        "schema_version": 1,
        "matrix_sha256": digest(matrix_path.read_bytes()),
        "qualification": "UNASSESSED_NO_EXPERIMENT_VERDICT",
        "slots": [
            {
                "slot": f"W{i:02d}",
                "state": "PLANNED",
                "reason": None,
                "campaign_id": None,
                "trial_id": None,
                "experiment_id": None,
                "mission_run_id": None,
                "files": [],
                "availability": "UNAVAILABLE",
                "observations": {
                    "original_outcome": "UNAVAILABLE",
                    "final_xy_m": None,
                    "final_yaw_rad": None,
                    "duration_ros_s": None,
                    "odometry_m": None,
                    "recording_coverage": "UNAVAILABLE",
                    "initial_conditions": "UNAVAILABLE",
                    "random_seed": None,
                    "gaps": [],
                },
            }
            for i in range(1, 7)
        ],
    }


def test_planned_not_run_and_incomplete_evidence_remain_explicit(workspace):
    d = index_data(workspace / "benchmarks/warehouse_v1/matrix.json")
    d["slots"][1].update(state="NOT_RUN", reason="Sequence stopped before dispatch")
    d["slots"][0].update(
        state="ATTEMPTED",
        reason="Partial record; independent audit required",
        campaign_id="a" * 32,
        availability="INCOMPLETE",
    )
    path = workspace / "artifacts/index.json"
    path.write_bytes(canonical(d))
    index = validate_evidence_index(
        workspace, path, workspace / "benchmarks/warehouse_v1/matrix.json"
    )
    assert index.slots[0].mission_run_id is None
    assert index.slots[0].observations.final_xy_m is None
    assert index.slots[1].state == "NOT_RUN"


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "invented_id",
        "invented_metric",
        "missing_reason",
        "complete_missing",
        "reused_id",
        "missing_file",
        "wrong_hash",
        "wrong_matrix",
    ],
)
def test_evidence_does_not_fabricate_or_hide_missing_data(workspace, mutation):
    d = index_data(workspace / "benchmarks/warehouse_v1/matrix.json")
    s = d["slots"][0]
    if mutation == "duplicate":
        d["slots"][1]["slot"] = "W01"
    if mutation == "invented_id":
        s["mission_run_id"] = "a" * 32
    if mutation == "invented_metric":
        s["observations"]["final_xy_m"] = 0.0
    if mutation == "missing_reason":
        s["state"] = "NOT_RUN"
    if mutation == "complete_missing":
        s.update(state="ATTEMPTED", reason="Missing", availability="UNASSESSED")
    if mutation == "reused_id":
        for entry in d["slots"][:2]:
            entry.update(
                state="ATTEMPTED",
                reason="Missing",
                availability="INCOMPLETE",
                campaign_id="a" * 32,
            )
    if mutation in ("missing_file", "wrong_hash"):
        s.update(
            state="ATTEMPTED",
            reason="Missing",
            availability="INCOMPLETE",
            files=[{"path": "artifacts/missing.json", "sha256": "0" * 64}],
        )
        if mutation == "wrong_hash":
            (workspace / "artifacts/missing.json").write_bytes(b"original")
    if mutation == "wrong_matrix":
        d["matrix_sha256"] = "0" * 64
    path = workspace / "artifacts/index.json"
    path.write_bytes(canonical(d))
    with pytest.raises((ValueError, FileNotFoundError)):
        validate_evidence_index(workspace, path, workspace / "benchmarks/warehouse_v1/matrix.json")


def test_machine_readable_schemas_match_models():
    directory = ROOT / "benchmarks/warehouse_v1"
    assert (
        json.loads((directory / "matrix.schema.json").read_bytes())
        == WarehouseMatrix.model_json_schema()
    )
    assert (
        json.loads((directory / "evidence.schema.json").read_bytes())
        == EvidenceIndex.model_json_schema()
    )


def test_rehashed_map_world_mismatch_is_rejected(workspace):
    d = json.loads((workspace / "benchmarks/warehouse_v1/matrix.json").read_bytes())
    world = workspace / d["scenario"]["world"]["path"]
    world.write_bytes(world.read_bytes().replace(b"0.8 4.0 1.2", b"1.0 4.0 1.2"))
    metadata = workspace / d["scenario"]["map_metadata"]["path"]
    meta = json.loads(metadata.read_bytes())
    meta["world_sha256"] = digest(world.read_bytes())
    metadata.write_bytes(canonical(meta))
    d["scenario"]["world"]["sha256"] = digest(world.read_bytes())
    d["scenario"]["map_metadata"]["sha256"] = digest(metadata.read_bytes())
    with pytest.raises(ValueError, match="deterministic geometry"):
        validate_matrix(workspace, write_matrix(workspace, d))


def test_no_ros_or_operational_imports_in_offline_tools():
    import ast

    paths = [
        ROOT / "scripts/warehouse_scenario.py",
        ROOT / "scripts/prepare_warehouse_matrix.py",
        ROOT / "backend/robotops_backend/benchmarks/warehouse.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text())
        names = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not any(
            n and n.split(".")[0] in {"rclpy", "launch", "fastapi", "subprocess", "socket"}
            for n in names
        )
    for path in [
        ROOT / "ros2_ws/src/robot_bringup/launch/robot.launch.py",
        ROOT / "ros2_ws/src/robot_simulation/launch/gazebo.launch.py",
    ]:
        tree = ast.parse(path.read_text())
        choices = [
            k.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            for k in n.keywords
            if k.arg == "choices" and isinstance(k.value, ast.List)
        ]
        assert ["control_pad", "mapping_lab", "warehouse_v1"] in [
            ast.literal_eval(v) for v in choices
        ]


def test_private_evidence_hashing_streams_large_files(tmp_path):
    import hashlib

    from robotops_backend.benchmarks.warehouse import FilePin

    path = tmp_path / "artifacts/synthetic-large.mcap"
    path.parent.mkdir()
    with path.open("wb") as stream:
        stream.truncate(17 * 1024 * 1024)
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    FilePin(path="artifacts/synthetic-large.mcap", sha256=hasher.hexdigest()).verify(tmp_path)


def test_prepare_matrix_is_reproducible_new_only_and_private(workspace):
    spec = importlib.util.spec_from_file_location(
        "prepare_matrix", ROOT / "scripts/prepare_warehouse_matrix.py"
    )
    prepare_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepare_module)
    # Reproduce a temporary current-source specification, never rewrite history.
    directory = workspace / "benchmarks/warehouse_v1"
    expected = {p.name: p.read_bytes() for p in (ROOT / "benchmarks/warehouse_v1").rglob("*.json")}
    expected["matrix.json"] = (directory / "matrix.json").read_bytes()
    expected_index = index_data(directory / "matrix.json")
    for path in directory.rglob("*.json"):
        path.unlink()
    (workspace / "docs/plans").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "docs/plans/warehouse-experiment-matrix-v1.json",
        workspace / "docs/plans/warehouse-experiment-matrix-v1.json",
    )
    index = workspace / "artifacts/prepared-index.json"
    prepare_module.prepare(workspace, index)
    for path in directory.rglob("*.json"):
        assert path.read_bytes() == expected[path.name]
    assert json.loads(index.read_bytes()) == expected_index
    with pytest.raises(FileExistsError):
        prepare_module.prepare(workspace, index)
    with pytest.raises(ValueError):
        prepare_module.prepare(workspace, workspace / "public-index.json")


def test_source_only_workspace_regenerates_private_map_fixture(workspace, tmp_path, monkeypatch):
    for path in (workspace / "artifacts/maps").iterdir():
        path.unlink()
    monkeypatch.setitem(globals(), "ROOT", workspace)
    clean = workspace / "source-only-check"
    clean.mkdir()
    regenerated = globals()["workspace"].__wrapped__(clean)
    validate_matrix(regenerated, regenerated / "benchmarks/warehouse_v1/matrix.json")


def test_floor_identity_matches_unchanged_contact_adapter_and_preserves_geometry():
    sim = ROOT / "ros2_ws/src/robot_simulation"
    configured = ET.parse(sim / "urdf/gazebo.urdf.xacro").findtext(
        './/plugin[@name="robot_simulation::ContactEvidence"]/floor'
    )
    assert configured == "control_pad_floor::floor::floor_collision"
    for name in ("warehouse_v1", "mapping_lab", "control_pad"):
        world = ET.parse(sim / f"worlds/{name}.sdf")
        floors = []
        for model in world.findall(".//world/model"):
            for link in model.findall("link"):
                for collision in link.findall("collision"):
                    if collision.find("geometry/plane") is not None:
                        floors.append(
                            "::".join(
                                (
                                    model.attrib["name"],
                                    link.attrib["name"],
                                    collision.attrib["name"],
                                )
                            )
                        )
        assert floors == [configured]
    warehouse = ET.fromstring(scenario.world_bytes(scenario.load_geometry(DESCRIPTOR)))
    floor = warehouse.find('.//model[@name="control_pad_floor"]')
    assert floor.findtext("static") == "true"
    assert floor.findtext("pose") == "4 3.5 0 0 0 0"
    for kind in ("collision", "visual"):
        assert floor.findtext(f"link/{kind}/geometry/plane/size") == "16 14"
        assert floor.findtext(f"link/{kind}/geometry/plane/normal") == "0 0 1"


def test_support_classification_is_exact_not_a_broad_floor_exclusion():
    # Offline oracle of the UNCHANGED C++ adapter predicate. No contact telemetry
    # is invented here; these are synthetic scoped-name classification fixtures.
    sim = ROOT / "ros2_ws/src/robot_simulation"
    plugin = ET.parse(sim / "urdf/gazebo.urdf.xacro").find(
        './/plugin[@name="robot_simulation::ContactEvidence"]'
    )
    supports = {e.text for e in plugin.findall("support_body")}
    floor = plugin.findtext("floor")
    code = (sim / "src/contact_evidence.cpp").read_text()
    assert "if (support_.count(name) && other_name == floor_)" in code

    def support(body, other_scoped):
        other = other_scoped.split("::", 1)[1]  # Existing adapter strips world prefix only.
        return body in supports and other == floor

    for body in supports:
        assert support(body, f"warehouse_v1::{floor}")
        assert not support(body, "warehouse_v1::warehouse_floor::body::collision")
        assert not support(body, "warehouse_v1::rack_1::body::collision")
    chassis = next(e.text for e in plugin.findall("body") if "chassis" in e.text)
    assert not support(chassis, f"warehouse_v1::{floor}")
    assert not support(next(iter(supports)), "warehouse_v1::other_floor::floor::floor_collision")


def test_floor_contract_preflight_rejects_original_mismatch():
    generated = scenario.world_bytes(scenario.load_geometry(DESCRIPTOR))
    robot = (ROOT / "ros2_ws/src/robot_simulation/urdf/gazebo.urdf.xacro").read_bytes()
    assert (
        scenario.validate_support_floor(generated, robot)
        == "control_pad_floor::floor::floor_collision"
    )
    wrong = generated.replace(b'name="control_pad_floor"', b'name="warehouse_floor"')
    with pytest.raises(ValueError, match="support-floor identity"):
        scenario.validate_support_floor(wrong, robot)


def test_frozen_matrix_rejects_reconstructed_byte_identities(workspace):
    # Historical pins are evidence, not aliases for semantically equal new files.
    historical = WarehouseMatrix.model_validate_json(MATRIX.read_bytes())
    pins = [*historical.shared, *[p.source for p in historical.profiles.values()]]
    mismatches = []
    for pin in pins:
        try:
            pin.verify(workspace)
        except ValueError as error:
            assert "Hash mismatch:" in str(error)
            mismatches.append(pin.path)
    assert set(mismatches) == {
        "ros2_ws/src/robot_navigation/config/navigation.yaml",
        "ros2_ws/src/robot_navigation/config/localization.yaml",
        "ros2_ws/src/robot_navigation/config/profiles/navfn_rpp.yaml",
        "ros2_ws/src/robot_navigation/config/profiles/smac_dwb.yaml",
    }
    path = write_matrix(workspace, historical.model_dump(mode="json"))
    assert path.read_bytes() == MATRIX.read_bytes()
    with pytest.raises(ValueError, match="Hash mismatch:.*navigation.yaml"):
        validate_matrix(workspace, path)
    # Despite distinct source bytes, the accepted effective tuning stays pinned.
    for name, value in parameters(ROOT).items():
        assert digest(canonical(value)) == historical.profiles[name].effective_parameters_sha256
