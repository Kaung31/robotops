# Milestone 5 — Mission execution and recording

## Goals and scope

Execute an explicit ordered sequence of planar poses through Nav2, support action
cancellation, and persist run metadata, transitions, results and optional MCAP
telemetry. One mission owns this manager at a time. No experiment framework,
backend, frontend, replay player, faults, docking or new navigation algorithms.

## Prior milestone gate

A fresh full build/test on 2026-10-07 passed all 98 aggregate results. The earlier
Gazebo shutdown hang remains an open simulator reliability issue, not a fixed
bug. Revise the previous blanket hold: backend-independent mission/recording work
can proceed with deterministic ROS integration tests and explicit error outcomes.
Existing Gazebo tests retain strict teardown checks. A future passing simulation
run does not close that issue or establish repeatable experiment reliability.
Nothing requires owner input for local work.

## Packages and files

- `robotops_interfaces`: one `ExecuteMission` action. Standard geometry messages
  represent poses; the custom action is needed for mission/run IDs, artifact
  references, recording selection, progress and distinguishable failure outcomes.
- `mission_manager`: action server, small mission request validator, launch/config,
  ROS integration tests. Uses only Nav2 actions; publishes no velocity commands.
- `robot_recorder`: rosbag2 process ownership and artifact persistence library,
  topic/QoS configuration, pure artifact/config tests and MCAP integration checks.
- `docs/MISSIONS.md`, README, CI and this plan: contract, usage and verification.

## Implementation steps

1. Define the mission action and validate requests before reserving execution.
2. Implement exclusive UUID run directories, atomic JSON metadata/results and
   timestamped events; unknown software revision is explicit, never fabricated.
3. Start rosbag2 with MCAP and deliberate sensor/transient-local QoS. Confirm
   required subscriptions before sending any navigation goal. Finalize and check
   recording metadata on every terminal path; record failure overrides success.
4. Execute waypoints sequentially. Forward cancellation to the owned Nav2 goal,
   wait for its terminal result, and reject overlapping missions. If cancellation
   cannot be confirmed, report it and latch a fault rejecting future missions.
5. Preserve ROS time for goals/durations, use wall-time bounds for communications
   and cleanup, and handle shutdown with the ROS context alive. Replay/unsupported
   modes must reject mission startup; runtime selection stays in launch composition.
6. Verify against a controlled Nav2 action server (including failure modes), real
   rosbag2/MCAP, and an opt-in Gazebo/Nav2 mission. Update CI and documentation.

## Tests and success criteria

- Invalid/empty/non-finite/non-planar goals rejected; concurrent goal rejected.
- Successful ordered mission produces metadata, timestamps, events, result and
  a readable MCAP with required telemetry, including transient-local data.
- Nav2 rejection/abort, cancellation, recorder failure and missing dependencies
  never report success. Cancellation waits for Nav2; unavailable cancellation
  latches a fault. Shutdown cancels before recorder finalization.
- Recording disabled produces a valid run without a bag. Artifacts never overwrite
  another run, output paths are not derived from user labels, JSON disallows NaN.
- Same high-level code runs against controlled ROS tests and real Nav2; no Gazebo
  APIs or simulator mode branches in mission/recording logic.
- All available build, lint, pure and ROS tests pass; precise limitations recorded.

## Implemented contract and decisions

The three packages above are implemented; no other package was added. Missions
are ordered planar navigation poses with a per-mission recording option, not a
new behavior-tree language or an experiment runner. The custom action includes
run/artifact results that standard navigation actions cannot represent.

Cancellation forwards only to the owned Nav2 goal. Late acceptance is canceled;
unconfirmed termination latches a fault and rejects later missions. Restarting
requires checking that navigation has stopped. This does not claim an emergency
stop or prevent a separate teleop producer from operating. Recording failure
prevents a successful run result. Shutdown keeps ROS responses alive until
cancellation/finalization finishes. Runtime mode and configuration parameters are
read-only after startup, preventing metadata/configuration drift through ROS
parameter services.

Metadata has an immutable mission-definition hash, unique run ID, UTC/ROS timing,
configuration and recording references. Optional map YAML/image hashes record
operator-supplied provenance. Active Nav2 parameters are not inferred. Git revision
is explicitly null when unavailable; experiment IDs/faults are null at this stage.
See [MISSIONS.md](../MISSIONS.md) for the full action, artifact and failure contract.

## Hardening findings

- The recorded TF stream originally missed publishers when rosbag2 adapted its
  durability to the first discovered publisher. Explicit reliable/volatile
  dynamic-TF QoS now records AMCL, drive and wheel transforms; the MCAP test checks
  every edge of that moving frame chain and rejects incompatible-QoS warnings.
- Under recording/discovery load, Nav2's 20 ms action-acknowledgement limit caused
  a real goal failure. `robot_navigation/config/navigation.yaml` now uses a
  bounded 1000 ms limit, verified against the installed Jazzy BT API's millisecond
  units. Base command watchdog limits are unchanged.
- Cleanup tests caught action callbacks accessing destroyed ROS handles. A single
  ROS executor now serves callbacks while an explicitly owned orchestration
  worker performs blocking work and is joined before node destruction. Tests
  reject unretrieved callback exceptions, including delayed cancellation paths.
- Missions may arrive before the first clock sample. They now wait for clock/Nav2
  readiness with a wall-time bound. Accepted and execution-start timestamps are
  distinct; ROS duration stays null if execution never became ready. A missing-
  clock regression verifies that no navigation goal is sent.
