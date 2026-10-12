# RobotOps Testing, Run, and Web Deployment Guide

This guide is the operator checklist for validating RobotOps from a clean checkout/source archive.
Run the stages in order. Do not skip directly to the web UI if the ROS stack below it is not healthy.

## 0. What this guide assumes

Primary target:

- Ubuntu 24.04
- ROS 2 Jazzy
- Gazebo Harmonic
- Node.js 22 for the web frontend
- Python 3.12+ for portable/backend checks

The project is currently simulation-first. Physical robot operation is not yet implemented or approved.
Do not expose the unauthenticated backend or ROS graph to an untrusted network.

## 1. Keep a backup first

Before replacing an older working folder:

1. Keep the old folder or ZIP until the new source archive passes the checks in this guide.
2. If the old folder contains `.git`, do not delete it merely because a source ZIP works. The source archive intentionally does not contain Git history.
3. Back up any `.mcap`, `.db3`, saved maps, experiment artifacts, or local `.env` files separately. These are intentionally ignored by Git/source packaging.
4. Only remove the older source copy after the acceptance checklist at the end passes.

## 2. Extract and inspect the source archive

After extracting, the repository root should contain at least:

```text
AGENTS.md
README.md
docs/
ros2_ws/
backend/
web/
.github/workflows/ci.yml
pyproject.toml
requirements-dev.txt
```

It should **not** need to contain:

```text
.venv/
ros2_ws/build/
ros2_ws/install/
ros2_ws/log/
node_modules/
web/dist/
__pycache__/
.pytest_cache/
.ruff_cache/
```

Those are generated locally.

## 3. Portable source checks — no ROS required

From the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/python --version  # must report Python 3.12.x
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
```

Run Python formatting/lint/tests:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
```

Run C++ formatting:

```bash
find ros2_ws/src -type f \( -name '*.cpp' -o -name '*.hpp' \) \
  -exec .venv/bin/clang-format --dry-run --Werror {} +
```

Run YAML/CMake checks:

```bash
.venv/bin/yamllint .
find ros2_ws/src -name CMakeLists.txt -exec .venv/bin/cmake-lint {} +
find ros2_ws/src -name CMakeLists.txt -exec .venv/bin/cmake-format --check {} +
```

If `xmllint` is installed:

```bash
find ros2_ws/src -type f \( -name '*.xml' -o -name '*.xacro' -o -name '*.sdf' \) \
  -exec xmllint --noout {} +
```

Expected result: all checks pass before ROS integration testing.

## 4. Install ROS dependencies and build

Open a clean ROS 2 Jazzy shell. Do not activate the portable `.venv` while building ROS packages.

```bash
source /opt/ros/jazzy/setup.bash
sudo apt-get update
sudo apt-get install -y \
  python3-colcon-common-extensions \
  python3-rosdep \
  liburdfdom-tools \
  xvfb \
  xauth \
  libgl1-mesa-dri
```

Initialize rosdep once per machine if needed:

```bash
sudo rosdep init
```

Then:

```bash
rosdep update --rosdistro jazzy
rosdep install --from-paths ros2_ws/src --ignore-src --rosdistro jazzy -r -y
```

Build:

```bash
cd ros2_ws
colcon build --event-handlers console_direct+
source install/setup.bash
```

Validate installed robot resources:

```bash
cd /tmp
xacro "$(ros2 pkg prefix --share robot_description)/urdf/robot.urdf.xacro" \
  -o /tmp/robotops.urdf
check_urdf /tmp/robotops.urdf
ros2 launch robot_description description.launch.py --show-args
```

## 5. Run the normal ROS test suite

From `ros2_ws` with Jazzy and the workspace sourced:

```bash
colcon test --event-handlers console_direct+ --return-code-on-test-failure
colcon test-result --verbose
```

Do not continue if there are unexplained failures.

## 6. Test mock control first

Launch mock mode:

```bash
ros2 launch robot_bringup robot.launch.py mode:=mock
```

In another sourced terminal:

```bash
ros2 control list_controllers
ros2 topic pub --rate 20 /cmd_vel/test geometry_msgs/msg/TwistStamped \
  '{header: {stamp: now, frame_id: base_link}, twist: {linear: {x: 0.15}}}'
```

Verify:

- controllers are active;
- wheel/odometry state changes as designed;
- stopping the publisher causes the command watchdog to stop motion;
- no direct publishing to `drive_controller/cmd_vel` is needed.

Stop with Ctrl+C.

## 7. Test Gazebo control and shutdown reliability

Build the simulation-specific tests:

```bash
cd ros2_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
colcon build --packages-select robot_bringup --cmake-args -DROBOTOPS_SIM_TESTS=ON
colcon build --packages-select robot_simulation \
  --cmake-args -DROBOTOPS_GAZEBO_SHUTDOWN_TESTS=ON
source install/setup.bash
```

