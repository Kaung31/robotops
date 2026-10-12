# Experiments (Milestone 6 foundation + current transition)

> **Current status (2026-10-10):** React is now a client of the backend campaign
> service. The backend owns trial startup, execution, persistence and cancellation,
> reusing the ROS `experiment_runner` for provenance and recorded-data metrics.
> Browser-local historical results remain labeled approximate and separate.
> Independent validation and collision truth are the next stages. See
> [CURRENT_STATUS.md](CURRENT_STATUS.md).

`experiment_runner` submits sequential `missions/execute` actions to an existing
robot/navigation/mission stack. It does not launch, reset or teleport a backend,
change navigation parameters, publish velocity, or initialize localization.
`mock` and `sim` are supported; `real` and `replay` are rejected. Offline comparison
has no ROS command client. The ROS CLI does not provide faults, random-seed control or a web API itself;
backend orchestration is documented below.

## Run a repeatable round trip

Build/source the workspace and start saved-map navigation as described in
[NAVIGATION.md](NAVIGATION.md). Start the mission server with truthful metadata:

```bash
ros2 run mission_manager mission_server --ros-args \
  -p runtime_mode:=sim -p use_sim_time:=true \
  -p environment:=mapping_lab -p navigation_profile:=navfn_rpp \
  -p map_file:=/absolute/path/lab.yaml
```

Check the mission launch arguments in [MISSIONS.md](MISSIONS.md) if using a custom
configuration. Mock control alone does not supply localization/navigation; mock
experiments also need compatible TF, map and mission/navigation services. Localize the robot at the configured start pose, then run:

```bash
ros2 run experiment_runner experiment run \
  "$(ros2 pkg prefix --share experiment_runner)/config/round_trip.yaml" \
  --output artifacts/experiments
```

The example runs two recorded round trips to `(1.0, 0.3)` and back to `(0, 0)`.
Every repetition requires a fresh `map -> base_link` transform (at most one second
old) within 0.35 m and 0.4 rad of the configured start. A failed start check sends no
mission. Choose mission endpoints that return to the start; there is no hidden
reset between repetitions. Run one experiment at a time without teleoperation or
other direct Nav2 clients. Mission admission prevents overlapping mission goals,
but does not lock out independent clients of Nav2 or the command mux.

Copy/edit the YAML to select repetitions, waypoints, expected robot/mode/environment/
navigation profile, start tolerances and wall-clock timeouts. Unknown fields and
unsupported modes are rejected. Recording is mandatory. Topic and node names resolve
within the runner namespace; use normal ROS remappings for `odom`, TF and the
mission action. The current frame contract is `map` / `base_link`.

## Evidence and artifacts

Each invocation creates a new UUID directory with atomic `manifest.json` and
`report.json`. The manifest includes the exact validated configuration, timestamps,
observed start poses, all parameters from mission manager, drive controller, Nav2
controller/planner/BT/behavior servers, map server and AMCL, and saved-map file
hashes obtained from the live map server's `yaml_filename`. Parameters are checked
before and after every trial and between trials. ROS non-finite limit sentinels
(such as an unset controller limit) use explicitly tagged JSON objects; requested
experiment poses and timeouts still reject non-finite values. A changed parameter invalidates
the trial/experiment; brief changes between observations cannot be detected.

A client-generated action goal UUID is persisted before submission. Feedback
records the mission run UUID as soon as it arrives. Mission UUIDs and artifact paths associate each trial with its immutable mission
metadata, result and finalized MCAP. The mission action schema is unchanged; the
experiment-to-run relationship lives in the experiment manifest. Do not copy large
recordings into Git. Both processes currently require a trusted ROS graph and a
shared local filesystem. File hashes identify saved map files, not independent
proof that a live map topic has not been replaced by another publisher.

Software revision comes from mission metadata and is explicitly `null` when
unavailable. An operator-supplied revision is not proof of the exact running binary.
No Git repository exists yet in this checkout. Fault configuration and random seed
are `null`, meaning unsupported/uncontrolled, not simulated fault-free evidence.
This is configuration and provenance capture, not a claim of bitwise determinism.

