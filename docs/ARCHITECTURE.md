# RobotOps Architecture

> This file holds the local ROS/interface contracts. The static Recorded Lab is in
> [PUBLIC_DEMO_ARCHITECTURE.md](PUBLIC_DEMO_ARCHITECTURE.md); current phases are in
> [AGENTS.md](../AGENTS.md#development-order). ML diagrams are deferred design
> references, not implementation. The live app is not a public gateway.

## 1. Architectural goal

RobotOps must isolate hardware/simulator-specific details from robot application logic.

The central design principle is:

```text
                    High-level RobotOps software
                              |
                       Stable ROS contracts
                              |
                     Hardware abstraction
               /              |              \
            Mock           Simulation          Real
```

Live navigation, missions, telemetry, experiments, diagnostics, and recording should not require rewrites when switching among mock, simulation, and physical backends. Replay is different: it reuses the observability, diagnostics, analytics, visualization, and ML paths but is intentionally read-only.

### Current product/deployment decisions

RobotOps is one-robot-per-runtime/session and local-first for engineering work.
Approved delivery adds a backend-independent public static Replay + Testing Lab
and, separately, a later invitation-only attended Live Simulation Lab on the
owner's computer. The new architecture is proposed, not implemented. No physical
robot, existing admin backend/Vite proxy or generic ROS graph may be public.

RViz is an optional engineering companion, not part of the control/safety chain. RobotOps may launch RViz, but RViz availability must not change readiness, navigation behavior, benchmark metrics, or experiment verdicts.

Campaign definitions, trial IDs, execution state, evidence references and events now persist server-side in SQLite behind a repository interface. An opt-in lifespan worker reuses the ROS runner with exclusive local runtime ownership; React observes the backend campaign API. SQLite remains the first local/demo metadata store; PostgreSQL remains a later option when hosted concurrency or multi-user deployment makes it useful.

## 2. High-level system

```text
+---------------------------------------------------------------+
|                       Web Application                         |
|                                                               |
|  Robot status | Missions | Visualization | Experiments        |
|  Diagnostics  | Replay   | Analytics     | ML alerts          |
+-------------------------------+-------------------------------+
                                |
               +----------------+----------------+
               |                                 |
        Application API                    Live telemetry
               |                                 |
               v                                 v
+---------------------------+          +-------------------------+
| FastAPI RobotOps Backend  |          | WebSocket/ROS Gateway   |
|                           |          |                         |
| Commands                  |          | Robot state             |
| Experiments               |          | Map / pose / sensors    |
| Dataset metadata          |          | Diagnostics             |
| Analytics queries         |          | Mission state           |
+-------------+-------------+          +------------+------------+
              |                                     |
              +------------------+------------------+
                                 |
                                 v
+----------------------------------------------------------------+
|                            ROS 2                               |
|                                                                |
| Mission Manager | Nav2 | Diagnostics | Recorder | Experiment    |
| TF              | Control | Lifecycle | Fault Injection (sim)   |
+-------------------------------+--------------------------------+
                                |
                         ros2_control / drivers
                                |
              +-----------------+------------------+
              |                 |                  |
              v                 v                  v
            MOCK              GAZEBO              REAL
```

## 3. Layer responsibilities

### 3.1 Presentation layer

Technology:

- React
- TypeScript
- Three.js where needed

Responsibilities:

- display live robot state
- allow users to request operations
- visualize map, pose, path, sensors
- display experiment results
- display diagnostics and ML outputs
- replay previous runs

Must not:

- become the authoritative controller state machine
- own safety-critical robot behavior
- contain Gazebo-specific behavior
- assume real/sim based on topic names

### 3.2 Application backend

Technology:

- FastAPI
- backend persistence abstraction (SQLite implemented for campaign definitions/execution/events; PostgreSQL later when hosted concurrency or scale requires it)

Responsibilities:

- validate user/application commands
- manage experiment definitions
- manage dataset/run metadata
- provide query APIs
- coordinate application workflows
- persist results and reports

The backend may communicate with ROS through a dedicated gateway/client layer.

### 3.2.1 Current experiment-orchestration transition

React now submits campaign intent and observes backend status/history/events. It does not restart stacks, submit trial missions, compute campaign metrics, or own authoritative lifecycle state. Historical browser results remain separate approximate evidence.

Backend execution is now available behind `ROBOTOPS_CAMPAIGN_EXECUTION=1`, using
a transactional lease and an inherited file lock, with simulation assumptions
isolated in its runtime adapter. One runner process handles each fresh-stack trial;
profile parameter and campaign map baselines persist across processes. Uncertain
termination or cleanup retains ownership and prevents automatic retry. Reconcile
only after local runtime checks. The backend exposes runtime reservation discovery
independently of history pagination; its worker flag describes this backend process. See [campaign contract](EXPERIMENTS.md#backend-campaigns--definitions-and-execution-2026-10-10).

Target ownership:

```text
React experiment client
        |
        v
FastAPI experiment/campaign API
        |
        v
Canonical backend experiment service
        |
        +-- reset/start stack
        +-- readiness
        +-- mission execution
        +-- recording
        +-- provenance
        +-- metrics
        +-- validation
        |
        v
ROS experiment_runner / mission / Nav2 interfaces
```

The browser should own presentation and user intent, not trial execution truth.

### 3.3 ROS application layer

Responsibilities:

- missions
- navigation
- robot lifecycle
- telemetry generation
- diagnostics
- recording
- experiment execution
- safe robot command orchestration

This layer should consume stable ROS interfaces.

### 3.4 Hardware abstraction layer

Primary technology:

- ros2_control

Responsibilities:

- expose command interfaces
- expose state interfaces
- isolate backend-specific implementations

Backends for the control path:

- mock
- Gazebo
- physical hardware

Not all sensors belong behind ros2_control. Environmental/perception sensors such as LiDAR and cameras may use normal ROS drivers while preserving the same ROS-facing message contract across simulation and real hardware.

## 4. Mapping and localization architecture

RobotOps supports two intentionally separate map workflows.

### Mapping mode

```text
Custom Gazebo world
        |
Simulated LiDAR
        |
      /scan
        |
 SLAM Toolbox
        |
      /map
        |
  Web visualization
        |
     Map save
        |
 Saved occupancy map
```

Purpose:

- showcase autonomous mapping
- create reusable maps
- validate sensor/TF integration
- generate map artifacts for later navigation

### Localization/navigation mode

```text
Saved occupancy map
        |
    map_server
        |
       AMCL
        |
 map -> odom TF
        |
       Nav2
        |
      Robot
```

Purpose:

- deterministic navigation
- repeatable benchmarking
- regression testing
- mission execution

Do not rebuild maps during every navigation benchmark unless the benchmark specifically targets SLAM.

### Web map data

The web layer may consume:

- `/map`
- `/tf`
- `/tf_static`
- `/scan`
- robot pose
- global/local plan data
- localization/mission status

The UI should clearly indicate whether the robot is in mapping mode or saved-map localization mode.

### Readiness levels

Do not collapse these into one boolean:

```text
stack running != telemetry connected != navigation ready != experiment ready
```

Navigation readiness should require fresh state from the current stack/session, including fresh odometry, scan, AMCL/localization evidence, relevant TF, active Nav2 lifecycle nodes, and action availability. Experiment readiness adds expected environment/map/profile/parameters, start-pose checks, recording availability, and protection against stale state from a previous trial.

A transform merely existing in a long-lived TF buffer is not sufficient evidence that it belongs to the current trial.

## 5. Runtime mode architecture

### Mock

```text
High-level nodes
      |
ros2_control
      |
MockComponents
```

Use for:

- CI
- launch tests
- controller wiring
- fast development

### Simulation

```text
High-level nodes
      |
ros2_control
      |
gz_ros2_control
      |
Gazebo Harmonic
```

Additional ROS/Gazebo integration may use `ros_gz`.

Use for:

- sensors
- navigation
- system behavior
- experiments
- fault injection

### Replay

```text
MCAP / rosbag2
      |
Playback / replay adapter
      |
ROS topics / RobotOps telemetry
      |
Web + diagnostics + analytics + ML

COMMAND PLANE: DISABLED
```

Replay should allow debugging without a live robot and must remain read-only. Command endpoints must reject teleoperation, mission execution, controller commands, and other robot mutations in this mode.

### Real

Control/odometry path:

```text
High-level nodes
      |
ros2_control
      |
Robot hardware plugin
      |
Motor controller / MCU / encoders
```

Perception sensor path:

```text
LiDAR / camera / other sensor
      |
device-specific ROS driver
      |
standard ROS sensor topic
```

Only low-level hardware/device integrations should change; higher-level ROS-facing contracts should remain stable.

## 6. Robot control boundary

For the differential-drive robot:

```text
              Nav2 / Teleop
                    |
       stamped velocity command
                    |
          Differential drive control
                    |
              ros2_control
                    |
        +-----------+-----------+
        |                       |
      states                 commands
        |                       |
     encoders                 wheels
```

For ROS 2 Jazzy `diff_drive_controller`, the controller input `~/cmd_vel` uses `geometry_msgs/msg/TwistStamped`. Upstream command sources should be integrated through explicit remapping/adaptation rather than relying on an unstamped command assumption.

Physical base hardware will eventually implement read/write behavior behind ros2_control interfaces.

## 7. Sensor boundary

Consumers should subscribe to standard ROS sensor topics regardless of source.

Example:

```text
SIM:
Gazebo LiDAR -> /scan

REAL:
LiDAR driver -> /scan

Consumers:
Nav2
Diagnostics
Recorder
Web telemetry
Experiment metrics
ML pipeline
```

No consumer should require knowledge of which LiDAR backend produced `/scan`. The same principle applies to camera, IMU, GNSS, and other device topics; whether they use ros2_control or standalone drivers is an implementation detail below the ROS message contract.

## 8. Mission architecture

Recommended shape:

```text
Web request
    |
FastAPI validation
    |
Mission Manager
    |
ROS actions/services
    |
Nav2 / robot behaviors
```

Mission Manager responsibilities:

- validate current robot state
- start mission
- expose mission status
- support cancellation
- collect mission outcome
- emit structured events
- trigger recording hooks where configured

Mission steps should be explicit and serializable.

## 9. Experiment architecture

```text
Experiment config
      |
Experiment Runner
      |
+-----+-------------------------------------------+
| configure world / parameters / faults          |
| launch or reset scenario                       |
| start recording                                |
| execute mission                                |
| collect metrics                                |
| stop recording                                 |
| persist result                                 |
+-------------------------------------------------+
      |
Run result + MCAP + metrics + events
```

Experiment Runner must avoid embedding scenario-specific logic when configuration can express it.

## 10. Navigation benchmark architecture

Nav2 remains the primary navigation framework, but RobotOps should support multiple selectable navigation configurations.

```text
                    RobotOps Experiment
                           |
                  Navigation profile
                           |
          +----------------+----------------+
          |                                 |
     Planner profile A                 Planner profile B
          |                                 |
          +----------------+----------------+
                           |
                    Controller profile
                           |
                   command arbitration
                           |
                         Robot
```

Later, additional profiles may include:

- different built-in Nav2 planners
- different Nav2 controllers
- route-graph navigation where appropriate
- a custom Nav2 planner plugin
- a custom Nav2 controller plugin

The same mission should be runnable across multiple profiles and maps.

### Map benchmark matrix

```text
                Easy   Medium   Hard   Extreme
Planner A         x       x       x       x
Planner B         x       x       x       x
Custom later      x       x       x       x
```

### Benchmark outputs

Store per-run and aggregate metrics such as:

- success/failure
- planning latency
- completion time
- path length
- path smoothness
- recoveries
- collisions/failures
- minimum clearance where measurable
- localization failures
- CPU/memory use

Navigation profiles and benchmark scenarios must be configuration-driven and versioned.

## 11. Recording architecture

ROS telemetry:

```text
ROS topics
    |
rosbag2
    |
MCAP
```

Structured metadata:

```text
RobotOps Backend
    |
Persistence interface
    |
SQLite (campaign definitions/execution/events implemented; other metadata planned)
    |
PostgreSQL later if deployment/concurrency requires it
```

A recording reference links structured metadata to the telemetry artifact. Large MCAP/media artifacts remain outside the relational database. Local filesystem is sufficient initially; object storage can be added later.

## 12. Diagnostics architecture

The first implemented stage is the standalone, opt-in `robot_diagnostics`
freshness monitor. It observes standard odometry/LaserScan/IMU headers and publishes
standard DiagnosticArray; it has no command paths or connections to readiness or
experimental verdicts. ROS-clock pause/reset is distinguished from sensor receipt
and timestamp aging. Bringup now supports opt-in `diagnostics:=true` (default false,
or exported `ROBOTOPS_DIAGNOSTICS`). Its failure has no process-exit shutdown hook.
Recording includes the optional diagnostic topic with explicit reliable/volatile
QoS; absent diagnostics do not invalidate recordings or become healthy evidence.
See `ros2_ws/src/robot_diagnostics/README.md` and
`docs/plans/deterministic-diagnostics.md` for its contract and staged acceptance.
The live adapter and freshness core now use C++/rclcpp within this package; the
pure Python policy remains an offline test reference. Clock and sensor callbacks
share a single executor, with steady publication and explicit jump invalidation.
Public topics, QoS, status names and verdict separation remain unchanged. This
reduces measured CPU but does not justify default enablement; see current status.
Broader checks and production campaign fault integration remain planned.
The isolated bounded C++ scan-fault adapter is now component/MCAP-qualified;
see `sensor-fault-adapter-20261010.md`.

Use two layers.

### Deterministic health checks

Examples:

- topic freshness
- expected frequency
- lifecycle state
- TF availability
- controller state
- localization status
- process heartbeat
- CPU/memory
- sensor availability

### ML anomaly detection

Consumes telemetry/features and generates an anomaly score.

ML output supplements diagnostics; it does not replace deterministic checks.

```text
Telemetry
   |
   +--> deterministic diagnostics
   |
   `--> feature pipeline --> ML model --> anomaly score
```

## 13. Fault injection boundary

Fault injection should be isolated from normal robot logic.

```text
Experiment Runner
       |
Fault configuration
       |
Fault Injection subsystem
       |
Simulation/backend adapter
```

Never scatter fault conditions throughout navigation or mission code.

All injected faults must emit structured events.

Real mode should reject or disable simulation fault injection by default.

## 13.1 RViz engineering companion

RViz remains the preferred deep ROS visualization/debugging surface for TF, robot model, scans, plans, costmaps, and footprints. RobotOps may start/stop an auxiliary RViz process with approved configs. RViz failure must not stop the robot stack. Automated benchmark campaigns keep RViz off by default so GUI load is not part of benchmark execution. Engineers may attach RViz separately when debugging a campaign.

## 14. Web communication

Separate command/control API traffic from high-volume telemetry where practical.

### Command path

```text
Browser
   |
HTTP/Web API
   |
FastAPI
   |
validation
   |
ROS service/action/client
```

### Telemetry path

```text
ROS
 |
WebSocket / gateway
 |
Browser
```

Foxglove-compatible transport may be used where useful, but RobotOps application semantics should remain independent from one visualization vendor.

Do not expose a generic ROS bridge directly to an untrusted/public network. For physical operation, external clients must cross an authenticated/authorized application boundary with transport security.

A future hosted portfolio demo is allowed only for simulation. It should use bounded sessions/leases and reset the simulator between visitors. Public/demo clients may request approved application operations, but must not receive arbitrary shell access, direct public ROS graph access, or physical robot control.

## 15. State ownership

### ROS owns

- live controller state
- lifecycle state
- live robot pose
- sensor streams
- navigation state
- mission execution state where mission manager is ROS-based

### Backend persistence owns

- experiment definitions
- run metadata
- dataset references
- reports
- historical analytics metadata
- user/application configuration where applicable

### Browser owns only

- presentation state
- temporary UI interactions
- selected panels
- visualization preferences

Never make browser memory the only source of mission or robot truth.

In replay mode, historical data is immutable input. The UI/backend must not reinterpret replay as a live controllable robot state.

## 16. Command arbitration, timing, QoS, and safety architecture

### Command arbitration

Multiple command producers must not publish independently to the final drive-controller input.

Recommended shape:

```text
Nav2 --------\
Teleop -------+--> command arbiter/mux --> optional safety filter --> diff_drive_controller
Test runner --/
```

The command path must define priority/ownership explicitly.

For the base controller, configure stale-command timeout/watchdog behavior so loss of fresh commands causes a stop.

### Time

Simulation-time-dependent nodes must use the ROS clock and consistently respect `use_sim_time`. Persist both run-relative/ROS timing and wall-clock metadata where needed for later correlation.

### QoS

QoS is part of the interface contract, not an implementation afterthought. Choose profiles deliberately for:

- high-rate sensor streams
- commands
- robot state
- diagnostics/events
- latched/static-like data where durability matters

Test important publisher/subscriber compatibility.

### TF ownership

Document the frame tree, typically including:

```text
map -> odom -> base_link -> sensor frames
```

Each transform must have a single clear publisher/owner. Avoid duplicate `odom -> base_link` or equivalent transform publication.

### Physical safety

Future physical mode must assume browser/network connections can fail.

Future physical mode must assume browser/network connections can fail.

Requirements:

- robot must not continue uncontrolled because the browser disappeared
- velocity commands should use appropriate watchdog/timeout behavior
- safe stop should be available independently of visualization
- lifecycle/controller state transitions should be explicit
- command validation should reject invalid state transitions

Remote software activation is not equivalent to electrical power-on.

Nav2 Collision Monitor or similar software filters can add useful collision protection, but they are not a substitute for hardware emergency-stop and certified safety mechanisms where those are required.

## 17. Repository architecture

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
│   ├── worlds/
│   ├── models/
│   └── scenarios/
├── backend/
├── web/
├── ml/
├── tests/
├── docker/
└── .github/workflows/
```

## 18. Dependency direction

Prefer dependencies to flow inward toward stable abstractions.

Good:

```text
web -> backend API
backend -> ROS gateway
mission manager -> Nav2 interfaces
experiment runner -> mission/recording/fault interfaces
Gazebo adapter -> ros2_control contract
physical adapter -> ros2_control contract
```

Avoid:

```text
mission manager -> Gazebo APIs
web -> Gazebo APIs
ML -> simulator internals
navigation -> FastAPI internals
```

## 19. Data model sketch

Core application entities:

### Robot
- ID
- name
- model
- runtime mode
- status

### Mission
- ID
- definition
- state
- start/end
- result

### Experiment
- ID
- configuration
- requested run count
- software/config version

### Run
- ID
- experiment ID
- mode
- result
- timestamps
- metrics
- recording reference

### Dataset/Recording
- ID
- run ID
- path/object reference
- format
- size
- topic metadata

### FaultEvent
- type
- severity
- start/end
- subsystem

### ModelEvaluation
- model/version
- dataset
- metrics
- threshold/configuration

## 20. Observability

Every major subsystem should produce enough information to diagnose failures.

Prefer structured logs/events for:

- mission transitions
- experiment transitions
- recording state
- lifecycle changes
- faults
- failures
- recovery actions

Use timestamps consistently.

When simulation time is active, ROS-time-sensitive components must respect ROS time.

## 21. Design checkpoints

Before progressing to later milestones, verify:

### Checkpoint A
Mock backend and Gazebo backend expose the same controller-facing contract.

### Checkpoint B
Nav2 and mission code contain no Gazebo-specific branching.

### Checkpoint B2
SLAM can generate/save a map from the custom simulated world, and localization/navigation can later reuse the fixed saved map without rebuilding it.

### Checkpoint C
Experiments are reproducible from checked-in configuration.

### Checkpoint D
A run can produce recording + metadata + metrics.

### Checkpoint E
The web app can reconnect without corrupting robot/mission state.

### Checkpoint F
Fault injection is isolated and disabled in real mode.

### Checkpoint G
ML operates on a stable telemetry/feature schema rather than simulator internals.

### Checkpoint H
Replay mode is provably read-only and command endpoints reject mutations.

### Checkpoint I
Physical sensor integrations can use standalone ROS drivers without forcing them behind ros2_control.

### Checkpoint J
Before remote physical operation, authentication/authorization and the ROS/network trust boundary are explicitly tested.

### Checkpoint K
At least two navigation profiles can run the same mission on the same fixed map and produce comparable, reproducible metrics.

### Checkpoint L
The benchmark suite includes documented environments of increasing difficulty rather than a single demonstration map.

## 22. Future physical hardware integration

When physical hardware is introduced:

1. create hardware-specific package/plugin
2. implement ros2_control command/state interfaces
3. add real sensor drivers
4. map hardware data to the existing ROS topic contract
5. preserve high-level configuration where possible
6. add hardware tests
7. compare equivalent sim vs real missions

The following should not require redesign:

- frontend
- backend experiment model
- mission manager
- Nav2 integration
- recorder
- historical analytics
- diagnostics API
- experiment reporting
- ML pipeline schema

That is the key architectural acceptance criterion for sim-to-real readiness.

### Localization-based validation boundary (2026-10-10)

`experiment_runner.validation` is pure deterministic logic; `observation` is its
read-only ROS adapter. A final snapshot and independently captured policy feed a
separate pose verdict, bound to local mission/map/parameter/recording provenance.
The campaign service persists that evidence without interpreting a pose verdict
as mission termination, cleanup, or permission to release runtime ownership.
React displays it without calculating new truth. `POSE_VERIFIED` describes final
localized pose only. Contact evidence uses a separate read-only simulation adapter;
physical ground truth remains a later milestone. See the contracts in EXPERIMENTS.md.

### Independent contact evidence boundary (2026-10-10)

`robot_simulation` owns the model-scoped Gazebo contact plugin and the exact reduced
collision-body/support-floor inventory. It samples requested ContactSensorData at
every unpaused physics step and publishes 50 ms accumulated windows on relative
`validation/contacts` using `robotops_interfaces/ContactEvidence`. This is an
additive, read-only ROS contract; no Gazebo types enter backend/experiment logic.
The plugin publishes through its own ROS context and creates no command, TF,
odometry, controller or safety paths. Its topic is configurable in the plugin SDF.

`experiment_runner.contact_observation` collects bounded windows across the trial,
and pure `contacts.evaluate_contacts` checks coverage/continuity. The finalized JSON
evidence and SHA-256 are persisted beside the experiment manifest, with optional
MCAP recording of the same topic. Backend `evidence.collision` stores the result;
ROS lifecycle, pose verdict, runtime lease and cleanup rules remain separate.
There is no combined experimental pass or authoritative browser computation.

### Durable report boundary (2026-10-10)

`campaigns.reports` derives finalized-campaign summaries and audits confined local
artifact references without accessing ROS or command paths. `CampaignRepository`
persists immutable versioned report snapshots; SQLite schema 3 adds a reports table
and index without changing campaigns/events/leases. Generation compares the campaign
snapshot inside its write transaction to reject concurrent changes. Identity covers
the source snapshot and integrity results; retries reuse identical reports.

The API exposes explicit generation, saved-report retrieval and JSON/HTML download.
HTML is an escaped representation of saved JSON, with no scripts or remote resources.
React presents backend contact verdicts and report integrity without recalculation
or local evidence persistence. Artifact integrity remains separate from ROS success,
pose/contact verdicts, cleanup, ownership and physical safety. See EXPERIMENTS.md for
verification scope, limits, API and legacy behavior.
