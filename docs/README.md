# RobotOps documentation

Start with [CURRENT_STATUS.md](CURRENT_STATUS.md) (one page) and the working rules
in [AGENTS.md](../AGENTS.md#development-order). Source code and tests are the final
authority on what exists.

## Architecture and contracts

- [ROS/local architecture](ARCHITECTURE.md), [specification](PROJECT_SPEC.md)
- [Frames](FRAME_CONTRACT.md), [control and command arbitration](CONTROL_CONTRACT.md)
- [Static Recorded Lab architecture](PUBLIC_DEMO_ARCHITECTURE.md) and its
  [playback data contract](plans/public-replay-contract.md)

## Runbooks

- [Mapping](MAPPING.md), [navigation](NAVIGATION.md), [missions](MISSIONS.md)
- [Experiments and campaigns](EXPERIMENTS.md), [web control center](WEB_CONTROL_CENTER.md)
- [RViz](RVIZ_INTEGRATION.md), [testing and runbook](TESTING_AND_RUNBOOK.md)

## Design records

`plans/` holds the engineering plan and verification record for each stage:

- `plans/milestone-*.md`: foundational stages (robot, control, mapping,
  navigation, missions, experiments, web).
- [Backend campaign service](plans/backend-campaign-service.md),
  [validation integrity](plans/validation-integrity-v1.md),
  [Gazebo contact evidence](plans/gazebo-collision-truth.md),
  [durable reports](plans/durable-experiment-reports.md).
- [Deterministic diagnostics](plans/deterministic-diagnostics.md),
  [controlled sensor faults](plans/controlled-sensor-faults.md),
  [fault campaign integration](plans/fault-campaign-integration.md).
- [Campaign restart diagnosis](plans/campaign-restart-diagnosis.md),
  [Gazebo shutdown repair](plans/gazebo-shutdown-repair.md),
  [coordinated navigation diagnosis](plans/coordinated-navigation-diagnosis.md),
  [rotation repeatability](plans/rotation-repeatability.md).

Older plans keep their original "next steps"; check the source before treating
them as pending work. Dated reviews and owner approvals are kept locally in
`docs/archive/` and are not published.
