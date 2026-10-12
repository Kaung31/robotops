# Milestone 1 — Foundation

## Goals and scope

Build the smallest backend-independent ROS 2 Jazzy robot foundation, following
`AGENTS.md`, `docs/PROJECT_SPEC.md`, and `docs/ARCHITECTURE.md`. Define a
parameterized differential-drive URDF/Xacro and frame/control contracts without
implementing a control backend. Only `robot_description` is needed now.

Excluded: controllers, mock hardware, Gazebo, Nav2, SLAM/mapping, physical drivers,
application services/UI, experiments, faults, and ML.

## Files/packages to create

- `ros2_ws/src/robot_description/`: ament CMake package, manifest, installed Xacro
  and geometry configuration, description-only launch, model and ROS launch tests.
- `docs/FRAME_CONTRACT.md`: frame ownership, geometry conventions, future control
  interface, and preview limitations.
- Root `README.md`: scope, Jazzy dependency setup, build/test/preview commands.
- `.editorconfig`, `.gitignore`, `pyproject.toml`, `requirements-dev.txt`,
  `.yamllint.yaml`: small formatting/lint/test baseline.
- `.github/workflows/ci.yml`: portable model/lint checks and Ubuntu 24.04/Jazzy
  workspace build, package/launch tests, installed-resource check.

## Implementation steps

1. [x] Read source-of-truth docs; inspect repository and nested instructions.
2. [x] Define frame/control contracts and configurable primitive geometry.
3. [x] Implement and install one description package with a preview launch.
4. [x] Test expanded model structure, inertias, wheel geometry/axes, configuration
   overrides, invalid configuration, and ROS TF/joint-state publication.
5. [x] Add formatter/linter configuration, CI, and build/run instructions.
6. [x] Run available checks, review scope, and record verification limits here.

## Tests

- Expand Xacro with default and alternate geometry; reject invalid dimensions.
- Check a connected, acyclic, uniquely named URDF rooted at `base_link`;
  continuous wheel joints; fixed sensor mounts; positive physical inertias;
  wheel contact geometry, separation and rolling axes; no backend plugins.
- Parse expanded URDF with `check_urdf` in ROS CI.
- Launch installed description with ROS; check durable static TF for late
  subscribers, dynamic wheel TF from supplied joint states, optional preview
  joint states, namespace behavior, and `use_sim_time` parameter forwarding.
- Ruff format/check, yamllint, XML lint, CMake lint, pytest; colcon build/test
  and verbose test results in Jazzy CI.

## Success criteria

- Only the required description package exists; no empty future packages.
- Installed Xacro expands and URDF parser accepts the model.
- Geometry/configuration and documented TF ownership agree with tests.
- Preview can publish the description and fixed TF; synthetic wheel states are
  explicitly opt-in and never presented as ros2_control mock hardware.
- The future wheel contract is velocity commands and position/velocity states;
  no hardware plugin is selected or controller instantiated in this milestone.
- All locally available checks pass; unavailable ROS validation is explicitly
  recorded, with CI configured to perform it on the supported platform.

## Inspection findings and decisions

- Initial repository has only the three guidance documents; no nested AGENTS.md,
  existing packages, build tooling, or Git metadata.
- Host is Ubuntu 26.04, with no ROS installation, colcon, or Docker. Target remains
  Ubuntu 24.04/Jazzy. Follow-up inspection found the existing Podman/Distrobox
  `jazzy` container with Ubuntu 24.04.4, ROS Jazzy, colcon, and rosdep.
- Description preview stays in `robot_description`; `robot_bringup` will own
  runtime composition once controllers/backends are implemented in Milestone 2.
- `base_link` is a massless axle-center root, with chassis inertia on a fixed child
  to avoid KDL root-inertia limitations. World/odometry frames remain external.

## Verification record

Implemented the scoped foundation. Verification on 2026-10-07:

- `python3 -m venv .venv` and `.venv/bin/pip install -r requirements-dev.txt`: passed
  on host Python 3.14 (CI targets Python 3.12).
