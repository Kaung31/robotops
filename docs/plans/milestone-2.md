# Milestone 2 — Hardware abstraction

## Goal and authorization

The user requested a second check of Milestone 1 and authorized proceeding to the
next milestone if no prerequisite needed their intervention. Rebuilt/retested
Milestone 1 in the existing Ubuntu 24.04/Jazzy Distrobox: passed (20 aggregate
results, zero failures). Licensing/contact/remote choices are publication tasks,
not blockers for local development.

Implement the PROJECT_SPEC Milestone 2 only: ros2_control, mock hardware, Gazebo
Harmonic, and proof that the same high-level control path works on both. No Nav2,
SLAM, mapping, application services, fault injection, experiments, or real drivers.

## Packages and files

- Extend `robot_description`: reusable robot geometry macro and backend-neutral
  wheel ros2_control interface fragment; preserve description-only entry point.
- `robot_control`: shared controllers, command arbitration configuration and a
  C++ command-validation guard with unit tests.
- `robot_bringup`: validated runtime mode selection, mock composition, common
  controller startup and backend-independent tests.
- `robot_simulation`: Gazebo-only model wrapper, launch, clock bridge, contact
  settings, and a small original flat test world. This adapter package is needed
  to isolate Gazebo dependencies from shared description/control code.
- Documentation: control/topic contract, setup/run commands and review items.
- CI: retain portable checks and mock tests on PRs; put headless Gazebo tests in
  a separate job. No empty future packages.

## Implementation stages and tests

1. [x] Re-read source-of-truth docs and rerun Milestone 1 gate.
2. [x] Define identical wheel velocity command and position/velocity state
   interfaces, shared geometry-derived controller parameters, closed-loop
   encoder odometry, one TF owner, explicit source arbitration and timeout.
3. [x] Implement mock launch with GenericSystem dynamics and controller lifecycle
   startup. Reject unsupported real/replay modes before starting any processes.
4. [x] Implement Gazebo adapter using gz_ros2_control and a headless test world.
5. [x] Run the same ROS contract test against both modes: active controllers and
   claimed interfaces, stamped commands, wheel states, forward/turn odometry,
   command arbitration, stale-input stop, single odom TF owner and clean shutdown.
6. [x] Test configurations/model interfaces and failure cases; run build, portable
   format/lint/unit checks and all relevant ROS tests on Ubuntu 24.04/Jazzy.
7. [x] Update README/contracts/CI and record evidence, limitations, review items.

## Success criteria

- `ros2 launch robot_bringup robot.launch.py mode:=mock` and `mode:=sim` work.
- Same joints, controllers, command topics/types and odometry/TF across backends.
- All final drive commands pass through explicit arbitration; stale commands stop.
- Only adapters/composition select backends; shared control has no mode branching.
- Mock integrates commanded velocity into position; sim uses physical joint state.
- Headless sim demonstrates actual model translation/rotation, not only spinning
  wheels or fabricated odometry. No claim of navigation/sensor completeness.
- Real/replay modes fail clearly until their dedicated implementations exist.
- Reproducible test output and limitations are recorded; no generated data in Git.

## Decisions and discoveries

- Existing `jazzy` container already has Gazebo Harmonic 8.11.0, gz_ros2_control,
  controller_manager and ros2_controllers; use it for development.
- Nominal Milestone 1 geometry remains the starting design, subject to contact
  validation. Licensing, maintainer email and Git remote remain owner decisions.

- The simulator required an explicit gz_ros2_control plugin search path; added
  package-prefix lookup in the simulation adapter instead of global shell setup.
- `twist_mux` 4.5.0 was installed after updating stale apt metadata inside the
  existing container. The manifest requires >=4.5.0 for stamped-mode fixes.
- Review found that controller watchdog age is computed from message stamps.
  Added a backend-independent C++ guard so future timestamps cannot defer stopping.
  Invalid/stale/non-planar/non-finite commands request zero; tests exercise the
  same guard on both backends.

## Verification

Final validation on 2026-10-07 in the existing Ubuntu 24.04.4/Jazzy container:

- `rosdep check --from-paths ros2_ws/src --ignore-src --rosdistro jazzy`: all
  dependencies satisfied. Installed only `ros-jazzy-twist-mux` and its message
  dependency, using the user's authorization for required tooling.
- `colcon build`: all four packages passed, including C++ compilation with
  `-Wall -Wextra -Wpedantic`. Enabled sim test registration with
  `colcon build --packages-select robot_bringup --cmake-args -DROBOTOPS_SIM_TESTS=ON`.
- `ROS_DOMAIN_ID=87 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST colcon test
  --return-code-on-test-failure`: passed. `colcon test-result --verbose` reports
  **50 results, zero errors/failures/skips**. This aggregate includes CTest wrappers:
  27 portable cases, four unsupported-mode cases, five C++ validation cases,
  and integration/shutdown cases for description, mock, and sim.
- Mock and sim both pass active-controller/interface checks, joint feedback,
  forward/turn odometry, single output publisher, teleop priority and expiry,
  stale-stream stop, rejection of stale/future/NaN commands, TF and zero-exit
  shutdown. Sim additionally passes model translation and yaw checks using
  independent Gazebo truth, not encoder odometry alone.
- `.venv/bin/python -m pytest -q`: 27 passed without ROS.
- Ruff format/check, yamllint, cmake-format/check, cmake-lint, and clang-format
  dry-run/Werror on all applicable source files: passed.
- Expanded all three installed model entry points from `/tmp` and parsed them
  with `check_urdf`: passed. The sim parse used a placeholder controller-file path
  because the parser does not start plugins; live sim tests used the actual
  generated controller configuration.
- `xmllint --noout` on XML/Xacro/SDF and installed launch `--show-args`: passed.
- GitHub Actions now separates mock/package and headless-sim jobs, and adds C++
  formatting plus compiler/GTest coverage. Hosted execution is not claimed.

Observed limitations: the container cannot enable FIFO real-time scheduling;
no hard-real-time performance claim is made. The installed controller manager's
`pal_statistics` publisher logs a context-invalid error during mock shutdown;
all processes still return zero and hardware/controllers deactivate. Gazebo
also logs startup/statistics and controller-period warnings; 100 Hz control over
1 kHz physics is intentional. No application or test failure is suppressed.
Interactive Gazebo/RViz visual inspection and hosted GitHub Actions remain
unverified. No Git repository/remote exists, so changes are local and uncommitted.
The container remains available; no robot or simulator session is left running.

## Owner actions

No action is required to continue local milestone development. Before public
publication, choose a license, replace the placeholder maintainer email, and
choose/configure a Git remote. Optional: inspect the robot with Gazebo/RViz and
provide preferred dimensions/appearance; nominal geometry is already validated
for the current flat-world control test.

## Follow-up audit before Milestone 3

At the user's request, inspected command validation, controller configuration,
backend boundaries, lifecycle startup/shutdown and the common control test again.
Rebuilt all four packages and reran the complete suite: 50 results, zero
errors/failures/skips. Ruff, YAML, CMake and C++ format checks passed. Existing
limitations remain documented above; no new blocking defect was found.