## Results and comparison

```bash
ros2 run experiment_runner experiment compare \
  artifacts/experiments/EXPERIMENT_A/manifest.json \
  artifacts/experiments/EXPERIMENT_B/manifest.json > comparison.json
```

Compare matching robot, mode, environment, mission, start conditions and map hashes.
Navigation profiles may differ; inspect the retained parameter snapshots. A
running/interrupted-by-process-death manifest cannot be treated as finalized.

Metrics have explicit units and populations:

- success rate uses **all attempted trials**, including failed/uncertain ones;
  requested and attempted counts are separate, since failures stop remaining trials;
- mission duration uses the mission server's ROS seconds, including preparation
  after clock readiness and recording finalization;
- travelled distance sums planar odometry increments in metres from finalized
  MCAP, including recorded preparation/finalization motion; this is encoder-based
  distance, not ground truth or planned path length;
- duration/distance means use successful trials with available values; sample counts
  are reported. Missing or invalid odometry yields `null` plus an explanation.

Odometry requires increasing positive timestamps, fixed nonempty parent/child
frames and finite positions. Explicit time/frame resets are rejected; a position
jump without a corresponding frame/time reset cannot reliably be distinguished
from motion. Collision count, planning latency, recoveries, clearance, CPU/memory
and statistical significance are not measured in this milestone.

## Failure and interruption

A trial is persisted as pending before submission. Rejection, failed mission,
parameter drift, timeout or SIGINT stops further trials. The runner cancels only
its owned mission and waits for its terminal result, including recorder cleanup.
Cancellation acknowledgement alone is not sufficient. If acceptance or termination
cannot be confirmed, the manifest records uncertainty; do not resubmit until the
live mission/navigation state has been inspected. There are no automatic retries.
A hard-killed runner leaves `state: running` and possibly a pending trial; this is
an incomplete artifact, not permission to resume. Recovery/resume is deliberately
manual because the original robot command may still have executed.

## Verification scope

Portable tests cover validation, pose tolerances, odometry distance and comparisons.
Controlled ROS tests use the actual mission server and MCAP recorder, covering two
trials, invalid conditions, navigation failure, SIGINT cancellation and parameter
drift. `ROBOTOPS_EXPERIMENT_SIM_TESTS=ON` enables two recorded trials on a persistent
Gazebo/Nav2 stack. CI has a separate experiment simulator job. The pre-existing
Gazebo signal-handler deadlock is addressed by the
[simulation-adapter repair](plans/gazebo-shutdown-repair.md), with strict shutdown
checks retained. Separate middleware response timeouts remain a reliability concern.

Run the optional live experiment test in a Jazzy workspace:

```bash
colcon build --packages-select experiment_runner \
  --cmake-args -DROBOTOPS_EXPERIMENT_SIM_TESTS=ON
source install/setup.bash
xvfb-run -a colcon test --packages-select experiment_runner \
  --return-code-on-test-failure
colcon test-result --verbose
```

## Backend campaigns — definitions and execution (2026-10-10)

The backend now persists campaign definitions, server-owned planned trial IDs,
ordered events and draft cancellation in SQLite behind a repository interface.
Creating a definition never commands the robot. Explicit backend execution is
opt-in with `ROBOTOPS_CAMPAIGN_EXECUTION=1`; React submits intent and observes
backend status/history/events. The backend reuses the ROS
experiment_runner for action execution, provenance and recorded-data metrics.

