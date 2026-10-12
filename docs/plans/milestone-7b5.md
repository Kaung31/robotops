# Milestone 7B.5 — Nav2 Auto-Readiness & Auto-Localization

## Goal

Remove the manual Nav2 recovery sequence discovered during live testing. In simulation, starting Navigation from RobotOps should automatically establish localization and activate the remaining Nav2 lifecycle nodes before missions are allowed.

## Behavior

Navigation startup now:

1. resets readiness from the previous stack;
2. starts the approved simulation, saved-map navigation, and mission launch processes;
3. waits for a fresh saved map;
4. ensures map server and AMCL are active;
5. publishes the known simulation spawn pose `(0, 0, 0)` to `/initialpose`;
6. waits for `/amcl_pose`;
7. waits for `map -> base_link` TF;
8. activates any remaining inactive Nav2 lifecycle nodes in dependency-aware order;
9. exposes a readiness model to the web UI;
10. blocks new mission submission until readiness is true.

## Safety / scope

- Automatic pose initialization is simulation-only.
- Real hardware must not assume `(0, 0, 0)` and will require an operator/known-dock localization strategy later.
- The browser still does not invoke arbitrary shell commands.
- Existing ROS launch interfaces and planner profiles are unchanged.

## API

- `GET /api/v1/navigation/readiness`
- `POST /api/v1/navigation/prepare` to retry the approved simulation readiness sequence

## UI

Navigation mode now displays:

- map availability;
- AMCL localization;
- `map -> base_link` TF readiness;
- lifecycle state for map server, AMCL, controller, behavior server, planner, and BT navigator;
- READY / NOT READY state;
- retry button when preparation is incomplete.

Mission start is disabled until READY.

## Audit hardening

- Automatic startup requires a fresh AMCL pose after the current run's initial-pose publication; a late sample from a previous stack cannot satisfy readiness.
- RobotOps activates top-level Nav2 servers only. `controller_server` and `planner_server` retain ownership of their local/global costmap lifecycle transitions.
