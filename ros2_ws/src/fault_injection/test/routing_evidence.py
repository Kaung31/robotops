"""Pure, private R2a evidence attribution. Never changes a trial's verdict or guard."""

from __future__ import annotations

import hashlib
import json
import math

from probe_evidence import (
    CLOCK_STATUS,
    OUTPUT_MONITOR,
    SCAN_STATUS,
    assess_diagnostic_window,
    diagnostic_level,
)

SERVERS = ("controller_server", "planner_server")
MARGIN_NS = 200_000_000
FRESH_NS = 500_000_000
MIN_SAMPLES = 5
STATES = (
    "requested",
    "armed",
    "nav_accepted",
    "execution_started",
    "activation_acknowledged",
    "effect_observed",
    "stopped_ended",
    "recovery_requested",
    "recovery_verified",
)


class EvidenceProblem(Exception):
    def __init__(self, message: str, status: str = "INCONCLUSIVE"):
        super().__init__(message)
        self.status = status


def require(condition: bool, reason: str, status: str = "INCONCLUSIVE") -> None:
    if not condition:
        raise EvidenceProblem(reason, status)


def sealed_window(plan_bytes: bytes, events_bytes: bytes, seal_bytes: bytes, owner: dict) -> dict:
    """Hashes attest bytes/closure, not external authenticity; verify expected owner too."""
    require(bool(plan_bytes and events_bytes and seal_bytes), "Missing sealed relay evidence")
    plan, seal = json.loads(plan_bytes), json.loads(seal_bytes)
    events = [json.loads(line) for line in events_bytes.splitlines()]
    require(seal["termination"] == "closed", "Relay evidence not closed")
    require(seal["schema_version"] == plan["schema_version"] == 2, "Wrong evidence schema", "FAIL")
    for data, key in ((plan_bytes, "plan_sha256"), (events_bytes, "events_sha256")):
        require(hashlib.sha256(data).hexdigest() == seal[key], "Seal digest mismatch", "FAIL")
    require(seal["event_count"] == len(events), "Incomplete sealed event count")
    require(
        [e["sequence"] for e in events] == list(range(1, len(events) + 1)),
        "Missing/duplicate event sequence",
    )
    require([e["state"] for e in events] == list(STATES), "Incomplete/conflicting lifecycle")
    require(
        plan["mode"] == "sim"
        and plan["fault_type"] == "dropout"
        and plan["target"] == "scan"
        and plan["input_topic"] == "/scan"
        and plan["output_topic"] == "/fault_probe/scan",
        "Unexpected sensor plan",
        "FAIL",
    )
    for key in ("experiment_id", "trial_id", "session_id"):
        require(bool(owner[key]) and plan[key] == owner[key], "Wrong plan owner: " + key, "FAIL")
    for e in events:
        for key in ("experiment_id", "trial_id", "session_id"):
            require(e[key] == owner[key], "Wrong event owner: " + key, "FAIL")
        require(e["plan_sha256"] == seal["plan_sha256"], "Wrong event plan", "FAIL")
        if e["state"] != "requested":
            require(
                e["mission_id"] == owner["mission_id"] and bool(owner["mission_id"]),
                "Wrong mission identity",
                "FAIL",
            )
        if e["state"] not in ("requested", "armed"):
            require(
                e["nav_goal_id"] == owner["nav_goal_id"] and bool(owner["nav_goal_id"]),
                "Wrong Nav2 goal identity",
                "FAIL",
            )
    times = [e["ros_time_ns"] for e in events]
    require(all(type(t) is int and t >= 0 for t in times), "Invalid event time", "FAIL")
    require(
        times == sorted(times) and len({e["clock_epoch"] for e in events}) == 1,
        "Clock discontinuity in lifecycle",
        "FAIL",
    )
    indexed = {e["state"]: e for e in events}
    start, stop, restored = (
        indexed[k]["ros_time_ns"]
        for k in ("activation_acknowledged", "stopped_ended", "recovery_verified")
    )
    effect = indexed["effect_observed"]
    require(
        0 < start <= effect["ros_time_ns"] < stop <= restored,
        "Invalid fault/restoration interval",
        "FAIL",
    )
    require(
        type(plan["duration_ns"]) is int
        and plan["duration_ns"] > 0
        and type(plan["delay_ns"]) is int
        and plan["delay_ns"] >= 0,
        "Invalid planned timing",
        "FAIL",
    )
    delay = start - indexed["execution_started"]["ros_time_ns"] - plan["delay_ns"]
    require(
        0 <= delay <= MARGIN_NS and abs(stop - start - plan["duration_ns"]) <= MARGIN_NS,
        "Fault interval disagrees with authorized plan",
        "FAIL",
    )
    count = indexed["stopped_ended"]["affected_samples"]
    require(type(count) is int and count >= MIN_SAMPLES, "Insufficient confirmed effect")
    require(
        effect["applied_confirmed"] is True
        and type(effect["affected_samples"]) is int
        and effect["affected_samples"] == 1,
        "Actual effect not confirmed",
    )
    require(
        indexed["recovery_verified"]["recovery_verified"] is True
        and indexed["recovery_verified"]["affected_samples"] == count,
        "Local restoration not confirmed",
    )
    return {
        "start_ns": start,
        "stop_ns": stop,
        "restored_ns": restored,
        "effect_ns": effect["ros_time_ns"],
        "affected_samples": count,
    }


