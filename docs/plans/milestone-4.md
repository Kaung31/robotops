# Milestone 4 — Autonomous navigation

## Scope and gate

The user requested another audit and authorized the next milestone if no owner
input blocks progress. License, maintainer contact and Git remote remain
publication decisions. Recheck Milestone 3 before implementing this milestone.

Implement PROJECT_SPEC Milestone 4 only: Nav2 goal navigation on a saved map,
selectable planner/controller configurations, lifecycle management, and regression
coverage. Keep the existing ROS interfaces, mux, guard and watchdog. No missions,
recording, experiment framework, backend, UI, ML or physical hardware.

## Goals and success criteria

- Nav2 consumes standard scan, odometry and TF; no simulator-specific logic in
  navigation nodes/configuration. Map server/AMCL remain the fixed-map workflow.
- Two explicit profiles select different planner/controller plugin combinations:
  NavFn + Regulated Pure Pursuit, and Smac 2D + DWB. Profile selection and invalid
  map input fail before any processes start. No unused ROS packages are created.
- Stamped commands from Nav2 route only through `cmd_vel/autonomy`, then the
  established mux/guard/controller. Teleop still takes precedence. Cancellation
  and navigation shutdown stop the robot. Unknown space is not traversable.
- Local/global costmaps use actual LiDAR and a conservative footprint derived
  from the same geometry as the robot. One owner per TF edge is preserved.
- Each profile reaches the same goal on the same saved map after a fresh robot
  start, with independent simulator motion/goal checks. Exercise cancellation,
  invalid/unreachable goal handling and command arbitration. Save map once per
  system-test invocation, reuse unchanged across profiles; do not benchmark SLAM.
- All previous tests, applicable lint, build and the new headless navigation
  tests pass. Document limitations and unverified GUI/hosted CI separately.

## Files/packages

Extend `robot_navigation` only:

- `config/navigation.yaml` and `config/profiles/*.yaml`: shared Nav2 parameters
  and two plugin configurations.
- `robot_navigation/navigation_config.py`: pure configuration composition and
  footprint derivation, with portable tests.
- `launch/navigation.launch.py`: map validation, existing localization launch,
  only required Nav2 servers and lifecycle manager, installed resources.
- `test/navigation_launch_validation.py`, `test/navigation_system.py`: launch
  validation and end-to-end goal/cancel/control tests.
- Extend existing test support minimally to reuse simulator setup/map generation.
- Update package manifest/CMake, RViz view, CI, README and navigation docs.

## Implementation steps

1. [x] Audit Milestone 3 with full local build/test/lint.
2. [x] Implement shared costmaps/control contract and both configuration profiles.
3. [x] Compose localization + Nav2 with explicit lifecycle management and command
   remapping. Keep base bringup independent.
4. [x] Add pure/launch validation tests and run first live navigation proof.
5. [x] Verify both profiles on one map, cancellation/stopping/arbitration and
   invalid-goal behavior; rerun affected tests after fixes.
6. [x] Update docs/CI and run final configured build, lint and regression checks.

## Decisions and evidence

- Used installed Jazzy packages and upstream Jazzy source to verify stamped
  controller/recovery commands retain a current timestamp and `base_link` frame.
  Explicitly enabled `enable_stamped_cmd_vel`; no command-restamping adapter.
- Reused the existing `robot_navigation` package and localization launch. Only
  planner, controller, behavior server and NavigateToPose BT navigator are added;
  no generic full Nav2 bringup (docking/routes/waypoint services) is started.
- Both profiles use a conservative circular footprint derived from robot geometry,
  shared costmaps and the same mux/guard path. Profile differences are YAML.
- Costmap child namespaces initially resolved scan/map to private topics. Fixed
  composition remapping to the parent namespace's interfaces; live tests verify
  actual costmap subscribers on the shared scan/map topics.
- Test fixtures reuse one actual SLAM-produced map across fresh navigation
  sessions. Map generation uses domain 94, profiles 95 and 96, with unique Gazebo
  partitions. A rapid same-domain restart during development showed a Fast DDS
  controller parameter-response timeout; isolated test domains avoid discovery
  carryover between trials. No middleware setting is silently changed.
- One development run required forced termination of Gazebo during sensor
  teardown. Subsequent completed runs exited cleanly. This intermittent upstream
  shutdown behavior is not claimed fixed; tests explicitly reject forced child
  exits, so it remains visible if it recurs. The existing software GLX renderer
  and SLAM bond workaround are unchanged.

