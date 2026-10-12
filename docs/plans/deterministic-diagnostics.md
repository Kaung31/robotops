# Deterministic diagnostics and fault regressions

Date: 2026-10-10. Stages A/B implemented and functionally verified. Default
enablement remains deferred: the replay CPU target is unmet. The isolated bounded
sensor-fault stage now passes component/evidence/resource checks; production
arming/campaign integration remains pending. See
`../sensor-fault-adapter-20261010.md` and `fault-campaign-integration.md`.
Historical stages and measurements below retain their original scope.

## Source findings and choice

At the start of Stage A there was no diagnostics or fault-injection package. Backend health is application
availability; its operations snapshot is not authoritative ROS diagnostics.
Mission-manager fault latches protect uncertain mission termination and must remain
separate. `experiment_runner.model.validate` rejects unknown fields, including
`faults`, and disables real/replay execution. Keep those guards intact.

Begin with an opt-in, standalone, read-only `robot_diagnostics` package. It observes
standard odometry, LaserScan and IMU headers and publishes DiagnosticArray. Do not
change launch composition, control, readiness, campaign outcomes or report schema.
This small stage establishes deterministic freshness semantics before adding fault
actuators or claiming health coverage beyond message timing.

## Stage A contract and acceptance

- Relative, remappable `odom`, `scan`, `imu/data` inputs; sensor-data QoS
  (best effort, volatile) accepts best-effort and reliable writers. Configurable
  enabled inputs; a disabled sensor emits no status, never a fabricated OK.
- Relative `diagnostics` output, reliable/volatile depth 10; stable names
  `robotops/clock`, `robotops/freshness/{odom,scan,imu}`. Hardware ID defaults to
  `robotops`, configurable; no new custom messages.
- Default publish period 0.2 steady seconds, warning age 0.5 ROS seconds,
  error age 1.0 ROS seconds, future-stamp tolerance 0.1 ROS seconds and clock-stall
  timeout 2.0 steady seconds. Thresholds are configurable and validated.
- Missing input or receipt silence beyond error age: STALE. Old stamps despite
  continuing receipts: ERROR. Either age beyond warning age: WARN. Invalid,
  regressing or excessively future stamps: ERROR. Two consecutive valid advancing
  samples are required to reach OK; fresh receipt alone cannot repair a frozen stamp.
- ROS time zero is uninitialized. A clock that stops advancing produces STALE clock
  and STALE stream statuses, with a clock-specific reason, not a sensor-dropout
  diagnosis. Steady time only drives publication and detects absent clock progress;
  stream age uses ROS time. Backward ROS jumps and resumption after clock stall clear
  prior observations. No old epoch can become healthy after reset.
- Pure tests cover threshold boundaries, dropout/recovery, repeated timestamps,
  malformed/future/regressing stamps, clock absence/pause/reset and policy errors.
  Isolated ROS tests prove standard output, QoS compatibility and detection/recovery
  with controlled publishers; no robot command publishers/services/actions exist.
- Build the new package, run the existing fast suite and lint, and record exact
  verification limits. No healthy-value/frequency/localization/controller claim.

Stage A evidence: package build passes, 25 pure freshness tests and 7 isolated ROS
cases pass; the complete fast suite passes 271 tests. ROS tests exercise every input
with reliable/best-effort writers, dropout/frozen stamps/recovery, output publication
and a controlled paused/reset ROS clock. Installed Jazzy messages represent the
DiagnosticStatus byte level as Python bytes; an initial transport abort exposed
an integer assignment in the new adapter, now corrected and transport-tested.
No live stack or Gazebo campaign was changed or run. Logs are under ignored
`artifacts/diagnostics-20261010/`; frontend checks are unnecessary for this stage.

The detection bound is the configured age/stall threshold plus one publication
period in the applicable clock domain, assuming callbacks are scheduled. This is
an observability target, not a hard real-time or physical safety guarantee.

## Later stages (not implemented by Stage A)

### Stage B acceptance and evidence (2026-10-10)