Run:

```bash
ROS_DOMAIN_ID=87 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
xvfb-run -a colcon test --packages-select robot_bringup robot_simulation \
  --return-code-on-test-failure --event-handlers console_direct+ \
  --ctest-args -R '^(sim_control|gazebo_shutdown)$'

colcon test-result --verbose
```

Because Gazebo previously had an intermittent shutdown deadlock, repeat the shutdown test several times before calling a machine/environment stable. A single clean run is useful but not sufficient proof that the historical issue can never recur.

## 8. Test mapping and saved-map localization

Read `docs/MAPPING.md` first.

Build/run the automated mapping system test:

```bash
cd ros2_ws
colcon build --packages-select robot_navigation --cmake-args -DROBOTOPS_MAPPING_TESTS=ON
source install/setup.bash
xvfb-run -a colcon test --packages-select robot_navigation \
  --return-code-on-test-failure --event-handlers console_direct+ \
  --ctest-args -R '^mapping_system$'
colcon test-result --verbose
```

Manual showcase validation should confirm:

- custom Gazebo world launches;
- LiDAR is visible;
- SLAM produces `/map`;
- map grows while the robot explores;
- map can be saved;
- the saved map can be loaded later;
- AMCL/localization works without rebuilding the map every run.

## 9. Test Nav2 navigation profiles

Read `docs/NAVIGATION.md` first.

```bash
cd ros2_ws
colcon build --packages-select robot_navigation \
  --cmake-args -DROBOTOPS_NAVIGATION_TESTS=ON
source install/setup.bash
xvfb-run -a colcon test --packages-select robot_navigation \
  --return-code-on-test-failure --event-handlers console_direct+ \
  --ctest-args -R '^navigation_system$'
colcon test-result --verbose
```

Verify both configured navigation profiles rather than testing only one planner/controller combination.

## 10. Test missions and recording

Read `docs/MISSIONS.md` first.

```bash
cd ros2_ws
colcon build --packages-select mission_manager \
  --cmake-args -DROBOTOPS_MISSION_SIM_TESTS=ON
source install/setup.bash
xvfb-run -a colcon test --packages-select mission_manager \
  --return-code-on-test-failure --event-handlers console_direct+ \
  --ctest-args -R '^mission_system$'
colcon test-result --verbose
```

Verify:

- mission accepted/rejected states are explicit;
- cancellation is not silently assumed successful;
- MCAP recording starts/stops cleanly;
- mission/run IDs remain traceable;
- incomplete/interrupted runs remain visible rather than being erased.

## 11. Test repeated experiments

Read `docs/EXPERIMENTS.md` first.

```bash
cd ros2_ws
colcon build --packages-select experiment_runner \
  --cmake-args -DROBOTOPS_EXPERIMENT_SIM_TESTS=ON
source install/setup.bash
xvfb-run -a colcon test --packages-select experiment_runner \
  --return-code-on-test-failure --event-handlers console_direct+ \
  --ctest-args -R '^experiment_system$'
colcon test-result --verbose
```

Verify:

- each repetition has its own trial record;
- map/start pose/parameters are checked before a repetition;
- parameter drift causes rejection rather than a misleading comparison;
- interrupted/running experiments cannot be compared as finalized results;
- failed trials remain in results;
- distance/metrics are derived from the recording as documented.

## 12. Backend-only tests

With the portable virtual environment active:

```bash
.venv/bin/python -m pytest -q backend/tests
```

Important behaviors covered include:

- disconnected state is not fabricated as connected;
- stale telemetry becomes visible even if no new ROS message arrives;
- replay rejects mutating commands;
- mission start requires fresh telemetry;
- cancellation remains available as an attempt when telemetry is stale;
- ROS timeout errors become HTTP 504 rather than unexplained 500 errors;
- malformed maps/scans are rejected;
- a built frontend can be served same-origin by FastAPI.

## 13. Frontend install, typecheck and build

Use Node.js 22.

```bash
cd web
npm install
npm run typecheck
npm run build
```

After the first successful dependency install, commit the generated `package-lock.json` to the real Git repository and prefer:

```bash
npm ci
```

for repeatable CI/local builds.

Expected build output:

```text
web/dist/
```

`web/dist/` is generated and should not be committed.

## 14. Run the development web UI against simulation

### Terminal A — launch the ROS simulation/navigation stack

Follow `docs/MAPPING.md` / `docs/NAVIGATION.md` for the saved-map navigation stack you want to demonstrate.

Confirm before starting the backend:

```bash
ros2 topic echo /odom --once
ros2 topic echo /map --once
ros2 topic echo /scan --once
ros2 action list | grep missions/execute
```

### Terminal B — backend

