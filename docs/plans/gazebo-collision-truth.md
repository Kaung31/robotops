# Independent Gazebo contact evidence

Date: 2026-10-10. Scope: read-only contact evidence, separate from mission and pose verdicts.

## Design and success criteria

Gazebo Harmonic's built-in Contact system publishes only nonempty contacts. Its Physics
system populates requested ContactSensorData components each step, including clearing
empty contacts. Use a model-scoped simulation plugin to request all six current collision
bodies and accumulate evidence every unpaused physics step. Publish bounded windows over
a backend-neutral ROS message. No command, TF, controller, geometry or navigation changes.

Coverage requires the exact configured body inventory, observed normal support contact
(attesting that this physics engine supplies contacts), positive physics steps, and a
continuous source/sequence/time interval. Only configured wheel/caster-to-floor pairs are
normal support; chassis-floor, self contact, and obstacle contact remain collision evidence.
An unavailable adapter, discontinuity, changed inventory or reset means UNKNOWN, never zero.
This measures simulated contact geometry, not real-world safety or near-miss clearance.

1. Implement and build the simulation plugin and ROS evidence contract.
2. Verify normal support, deliberate obstacle contact, unavailable coverage, pause/reset and
   subscriber loss using focused tests; retain logs under ignored artifacts.
3. Integrate a bounded per-trial ROS collector, optional MCAP topic, and persisted backend
   evidence without changing existing outcome/pose verdict semantics.
4. Run unit/component checks and a known-good recorded simulation campaign, update docs
   and source manifest. Keep incomplete stages explicit.

## Research

- https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/contact/Contact.cc
- https://github.com/gazebosim/gz-sim/blob/gz-sim8/src/systems/physics/Physics.cc
- https://gazebosim.org/docs/harmonic/sensors/

## Progress

Research and generated-SDF inspection complete: fixed-joint reduction produces six
collision bodies. Both supported worlds use control_pad_floor::floor::floor_collision.
All four stages complete. The additive ROS contract and read-only model plugin build;
the bounded collector persists raw evidence with a SHA-256 reference, independently
of existing ROS/pose results. MCAP records the topic optionally. CLI summary counts
trial verdicts; backend history persists them without a schema migration. UI contact
presentation remains explicitly part of the next durable reporting stage.

Verification: 226 unit/component tests (13 new coverage cases), 11 controlled ROS
cases with absent-adapter UNKNOWN assertions, three physics cases including normal
support/obstacle/inventory mismatch plus pause/reset, Ruff check/format and four
ROS package builds. Missing windows/source/policy/sequence/time changes are exercised
in pure tests; no network fault injection is claimed. Two one-trial live campaigns
completed with continuous NO_CONTACT_OBSERVED coverage and POSE_VERIFIED results.
Final campaign 9ca4924760684146ba5b9976aeda6bd3 has 421 windows, 395 MCAP messages,
confirmed provenance, matching artifact hashes and identical offline reanalysis.
Backend restart preserves it and leaves no lease. Logs and verification are under
ignored artifacts/collision-truth-20261010/.

An intermediate unit run overlapped a live campaign: seven fake-command tests hit
the legitimate ownership guard. Serial final checks pass. No frontend changes or
browser verification, broad mapping/teleop/replay/RViz reruns, physical-robot tests,
unique collision episode counts or combined experimental verdict are claimed.