- Add `diagnostics:=false` bringup argument (default may be supplied by exported
  `ROBOTOPS_DIAGNOSTICS=true|false`). Enabled monitor inherits the adapter clock;
  mock and sensor-disabled sim observe odometry only, sensor-enabled sim also
  observes LiDAR/IMU. No monitor process-exit shutdown handler: its failure must
  not stop robot/control/navigation. Keep explicit false as the normal default.
- Record `diagnostics` as an optional reliable/volatile topic. Existing required
  odom/TF recording validation remains unchanged; absent diagnostics cannot fail
  a mission or alter pose/contact evidence.
- Verify launch selection/default/clock, optional recorder behavior, existing mock
  control launch and new package ROS tests. Build both changed ROS packages.
- Run matched fresh-stack one-profile/one-repetition Gazebo campaigns with monitor
  disabled/enabled using the existing backend worker, RViz off. Inspect finalized
  MCAP messages, header/receipt ages and verdicts; verify report integrity and clean
  ownership release. Sample monitor CPU/RSS and summarize cadence/overhead honestly:
  two trials do not establish statistical performance equivalence.
- No frontend/API/schema changes, default enablement or fault actuator in Stage B.

Stage B implementation passes 273 fast tests; ament reports 21 bringup checks
(including mock and Gazebo control launch), 35 diagnostics checks and 11 recorder
checks, without failures/skips. Three ROS packages build; Ruff check/format pass.
Initial launch execution exposed missing executable permission on the new script;
fixed its source mode and added a symlink-install executability regression. Those
failed launches left test publishers in domain 186 and contaminated the first
rerun. Stopped only captured owned test PIDs; a clean domain-185 run passes.

Matched fresh-stack mapping_lab/control_pad_v1/navfn_rpp campaigns, one trial each:

| Monitor | Campaign | ROS duration | Odom path | RobotOps diagnostic arrays |
|---|---|---:|---:|---:|
| off | 8235e0eea29e4bd7af583b5d2c1b2991 | 20.965 s | 1.5739 m | 0 |
| on | d893f9271f994502a07fffd60460865e | 20.910 s | 1.5377 m | 101 |

Both retain ROS success / POSE_VERIFIED / NO_CONTACT_OBSERVED separately, with
termination/cleanup confirmed, no lease after completion and all report references
VERIFIED. Offline MCAP inspection finds all 101 monitor arrays during the enabled
mission healthy, with max stamp age 0.115 s for scan and 0.020 s for odom/IMU.
Mean output period is 0.19479 ROS s (the timer is 0.2 steady s). Both bags also
contain 80 arrays from existing mux/Nav2/control diagnostics publishers: consumers
must filter stable status names, not assume every `/diagnostics` array is this monitor.

Resource limitation: 58 process samples across 32.26 wall seconds measured monitor
CPU at 62.93% of one core and peak sampled RSS 63,778,816 bytes. Eight-second
isolated sensor/clock-only bag replay reproduced 67.82% under profiling, while a
five-second idle/no-clock run measured 2.10%. The replay handled 7,181 subscriptions
(823 monitored sensor samples; the rest predominantly clock) and spent most Python
time in executor/wait-set/event plumbing; pure freshness logic used about 0.007 s
of direct Python time. These are local sampled/profiled measurements, not a
statistical benchmark or proof of no navigation overhead. Two successful missions
do not establish performance equivalence. Keep diagnostics off by default; the
next task is a bounded CPU mitigation design/verification before enabling it by
default or adding costly fault infrastructure. Do not throttle shared robot clock
or alter navigation/control to hide monitor overhead.

Evidence, raw process samples, reports, offline analysis and replay profile are
under ignored `artifacts/diagnostics-integration-20261010/`. Replay allowed only
clock/odom/scan/IMU topics in isolated domain 189, with no command topics. Backend
is restored to default-off diagnostics, stopped runtime and no lease. Broad mapping,
full replay investigation, RViz animation and interactive browser suites were not
rerun; frontend source is unchanged.

