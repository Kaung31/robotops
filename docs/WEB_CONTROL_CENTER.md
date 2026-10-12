# RobotOps web control center

The web application is the normal local entry point for RobotOps simulation workflows. You start the FastAPI/backend service from a sourced Jazzy environment; the browser then requests only approved Mapping/Navigation operations through backend orchestration.

RobotOps is local-first today. A later milestone may expose a safe simulation-only portfolio/demo mode for friends, recruiters, and interviewers. That future demo must not expose arbitrary shell execution, a generic public ROS graph, or physical-robot control.

## One-time environment setup

Inside the `jazzy` Distrobox:

```bash
distrobox enter jazzy
cd ~/robotops_verified_source_v2/robotops
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

.venv/bin/python -m pip install -e ./backend

cd web
npm install
npm run typecheck
npm run build
cd ..
```

## Run the production-style local app

From the repository root in the sourced Jazzy/workspace shell:

```bash
export ROBOTOPS_GATEWAY=ros
export ROBOTOPS_RUNTIME_MODE=sim
export ROBOTOPS_WEB_DIST="$PWD/web/dist"
export ROBOTOPS_USE_XVFB=true
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

.venv/bin/python -m uvicorn robotops_backend.app:app \
  --app-dir backend \
  --host 127.0.0.1 \
  --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Do not separately launch Gazebo/Nav2 for normal web-control use. A separately launched RViz is fine for debugging.

## Mapping workflow

1. Select **Mapping**.
2. Select an approved environment.
3. Optionally enable **Open RViz engineering view when the stack starts**.
4. Click **Start system**.
5. Wait for live odometry/LiDAR/map telemetry.
6. Use press-and-hold teleoperation.
7. Watch the occupancy map build live.
8. Save the map from the web UI.
9. Click **Stop system** before switching workflows.

Generated maps live under:

```text
artifacts/maps/<name>.yaml
artifacts/maps/<name>.pgm
```

## Navigation workflow

1. Select **Navigation**.
2. Select the same simulation world used to create the saved map.
3. Select a compatible saved map.
4. Select `navfn_rpp` or `smac_dwb`.
5. Optionally enable **Open RViz engineering view when the stack starts**.
6. Click **Start system**.
7. Wait for Navigation READY. Current READY checks do not yet enforce per-stream age or fresh AMCL receipt; see `CURRENT_STATUS.md` for the diagnostic limits.
8. Send a single goal or waypoint route from Mission Operations.
9. Observe pose, map, LiDAR, mission state, and optionally RViz.
10. Cancel a web-started mission if needed.
11. Click **Stop system** when finished.

RViz may also be opened or closed while a Mapping/Navigation stack is already running. RViz is auxiliary: closing or crashing it must not stop the robot stack.

## Automated benchmark campaign — current transitional behavior

The current browser Automated Benchmark Campaign can:

- select world/map/profile(s);
- set repetitions and trial timeout;
- build a waypoint route;
- restart simulation/navigation between trials;
- wait for Navigation READY;
- submit the mission;
- collect lightweight metrics/history/export data.

This browser orchestration is **transitional**. Preserve it while stabilizing the current behavior, but do not add new authoritative experiment truth to React. The target is a canonical backend experiment service; the web should become a campaign client and progress/results viewer.

Automated campaigns intentionally use:

```text
open_rviz: false
```

so repeated benchmark trials do not spawn RViz windows or depend on GUI load.

### Current campaign diagnostic

Manual Mission Operations + Gazebo + RViz + RobotOps are working. During automated campaign testing, visual movement was not seen as expected, but the captured UI was still at `restarting simulation`, where movement is not expected.

Before changing architecture, run one small campaign (`navfn_rpp`, one repetition, known-good route) and wait until mission acceptance. Then classify:

```text
Gazebo moves + RViz moves + RobotOps does not
  -> web telemetry/rendering

Gazebo moves + RViz does not + RobotOps does not
  -> ROS TF/localization/telemetry freshness/reconnect

Gazebo does not move
  -> campaign readiness/orchestration/mission path
```

Do not hide an existing runtime bug inside the backend refactor.

## Readiness semantics

The UI should not treat the following as equivalent:

```text
stack running != connected != navigation ready != experiment ready
```

For restart-per-trial experiments, freshness matters. A transform that merely remains in a long-lived TF buffer is not sufficient evidence that the new trial is localized and ready.

## Stack state and logs

The UI reports `stopped`, `starting`, `running`, `stopping` or `failed`.

If a managed core ROS launch exits unexpectedly, the backend marks the stack failed and stops remaining managed core processes. A RobotOps-owned RViz process should also be cleaned up, but RViz itself is never a core process.

Logs are written under:

```text
artifacts/logs/orchestrator/
```

## Important boundaries

- The browser never receives arbitrary shell access.
- The backend accepts only approved worlds, maps and Nav2 profiles.
- Teleop goes through `/cmd_vel/teleop`; the existing mux/guard/watchdog remain authoritative.
- ROS remains the source of live robot truth.
- Replay remains read-only.
- Physical robot orchestration is intentionally unavailable.
- Keep the current service on localhost/trusted development networking.
- A future public demo is simulation-only and must add an application trust/session boundary.
- RViz is observability only and must not affect benchmark outcomes.