| Endpoint | Behavior |
| --- | --- |
| `POST /api/v1/campaigns` | Validate and save a draft definition; 201 on create |
| `GET /api/v1/campaigns?limit=20&offset=0` | Persistent history, newest first |
| `GET /api/v1/campaigns/runtime` | Execution availability and current runtime reservation |
| `GET /api/v1/campaigns/{id}` | Definition and stable trial IDs |
| `GET /api/v1/campaigns/{id}/events?after=0&limit=100` | Ordered events after a sequence cursor |
| `POST /api/v1/campaigns/{id}/start` | Claim an idle runtime and execute a draft; 202 |
| `POST /api/v1/campaigns/{id}/cancel` | Cancel a draft or request cooperative active cancellation |
| `POST /api/v1/campaigns/{id}/reconcile` | Release interrupted ownership after runtime checks |

An optional `Idempotency-Key` header makes creation retryable: the same key and
normalized definition returns the existing record with 200; changed content is
409. A retry remains valid if its previously selected map later disappears.
Definitions are immutable. Unknown worlds/profiles, incompatible or legacy maps,
nonfinite inputs, duplicate profiles, extra fields, and real/replay definitions
are rejected. Limits: 100 trials total and 100 waypoints. Missing IDs are 404;
storage failures are 503. Execution disabled or unsupported adapters return 501.
Only the simulation adapter executes initially; mock definitions remain valid.

Example request body:

```json
{
  "name": "Mapping Lab round trip",
  "runtime_mode": "sim",
  "world": "mapping_lab",
  "map_id": "control_pad_v1",
  "profiles": ["navfn_rpp"],
  "repetitions": 1,
  "waypoints": [{"x": 0.77, "y": 0.62, "yaw": 0}, {"x": 0, "y": 0, "yaw": 0}],
  "start": {"x": 0, "y": 0, "yaw": 0, "position_tolerance": 0.35, "yaw_tolerance": 0.4},
  "timeouts": {"response": 15, "trial": 180, "cancel": 30}
}
```

Default metadata file: `artifacts/campaigns.sqlite3`; override with
`ROBOTOPS_CAMPAIGN_DB` (absolute path recommended). WAL sidecars belong with the
metadata file. MCAP/media remain external. No browser history is imported or
silently replaced. Existing databases with an unsupported schema version fail
startup explicitly; do not delete them to work around a migration error.

Execution runs one fresh stack and one ROS runner process per trial. The mission
launch receives the selected environment/profile/map as provenance parameters.
Later trials check the previous completed parameter baseline for their profile,
plus the first trial's saved-map hashes, before mission dispatch. CLI `run`
accepts optional `--baseline` and `--map-baseline` manifests for those checks.
ROS/MCAP-derived metrics retain the units and limitations documented above;
completed does not mean independently VERIFIED_SUCCESS or collision-free.

A transactional SQLite lease (database schema v2, upgrading v1 in place) and
`artifacts/runtime.lock` protect the single local runtime. The child ROS runner
inherits the lock descriptor, retaining ownership if the backend dies. Competing
manual stack, navigation preparation, map-save, initial-pose, teleop and mission
mutations return 409 during ownership. Reads and optional RViz remain available.
The lease covers RobotOps APIs; external ROS/launch tools are outside this local
advisory lock. Use one repository/runtime and keep the database path stable.

Cancellation returns persisted intent immediately (`canceling`); the worker
signals only its runner, waits for terminal mission evidence and then stops its
stack. Ownership is released only after confirmed termination and cleanup,
including loss of fresh telemetry. Configure a generous graceful shutdown (for
example Uvicorn `--timeout-graceful-shutdown 90`); a forced kill is interruption.
No automatic retries or resume occur. Unconfirmed termination/cleanup retains the
lease with `interrupted`. Startup quarantines orphan ownership when the file lock
is available; if a child still holds it, reconciliation can recover the record
later. Reconciliation requires the file lock, a stopped managed stack and absent
fresh telemetry; it releases the lease without changing the uncertain outcome.
It never kills an unknown external process. These are local runtime checks, not
physical safety certification or proof of ROS graph absence.

Trial evidence lives under `artifacts/campaigns/<campaign-id>/<trial-id>/`, linked
to the runner manifest and mission run/MCAP. Browser disconnection does not stop
the worker; reconnect using status/history/events. See the
[staged plan](plans/backend-campaign-service.md) for verification and next steps.

