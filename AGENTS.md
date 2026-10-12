# AGENTS.md — RobotOps

## Purpose

RobotOps is a portfolio-grade, simulation-first ROS 2 robotics validation and operations platform.

The strongest engineering claim of this project is:

> The same live-operation software should work across mock, Gazebo, and physical robot backends through stable ROS 2 interfaces, while the observability/analytics stack should also work against recorded-data replay.

Do not undermine that claim for convenience.

## Direction — updated 2026-10-12

The product is a local Engineering Studio plus an independent static public
Recorded Lab. An invitation-only live lab is a possible later addition. Hosting
must remain £0/month; no paid services without explicit owner approval. No AI
chatbot. ML and physical-robot work each need explicit owner approval to start.

Keep original recorded evidence separate from visitor analysis. Never expose the
existing backend, the Vite proxy or the ROS graph directly to a network. Remote
live access needs owner approval and an independent security review.

`docs/ROBOTOPS_DELIVERY_PLAN.md`, `docs/direction/` and the dated reviews in
`docs/` are history. Their technical and safety contracts still apply; their
process gates are replaced by the working rules under "Development order".
Source and runtime evidence remain authoritative for implementation facts.

For current priorities and known runtime issues, read first:

- `docs/CURRENT_STATUS.md`

For project scope and requirements, read:

- `docs/PROJECT_SPEC.md`

For system design and architectural boundaries, read:

- `docs/ARCHITECTURE.md`

## Target stack

Use these as the default project choices unless there is a strong technical reason to change them:

- Ubuntu 24.04
- ROS 2 Jazzy
- Gazebo Harmonic
- ros2_control
- gz_ros2_control
- ros_gz
- Nav2
- SLAM Toolbox
- nav2_map_server / AMCL for saved-map localization
- URDF / Xacro
- C++ for latency-sensitive ROS components and hardware interfaces
- Python for orchestration, experiments, analytics, and ML
- React + TypeScript for the web frontend
- Three.js for 3D visualization
- FastAPI for the backend
- persistence abstraction for structured metadata (SQLite first; PostgreSQL later when deployment/concurrency justifies it)
- rosbag2 + MCAP for robot telemetry
- scikit-learn / PyTorch for ML
- Docker
- GitHub Actions

Do not introduce major alternative frameworks without a clear reason documented in `docs/`.

## Core architecture rules

1. High-level code must not depend on whether the robot is simulated or physical.
2. `ros2_control` is the main hardware abstraction boundary.
3. Simulation-specific code must remain inside simulation/adaptor packages.
4. Physical hardware-specific code must remain inside hardware driver/interface packages.
5. Web UI code must not directly become the robot safety controller.
6. ROS remains the source of truth for live robot state.
7. Structured application metadata, experiment/run records, dataset references, and reports belong behind a backend persistence abstraction. Use SQLite first for the local-first/demo implementation; PostgreSQL is a later deployment option when concurrency or scale justifies it. Large MCAP/media artifacts remain outside the relational database.
8. Use standard ROS interfaces whenever possible.
9. Custom ROS interfaces belong in `robotops_interfaces`.
10. Do not silently change public topics, services, or actions.

Avoid:

```python
if simulation:
    ...
else:
    ...
```

in high-level application logic.

Prefer adapters that implement a stable contract.

## Supported runtime modes

Design for:

- `mock` — controllable live robot using ros2_control mock components
- `sim` — controllable live robot using Gazebo
- `replay` — read-only historical telemetry; robot command paths must be disabled
- `real` — controllable physical robot using real drivers/hardware interfaces

Expected usage should eventually resemble:

```bash
ros2 launch robot_bringup robot.launch.py mode:=mock
ros2 launch robot_bringup robot.launch.py mode:=sim
ros2 launch robot_bringup robot.launch.py mode:=real
```

Replay may use a separate launch entry point where cleaner.

## Initial robot scope

Start with one differential-drive autonomous mobile robot.

Initial simulated sensors:

- wheel encoders
- 2D LiDAR
- IMU
- optional RGB camera

The simulation environment must eventually include multiple custom maps/worlds with increasing difficulty. Do not rely only on default tutorial worlds.

Mapping and localization are separate capabilities:

- mapping mode uses SLAM to build and save a map
- localization/navigation mode loads a fixed saved map for repeatable tests

Do not add arms, drones, multi-robot scheduling, multiple simulators, or cloud-scale infrastructure until the first robot architecture is stable.

RobotOps is one-robot-per-runtime/session, not one-user-forever. It is local-first for development, but a later portfolio milestone may expose a safe simulation-only hosted demo for friends, recruiters, and interviewers. That demo must not expose a physical robot, arbitrary shell execution, or a generic public ROS graph.

## ROS conventions

Prefer standard interfaces and remappable names rather than hard-coded absolute topic names.

Typical interfaces include:

- velocity command input (`geometry_msgs/msg/TwistStamped` for the Jazzy `diff_drive_controller`; typically remapped to the chosen command topic)
- `/odom`
- `/scan`
- `/imu/data`
- `/joint_states`
- `/tf`
- `/tf_static`
- `/map`
- `/diagnostics`
- standard Nav2 actions/services/topics

