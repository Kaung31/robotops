# robot_diagnostics

Read-only header/receipt freshness monitor. This first stage does not measure
sensor accuracy, value freeze, publication frequency, TF, localization quality,
controller state or overall robot safety. It does not command the robot, change
readiness or compute experiment verdicts. Off by default in robot bringup.

After building and sourcing the workspace, opt in explicitly:

```bash
# Gazebo or recorded ROS-time observations
ros2 run robot_diagnostics freshness_monitor --ros-args -p use_sim_time:=true

# Opt in as part of a fresh simulation stack
ros2 launch robot_bringup robot.launch.py mode:=sim diagnostics:=true

# Wall-clock sources, e.g. mock odometry only
ros2 run robot_diagnostics freshness_monitor --ros-args \
  -p 'enabled_streams:=[odom]' -p use_sim_time:=false

ros2 topic echo /diagnostics
```

Bringup also accepts exported `ROBOTOPS_DIAGNOSTICS=true|false` as its argument
default. Explicit `diagnostics:=false` overrides the environment. For backend
campaigns, export the variable before starting Uvicorn; each child launch inherits
it. This is runtime observability configuration, not a new campaign definition or
fault configuration. Bringup selects odometry only in mock or sensor-disabled sim,
and all three streams in sensor-enabled sim, with the adapter's existing clock.
The monitor has no exit handler that shuts down the robot stack. Existing unsupported
real/replay bringup modes still reject before constructing processes.

Mission recording now includes `diagnostics` as an optional reliable/volatile
topic. It is not required for recording validity, readiness, metrics or verdicts;
absence is not healthy evidence. Recorded statuses are observations, not fault
labels, and bag/manifest integrity rules remain unchanged.

The first paired Gazebo baseline verified healthy recorded updates and unchanged
separate mission/pose/contact verdicts, but measured approximately 63% of one CPU
core for the original Python monitor under the high-rate clock stream. The live
monitor/core now use C++/rclcpp in this package; the pure Python policy remains an
offline parity oracle. Matched replay measured 53.52% versus 13.96% of one core
(73.92% reduction), with sampled native RSS 18,247,680 bytes. The <=10% CPU target
was not met, so diagnostics remain opt-in. Repeated residual measurements
subsequently averaged 12.07% for full replay and 11.24% for a minimal clock-only
node; a standard static-executor probe provided no improvement. Clock and sensor callbacks share a
single executor; shared clock rates and robot interfaces are unchanged. See the
plan for evidence and live measurements; individual trials do not establish
performance equivalence.

A later stock-Nav2 behavior-tree qualification passes three fresh-stack off/on
pairs: warm monitor CPU 8.81–9.87% of one core, RSS <=20.39 MiB, duration/path
comparisons and independent evidence/clean shutdown checks pass. This accepts
only the predeclared **local opt-in isolated fault-development** budget. The
separate replay/default target above remains unmet; diagnostics remain false.

Inputs are relative/remappable `odom` (Odometry), `scan` (LaserScan), `imu/data`
(Imu), with best-effort/volatile sensor-data QoS. `enabled_streams` defaults to
`[odom, scan, imu]`; exclude absent sensors explicitly. Relative `diagnostics`
publishes reliable/volatile DiagnosticArray, depth 10, every 0.2 steady seconds.
Namespaces/remapping follow ordinary ROS rules. Subscribers joining later receive
the next status, not historical transitions. Stopping the monitor does not publish
a final status; consumers must independently detect absent diagnostics.

Status names: `robotops/clock`, `robotops/freshness/{odom,scan,imu}`. Output includes
schema version 1, local clock epoch and, when observed, receipt/stamp ages,
source stamp, advancing sample count and thresholds as DiagnosticStatus values.
`hardware_id` defaults to `robotops`; set it per runtime when needed. This ID and
clock epoch are local monitor metadata, not proof of publisher/trial identity.

Read-only startup parameters:

| Parameter | Default | Meaning |
|---|---:|---|
| warn_seconds | 0.5 | ROS age warning threshold |
| error_seconds | 1.0 | ROS stamp error / receipt timeout threshold |
| future_seconds | 0.1 | Allowed stamp lead over local ROS time |
| clock_stall_seconds | 2.0 | Steady-time limit without ROS clock advance |
| publish_period_seconds | 0.2 | Steady-time period, finite [1e-9, 86400] seconds |

Equality at age thresholds is accepted at the preceding level. Missing input is
STALE; receipt timeout is STALE; invalid/future/regressing/expired stamps are ERROR;
intermediate age is WARN. Fresh data needs two advancing samples to reach OK.
ROS-time zero, clock stall and clock-source changes/backward jumps invalidate or
block health; recovery requires current observations. Constant values with advancing
stamps can be legitimate and are not treated as faults. Neither timestamps nor
receipt cadence authenticate a publisher, so avoid competing input publishers.

The steady timer continues during simulation/replay pause. A paused clock is
reported as `clock_not_advancing`, which does not distinguish intentional pause
from loss of the clock publisher. Sensor ages remain in ROS time, avoiding false
dropout accusations caused solely by slow simulation. No physical real-time or
safety guarantee is implied.

Tests: `test/test_freshness.py` is pure Python; `test/diagnostics_integration.py`
launches the installed native executable in an isolated ROS domain (187 when run
by ament) with controlled publishers. `test/policy_parity.py` compares 3,000
adversarial evaluations against the offline reference via the test-only native
`policy_trace` executable. They do not use Gazebo or live robot faults. See the staged
[diagnostics plan](../../../docs/plans/deterministic-diagnostics.md).