## React campaign client — 2026-10-10

The campaign panel creates a definition with an idempotency key, then explicitly
starts it. The browser no longer launches/stops stacks, dispatches mission goals,
estimates campaign metrics or saves new browser campaign outcomes. It polls the
backend every 1.5 seconds, single-flight, and fetches ordered events by cursor.
Timeouts and transport errors preserve the last known state and disable commands
until a fresh observation; polling/unmount never creates or cancels a trial.

`GET /campaigns/runtime` returns `execution_enabled`, `supported_modes`, current
lease `campaign_id`, and `worker_active` for this backend process. Ownership is
independent of history pagination and includes quarantined records. A false
worker flag does not prove a child stopped; another backend process or an orphan
runner may retain ownership. The UI exposes reconciliation only as an explicit
request, subject to the server's lock/runtime/telemetry checks.

Only a pending creation request (key and immutable definition) is saved under
`robotops.campaignRequest.v1`. Lost responses can be retried explicitly using the
same key. Creation retry observes an active/finalized record without starting it
again. A server validation rejection permits correcting the form. No automatic
request retry or mission resume occurs on mount/reconnect. Browser storage must
be writable to start a new request; its failure is surfaced before creation.

Start pose/tolerances are explicit. Optional return uses that fixed configured
pose, never a browser pose observed after a reset. The runner checks the required
start; the form does not reposition the robot. Stop a manual stack before running
a campaign. Saved definitions can populate the form with Use campaign configuration.

Backend history is paged in groups of 20. Exports retain the backend record and
manifest/run references. Duration is ROS seconds; distance is MCAP odometry metres.
Missing values remain unavailable, with independent sample counts for successful
means. Canceled trials without evidence are skipped; failed/interrupted attempts
remain in the finalized-attempt success population. Legacy browser campaigns and
the browser mission dashboard retain approximate historical metrics separately.

## Validation Integrity v1 — localization final pose (2026-10-10)

New runner trials carry `validation` separately from `outcome` / `action_status`.
Campaign completion and its ROS success percentage retain their existing lifecycle
meaning. A completed campaign can contain rejected or inconclusive pose results.
Old manifests and history are unvalidated; they are never silently upgraded.

Verdicts:

| Verdict | Meaning |
| --- | --- |
| `POSE_VERIFIED` | ROS mission succeeded; final localized map pose meets the independent policy and required freshness/provenance checks passed. |
| `POSE_REJECTED` | ROS mission succeeded with usable evidence, but final XY and/or wrapped yaw error exceeds RobotOps tolerance. |
| `INCONCLUSIVE` | Required localization, TF, timing or provenance evidence is missing, stale, invalid, or uncertain. |
| `MISSION_FAILED` | Mission/action did not report successful terminal completion. |

These verdicts assess the final waypoint only. They do not independently verify
intermediate waypoint visits, physical/Gazebo ground truth, obstacle clearance,
collision absence, or successful stopping under a certified safety standard.
Localization covariance is a finite/nonnegative diagonal-threshold check, not a
calibrated confidence guarantee or a full localization health diagnostic.

The runner observes relative/remappable `tf` and `amcl_pose` topics. AMCL observation
uses volatile best-effort QoS, compatible with reliable and best-effort publishers;
retained pre-trial poses cannot establish current-trial evidence. Direct dynamic
`map -> odom`, `odom -> base_link`, latest composed `map -> base_link`, and AMCL
must have current-trial stamps and bounded monotonic receipt ages. AMCL's configured
`transform_tolerance` is subtracted from raw map->odom timestamps before age checks.
The final snapshot is taken upon receipt of the terminal mission result, after
recording finalization, before parameter/file work. It does not wait for a better
pose or command localization updates. A stationary/sparse AMCL publisher may yield
INCONCLUSIVE; missing evidence must not be disguised as a pass.