Do not invent non-standard topic semantics without a compelling reason. Topic names should remain configurable/remappable.

For ROS 2 Jazzy `diff_drive_controller`, do not assume an unstamped `geometry_msgs/msg/Twist` command: the controller's `~/cmd_vel` interface is `geometry_msgs/msg/TwistStamped`.

## Package design

Keep packages narrow and cohesive.

Suggested responsibilities:

### `robotops_interfaces`
Custom messages, services, and actions only when standard ROS interfaces are insufficient.

### `robot_description`
URDF/Xacro, meshes, ros2_control description.

### `robot_bringup`
Launch composition, runtime mode selection, shared configuration.

### `robot_control`
Shared controller configuration and control-related nodes.

### `robot_navigation`
Nav2 configuration and navigation integration.

### `mission_manager`
Mission orchestration and mission state.

### `robot_diagnostics`
Deterministic health checks and diagnostic aggregation.

### `robot_recorder`
rosbag2/MCAP recording orchestration and metadata association.

### `experiment_runner`
Scenario execution, repeatability, run lifecycle, metric hooks.

### `fault_injection`
Simulation/testing faults only.

Do not create one giant `robotops_node`.

## Web/backend rules

Prefer:

```text
Browser
  |-- commands --> FastAPI / RobotOps backend --> ROS 2
  |
  `-- telemetry <---------------- WebSocket <---- ROS 2
