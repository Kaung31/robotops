# Fault campaign integration — next staged proposal (2026-10-10)

> Planning status, 2026-10-11: Technical proposal retained below. The 2026-10-11 source audit refines the timing contract: arm is separate from activation; ExecuteMission acceptance and navigating feedback do not prove accepted Nav2 execution. Use ../ROBOTOPS_DELIVERY_PLAN.md R1 before implementation.

Status: proposal after the isolated relay gate; no campaign API/schema changes yet.
Read `controlled-sensor-faults.md` and `../sensor-fault-adapter-20261010.md` first.

## Source findings and boundary

`CampaignDefinition` and experiment `model.validate` currently reject arbitrary
fault fields. `ExperimentRunner` writes `fault_configuration=None`; it checks the
mission action acceptance immediately before waiting for the result. The Gazebo
bridge currently publishes standard `scan` directly. Existing campaign/report
models are strict version 1, and reports have content-derived IDs. Preserve all
these existing no-fault semantics and stored evidence.

The isolated adapter starts its delay at its first positive ROS clock. That is
appropriate for synthetic component qualification but **not** the desired
mission-acceptance-relative campaign schedule. Starting this plan during stack
startup could fault the readiness/localization preparation. Do not wire the
current standalone auto-start plan directly into production bringup.

## Small implementation stages and acceptance

1. Add a separate explicit arming contract in `robotops_interfaces` and the native
   adapter. Keep immutable plan/identity/hash and normal forwarding while pending;
   accept exactly one identity-matched arm with positive acceptance ROS time and
   current clock epoch. Schedule from that acceptance time. Reject duplicate,
   stale, wrong-trial and post-abort arms. Persist armed and actual applied events
   separately. Version this schedule change; retain v1 standalone evidence readers.
   Cancel/clock regression before activation must prevent later activation.
2. In the simulation adapter only, opt-in raw scan remapping and relay ownership.
   Default launch is byte/behavior equivalent to current direct scan wiring.
   Validate one output publisher and QoS/TF/frame contracts at runtime before
   accepting a fault trial. No simulation branching in mission/validation logic.
   Preserve mapping, Nav2 profiles, command arbitration and optional RViz.
3. Extend backend/runner with a typed optional versioned single-fault plan behind
   a default-off execution capability. Real/replay/mock reject it on the server
   and adapter. Backend creates durable experiment/trial identities; the ROS
   runner arms only after current mission acceptance. Failed arming cancels and
   confirms mission termination; never leave a goal or relay active on timeout.
   Fresh trial teardown must retain the accepted single-interrupt/identity guards.
4. Persist requested plan and independently verified raw fault events/seal/MCAP
   references through the existing repository/artifact boundary. Introduce a
   deliberate versioned report extension rather than silently changing v1 report
   content hashes. Old no-fault records, idempotency keys and report IDs must
   round-trip unchanged. Missing, tampered, wrong-trial or unsealed evidence is
   inconclusive/untrusted, never proof of application. Add migration/reader tests.
5. Separate fault application, diagnostic expectation and navigation/pose/contact
   verdicts. Detecting an injected fault does not repair a failed ROS mission.
   Record both raw and relayed scan topics plus typed fault/diagnostic events.
   First qualify one baseline/dropout/freeze scenario with reset, acceptance-time
   bounds, measured detection/recovery, independent contact truth, report checks
   and no orphan publishers/processes; then repeated fault-labelled regressions.
   Measure combined loaded-runtime overhead separately from the isolated relay.

Do not add browser execution loops, hosted controls, ML or physical fault support
in these stages. Diagnostics remain opt-in; the original <=10% replay CPU target
is still unmet. User-reported RViz acceptance remains separate from automated
campaign evidence. Update this proposal with discoveries before broadening scope.