def observations(rows: list[dict], label: str, issues: list[dict]) -> dict[int, dict]:
    result = {}
    previous = -1
    for row in rows:
        t, receipt = row["stamp_ns"], row["receipt_ros_ns"]
        require(
            type(t) is int and type(receipt) is int and t > 0 and receipt >= t,
            "Invalid sensor timestamp: " + label,
        )
        require(row["frame"] == "lidar_link", "Wrong sensor frame", "FAIL")
        digest = row["cdr_sha256"]
        require(
            isinstance(digest, str)
            and len(digest) == 64
            and all(c in "0123456789abcdef" for c in digest),
            "Invalid sensor digest",
        )
        if t in result:
            require(result[t]["cdr_sha256"] == digest, "Conflicting duplicate sample", "FAIL")
            issues.append({"kind": "duplicate", "stream": label, "stamp_ns": t})
            continue
        if t < previous:
            issues.append({"kind": "out_of_order", "stream": label, "stamp_ns": t})
        if receipt - t > FRESH_NS:
            issues.append({"kind": "delayed", "stream": label, "stamp_ns": t})
        previous = t
        result[t] = row
    require(bool(result), "Missing sensor observations: " + label)
    return result


def diagnostic_pair(row: dict):
    selected = {
        name: [
            s for s in row["status"] if s["name"] == name and s["hardware_id"] == OUTPUT_MONITOR
        ]
        for name in (CLOCK_STATUS, SCAN_STATUS)
    }
    require(all(len(v) <= 1 for v in selected.values()), "Conflicting monitor identities", "FAIL")
    if not all(selected.values()):
        return None
    return selected[CLOCK_STATUS][0], selected[SCAN_STATUS][0]


def ordered_diagnostics(rows: list[dict], end_ns: int, issues: list[dict]) -> list[dict]:
    """DDS callback order is not measurement time; conflicting duplicates stay unsafe."""
    indexed = {}
    previous = -1
    for row in rows:
        t = row["stamp_ns"]
        require(type(t) is int and 0 < t <= end_ns, "Invalid diagnostic timestamp")
        pair = diagnostic_pair(row)
        require(pair is not None, "Incomplete/wrong diagnostic identity")
        for status in pair:
            diagnostic_level(status["level"])
        if t < previous:
            issues.append({"kind": "diagnostic_out_of_order", "stamp_ns": t})
        if t in indexed:
            require(
                indexed[t]["status"] == row["status"], "Conflicting diagnostic duplicate", "FAIL"
            )
            issues.append({"kind": "diagnostic_duplicate", "stamp_ns": t})
        else:
            indexed[t] = row
        previous = t
    require(bool(indexed), "Missing diagnostic evidence")
    return [indexed[t] for t in sorted(indexed)]


def unexpected_starvation(t: int, diagnostics: list[dict], restored: int) -> bool:
    """Positive clock-valid monitor starvation corroborates delivery loss, not its component."""
    for row in diagnostics:
        pair = diagnostic_pair(row)
        if pair is None or row["stamp_ns"] <= max(t + FRESH_NS, restored + FRESH_NS):
            continue
        clock, scan = pair
        values = scan["values"]
        if (
            diagnostic_level(clock["level"]) == 0
            and diagnostic_level(scan["level"]) in (1, 2, 3)
            and scan["message"] in ("age_warning", "receipt_timeout", "stamp_timeout")
        ):
            receipt_age = float(values["receipt_age_seconds"])
            stamp_age = float(values["stamp_age_seconds"])
            if (
                all(math.isfinite(v) for v in (receipt_age, stamp_age))
                and receipt_age > 0.5
                and stamp_age > 0.5
                and int(values["stamp_ns"]) < t
                and row["stamp_ns"] - int(receipt_age * 1e9) < t
            ):
                return True
    return False