Independent defaults are 0.20 m XY / 0.25 rad yaw, 1 s TF age / receipt age, 5 s
AMCL age / receipt age, 0.25 m² XY variance and 0.25 rad² yaw variance. These are
RobotOps acceptance settings, separate from the captured live Nav2 goal checker
parameters. The ROS CLI accepts an optional complete `validation` policy mapping
(as in `round_trip.yaml`); the backend campaign adapter currently uses the versioned
runner defaults. Each new manifest stores its effective policy and version. Baseline
and comparison checks preserve that policy; a changed policy is not comparable.

Provenance binds the requested mission, expected settings, action-returned run ID,
runner goal UUID, experiment ID, backend campaign/trial IDs where applicable,
unchanged before/after parameters and saved map hashes. It fingerprints metadata,
result, bag metadata and finalized MCAP files with SHA-256. This supports local
integrity/audit checks; it is not signed authenticity or protection against an
actor rewriting every artifact. Software revision stays unavailable in a Git-less
export instead of inventing a commit. Existing recorder structural/required-topic
checks and recorded odometry metrics remain in use.

The backend adds nullable `evidence.validation`; no database migration, public ROS
interface change, automatic retry, or runtime ownership change is needed. The UI
shows a separate pose-verdict column and error/tolerance details, labels lifecycle
percentages **ROS success**, and keeps legacy results **Unvalidated**.

## Independent contact evidence (2026-10-10)

Each new runner trial has a separate `collision` result, persisted as backend
`evidence.collision`. Existing historical records retain null/missing evidence.

| Verdict | Meaning |
| --- | --- |
| `NO_CONTACT_OBSERVED` | Complete continuous adapter coverage across dispatch through terminal-result observation; no non-support contact observed. |
| `CONTACT_DETECTED` | At least one valid non-support contact observed in the trial window; coverage gaps remain listed. |
| `UNKNOWN` | Coverage/provenance/clock/terminal confirmation is unavailable or discontinuous. |

These verdicts describe monitored contact geometry in the simulation physics engine.
They do not certify real-world safety, minimum clearance, force severity, or unique
collision episodes. Contact-pair entries aggregate first/last occurrence per 50 ms
window. Boundary windows are conservative: an aggregated pair straddling a mission
boundary can produce a positive verdict. CLI reports count trial verdicts, not
collision episodes; ROS success rate remains unchanged. The existing UI continues
to show ROS outcomes and pose validation; contact UI/report presentation is next.

Gazebo's event-only built-in Contact system cannot establish zero from silence.
The model plugin instead requests every current collision body's ContactSensorData
and samples it each unpaused step, including empty results. Complete coverage requires
the exact configured six-body inventory, positive continuous physics steps, and
previously observed normal support contact from this source as a capability check.
Only exact configured wheel/caster-to-control_pad_floor pairs are ignored. Chassis
floor contact, self contact, and obstacle contact remain evidence. Both current
worlds use that floor identifier. A geometry/SDF inventory change must update this
adapter configuration; otherwise coverage fails closed. Supported physics is the
tested Harmonic engine; this is not runtime certification of arbitrary engines.

`ContactEvidence` uses reliable/volatile depth 100 QoS on relative
`validation/contacts`. A new plugin instance gets a fresh source ID. Pause publishes
no heartbeat; clock reset/discontinuity permanently invalidates that instance's
coverage until a fresh model is created. The runner checks source, sequence, body
inventory, support policy, contiguous timestamps, positive physics steps, and a
maximum window length of 250 ms. Missing/dropped windows cannot establish zero.
Its buffer is capped at 100,000 frames; overflow prevents a zero-contact verdict.

The read-only collector begins at dispatch and waits up to one wall second for the
terminal boundary window. An unavailable adapter does not block mission execution.
It saves `contacts-<trial-index>.json` with all collected windows beside the experiment
manifest and records its SHA-256 and topic. This file covers recorder startup and
shutdown margins; MCAP also records the optional topic but is not assumed to cover
those margins. Mission/map/parameter/artifact provenance must still be confirmed;
uncertain mission termination or clock regression forces UNKNOWN. Existing mock
and real adapters can omit this contract and yield UNKNOWN without simulator branches
in high-level code. Replay command restrictions remain unchanged.

