# Milestone 7B.1 — Visualization and Map UX

## Goal

Turn the Milestone 7B telemetry canvas into an interactive navigation workspace without changing the established ROS control path.

## Scope

- interactive 2D occupancy-map viewer
- fit/zoom/pan controls
- clearer robot pose/heading marker
- click-on-map goal selection
- selected-goal marker
- global and local Nav2 path overlays when the standard `plan` / `local_plan` topics are available
- mission form synchronization with the selected map goal
- saved-map metadata linking newly saved maps to the simulation world used to create them
- backend rejection of known map/world mismatches
- legacy saved maps remain usable when they have no world metadata

## Architectural rules

- Clicking the map selects a goal only; it does not bypass `mission_manager`.
- Browser remains an application client and does not publish ROS topics directly.
- Nav2 planner/controller selection remains owned by the approved orchestrator profiles.
- Map/world compatibility is enforced by the backend when metadata is known.
- No ROS package interfaces are changed by this milestone.

## ROS telemetry additions

The web gateway subscribes to:

- `plan` (`nav_msgs/msg/Path`)
- `local_plan` (`nav_msgs/msg/Path`)
- `amcl_pose` (`geometry_msgs/msg/PoseWithCovarianceStamped`)

Missing path topics are non-fatal; overlays simply remain empty.

## Map metadata

Newly saved maps get a sidecar file:

```text
artifacts/maps/<map>.robotops.json
```

containing the source `world_id`.

Existing maps without a sidecar are treated as legacy/unknown-world maps so old work is not broken.

## Validation

Backend focused suite after implementation:

```text
24 passed
```

Frontend TypeScript/Vite build must be rerun in the Jazzy Distrobox after applying the patch.
