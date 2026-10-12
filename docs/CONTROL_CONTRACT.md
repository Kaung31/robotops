# Milestone 2 control contract

One differential-drive base, two implemented live backends: `mock` and `sim`.
`real` and `replay` are rejected before any robot process starts. There are no
physical drivers or replay command paths in this milestone.

## Package boundary

- `robot_description`: primitive geometry, frames and wheel interface macro.
- `robot_control`: shared controller/mux configuration, C++ command validation
  and geometry-derived parameters; no backend selection or simulator dependency.
- `robot_bringup`: selects an adapter and composes the shared nodes/controllers.
- `robot_simulation`: Gazebo-specific Xacro extensions, plugin loading, contact
  properties, headless world, entity creation and transport bridge.

Adding `robot_simulation` makes the simulator boundary explicit; it is a concrete
adapter package, not an alternative architecture. Its installed `control_pad.sdf`
is an original 20 m flat control-test floor with no downloaded assets. It is not
a navigation benchmark map or a claim of navigation difficulty coverage.

Both adapters expand the same base and ros2_control wheel macros. Mock uses
`mock_components/GenericSystem` with `calculate_dynamics=true` to integrate wheel
velocity into position. Sim uses `gz_ros2_control/GazeboSimSystem`. Joint names:

| Joint | Command | States |
| --- | --- | --- |
| `left_wheel_joint` | velocity (rad/s) | position (rad), velocity (rad/s) |
| `right_wheel_joint` | velocity (rad/s) | position (rad), velocity (rad/s) |

Positive velocity on both +Y wheel axes moves forward. Radius and separation are
read from the same geometry YAML for URDF and controller parameters. The launch
writes a temporary controller YAML for both backends and removes it on shutdown.

## Live ROS interfaces

Names below are relative, shown without a leading slash. This launch currently
composes one robot at the root namespace; multi-robot operation is out of scope.

| Interface | Type | Owner/purpose |
| --- | --- | --- |
| `cmd_vel/teleop` | geometry_msgs/msg/TwistStamped | Highest-priority source (100) |
| `cmd_vel/test` | geometry_msgs/msg/TwistStamped | Test/development source (50) |
| `cmd_vel/autonomy` | geometry_msgs/msg/TwistStamped | Reserved autonomy source (10) |
| `cmd_vel/selected` | geometry_msgs/msg/TwistStamped | Mux output to guard |
| `drive_controller/cmd_vel` | geometry_msgs/msg/TwistStamped | Guard output only |
| `odom` | nav_msgs/msg/Odometry | Drive controller, encoder feedback |
| `joint_states` | sensor_msgs/msg/JointState | Joint state broadcaster |
| `tf` | tf2_msgs/msg/TFMessage | Drive controller and robot state publisher |
| `tf_static` | tf2_msgs/msg/TFMessage | Robot state publisher |
| `robot_description` | std_msgs/msg/String | Robot state publisher |
| `clock` (sim) | rosgraph_msgs/msg/Clock | Gazebo -> ROS bridge |
| `simulation/ground_truth` (sim) | tf2_msgs/msg/TFMessage | Adapter verification only |

The wheel/odometry topics are the same in both modes. Mock does not simulate
perception or physical contact. LiDAR/IMU are mounts only; their data interfaces
will be implemented with the mapping/sensor milestone.

## Arbitration, limits and stop behavior

`twist_mux` (>=4.5.0) operates in stamped mode. Source freshness expires after
0.3 seconds of ROS time. A fresh higher-priority source masks lower priorities;
a zero teleop command therefore takes precedence over a moving test command.
When it expires, a continuing lower-priority stream can regain control. The mux
forwards stamps unchanged and does not latch or periodically replay commands.

A shared C++ `command_guard` sits between mux and controller. It rejects zero,
negative/malformed, stale (>0.3 s) or future-dated (>0.05 s) timestamps, non-finite
or non-planar velocity, and frames other than `base_link`. Rejected commands
produce a fresh zero command and a throttled warning. Accepted stamps are preserved;
the guard never renews a moving command after receipt. This closes the case where
a far-future source stamp would otherwise postpone the controller watchdog.

Use current ROS-clock stamps and `base_link` for command frame IDs. The drive
controller's 0.5-second watchdog stops after input loss (up to 0.55 s for accepted
clock skew); configured deceleration can add stopping time. Limits are 0.4 m/s
and 1.0 rad/s, with 0.5 m/s² and 1.5 rad/s² acceleration/deceleration bounds.
These are conservative development values, not measured safety ratings.

Commands use reliable, volatile QoS; sensors/joint feedback can be consumed with
sensor-data QoS. Integration tests exercise publisher/subscriber compatibility.
Input producers must use their own mux topic, never publish directly to the final
controller input. ROS graph access is trusted local development access; this
convention is not access control. It does not authorize public network or physical
operation. A manual stop request does not replace a physical emergency stop.

`use_sim_time` is false for mock and true for sim across the shared nodes and
controllers. Sim watchdog/source expiry follow ROS time: pausing Gazebo also
pauses physics/timeouts. Time jumps and restarting a running world in place are
not yet supported; restart the launch to reset the session.

## Lifecycle and TF ownership

Startup loads and activates the drive controller and joint state broadcaster as
a group after controller_manager is available. Readiness is both controllers
reporting `active`, not merely the launch command returning. Spawner failures
stop the launch. Exit of controller_manager, mux, command guard, state publisher, Gazebo server
or bridge shuts down the session. Normal Ctrl+C shutdown is tested.

The drive controller alone owns `odom -> base_link`; its odometry uses measured
wheel position (`open_loop=false`, `position_feedback=true`). Robot state
publisher owns all links below `base_link`. `map -> odom` is still absent.
Simulator truth never publishes to `tf` or substitutes for encoder odometry.
The tests verify real model displacement and yaw separately from odometry.

## Verification limits

This proves wiring, basic motion, arbitration, and stop behavior on the nominal
model in a flat world. It does not prove navigation, contact fidelity under all
loads, long-duration reliability, clock-reset recovery, network trust, or physical
safety. Generic mock hardware is ideal; simulation can slip. Validate/tune sensor
and contact realism as later milestones require it.

Upstream details: [Jazzy mock components](https://control.ros.org/jazzy/doc/ros2_control/hardware_interface/doc/mock_components_userdoc.html),
[gz_ros2_control](https://control.ros.org/jazzy/doc/gz_ros2_control/doc/index.html),
and [twist_mux](https://index.ros.org/p/twist_mux/).

## Nav2 integration (Milestone 4)

`navigation.launch.py` routes controller_server and BT-sequenced recovery output
to `cmd_vel/autonomy`. Both explicitly use Jazzy's stamped command option and
retain `base_link`/ROS-clock timestamps. Teleop and test priority, the command
guard and the drive timeout are unchanged. There is no new publisher on the
final drive command input. A teleop override does not cancel a Nav2 action;
cancel it before releasing the override if autonomous motion must not resume.
See [navigation](NAVIGATION.md) for profile selection, cancellation and tests.
