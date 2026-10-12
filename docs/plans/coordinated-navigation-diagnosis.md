# Coordinated navigation-state diagnosis — 2026-10-10

User authorizes continuing remaining work and reports RViz working. The rejected
latch-only adapter remains parked. Observe original Nav2 behavior before choosing
another fix. No fault/hosting/ML/hardware expansion until prerequisites pass.

## Stage 1: read-only native observation

Use temporary plugins that delegate every RPP and SimpleGoalChecker operation to
the installed Nav2 implementation, logging plan/reset, controller XY latch and
checker XY state with ROS timestamps. Keep tolerances, progress, collision,
velocities and backend mission/validation logic unchanged. Log overhead means
these runs diagnose behavior, not qualify resource cost. Preserve baseline files
and restore after bounded runs. Require an original-controller slow trial or
report failure to reproduce; never infer a branch solely from telemetry.

## Stage 2: narrow remedy only after evidence

Investigate coordinated replanning/controller/checker lifecycle. Prefer standard
Nav2 BT/configuration facilities over custom controller internals. Define criteria
before trial results: both-profile system checks, baseline independent verdicts,
three rotated diagnostics pairs, absolute <=10% timing/path difference, existing
CPU/RSS ceilings and clean shutdown. No tolerance or safety relaxation.

## Stage 3: context and delivery

Keep historical failed gates. Record RViz as user-verified. Restore idle runtime,
diagnostics=false, update status/plan and source manifest; report remaining
uncertainty and next gated project work precisely.

## Baseline trace and selected candidate

Five traced original-controller campaigns: 20.769, 21.086, 21.268, 21.313,
36.125 ROS seconds. The fifth captures four same-goal replans with prior RPP
XY latch true and next computation false, goal checker reset from reached state,
and distance moving from 0.14891 to 0.15437 m at the first event. Controller then
uses rotate-to-path behavior and later fails progress. Original profile restored;
trace-only library/resources removed. Diagnosis runs are not resource benchmarks.

Select Nav2's shipped
navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml via a launch
argument, keeping original RPP and SimpleGoalChecker. Goal updates and invalid
paths cause replanning; unchanged valid paths retain both states. Path validity
checked at 1 Hz; local collision checks and recovery stay active. Tradeoff: a
still-valid path is not periodically replaced for route optimization. Do not
claim this is appropriate for every future dynamic scenario without qualification.

Additional system acceptance: both profiles retain one plan over several seconds
on a valid path, replan after a real Gazebo obstacle invalidates a held path,
accept a changed active goal, and pass existing cancel/watchdog/pose checks.
All paired campaign criteria above are frozen before candidate measurements.

## Qualification and additional lifecycle finding

Both profiles pass all four Gazebo system cases; configuration 10 and launch
validation 6 pass. Three uninstrumented off/on pairs pass absolute timing/path
bounds and CPU/RSS/diagnostic/evidence/raw-exit criteria. Accept the predeclared
local opt-in isolated-fault gate only, keeping diagnostics false by default and
original replay target unmet. Native candidate confirmation has one path per
waypoint and no progress failure, but map_server exit -2 exposed duplicate group
SIGINT plus launch forwarding. Add deterministic before-failing (2 interrupts)
regression; signal directly owned ROS launch via Popen first, retaining wrapper
identity guards and group escalation. Final fast suite 280; existing loaded
rendered shutdown 3 pass. Final fresh two-trial canonical check follows backend
restart. Preserve all diagnostic anomalies and historical failed comparisons.
