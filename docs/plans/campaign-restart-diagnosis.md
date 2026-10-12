# Campaign restart diagnosis — 2026-10-09

> Planning status, 2026-10-11: Historical diagnosis log, retained unchanged below. Later source/runtime fixes and the approved delivery plan control new work.

## Scope and acceptance criteria

Audit the existing browser campaign and gateway before changing behavior. Reproduce
one navfn_rpp trial on control_pad_v1 with two waypoints and a 180-second
mission timeout. Correlate physical Gazebo pose, ROS TF/AMCL/odom, HTTP and
WebSocket telemetry after mission acceptance. Preserve optional RViz and existing
Nav2/control/mission contracts. Any confirmed fix needs focused regression tests
and portable checks; do not call the campaign reliable without runtime evidence.

## Initial source findings

- BenchmarkCampaign stops the stack, requires three stopped polls plus 900 ms,
  starts rendered sensors under Xvfb with RViz disabled, waits for readiness,
  submits a recorded waypoint mission, polls HTTP every 500 ms, and saves browser
  history. Final cleanup stops the stack, including managed RViz.
- POST stack awaits prepare_navigation before returning its original startup
  snapshot. The browser's subsequent 75-second readiness deadline excludes this
  preparation time. Stop is synchronous inside an async HTTP handler.
- Readiness flags reset on stop/start, but AMCL receipt is not used. Latest TF
  availability is used without an explicit age test or reset of the TF buffer.
  An existing test explicitly allows ready without any AMCL pose receipt.
- The backend/gateway and WebSocket survive ROS stack restart. WebSocket clients
  get latest snapshots and reconnect after one second on socket closure.
- Odometry and AMCL both write the same unframed pose field. This is a separate
  representation weakness; it does not by itself establish a restart freeze.
- Completion uses observed activity or a changed run ID plus terminal mission
  state; trial distance is approximate browser polling, not recorded ROS metrics.

## Runtime constraints discovered

The existing backend PID 89740 and its mission child inherited
ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET and no RMW_IMPLEMENTATION override, unlike the
requested Cyclone DDS / LOCALHOST verification environment. Another client was
restarting this backend's stack during inspection. A diagnostic start returned
409 (already active); no diagnostic mission has been submitted at this point.
Coordinate ownership before an isolated trial. Repository is a source export
without .git; its Python 3.12 virtualenv is usable inside Distrobox, not the host.

## Observations and verification so far

A live readiness response reported waiting_scan, odom_available=true,
scan_available=false, map_available=false, localized=true and map_to_base=true.
Thus localization can be reported before the full current startup evidence is
present, but ready remained false. This does NOT establish premature mission
submission or the cause of the reported motion problem. A Cyclone/LOCALHOST
observer saw only /parameter_events and /rosout; this observation cannot be used
to diagnose the differently configured live stack's sensors as absent.

Portable checks inside jazzy: 39 backend tests passed, Ruff format and lint passed.
Existing source-manifest entries all match; the new diagnosis document requires
manifest regeneration. No runtime behavior has been changed. No isolated mission,
Gazebo physical motion, RViz RobotModel motion or browser rendering comparison has
yet been verified. The active client's restart must be coordinated first.

## Next diagnostic steps

1. Stop the other browser campaign; preserve existing logs/results.
2. Run backend and observers with explicit Cyclone DDS and LOCALHOST, sourcing
   Jazzy and the installed workspace. Do not mix discovery environments.
3. Use the existing map and a checked free-space two-waypoint route. Capture
   stack phase, mission acceptance/run ID, /clock, odom, scan, AMCL, both dynamic
   TF edges, HTTP and WebSocket pose. Capture Gazebo physical pose independently.
4. Open RViz explicitly for this diagnostic only, after restart. Campaign defaults
   remain open_rviz=false. Compare all three representations during navigation.
5. Repeat the restart once to test generation/freshness behavior. Only patch the
   confirmed failure and add a regression reproducing it. Re-run portable and
   targeted ROS checks; preserve evidence of any failures.

## Conditional next milestone (not approved as a reliable baseline yet)

After the diagnostic acceptance criteria pass, prepare the canonical service in
small stages:

