# Milestone 3 — Mapping and localization

## Gate and scope

The user authorized continued development if publication decisions do not block it,
while requesting another Milestone 2 audit. The existing four-package Jazzy build,
50 aggregate colcon results and all configured lint/format checks passed again.
The license/contact/remote choices do not block local work.

Implement PROJECT_SPEC Milestone 3 only: custom Gazebo world, standard simulated
LiDAR/IMU, SLAM Toolbox live mapping, occupancy-map saving/loading, and AMCL
localization on a fixed saved map. No planner/controller server, autonomous goals,
mission manager, web platform, physical drivers, or ML.

## Files and boundaries

- `robot_simulation`: isolated LiDAR/IMU SDF extensions, transport mappings,
  rendering systems, and a custom asymmetric indoor mapping laboratory.
- `robot_bringup`: pass simulator environment selection through composition,
  preserving default control-pad behavior and existing command interfaces.
- `robot_navigation`: shared mapping/localization launch and configuration,
  explicit exclusive workflow selection, saved-map validation, RViz configuration,
  pure tests and a mapping-save-restart-localization system test.
- Docs: mapping/localization instructions, frame/sensor/QoS contract and validation.
- CI: separate opt-in headless mapping job with software rendering; retain fast
  unit/mock jobs and the existing headless control test.

## Implementation stages

1. [x] Audit Milestone 2; rerun build/tests/lint without failures.
2. [x] Add real Gazebo-generated LaserScan/Imu data with correct sensor frames,
   timestamps, deliberate QoS, and a custom indoor world with documented geometry.
3. [x] Add backend-independent SLAM and saved-map/AMCL lifecycle configuration.
   Select exactly one map->odom publisher within the launch. Validate map input
   before launching localization; missing or invalid input must fail clearly.
4. [x] Demonstrate live occupancy updates while commanding the existing mux path;
   save an actual SLAM-produced occupancy image/YAML outside the source tree.
5. [x] Restart the robot session, load that saved map, initialize AMCL, and verify
   localization while moving; compare estimated pose with independent sim truth.
6. [x] Add/run regression checks, retain Milestone 1/2 tests, update CI and docs.

## Success criteria and tests

- Scan/IMU have correct frame IDs, advancing ROS timestamps and expected data;
  scan returns reflect known walls and TF resolves at scan times.
- Live `/map` contains occupied/free cells and updates with motion; SLAM owns
  `map -> odom`, drive controller alone owns `odom -> base_link`.
- Map saver outputs valid YAML/image; a new localization session loads the same
  saved occupancy data. No tutorial map or hand-authored occupancy grid is used
  as evidence of SLAM mapping.
- AMCL and map server activate; AMCL owns `map -> odom` and SLAM is absent.
  The estimated map-frame robot pose stays close to simulator ground truth while
  moving, and localization leaves the saved map and published grid unchanged.
- Invalid workflow/missing/malformed map tests pass. Package build, portable lint,
  pure tests, C++ guard tests, mock/sim control tests and end-to-end map test pass
  on Ubuntu 24.04/Jazzy. GUI verification is stated separately if unavailable.

## Decisions

- Mapping and localization nodes subscribe only to ROS interfaces and know nothing
  about Gazebo. Their launch is separate from base bringup, with explicit ROS-time
  selection. A single workflow switch selects SLAM OR map_server/AMCL.
- The map test uses a dedicated ROS domain and Gazebo partition, temporary outputs,
  and full shutdown/restart between map production and consumption.
- GPU LiDAR requires Gazebo's rendering sensor system; headless tests use Xvfb/GLX/Mesa
  software rendering. EGL is available as an adapter launch option. No synthetic scan publisher.

- On this laptop, Ogre's EGL enumeration segfaulted in Mesa while probing the
  exposed NVIDIA device, including with `LIBGL_ALWAYS_SOFTWARE=1`. The test uses
  Xvfb, `headless_rendering:=false`, and process-local
  `__EGL_VENDOR_LIBRARY_FILENAMES=/dev/null`; no driver/system configuration was
  changed. Normal EGL-capable systems can use the default headless renderer.
- Jazzy SLAM Toolbox aborted while destroying its lifecycle bond after ROS
  context shutdown. Mapping disables that bond while retaining manager-driven
  configure/activate transitions and launch process-exit supervision. AMCL and
  map_server retain bonds. Hung-SLAM detection is a remaining limitation.
- Sensor drivers remain separate standard ROS publishers; IMU fusion is deferred.
  The neutral robot description and shared controller interfaces are unchanged.
- Tests check TF publisher node identities and uniqueness of nodes; they do not
  equate TF endpoint count with transform ownership (SLAM has multiple endpoints).

## File inventory for this milestone

New:

