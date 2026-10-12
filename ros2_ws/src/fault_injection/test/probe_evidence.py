"""Private probe evidence helpers; no ROS, commands, public schema or guard reset."""

from __future__ import annotations

import json
import math
import os
import threading
import time
from pathlib import Path

OUTPUT_MONITOR = "r2a_probe_output"
SCAN_STATUS = "robotops/freshness/scan"
CLOCK_STATUS = "robotops/clock"


def diagnostic_level(value: object) -> int:
    """ROS byte fields are bytes on Jazzy; permit plain integer bindings too."""
    if type(value) is bytes and len(value) == 1:
        level = value[0]
    elif type(value) is int:
        level = value
    else:
        raise ValueError("diagnostic level must be one byte or a plain integer")
    if level not in (0, 1, 2, 3):
        raise ValueError("diagnostic level must be OK/WARN/ERROR/STALE (0..3)")
    return level


class EvidenceJournal:
    """Exclusive JSONL, flushed/fsynced per record, including before assertions."""

    def __init__(self, path: Path):
        self.stream = path.open("x", encoding="utf-8")
        self.lock = threading.Lock()
        self.sequence = 0

    def record(self, kind: str, **fields) -> None:
        with self.lock:
            row = {
                "sequence": self.sequence + 1,
                "wall_monotonic_ns": time.monotonic_ns(),
                "kind": kind,
                **fields,
            }
            encoded = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            self.stream.write(encoded + "\n")
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.sequence += 1

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, _tb):
        try:
            if exc_type:
                self.record(
                    "harness_exception", exception_type=exc_type.__name__, message=str(exc)
                )
        finally:
            self.close()

    def close(self) -> None:
        self.stream.close()


def assess_diagnostic_window(
    rows: list[dict],
    start_ns: int,
    stop_ns: int,
    recovery_ns: int,
    end_ns: int,
    *,
    monitor: str = OUTPUT_MONITOR,
    warn_ns: int = 500_000_000,
) -> dict:
    """Require fresh pre-fault, clock-valid fault-age degradation and fresh recovery."""
    assert 0 < start_ns < stop_ns <= recovery_ns < end_ns
    selected = []
    for row in rows:

        def status(name, row=row):
            matches = [
                s for s in row["status"] if s["name"] == name and s["hardware_id"] == monitor
            ]
            assert len(matches) <= 1, "Duplicate status identity"
            return matches[0] if matches else None

        scan, clock = status(SCAN_STATUS), status(CLOCK_STATUS)
        if scan is not None and clock is not None:
            selected.append((row["stamp_ns"], scan, clock))

    def healthy(item):
        _, scan, clock = item
        return (
            diagnostic_level(clock["level"]) == 0
            and diagnostic_level(scan["level"]) == 0
            and scan["message"] == "fresh"
            and int(scan["values"].get("advancing_samples", "0")) >= 2
        )

    before = [i for i in selected if start_ns - 1_000_000_000 <= i[0] < start_ns]
    during = [i for i in selected if start_ns + warn_ns <= i[0] <= stop_ns]
    after = [i for i in selected if recovery_ns + 100_000_000 <= i[0] <= end_ns]
    assert before and healthy(before[-1]), "Output monitor was not healthy before fault"
    degraded = []
    for item in during:
        t, scan, clock = item
        if diagnostic_level(clock["level"]) != 0:
            continue
        if diagnostic_level(scan["level"]) in (1, 2, 3) and scan["message"] in (
            "age_warning",
            "receipt_timeout",
            "stamp_timeout",
        ):
            ages = [
                float(scan["values"][key]) for key in ("receipt_age_seconds", "stamp_age_seconds")
            ]
            assert all(math.isfinite(age) for age in ages)
            age = max(ages)
            threshold = float(scan["values"]["warn_seconds"])
            assert math.isfinite(age) and math.isfinite(threshold) and threshold == warn_ns / 1e9
            if age > threshold:
                degraded.append(t)
    assert degraded, "No genuine clock-valid output degradation inside fault window"
    assert len(after) >= 2 and all(healthy(i) for i in after[-2:]), (
        "No sustained fresh output recovery"
    )
    return {
        "monitor_hardware_id": monitor,
        "pre_fault_ns": before[-1][0],
        "degraded_ns": degraded,
        "recovered_ns": [i[0] for i in after[-2:]],
    }