1. Define server-owned campaign/trial IDs, state transitions, cancellation and
   restart recovery semantics. Persist definitions and events in SQLite or atomic
   files; retain existing artifact schema and historical browser results.
2. Have one backend worker own stack leases, restart/readiness and trial sequencing.
   Invoke the existing ROS experiment_runner for one trial per fresh stack,
   retaining parameter snapshots, drift checks, start tolerance, goal IDs,
   cancellation, MCAP and recorded odometry metrics. Preserve a campaign-level
   parameter baseline across these one-trial invocations; do not accidentally
   discard drift detection at process boundaries.
3. Add create/status/cancel/history APIs and resumable progress events. Test browser
   disconnect, duplicate requests, backend restart, cancellation during startup
   and execution, infrastructure failure, replay rejection and optional RViz.
   Never automatically replay an uncertain previously accepted mission.
4. Migrate React to an experiment client. Explicitly label historical approximate
   browser distance separately from recorded odometry metrics. Test the same
   route/profile matrix before removing the browser executor.
5. Keep independent validation, physical collision truth and report generation as
   subsequent milestones; Nav2 success remains distinct from verified success.

Frontend typecheck and production build also passed (existing large-bundle
warning). Source manifest regenerated for this documentation-only audit.


## Follow-up evidence — 2026-10-10

The user stopped the prior runtime and authorized an isolated diagnostic. Applied
the supplied documentation update after comparing it with source, preserving
previous documentation under ignored artifacts/context-update-backup-20261009.
The supplied manifest was not copied; regenerate from the final source tree.
Corrected the architecture wording to say SQLite is planned, not implemented.

With backend and all ROS children using Cyclone DDS / LOCALHOST, the actual browser
campaign ran navfn_rpp, one repetition, two free-space waypoints (0.880, 0.508, 0)
and (0, 0, 0), a 180-second timeout, and the existing control_pad_v1 map associated
with mapping_lab. The campaign restarted an existing manual navigation stack.
It completed successfully: campaign duration 40.255 s from pre-submission to
observed completion, approximate browser distance 1.618 m. ROS run
`e030b50016924e318d845e1e0b53c221` reports both waypoints completed, 21.242 ROS s,
22.886 wall s, and a 3.75 MB MCAP. These clocks/intervals measure different things;
do not present browser duration or distance as independent verification.

During the trial, physical Gazebo pose had maximum displacement 0.884 m, map TF
0.884 m, odometry 0.886 m and WebSocket pose 0.886 m. The diagnostic WebSocket
stayed connected through the restart. Fresh AMCL messages arrived during motion.
These observations reject a persistent post-acceptance pose freeze for this run.
Managed RViz was explicitly opened after restart for diagnosis, initialized
RobotModel/map, and exited with stack cleanup. Its log includes a map GLSL sampler
error. Direct RViz RobotModel animation was not visually verified; healthy TF is
not proof of RViz rendering. Campaign defaults remain RViz off.

A second campaign on an otherwise unchanged backend with diagnostic stack sampling
also completed both waypoints (run `4d1fdafd676349c8b80bf231841d2faf`). Browser
screenshots before/during navigation show the marker move and displayed pose
change to (0.78, 0.40). This confirms the web rendering path in the repeat.
One attempted repeat while the diagnostic backend was restarting generated a
zero-duration Failed to fetch entry; exclude it from navigation results.

Local evidence is in ignored artifacts/campaign-diagnosis-20261009: campaign.json,
summary.json, observations.jsonl, gazebo.jsonl, before-motion.jpg,
during-motion.jpg and thread-stacks.txt. Existing MCAP/run artifacts are preserved.

### Reproduced delay, separate from a motion freeze

The first campaign spent 131.793 seconds before pre-submission timing began.
Readiness HTTP latency median was 12.626 seconds across 16 ready responses;
another request in the profiled repeat took 12.455 seconds. AMCL answered a
separate CLI lifecycle query immediately, while the gateway parameter service
timed out. The backend approached one CPU core of Python work.

Thread snapshots repeatedly show the gateway's odometry callback inside full-map
occupancy validation or deep-copy. TelemetryStore.publish dumps, validates and
copies the entire cached map for every pose update, then copies it again for each
subscriber. A local timing check on the existing map measured roughly 27 ms per
publish even without subscribers. Recorded odometry is about 50 Hz, plus scans
and AMCL; this work competes with service/action callbacks in the same default
mutually exclusive ROS callback group. The UI useControlCenter refresh starts
another request every 1.5 seconds regardless of pending completion; readiness
calls taking 12 seconds accumulate and delay campaign HTTP requests further.

