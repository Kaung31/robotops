# Milestone 7C / 8A — Mission Operations & Benchmark Dashboard

This increment deliberately leaves the now-stable Nav2 bringup unchanged and builds on the existing ExecuteMission multi-waypoint interface.

## Added
- Multi-waypoint route builder and sequential mission submission through the existing mission action.
- Explicit mission UX states so a completed mission immediately returns to "ready for next goal" instead of appearing stuck.
- Live per-run elapsed time and traveled-distance estimate from web telemetry.
- Browser-persistent mission run history (bounded to 250 records).
- Benchmark aggregation by navigation profile: run count, success rate, mean duration and mean distance.
- Recent-run table and JSON/CSV export.

## Scope / data ownership
The benchmark history in this increment is intentionally browser-local. Canonical experiment artifacts and MCAP data remain owned by the ROS experiment/mission layers. A later Milestone 8 increment can promote benchmark metadata to PostgreSQL / server-side experiment records without changing the mission interface.

## Audit corrections

- Benchmark aggregates are grouped by map and navigation profile.
- Average duration and distance are calculated from successful runs only; success rate includes all attempts.
- Each active mission snapshots its map/profile at launch so later UI selection changes cannot relabel a stored run.
- Route building enforces the API limit of 100 waypoints.
- Mission elapsed time is driven by an independent UI timer.
- Stored browser history is validated on load and localStorage failures do not block mission controls.
