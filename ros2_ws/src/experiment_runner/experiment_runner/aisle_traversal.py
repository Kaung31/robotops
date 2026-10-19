"""Independent aisle-traversal validation from recorded trajectories. Pure; no ROS imports.

A succeeded Nav2 mission says each waypoint was reached, not how the robot got there.
This module decides from time-stamped map-frame positions alone whether the robot
entered a corridor through one gate, traversed it and left through the opposite gate,
in a required order. Evidence that cannot settle the question (gaps, jumps, positions
inside obstacles, missing coverage, disagreeing sources) is INCONCLUSIVE, never a guess.

Zones use hysteresis: a position counts as "low" or "high" only beyond a band around
each gate line, and as "inside" only within the corridor clear of both bands.
Positions in a band keep the previous zone, so localization jitter at a gate cannot
create or hide a crossing.
"""

from __future__ import annotations

import math

Sample = tuple[int, float, float]  # (stamp_ns, x, y) in the map frame
Rect = tuple[float, float, float, float]  # (x_min, x_max, y_min, y_max)

VERIFIED = "TRAVERSAL_VERIFIED"
NOT_MET = "ROUTE_REQUIREMENT_NOT_MET"
INCONCLUSIVE = "INCONCLUSIVE"
DIRECTIONS = ("low_to_high", "high_to_low")

DEFAULT_POLICY = {
    "gate_band_m": 0.15,
    "max_gap_s": 0.25,
    "max_speed_m_s": 0.5,
    "jump_tolerance_m": 0.10,
    "obstacle_tolerance_m": 0.10,
    "coverage_tolerance_s": 0.5,
}


def corridor(spec: dict) -> dict:
    """Validate a corridor: axis-aligned, gates are its two ends along `axis`."""
    if set(spec) != {"axis", "low", "high", "lateral"} or spec["axis"] not in ("x", "y"):
        raise ValueError("corridor needs axis (x|y), low, high and lateral bounds")
    values = [spec["low"], spec["high"], *spec["lateral"]]
    if len(spec["lateral"]) != 2 or not all(
        type(v) in (int, float) and math.isfinite(v) for v in values
    ):
        raise ValueError("corridor bounds must be finite numbers")
    if not (spec["low"] < spec["high"] and spec["lateral"][0] < spec["lateral"][1]):
        raise ValueError("corridor bounds must be increasing")
    return dict(spec, lateral=tuple(spec["lateral"]))


def policy_for(policy: dict | None) -> dict:
    merged = dict(DEFAULT_POLICY, **(policy or {}))
    if set(merged) != set(DEFAULT_POLICY):
        raise ValueError("Unknown aisle traversal policy fields")
    for key, value in merged.items():
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be finite and positive")
    return merged


def _axes(c: dict, x: float, y: float) -> tuple[float, float]:
    """(along-corridor, lateral) coordinates."""
    return (y, x) if c["axis"] == "y" else (x, y)


def _zone(c: dict, band: float, tol: float, u: float, v: float) -> str | None:
    if u < c["low"] - band:
        return "low"
    if u > c["high"] + band:
        return "high"
    lo, hi = c["lateral"]
    if c["low"] + band <= u <= c["high"] - band and lo - tol <= v <= hi + tol:
        return "inside"
    return None  # Gate band, or beside the corridor: keep the previous zone.


def _boundary_distance(c: dict, band: float, u: float, v: float) -> float:
    """Shortest distance to any line where the zone classification could change."""
    lo, hi = c["lateral"]
    along = min(
        abs(u - level)
        for level in (c["low"] - band, c["low"] + band, c["high"] - band, c["high"] + band)
    )
    if c["low"] - band <= u <= c["high"] + band:
        along = min(along, abs(v - lo), abs(v - hi))
    return along


def _crossing(samples, uv, i, j, level):
    """Time and lateral position of the last crossing of `level` between i and j."""
    for k in range(j, i, -1):
        u0, u1 = uv[k - 1][0], uv[k][0]
        if (u0 - level) * (u1 - level) <= 0 and u0 != u1:
            f = (level - u0) / (u1 - u0)
            t = samples[k - 1][0] + f * (samples[k][0] - samples[k - 1][0])
            return round(t), uv[k - 1][1] + f * (uv[k][1] - uv[k - 1][1])
    return None, None