The screenshot at restarting simulation therefore does not demonstrate failed
navigation. Long startup and request delays are confirmed. The original reported
post-acceptance no-motion symptom has not reproduced in two successful runs.

### Causal scheduling probe and narrow proposal

A diagnostic launcher capped only gateway odometry/scan publication at 10 Hz
without changing ROS publishers, Nav2 or the repository's application code.
Five readiness requests still took 12.48–12.64 seconds. The telemetry-copy cost is
real, but a rate cap alone is not an adequate fix for service responsiveness.
The diagnostic trial nevertheless succeeded (run d2f9afb24d8d497fa2bc7075628d648c).

A separate ROS probe reproduced the existing telemetry-store workload on incoming
odometry and issued identical AMCL lifecycle requests using two clients. Both
used the same node and two-thread executor; one client shared the subscription's
default mutually exclusive callback group and one had a separate mutually
exclusive group. In three repetitions, shared-group responses did not complete
within 3 seconds; separate-group responses completed in 0.0085, 0.0160 and 0.0108
seconds, all reporting active. Evidence: callback_probe.py and callback-probe.json.
This establishes callback-group starvation under the telemetry workload as a
cause of the reproduced lifecycle-query delays. It does not establish that the
original screenshot captured a failed mission.

Proposed smallest production change, for review before implementation:

1. Give RosGateway's readiness lifecycle/manager clients a dedicated callback
   group so heavy sensor callbacks cannot exclude their response handlers.
   Retain the existing two-thread executor, interfaces and readiness criteria.
2. Make useControlCenter refresh single-flight so slow requests cannot accumulate;
   guard against applying responses from an older lifecycle state.
3. Add a targeted ROS test with the actual telemetry/map workload and service
   responses, plus a browser polling regression with delayed responses. Repeat
   the one-profile restart campaign and manual mission/RViz lifecycle checks.
4. Track map-copy optimization and current-generation TF/AMCL freshness as distinct
   follow-ups. Do not silently replace benchmark metrics, relax readiness or
   fold these changes into an experiment architecture rewrite.

A full-rate diagnostic gateway comparison with isolated readiness clients follows
below. Diagnostic launchers/probes live only in ignored artifacts; production
Python and TypeScript remain unchanged.


### Full gateway comparison outcome

A final diagnostic launcher put only the gateway lifecycle/manager clients in a
separate mutually exclusive callback group. Telemetry ran at its original rate;
the rate-limit diagnostic flag was off. Eight readiness responses took
0.215–0.930 seconds and all six lifecycle nodes reported active once startup had
settled. This removes the repeated six two-second response timeouts seen with
shared callback groups. The original browser campaign then completed both goals:
run c469cd7d6e3d47338a197e330ededfd5; browser mission interval 32.954 seconds.
See separate-readiness.json and campaign-isolated-clients.json. This is a causal
comparison supporting the proposed callback-group fix, not a production patch or
an independent VERIFIED_SUCCESS verdict.

All experimental callback changes were confined to an ignored diagnostic launcher.
No backend, ROS package or frontend source was edited. Restore the ordinary
backend launcher after diagnostics; leave the robot stack stopped.

Verification after documentation changes: 39 backend tests passed, frontend
typecheck/build passed, Ruff formatting/lint passed. The existing production build
has a non-fatal large-bundle warning. Temporary diagnostic Python scripts were
also formatted/linted because this Git-less export's Ruff scan includes artifacts.
No ROS packages changed or required rebuilding; this task ran live ROS/Gazebo
campaigns rather than rerunning all historical heavy system suites.

## Stabilization implementation — 2026-10-10

Authorized narrow change: isolate gateway readiness clients from sensor callbacks
and serialize UI polling, invalidating pending polling on control actions and
effect cleanup. Keep readiness criteria, telemetry rate, executor thread count,
ROS interfaces and campaign metrics unchanged.

