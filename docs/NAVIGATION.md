# Autonomous navigation on a saved map

Milestone 4 runs Nav2 against a fixed occupancy map with AMCL. The navigation
launch consumes standard ROS scan/odom/TF and has no simulator/hardware mode.
Start the desired base backend separately. Mapping and saved-map navigation are
separate sessions; do not run SLAM or a second localization launch concurrently.

## Run

Build and source the workspace as described in the root README. Create and save
a map using [the mapping workflow](MAPPING.md), then stop SLAM and the robot.
Restart the robot in the same world. On this laptop's Jazzy container:

```bash
LIBGL_ALWAYS_SOFTWARE=1 __EGL_VENDOR_LIBRARY_FILENAMES=/dev/null \
  xvfb-run -a ros2 launch robot_bringup robot.launch.py \
  mode:=sim world:=mapping_lab sensors:=true headless_rendering:=false
```

In a second sourced terminal, from the repository root:

```bash
ros2 launch robot_navigation navigation.launch.py \
  map_file:="$PWD/artifacts/maps/lab.yaml" use_sim_time:=true profile:=navfn_rpp
# Use profile:=smac_dwb for the other planner/controller pair.
# Add rviz:=true when a working desktop display is available.
```

The launch starts map_server, AMCL, planner_server, controller_server,
behavior_server and bt_navigator with lifecycle managers. It starts no SLAM,
robot drivers, waypoint/mission/recording nodes or application services. Invalid
profiles and map metadata fail before any process starts.

Initialize AMCL with RViz's **2D Pose Estimate** at the actual map position and
heading. The initial pose must correspond to the saved map; the navigation
launch does not guess it from simulator ground truth. Once localized, Nav2's
servers can finish activation. Check readiness with:

```bash
ros2 lifecycle get amcl
ros2 lifecycle get bt_navigator
```

Both should be active. Send a goal in the saved map's frame, selecting coordinates
that are known free in that map:

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  '{pose: {header: {frame_id: map}, pose: {position: {x: 1.4, y: 0.6}, orientation: {w: 1.0}}}}' \
  --feedback
```

The included RViz view also has **2D Goal Pose** on `goal_pose` (Nav2's topic-to-
action input) and shows `plan`. Interactive GUI use remains separately verified
from headless tests. Coordinates above are the regression goal for a map created
at the custom world's origin; they are not appropriate for every saved map.

Cancel navigation using the standard action cancellation service. Zero goal ID
and timestamp select all current NavigateToPose goals in this one-robot session:

```bash
ros2 service call /navigate_to_pose/_action/cancel_goal action_msgs/srv/CancelGoal \
  '{goal_info: {goal_id: {uuid: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]}, stamp: {sec: 0, nanosec: 0}}}'
```

A command-line client's Ctrl+C alone should not be used as the cancellation
protocol. Confirm the goal canceled and the robot stopped. Stop the navigation
launch with Ctrl+C before stopping the base.

## Profiles and control contract

| Profile | Global planner | Local controller |
| --- | --- | --- |
| `navfn_rpp` (default) | NavFn / Dijkstra | Regulated Pure Pursuit |
| `smac_dwb` | Smac 2D / A* | Dynamic Window Approach (DWB) |

Select at startup and restart navigation to switch profiles. The shared costmap,
frames, goal tolerances and velocity path stay the same. This provides comparable
configurations, not benchmark results or a claim that either is superior.

The default NavigateToPose behavior tree is Nav2's shipped
`navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml`. It checks
path validity at 1 Hz and replans when the goal changes or the path is invalid.
Retaining an unchanged valid path preserves both controller and goal-checker
alignment state near the destination. Local collision checks, progress checks,
command arbitration and independent experiment validation remain active. A
still-valid route is not periodically replaced merely to optimize its length.
This is a behavior policy choice, not a new planner/controller implementation.

Engineering launches may override the tree with the optional `bt_xml` launch
argument. Its default is resolved from the installed `nav2_bt_navigator` package;
a missing file or directory is rejected before creating ROS nodes. Actual
`default_nav_to_pose_bt_xml` is included in runner parameter snapshots. Requalify
this policy when upgrading Nav2 or introducing new dynamic scenarios.

Both profiles target at most 0.25 m/s nominal forward speed. The base's existing
limits remain authoritative. Local/global costmaps consume real sensor streams,
mark and clear obstacles, inflate obstacle costs, and disallow planning through
unknown cells. A 0.3 s expected scan interval prevents stale obstacle observations
from being treated as current by the controller. This is software behavior, not
certified physical safety hardware.

The navigation footprint is a conservative enclosing circle derived from the
same geometry YAML as the URDF, including chassis offset, wheels and sensor
extents. Nominal radius is about 0.303 m plus 0.015 m padding. If overriding
`geometry_file`, pass the same file to base bringup and navigation. The shared
costmap configuration remains in `config/navigation.yaml`; plugin differences
live in `config/profiles/`. Costmaps are nested ROS nodes, so launch explicitly
remaps their scan/map subscriptions to the parent namespace's shared topics.

```text
Nav2 controller / BT-sequenced recovery
        -> cmd_vel/autonomy (TwistStamped, base_link, ROS timestamp)
        -> twist_mux -> cmd_vel/selected
        -> command_guard -> drive_controller/cmd_vel
        -> ros2_control
