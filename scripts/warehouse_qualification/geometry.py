"""W3-only pure checks; measurements are never synthesized as telemetry."""

import math


def flatten(value, prefix=""):
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.update(flatten(item, name))
        else:
            result[name] = item
    return result


def ray_distance(x, y, angle, boxes):
    dx, dy = math.cos(angle), math.sin(angle)
    distances = []
    for box in boxes:
        lo, hi = 0.0, math.inf
        for origin, direction, centre, size in zip(
            (x, y), (dx, dy), box["centre_m"][:2], box["size_m"][:2], strict=True
        ):
            minimum, maximum = centre - size / 2, centre + size / 2
            if abs(direction) < 1e-12:
                if not minimum <= origin <= maximum:
                    hi = -1
                    break
            else:
                a, b = (minimum - origin) / direction, (maximum - origin) / direction
                lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
        if hi >= lo:
            distances.append(lo)
    return min(distances, default=math.inf)


def scan_check(ranges, angle_min, increment, maximum, x, y, heading, boxes):
    errors = []
    for i, observed in enumerate(ranges):
        expected = ray_distance(x, y, heading + angle_min + i * increment, boxes)
        if 0.15 < expected < maximum - 0.1:
            errors.append(abs(observed - expected) if math.isfinite(observed) else maximum)
    if len(errors) < 100:
        raise ValueError("Insufficient comparable static LiDAR rays")
    within = sum(error <= 0.15 for error in errors) / len(errors)
    result = {
        "comparable_rays": len(errors),
        "fraction_within_0_15m": within,
        "max_error_m": max(errors),
        "mean_error_m": sum(errors) / len(errors),
    }
    return result, within >= 0.95


def qualified(manifest):
    trials = manifest.get("trials", [])
    return (
        manifest.get("state") == "completed"
        and len(trials) == 1
        and trials[0].get("action_status") == 4
        and trials[0].get("mission_outcome") == "succeeded"
        and trials[0].get("validation", {}).get("verdict") == "POSE_VERIFIED"
        and trials[0].get("collision", {}).get("verdict") == "NO_CONTACT_OBSERVED"
    )