Research: [Harmonic Contact system](https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/contact/Contact.cc)
and [Physics contact components](https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/physics/Physics.cc).

## Durable backend reports (2026-10-10)

The campaign panel displays stored contact verdicts, coverage counts, reasons and
evidence references separately from ROS outcome and localized pose validation.
Missing historical contact evidence remains Unvalidated. Contact pairs are bounded
to the first 20 window entries on screen; the report retains the complete stored data.

After a campaign is completed, failed, canceled or interrupted, explicitly choose
**Generate report and check evidence**. This is a metadata operation, never a
robot command, retry, cancellation or runtime-ownership release. It creates a
versioned immutable JSON snapshot in SQLite, containing the campaign definition,
trials, separate verdict populations, per-profile ROS success/sample counts, metrics,
provenance references and artifact checks. Failed/interrupted trials remain in the
attempted population; canceled trials with no runner evidence are not assumed to
have executed. Missing metric samples remain unavailable. Reports do not import
legacy browser estimates or infer a combined experimental pass.

| API | Behavior |
| --- | --- |
| `POST /api/v1/campaigns/{id}/reports` | Check current artifact references and persist/reuse a report. Active/draft campaigns return 409. |
| `GET /api/v1/campaigns/{id}/reports?limit=20` | List saved reports, newest creation first; limit 1–100. |
| `GET /api/v1/campaigns/{id}/reports/{report_id}` | Retrieve a saved snapshot without rechecking files. |
| `GET /api/v1/campaigns/{id}/reports/{report_id}/download?format=json` | Download the complete saved JSON snapshot. |
| Same download path with `format=html` | Download a self-contained, escaped readable HTML representation of the saved data. |

Reports have schema version 1 and a deterministic SHA-256 identity over the complete
payload excluding identity/creation time. Identical campaign and integrity results
reuse the original report and timestamp, including concurrent/retried generation.
Changed campaign data or integrity results create a separate immutable report; old
reports are not overwritten. A campaign changing during generation returns 409.
HTML is rendered from the stored JSON; presentation can evolve without changing
the saved experimental evidence. No report is generated automatically by a GET,
browser refresh, backend restart or runtime worker.

Artifact integrity is **VERIFIED**, **ISSUES** or **UNAVAILABLE**, separate from
experimental verdicts. Generation binds the runner's experiment/campaign/trial/run
identity, outcome, metrics, pose/contact results, config and parameter fingerprints
to the stored backend record. The runner manifest has no prior whole-file hash;
its current hash is captured and its bound fields are checked. Individual mission
metadata/result, bag metadata/MCAP and contact evidence hashes are compared with
their stored fingerprints. No raw ROS reanalysis is performed by the report service.

Reads are confined to `<ROBOTOPS_REPO_ROOT>/artifacts`, using descriptor-relative
opens that reject symlinks, traversal and special files. JSON input is capped at
16 MiB; total bytes verified per report are capped at 512 MiB. Files over budget
are explicitly unavailable, never verified. Missing/mismatched/untrusted files
produce issues without rewriting the original robot outcomes. Artifacts relocated
outside this root remain unavailable/untrusted until a future explicit import path
is designed. Large MCAP files stay outside SQLite. Hashes provide local integrity,
not signed authenticity, atomic cross-file snapshots or ongoing tamper monitoring.
GET/download retains the original check time; generate again for current checks.

The repository migrates SQLite schema 0/1/2 to 3 transactionally by adding the report
table/index. Existing campaigns, events and leases are preserved. Reports are behind
the same persistence abstraction; they do not introduce ROS or simulator imports.

Implementation research: [FastAPI response types](https://fastapi.tiangolo.com/advanced/custom-response/)
and [SQLite transactions](https://www.sqlite.org/lang_transaction.html).