def analyse(
    samples: list[Sample],
    spec: dict,
    *,
    window_ns: tuple[int, int],
    obstacles: list[Rect] = (),
    policy: dict | None = None,
) -> dict:
    """Zones, traversals and evidence problems for one trajectory source."""
    c, p = corridor(spec), policy_for(policy)
    start, end = window_ns
    result = dict(
        status="COMPLETE",
        problems=[],
        samples=0,
        zones=[],
        traversals=[],
        aborted_entries=[],
        bypasses=[],
        start_zone=None,
        end_zone=None,
    )
    problems = result["problems"]
    if not end > start:
        problems.append("Mission window is empty")
    if any(
        len(s) != 3 or type(s[0]) is not int or not all(math.isfinite(v) for v in s[1:])
        for s in samples
    ):
        result.update(status="INCOMPLETE", problems=["Malformed or nonfinite samples"])
        return result
    stamps = [s[0] for s in samples]
    if any(b <= a for a, b in zip(stamps, stamps[1:], strict=False)):
        result.update(status="INCOMPLETE", problems=["Samples are not strictly time-ordered"])
        return result
    tol_ns = p["coverage_tolerance_s"] * 1e9
    inside_window = [s for s in samples if start - tol_ns <= s[0] <= end + tol_ns]
    result["samples"] = len(inside_window)
    if not inside_window:
        problems.append("No samples in the mission window")
    else:
        # An uncovered edge is acceptable only if the robot could not have reached any
        # zone boundary in that time (e.g. recording began at dispatch, before the
        # first bracketed map->odom sample).
        for missing_ns, (_, x, y) in (
            (inside_window[0][0] - start, inside_window[0]),
            (end - inside_window[-1][0], inside_window[-1]),
        ):
            missing_s = missing_ns / 1e9
            reach = missing_s * p["max_speed_m_s"] + p["jump_tolerance_m"]
            if missing_s > p["coverage_tolerance_s"] and reach >= _boundary_distance(
                c, p["gate_band_m"], *_axes(c, x, y)
            ):
                problems.append(
                    f"Trajectory misses {missing_s:.3f} s at a mission-window edge, "
                    "enough to change zone unobserved"
                )
    samples = inside_window
    uv = [_axes(c, x, y) for _, x, y in samples]
    for (t0, x0, y0), (t1, x1, y1) in zip(samples, samples[1:], strict=False):
        dt = (t1 - t0) / 1e9
        if dt > p["max_gap_s"]:
            problems.append(f"Gap of {dt:.3f} s at {t0} ns")
        elif math.hypot(x1 - x0, y1 - y0) > p["max_speed_m_s"] * dt + p["jump_tolerance_m"]:
            problems.append(f"Position jump of {math.hypot(x1 - x0, y1 - y0):.3f} m at {t1} ns")
    tol = p["obstacle_tolerance_m"]
    for t, x, y in samples:
        if any(r[0] + tol < x < r[1] - tol and r[2] + tol < y < r[3] - tol for r in obstacles):
            problems.append(f"Position ({x:.3f}, {y:.3f}) is inside an obstacle at {t} ns")
            break
    if problems:
        if len(problems) > 20:
            problems[20:] = [f"... and {len(problems) - 20} more"]
        result["status"] = "INCOMPLETE"
        return result

    # Stable zone runs: (zone, first index, last index).
    runs: list[list] = []
    for k, (u, v) in enumerate(uv):
        zone = _zone(c, p["gate_band_m"], tol, u, v)
        if zone is None:
            continue
        if runs and runs[-1][0] == zone:
            runs[-1][2] = k
        else:
            runs.append([zone, k, k])
    if not runs:
        result.update(status="INCOMPLETE", problems=["No sample lies in a decidable zone"])
        return result
    result.update(zones=[r[0] for r in runs], start_zone=runs[0][0], end_zone=runs[-1][0])
    lo, hi = c["lateral"]
    centre = (lo + hi) / 2
    for a, b in zip(runs, runs[1:], strict=False):
        if {a[0], b[0]} == {"low", "high"}:
            result["bypasses"].append(
                dict(
                    direction=f"{a[0]}_to_{b[0]}",
                    left_ns=samples[a[2]][0],
                    arrived_ns=samples[b[1]][0],
                )
            )
    for k in range(1, len(runs) - 1):
        before, inside, after = runs[k - 1], runs[k], runs[k + 1]
        if inside[0] != "inside":
            continue
        if before[0] == after[0]:
            result["aborted_entries"].append(
                dict(
                    side=before[0], entered_ns=samples[inside[1]][0], left_ns=samples[inside[2]][0]
                )
            )
            continue
        entry_level = c["low"] if before[0] == "low" else c["high"]
        exit_level = c["high"] if before[0] == "low" else c["low"]
        entry_ns, entry_v = _crossing(samples, uv, before[2], inside[1], entry_level)
        exit_ns, exit_v = _crossing(samples, uv, inside[2], after[1], exit_level)
        if entry_ns is None or exit_ns is None:
            result.update(
                status="INCOMPLETE",
                problems=["A gate crossing could not be located between samples"],
            )
            return result
        if not (lo - tol <= entry_v <= hi + tol and lo - tol <= exit_v <= hi + tol):
            result.update(
                status="INCOMPLETE", problems=["Gate crossing lies outside the corridor opening"]
            )
            return result
        span = [k2 for k2 in range(len(samples)) if entry_ns <= samples[k2][0] <= exit_ns]
        lateral = [uv[k2][1] for k2 in span]
        result["traversals"].append(
            dict(
                direction=f"{before[0]}_to_{after[0]}",
                entry_ns=entry_ns,
                exit_ns=exit_ns,
                duration_s=(exit_ns - entry_ns) / 1e9,
                entry_lateral_m=entry_v,
                exit_lateral_m=exit_v,
                max_lateral_offset_m=max(abs(v - centre) for v in [entry_v, exit_v, *lateral]),
                min_centre_to_wall_m=min(min(v - lo, hi - v) for v in [entry_v, exit_v, *lateral]),
                path_length_m=sum(
                    math.dist(samples[a][1:], samples[b][1:])
                    for a, b in zip(span, span[1:], strict=False)
                ),
            )
        )
    return result