```

Nav2 explicitly enables stamped commands for Jazzy. No Twist-to-TwistStamped
adapter invents timestamps. Teleop and test input retain higher mux priority.
A teleop override does not cancel the autonomous goal: cancel the action before
releasing teleop if navigation must not resume. Recovery and tracking are
sequenced by Nav2's standard behavior tree; do not send independent `follow_path`
or recovery actions concurrently. No producer may bypass the mux/guard boundary.

AMCL owns `map -> odom`; the drive controller owns `odom -> base_link` and the
robot state publisher owns the URDF transforms. Navigation adds no TF owner.
There is no velocity smoother in this milestone; controller/drive limits handle
speed/acceleration. Progress failures, unreachable goals and lifecycle losses
remain visible through standard actions, lifecycle state and ROS logs.

## Tests

From the built/sourced `ros2_ws`, reserve ROS domains 94–96 for navigation tests:

```bash
colcon build --packages-select robot_navigation --cmake-args -DROBOTOPS_NAVIGATION_TESTS=ON
source install/setup.bash
xvfb-run -a colcon test --packages-select robot_navigation \
  --return-code-on-test-failure --ctest-args -R '^navigation_system$'
colcon test-result --verbose
```

Use `ROBOTOPS_NAVIGATION_TESTS=OFF` to disable this opt-in suite. If mapping and
navigation test options are enabled, wrap the full `colcon test` command in
`xvfb-run -a` as well. CI separates the expensive navigation suite from portable,
mock, Gazebo-control and mapping checks.

The navigation fixture generates a SLAM map once, then restarts the robot for
each profile and reuses that saved map. Tests verify loaded plugin parameters,
real sensor wiring, goal result and independent physical pose, teleop override,
cancel-and-stop, occupied/out-of-map goal failure, navigation shutdown stopping,
and map immutability. Each fresh session uses its own ROS domain and Gazebo
partition to avoid stale discovery/clock data between restarts. This is an initial
regression in one world; broad obstacle/dynamic-scene benchmarks, recording,
mission orchestration and physical deployment belong to later milestones.

Upstream references:
[Nav2 Jazzy controller server](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/controller_server/),
[Jazzy regulated pure pursuit](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/),
[Jazzy navigation source](https://github.com/ros-navigation/navigation2/tree/jazzy).

Rapid same-domain restarts produced a middleware parameter-response timeout in
one development run. Ensure previous processes have exited; if discovery remains
stale, use a fresh `ROS_DOMAIN_ID` consistently in all session terminals. One
Gazebo sensor teardown also timed out during development; tests treat that as a
failure. Final verification and remaining limitations are recorded in the
[Milestone 4 plan](plans/milestone-4.md).


Milestone 5 recording tests exposed a Nav2 BT action-acknowledgement timeout under
concurrent discovery/recording load. The shared `default_server_timeout` is now
1000 ms (previously 20 ms). This bounds action communication waits; it does not
change controller command watchdogs or goal progress limits. See the
[mission verification record](plans/milestone-5.md) for the recorded-mission and
both-profile regression checks.
