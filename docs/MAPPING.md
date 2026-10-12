# Mapping and saved-map localization

Milestone 3 adds one custom indoor world, live simulated LiDAR/IMU, SLAM Toolbox,
occupancy-map saving and AMCL localization. This mapping launch does not start Nav2 planning or
navigation controllers. For Milestone 4 goal navigation, use the separate
[navigation workflow](NAVIGATION.md) after saving your map. `robot_navigation` consumes standard ROS interfaces;
Gazebo-specific sensors, rendering and transport stay in `robot_simulation`.

## Start the robot and map it

Use Ubuntu 24.04/Jazzy (on this laptop: `distrobox enter jazzy`). Build using the
root README and source both ROS and `ros2_ws/install/setup.bash` in every terminal.
Use one robot and one mapping/localization workflow per ROS domain. Stop any
previous session before starting these commands.

The laptop container needs software GLX rendering because EGL device probing
crashes in the installed Mesa/NVIDIA combination. This tested fallback uses a
virtual display, does not change system graphics settings, and opens no GUI:

```bash
sudo apt-get install -y xvfb xauth libgl1-mesa-dri
LIBGL_ALWAYS_SOFTWARE=1 __EGL_VENDOR_LIBRARY_FILENAMES=/dev/null \
  xvfb-run -a ros2 launch robot_bringup robot.launch.py \
  mode:=sim world:=mapping_lab sensors:=true headless_rendering:=false
```

On a machine with working EGL, use `headless_rendering:=true` (the default)
without Xvfb. `gui:=true` starts the optional Gazebo client and requires a working
desktop display. `headless_rendering` selects the server rendering interface;
`gui` independently controls whether a Gazebo client opens.

In a second terminal:

```bash
ros2 launch robot_navigation map.launch.py workflow:=mapping use_sim_time:=true
# Add rviz:=true when a working desktop display is available.
```

SLAM activates through a lifecycle manager. It consumes `scan` and odometry TF,
publishes `map` and owns `map -> odom`. Move through the existing stamped mux
input (Ctrl+C stops the publisher and the drive timeout stops motion):

```bash
ros2 topic pub --rate 20 /cmd_vel/teleop geometry_msgs/msg/TwistStamped \
  '{header: {stamp: now, frame_id: base_link}, twist: {linear: {x: 0.15}}}' --use-sim-time
# For a turn, replace twist with: {angular: {z: 0.25}}
```

This is manual mapping: monitor position and stop before obstacles. No collision
avoidance or autonomous exploration is implemented. Mapping doesn't consume the
independent simulator ground truth. Wheel odometry remains the motion estimate;
the IMU is published for inspection and later fusion, not fused in this milestone.

## Save and load

Stop command publishers and save while SLAM is still running. From the repository
root (generated artifacts are ignored by Git):

```bash
mkdir -p artifacts/maps
ros2 run nav2_map_server map_saver_cli -f "$PWD/artifacts/maps/lab" \
  --ros-args -p use_sim_time:=true -p save_map_timeout:=10.0
```

This creates `lab.yaml` and `lab.pgm`. Keep both together. These are occupancy
maps for AMCL; SLAM pose-graph serialization/resuming mapping is not included.

Stop the mapping launch before starting localization. For a repeatable start,
stop and restart the robot with the same world as well. Then run:

```bash
ros2 launch robot_navigation map.launch.py workflow:=localization \
  map_file:="$PWD/artifacts/maps/lab.yaml" use_sim_time:=true
```

The map YAML and referenced image must exist; malformed metadata is rejected
before nodes start. The map server still validates the image encoding when it
loads. The lifecycle manager activates map_server and AMCL. AMCL requires an
initial pose: use RViz's **2D Pose Estimate** tool with fixed frame `map` to select
the known robot position and heading. Add `rviz:=true` to the launch for the
provided view. For the test's map, a restarted robot begins near map origin with
zero yaw; this is not a universal initial pose for arbitrary saved maps.

AMCL now owns `map -> odom`; SLAM must remain stopped. The workflow selector
starts only one owner, but cannot prevent a separately launched conflicting
process. Localization uses the fixed map without rebuilding it. Use
`use_sim_time:=false` for a future live source using wall time; no real hardware
bringup exists yet.