Acceptance: production gateway service responses complete while a sensor callback
holds its group; delayed UI polls do not overlap or apply obsolete results;
backend tests, frontend tests/typecheck/build and Ruff pass; repeat a one-profile,
one-repetition browser campaign, then a manual mission and optional RViz lifecycle
check. Record any unverified visual/runtime behavior explicitly.

### Production patch verification — 2026-10-10

Implemented the dedicated lifecycle/manager callback group without changing the
two-thread executor, sensor/action scheduling, public interfaces or READY criteria.
The UI refresh gate permits one pending refresh, pauses during control-center
actions, and invalidates results on actions and effect cleanup. Tests exercise
delayed polling, stale readiness suppression, failure recovery and pre-start
invalidation. CI runs frontend tests and the ROS scheduling test explicitly.

The ROS test uses the production RosGateway, a 32,400-cell cached map and real
odometry publication. It deliberately holds the sensor callback group after
actual telemetry-store work, then requires lifecycle and manager responses within
one second before releasing that callback. This isolates scheduling from CPU speed.

Production campaign campaign-1791600052710-601187 completed both waypoints:
run 25916c48d9ec4cc4abba3c1fda1677e1. Browser interval 23.451 s, approximate
browser distance 1.573 m; ROS duration 21.266 ROS s / 22.069 wall s.
The route is (0.771, 0.623, 0) -> origin, slightly different from the diagnostic
route, so durations are not a controlled navigation-performance comparison.
MCAP recording is preserved (~3.76 MB). During the mission, 22 readiness samples
had median 0.363 s and maximum 0.702 s. Maximum displacement from the first
mission-window sample was Gazebo 0.852 m, map TF 0.856 m, odom/HTTP/WS 0.853 m.
The WebSocket observer recorded one connection and no errors across restart.
Evidence: ignored artifacts/campaign-stabilization-20261010 contains campaign.json,
summary.json, observations.jsonl, gazebo.jsonl, during-motion.jpg, completed.jpg.

Manual browser single-goal submission succeeded with RViz running:
e7831ee3ccfd4c6189ce786a350f7f36, one waypoint, 8.908 ROS s / 10.193 wall s.
RViz closed without stopping navigation, reopened while READY, and was cleaned
up on stack stop. The existing GLSL map shader error persists; RobotModel motion
was not visually inspected.

Checks: 40 backend tests including the sourced ROS scheduling test passed;
128 full unit/component tests passed with sourced ROS and
-p no:launch_testing -p no:launch_ros. An initial unsourced full-suite invocation
could not import Xacro; the sourced invocation encountered the installed
launch_testing plugin's duplicate test_models import. Disabling launch collection
plugins resolved collection; this does not run separate ament launch/system suites.
Four frontend tests, typecheck/build, Ruff and workflow YAML lint passed.
Existing warnings: Starlette/anyio deprecation and Vite bundle size. Heavy
mapping/teleop/replay/launch suites were not rerun.
Final robot stack stopped, patched backend available; diagnostic observers stopped.


## Mission-brief reconciliation and reaudit — 2026-10-10

The supplied CODEX_PROJECT_MISSION.md describes the diagnostic/proposal phase;
source and the production verification section above already contain the narrow
fix. User renewed campaign stabilization as the immediate priority. No additional
backend/frontend readiness patch or architecture rewrite was needed. Unfinished
navigation follow-up was parked and the original files/profile restored exactly.

Reverification passes 277 sourced tests (including the actual production gateway
with blocked sensor group), 15 frontend tests, typecheck/build, original navigation
package rebuild, Ruff/full formatting and source manifest. Live canonical campaign
98155c3495e647869659a425a0c66cfb completes 2/2 fresh-stack trials, with one then four
WS consumers. Mission readiness maxima 0.327/0.464 s; startup+mission maximum
2.585 s. Gazebo/TF/odom/HTTP/WS move about 0.85 m during mission-server navigation
windows. Separate ROS/pose/contact/report checks pass; Gazebo exits cleanly,
recorded PIDs gone, ownership released and runtime stopped. No fresh browser/RViz
visual animation claim. See `../mission-brief-reconciliation-20261010.md` for the
complete reconciliation, results and limits; ignored campaign-reaudit artifacts
preserve raw observations. Earlier failed resource comparisons remain failed.