- `docs/plans/milestone-3.md`, `docs/MAPPING.md`
- `ros2_ws/src/robot_simulation/worlds/mapping_lab.sdf`
- `ros2_ws/src/robot_navigation/CMakeLists.txt`, `package.xml`
- `robot_navigation/config/slam.yaml`, `config/localization.yaml`
- `robot_navigation/launch/map.launch.py`, `rviz/mapping.rviz`
- `robot_navigation/robot_navigation/__init__.py`, `map_config.py`
- `robot_navigation/test/test_map_configuration.py`, `map_launch_validation.py`,
  `mapping_system.py`

The shortened `robot_navigation/` paths above are under `ros2_ws/src/`.

Updated:

- `.github/workflows/ci.yml`, `.gitignore`, `pyproject.toml`, `README.md`
- `docs/FRAME_CONTRACT.md`, `docs/plans/milestone-2.md` (follow-up audit)
- `ros2_ws/src/robot_bringup/launch/robot.launch.py`, `test/control_launch.py`
- `ros2_ws/src/robot_simulation/package.xml`, `config/bridge.yaml`,
  `launch/gazebo.launch.py`, `urdf/gazebo.urdf.xacro`, `worlds/control_pad.sdf`

`AGENTS.md`, `PROJECT_SPEC.md` and `ARCHITECTURE.md` remain the source of truth;
no architecture change was needed.

## Verification

Validated in the existing `jazzy` Ubuntu 24.04.4 container with ROS 2 Jazzy,
Gazebo Harmonic 8.11 and Mesa software rendering. Installed Xvfb/xauth/mesa-utils
for rendering diagnosis/testing; Docker was unnecessary because Distrobox/Podman
already provided the target environment.

- `rosdep check --from-paths ros2_ws/src --ignore-src --rosdistro jazzy`: satisfied.
- `colcon build --event-handlers console_direct+`: all five packages built.
  `ROBOTOPS_SIM_TESTS=ON` and `ROBOTOPS_MAPPING_TESTS=ON` were enabled for their
  respective package builds.
- `PYTEST_ADDOPTS=-s xvfb-run -a colcon test --return-code-on-test-failure
  --event-handlers console_direct+`: exercised all packages, including the
  Milestone 2 description/mock/sim and C++ regressions. After correcting the new
  test's assumptions about Jazzy TF metadata/endpoints, reran all navigation
  package tests with `PYTEST_ADDOPTS=-s xvfb-run -a colcon test
  --packages-select robot_navigation --return-code-on-test-failure`.
- Final `colcon test-result`: **70 results, zero errors/failures/skips**. The count
  includes CTest wrappers and is not 70 distinct behavior scenarios.
- End-to-end sensor/map/save/restart/localization test: passed in 28.73 seconds.
  Final observed AMCL error: **0.032 m**, **-0.120 rad** against independent
  simulator truth; assertions require <0.35 m and <0.25 rad. These are one test
  run's observations, not a navigation accuracy benchmark. Saved YAML/PGM and
  the localization occupancy grid were unchanged; child processes exited cleanly.
- `.venv/bin/python -m pytest -q`: **39 passed** on the host. The same pinned
  portable environment on Python 3.12 inside Jazzy also passed all 39 cases.
- `ruff format --check .`, `ruff check .`, `yamllint .`, `cmake-lint`,
  `cmake-format --check` and `clang-format --dry-run --Werror`: passed on all
  relevant source files. `xmllint --noout` passed on XML/Xacro/SDF inside Jazzy
  (xmllint is not installed on the host).
- Installed neutral Xacro expanded and passed `check_urdf` from `/tmp`; installed
  mapping launch `--show-args` passed. ROS tests ran against installed launch,
  configuration and resource files, not a source-directory-only setup.
- Checked process cleanup: no robot/Gazebo/SLAM/AMCL processes remain running.

Not verified: interactive Gazebo/RViz appearance, hardware-accelerated EGL on
this laptop, hosted GitHub Actions, broad localization robustness or autonomous
navigation. The tested GLX fallback is documented in `docs/MAPPING.md`. The
existing Milestone 2 upstream scheduling/statistics warnings remain applicable.
No code was committed or published: the directory still has no Git metadata or
remote. Generated maps remain temporary test artifacts.

## Owner actions and next review

Nothing is required from the owner to build or test locally. Before publishing,
provide the intended license, maintainer email and GitHub repository URL; the
placeholder contact and Proprietary designation remain unchanged.

Before Milestone 4, review the SLAM bond workaround/hung-process limitation,
manual initial-pose workflow and nominal robot/world geometry. Autonomous Nav2
must continue to use the existing `cmd_vel/autonomy` mux input and respect the
exclusive map/odom ownership contract. IMU fusion, multiple benchmark worlds and
physical operation remain later work.



## Follow-up audit before Milestone 4

Repeated the five-package build and complete enabled mock/sim/mapping suite at
the user's request: 70 results, no failures/errors/skips. Portable pytest
(39 cases), Ruff and YAML checks passed again. Reviewed the documented renderer
and SLAM bond limitations; neither requires an owner action for local Nav2 work.
