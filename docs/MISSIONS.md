# Missions and recordings — Milestone 5

`mission_manager` executes ordered planar waypoints through Nav2's standard
`NavigateToPose` action. It publishes no velocity commands and uses no Gazebo API.
Existing Nav2 → mux → guard → controller ownership remains unchanged.
`robot_recorder` owns a rosbag2/MCAP subprocess and local artifact persistence.

## Run a recorded mission

Build and source the workspace as in the root README. First follow
[NAVIGATION.md](NAVIGATION.md) to start the robot, saved-map localization and Nav2,
and initialize AMCL. Confirm navigation is ready before starting a mission.

Copy the installed mission configuration and edit its artifact directory,
environment, navigation profile and `map_file` to describe that running system:

```bash
cp "$(ros2 pkg prefix --share mission_manager)/config/mission.yaml" /tmp/robotops-mission.yaml
# Edit /tmp/robotops-mission.yaml. Prefer an absolute artifact_root and map_file.
ros2 launch mission_manager mission.launch.py mode:=sim config_file:=/tmp/robotops-mission.yaml
```

From another sourced terminal in the same ROS domain:

```bash
ros2 action send_goal missions/execute robotops_interfaces/action/ExecuteMission \
  "$(cat "$(ros2 pkg prefix --share mission_manager)/config/example_mission.yaml")" --feedback
```

The example visits `(1.4, 0.6)` then `(0, 0)` in `map`, with recording enabled.
Its geometry suits the current mapping lab; validate goals against your loaded
map before using a different environment. Set `record: false` to retain run
metadata/results without creating a bag. An empty or invalid mission is rejected.

Cancel the current mission using the standard action cancellation service:

```bash
ros2 service call missions/execute/_action/cancel_goal action_msgs/srv/CancelGoal '{}'
```

The empty request cancels all goals on this manager's action (at most one is
accepted). Applications can cancel their specific action goal handle instead.
Ctrl-C on the mission server also requests cancellation and finalizes recording
while keeping the ROS context alive. Stopping a `ros2 action send_goal` CLI alone
is not a mission cancellation command.

`mode:=mock` uses wall time and the same action/recording code. Mock hardware alone
has no perception/localization provider, so it is not sufficient for autonomous
Nav2 navigation. Controlled ROS tests supply a Nav2 action server separately.
Startup configuration (including mode and clock policy) is read-only through ROS
parameter services; restart the manager to change it.
`real`, `replay` and unknown modes reject startup; no physical operation or replay
player is implemented.

## Action and ownership contract

Relative action name: `missions/execute`, type
`robotops_interfaces/action/ExecuteMission`.

- Goal: label, 1–100 planar `PoseStamped` waypoints in the configured global frame,
  and a recording flag. Quaternions must be normalized and all values finite.
- Feedback: run ID, stage, zero-based waypoint index, completed waypoint count.
- Result: run ID, artifact directory, completed count, outcome and explanation.
- Outcomes: `succeeded`, `canceled`, `failed`, `cancellation_unconfirmed`.

A single manager rejects overlapping missions. It sends one Nav2 goal at a time,
with a fresh ROS timestamp and Nav2's configured default behavior tree. Direct
Nav2 clients remain capable of preemption; this manager does not claim exclusive
ownership of the whole ROS graph. A higher-priority teleop stream overrides base
commands but does not cancel the mission. Cancel explicitly before changing tasks.

Cancellation is confirmed only when the owned Nav2 action returns a terminal
status. A cancel acknowledgement alone is insufficient. If acceptance or
termination remains uncertain, the manager aborts with `cancellation_unconfirmed`
and latches a fault rejecting further missions. A delayed accepted goal is still
canceled if its response arrives later. Check/stop navigation before restarting a
faulted manager; restarting is not proof that an old goal stopped.

This is application-level navigation cancellation, not an emergency stop or a
measurement of physical standstill. Another command producer such as teleop may
still be active. Live integration tests separately verify actual stopping through
odometry and independent simulator pose. SIGKILL, loss of the manager process or
loss of connectivity can prevent cancellation; independent control watchdogs and
operator stop facilities remain necessary. Physical safety is out of scope.