- A failed acceptance response must not leave the manager busy forever. A bounded
  reservation timeout latches a fault; delayed execution cannot start navigation
  after that fault. Parameter services reject changes to startup mode/time/config.
- Recorder discovery tests use the production 15-second startup allowance;
  deliberately missing-dependency tests retain a short timeout. No failure checks
  or simulator shutdown assertions were removed to obtain passing results.

## Verification (2026-10-08)

Commands run inside the Ubuntu 24.04/Jazzy container source
`/opt/ros/jazzy/setup.bash` and `ros2_ws/install/setup.bash` as appropriate.

- The original five-package baseline passed all 98
  aggregate results before adding this milestone.
- `colcon build`: all eight packages build, including generated action interfaces.
- Latest full `xvfb-run -a colcon test --return-code-on-test-failure` finished in
  4 min 16 s. All Milestone 5 tests passed. `colcon test-result` reported 144
  aggregate results with 2 failure entries for one underlying failure (CTest
  wrapper plus pytest): Gazebo required SIGKILL during DWB test teardown after
  its navigation assertions passed. This is the previously tracked shutdown hang;
  the full run is **not** claimed green.
- Enabled options: `ROBOTOPS_SIM_TESTS=ON` on `robot_bringup`,
  `ROBOTOPS_MAPPING_TESTS=ON` and `ROBOTOPS_NAVIGATION_TESTS=ON` on
  `robot_navigation`, `ROBOTOPS_MISSION_SIM_TESTS=ON` on `mission_manager`.
- Controlled tests cover root/non-root namespaces, immutable configuration,
  success/overlap/invalid goals, rejection/abort, recorder loss, missing telemetry
  and time, paused time, late/refused cancellation, shutdown and lost acceptance.
- `.venv/bin/python -m pytest -q`: 73 portable tests passed.
- `ruff check .`, `ruff format --check .`, `yamllint .`, `cmake-lint`,
  `cmake-format --check`, `clang-format --dry-run --Werror`, and container
  `xmllint --noout` passed on applicable sources.
- `rosdep check --from-paths ros2_ws/src --ignore-src --rosdistro jazzy`: all
  dependencies satisfied. Installed action introspection and launch `--show-args`
  passed from `/tmp`. Actual installed `mission.launch.py mode:=mock` startup
  exposed the action and exited cleanly on SIGINT without a navigation server.

CI includes a separate opt-in recorded-mission simulator job; the default ROS job
runs controlled action/MCAP tests. The final M5 suite includes 13 controlled ROS
cases, three launch-rejection cases and the live two-waypoint mission. The live
mission recorded 28,175 messages (3,990,644 bytes), verified every required moving
TF edge, completed both poses, preserved the saved map, and stopped. Its 22.831 ROS
seconds are one regression observation, not a benchmark. Hosted Actions were not executed because
Git/remote are unconfigured. GUI appearance, replay and physical operation remain
unverified. The earlier intermittent Gazebo teardown and rapid-restart middleware
response issues remain open; application failure handling and successful test
runs do not claim to fix the underlying simulator/middleware behavior.

## Changed files

New package files:

- `robotops_interfaces`: `CMakeLists.txt`, `package.xml`,
  `action/ExecuteMission.action`.
- `robot_recorder`: `CMakeLists.txt`, `package.xml`, `config/recording.yaml`,
  `robot_recorder/{__init__,artifacts,recording}.py`,
  `test/test_recording_artifacts.py`.
- `mission_manager`: `CMakeLists.txt`, `package.xml`, `scripts/mission_server`,
  `config/{mission,example_mission}.yaml`, `launch/mission.launch.py`,
  `mission_manager/{__init__,model,server}.py`, and
  `test/{test_mission_validation,mission_launch_validation,mission_integration,mission_system}.py`.

All package paths above are under `ros2_ws/src/`. Also added `docs/MISSIONS.md` and
this plan; updated `README.md`, `pyproject.toml`, `.github/workflows/ci.yml` and
`docs/plans/milestone-4-recheck.md` and `docs/NAVIGATION.md`. The only existing runtime configuration change is
`ros2_ws/src/robot_navigation/config/navigation.yaml` for the acknowledgement
timeout explained above. Robot description/control implementations are unchanged.

## Before Milestone 6

No owner action is required for local development. License, maintainer email and
repository URL remain publication decisions. Keep the Gazebo teardown issue
visible when adding repeated experiments. Plan full live-parameter/revision
provenance, interrupted-run recovery and coordination of other navigation clients
before claiming reproducibility or broader operation guarantees. Retain explicit
cancellation uncertainty and recorder finalization failures in experiment results.

## Final diagnostic follow-up

A bounded diagnostic `ctest --repeat until-fail:3 -R '^navigation_system$'
--output-on-failure` ran both navigation profiles three more times: all three
runs passed (77.13, 75.86 and 80.62 seconds). A debugger watcher was ready to capture
Gazebo if shutdown exceeded two seconds, but no hang recurred, so no causal stack
trace was obtained. The watcher was then stopped. These reruns do not erase the
failed full-suite result or close the simulator issue. No retry loop was added to
CI and no shutdown checks were relaxed.

Final installed launch/config smoke test passed again after the executor changes.
All new Milestone 5 tests, builds and portable checks pass. **Project-wide clean
acceptance remains pending the intermittent Gazebo teardown problem.**
