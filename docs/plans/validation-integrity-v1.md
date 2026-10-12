# Validation Integrity v1 — 2026-10-10

## Scope and research

Preserve ROS mission/action outcomes and campaign lifecycle. Add a separate,
versioned **POSE_VERIFIED / POSE_REJECTED / INCONCLUSIVE / MISSION_FAILED**
verdict; POSE_VERIFIED is explicitly localization-based, not ground-truth or
collision-free success. No controller, localization, safety or readiness redesign.

Primary sources reviewed before implementation:
- https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/others/configuring_amcl/
- https://api.nav2.org/nav2-jazzy/html/amcl__node_8cpp_source.html

AMCL post-dates map->odom by transform_tolerance and pose publication depends on
motion/update thresholds. Therefore latest composite TF existence is insufficient.
Observe direct dynamic TF and AMCL separately, retain ROS message and monotonic
receipt ages, and account for configured AMCL post-dating. Do not force localization
updates or alter Nav2 tolerances to obtain a passing verdict.

## Acceptance and implementation stages

1. Pure deterministic validation and strict configurable policy: XY/yaw error,
   wrapped angles, finite/normalized poses, correct frames, same-trial timestamps,
   ROS and wall freshness, localization covariance, and explicit missing evidence.
2. Runner collects read-only final evidence immediately upon terminal result,
   before parameter/file work; independently checks map/parameter/mission/recording
   provenance. Persist evidence and content hashes in trial manifest. Failed and
   interrupted attempts retain explicit verdicts. Old results remain unvalidated.
3. Backend passes validation evidence through without changing ROS success or
   campaign termination/lease semantics. UI may display separate pose verdicts
   only after deterministic and controlled ROS tests pass.
4. Verify known-good one-profile simulation, preserve recorded metrics, inspect
   missing/rejected cases and document limits. Collision truth stays a later stage.

Default independent policy: 0.20 m XY, 0.25 rad yaw; 1 s TF freshness,
5 s AMCL freshness; maximum XY variance 0.25 m² and yaw variance 0.25 rad².
These are engineering acceptance settings, not Nav2 defaults or calibrated
localization accuracy claims. Policy must be stored with each verdict.

## Outcomes

Implemented all four stages: pure policy/evaluator, read-only ROS observations,
content-bound provenance, backend persistence/API and separate UI pose verdicts.
Existing lifecycle and ROS success remain unchanged. Backend campaigns currently
use runner defaults; the CLI supports an optional complete YAML validation policy.
Stored effective policies are compared across baselines, rather than recomputing
historical defaults. Unknown termination is INCONCLUSIVE, never confirmed failure.

Verified 213 sourced unit/component tests (including 37 pure validation cases),
11 controlled ROS experiment cases, 10 frontend tests, typecheck/build, Ruff,
YAML/CMake checks, and the affected ROS package build. Pure validation passes
standalone without ROS setup. Controlled success, wrong final pose, missing AMCL,
QoS, map/parameter provenance, cancellation and uncertain result paths are covered.
The final two uncertainty/transport cases passed again after the last classification
change. Full controlled-suite teardown emitted a Destroyable warning; its assertions
passed and the focused rerun was clean. Existing anyio/Vite warnings remain.

Live UI campaign acece2346a104d29ae7d19aa058cf312, run
b642d172cef6427e9c9bc42bb054debc, completed 1/1 navfn_rpp round trips:
20.802 ROS s / 1.5614 odometry m, localized XY error 0.147487 m / yaw 0.013272 rad,
POSE_VERIFIED. Current-trial TF/AMCL freshness, covariance and provenance passed.
UI visually showed separate ROS success, pose verdict, errors and policy. After
session interruption/container restart, persisted verdict and all four fingerprints
were verified again. Stack is stopped; ownership released; backend available.
Fresh browser recapture was blocked by the browser's URL security policy on its
restored error page; no bypass was attempted. Evidence is ignored under
artifacts/validation-integrity-20261010/ and linked campaign/run artifacts.

Limits: final localized pose only; no collision or physical ground truth, no
independent intermediate-waypoint validation or calibrated covariance confidence.
Existing preflight readiness is preserved. Heavy mapping/teleop/replay and RViz
animation were not rerun. Collision evidence is the next scoped milestone.
