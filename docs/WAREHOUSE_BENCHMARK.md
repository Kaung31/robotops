# Warehouse navigation benchmark v1 — results

Run 2026-10-12 on `warehouse_v1` (Gazebo Harmonic, ROS 2 Jazzy, Nav2, Cyclone DDS).
Six trials, three per Nav2 configuration, in the frozen AB/BA/AB order from
[`benchmarks/warehouse_v1/matrix.json`](../benchmarks/warehouse_v1/matrix.json).
**All six completed with a verified final pose and no observed contact.**

Status: adopted as an **exploratory** benchmark with the limitations below. The
trials ran through the normal backend campaign path. They are not executions of
the separate qualification harness, which did not qualify.

> **Key finding — no aisle driving.** The goals sit at both ends of the two 1.2 m
> aisles between the racks, but in all six trials both configurations drove around
> the rack block on the perimeter and never entered an aisle. v1 therefore says
> nothing about narrow-aisle navigation, and no such capability is claimed.

## Method

Each slot (`benchmarks/warehouse_v1/campaigns/W01.json` … `W06.json`) ran as its own
backend campaign: a fresh Gazebo + Nav2 stack, AMCL localization on the saved
warehouse map, a five-goal mission, MCAP recording, then independent checks. The
goals sit at both ends of the two 1.2 m aisles between the three racks: (3, 0),
(3, 7), (5, 7), (5, 0), then home. The recorded trajectories show that both
configurations drove around the rack block on the perimeter (west of rack 1 at
x ≈ 0.9 m, along y ≈ 7 m, east of rack 3 at x ≈ 7 m) and never entered an aisle;
that is why the path is about 28 m rather than about 24 m.

- **ROS outcome**: Nav2 / mission action result.
- **Final pose**: localized final pose versus the commanded goal, limits 0.20 m and
  0.25 rad, with TF/localization freshness and provenance checks.
- **Contact**: Gazebo contact evidence for all robot collision bodies, excluding
  wheel/caster-to-floor support, in 50 ms windows over the whole mission.
- **Report integrity**: each campaign report re-hashes the runner manifest, mission
  result, recording metadata, MCAP and contact evidence.

## Results

| Slot | Configuration | Time (ROS s) | Path (odom m) | Final XY error (m) | Final yaw error (rad) | Pose | Contact | Campaign |
|---|---|---|---|---|---|---|---|---|
| W01 | NavFn + RPP | 137.37 | 28.05 | 0.151 | 0.059 | VERIFIED | none observed (2854 windows) | `46fd6f8c` |
| W02 | Smac 2D + DWB | 132.94 | 27.95 | 0.131 | 0.194 | VERIFIED | none observed (2768 windows) | `fbb8f2ea` |
| W03 | Smac 2D + DWB | 132.08 | 27.98 | 0.119 | 0.191 | VERIFIED | none observed (2749 windows) | `bb001268` |
| W04 | NavFn + RPP | 137.86 | 28.11 | 0.140 | 0.053 | VERIFIED | none observed (2864 windows) | `b8e0d236` |
| W05 | NavFn + RPP | 137.78 | 28.12 | 0.134 | 0.055 | VERIFIED | none observed (2861 windows) | `908e04a6` |
| W06 | Smac 2D + DWB | 133.32 | 28.02 | 0.151 | 0.192 | VERIFIED | none observed (2776 windows) | `57cbadea` |

All six campaign reports are integrity `VERIFIED` (36/36 artifact checks).
Recorder loss accounting, assessed afterwards from the original recorder logs, is
complete for all six (the event thread started, recording stopped normally, the
thread exited) with 0 messages lost on the transport layer.

| Configuration | Mean time (range) | Mean path | Mean XY error | Mean yaw error |
|---|---|---|---|---|
| NavFn + Regulated Pure Pursuit | 137.67 s (137.37–137.86) | 28.09 m | 0.142 m | 0.056 rad (≈3.2°) |
| Smac 2D + DWB | 132.78 s (132.08–133.32) | 27.98 m | 0.134 m | 0.192 rad (≈11.0°) |

## Observations

- **Smac 2D + DWB finished about 4.9 s (3.6%) sooner in every trial**, on a
  slightly shorter odometry path.
- **NavFn + RPP ends with a much tighter heading** (≈3° versus ≈11°). DWB stops as
  soon as it is inside Nav2's 0.20 rad yaw goal tolerance, which leaves only
  ≈0.06 rad of margin to RobotOps' 0.25 rad validation limit.
- **Runs are highly repeatable**: the time spread across three trials is 0.49 s for
  NavFn + RPP and 1.24 s for Smac + DWB.
- **Neither configuration used the aisles.** Both chose the wide perimeter over
  the 1.2 m aisles, so v1 does not measure narrow-aisle navigation.

## Limits

- Three trials per configuration show repeatability, not statistical significance.
- Each configuration changes both planner and controller; the results compare
  bundles, not individual algorithms.
- One simulated world and start pose. Final pose comes from AMCL localization, not
  simulator ground truth.
- "No contact observed" covers the monitored simulated collision bodies only; it
  is not a certification of collision-free behavior.
- Times are simulation (ROS) time on one laptop; other hosts may differ.
- W03's stack teardown, after its evidence was finalized and hashed, lost its X
  display: `gazebo_runner` exited -11 (SIGSEGV) and `twist_mux` exited -2. The other
  five logged no child failure. The campaign record says cleanup was confirmed
  because the check at the time did not include process exit status. Cause: the
  backend sometimes recorded a short-lived `xvfb-run` subshell as the launch
  process under load, then fell back to a group SIGINT that reached Xvfb and every
  node twice (reproduced offline in 24/40 loaded starts). Fixed afterwards; see
  `backend/README.md`.
- The software revision was not recorded in the trial evidence. Runs used checkout
  `ebdb551` plus uncommitted changes.
- Final pose is localized TF; AMCL pose and simulator ground truth were not
  recorded, and nothing is reconstructed for these runs.

## Evidence recorded by later runs

Campaign trials started after these runs also write `software.json` (Git revision,
dirty state and change hashes) and `shutdown.json` (exit codes, shutdown path,
child failures, display loss). Campaign cleanup is confirmed only when shutdown is
clean. The recorder fails a recording whose loss accounting is incomplete and
saves `message_loss.json`. `ROBOTOPS_RECORDING_PROFILE=validation` additionally
records `/amcl_pose` and `simulation/ground_truth`; the default profile, which
the frozen matrix pins, is unchanged.

These were accepted by a separate infrastructure campaign on 2026-10-13
(`infra-acceptance-20261013-a`, campaign `8838d36b…`, a 5 m out-and-back in
`warehouse_v1`; it is not part of the benchmark): clean shutdown with all three
launches exiting 0, software revision recorded, 0 messages lost with complete
accounting, and AMCL within 7.4 cm and 0.037 rad of simulator ground truth across
153 time-aligned samples.

## Reproduce

From a sourced Jazzy workspace, start the backend with campaign execution enabled
(see [EXPERIMENTS.md](EXPERIMENTS.md)), then submit each slot:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/campaigns -H 'Content-Type: application/json' -H 'Idempotency-Key: W01-run1' --data @benchmarks/warehouse_v1/campaigns/W01.json
```

Start it with `POST /api/v1/campaigns/{id}/start`, poll `GET /api/v1/campaigns/{id}`
and generate the report with `POST /api/v1/campaigns/{id}/reports`. Recordings and
reports stay in the local `artifacts/` folder and are not part of the repository.
