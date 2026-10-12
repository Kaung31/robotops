#!/usr/bin/env python3
"""Prepare/check offline warehouse specifications; no campaign dispatch or ROS imports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from robotops_backend.benchmarks.warehouse import (  # noqa: E402
    MAP,
    POLICY,
    SCENARIO,
    SHARED,
    START,
    TIMEOUTS,
    WAYPOINTS,
    WORLD,
    EvidenceIndex,
    Mission,
    WarehouseMatrix,
    campaign,
    canonical,
    digest,
    file_bytes,
    parameters,
    validate_evidence_index,
    validate_matrix,
    validate_parameters,
)


def prepare(root: Path, evidence_output: Path) -> None:
    """New-only writes; never overwrite evidence or prior configuration proposals."""
    evidence_output.resolve().relative_to((root / "artifacts").resolve())
    directory = root / "benchmarks/warehouse_v1"
    matrix_path = directory / "matrix.json"
    generated = [matrix_path, directory / "matrix.schema.json", directory / "evidence.schema.json"]
    generated += [directory / "campaigns" / f"W{i:02d}.json" for i in range(1, 7)]
    if any(p.exists() for p in generated) or evidence_output.exists():
        raise FileExistsError("Refusing to overwrite existing matrix or evidence index")
    mission = Mission.model_validate(
        {
            "frame": "map",
            "position_unit": "m",
            "yaw_unit": "rad",
            "waypoints": WAYPOINTS,
            "start": START,
            "timeouts": TIMEOUTS,
            "validation_policy": POLICY,
        }
    )
    effective = parameters(root)
    validate_parameters(effective)

    def pin(path: str) -> dict:
        return {"path": path, "sha256": digest(file_bytes(root, path))}

    draft = json.loads((root / "docs/plans/warehouse-experiment-matrix-v1.json").read_bytes())
    proposals = {}
    slots = []
    for trial in draft["trials"]:
        slot, profile = trial["slot"], trial["profile"]
        path = f"benchmarks/warehouse_v1/campaigns/{slot}.json"
        proposals[path] = canonical(campaign(slot, profile, mission).model_dump(mode="json"))
        slots.append(
            {
                "slot": slot,
                "profile": profile,
                "profile_trial": trial["profile_trial_number"],
                "pair": trial["pair"],
                "state": "PLANNED",
                "config_ref": path,
                "config_sha256": digest(proposals[path]),
            }
        )
    matrix = WarehouseMatrix.model_validate(
        {
            "schema_version": 1,
            "id": "warehouse-navigation-v1",
            "authority": "OFFLINE_PLAN_NOT_EXECUTION_AUTHORIZATION",
            "comparison": "PLANNER_CONTROLLER_BUNDLES_N3_NO_SUPERIORITY_CLAIM",
            "execution_approved": False,
            "publication_approved": False,
            "scenario": {
                "id": "warehouse_v1",
                "qualification": "OFFLINE_ONLY_RUNTIME_UNQUALIFIED",
                "descriptor": pin(SCENARIO),
                "world": pin(WORLD),
                "map_yaml": pin(MAP + ".yaml"),
                "map_image": pin(MAP + ".pgm"),
                "map_metadata": pin(MAP + ".robotops.json"),
                "seed": None,
                "initial_conditions": "REQUESTED_ONLY_NOT_OBSERVED",
                "stochastic_determinism": "UNQUALIFIED_SEEDS_UNKNOWN",
            },
            "mission": mission.model_dump(),
            "profiles": {
                name: {
                    "source": pin(f"ros2_ws/src/robot_navigation/config/profiles/{name}.yaml"),
                    "effective_parameters_sha256": digest(canonical(value)),
                    "provenance": "UNKNOWN_PUBLIC_INCLUSION_HELD",
                }
                for name, value in effective.items()
            },
            "shared": [pin(p) for p in SHARED],
            "trials": slots,
            "failure_policy": "STOP_NO_AUTOMATIC_RETRY_OR_REPLACEMENT",
            "reset_policy": "FRESH_OWNED_STACK_PER_SLOT",
        }
    )
    matrix_bytes = canonical(matrix.model_dump(mode="json"))
    index = EvidenceIndex.model_validate(
        {
            "schema_version": 1,
            "matrix_sha256": digest(matrix_bytes),
            "qualification": "UNASSESSED_NO_EXPERIMENT_VERDICT",
            "slots": [
                {
                    "slot": s.slot,
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
                for s in matrix.trials
            ],
        }
    )
    # All modelling/reads complete before any write; a failed preparation is not executable.
    outputs = {
        **proposals,
        "benchmarks/warehouse_v1/matrix.json": matrix_bytes,
        "benchmarks/warehouse_v1/matrix.schema.json": canonical(
            WarehouseMatrix.model_json_schema()
        ),
        "benchmarks/warehouse_v1/evidence.schema.json": canonical(
            EvidenceIndex.model_json_schema()
        ),
    }
    for relative, data in outputs.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    evidence_output.parent.mkdir(parents=True, exist_ok=True)
    with evidence_output.open("xb") as stream:
        stream.write(canonical(index.model_dump(mode="json")))
    validate_evidence_index(root, evidence_output, matrix_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "check"])
    parser.add_argument("--evidence-index", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        # Private index may only be created beneath this working repository's artifacts.
        args.evidence_index.resolve().relative_to((ROOT / "artifacts").resolve())
        prepare(ROOT, args.evidence_index)
    else:
        validate_matrix(ROOT, ROOT / "benchmarks/warehouse_v1/matrix.json")
        validate_evidence_index(
            ROOT, args.evidence_index, ROOT / "benchmarks/warehouse_v1/matrix.json"
        )
    print("Validated offline six-slot plan; no execution, observations or experiment verdict.")


if __name__ == "__main__":
    main()
