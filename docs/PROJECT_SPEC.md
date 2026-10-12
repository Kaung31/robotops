# RobotOps Project Specification

> Current phases and working rules are in [AGENTS.md](../AGENTS.md#development-order);
> implementation status is in [CURRENT_STATUS.md](CURRENT_STATUS.md). Technical
> requirements below still apply; strategic milestones may be superseded.

## 1. Project summary

RobotOps is a simulation-first ROS 2 platform for operating, testing, validating, recording, and analysing autonomous robots.

The platform must allow the same high-level software to work against:

- mock hardware
- Gazebo simulation
- recorded robot data
- physical hardware later

The project is intended to demonstrate strong robotics software engineering rather than a simple visualization dashboard.

A major showcase scenario is:

1. launch a custom simulated environment
2. map it using simulated LiDAR and SLAM
3. visualize the map building live
4. save the map
5. relaunch in localization/navigation mode
6. select a goal from the web UI
7. navigate autonomously
8. record telemetry and metrics
9. compare navigation methods on the same map

## 2. Primary objective

Build a hardware-agnostic RobotOps platform where robot operations, navigation, experiments, telemetry, diagnostics, data collection, replay, and later ML analysis remain reusable across simulated and physical robots. The current product is local-first and one-robot-per-runtime/session, with a later simulation-only shareable demo for portfolio/interview use.

## 3. Core and stretch success criteria

The core robotics/validation platform is successful when the following are true:

- one differential-drive robot works in ROS 2 Jazzy
- the robot can run against mock ros2_control hardware
- the same high-level controller setup works in Gazebo
- SLAM can build and save a map from simulated LiDAR
- the robot can reload and localize against a saved map
- Nav2 can autonomously navigate the simulated robot
- at least two navigation planner/controller configurations can be benchmarked on the same environment
- a mission can be started and observed through the web platform
- telemetry can be recorded to rosbag2/MCAP
- recordings can be replayed and analysed
- experiments are reproducible from configuration
- simulation faults can be injected intentionally
- regression runs can compare software/configuration changes
- deterministic diagnostics report robot/system health
- the architecture preserves a stable path for a later physical hardware adapter without redesigning live high-level software
- replay can drive visualization, diagnostics, analytics, and ML without enabling robot command paths

Stretch success criteria after the core platform is stable:

- a safe simulation-only hosted demo can be shared with friends, recruiters, and interviewers without exposing a physical robot or generic public ROS graph
- controlled faults and verified outcomes can generate a labelled dataset
- an ML anomaly detector can be trained and evaluated on that trustworthy dataset if the project finishes on schedule
- a physical hardware adapter can be implemented later through the same stable ROS-facing contracts

## 4. Non-goals for the first major version

Do not target these initially:

- robotic arms
- drones
- multiple robot fleets
- fleet scheduling
- multi-cloud deployment
- fleet-scale/public physical-robot operations
- Kubernetes
- multiple simulation engines
- custom SLAM algorithms
- custom global/local planner research
- production electrical power management
- highly autonomous AI agents controlling the robot

## 5. User-facing capabilities

### 5.1 Robot operations

The web application should eventually allow the user to:

- see robot online/offline state
- see runtime mode
- activate/deactivate robot software
- start or cancel missions
- request a safe stop
- enter teleoperation mode
- monitor navigation state
- inspect core telemetry
- inspect diagnostics
- start/stop data recording

### 5.2 Visualization

The platform should display:

- robot pose
- occupancy map
- live map-building progress in mapping mode
- navigation path
- LiDAR data
- camera stream when implemented
- mission state
- robot/system health
- live metrics

3D visualization may use Three.js where it adds value.

### 5.3 Mapping and localization

RobotOps must support two distinct workflows.

#### Mapping mode

- use SLAM Toolbox
- consume simulated LiDAR
- build a 2D occupancy map
- display map growth live in the web UI
- allow map save/export
- associate saved maps with metadata

#### Localization/navigation mode

- load a saved occupancy map
- run map server
- localize using AMCL or the selected supported localization approach
- expose localization state and pose
- run Nav2 against the fixed map

For repeatable regression tests and navigation benchmarks, fixed saved maps are the default.

Mapping quality experiments may rebuild maps, but mapping should not be repeated unnecessarily for every navigation run.

### 5.4 Missions

A mission should be represented explicitly and have machine-readable state.

Candidate steps:

- navigate to pose
- navigate through waypoints
- wait
- record data
- capture snapshot
- return to dock
- stop safely

Each mission should produce:

- status
- start/end timestamps
- final result
- useful metrics
- associated recording where enabled

### 5.5 Experiments

Experiments must be configuration-driven and reproducible.

An experiment may define:

- robot configuration
- runtime mode
- world
- initial pose
- goal/mission
- Nav2/controller parameters
- random seed
- fault injection
- recording settings
- metrics
- number of repetitions

Example:

```yaml
name: warehouse_lidar_dropout
mode: sim
world: warehouse_a

mission:
  type: navigate_to_pose
  goal: shelf_07

faults:
  - type: lidar_dropout
    start_seconds: 18
    duration_seconds: 2

runs: 20

record:
  - /scan
  - /odom
  - /cmd_vel
  - /tf
  - /diagnostics
```

### 5.5.1 Current campaign transition

The web campaign is now a client of the canonical backend experiment service.
Backend/ROS owns fresh-stack trials, execution, recording, provenance, metrics,
persistence and localization-based final-pose validation. Browser refresh does
not restart or cancel trials. Legacy browser results remain separate approximate
history. Independent Gazebo contact evidence is now persisted through the backend,
with explicit UNKNOWN coverage. Durable backend report snapshots and separate contact
presentation are implemented; see CURRENT_STATUS for verification and remaining work.

Do not add authoritative experiment truth to browser-local state.

### 5.6 Experiment comparison

RobotOps should support comparison between runs or software versions.

Useful comparison metrics:

- mission success rate
- completion time
- path length
- recovery count
- collision count
- localization failures
- control errors
- sensor dropout rate
- CPU/memory use
- anomaly-detection results

## 6. Map difficulty and navigation benchmarking

RobotOps should maintain multiple custom Gazebo environments rather than relying only on tutorial/default maps.

Suggested benchmark classes:

- easy — open floor, sparse obstacles, wide passages
- medium — office/warehouse corridors, doorways, moderate clutter
- hard — narrow passages, sharp turns, dead ends, tighter clearances
- extreme — dense clutter and/or controlled dynamic obstacles

Each environment should document why it belongs to its difficulty class.

Navigation benchmarking must support running the same mission across different navigation configurations.

Initial comparisons may use multiple Nav2 planner/controller plugin combinations.

Later, a custom Nav2 planner or controller plugin may be added and benchmarked against existing methods.

A benchmark configuration should be able to select:

- map/world
- start pose
- goal or mission
- planner plugin/configuration
- controller plugin/configuration
- number of runs
- random seed where applicable
- fault configuration
- recording settings

Metrics should include, where measurable:

- success rate
- planning latency
- mission completion time
- path length
- path smoothness
- recovery count
- collision/failure count
- minimum obstacle clearance
- localization failures
- CPU/memory use

Navigation method selection must be configuration-driven and reproducible.

## 7. Runtime modes

### 6.1 Mock mode

Purpose:

- fast development
- ros2_control integration
- launch testing
- CI
- control-path verification without Gazebo

Expected backend:

- ros2_control mock components

### 6.2 Simulation mode

Purpose:

- full system validation
- Nav2
- virtual sensors
- experiment execution
- fault injection
- synthetic dataset generation

Expected backend:

- Gazebo Harmonic
- gz_ros2_control
- ros_gz where required

### 6.3 Replay mode

Purpose:

- debugging
- demonstrations
- offline analytics
- dataset inspection
- ML development

Expected backend:

- rosbag2/MCAP playback and/or RobotOps-specific replay adapters

Replay is explicitly read-only. Teleoperation, mission start, controller activation, safe-motion commands, and any other mutating robot action must be disabled or rejected while in replay mode.

### 6.4 Real mode

Purpose:

- physical robot deployment

Expected backend:

- ros2_control hardware interface for base actuation/encoder-style state where appropriate
- normal ROS device drivers for sensors such as LiDAR, camera, GNSS, or other devices that do not need to live behind ros2_control

Real mode must reuse the same high-level ROS-facing contracts used by mock/sim.

## 8. Initial robot

Robot type:

- differential-drive autonomous mobile robot

Initial sensor set:

- wheel encoders
- 2D LiDAR
- IMU
- optional RGB camera

Required software capabilities:

- differential-drive control
- odometry
- TF
- localization
- Nav2
- obstacle avoidance
- teleoperation
- autonomous goal navigation

## 9. ROS requirements

Prefer standard ROS 2 interfaces.

Expected topics/interfaces include where appropriate:

- velocity command interface using `geometry_msgs/msg/TwistStamped` at the Jazzy `diff_drive_controller` boundary
- `/odom`
- `/scan`
- `/imu/data`
- `/joint_states`
- `/tf`
- `/tf_static`
- `/map`
- `/diagnostics`
- Nav2 actions and services

Create custom messages/services/actions only when standard messages are insufficient.

All custom interfaces belong in `robotops_interfaces`.

Topic names must be remappable/configurable. Do not make application logic depend on absolute topic names.

Define and document a TF contract early, including at minimum `map`, `odom`, `base_link`, and sensor frames. Each transform must have a single clear owner.

## 10. Data collection

RobotOps should associate every recorded run with structured metadata.

A run should logically contain:

```text
run/
├── metadata.json
├── telemetry.mcap
├── events.json
├── metrics.json
├── config.yaml
└── result.json
```

Metadata should include:

- run ID
- experiment ID
- robot model
- runtime mode
- world
- mission/scenario
- Git commit
- relevant package/config versions
- timestamps
- fault configuration
- random seed where relevant

Large telemetry files should not be committed to Git.

## 11. Diagnostics

Deterministic diagnostics come before ML.

Implemented first stage (2026-10-10): opt-in, read-only ROS input freshness for
odometry, LiDAR and IMU, with explicit ROS-clock pause/reset handling and standard
DiagnosticArray output. Opt-in launch and optional MCAP recording are verified with
paired Gazebo campaigns. A package-local C++ monitor reduces matched replay CPU
by 73.9%, but still uses about 14% of one core, above the <=10% target. Default
enablement remains deferred pending residual overhead work. Broader health checks and campaign fault integration remain later stages;
standalone bounded sensor faults are now component-qualified; see `plans/deterministic-diagnostics.md`.

Initial health signals may include:

- controller active/inactive
- sensor publication frequency
- stale topic detection
- TF freshness
- localization status
- Nav2 lifecycle state
- CPU
- memory
- recording status
- mission status
- network heartbeat where applicable
- battery/motor status when physical hardware is added

Diagnostics should use clear states such as:

- OK
- WARN
- ERROR
- STALE

## 12. Fault injection

The simulation environment should support controlled faults. As of 2026-10-11,
a bounded standalone LiDAR dropout/stamp-freeze adapter is component/MCAP
qualified. Mission-relative arming, production campaign wiring/evidence and
fault-labelled Gazebo qualification are pending. See CURRENT_STATUS.md.

Candidate fault types:

- LiDAR dropout
- LiDAR noise
- sensor freeze
- camera delay
- IMU noise
- encoder noise
- wheel slip
- reduced actuator authority
- localization disturbance
- artificial network delay

Every injected fault must be logged with:

- type
- severity
- start time
- end time
- affected subsystem

Physical production mode must disable simulation fault mechanisms.

## 13. Machine learning scope

Initial objective:

- anomaly detection for robot/system health

Potential features:

- commanded velocity
- measured velocity
- wheel velocity
- controller error
- IMU features
- localization residuals
- LiDAR/sensor timing
- CPU/memory
- network latency
- battery/motor signals when hardware exists

Start with baselines:

- statistical thresholds
- Isolation Forest
- One-Class SVM

Add deeper models only if baseline performance justifies it.

Evaluate using:

- precision
- recall
- F1
- false-positive rate
- detection latency

No unsupported claims about predictive maintenance.

## 13.1 Persistence direction

Structured metadata belongs behind a backend persistence interface. Use SQLite first for the current local-first / portfolio-demo implementation. PostgreSQL remains a later option if hosted concurrency or multi-user deployment requires it. Large MCAP/media artifacts stay outside the relational database and are referenced by metadata.

## 14. Backend requirements

FastAPI is the default application backend.

Responsibilities:

- robot/mission command API
- experiment management
- dataset metadata
- run metadata
- analytics query endpoints
- user-facing validation
- authentication later if required
- integration with ROS-side gateway/services

The backend must not directly replace ROS lifecycle/control mechanisms.

Before any physical robot is reachable from outside a trusted development network, add authentication, authorization, transport security, and an explicit network trust boundary. Do not expose a generic ROS bridge directly to the public Internet.

A public/interview demo may be implemented earlier only as simulation-only application access. It should use approved operations, bounded sessions/reset behavior, and an explicit application trust boundary. Public demo access must not provide physical robot control, arbitrary shell execution, or direct generic ROS access.

## 15. Frontend requirements

React + TypeScript.

Main screens may include:

- robot overview
- robot detail
- mission control
- experiment runner
- dataset/replay browser
- analytics
- diagnostics

Important frontend rules:

- type APIs explicitly
- do not treat React state as authoritative robot state
- handle disconnected/stale telemetry visibly
- distinguish mock/sim/replay/real mode clearly
- disable command controls in replay mode
- make stale/disconnected telemetry obvious

## 16. Command, timing, QoS, and safety requirements

- Use an explicit velocity-command arbitration path so Nav2, teleop, experiments, and tests cannot race on the final drive command.
- Configure stale-command timeout/watchdog behavior so loss of fresh velocity commands stops the base.
- Use ROS time for simulation-time-dependent logic and test `use_sim_time` behavior.
- Choose QoS explicitly for sensor streams, commands, state, events, and results instead of relying blindly on defaults.
- Treat Nav2 Collision Monitor or similar filters as supplemental software protection, not certified functional-safety hardware.
- Physical emergency-stop/power safety remains a separate hardware responsibility.

## 17. Testing requirements

Testing layers:

1. unit
2. ROS component/node
3. launch/integration
4. mock hardware
5. Gazebo
6. regression scenario
7. hardware later

High-value regression scenarios should include:

- successful navigation
- unreachable goal
- obstacle/recovery
- sensor dropout
- localization degradation
- mission cancellation
- safe stop
- ROS node failure/restart where practical

## 18. CI requirements

CI should gradually support:

- formatting
- linting
- C++ build/tests
- Python tests
- TypeScript lint/typecheck/tests
- ROS workspace build
- launch tests
- mock-hardware tests
- selected headless Gazebo tests

Do not block every small PR on very expensive simulation runs if a separate scheduled/full suite is more appropriate.

## 19. Repository structure

Target structure:

```text
robotops/
├── AGENTS.md
├── README.md
├── docs/
│   ├── PROJECT_SPEC.md
│   ├── ARCHITECTURE.md
│   └── plans/
├── ros2_ws/
│   └── src/
│       ├── robotops_interfaces/
│       ├── robot_description/
│       ├── robot_bringup/
│       ├── robot_control/
│       ├── robot_navigation/
│       ├── robot_diagnostics/
│       ├── robot_recorder/
│       ├── mission_manager/
│       ├── experiment_runner/
│       └── fault_injection/
├── simulation/
├── backend/
├── web/
├── ml/
├── tests/
├── docker/
└── .github/workflows/
```

Only create directories when they have actual content/responsibility.

## 20. Historical milestone framework

New delivery sequencing is in ROBOTOPS_DELIVERY_PLAN.md: public read-only
preparation may run independently of non-blocking reliability work; invited live
operation is separately gated. Retain these milestone numbers as technical history.

### Milestone 1 — Foundation
- repo structure
- ROS 2 workspace
- formatting/linting
- basic CI
- robot description

### Milestone 2 — Hardware abstraction
- ros2_control setup
- mock backend
- Gazebo backend
- prove common high-level control path

### Milestone 3 — Mapping and localization
- custom Gazebo world
- SLAM Toolbox
- live map generation
- map save/load
- map server
- localization on saved map

### Milestone 4 — Autonomy
- Nav2
- autonomous navigation
- selectable planner/controller configurations
- lifecycle bringup

### Milestone 5 — Mission + recording
- mission manager
- rosbag2/MCAP recording
- metadata
- run results

### Milestone 6 — Experiment framework
- configuration-driven experiments
- repeat runs
- metrics
- run comparison

### Milestone 7 — Web platform
- backend API
- live telemetry
- robot status
- mission control
- visualization

### Milestone 8 — Experiment & Validation Platform
- 8A benchmark UI
- 8B benchmark operations/history
- 8C automated campaign prototype
- 8D RViz engineering integration and campaign stabilization
- 8E canonical backend experiment runner
- 8F Validation Integrity v1
- 8G independent Gazebo collision truth
- 8H experiment reports

### Milestone 9 — Reliability Engineering
- deterministic diagnostics
- fault injection
- regression scenarios

### Milestone 10 — Shareable Demo
- safe simulation-only hosted demo
- session/lease and clean reset controls
- basic authentication/access boundary
- no public physical-robot control
- no direct generic public ROS graph

### Milestone 11 — Replay & Data Intelligence
- MCAP replay workflow
- historical failure investigation
- evidence/recording browsing
- richer comparison/analytics

### Milestone 12 — ML stretch milestone
- dataset generation from verified runs and controlled faults
- anomaly labels
- baseline anomaly detector
- measurable evaluation
- dashboard integration
- only proceed if core project schedule and data quality permit

### Milestone 13 — Physical robot
- physical hardware interface
- sensor drivers
- hardware safety boundary / emergency stop
- hardware tests
- verify high-level reuse and sim-vs-real behavior

## 21. CV-quality requirements

Before presenting the project publicly, the repository should contain:

- clear README
- architecture diagram
- setup instructions
- reproducible demo
- safe simulation-only shareable portfolio demo when Milestone 10 is implemented
- example experiment
- example recording/replay
- tests
- CI
- meaningful metrics
- ML evaluation if ML is included
- explanation of sim-to-real design
- short demo video/screenshots later

Do not use invented benchmark numbers in documentation or CV material.
