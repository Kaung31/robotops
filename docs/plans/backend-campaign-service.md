# Canonical backend campaign service — 2026-10-10

## Scope and stages

Keep the existing browser campaign working while migrating ownership in verified
stages. Reuse the ROS experiment_runner rather than duplicating action execution,
provenance checks, start tolerances, cancellation or recorded-data metrics.

1. Durable foundation: strict campaign definitions, server-owned campaign/trial
   IDs, SQLite behind a repository interface, idempotent creation, history,
   ordered events and cancellation of unstarted definitions. API-only; all
   trials remain planned. Creation must never start a stack or mission.
2. Execution: one worker and exclusive runtime lease, reset/start/readiness,
   one existing ROS experiment_runner invocation per fresh trial. Preserve a
   per-profile parameter baseline and campaign map hashes across invocations.
   Protect manual mutating operations while the worker owns the runtime.
3. Recovery/cancellation: persisted intent before mission dispatch, confirmed
   cancellation and cleanup, interrupted/uncertain states on restart. Never
   automatically resubmit an uncertain accepted mission. Fault-test startup,
   shutdown and browser disconnection before exposing execution to React.
4. Client migration: replace browser orchestration with backend API observation,
   retain historical browser results and label their approximate metrics.
5. Independent validation and collision truth remain separate later milestones.

## Stage 1 acceptance

- Strict finite/bounded configuration; reject extra fields and real/replay modes.
- Validate world, map compatibility and profile IDs against current options.
- Create immutable definitions and a deterministic profile/repetition trial order.
- Stable idempotency key retries; changed content under the same key is a conflict.
- Definitions, trial IDs and events survive repository/backend recreation.
- Atomic create/cancel; repeated cancellation emits no duplicate transition.
- Bounded history/events pagination with a resumable event sequence.
- No ROS calls or stack mutations from definition APIs, including cancellation.
- Existing tests and frontend checks still pass; new repository/API tests cover
  concurrency, persistence, invalid input, missing IDs and unavailable storage.

Stage 1 is a complete persistence/API increment, not a functioning backend executor.
No queued/running state or independent VERIFIED_SUCCESS claim is exposed yet.

## Stage 1 outcome — 2026-10-10

Implemented the repository abstraction, SQLite schema v1, strict definitions,
stable planned trial IDs, create/status/history/events/cancel APIs and optional
ROBOTOPS_CAMPAIGN_DB override. SQLite operations run in synchronous API handlers
on FastAPI's thread pool rather than blocking the ROS/readiness event loop.
Creation and cancellation write their record and event in the same transaction.
Idempotency retries return existing records even if map options have changed.

32 new tests cover invalid/unsafe modes and inputs, map/profile compatibility,
parallel duplicate requests, cancellation races, transaction rollback, bounded
pagination, schema version rejection, corrupt/unavailable storage, and reopening
repositories/API lifespans. The full sourced unit/component suite now passes
160 tests. Four frontend polling tests, typecheck/build and Ruff also passed.
Existing Starlette/anyio deprecation and Vite bundle-size warnings remain.

Live API smoke test created draft 05153bf5f4c84a0b8152489e3b4042c2, retried it
idempotently, restarted the backend, verified identical campaign/trial IDs, and
canceled it. Both events persisted; the robot stayed stopped during these calls.
Evidence: artifacts/campaign-foundation-20261010/{definition.json,
canceled-definition.json,events.json} (ignored generated files).

The unchanged browser campaign was repeated against the updated backend:
campaign-1791600921255-2bdcff, ROS run acf0c842d9a848e09eaae9c68ff58af2,
1/1 trial, both waypoints succeeded. Browser interval 22.354 s / approximate
distance 1.547 m; recorded ROS result 20.849 ROS s / 21.573 wall s, MCAP 3.71 MB.
Twelve readiness samples took 0.197–0.434 s, all READY. Evidence in the same
ignored directory: browser-campaign.json, readiness.json, completed.jpg.
No new physical-Gazebo/RViz visual comparison or heavy mapping/teleop/replay
launch suite was run in this follow-up. Robot stack is stopped; backend available.

At completion of stage 1, stage 2 remained pending: an exclusive runtime lease and worker using the existing
ROS runner, with explicit recovery semantics and baseline preservation. Do not
interpret draft persistence as completed backend execution or migrate the React
executor before that stage passes its runtime and failure tests.

## Research and stage 2 decision — 2026-10-10

Primary sources reviewed:
- https://fastapi.tiangolo.com/advanced/events/ — lifespan owns startup/shutdown.
- https://sqlite.org/lang_transaction.html — BEGIN IMMEDIATE serializes write claims.
- https://design.ros2.org/articles/actions.html — cancellation acceptance is not terminal completion.
- https://docs.python.org/3.12/library/asyncio-subprocess.html — subprocess lifecycle and explicit timeout cleanup.
- https://docs.python.org/3.12/library/fcntl.html — local nonblocking advisory locks.

Chosen implementation: one lifespan-managed async coordinator, existing ROS runner
in a subprocess, transactional persistent lease plus local runtime file lock.
No Celery/Redis/distributed retry queue for the one-robot local runtime. This is
an engineering choice inferred from the project constraints, not a claim that
those tools are universally unsuitable. Long ROS execution stays outside FastAPI;
blocking launch/SQLite work moves to threads. Only registered sim orchestration
is executable initially; mock definitions remain supported but need an adapter.

Stage 2 acceptance: explicit start, one owner, concurrent manual mutation rejection,
independent optional RViz, fresh-stack trial ordering, persisted dispatch intent,
per-profile parameter baselines and campaign map hashes, recorded metrics,
cooperative cancellation and cleanup, conservative restart interruption without
replay. Reconciliation requires no live telemetry and an available runtime lock.
Execution is opt-in until backend tests and a real single-profile campaign pass.
React migration stays separate.

