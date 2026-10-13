# RobotOps — current status

Updated 2026-10-13. Kept to one page: it describes the present, not the history.
The full development log is kept locally in `docs/archive/` and is not published.

## Works today (simulation)

- ros2_control robot with mock and Gazebo Harmonic backends; stamped command mux,
  command guard and timeouts.
- SLAM Toolbox mapping, saved maps, AMCL localization, Nav2 profiles `navfn_rpp`
  and `smac_dwb`.
- Multi-waypoint missions with MCAP recording.
- Backend-owned campaigns (SQLite history, exclusive runtime lease, crash
  recovery), final-pose validation, Gazebo contact evidence, versioned reports.
- React dashboard (live map, LiDAR, teleop, readiness, campaigns, reports) and a
  separate static Recorded Lab: the six warehouse benchmark trials (W01–W06) with
  a six-trial comparison, plus two earlier baselines (N0, N2). Private release
  candidate only; datasets are not published.
- Opt-in native freshness diagnostics; an isolated LiDAR fault relay that is not
  yet wired into campaigns.

## Evidence so far

- **Warehouse benchmark v1 (2026-10-12):** 6/6 trials completed on `warehouse_v1`,
  three each for NavFn + RPP and Smac 2D + DWB, all pose-verified with no observed
  contact and integrity-verified reports. Adopted as exploratory, not qualified;
  W03's teardown crash is disclosed. See [WAREHOUSE_BENCHMARK.md](WAREHOUSE_BENCHMARK.md).
- Earlier: 49 trials on `mapping_lab` with `navfn_rpp` on one short round trip,
  42 succeeded, median 21.0 ROS seconds.

## Current phase: 0 — get visible

Done: Apache-2.0 `LICENSE` and `NOTICE`; portable CI test fixes; backend tests
isolated from the real `artifacts/` database and runtime lock.
Next: Git history and first push, green CI, static site v0.1, docs cleanup.

## Fixed 2026-10-13

- Wrapped-launch shutdown race (W03's teardown crash): no graceful group SIGINT
  under `xvfb-run`; cleanup now requires clean exit codes.
- Trials record the software revision and a shutdown report; the recorder fails
  closed on incomplete loss accounting; an opt-in recording profile adds AMCL
  pose and simulator ground truth.
- Recorder readiness wrongly required the MCAP header on disk, so low-rate
  recordings could never start (the mission integration tests failed). The
  recorder now refuses a pre-existing output directory instead.
- Accepted live by infrastructure campaign `8838d36b…` (2026-10-13); see
  [WAREHOUSE_BENCHMARK.md](WAREHOUSE_BENCHMARK.md).

## Known issues (2026-10-12 audit)

1. `TelemetryStore.publish` costs ~17 ms per message (~138% of a core while
   navigating), and every websocket frame carries the whole map.
2. Odometry-frame and map-frame poses share the `pose` field, so the map marker
   is wrong whenever map→odom is not identity.
3. The separate warehouse qualification harness (`scripts/warehouse_qualification/`,
   `robot_navigation/test/warehouse_session.py`) failed on its own checks (observer
   backlog, unsynchronized odom/truth comparison). The benchmark runs through the
   normal campaign path; the harness is kept for reference.
4. Blocking orchestrator calls inside `async def` endpoints freeze the API during
   Stop and map save. Stop is refused (409) while Start is localizing.
5. The backend accepts any `Host` header and any WebSocket `Origin`.

## Next phases

1. Real benchmark: warehouse via campaigns (v1 done, exploratory), a world that
   forces aisle driving, an easy→extreme world ladder, published results after a
   dataset licence decision.
2. Reliability: fault relay in campaigns; navigation regression CI.
3. Showcase: demo video, README rewrite, one-command Docker demo.
4. Physical robot through the same ROS interfaces (owner approval required).
