# Milestone 4 recheck and shutdown repair

## Scope and gate

Rebuild and rerun all existing checks before Milestone 5. The first recheck on
2026-10-07 failed: 89 aggregate results, 2 errors and 3 failures (including CTest
wrappers). Mapping completed its assertions but Gazebo required SIGKILL during
teardown. The shared SLAM fixture for both navigation profiles crashed during
teardown with `context cannot be slept with because it's invalid`.

These failures block advancing the milestone; owner publication decisions do not.
Do not suppress teardown failures or claim a retry establishes reliability.

## Steps and files

1. Collect Gazebo shutdown diagnostics separately from mapping/navigation.
2. Add a narrow SLAM executable in `robot_navigation` using the installed upstream
   library. On SIGINT/SIGTERM, deactivate and clean up while the ROS context is
   valid, then destroy the node and shut down the context. Keep mapping algorithms,
   interfaces and configuration unchanged. Update CMake, manifest and map launch.
3. Add regression tests for active and unconfigured SLAM shutdown, including ROS
   simulated time. Preserve existing system teardown assertions.
4. Run build, formatting/lint, pure tests and full ROS tests. Document any
   unresolved Gazebo issue honestly before deciding whether to proceed.

## Success criteria

SLAM exits cleanly with workers stopped before context teardown. Mapping and both
navigation profiles pass including normal process shutdown, without weakening
assertions. No simulator-specific logic enters mapping or navigation code.

## Architectural decision

A small process entry point owns lifecycle shutdown; it links the distro's SLAM
Toolbox implementation rather than copying or modifying the SLAM algorithm.
This replaces the upstream executable only. Keep the existing no-bond workaround
until bond lifecycle behavior has separate verification.

## Verification and remaining gate (2026-10-07)

All five packages build in the Ubuntu 24.04 `jazzy` container. Installed versions:
SLAM Toolbox 2.8.5, gz_ros2_control 1.2.19, Gazebo Harmonic 8.11. The new executable
links the distro implementation; no dependency source or system library was patched.

Commands run from the repository (ROS commands inside the container after sourcing
`/opt/ros/jazzy/setup.bash` and, for tests, `ros2_ws/install/setup.bash`):

- `colcon build` in `ros2_ws`: all 5 packages passed.
- `xvfb-run -a colcon test --return-code-on-test-failure`: all 5 packages passed
  in 2 min 33 s after the repair, with mock, sim, mapping and navigation suites
  enabled in the build configuration.
- `colcon test-result`: **98 aggregate results, 0 errors, 0 failures, 0 skips**
  (includes CTest wrappers). Mapping and both navigation profiles passed their
  original motion, map, goal, cancellation, arbitration and shutdown assertions.
- Dedicated `colcon test --packages-select robot_navigation
  --return-code-on-test-failure --ctest-args -R slam_shutdown`: 8 new cases passed.
- `.venv/bin/python -m pytest -q`: **49 portable tests passed**.
- `ruff check .`, `ruff format --check .`, `yamllint .`, `cmake-lint`,
  `cmake-format --check`, `clang-format --dry-run --Werror`: passed on applicable
  repository sources. Container `xmllint --noout` passed on XML/Xacro/SDF files.
- `rosdep check --from-paths ros2_ws/src --ignore-src --rosdistro jazzy`: all
  declared system dependencies satisfied; Boost and TBB rosdep keys resolve.
- Installed `ros2 launch robot_navigation map.launch.py --show-args` from `/tmp`:
  passed.

Four isolated Gazebo startup/shutdown probes also exited normally. However,
**the original Gazebo shutdown hang has not been root-caused or fixed**. No Gazebo
adapter change was made, and the later successful suite cannot prove the
intermittent issue is gone. The diagnostic watcher did not catch another hang,
so there is no stack trace establishing its cause. Test failure checks remain
intact. Initial failure XML is retained locally under `/tmp/robotops-initial-audit/`;
these temporary diagnostic files are not repository artifacts.

**Milestone 5 is not started in this recheck.** Resolve or characterize the Gazebo
teardown failure before building mission/recording lifecycle guarantees on it.
The SLAM repair is independent of backend choice and adds no simulation branches,
new public topics or packages. The remaining no-bond limitation is unchanged.

Hosted GitHub Actions and interactive RViz/Gazebo appearance remain unverified.
License selection, maintainer email and repository URL are still owner decisions
before publication; none is needed to reproduce or investigate this local gate.

## Files changed in this recheck

- `README.md`: link the latest verification record.
- `docs/MAPPING.md`: explain SLAM signal/lifecycle ordering.
- `docs/plans/milestone-4-recheck.md`: audit, repair plan, evidence and open gate.
- `ros2_ws/src/robot_navigation/CMakeLists.txt`: build/install the entry point and
  register its default CI regression.
- `ros2_ws/src/robot_navigation/package.xml`: declare build/runtime dependencies.
- `ros2_ws/src/robot_navigation/launch/map.launch.py`: select the new entry point.
- `ros2_ws/src/robot_navigation/src/slam_runner.cpp`: orderly lifecycle shutdown.
- `ros2_ws/src/robot_navigation/test/slam_shutdown.py`: signal/state/clock coverage.

Additional regression: `ctest --repeat until-fail:5 -R '^slam_shutdown$'
--output-on-failure` passed all five repetitions (40 signal/state/clock cases,
45.1 seconds). This targets the repaired SLAM race; it is not evidence that the
separate Gazebo hang is fixed. Final process inspection found no running robot,
Gazebo, SLAM or Nav2 processes.


## Subsequent decision

The next recheck passed all 98 results again. Milestone 5 proceeds with explicit
failure handling and independent ROS action/recording tests; its plan supersedes
the blanket hold above. The Gazebo shutdown issue remains open and no assertion
has been weakened. See [Milestone 5](milestone-5.md) for scope and verification.
