# RobotOps — current status

Updated 2026-10-12. Kept to one page: it describes the present, not the history.
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
  separate static Recorded Lab with two recorded runs (N0, N2).
- Opt-in native freshness diagnostics; an isolated LiDAR fault relay that is not
  yet wired into campaigns.

## Evidence so far

49 campaign trials, all on `mapping_lab` with `navfn_rpp` and the same short round
trip: 42 succeeded, median 21.0 ROS seconds. `smac_dwb` has not run in a campaign.
The `warehouse_v1` world exists but has no completed trial.

## Current phase: 0 — get visible

Done: Apache-2.0 `LICENSE` and `NOTICE`; portable CI test fixes; backend tests
isolated from the real `artifacts/` database and runtime lock.
Next: Git history and first push, green CI, static site v0.1, docs cleanup.

## Known issues (2026-10-12 audit)

1. `TelemetryStore.publish` costs ~17 ms per message (~138% of a core while
   navigating), and every websocket frame carries the whole map.
2. Odometry-frame and map-frame poses share the `pose` field, so the map marker
   is wrong whenever map→odom is not identity.
3. The warehouse qualification harness backs up on `/clock` and `/tf`. Replace it
   with the normal campaign path. AMCL publishes only after motion; call
   `request_nomotion_update` before readiness checks.
4. Blocking orchestrator calls inside `async def` endpoints freeze the API during
   Stop and map save. Stop is refused (409) while Start is localizing.
5. The backend accepts any `Host` header and any WebSocket `Origin`.

## Next phases

1. Real benchmark: warehouse via campaigns, an easy→extreme world ladder, both
   profiles, published results.
2. Reliability: fault relay in campaigns; navigation regression CI.
3. Showcase: demo video, README rewrite, one-command Docker demo.
4. Physical robot through the same ROS interfaces (owner approval required).
