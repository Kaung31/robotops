# Milestone 7 — Web platform

## Goal

Add a typed application boundary around the existing ROS stack and a browser UI for
robot status, mission submission/cancellation and live 2D map/pose/LiDAR telemetry.
The browser must never become the source of truth for robot state, and replay must
remain read-only.

## Scope

- FastAPI backend with versioned HTTP and WebSocket APIs.
- Pluggable gateway contract so application code is not simulator-specific.
- ROS gateway using existing `missions/execute`, `/odom`, `/map` and `/scan` contracts.
- React + TypeScript dashboard with connection/mode state, mission controls and a 2D map.
- Explicit stale/disconnected telemetry state.
- Backend portable tests for state/validation behavior.

## Out of scope

- Authentication/authorization for public deployment.
- PostgreSQL persistence and historical dataset browser.
- Replay implementation.
- Fault injection, diagnostics aggregation and ML.
- Direct browser access to the ROS graph.
- Electrical power control or physical-hardware safety claims.

## Success criteria

1. The backend can run without ROS and reports the robot as unavailable rather than
   fabricating state.
2. With the ROS gateway enabled, map/pose/scan updates feed a WebSocket snapshot.
3. Mission start/cancel goes through the existing mission action only.
4. Replay mode rejects mutating mission requests.
5. The frontend visibly distinguishes connected, stale and disconnected telemetry.
6. The frontend renders occupancy cells and the robot pose without owning live state.
7. Portable backend tests and frontend static/type checks are documented; anything
   not runnable in the current environment remains explicitly unverified.

## Implementation status

Implemented the first web-platform slice:

- `backend/`: FastAPI API boundary, typed models, thread-safe telemetry store,
  pluggable gateway contract, optional ROS 2 adapter, HTTP mission start/cancel,
  WebSocket telemetry and replay mutation rejection.
- ROS adapter consumes the existing mission action plus odometry, occupancy map and
  LiDAR; map and sensor QoS are explicit. It does not publish velocity or bypass the
  mission manager.
- Mission admission requires fresh live telemetry. Cancellation remains available
  when telemetry is stale/disconnected so a stop attempt is not blocked by the UI
  health gate.
- JavaScript-facing nanosecond timestamps are serialized as strings to avoid loss of
  integer precision.
- `web/`: React/TypeScript status dashboard, map/pose canvas, LiDAR canvas and mission
  start/cancel controls. Replay/unknown modes disable mutating controls; stale or
  disconnected state disables mission start.
- Root CI now contains a web typecheck/build job and portable Python discovery includes
  backend tests.

Portable verification in the continuation environment and second audit:

- backend/API plus Milestone 6 model tests: 31 passed after additional regression coverage;
- Ruff formatting/lint passed for the updated source tree;
- Python compile checks passed;
- `web/package.json` JSON validation passed.
- source comparison confirmed no source-like file from the uploaded pre-web tree was dropped.

The second audit also fixed stale/disconnect propagation, WebSocket reconnect behavior,
ROS timeout HTTP mapping, occupancy/scan validation and same-origin serving of a built frontend.

The frontend dependency installation could not complete in the sandbox, so the
TypeScript/Vite build is intentionally marked unverified here. The ROS adapter also
requires a sourced Jazzy workspace and must be verified in the project ROS
container before Milestone 7 is considered fully accepted.
