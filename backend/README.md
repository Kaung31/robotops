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
wrapper. `xvfb-run` is a shell script whose short-lived subshells share its
argv, so those are never accepted as the launch. Graceful stop verifies the
child's parent and Linux start time (searching again if the recorded identity
is stale), then sends SIGINT to launch only, so Gazebo releases rendering
resources before the wrapper stops Xvfb. If the launch cannot be found, no
graceful signal is sent and timeout escalation (SIGTERM, then SIGKILL, to the
whole group) handles the stack; a graceful group SIGINT would reach Xvfb and
every node twice. Killing Xvfb alongside Gazebo can cause XIO errors and
teardown SIGSEGV (warehouse benchmark W03, 2026-10-12).

Process cleanup alone does not prove clean exit. Each stop produces a shutdown
report (`StackStatus.shutdown`) built from the wrapper's exit code, any
escalation, and the launch log's `process has died` and `XIO:` lines; campaign
cleanup is confirmed only when that report is clean, and each trial directory
receives `shutdown.json` and `software.json` (Git revision, dirty state and
change hashes). The opt-in regression is `backend/tests/runtime_loaded_shutdown.py`
(sourced Jazzy workspace, Xvfb required).
