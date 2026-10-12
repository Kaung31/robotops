# Milestone 8C — Automated Benchmark Campaigns

> Planning status, 2026-10-11: Historical browser-orchestrated campaign prototype; execution is now backend-owned. Do not restore this browser loop. Use CURRENT_STATUS and the approved delivery plan for current work.

This increment is additive. It does not change Nav2 bringup, localization, mapping, teleoperation, map saving, manual mission execution, or planner configuration.

## Added

- browser-side automated campaign orchestrator;
- selectable world, saved map, profile set, repetitions and timeout;
- route capture from the existing map goal selection or current robot pose;
- full simulation/navigation restart before every trial for repeatable simulator spawn conditions;
- readiness gating before every trial;
- optional return-to-start waypoint;
- per-trial mission time and odometry-derived web distance estimate;
- campaign cancellation;
- campaign history and JSON export;
- each campaign trial is also written to the existing benchmark run history, so the existing benchmark dashboard immediately includes campaign results.

## Reproducibility boundary

Restarting the simulator before every trial is deliberate: it avoids using the previous trial's end pose as the next trial's start. This is appropriate for the current simulation benchmark workflow and does not claim physical-hardware reset support.

The canonical Milestone 6 ROS experiment runner remains the stronger artifact/provenance path for recorded MCAP experiments. This web campaign UI is an operator-facing automation layer and intentionally reuses the already-working public RobotOps web APIs.
