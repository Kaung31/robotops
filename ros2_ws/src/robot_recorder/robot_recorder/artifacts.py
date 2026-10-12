"""Local, versioned run artifacts; no ROS or simulator dependencies."""

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    payload = json.dumps(value, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class RunStore:
    """UUID paths never depend on a mission label or overwrite a prior run."""

    def __init__(self, root: Path, metadata: dict):
        self.run_id = uuid4().hex
        root = root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.directory = root / self.run_id
        self.directory.mkdir(exist_ok=False)
        self._lock = threading.Lock()
        atomic_json(
            self.directory / "metadata.json",
            dict(metadata, schema_version=1, run_id=self.run_id, created_utc=utc_now()),
        )

    def start(self, ros_ns: int) -> None:
        with self._lock:
            path = self.directory / "metadata.json"
            metadata = json.loads(path.read_text())
            metadata.update(started_ros_ns=ros_ns, started_utc=utc_now())
            atomic_json(path, metadata)

    def event(self, state: str, ros_ns: int, **details) -> None:
        payload = json.dumps(
            dict(state=state, utc=utc_now(), ros_ns=ros_ns, **details), allow_nan=False
        )
        with self._lock, (self.directory / "events.jsonl").open("a") as stream:
            stream.write(payload + "\n")
            stream.flush()

    def finish(self, result: dict) -> None:
        atomic_json(
            self.directory / "result.json",
            dict(result, schema_version=1, run_id=self.run_id, ended_utc=utc_now()),
        )


def map_reference(filename: str) -> dict | None:
    """Fingerprint an explicitly supplied map; do not infer live Nav2 state."""
    if not filename:
        return None
    import hashlib

    import yaml

    path = Path(filename).expanduser().resolve(strict=True)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("image"), str):
        raise ValueError("Map reference must name a map YAML with an image")
    image = (path.parent / data["image"]).resolve(strict=True)
    return {
        "yaml": str(path),
        "yaml_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "image": str(image),
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "source": "operator supplied; not inferred from live navigation",
    }
