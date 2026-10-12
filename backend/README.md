# RobotOps backend

Development API boundary for Milestone 7.

Without ROS it deliberately reports unavailable state. In a sourced ROS 2 Jazzy
workspace, set `ROBOTOPS_GATEWAY=ros` and `ROBOTOPS_RUNTIME_MODE=sim` (or `mock` /
`real`) before starting Uvicorn. Replay is intentionally not exposed through the
live ROS gateway.

Example after installing backend dependencies:

```bash
uvicorn robotops_backend.app:app --app-dir backend --host 127.0.0.1 --port 8000
```

Do not bind this unauthenticated development API to an untrusted network.

Backend campaign execution is opt-in via `ROBOTOPS_CAMPAIGN_EXECUTION=1`. Start
a saved definition through `/api/v1/campaigns/{id}/start` on an idle simulation
runtime. Use a graceful shutdown timeout of 90 seconds for cooperative mission
cancellation. React submits intent and observes backend execution; see [campaign contract](../docs/EXPERIMENTS.md).

Finalized campaigns support explicitly generated saved reports at
`POST /api/v1/campaigns/{id}/reports`, with retrieval and JSON/HTML downloads from
the saved report ID. Generation verifies confined local artifact references without
robot commands. SQLite schema 3 adds immutable report snapshots; large recordings
remain outside the database. Integrity checks have explicit scope/byte limits and
do not rewrite experimental verdicts. See the campaign contract for details.

Optional ROS freshness diagnostics can be enabled by exporting
`ROBOTOPS_DIAGNOSTICS=true` before starting this backend. Robot bringup reads this
as the default for `diagnostics:=`; it remains false when unset. The worker inherits
the setting for fresh launches, without a new campaign API field. Mission MCAP
recording captures the optional diagnostic topic; its absence does not fail trials
or change readiness/pose/contact verdicts. See the diagnostics package README.

For locally rendered simulation launched with `ROBOTOPS_USE_XVFB=true`, the
orchestrator records the exact ROS launch child under its owned `xvfb-run`
wrapper. Graceful stop verifies that child's parent and Linux start time, then
sends SIGINT to launch so Gazebo releases rendering resources before the wrapper
stops Xvfb. Whole-group timeout escalation remains available for a hung stack.
Killing Xvfb alongside Gazebo can cause XIO errors and teardown SIGSEGV; process
cleanup alone does not prove clean exit. The opt-in regression is
`backend/tests/runtime_loaded_shutdown.py` (sourced Jazzy workspace, Xvfb required).