1. Record diagnostics as optional MCAP evidence, add fresh-stack opt-in launch
   composition and run a baseline Gazebo campaign. Measure monitor overhead and
   verify unchanged ROS/pose/contact results. Only then enable it by default.
2. Add a sim/testing-only sensor relay in its own adapter package. First faults:
   bounded LiDAR dropout and timestamp freeze. Remap at launch; do not add mode
   branches to navigation/mission logic. Reject nonempty fault configuration in
   real, replay, unsupported or absent mode before creating publishers. No production
   service or browser fault controls in the first relay stage.
3. Define versioned fault plans/events before relaxing experiment schemas: immutable
   requested config, experiment/trial IDs, target, type, severity, schedule, actual
   activation/termination ROS timestamps, clock epoch, confirmation, config hashes
   and raw event artifact hash. Requested fault is never proof it was applied.
   Reset/abort closes or marks events uncertain and cleanup must be confirmed.
4. Add isolated regressions for baseline, dropout, stamp freeze, pause/reset and
   recovery. Measure latency in ROS time (clock stalls separately in steady time),
   false positives and recovery samples. End-to-end Nav2 fault trials preserve ROS
   failure, pose validation, contact coverage and diagnostic expectations separately;
   a detected fault does not make navigation failure an experimental success.
5. Bind fault/diagnostic evidence through runner, persistence and reports with
   backward-compatible optional versioned fields and migration tests. Compare only
   matching fault conditions. Add TF/lifecycle/localization checks in separate
   reviewed stages, reusing existing evidence contracts where possible.

No ML, hosted demo or physical driver implementation belongs in this stage.
Identical values with advancing timestamps are not proof of freeze: a stationary
robot can legitimately produce constant sensor values.

## Stage C: bounded CPU mitigation (2026-10-10)

Preserve every input header, ROS clock jump notification, steady publication,
parameters, names, QoS and verdict separation. Do not sample/throttle shared clock,
sleep the executor to drop observations, or disable transport warnings merely to
make the CPU number lower. Compare the Python adapter against a no-default-event
callback probe on the same isolated sensor/clock recording. The probe is temporary
research, not a production configuration.

If entity trimming cannot meet a local <=10% one-core target and >=70% reduction
against matched replay, use a native rclcpp adapter/core confined to
`robot_diagnostics`, as required by the project's choice of C++ for high-rate ROS
components. Native rclcpp handles /clock without rebuilding Python wait sets. Keep the pure Python policy as an offline reference and test the
native policy against shared adversarial traces; remove the obsolete Python ROS
adapter rather than maintaining two live paths. This is a package-local performance
change, not a navigation/architecture refactor or new interface.

Acceptance: shared pure traces, transport QoS/dropout/frozen stamp/future and
regressing timestamps, zero/pause/reset/clock-source changes and repeated-clock
non-progress. Synchronize native clock-jump state with callbacks without reversing
clock/monitor lock order. Build and run relevant component/control launch tests,
measure matched replay including all process threads, then run a fresh enabled
Gazebo campaign and check healthy MCAP evidence, independent verdicts, report
integrity and clean shutdown. Retain opt-in default regardless of single-host CPU
results; record RSS, sampling/profile limits and any unmet acceptance.