From the repository root in a sourced Jazzy/workspace shell:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
export ROBOTOPS_GATEWAY=ros
export ROBOTOPS_RUNTIME_MODE=sim
uvicorn robotops_backend.app:app --app-dir backend --host 127.0.0.1 --port 8000
```

Check:

```bash
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/robot
```

### Terminal C — Vite frontend

```bash
cd web
npm run dev
```

Open the local URL printed by Vite.

Verify visually:

- mode says `sim`;
- connection becomes `connected` when ROS telemetry is active;
- stopping the ROS telemetry path eventually changes the web state to stale/disconnected rather than staying green forever;
- occupancy map renders;
- robot pose is in the correct map location/orientation;
- LiDAR renders;
- a valid mission can be sent;
- the mission result eventually leaves the navigating state;
- cancel can be attempted for the active web-started mission;
- no direct velocity command comes from the browser.

Also verify WebSocket reconnect: restart the backend and confirm the page reconnects without requiring a full browser refresh.

## 15. Production-build test for the web UI — local/simulation only

This is a production **build** test, not approval for public or physical-robot deployment.

Build the frontend:

```bash
cd web
npm install
npm run typecheck
npm run build
cd ..
```

Start FastAPI and let it serve `web/dist` from the same origin:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
export ROBOTOPS_GATEWAY=ros
export ROBOTOPS_RUNTIME_MODE=sim
export ROBOTOPS_WEB_DIST="$PWD/web/dist"
uvicorn robotops_backend.app:app --app-dir backend --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/
```

Then repeat the web validation checklist from the previous section.

Do **not** use `--host 0.0.0.0` on an untrusted network at this stage. Authentication, authorization and hardened remote access are not implemented yet.

## 16. CI-equivalent checks

The source of truth is `.github/workflows/ci.yml`.

Before a major milestone is accepted, verify locally where practical and then let GitHub Actions run:

- portable formatting/lint/tests;
- frontend typecheck/build;
- Jazzy mock suite;
- Gazebo control/shutdown suite;
- mapping suite;
- navigation suite;
- mission suite;
- experiment suite.

Do not mark a red CI job as accepted merely because a different machine passed once.

## 17. Known limitations / open reliability items

Keep these visible:

- the historical Gazebo shutdown deadlock was repaired and regression-tested, but repeated simulator startup/shutdown remains worth monitoring;
- an intermittent middleware/mission response timeout was previously observed and is not considered fully explained;
- frontend dependencies/build still need verification on your normal development machine if they have not already completed there;
- public-network authentication/authorization is not implemented;
- replay UI/backend implementation is not complete;
- server-side persistence/history is not complete; the current plan is SQLite first behind a persistence abstraction, with PostgreSQL later if deployment needs it;
- physical hardware mode is not implemented.

## 18. Acceptance checklist before deleting an older source copy

Only consider the new source archive your working baseline after you can answer **yes** to all applicable items:

- [ ] archive extracts cleanly;
- [ ] `AGENTS.md`, project docs, ROS sources, backend and web sources are present;
- [ ] portable lint/tests pass;
- [ ] ROS workspace builds;
- [ ] normal colcon tests pass;
- [ ] Gazebo shutdown/system tests pass;
- [ ] mapping/localization test passes;
- [ ] navigation test passes for both profiles;
- [ ] mission/recording test passes;
- [ ] experiment test passes;
- [ ] backend tests pass;
- [ ] `npm run typecheck` passes;
- [ ] `npm run build` passes;
- [ ] development UI shows live map/pose/LiDAR correctly;
- [ ] production build is served locally through FastAPI and works;
- [ ] any personal maps/recordings/artifacts from the old folder are backed up;
- [ ] any Git history from the old folder is preserved separately if needed.

After that, you may remove the old **source copy** if you want, but keep a proper Git remote or backup. Do not rely on one ZIP as the only copy of the project.

## Current Milestone 8D acceptance checks

These checks are the current high-value acceptance path after baseline cleanup and RViz integration. They supplement the historical package/system test sections above.

### A. Portable regression

From the repository root:

```bash
git status --short
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/python -m pytest -q backend/tests

cd web
npm run typecheck
npm run build
cd ..
```

The RViz-integration checkpoint produced 39 passing backend tests. If the count changes because tests are added, require zero unexplained failures rather than matching an old number blindly.

### B. RViz engineering view

Inside the sourced Jazzy workspace, rebuild `robot_navigation` when RViz configs/launch files change:

```bash
cd ros2_ws
colcon build --packages-select robot_navigation
source install/setup.bash
```

Then verify both paths:

1. Start Navigation with **Open RViz engineering view when the stack starts** enabled.
2. Start Navigation without it, then click **Open RViz** while the stack is already running.

