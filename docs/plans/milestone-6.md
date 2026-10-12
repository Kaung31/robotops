# Milestone 6 — Experiment framework

## Goals and boundary

Run a validated YAML experiment as sequential mission trials on an already-running
ROS stack. Persist configuration, observed ROS parameters, trial/run associations,
metrics and a comparison report. Keep simulator startup/reset outside the runner.
No backend, frontend, replay commands, faults or physical operation are added.

The intermittent Gazebo shutdown issue remains open. Development of the runner is
independent of simulator process teardown: it uses the existing mission action on
a persistent stack. System tests retain strict teardown checks; a successful run
must not be described as a fix for that issue.

## Files/packages

Create only `ros2_ws/src/experiment_runner`: Python configuration/metrics logic,
ROS action client, CLI, example YAML, package/CMake metadata and tests. Add
`docs/EXPERIMENTS.md`; update README, portable test discovery and CI as needed.
The existing mission action and immutable mission artifacts remain unchanged.
An experiment manifest associates its UUID with mission run UUIDs externally.

## Implementation steps

1. Validate exact configuration fields and finite planar poses; reject unsupported
   modes and options rather than silently ignoring them.
2. Snapshot live parameters before each trial, verify expected mission settings,
   require a fresh localized start pose within configured tolerances, and reject
   parameter drift. Do not teleport or reinitialize localization between trials.
3. Execute one mission at a time. Persist the pending trial before submission;
   record terminal failures and stop on rejection, interruption or uncertainty.
   Cancel owned goals with bounded waits. Never retry an uncertain submission.
4. Read finalized MCAP odometry for travelled distance, with timestamp/frame
   validation. Preserve unavailable metrics explicitly. Use mission ROS duration;
   report success rate over all attempted trials and successful duration means.
5. Compare reports only when robot/environment/mission/start/map conditions match;
   retain distinct live parameter snapshots so navigation configurations can differ.
6. Test pure validation/metrics/report behavior, real ROS action orchestration and
   repeated recorded Nav2 missions, then run existing build/lint/test commands.

## Success criteria and limits

Two sequential trials have distinct mission UUIDs and recordings, an immutable
configuration snapshot, live parameter evidence and explicit metric units. Invalid
configuration or start conditions cause no goal. Failures remain in the report;
SIGINT cancels the owned mission and prevents further trials. Interrupted manifests
are recognizable and never automatically resumed. No final velocity publisher,
Gazebo API, world reset or simulator branch enters the runner. Unknown software
revision is labelled unavailable, and local files/ROS graph must be trusted.

## Implementation decisions and discoveries

- Only `experiment_runner` was added. Existing mission messages, velocity topics,
  controller/simulation code and package responsibilities are unchanged.
- ROS parameter snapshots include tagged non-finite doubles because Jazzy
  controllers expose NaN for some unset limits. Requested poses/timeouts still
  require finite values; sentinel encoding is tested and preserves comparisons.
- Keep original mission artifacts immutable. The experiment manifest records its
  own UUID, a client-generated action goal UUID before submission, mission run
  UUID from feedback and final artifact paths. This avoids an action API change.
- A failed later preflight must not relabel an earlier completed trial. Explicit
  trial ownership and a regression test cover that boundary. Transport exceptions
  during result collection are persisted as termination uncertainty.
- The first ROS integration run caught a collision with `Node.handle`; the action
  handle is now `mission_handle`. The first simulator run exposed NaN serialization;
  tagged parameter encoding fixed it. The subsequent six controlled cases and live
  two-trial experiment passed; final verification adds interruption/provenance cases.
- No automatic restart/retry, Gazebo reset, synthetic ground-truth metric or
  unsupported performance claim was added. Initial-pose tolerances and odometry
  metric limitations are documented in `docs/EXPERIMENTS.md`.

## Recheck before implementation (2026-10-08)

All eight existing packages built. The unchanged full M5 suite passed in 4 min 12 s:
144 aggregate results, zero errors/failures/skips. All 73 then-existing portable
tests, formatting/lint, XML validation and rosdep checks passed. A debugger watcher
observed no Gazebo shutdown hang; its cause remains unresolved. This pass supports
continuing independent application work, not closing the simulator issue.

## Changed files

New package under `ros2_ws/src/experiment_runner/`:

- `CMakeLists.txt`, `package.xml`, `scripts/experiment`;
- `experiment_runner/{__init__,model,runner,cli}.py`;
- `config/round_trip.yaml`;
- `test/{test_model,experiment_integration,experiment_system}.py`.

Also added `docs/EXPERIMENTS.md` and this plan, and updated `README.md`,
`pyproject.toml` and `.github/workflows/ci.yml` (a dedicated experiment simulation
job; controlled ROS checks remain in the default fast ROS job).

## Simulator failure investigated during final verification

The first complete M6 run had 172 aggregate results and four failure entries for
**two** real test failures (pytest plus CTest wrappers): the existing mapping
shutdown hang, and a mission action response lost with `rmw_response.cpp` timeout.
All experiment tests passed, including nine controlled cases and two live recorded
trials. Logs were retained under `/tmp/robotops-m6-before-shutdown-repair/`.

This time GDB captured the shutdown deadlock. See
[gazebo-shutdown-repair.md](gazebo-shutdown-repair.md) for the lock-cycle evidence,
narrow simulation entry-point change and regression plan. Additional changed files:
`robot_simulation/{CMakeLists.txt,package.xml,launch/gazebo.launch.py}`, new
`src/gazebo_runner.cpp`, `test/{runner_validation,gazebo_shutdown}.py`, and
`docs/MISSIONS.md`. This is a documented process-lifecycle repair, not a change to
the robot architecture or command interfaces. The middleware response issue is
separate; no retry or assertion suppression was introduced.

## Post-Codex audit continuation

A later repository audit found one comparison-state bug: `comparison()` rejected
`running` manifests but accidentally allowed `interrupted` manifests even though its
own error text and finalization rule said both were non-comparable. The condition
was corrected and the regression test now covers both unfinished states.

Portable verification in the continuation environment: `test_model.py` passed
15/15. Full ROS/Gazebo verification could not be repeated there because the sandbox
did not provide the ROS/Jazzy Python dependencies; the earlier live verification
results above remain the latest ROS-system evidence.