Research: [rclpy Jazzy executor](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/executors.py),
[event callbacks](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/event_handler.py),
[rclcpp NodeOptions](https://github.com/ros2/rclcpp/blob/jazzy/rclcpp/include/rclcpp/node_options.hpp).
Installed source confirms the default Python event waitables and the public native
`use_clock_thread` default; no private executor patches or new framework are needed.

Stage C findings: disabling all default Python event callbacks removed 12
waitables but did not improve matched replay (44.68% versus 45.33% of one core).
That probe was not adopted. The live monitor and pure core are now native C++ in
the same package/executable; obsolete Python ROS adapter/script were removed.
The Python pure policy remains the offline parity oracle. Native policy matches
all levels, reasons and numeric evidence across 3,000 seeded adversarial
evaluations (12,000 statuses). Startup publication periods now explicitly reject
values outside finite [1e-9, 86400] seconds to avoid duration conversion overflow.

Matched replay, all process threads included, excluded the first two seconds
and measured about 6.95 seconds per variant. Python used 53.52% of one core;
native used 13.96% (73.92% reduction), with sampled RSS 57,221,120 versus
18,247,680 bytes. Native dedicated-clock-thread probes measured 13.82% unoptimized
and 15.40% RelWithDebInfo; sharing clock/sensors in the single executor measured
13.96%. These short runs do not establish a significant difference between native
thread choices. Use the single executor to keep callback ownership simple.
No shared clock rate, transport warning, robot control or navigation setting changed.

The >=70% reduction target passes, but the <=10% one-core target **does not**;
the replay acceptance script correctly exits with an assertion for this unmet
resource target. Functional checks pass separately. Do not describe Stage C as
meeting every acceptance criterion or enable diagnostics by default. Further
resource work needs a bounded measurement/design step, not shared clock throttling
or expanding fault infrastructure to mask the cost.

Live verification: fresh backend-owned one-trial navfn_rpp campaign
`86a8f84637eb476288ae671c4d1cce1f` completes with ROS success, POSE_VERIFIED,
NO_CONTACT_OBSERVED and all report references VERIFIED. Its 100 RobotOps arrays
are healthy throughout the recorded mission. Duration is 21.022 ROS seconds and
odometry path 1.5634 m; peak scan stamp age is 0.109 s, odom/IMU 0.020 s.
Monitor CPU averages 7.56% of one core over 31.21 wall seconds (57 samples),
peak sampled RSS 21,532,672 bytes. Earlier Python live baseline was 62.93%;
individual trials are not proof of performance equivalence. Replay's unmet target
remains authoritative for the resource acceptance, even though this live run is
below 10%.

Both changed ROS packages build, 272 fast tests pass, ament diagnostics 54 checks
and bringup 21 checks pass (including mock/Gazebo control). The mock diagnostic
test now filters RobotOps names before evaluating health, avoiding accidental
acceptance of healthy twist-mux arrays. Ruff check/format pass. Reports persist
and regenerate idempotently after backend restart; runtime stopped, lease absent,
diagnostics restored false. Evidence is under ignored
`artifacts/diagnostics-cpu-20261010/`. Broad mapping, browser, RViz animation and
full replay investigation were not rerun. No fault actuators or default enablement.

## Primary-source research

- [Jazzy DiagnosticStatus definition](https://github.com/ros2/common_interfaces/blob/jazzy/diagnostic_msgs/msg/DiagnosticStatus.msg)
  provides OK/WARN/ERROR/STALE and key/value evidence without a custom interface.
- [Jazzy rclpy QoS](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/qos.py)
  defines sensor-data and explicit output profiles; compatibility is tested locally.
- [ROS 2 clock design](https://design.ros2.org/articles/clock_and_time.html)
  requires handling zero/uninitialized time, pause and backward jumps. A ROS-time
  timer alone cannot publish a warning while that clock is stopped.

Direct docs.ros.org pages were access-denied during research; official source and
the installed Jazzy runtime are used instead.


## Stage D: residual native overhead measurement (2026-10-10, complete)

Run interleaved repeated idle, clock-only and full allowlisted replay against
the unchanged native monitor in an isolated ROS domain. Exclude startup from
CPU windows, include every process thread, record per-thread CPU/RSS, diagnostic
health/cadence and wall/ROS progress. Compare a minimal native ROS-clock node
without freshness work if clock-only dominates. Use syscall profiling separately
so instrumentation does not contaminate resource acceptance. Kernel perf is
restricted on this host; do not change system security settings to profile.

Success: a reproducible artifact with three matched observations per condition,
clear attribution bounds and a supported narrow fix only if evidence justifies
one. Never discard clock/sensor observations, change QoS or throttle shared
clock to meet the target. Evaluate executor alternatives against Jazzy source
and clock/pause/reset semantics before adopting anything. If no safe local fix
is justified, record the remaining budget limitation and a concrete next step;
keep diagnostics opt-in and preserve the verified robot operation path.

Stage D evidence: three rotated runs per condition give idle 0.26%, clock-only
12.07%, full replay 12.07% of one core. A separate three-repeat comparison gives
installed full monitor 11.63%, static-executor monitor 11.93%, and minimal native
clock-only node 11.24%. The static candidate offers no benefit and is rejected.
Clock/runtime handling dominates within measurement resolution; precise
function-level attribution is not available with restricted kernel perf access.
All full warm arrays are healthy; absent-clock/input semantics and clean exit
pass. Separate instrumented syscall counts support frequent wait/receive work
but are not CPU percentages.

No production source changes, extra executor configuration, clock throttling or
QoS changes. Measurement acceptance passes; the separate <=10% CPU gate remains
unmet. Keep opt-in default. The next gate is an explicit documented budget
decision based on representative campaign impact or a bounded upstream runtime
profile on a suitable host, rather than another freshness rewrite. Production
suites were not rerun; documentation/source manifest and Ruff are checked.
See `../diagnostics-residual-overhead-20261010.md`; evidence is under ignored
`artifacts/diagnostics-residual-20261010/`.

## Stage E: local opt-in resource decision (2026-10-10, measured; gate failed)

Run three fresh-stack off/on pairs for the same mapping_lab/control_pad_v1
navfn_rpp two-waypoint mission, rotating pair order off/on, on/off, off/on.
Canonical backend owns execution; RViz stays off. No production code changes.
Capture process CPU/RSS and worker execution state every 0.25 seconds. Resource
window uses only trial-running samples after three steady seconds, excluding
startup/readiness dilution; require at least ten measured seconds. This worker
window approximates mission execution and is not exact dispatch-time alignment.

Define the decision before measuring: all six campaigns must complete with
separate ROS success, POSE_VERIFIED, NO_CONTACT_OBSERVED, verified reports, clean
termination/cleanup and released ownership. Enabled recorded diagnostic arrays
must be healthy throughout the mission; disabled bags must contain no RobotOps
monitor arrays. Each matched duration/path change must remain within 10% to
exclude obvious regressions (three pairs do not prove statistical equivalence).
Each enabled warm execution window must use <=15% of one core, <=64 MiB sampled
RSS, and have no orphan monitor process after completion.

This <=15% is a proposed separate local opt-in experimental allowance for this
host/scenario, not a replacement for the unmet <=10% replay/default-enablement
target. If every check passes, document explicit acceptance only for opt-in local
isolated fault-regression development; keep diagnostics false by default and
default enablement deferred. Otherwise retain the gate and investigate the actual
failure. Restore the stopped, unowned backend with diagnostics false afterward.

Stage E results: all six campaigns retain successful separate mission/pose/contact
verdicts, verified reports, released ownership and confirmed process cleanup.
Enabled bags contain 300 healthy arrays, disabled bags none. Warm execution
CPU 7.78–9.38%, RSS 21.48–21.75 MB pass proposed local capacity checks.
However, two paired duration changes (-21.51%, -32.42%) fail the predefined
absolute 10% tolerance; path changes pass. Extra return-leg rotation accounts
for most excess time in the slower disabled runs. Its mechanism is not proven.
The analysis correctly fails its duration assertion; no criteria were relaxed.

All six Gazebo robot logs record exit -11 at teardown, both modes. Process
cleanup/lease release is confirmed but zero-exit shutdown is not. Existing
rendered-sensor regression lacks the fully loaded robot plugin combination.
Overall expansion allowance is not accepted; keep diagnostics false and original
replay target unchanged. Reports survive restart and regenerate idempotently;
no monitor remains. See `../diagnostics-local-budget-20261010.md`; ignored
evidence is under `artifacts/diagnostics-budget-20261010/`. No production code
changes; Ruff and manifest checked, production suites not rerun.

## Next bounded repair: loaded-robot Gazebo teardown

Capture a SIGSEGV debugger backtrace with the normal robot/control/contact
plugins loaded. Plugin-unload warnings alone are not a cause. Preserve signals,
rendered sensors, contact coverage and robot interfaces; do not mask exit status
or remove plugins. Add a regression observing robot odometry/contact output
before SIGINT/SIGTERM and requiring zero exit with no forced termination or
orphan processes. Fix only the stack-proven lifecycle defect within its adapter.
Run existing component/control and rendered shutdown tests plus the loaded-robot
regression, then a fresh canonical campaign and inspect both evidence and raw
shutdown exits. Investigate return-leg rotation variability separately before
reconsidering the failed comparison/resource expansion gate.

### Loaded-robot repair execution (2026-10-10, completed)

Reproduce in isolated ROS/Gazebo domains using normal robot description,
controllers, rendered LiDAR and contact plugin. A temporary package overlay
wraps only gazebo_runner with GDB; installed production files stay untouched.
Require live odometry, scan and contact evidence before shutdown. Capture the
crash and stack before choosing a fix. Add regression first, prove it fails
unfixed, then qualify SIGINT/SIGTERM, existing control/contact/rendered tests
and a fresh canonical campaign after the narrow adapter fix.


Execution discovery supersedes the earlier plugin-lifecycle hypothesis above:
GDB did not capture a SIGSEGV stack. Display-preserving direct stop exits normally;
whole-group stop under GDB produces XIO/exit 1. The ordinary loaded-robot regression
reproduces backend XIO/-11 before repair (1 failed, 2 passed) and passes all three
after preserving Xvfb lifetime. Fix is confined to backend process supervision:
record exact wrapped ROS launch child, verify parent/start ticks, signal it before
wrapper/display cleanup. Native plugins and ROS interfaces are unchanged.

Qualification passes: 277 fast tests; existing runner/rendered shutdown, mock/sim
control and independent contact tests; fresh canonical campaign
595305a9835f4d46a5ffd93549dd6941 with separate successful mission/pose/contact/report
evidence and raw clean Gazebo exit. Runtime stopped, lease released, diagnostics
false. See `../gazebo-teardown-20261010.md`. No remote CI run or manual mapping/UI/
RViz requalification claimed. Return-leg rotation mechanism remains unproven and
is the next diagnosis; prior resource/timing gate is not retroactively accepted.


### Return-leg qualification follow-up (2026-10-10, rejected)

The latch-only RPP candidate passes native and both-profile system tests but
fails all three new off/on duration comparisons. A combined installed-controller/
goal-checker test demonstrates state disagreement after replanning. Slow runs
occur with diagnostics both on and off. Restore original navigation; keep the
rejected draft in ignored artifacts. Six campaigns have clean raw exits and
verified mission/pose/contact/report evidence; CPU/RSS pass the proposed local
ceiling but the combined timing/resource gate still fails. Restoration smoke
campaign passes. Next observe coordinated plan/controller/checker/localization
state; no budget waiver, fault expansion or default enablement. See
`../rotation-qualification-20261010.md` and `rotation-repeatability.md`.


### Local opt-in gate accepted after coordinated lifecycle repair (2026-10-10)

A subsequent native original-controller trace captures same-goal replanning
resetting controller/checker XY state at the localization tolerance boundary.
Use Nav2's shipped valid-path/recovery BT with original RPP/checker. Both profiles
pass real obstacle replan, active-goal update and existing control/validation tests.
Three new off/on pairs pass duration/path comparisons (<=1.16% / <=0.74%), CPU
8.81–9.87% one core, <=20.39 MiB RSS and all diagnostic/pose/contact/report/raw-exit
checks. Accept Stage E's predeclared **local opt-in isolated fault-development**
allowance; this does not accept the old failed measurements, prove statistical
performance equivalence or satisfy the separate <=10% replay/default gate.
Diagnostics remain false. Additional duplicate-SIGINT shutdown regression fixed
with direct owned-launch interrupt; fast 280 and loaded-rendered shutdown 3 pass.
Next use `controlled-sensor-faults.md`; production fault schemas stay strict.
Evidence and limits: `../coordinated-navigation-repair-20261010.md`.
