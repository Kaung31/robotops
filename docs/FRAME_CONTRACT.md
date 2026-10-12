# Initial robot frame and control contract

This is the geometric contract for the single differential-drive base, established
in Milestone 1. The target is ROS 2 Jazzy. Milestone 2 adds mock/sim backends as
documented in [the control contract](CONTROL_CONTRACT.md).

## Coordinates and geometry

Use SI units and right-handed axes: +X forward, +Y left, +Z up. `base_link` is at
the midpoint of the wheel axle, one wheel radius above a flat ground plane. It is
massless; inertia belongs to `chassis_link` and the other physical links. This
avoids a root-link inertia that KDL cannot represent.

`config/geometry.yaml` is the single source for nominal dimensions/masses. The
Xacro `geometry_file` argument accepts a complete replacement YAML file (including
paths containing spaces). Values must be numeric, finite, positive, and below
1e6 SI units; wheel separation must clear the chassis, and the caster must fit
beneath it. Missing keys/files fail expansion. These checks do not certify every
possible custom geometry: review sensor placement, overlap, and support stability
when changing dimensions.

The chassis underside is at axle height, with its center shifted rearward by 10%
of chassis length. The rear spherical caster contacts the same plane as the
wheels. The caster is a fixed geometric approximation; contact/friction and caster
dynamics are decisions for the simulation adapter. Dimensions and inertias are
nominal analytical primitives, not a measured physical robot.

## Frame tree and ownership

```text
map                            SLAM OR AMCL owns map -> odom
└── odom                       drive_controller owns odom -> base_link
    └── base_link              root of this URDF
        ├── chassis_link       fixed
        ├── left_wheel_link    continuous left_wheel_joint, +Y axis
        ├── right_wheel_link   continuous right_wheel_joint, +Y axis
        ├── caster_link        fixed geometric support
        ├── lidar_link         fixed, nominal scan origin at sensor center
        └── imu_link           fixed, aligned with base axes
```

`map` and `odom` are reserved external frames, absent from this URDF. No dummy
world/odometry transforms are published. `base_footprint` is not needed now;
introducing it later requires a deliberate ownership/consumer review.

`robot_state_publisher` alone owns transforms beneath `base_link`. Fixed joints
use `tf_static`; wheel transforms use `tf` and require `sensor_msgs/msg/JointState`
on `joint_states`. Encoders will supply joint state rather than separate encoder
frames. Milestone 3 adds simulated sensor data on `scan` (`lidar_link`) and `imu/data`
(`imu_link`); the standalone description and mock backend remain sensor-free.
See [mapping and localization](MAPPING.md) for time, QoS and workflow ownership.

Static TF and `robot_description` use the publisher's reliable, transient-local
profiles so late subscribers can obtain them. Wheel state subscribers use the
standard robot_state_publisher sensor-data profile; integration tests exercise
compatibility with a reliable joint-state publisher. Names are relative, and the
launch remaps the publisher's absolute TF names to relative names for namespace
composition. Namespacing topics does not prefix frame IDs; this contract remains
for one robot, not a multi-robot deployment.

## Preview and time

`description.launch.py` starts only `robot_state_publisher` by default. The
`publish_preview_joint_states:=true` option adds `joint_state_publisher` with zero
wheel positions. It is a visual preview, not the ros2_control mock backend, and
must be disabled when real joint states or recorded joint states are supplied.

`use_sim_time` defaults to false and is forwarded as a boolean to both nodes.
Enabling it requires an external `/clock` publisher; this launch does not create
one. Integration tests verify forwarding, not paused-clock or replay behavior.

## Control integration

`left_wheel_joint` and `right_wheel_joint` retain their +Y axes and shared
geometry. Both positive wheel velocities mean forward motion. The reusable
`control.xacro` fragment exposes velocity commands and position/velocity states.
The standalone description preview still selects no hardware plugin.

`robot_control` owns shared controller/mux configuration; `robot_bringup` composes
the description, controllers and selected backend. `robot_simulation` owns
Gazebo-specific extensions. The drive controller currently owns `odom ->
base_link`; any future state estimator replacing it must disable controller TF
publication. See the control contract for stamped command arbitration/timeouts.

Upstream references: [robot_state_publisher](https://index.ros.org/p/robot_state_publisher/)
and [ROS 2 Jazzy diff_drive_controller](https://control.ros.org/jazzy/doc/ros2_controllers/diff_drive_controller/doc/userdoc.html).
