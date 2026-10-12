# Return-leg rotation qualification — 2026-10-10

The user authorizes work on remaining project tasks. Resume the bounded rotation
investigation parked during the mission-brief reaudit. Preserve all historical
measurements; do not claim their complete cause from a synthetic regression.

## Evidence and candidate

Installed Jazzy RPP 1.3.12 defaults stateful=true (previously confirmed live).
Upstream setPlan clears has_reached_xy_tolerance_ for every plan. A native
regression feeds inside tolerance, a same-destination replan, then outside:
upstream loses final heading alignment. The parked subclass passes that case
without replacing upstream tracking, collision detection or velocity policy.
Historical recordings show final-heading reversals and localized distance near
the tolerance boundary. This supports the candidate mechanism, not a captured
native branch trace of those historical failures.

The adapter preserves the latch only for an exactly unchanged destination pose
and frame. Changed destination/frame, new action/reset, stateless mode and empty
path must not retain alignment. Identity excludes timestamps and intermediate
path changes. Existing goal-checker/validation tolerances remain unchanged.

## Success criteria before qualification

1. Native before-fix regression fails; after-fix native cases pass, including
   new action/reset, changed position/orientation/frame, stateless mode, empty
   path and replanning before XY tolerance was reached.
2. Build and fast suite/lint pass. Both navigation profiles pass the existing
   system suite: collision/path rejection, teleop priority, cancel, completion,
   independent final pose and watchdog after navigation shutdown.
3. Run three fresh-stack diagnostics-off/on pairs in rotated order. Reuse Stage E
   CPU/RSS, >=10 s warm execution windows, <=10% paired duration/path tolerance,
   separate ROS/pose/contact/report evidence and raw clean exit checks. Do not
   relax criteria after observing results. If a criterion fails, document it;
   neither this repair nor diagnostics expansion is automatically accepted.
4. Keep RViz off for benchmark measurements. Visual RobotModel verification is
   independent and remains unclaimed without direct visual evidence.
5. Update current context and manifest. Default diagnostics remain false and
   original <=10% replay CPU target remains separate and unmet.

No fault relay, public hosting, ML or physical hardware in this qualification.

## Compatibility and evidence limits

This controller is a small adapter around installed Nav2 Jazzy RPP 1.3.12, not a
replacement controller. It uses protected RPP members and therefore requires
native regression/build checks when upgrading Nav2. Upstream source:
[1.3.12 RPP implementation](https://github.com/ros-navigation/navigation2/blob/1.3.12/nav2_regulated_pure_pursuit_controller/src/regulated_pure_pursuit_controller.cpp).

Exact destination equality intentionally clears state when any goal position,
orientation or path frame changes. Timestamp/intermediate-path changes do not
change goal identity. FollowPath action reset clears identity and the latch.
Independent final-pose/contact verdicts remain mandatory: ROS success alone
cannot accept a trial. No tolerance, rate, velocity, collision or readiness
setting changes are included.

The first qualification invocation exposed stale CMake configuration: the profile
changed but the new plugin resource/library had not been installed. AMCL remained
inactive after lifecycle startup failed at controller configuration. Force CMake
reconfiguration installs the plugin; preserve this failed log rather than treating
it as a navigation trajectory failure. The original cached three-case native
binary is superseded by the rebuilt six-case native suite.

## Qualification result

Rejected: six native tests and both navigation profiles pass, but all three
fresh-stack duration comparisons fail (+86.47%, -46.78%, +79.94%). CPU/RSS and
pose/contact/report/raw-exit checks pass. A seventh combined native case shows
preserved RPP alignment can disagree with the goal checker reset by Nav2's
ControllerServer. Original navigation restored; rejected draft kept in ignored
artifacts. No fault/default expansion. See ../rotation-qualification-20261010.md
for evidence, limits and the next coordinated state-observation investigation.
