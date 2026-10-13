"""Recreate exact pinned analytic map inputs in a clean CI checkout, never run evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from warehouse_scenario import generate  # noqa: E402


def prepare(root: Path) -> None:
    artifacts = root / "artifacts"
    if artifacts.exists():
        raise FileExistsError(
            "CI fixture preparation requires a checkout with no artifacts directory"
        )
    matrix = json.loads((root / "benchmarks/warehouse_v1/matrix.json").read_bytes())
    descriptor = root / matrix["scenario"]["descriptor"]["path"]
    staging = root / ".ci-results"
    staging.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as temporary:
        generated = Path(temporary) / "map"
        generate(descriptor, generated)
        inputs: list[tuple[Path, bytes]] = []
        for key in ("map_yaml", "map_image", "map_metadata"):
            pin = matrix["scenario"][key]
            destination = root / pin["path"]
            if not destination.resolve().is_relative_to(artifacts.resolve() / "maps"):
                raise ValueError("CI map input must be beneath artifacts/maps")
            content = (generated / destination.name).read_bytes()
            if hashlib.sha256(content).hexdigest() != pin["sha256"]:
                raise ValueError(f"Generated CI map does not match frozen identity: {key}")
            inputs.append((destination, content))
        # All three identities pass before any fixture input is written; new-only writes.
        for destination, content in inputs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(content)
    print("Prepared three exact pinned map fixtures; no run/claim/result/permission created")


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parents[2])