## Stage 2 outcome — 2026-10-10

Implemented explicit start and opt-in lifespan worker, transactional SQLite lease
(schema v2 upgrades v1), local inherited file lock, manual mutation guards,
simulation adapter, fresh-stack trial sequence, per-profile/map baselines,
confirmed cancellation/cleanup and conservative interrupted ownership recovery.
Reconciliation releases ownership without changing or rerunning uncertain results.
The browser executor remains intact; its API observation migration is next.

The first real run correctly failed preflight before dispatch because existing
mission launch parameters omitted environment/profile/map provenance. Added
optional launch arguments and forwarded selected values; existing config defaults
are preserved when arguments are absent. Regression tests cover command arguments
and launch parameter overrides.

Live repeat campaign 3e55d53ba32246088a84251b004d4c4e completed 2/2 fresh-stack
round trips, recorded 21.825/28.759 ROS seconds and 1.5474/1.6014 odometry metres.
Parameter snapshots remained identical, map hashes matched and the second process
loaded its predecessor's baseline. Teleop was blocked with 409 during ownership.
History survived backend restart. Live cancellation campaign
10f133693d4644568ab8207e6637d908 reached navigating, then action CANCELED (status 5),
confirmed termination/cleanup and released the lease. Evidence is ignored under
artifacts/campaign-worker-20261010 and its linked campaign/run directories.

Tests cover concurrent claims, owner fencing, cancellation writes, rollback on
unsafe release, schema migration, child lock inheritance, live-owner protection,
startup recovery without retries, cooperative shutdown, uncertain termination and
cleanup, external telemetry rejection, baseline conditions and API command guards.
Actual backend SIGKILL while a Gazebo mission runs remains unverified; controlled
ownership/recovery tests cover that design. No new independent success/collision
verdicts are claimed. Heavy mapping/replay/teleop and direct RViz animation checks
were not rerun in this stage.

Final verification: 172 sourced unit/component tests, 9 experiment integration
cases, 13 mission integration cases, 5 mission launch cases, 4 frontend polling
tests, Ruff, TypeScript typecheck/build and affected ROS package builds passed.
Existing anyio deprecation and Vite chunk-size warnings remain. The existing
manual API path completed run 445aeb29a815417ca4d54fa3c6635d6d after campaign
ownership release, then stopped cleanly. Backend remains available; stack stopped.

## Stage 4 client migration acceptance — 2026-10-10

Replace the React execution loop with create/start/cancel/reconcile API requests
and single-flight observation. Browser refresh/disconnection must not create,
restart, cancel or resubmit a trial. Discover ownership independently of history
pagination; retain last known state and report transport errors without inventing
results. Persist a creation idempotency key before requests and reuse it for
explicit retries after lost responses. Never start a finalized record again.

Keep existing browser history accessible as legacy approximate evidence; do not
merge it with recorded metrics or fabricate missing values. Present explicit
start pose/tolerances and fixed return waypoint in the submitted definition.
Preserve manual operations and optional RViz. Verify API contract, client retry
and stale-response behavior, UI reload during a real campaign, cancellation, and
backend hard-kill quarantine/reconciliation without automatic mission retry.

## Stage 4 research and outcome — 2026-10-10

Reviewed React's effect setup/cleanup semantics and AbortSignal timeout behavior:
- https://react.dev/reference/react/useEffect
- https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static

Observation lives in a custom hook using the existing refresh gate. Its cleanup
stops observation only. Requests have a bounded transport timeout; timeout never
implies cancellation or failure of the remote mission. Mutation errors remain
separate from polling errors. Creation intent is persisted before requests and
reused on explicit retry; an active/finalized creation response is observed without
starting it again. Invalid-definition responses allow editing instead of trapping
a malformed pending request.

Removed the browser execution loop and writes to browser campaign/run evidence.
Added typed campaign client, explicit start/return conditions, server history
pagination, event cursors, conservative missing metrics and evidence references.
Legacy browser campaigns remain read-only/exportable with approximate labels;
the browser mission dashboard remains separate. Runtime discovery returns lease
identity, availability and whether this backend process has an active worker.
No new public ROS interfaces or robot control paths were introduced.

Live UI campaign 31ff84397b784e0692ec9dcc6bf35c16 survived a refresh during
execution and completed one mission e0751d319824494d984def4da3485df3 (21.069 ROS s,
1.5796 odometry m), without duplicate create/start/dispatch. UI cancellation
campaign aaffd8d34b794fb6b99682cc54b3b01a was canceled after navigating, with
terminal cancellation and cleanup confirmed and ownership released.

Live SIGKILL test 4c8e1ddac88847bdb026bb29c4e6b7df killed the owned backend
after mission-server navigating evidence. Restart quarantined ownership, with
new execution and premature reconciliation both rejected (409) while orphan
telemetry stayed live. The original runner completed independently; its success
was not adopted by the restarted backend. Captured original process groups were
stopped using PID/start-time checks. Explicit UI reconciliation released ownership
while preserving interrupted state and false confirmation fields. Exactly one
runner manifest and one start event remained. Evidence: ignored
artifacts/campaign-client-20261010/{ui-result,ui-cancel-result,crash-state,
crash-before-reconcile,crash-reconciled,crash-events}.json and linked recordings.

Next is Validation Integrity v1, followed by independent collision truth and
reports. Heavy mapping/replay suites and direct RViz animation were not rerun.

Final client-stage checks: 173 sourced unit/component tests, 10 frontend tests,
Ruff, TypeScript typecheck/build passed. The source manifest is regenerated.
Existing anyio deprecation and Vite chunk-size warnings remain. Backend is
available; the stack is stopped and runtime reservation released.