- `.venv/bin/ruff format --check .` and `.venv/bin/ruff check .`: passed.
- `.venv/bin/yamllint .`: passed.
- `.venv/bin/cmake-lint ros2_ws/src/robot_description/CMakeLists.txt` and
  `.venv/bin/cmake-format --check ros2_ws/src/robot_description/CMakeLists.txt`: passed.
- `.venv/bin/python -m pytest -q`: 16 passed. Includes a regression for CLI input
  paths relative to the working directory, and missing configuration keys/files.
- `.venv/bin/xacro ros2_ws/src/robot_description/urdf/robot.urdf.xacro
  -o /tmp/robotops-milestone-1.urdf`: passed.
- `check_urdf /tmp/robotops-milestone-1.urdf`: passed; seven links with `base_link`
  as root. `xmllint --noout` on the manifest and both Xacro files: passed.
  Native tools/dependencies were downloaded from Ubuntu packages and extracted
  beneath `/tmp/robotops-m1-tools` without a system install. `check_urdf` used
  that directory's `usr/lib/x86_64-linux-gnu` as `LD_LIBRARY_PATH`.
- `cmake -S ros2_ws/src/robot_description -B /tmp/robotops-m1-cmake`: blocked at
  `find_package(ament_cmake)` because ROS is absent. No package build is claimed.

### Ubuntu 24.04 / Jazzy container verification

After the user identified the installed container, entered it using
`distrobox enter jazzy`. No Docker installation or new ROS dependencies were
needed. Ran on Ubuntu 24.04.4 with Python 3.12.3, sourcing
`/opt/ros/jazzy/setup.bash` and the workspace overlay where required:

- `rosdep check --from-paths ros2_ws/src --ignore-src --rosdistro jazzy`: all
  dependencies satisfied.
- `colcon build --event-handlers console_direct+` from `ros2_ws`: passed,
  one package built and installed without symlinking source resources.
- `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_DOMAIN_ID=87 colcon test
  --event-handlers console_direct+ --return-code-on-test-failure`: passed.
  Both CTest entries passed: 16 model cases plus the ROS integration and
  post-shutdown cases. `colcon test-result --verbose` reported 20 tests, zero
  errors/failures/skips (the aggregate includes CTest wrapper results).
- From `/tmp`, expanded the installed Xacro via `ros2 pkg prefix --share
  robot_description` and ran `check_urdf`: passed.
- `ros2 launch robot_description description.launch.py --show-args`: passed,
  resolving the installed geometry configuration correctly.
- `xmllint --noout` on package XML/Xacro: passed.
- Re-ran the complete portable lint/format/pytest suite in an isolated Python 3.12
  venv inside the container, with `PYTHONPATH` unset to exclude ROS packages.
  Added explicit Ruff exclusions for colcon build/install/log output after the
  first post-build lint run correctly exposed generated-file scanning.

The earlier host-only build limitation is resolved. Remaining unverified items
are interactive RViz visualization and the actual hosted GitHub Actions run.
No Git metadata or remote exists, so no commit, push, or hosted CI run was
performed. The existing container was started and remains available; generated
workspace build/install/log directories are ignored development outputs.

## Review before Milestone 2

- Confirm nominal dimensions, masses, wheel separation and axle-centered frame.
  Validate caster contact/friction and stability in the future simulation adapter.
- Preserve joint names/axes and introduce velocity command plus position/velocity
  state interfaces behind ros2_control; keep perception drivers separate.
- Choose the odometry TF owner and command arbitration/watchdog policy before
  enabling motion. Do not enable preview joint states alongside a state broadcaster.
- Confirm the package maintainer email (`kai@example.com` is a placeholder) and
  license. `Proprietary` avoids granting a license without the owner's choice.
- No architecture deviation or additional runtime mode has been introduced.

## Follow-up review before Milestone 2

Rebuilt and reran Milestone 1 in Jazzy at the user's request: all 20 aggregate
results passed. No owner action blocked further local development. The user
authorized the next milestone, now recorded in `milestone-2.md`.
