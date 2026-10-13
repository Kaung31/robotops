# RobotOps

[![CI](https://github.com/Kaung31/robotops/actions/workflows/ci.yml/badge.svg)](https://github.com/Kaung31/robotops/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Regression testing and evidence for robot navigation, built on ROS 2 Jazzy,
Gazebo Harmonic and Nav2.

Run the same mission many times, across Nav2 configurations, and get a result
you can check: whether ROS reported success, how far the robot's localized final
pose was from the goal, and whether Gazebo saw it touch anything. The same software runs against
mock hardware and Gazebo through `ros2_control`; a physical robot is planned.

**What works today:** SLAM mapping, AMCL localization, two Nav2 profiles
(NavFn + Regulated Pure Pursuit, Smac 2D + DWB), multi-waypoint missions with
MCAP recording, backend-owned experiment campaigns with SQLite history and crash
recovery, final-pose validation, Gazebo contact evidence, versioned reports, a
React/Three.js dashboard and a separate static Recorded Lab.
See [current status](docs/CURRENT_STATUS.md).

**Latest result:** [warehouse benchmark v1](docs/WAREHOUSE_BENCHMARK.md) (exploratory).
Both Nav2 configurations completed a 28 m, five-goal warehouse mission 3/3 times
with verified final pose and no observed contact. Smac 2D + DWB was ~3.6% faster;
NavFn + RPP finished with a much tighter heading (≈3° vs ≈11°). **Neither entered
the 1.2 m aisles between the racks; both drove around the rack block, so v1 shows
no narrow-aisle navigation capability.**

**Historical configuration boundary:** W01–W06 are bound to the frozen matrix's
original raw configuration hashes. The reconstructed navigation YAML preserves
effective parameters but has different bytes and cannot replace those files in
the original matrix. A campaign using this checkout is a new run, not a reproduction
of W01–W06. See [reproduction limits](docs/WAREHOUSE_BENCHMARK.md#reproduce).

- [Architecture](docs/ARCHITECTURE.md) and [documentation index](docs/README.md)
- [Mapping](docs/MAPPING.md), [navigation](docs/NAVIGATION.md),
  [missions](docs/MISSIONS.md), [experiments](docs/EXPERIMENTS.md)
- [Web control center](docs/WEB_CONTROL_CENTER.md),
  [testing and runbook](docs/TESTING_AND_RUNBOOK.md)

## Build on Ubuntu 24.04 / ROS 2 Jazzy

Install [ROS 2 Jazzy](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html)
first (ROS base is sufficient). On this laptop, the existing Ubuntu 24.04
Distrobox container already provides Jazzy and colcon:

```bash
distrobox enter jazzy
cd ~/robotops_verified_source_v2/robotops
```

Run the following inside that container (or a native Ubuntu 24.04/Jazzy system),
from the repository root:

```bash
source /opt/ros/jazzy/setup.bash
# RobotOps' verified full-stack profile uses Cyclone DDS. ROS 2 Jazzy defaults
# to Fast DDS, but RobotOps observed an intermittent response-delivery race there.
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
sudo apt-get update
sudo apt-get install -y python3-colcon-common-extensions python3-rosdep liburdfdom-tools \
  ros-jazzy-rmw-cyclonedds-cpp
# Run once if rosdep has not been initialized on this machine:
# sudo rosdep init
rosdep update --rosdistro jazzy
rosdep install --from-paths ros2_ws/src --ignore-src --rosdistro jazzy -r -y
cd ros2_ws
colcon build --event-handlers console_direct+
source install/setup.bash
colcon test --event-handlers console_direct+ --return-code-on-test-failure
colcon test-result --verbose
```

The default build runs portable/package tests and mock integration. Enable the
separate headless Gazebo contract test explicitly:

```bash
# From ros2_ws after the normal build:
colcon build --packages-select robot_bringup --cmake-args -DROBOTOPS_SIM_TESTS=ON
source install/setup.bash
RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=87 \
  ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  colcon test --return-code-on-test-failure
colcon test-result --verbose
```

Set `ROBOTOPS_SIM_TESTS=OFF` in the same build command to return to mock-only
testing. Tests use a private Gazebo transport partition; use an unused ROS domain.


## Run mock or Gazebo

From `ros2_ws`, in a Jazzy terminal:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch robot_bringup robot.launch.py mode:=mock
# Or, in a separate session after stopping mock:
ros2 launch robot_bringup robot.launch.py mode:=sim sensors:=false
# Optional Gazebo GUI:
ros2 launch robot_bringup robot.launch.py mode:=sim gui:=true sensors:=false
```

These control-only examples disable sensors. See [mapping instructions](docs/MAPPING.md)
for the indoor world, sensor rendering, SLAM, saving and AMCL. Then use the
[navigation workflow](docs/NAVIGATION.md) to initialize localization and send
a Nav2 goal with `profile:=navfn_rpp` or `profile:=smac_dwb`.

Run only one session per ROS domain/Gazebo partition. Stop with Ctrl+C.
`real` and `replay` fail explicitly before robot processes start. This is local
simulation/testing software; no physical operation is implemented.

In another sourced terminal, verify readiness and send a stamped command through
the mux. For sim, set the command publisher's `use_sim_time` to true as shown;
use false for mock:

```bash
ros2 control list_controllers
ros2 topic pub --rate 20 /cmd_vel/test geometry_msgs/msg/TwistStamped \
  '{header: {stamp: now, frame_id: base_link}, twist: {linear: {x: 0.15}}}' --use-sim-time
```

Omit `--use-sim-time` for mock. Stop the publisher with Ctrl+C; the drive watchdog
stops stale input. `cmd_vel/teleop` has higher priority than `cmd_vel/test`, which
has higher priority than `cmd_vel/autonomy`. Never publish directly to
`drive_controller/cmd_vel`. See the control contract for limits and stop timing.

## Run the description preview

In a terminal with ROS and the workspace overlay sourced:

```bash
ros2 launch robot_description description.launch.py publish_preview_joint_states:=true
```

This publishes the description, fixed TF, and synthetic zero-position wheel
states. It does not move a robot. Omit `publish_preview_joint_states` when another
source provides `joint_states`; the default is false. Stop with Ctrl+C.

Optional visualization (install `ros-jazzy-rviz2`): run `rviz2`, set Fixed Frame to
`base_link`, add RobotModel using the `robot_description` topic and add TF.
No `map` or `odom` transform is fabricated for preview.

Configuration arguments:

- `geometry_file:=/absolute/path/to/geometry.yaml`: complete replacement for
  `ros2_ws/src/robot_description/config/geometry.yaml`.
- `use_sim_time:=true`: use an externally supplied ROS clock (none is started here).

Expand and validate installed resources from any working directory:

```bash
xacro "$(ros2 pkg prefix --share robot_description)/urdf/robot.urdf.xacro" -o /tmp/robotops.urdf
check_urdf /tmp/robotops.urdf
ros2 launch robot_description description.launch.py --show-args
```

## Portable checks (no ROS required)

From the repository root, with Python 3.12 and venv support:

Do not use a Python 3.13/3.14 virtual environment for the ROS-connected backend; ROS 2 Jazzy on Ubuntu 24.04 targets Python 3.12.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff format --check .
.venv/bin/ruff check .
find ros2_ws/src -type f \( -name '*.cpp' -o -name '*.hpp' \) \
  -exec .venv/bin/clang-format --dry-run --Werror {} +
.venv/bin/yamllint .
find ros2_ws/src -name CMakeLists.txt -exec .venv/bin/cmake-lint {} +
find ros2_ws/src -name CMakeLists.txt -exec .venv/bin/cmake-format --check {} +
.venv/bin/python -m pytest -q
# XML lint, when libxml2-utils is installed:
find ros2_ws/src -type f \( -name '*.xml' -o -name '*.xacro' -o -name '*.sdf' \) -exec xmllint --noout {} +
```

Use `ruff format .`, `clang-format -i` on C++ files and `cmake-format -i` on package CMakeLists.txt files
to format. The portable suite checks expanded model contracts and invalid input;
ROS launch tests are registered separately with CMake and run through colcon.
The C++ command guard is built with compiler warnings and GTest coverage through
colcon. The web frontend is TypeScript and is type-checked/built in its own CI job.
Scoped Python type checking is configured in `pyrightconfig.json`.

Ordinary pull-request CI has three jobs: Python/static checks, frontend tests and
builds, and a Jazzy build with an explicit passive package-test allowlist. These
jobs need no private recordings and start no ROS/Gazebo workloads. The separate
[robotics integration workflow](.github/workflows/robotics-integration.yml) is
manual-only; it retains mock, simulation, mapping, navigation, mission and experiment
suites. Opening a PR does not dispatch it. Local verification scope and outstanding
hosted validation are recorded in [the remediation report](docs/PUBLICATION_REMEDIATION_REPORT.md).

Portable tests use pinned PyPI Xacro; the ROS job uses Jazzy's Xacro. Keep a
portable venv deactivated when building/testing ROS. When running portable checks
from a ROS-sourced shell, unset `PYTHONPATH` first to avoid mixing ROS packages
into the isolated venv.

## License

RobotOps source is licensed under the [Apache License 2.0](LICENSE). See
[NOTICE](NOTICE) for third-party configuration attribution. Recorded experiments
and replay datasets are not part of the source release.

## Before publication

The package manifests still use a placeholder maintainer address. Source-only
publication excludes recordings and replay datasets; it does not deploy a live lab.

See the [Milestone 6 verification record](docs/plans/milestone-6.md) for current
build/test results. Hosted Actions and interactive GUI review are not verified.
The [Gazebo shutdown repair](docs/plans/gazebo-shutdown-repair.md) addresses a
captured signal-handler deadlock inside the simulation adapter. Strict shutdown
checks remain enabled. The archived Fast DDS baseline contains an intermittent response-delivery timeout where the mission goal was accepted and navigation started but the action client did not receive the goal response. RobotOps therefore uses Cyclone DDS as its verified automation/CI profile. Treat other RMW implementations as supported only after the full mission and experiment suites pass on that RMW.

## Current product direction

RobotOps is local-first but designed for a later simulation-only shareable demo. The
backend should own durable experiment truth. Use a persistence abstraction: SQLite is
the preferred first server-side store for local/demo use, while PostgreSQL remains a
later option if hosted concurrency or multi-user deployment requires it. Large MCAP
artifacts remain file/object references rather than database blobs.

RViz complements RobotOps rather than being embedded/reimplemented as the web product.
RobotOps may launch RViz as an optional engineering view; automated benchmark campaigns
keep RViz off by default so GUI load does not affect benchmark behavior.

## Run the Milestone 7B web control center

The normal local simulation workflow now starts only the RobotOps backend manually.
The browser then selects Mapping or Navigation and the backend starts only approved ROS
launch configurations. See [the full control-center guide](docs/WEB_CONTROL_CENTER.md).

From a sourced Jazzy/workspace shell at the repository root:

```bash
.venv/bin/python -m pip install -e ./backend
cd web
npm install
npm run typecheck
npm run build
cd ..

export ROBOTOPS_GATEWAY=ros
export ROBOTOPS_RUNTIME_MODE=sim
export ROBOTOPS_WEB_DIST="$PWD/web/dist"
export ROBOTOPS_USE_XVFB=true

.venv/bin/python -m uvicorn robotops_backend.app:app \
  --app-dir backend \
  --host 127.0.0.1 \
  --port 8000
```

Open `http://127.0.0.1:8000`. For normal Milestone 7B use, do not separately
launch Gazebo/Nav2: choose the workflow, world, saved map and Nav2 profile in the
control center and click **Start system**. Generated maps are discovered from
`artifacts/maps/`; managed process logs are written to `artifacts/logs/orchestrator/`.

This remains a localhost/trusted-network development service. Do not expose it to
an untrusted network or physical robot before authentication/authorization and
physical safety controls are implemented.