```

The backend should validate application-level commands before forwarding them.

Do not keep critical live robot state only in React component state.

Do not assume software can electrically power on an unpowered physical robot.

Replay mode is read-only: disable teleop, mission start, controller commands, and other mutating robot actions.

Do not expose the ROS graph or a generic ROS WebSocket bridge directly to an untrusted/public network. External access must pass through an authenticated/authorized trust boundary before physical operation is enabled.

React is now an experiment client of the backend campaign service. Keep trial reset/start, readiness, execution, metrics, validation, persistence, and authoritative lifecycle state in backend/ROS components. Preserve legacy browser history as separate approximate evidence; do not restore browser execution loops or add new experiment truth to React.

RViz is an optional engineering/observability companion. Its presence or failure must never alter robot operation, navigation readiness, benchmark metrics, or experiment verdicts. Automated campaigns keep RViz off by default.

## Map and navigation benchmark suite

Maintain a set of custom simulated environments with increasing difficulty.

Suggested difficulty classes:

- easy — open space, simple obstacles
- medium — corridors, doorways, moderate clutter
- hard — narrow passages, sharp turns, dead ends
- extreme — dense clutter and/or dynamic obstacles

Difficulty labels must be backed by documented scenario characteristics, not arbitrary names.

RobotOps should be able to run the same mission across:

- multiple maps
- multiple planner/controller configurations
- repeated trials

Useful navigation benchmark outputs include:

- success rate
- planning time
- mission completion time
- path length
- path smoothness
- recovery count
- collision/failure count
- minimum obstacle clearance where measurable
- CPU/memory usage
- localization failures

## Data and experiments

Experiments are first-class entities.

Each run should be reproducible and associated with:

- experiment ID
- robot model
- runtime mode
- environment/world
- mission/scenario
- software Git commit
- parameters
- fault configuration
- timestamps
- result
- metrics
- recording location

Prefer rosbag2 + MCAP for ROS telemetry.

Do not commit large recordings or datasets to Git.

## Fault injection

Fault injection belongs to simulation/testing infrastructure.

Possible faults include:

- LiDAR dropout/noise
- sensor freeze
- camera latency
- IMU noise
- encoder noise
- wheel slip
- actuator degradation
- network delay
- localization disturbance

Fault injection must never accidentally activate in physical production mode. Real mode must reject simulation fault-injection configuration by default, not merely hide it in the UI.

## ML rules

ML remains a planned stretch milestone if the core project finishes on schedule. Do not remove it from the roadmap, but do not implement it while experiment truth, validation, diagnostics, or fault-labelled data are still immature.

Build deterministic diagnostics, telemetry, reproducible experiments, validation, and metrics first. Prefer generating labelled data through controlled faults and verified trial outcomes before training a model.

Initial ML objective:

- robot-health / anomaly detection

Start with simple, interpretable baselines before deep models.

Evaluate with measurable metrics:

- precision
- recall
- F1
- false-positive rate
- detection latency

Do not claim predictive maintenance without evidence. Do not start the ML milestone unless the user explicitly moves the project into that milestone.

## Code quality

General:

- keep components small
- prefer explicit interfaces
- avoid hidden global state
- validate external inputs
- log actionable information
- fail clearly
- shut down cleanly
- document non-obvious architectural decisions
- remove dead code

C++:

- use RAII
- use smart pointers appropriately
- avoid raw ownership
- use ROS clocks for ROS-time-dependent logic

Python:

- use type hints
- separate ROS node logic from pure computation
- keep pure logic unit-testable without ROS

TypeScript:

- avoid `any` unless unavoidable and documented
- keep API/telemetry types explicit
- separate visualization state from server/robot state

## ROS time, frames, and QoS

- Nodes that depend on simulated time must use the ROS clock and respect `use_sim_time`.
- Keep a documented TF frame contract (`map -> odom -> base_link` plus sensor frames).
- Do not let multiple nodes publish conflicting ownership of the same TF transform.
- Choose QoS deliberately. High-rate sensor streams may use sensor-data-style QoS; commands, state, events, and results need semantics appropriate to their reliability/durability requirements.
- Tests should cover important QoS compatibility assumptions.

## Command and safety path

- Multiple velocity producers (Nav2, teleop, tests) must not race on the final base command topic.
- Use an explicit command arbitration/mux strategy.
- Configure command timeout/watchdog behavior so stale velocity input results in stop.
- Safety filters such as Nav2 Collision Monitor may be used as an additional software protection layer, but must not be described as certified physical safety hardware.

## Configuration

Prefer YAML, Xacro, launch arguments, and environment configuration over hard-coded values.

Never commit secrets.

Use `.env.example` for required backend/frontend environment variables.

## Testing

Testing is a core feature, not cleanup work.

Use layers:

1. unit tests
2. ROS node/component tests
3. launch/integration tests
4. mock-hardware tests
5. Gazebo system tests
6. regression scenarios
7. physical-hardware tests later

When fixing bugs, add regression tests where practical.

A feature is not done because it worked once manually.

## CI expectations

CI should evolve toward:

- formatting/linting
- C++ build/tests
- Python tests
- TypeScript lint/typecheck/tests
- ROS workspace build
- launch/integration tests
- mock-hardware tests
- selected headless simulation tests

Separate expensive simulation suites from fast PR checks when needed.

## Development order

Milestones 1–8 (simulation, mapping, navigation, missions, backend campaigns,
validation, contact evidence, reports) are implemented. Current phases:

0. Get visible: Git history, green CI, Apache-2.0, lean docs, static site v0.1.
1. Real benchmark: warehouse through the normal campaign path, an easy→extreme
   world ladder, both Nav2 profiles, published results.
2. Reliability: LiDAR fault relay in campaigns; navigation regression CI.
3. Showcase: demo video, README rewrite, one-command Docker demo.
4. Physical robot through the existing ROS interfaces (owner approval required).
5. Later, each with owner approval: ML anomaly detection, invited live lab.

Working rules:

- Work on a branch and open a pull request. A change is done when CI is green
  and the owner has reviewed the PR. Per-task approval documents are not needed.
- Explicit owner approval is still required for: physical-robot motion or
  hardware changes, exposing anything beyond the static site to the internet,
  paid services, deleting recorded evidence, and publishing datasets.
- Simulation runs, benchmarks and retries are normal engineering work. A failed
  trial is a result to record and debug, not a stop condition.
- Plan approval is not deployment authorization.

## Definition of done

Before calling a meaningful task complete:

- code builds
- relevant tests pass
- lint/type checks pass where configured
- new behavior has tests where practical
- runtime-mode abstraction remains intact
- no simulation-specific assumptions leaked upward
- errors are handled explicitly
- docs/config are updated if behavior changed
- no secrets or large generated artifacts were committed

If something could not be tested, state exactly what was not verified.

## Codex workflow

Before changing code:

1. inspect relevant files
2. check for nested `AGENTS.md`
3. understand current package boundaries
4. identify the narrowest correct change
5. preserve existing interfaces unless intentionally changing them

For substantial features or refactors:

- create or update a plan under `docs/plans/`
- define success criteria before implementation
- implement in small verifiable stages
- update the plan when important discoveries are made

Do not rewrite unrelated code during a focused task.

## Documentation truth order

When documentation disagrees, use this order:

1. current source code and runtime evidence;
2. this `AGENTS.md`;
3. `docs/CURRENT_STATUS.md`;
4. current architecture and interface contracts;
5. `docs/PROJECT_SPEC.md` and long-term roadmap;
6. historical milestone plans and dated audit notes.

Do not rewrite historical audit notes merely to make old verification look current.

## Current scope boundary

Current / active scope:

- one differential-drive robot per runtime/session
- one Gazebo simulator
- multiple custom maps/worlds with increasing difficulty
- SLAM-based map creation and saved-map localization
- ROS 2 Jazzy
- ros2_control abstraction
- Nav2 autonomy
- selectable Nav2 planner/controller methods
- web operations and telemetry
- missions
- navigation benchmarking
- reproducible experiments
- backend-owned experiment orchestration
- independent validation
- experiment evidence/reporting
- optional RViz engineering integration
- automated regression testing

Planned later:

- broader deterministic diagnostics and campaign fault integration
- safe static public replay/testing and restricted attended live sessions
- recording replay and historical investigation
- ML anomaly detection as a stretch milestone if schedule/data quality permit
- physical robot adapter and sensors

Out of scope for now:

- manipulators
- drones
- fleet scheduling
- multi-robot orchestration
- Kubernetes
- multiple simulation engines
- custom SLAM research
- custom motion-planning research
- cloud-scale fleet infrastructure
- public physical-robot control
- production robot electronics
