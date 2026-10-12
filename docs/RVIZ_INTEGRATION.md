# RobotOps RViz Engineering View

RobotOps treats RViz as an optional engineering/debugging companion rather than a replacement target.

## Web workflow

The Control Center now provides two ways to use RViz:

1. Enable **Open RViz engineering view when the stack starts** before starting Mapping or Navigation.
2. Start the stack normally and use **Open RViz** / **Close RViz** while it is running.

RViz is auxiliary. If RViz cannot start or exits unexpectedly, RobotOps keeps the robot, mapping, or navigation stack running and reports the RViz error separately.

RViz is observability only. Whether RViz is open, closed, slow, or crashed must not change RobotOps navigation readiness, experiment metrics, benchmark verdicts, or robot control behavior.

Stopping the RobotOps stack also closes an RViz instance started by RobotOps.

Automated benchmark campaigns request `open_rviz: false` so repeated trials do not create GUI windows or make benchmark execution depend on GUI load. An engineer may attach a separately launched RViz instance while diagnosing a campaign; it may temporarily lose ROS data while the stack restarts and should recover when the new stack publishes again.

## RViz configurations

- `ros2_ws/src/robot_navigation/rviz/mapping.rviz`
  - RobotModel from `/robot_description`
  - `/map`
  - `/scan`
  - TF
- `ros2_ws/src/robot_navigation/rviz/navigation.rviz`
  - all mapping displays
  - `/plan`
  - optional global/local costmaps (disabled by default)
  - optional local footprint (disabled by default)

The navigation launch file now also honors its existing `rviz:=true` argument for direct ROS launch workflows.

## Manual fallback

With a RobotOps stack already running:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
rviz2 -d "$(ros2 pkg prefix robot_navigation)/share/robot_navigation/rviz/navigation.rviz"
```

After applying this patch, rebuild `robot_navigation` once so the new/updated RViz configs are copied into the install space.

## Current verification note

Manual Mission Operations have been observed with the RobotModel, occupancy map, LiDAR, TF and global plan visible in RViz while RobotOps navigation runs. The remaining automated-campaign visualization/restart behavior is under diagnosis and should not be "fixed" by making RViz part of campaign execution.