ROS time governs waypoint limits and duration metadata. Communications, paused
clock protection and cleanup have wall-time bounds. Backward ROS time during
navigation causes failure/cancellation. Accepted missions wait for a valid ROS clock and Nav2 readiness before execution;
startup is bounded, and missing time fails without sending navigation commands.
Accepted and execution-start timestamps are distinct. ROS duration is null if
execution never became ready. ROS signal shutdown keeps action responses processing
before closing the recorder. An internal shutdown cancellation reports a canceled
run but aborts the action unless its client requested cancellation (ROS action
state transitions require this distinction).

## Artifacts and provenance

Each accepted mission creates a new UUID directory under `artifact_root`:

```text
<run-id>/
  metadata.json
  events.jsonl
  result.json
  recording_qos.yaml       # when recording is enabled
  recorder.log
  telemetry/
    metadata.yaml
    telemetry_0.mcap
```

The action result gives the actual absolute directory. Bag filenames are assigned
by rosbag2; inspect `telemetry/metadata.yaml` rather than assuming a filename.
JSON metadata/result files are written through atomic replacement. Events include
UTC and ROS timestamps; results include elapsed ROS/wall time and completed count.
A content hash identifies the mission definition independently of its unique run
ID. Metadata captures the request, manager settings, recording configuration,
robot/environment/profile labels and optional map YAML/image SHA-256 fingerprints.

Environment/profile/revision/map references are explicitly operator supplied.
They are not inferred or verified against live Nav2 parameters. With no repository
revision supplied, `software_revision` is null; no Git commit is fabricated. The
experiment ID/fault configuration are null because Milestone 6 is not implemented.
Exact experiment provenance, full parameter capture, repeated trials and richer
motion metrics remain later work. Missing `result.json` means an interrupted or
incomplete run, never success; automatic recovery of abruptly interrupted bags is
not implemented. Keep run artifacts outside source packages and out of Git.

## Recording contract

`robot_recorder/config/recording.yaml` lists topics, required topics and QoS. Names
resolve in the mission node's namespace/remappings before being passed to the
recorder. `/clock` is explicitly global. Default required streams are odometry,
TF and static TF; LiDAR, IMU, map, joint states and command streams are also requested.
Optional streams may be absent on a backend. Map and static TF use transient-local
reliable subscriptions, while LiDAR/IMU use best-effort volatile subscriptions.
Dynamic TF explicitly uses reliable volatile QoS to receive all current
publishers even when their durability differs. Remaining topics use rosbag2's
publisher-adapted QoS.

The manager waits for required recorder subscriptions before sending navigation
commands. It monitors the recorder during execution. Every terminal path attempts
SIGINT finalization, then bounded escalation if necessary. Unexpected/forced exits,
invalid MCAP envelopes or missing required recorded messages are failures, even
when navigation reached its goal. Finalization failure overrides a successful
navigation result. Tests read the complete MCAP via rosbag2 and verify transient
static data published before recording started.

Start/stop recording is scoped to missions in this milestone; a standalone ROS
recording service/UI is not implemented. The recorder has no playback or command
publishing path.

## Tests and remaining limitations

Default `colcon test` includes controlled action-server/MCAP tests for success,
invalid/concurrent requests, rejection/abort, cancellation, late/refused responses,
recorder loss, missing telemetry, paused time and graceful server shutdown.

Opt into the real simulator integration test:

```bash
cd ros2_ws
colcon build --packages-select mission_manager --cmake-args -DROBOTOPS_MISSION_SIM_TESTS=ON
source install/setup.bash
xvfb-run -a colcon test --packages-select mission_manager --return-code-on-test-failure \
  --ctest-args -R '^mission_system$'
colcon test-result --verbose
```

This generates a temporary SLAM map, starts Nav2, executes two waypoints, verifies
standstill and the immutable map, and reads every recorded MCAP message. CI has a
separate mission simulation job. See [the plan](plans/milestone-5.md) for results.
The Gazebo hang was subsequently captured and addressed by the
[simulation-adapter shutdown repair](plans/gazebo-shutdown-repair.md). Normal
shutdown assertions remain enabled. Middleware response timeouts remain a
separate issue; a response timeout must not be treated as proof that no goal ran.
Hosted CI, GUI appearance, replay and physical operation remain unverified.