## File inventory

New files (under `ros2_ws/src/robot_navigation/` unless specified):

- `config/navigation.yaml`
- `config/profiles/navfn_rpp.yaml`, `config/profiles/smac_dwb.yaml`
- `robot_navigation/navigation_config.py`
- `launch/navigation.launch.py`
- `test/test_navigation_configuration.py`
- `test/navigation_launch_validation.py`, `test/navigation_system.py`
- Repository docs: `docs/NAVIGATION.md`, `docs/plans/milestone-4.md`

Updated:

- Package `CMakeLists.txt`, `package.xml`, `rviz/mapping.rviz`
- `test/mapping_system.py`: reusable map fixture/launch command hook, explicit
  per-session ROS domain and unique Gazebo partition; original assertions retained
- `.github/workflows/ci.yml`, `README.md`, `docs/MAPPING.md`,
  `docs/CONTROL_CONTRACT.md`, `docs/plans/milestone-3.md`

No new ROS package, custom interface or architecture change was necessary.

## Verification

Validated on the existing Ubuntu 24.04.4/Jazzy container with Gazebo Harmonic
and Xvfb/software GLX. No further system dependency installation was needed.

Commands/results:

- `rosdep check --from-paths src --ignore-src --rosdistro jazzy`: satisfied.
- `colcon build`: all **five packages** built successfully. No new ROS package.
- Enabled `ROBOTOPS_NAVIGATION_TESTS=ON` on `robot_navigation`; previous
  `ROBOTOPS_MAPPING_TESTS=ON` and `ROBOTOPS_SIM_TESTS=ON` remained enabled.
- Final `PYTEST_ADDOPTS=-s xvfb-run -a colcon test
  --return-code-on-test-failure`: all packages passed in about 2 min 24 s.
- `colcon test-result`: **89 results, 0 errors, 0 failures, 0 skips**, including
  CTest wrappers. Existing description, C++ guard, mock/sim and mapping tests
  all passed in that same final run.
- Navigation system test: **both profiles passed**, about 77.5 s including one
  SLAM map-production fixture and independent robot restarts. Both reject an
  actual occupied map cell and an out-of-map goal, accept/cancel goals, honor
  teleop override, reach the same free-space goal, and stop when navigation is
  shut down during a goal. YAML/image hashes and the localization map stay fixed.
- Final observed goal errors against independent simulator truth:
  `navfn_rpp`: **0.136 m, 0.026 rad**; `smac_dwb`: **0.175 m, 0.173 rad**.
  Thresholds are <0.35 m and <0.4 rad. These single-scenario observations are
  regression evidence, not a comparative navigation benchmark.
- Final mapping regression: **0.026 m, -0.114 rad** AMCL error, clean shutdown.
- `.venv/bin/python -m pytest -q`: **49 passed** without ROS. The 10 new pure
  navigation cases also passed under the pinned Python 3.12 container venv.
- `ruff check .`, `ruff format --check .`, `yamllint .`, `cmake-lint`,
  `cmake-format --check`, `clang-format --dry-run --Werror`, and container
  `xmllint --noout` on XML/Xacro/SDF: passed on applicable source files.
- Installed `ros2 launch robot_navigation navigation.launch.py --show-args`
  passed from `/tmp`. System tests used installed launch/config resources.
- Checked cleanup after the final run: no robot, Gazebo, SLAM or Nav2 process
  remains running. Generated maps stay in temporary test directories.

CI includes a separate opt-in navigation job. Hosted execution was not possible
without a repository/remote; neither hosted CI nor interactive GUI appearance is
claimed verified. Files remain local and uncommitted. The upstream intermittent
shutdown/restart observations above remain documented; the final suite required
no retries or suppressed failures.


## Owner actions and remaining scope

No owner input is required for local implementation/testing. License, maintainer
email and repository URL still need decisions before public distribution.
Interactive RViz/Gazebo appearance and hosted Actions remain unverified. These
are simulation regression checks in one small world, not robust navigation
benchmarks or physical-operation validation. Mock hardware has no perception
source, so autonomous navigation there would need an independent scan/localization
provider; the shared control path is already mock-tested.

Before Milestone 5, keep cancellation and command arbitration explicit in the
mission manager; teleop priority alone does not cancel an autonomous goal. Review
localization initialization and the recorded upstream restart/shutdown limitations.

