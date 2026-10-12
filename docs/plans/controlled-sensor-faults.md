# Controlled sensor faults — staged implementation contract

Start only after the local opt-in campaign/resource gate passes. Diagnostics
remain false by default; this stage must not waive the replay CPU target.

## First bounded stage

Implement a narrow simulation/testing adapter package for bounded LiDAR dropout
and timestamp freeze. Use C++ for the live relay and a pure testable policy;
avoid another Python high-rate clock/executor path. Navigation and missions
continue consuming their existing standard LaserScan interface. Remap raw input
and output at launch; never race with the original publisher on the output topic.
Do not introduce browser fault controls or relax campaign fault schemas yet.

Reject real, replay, unsupported or absent runtime mode and invalid configuration
before creating data publishers. Validate finite bounded scheduling values,
known fault types, distinct resolved input/output topics and use_sim_time. Keep
faults off without an explicit plan. Physical production mode must fail closed.

## Versioned evidence before integration

Define immutable version-1 requested plan with experiment/trial identity, target,
type, severity, schedule and config hash. Emit actual activation/end/abort events
with ROS timestamps, clock epoch, confirmation and plan identity. Persist raw
event evidence with a content hash; requested fault is never proof of activation.
Clock regression closes/aborts an active plan; no silent restart in a new epoch.
Cleanup must close events or mark termination uncertain.

Dropout suppresses samples only inside a bounded ROS-time interval. Timestamp
freeze forwards sample contents with the first active sample's stamp, preserving
other fields. A paused ROS clock does not advance the fault schedule; clock
liveness is reported separately in steady time. After the interval, forward
unmodified advancing samples; two valid advances satisfy existing diagnostic
recovery semantics. Identical values alone are not a freeze label.

## Required acceptance

1. Pure-policy tests for boundaries, invalid inputs, no-op, overlapping/unsupported
   plans, pause, backward clock jump, expiry and cleanup identity.
2. ROS component tests with synthetic LaserScan/clock: normal forwarding, dropout,
   stamp freeze, diagnostic latency/recovery, QoS compatibility and one output
   publisher. Assert payload/stamp preservation explicitly.
3. Real/replay/absent-mode rejection and no data publisher creation.
4. Isolated event/recording integrity and no leaked processes. Measure relay cost;
   no claim that passing functional tests establishes acceptable overhead.
5. Only then propose runner/persistence/report integration with optional versioned
   evidence and migration tests. Keep ROS outcome, pose validation, contact truth
   and diagnostic expectations separate; fault detection cannot turn a failed
   navigation mission into a navigation success.

Subsequent work: repeatable fault-labelled scenarios, historical replay workflows,
simulation-only demo/session controls and release documentation. ML requires
explicit milestone authorization and trustworthy labelled data; physical hardware
remains later. No public deployment or physical operation in this stage.

## Version-1 isolated adapter contract (2026-10-10)

One plan per process (therefore overlap/multiple fault types are rejected):
`dropout` or `stamp_freeze`, severity exactly 1, explicit sim mode and simulated
clock, experiment/trial IDs, delay [0,3600] seconds and duration [1 ns,60 s].
The first positive ROS clock observed anchors the delay; interval is [start,end).
Before initialization or after abort/expiry the adapter forwards unchanged data.
Paused ROS time keeps the interval unchanged. Any backward jump notification
aborts the plan, even if time returns before the next scan. No rearming.
A freeze requires a positive well-formed header; otherwise abort without applying.
All parameters, including use_sim_time, are immutable after construction.

Relative `scan_input` / `scan_output` use sensor-data QoS. Explicit remapping into
an isolated raw-input path is required; no production bringup changes yet.
Competing output publishers detected in discovery cause process failure (discovery
is asynchronous, so this guard supplements rather than replaces correct wiring).
Typed `robotops_interfaces/FaultEvent` uses reliable transient-local QoS, depth 32.
Versioned plan JSON bytes are hashed with SHA256; append/flush JSONL records carry
that hash, sequence, identities, ROS time, epoch, effect count and confirmation.
Activation means the relay suppressed or locally published a changed scan;
it does not prove downstream receipt, diagnostic detection or mission success.
The graceful-shutdown seal hashes the raw event bytes. Missing seal, killed
process or mismatched hash means uncertain/incomplete evidence; flushed files
are not a power-loss durability guarantee. Terminal events preserve application
count; a requested/expired plan with no affected scan is explicitly unconfirmed.

Before measurement, isolated relay resource acceptance is <=5% of one CPU core
and <=32 MiB RSS during a >=10-second warm window, with 1000 Hz /clock and 10 Hz
720-ray scans. Functional transport tests are separate from this resource gate;
passing neither enables diagnostics by default nor waives the replay CPU target.

## Isolated stage result (2026-10-10)

Native adapter/policy and actual-effect interface implemented. Component/MCAP
checks and the predeclared isolated resource gate pass; production campaign
schema and bringup are unchanged. See `../sensor-fault-adapter-20261010.md` for
raw evidence and limitations. The first-positive-clock schedule is standalone
only. Follow `fault-campaign-integration.md` for explicit mission-acceptance
arming before production wiring, versioned evidence and old-report compatibility.