Expected RViz data includes RobotModel, map, scan, TF and `/plan` during navigation. Closing RViz must not stop Nav2/Gazebo. Stopping RobotOps should close a RobotOps-owned RViz process.

### C. Three-view navigation sanity check

For a manual mission compare:

```text
Gazebo physical simulation
<-> RViz ROS representation
<-> RobotOps web representation
```

Check approximate robot position/orientation, map alignment, LiDAR alignment and path behavior. This is an engineering sanity check, not yet the independent Validation Integrity verdict.

### D. Minimal automated-campaign diagnostic before backend refactor

Do not begin the large campaign migration until the current restart-per-trial behavior is understood. Run:

- one profile: `navfn_rpp`;
- one repetition;
- known-good saved map;
- two or three easy waypoints;
- about 180 seconds trial timeout.

Wait until the campaign reaches mission submission/acceptance. Then record:

```text
Gazebo:   MOVING / NOT MOVING
RViz:     MOVING / NOT MOVING
RobotOps: MOVING / NOT MOVING
```

Interpretation:

- Gazebo+RViz move, RobotOps does not -> WebSocket/telemetry/rendering path.
- Gazebo moves, RViz+RobotOps do not -> ROS TF/localization/telemetry freshness/reconnection.
- Gazebo does not move -> readiness/orchestration/mission path.

Also inspect whether readiness can become true from stale AMCL/TF state after a restart. Require fresh current-trial evidence rather than only transform existence.

### E. Cyclone DDS full-system policy

Use the verified full-stack profile:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
```

The user has rerun `experiment_system` in the Jazzy environment and observed a pass. Do not claim all heavy ROS suites passed after every new patch unless their current outputs are available.

## Future shareable-demo testing boundary

When the simulation-only hosted demo milestone is implemented, add tests for session ownership/lease expiry, clean simulator reset, authorization boundaries, resource limits, and explicit rejection of physical-robot/generic-ROS access. Do not expose the current unauthenticated local service directly to an untrusted network.

## Gateway readiness scheduling regression (2026-10-10)

Readiness service clients have their own callback group so cached-map sensor
processing cannot exclude their responses. TF/AMCL freshness criteria are unchanged.
Control-center polling prevents overlapping background refreshes and invalidates
results superseded by its control actions.

Inside Jazzy, source /opt/ros/jazzy/setup.bash and ros2_ws/install/setup.bash.
Run the focused ROS test using a test-only domain:

    ROS_DOMAIN_ID=88 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST .venv/bin/python -m pytest -q backend/tests/test_ros_gateway_callbacks.py

Then run npm test, npm run typecheck and npm run build from web/.
The test-only domain prevents local AMCL/manager service stubs from colliding
with live services. This test needs ROS and built interfaces, but no Gazebo or
external Nav2. Portable tests skip it when ROS is unavailable; the Jazzy CI mock
job runs it explicitly.


### Coordinated navigation lifecycle checkpoint (2026-10-10)

Current default uses Nav2's shipped valid-path/recovery BT with original RPP and
SimpleGoalChecker. See `coordinated-navigation-repair-20261010.md` before comparing
older periodic-replanning campaign timings. Requalify changed active goals and
physical obstacle-triggered replanning, not just single-goal success.

Registered navigation_system now contains four cases across both profiles,
including valid-path retention, spawned Gazebo obstacle, preemption, final pose
and contact checks. navigation_launch_validation also rejects absent/directory
BT paths before process creation. Backend fast tests include an actual owned
process-tree regression proving ROS launch forwards initial SIGINT to children
once. Preserve wrapped-Xvfb lifetime and bounded group escalation.

RViz manual animation/integration is user-verified on 2026-10-10. Keep RViz off
for benchmark resource measurements. Three paired valid-path campaigns pass the
local opt-in isolated-fault gate; the separate replay/default CPU target is still
unmet. Diagnostics stay false. Historical failures remain historical evidence.


### Isolated sensor-fault checkpoint (2026-10-10)

`fault_injection` is standalone and opt-in; no production scan or campaign schema
changes. Follow its package README in an isolated ROS domain. Registered tests
cover six native policy cases and 25 ROS component/MCAP cases, including actual
diagnostic detection/recovery, serialized payloads, mode/clock/config guards,
hashed evidence, force-kill incompleteness and MCAP round trip.

Build from `ros2_ws`; run `colcon test --packages-select fault_injection
--return-code-on-test-failure`. The <=5% one-core/32 MiB isolated relay gate passes
with 1000 Hz clock/10 Hz 720-ray scans. Do not infer combined robot/campaign
overhead from this result. See `sensor-fault-adapter-20261010.md`. Explicit arming
after mission acceptance is the next prerequisite before production wiring; the
standalone first-clock schedule must not run faults during preparation.