## Sensor, frame and QoS contract

| Interface | Frame / owner | Profile |
| --- | --- | --- |
| `scan` / LaserScan | `lidar_link`, Gazebo adapter | Sensor data, best effort/volatile |
| `imu/data` / Imu | `imu_link`, Gazebo adapter | Sensor data, best effort/volatile |
| `map` / OccupancyGrid | `map`, SLAM or map_server | Reliable/transient local |
| `map -> odom` | SLAM or AMCL, exclusively | Standard dynamic TF |
| `odom -> base_link` | diff_drive_controller | Standard dynamic TF |
| Sensor mounting TF | robot_state_publisher | Reliable/transient-local static TF |

LiDAR: 360 samples, full horizontal revolution, 10 Hz simulated time, 0.12–12 m.
IMU: 50 Hz simulated time, orientation/angular velocity/linear acceleration.
Sensors use simulator timestamps and all simulation consumers use `/clock`.
Tests exercise sensor-data subscribers, late map subscribers, and timestamped TF.
The neutral URDF and mock backend contain no sensor publishers or fake scans.

The custom `mapping_lab` has walls centered at x=±5 m and y=±4 m (0.2 m thick),
plus an asymmetric shelf, pillar and partition. Walls/obstacles are 1.2 m tall,
with matching visual and collision boxes. The clear origin supports an initial
short manual mapping route; there are no remote assets or tutorial-world
requirements. This is a development laboratory, not a calibrated difficulty
benchmark. Broader environments and difficulty evidence belong to Milestone 8.

## Verify

From the built/sourced `ros2_ws`:

```bash
colcon build --packages-select robot_navigation --cmake-args -DROBOTOPS_MAPPING_TESTS=ON
source install/setup.bash
xvfb-run -a colcon test --packages-select robot_navigation \
  --return-code-on-test-failure --ctest-args -R '^mapping_system$'
colcon test-result --verbose
```

The opt-in test forces software GLX only in its child processes and uses ROS
domain 93 plus a private Gazebo partition. Reserve that domain during the run.
It verifies real wall returns/IMU/TF, drives through the mux, generates and saves
a SLAM map, shuts down, restarts, loads that map, initializes AMCL and compares
localization with independent simulator truth while moving. The map remains
unchanged. Maps and process logs are temporary pytest artifacts. Set
`ROBOTOPS_MAPPING_TESTS=OFF` to disable the expensive test again.

SLAM's Jazzy bond destruction was observed to abort after ROS context shutdown.
For mapping only, `use_lifecycle_manager: false` disables SLAM's bond and the
manager uses `bond_timeout: 0.0`; the manager still configures/activates SLAM.
Process-exit supervision remains enabled, but this does not detect a hung SLAM
process. AMCL/map_server retain their normal bonds. Revisit the SLAM workaround
when upgrading upstream packages. Tests check child-process exit logs as well as
launcher exit codes so a crash cannot masquerade as clean shutdown.

Upstream context: [Gazebo headless rendering](https://gazebosim.org/api/sim/8/headless_rendering.html),
[SLAM Toolbox](https://docs.ros.org/en/jazzy/p/slam_toolbox/),
[AMCL configuration](https://docs.nav2.org/configuration/packages/configuring-amcl.html).

### SLAM signal shutdown

Mapping now uses `robot_navigation/slam_runner`, a small C++ entry point linked
against the installed SLAM Toolbox library. It defers SIGINT/SIGTERM context
shutdown until lifecycle deactivation, cleanup and node destruction have stopped
the workers. This also works when simulated time is paused. The upstream
executable could abort when a sleeping worker observed an already-invalid ROS
context; disabling the bond alone did not solve that race. ROS node name, mapping
configuration and interfaces are unchanged. The default CI suite exercises both
signals in active and unconfigured states with wall and simulated time.

See the [Milestone 4 recheck](plans/milestone-4-recheck.md) for the current
verification gate and the separate intermittent Gazebo shutdown failure.