def _overlaps(a: dict, b: dict) -> bool:
    return a["entry_ns"] <= b["exit_ns"] and b["entry_ns"] <= a["exit_ns"]


def assess(
    localized: list[Sample],
    spec: dict,
    *,
    window_ns: tuple[int, int],
    required: list[str],
    start_zone: str,
    obstacles: list[Rect] = (),
    ground_truth: list[Sample] | None = None,
    require_ground_truth: bool = True,
    policy: dict | None = None,
) -> dict:
    """Verdict on whether the required ordered traversals happened.

    Ground truth must already be in the map frame (see ground_truth._to_map); it is
    compared, never preferred: when the sources disagree the result is INCONCLUSIVE.
    """
    if not required or any(d not in DIRECTIONS for d in required):
        raise ValueError(f"required traversals must be drawn from {DIRECTIONS}")
    if start_zone not in ("low", "high"):
        raise ValueError("start_zone must be low or high")
    end_zone = start_zone
    for direction in required:
        if not direction.startswith(end_zone):
            raise ValueError("required traversals must chain end to start")
        end_zone = direction.split("_to_")[1]
    kwargs = dict(window_ns=window_ns, obstacles=obstacles, policy=policy)
    sources = {"localized": analyse(localized, spec, **kwargs)}
    if ground_truth is not None:
        sources["ground_truth"] = analyse(ground_truth, spec, **kwargs)
    result = dict(
        schema_version=1,
        scope=(
            "Corridor traversal from recorded map-frame positions. Says nothing about "
            "contact, clearance or why the route was chosen."
        ),
        corridor=corridor(spec),
        policy=policy_for(policy),
        required=list(required),
        required_start_zone=start_zone,
        required_end_zone=end_zone,
        sources=sources,
        reasons=[],
    )
    reasons = result["reasons"]
    for name, analysis in sources.items():
        if analysis["status"] != "COMPLETE":
            reasons.append(f"{name} evidence incomplete: " + "; ".join(analysis["problems"]))
    if ground_truth is None and require_ground_truth:
        reasons.append("Ground truth is required but unavailable")
    if reasons:
        return dict(result, verdict=INCONCLUSIVE)
    if "ground_truth" in sources:
        a, b = sources["localized"], sources["ground_truth"]
        if (
            [t["direction"] for t in a["traversals"]] != [t["direction"] for t in b["traversals"]]
            or not all(map(_overlaps, a["traversals"], b["traversals"]))
            or (a["start_zone"], a["end_zone"]) != (b["start_zone"], b["end_zone"])
            or len(a["bypasses"]) != len(b["bypasses"])
        ):
            reasons.append("Localized and ground-truth trajectories disagree")
            return dict(result, verdict=INCONCLUSIVE)
    observed = sources["localized"]
    met = (
        [t["direction"] for t in observed["traversals"]] == list(required)
        and observed["start_zone"] == start_zone
        and observed["end_zone"] == end_zone
        and not observed["bypasses"]
    )
    if not met:
        reasons.append(
            "Observed traversals "
            f"{[t['direction'] for t in observed['traversals']]} from {observed['start_zone']} "
            f"to {observed['end_zone']} with {len(observed['bypasses'])} bypass(es); "
            f"required {list(required)} from {start_zone} to {end_zone}"
        )
    return dict(result, verdict=VERIFIED if met else NOT_MET)