def assess_routing(
    *,
    streams: dict,
    consumers: dict,
    diagnostics: list[dict],
    topology: dict,
    clocks: list[int],
    owner: dict,
    plan_bytes: bytes,
    events_bytes: bytes,
    seal_bytes: bytes,
    end_ns: int,
) -> dict:
    """SUPPORTED means scoped evidence supports recovery, never historical trial PASS."""
    report = {
        "assessment_status": "INCONCLUSIVE",
        "recovery": "UNKNOWN",
        "classification": [],
        "observation_issues": [],
        "reasons": [],
        "historical_verdict_changed": False,
    }
    count_verified = False
    try:
        window = sealed_window(plan_bytes, events_bytes, seal_bytes, owner)
        report["window"] = window
        require(type(end_ns) is int and end_ns > 0, "Invalid assessment end")
        require(clocks and all(type(t) is int and t >= 0 for t in clocks), "Missing/invalid clock")
        require(
            all(a <= b for a, b in zip(clocks, clocks[1:], strict=False)),
            "Simulation clock discontinuity",
            "FAIL",
        )
        require(
            clocks[0] <= window["start_ns"] < window["restored_ns"] <= clocks[-1],
            "Clock does not bracket fault/restoration",
        )
        raw_graph, out_graph = topology["/scan"], topology["/fault_probe/scan"]
        require(
            len(raw_graph["publishers"]) == len(out_graph["publishers"]) == 1,
            "Missing/ambiguous sensor publishers",
        )
        require(
            raw_graph["publishers"][0]["node"] == "simulation_bridge"
            and out_graph["publishers"][0]["node"] == "scan_fault_relay",
            "Wrong sensor publisher",
            "FAIL",
        )
        raw_subs = {e["node"] for e in raw_graph["subscribers"]}
        out_subs = {e["node"] for e in out_graph["subscribers"]}
        require(
            "amcl" in raw_subs
            and not {"local_costmap", "global_costmap"} & raw_subs
            and {"local_costmap", "global_costmap", "output_scan_monitor"} <= out_subs
            and "amcl" not in out_subs,
            "Sensor-routing bypass/missing endpoint",
            "FAIL",
        )
        for graph in (raw_graph, out_graph):
            require(
                all(
                    e["reliability"] == "BEST_EFFORT" and e["durability"] == "VOLATILE"
                    for e in graph["publishers"] + graph["subscribers"]
                ),
                "Unexpected sensor QoS",
                "FAIL",
            )
        expected_namespaces = {
            "simulation_bridge": "/",
            "scan_fault_relay": "/",
            "amcl": "/",
            "local_costmap": "/local_costmap",
            "global_costmap": "/global_costmap",
            "output_scan_monitor": "/",
        }
        for graph in (raw_graph, out_graph):
            for endpoint in graph["publishers"] + graph["subscribers"]:
                if endpoint["node"] in expected_namespaces:
                    require(
                        endpoint["namespace"] == expected_namespaces[endpoint["node"]]
                        and endpoint["type"] == "sensor_msgs/msg/LaserScan",
                        "Wrong sensor endpoint namespace/type",
                        "FAIL",
                    )
        raw = observations(streams["raw"], "raw", report["observation_issues"])
        output = observations(streams["output"], "output", report["observation_issues"])
        require(
            all(raw[t]["cdr_sha256"] == output[t]["cdr_sha256"] for t in raw.keys() & output),
            "Relay payload mismatch",
            "FAIL",
        )
        lo, hi = max(min(raw), min(output)) + MARGIN_NS, min(max(raw), max(output)) - MARGIN_NS
        require(
            lo < window["start_ns"] and window["restored_ns"] + MARGIN_NS < hi <= end_ns,
            "Incomplete observation coverage",
        )
        report["assessed_stamp_interval_ns"] = [lo, hi]
        report["boundary_unassessed_stamps_ns"] = sorted(
            t for t in raw.keys() | output.keys() if not lo <= t <= hi
        )
        require(all(name in consumers for name in SERVERS), "Missing consumer evidence")
        added = {n: set(consumers[n]["received_stamps_ns"]) for n in SERVERS}
        ready = {n: set(consumers[n]["ready_stamps_ns"]) for n in SERVERS}
        require(all(ready[n] <= added[n] for n in SERVERS), "Ready/receipt evidence conflicts")
        require(
            all(any(lo <= t < window["start_ns"] for t in ready[n]) for n in SERVERS),
            "Missing healthy pre-fault consumer evidence",
        )
        require(
            not any(
                window["start_ns"] <= t < window["stop_ns"]
                for t in output.keys() | added[SERVERS[0]] | added[SERVERS[1]]
            ),
            "Suppressed-window output/consumer delivery conflicts with fault",
            "FAIL",
        )
        diagnostics = ordered_diagnostics(diagnostics, end_ns, report["observation_issues"])
        intentional, unknown, unexpected = [], [], []
        for t in sorted(raw):
            # Boundary omissions also need explicit attribution; the margin only
            # scopes payload/recovery comparison, never hides unexplained loss.
            row = raw[t]
            inside = window["start_ns"] <= t < window["stop_ns"]
            delivered = [n for n in SERVERS if t in added[n] or t in ready[n]]
            if inside:
                require(
                    t not in output and not delivered, "Suppressed-window delivery/bypass", "FAIL"
                )
                require(
                    window["start_ns"] <= row["receipt_ros_ns"] < window["stop_ns"],
                    "Fault sample receipt does not corroborate window",
                )
                intentional.append(t)
                category = "INTENTIONAL_SUPPRESSION"
            elif t in output:
                continue
            elif all(t in ready[n] for n in SERVERS):
                category = "OBSERVER_ONLY_OMISSION"
            elif not delivered and unexpected_starvation(t, diagnostics, window["restored_ns"]):
                category = "CONFIRMED_UNEXPECTED_DELIVERY_LOSS"
                unexpected.append(t)
            else:
                category = "UNKNOWN"
                unknown.append(t)
            report["classification"].append({"stamp_ns": t, "category": category})
        require(
            len(intentional) >= MIN_SAMPLES and len(intentional) == window["affected_samples"],
            "Observed suppression does not match sealed effect count",
        )
        require(
            intentional[0] <= window["effect_ns"] <= intentional[0] + MARGIN_NS,
            "Actual-effect time does not corroborate samples",
        )
        count_verified = True
        report["intentional_stamps_ns"] = intentional
        common = [
            t
            for t in raw.keys() & output
            if t > window["restored_ns"] + MARGIN_NS
            and t <= hi
            and output[t]["receipt_ros_ns"] - t <= FRESH_NS
            and raw[t]["receipt_ros_ns"] - t <= FRESH_NS
            and all(t in ready[n] for n in SERVERS)
        ]
        report["recovery_sample_stamps_ns"] = sorted(common)
        if unexpected:
            report["assessment_status"] = "FAIL"
            report["reasons"].append(
                "Unexpected output delivery starvation corroborated; component unknown"
            )
        if unknown:
            report["reasons"].append("Unexplained observation omissions remain UNKNOWN")
        require(len(common) >= MIN_SAMPLES, "Missing fresh recovery at both consumers")
        require(
            diagnostics[-1]["stamp_ns"] >= end_ns - 1_000_000_000,
            "Diagnostic tail coverage incomplete",
        )
        report["diagnostic_window"] = assess_diagnostic_window(
            diagnostics, window["start_ns"], window["stop_ns"], window["restored_ns"], end_ns
        )
        report["recovery"] = "VERIFIED"
        report["recovery_category"] = "VERIFIED_DOWNSTREAM_RECOVERY"
        report["assessment_status"] = (
            "FAIL" if unexpected else "INCONCLUSIVE" if unknown else "SUPPORTED"
        )
    except EvidenceProblem as exc:
        if report["assessment_status"] != "FAIL":
            report["assessment_status"] = exc.status
        report["reasons"].append(str(exc))
    except (KeyError, TypeError, ValueError, IndexError, AssertionError) as exc:
        report["reasons"].append("Incomplete/malformed evidence: " + str(exc))
    if not count_verified:
        for item in report["classification"]:
            if item["category"] == "INTENTIONAL_SUPPRESSION":
                item["category"] = "UNKNOWN"
    return report


def assess_routing_files(runtime, **observations_data) -> dict:
    """Read an existing relay evidence directory; never create/write a file or guard."""
    from pathlib import Path

    data = {}
    missing = []
    for name, key in (
        ("plan.json", "plan_bytes"),
        ("events.jsonl", "events_bytes"),
        ("seal.json", "seal_bytes"),
    ):
        try:
            data[key] = (Path(runtime) / "relay" / name).read_bytes()
        except OSError as exc:
            data[key] = b""
            missing.append({"file": name, "error": str(exc)})
    report = assess_routing(**data, **observations_data)
    report["relay_input_hashes"] = {k: hashlib.sha256(v).hexdigest() for k, v in data.items()}
    report["unavailable_relay_files"] = missing
    return report
