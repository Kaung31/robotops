# Isolated sensor faults (version 1)

This opt-in C++ testing adapter supports one bounded LaserScan dropout or header
stamp freeze per process. It is not wired into production bringup, Nav2 or the
campaign service. Diagnostics remain off by default. Use only an isolated ROS
domain while qualifying it; never run it alongside a physical robot graph.

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
ROS_DOMAIN_ID=188 ros2 run fault_injection scan_fault_relay --ros-args \
  -p mode:=sim -p use_sim_time:=true \
  -p experiment_id:=example -p trial_id:=trial1 \
  -p fault_type:=dropout -p severity:=1.0 \
  -p delay_seconds:=2.0 -p duration_seconds:=1.0 \
  -p evidence_directory:=/absolute/existing/parent/new-trial-directory \
  -r scan_input:=raw_scan -r scan_output:=faulted_scan
```

Publish `/clock` and `raw_scan`; observe `faulted_scan`. Input/output are standard
sensor_msgs/LaserScan with best-effort volatile sensor-data QoS. Reliable and
best-effort input publishers are supported. The output requires compatible
best-effort readers. Explicitly move the original sensor publisher to raw input
before any later robot integration: a discovery-time competing-output check is
only a supplementary guard, not an atomic graph ownership mechanism.

Absent/real/replay/mock mode, wall-time operation, unknown/multiple fault types,
nonfinite/unbounded schedules, severity other than 1, invalid identities or
colliding resolved topics fail before data publisher construction. IDs are
1..128 ASCII letters/digits/underscore/hyphen. Delay is [0,3600] seconds;
duration is [1 ns,60 s], converted to integer nanoseconds. All parameters are
immutable. The first observed positive ROS clock anchors delay, and the interval
is [start,end). A paused clock does not expire the fault. Backward clock jumps
abort without rearming. Freeze forwards each current payload using the first
active sample's positive stamp; invalid stamps abort that plan. Other scan fields
are unchanged. Normal forwarding resumes after expiry or abort.

Evidence directory must be new, absolute, with an existing parent. It contains:

- `plan.json`: immutable requested version-1 plan; SHA256 covers exact bytes.
- `events.jsonl`: requested, activated and terminal records, identities, plan hash,
  sequence, ROS nanoseconds, clock epoch, effect count and applied confirmation.
- `seal.json`: exact raw event hash/count and plan hash after graceful closure.

The typed relative `fault_events` topic uses
`robotops_interfaces/msg/FaultEvent`, reliable transient-local depth 32. Standard
ROS diagnostics do not encode experiment identity/application provenance, hence
this separate interface. Activation confirms local suppression or a successful
local publish call; it does not prove downstream receipt, diagnostic detection,
navigation success, pose correctness or collision freedom. JSONL is flushed at
each event; this is not a guarantee against power loss. Shutdown before completion
is `aborted_shutdown`; runtime errors are `aborted_runtime`; clock regression is
`aborted_clock`. An unused expired window is `expired_unapplied`. A missing seal,
hash mismatch or uncertain publish operation means incomplete/uncertain evidence,
including SIGKILL. Never infer application from a requested plan alone.

Build and test from `ros2_ws`:

```bash
colcon build --packages-up-to fault_injection
source install/setup.bash
colcon test --packages-select fault_injection --return-code-on-test-failure
colcon test-result --test-result-base build/fault_injection --verbose
```

Pure C++ policy tests and isolated ROS transport tests are separate from resource
acceptance. Transport covers both input reliability policies, actual diagnostic
detection/recovery, payload/header integrity, mode/configuration guards, paused
and reset clocks, graceful/forced cleanup and evidence hashes, including an MCAP round trip. See
`docs/plans/controlled-sensor-faults.md` for the predeclared resource gate and
staged runner/report integration boundary. No fault-labelled campaign acceptance
or Gazebo wiring is implied by these component tests.

## Owned lifecycle v2 (R1, isolated only)

Explicit `lifecycle_mode:=owned_v2` changes scheduling; omit it to retain v1.
Also supply an absolute `recovery_guard_path` shared by all trials for that
isolated runtime. Defaults: `wall_lease_seconds:=90.0` (0.001..120),
`recovery_seconds:=5.0` (0.001..30). Lease includes startup/armed wait, and cannot
be extended. Parameters remain immutable. Do not connect this to production
scan routing or campaign requests yet.

The local trusted owner calls `fault_control` (FaultControlV2): ARM with the
accepted mission UUID, then BIND_NAV with the first accepted Nav2 UUID. Include
experiment/trial, exact plan SHA256, plan session nonce, current epoch and mission
UUID. Arming/acceptance do not alter scans. Start requires current goal-specific
EXECUTING status plus feedback; binding refreshes the durable status subscription.
No second waypoint or late callback can rearm. STOP covers rejection, mission
failure/cancel/timeout; canceling/terminal Nav2 status and clock reset also stop.
Production owner callbacks are not wired by R1; wall expiry is an independent
fallback, not a substitute for owner cancellation.

States: requested, armed, nav_accepted, execution_started,
activation_acknowledged, effect_observed, stopped_REASON, recovery_requested,
recovery_verified **or** recovery_uncertain. Local affected-sample evidence is
not subscriber detection. Recovery needs two unchanged locally published scans
with strictly advancing positive recent stamps. It does not establish downstream
health or safe robot recovery. A seal means complete local event hashing, not
successful recovery. Wall expiry stops faults even when ROS time pauses.

The exclusive guard survives shutdown/SIGKILL unless local restoration was
verified; restart sharing it is rejected. An uncertain guard requires owner
inspection of stopped owned processes, original sensor/clock flow and intended
routing before a separately authorized recovery/reset. Do not delete it on startup
or choose a fresh guard to bypass quarantine. This is a local filesystem interlock,
not protection from arbitrary host access, hard real-time safety or a global
backend experiment gate (the latter is R2).

New typed `fault_lifecycle_events` (reliable/transient-local depth 32) carries
FaultLifecycleEvent, including session/mission/Nav2 identity and wall evidence.
Old FaultEvent is unchanged; schema_version=2 is explicit for new plan/events/seal.
See `docs/plans/r1-owned-fault-lifecycle.md` and the R1 verification report for
exact tests and remaining campaign/routing qualification.


## R2a attended routing prototype (not qualified)

`nav2_probe.launch.py` is explicit sim-only, owned_v2, dropout-only composition.
It keeps AMCL on healthy scan and sends only costmaps to `fault_probe/scan`.
Default navigation has no injector dependency. A required canonical private
runtime directory holds `routing.guard` separately from R1 `recovery.guard`.
Launch never removes the routing guard. Only a separately owner-approved supervised archive/reset can
release the exact named guard. Tests retain it even after downstream checks and
clean shutdown; relay local restoration alone is insufficient. Relay exit shuts down this composed navigation launch.
This initial route had no input watchdog; see the opt-in watchdog update below.
No unattended owner integration is claimed.

The first routed probe failed diagnostic uint8 decoding in the harness after
consumer recovery checks. Its original guard was later archived/reset under explicit owner approval; the
single supervised rerun failed an observer-attribution assertion and its new guard remains held. Do not run the launch,
reuse pytest basetemp or choose another runtime directory to bypass quarantine.
See `docs/r2a-verification-20261011.md` for retained evidence, limits and required
owner recovery review. P2 has not started. No campaign wiring/report schemas changed.


## Approved recovery preparation follow-up

Private test-boundary decoder now normalizes Jazzy one-byte diagnostic levels
(strict 0..3) and plain integer alternatives. Output-monitor identity, healthy
clock, fault-window age degradation and fresh recovery are all required.
`probe_session.py`/`probe_evidence.py` fsync independent observations incrementally,
including ROS CDR, receipt/source times, filter lines and process evidence.
Future routed tests retain routing.guard for owner review, even on success.

The attended probe now opts into an owned_v2 raw-input watchdog: 15 wall seconds
to first scan, then 2 seconds since last input callback. Default timeout 0 disables
it elsewhere; standalone_v1 cannot enable it. Output suppression does not affect
input liveness. Timeout/competing source triggers runtime failure and composed
Nav2 shutdown while route quarantine persists. No automatic guard reset exists.
This is component-qualified, not a hard-real-time safety guarantee or proof of
actual base stop under upstream loss; no real routed test was run in preparation.

The sole approved healthy baseline failed on a journal clock-property error and
interrupted Nav2 startup cleanup. The property defect is corrected/real-node tested;
no second baseline, guard reset or P2 was performed. Original guard/evidence are
unchanged. Read `docs/r2a-recovery-preparation-20261011.md` and request a corrected
ordinary baseline before any reset or routed retry. Earlier R2a paragraph describes
its historical implementation; the opt-in watchdog above is the latest source.

## R2a-H1 offline correction (not a new live qualification)

The corrected healthy baseline later passed; the owner-approved supervised reset
and one routed rerun are recorded in docs/r2a-supervised-rerun-20261011.md. H1
then corrected only private test attribution/recovery. See
docs/r2a-h1-offline-harness-20261011.md and test/routing_evidence.py.
Intentional suppression uses sealed owned lifecycle timing/count, not all observer
gaps. Both consumers plus strict diagnostics and five fresh matching samples are
required for recovery; uncorroborated omissions stay UNKNOWN. Diagnostic ordering,
clock discontinuities, sensor identity, conflicts and missing evidence fail closed.
Assessment waits for final seal/consumer logs after clean owned shutdown, retains
classification before assertions and never clears a guard. Observer writes remain
synchronous/bounded/lossy; no particular omission cause is claimed.

54 offline regression cases pass. Separate saved-data support does not change the
historical FAILED qualification. New guard remains unchanged; STOP for owner
review before any separately authorized reset/live qualification. No P2/campaign
integration. Earlier preparation paragraphs describe their historical results.
