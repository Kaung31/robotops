# Durable campaign reports and contact presentation

Date: 2026-10-10. Authorized next stage after independent contact evidence.

## Scope and success criteria

Keep existing SQLite history, runtime ownership and ROS interfaces. Add explicit
report generation for finalized campaigns only. Reports are immutable versioned
snapshots behind the repository abstraction, with deterministic identity, original
definition/trials, metric sample counts, separate pose/contact counts, and artifact
integrity checked at generation time. Missing, mismatched, unsafe, or unavailable
artifacts never become verified evidence. Original outcomes remain unchanged.

Persist JSON in SQLite (schema migration 2 -> 3); large evidence stays outside it.
Expose persisted reports and JSON/escaped self-contained HTML downloads using
FastAPI Responses. Generation must never dispatch/retry/cancel a mission, mutate
a campaign, release ownership, or include browser legacy history. Repeated identical
generation reuses the report; changed integrity creates a new immutable report.

Artifact reads are confined to the application's artifacts directory, reject
symlinks/path traversal/nonregular files, bind manifest fields to the stored trial,
and stream hashes with an explicit total verification budget. Integrity is a local
snapshot check, not signed authenticity or an ongoing monitor.

React shows stored contact verdict, coverage/reasons and opaque evidence references.
A report panel allows explicit generation, selection and download, handles stale
requests/errors and preserves local legacy approximate history separately.

Verify migration/reopening/idempotency/concurrent generation, partial/canceled/
interrupted cases, missing/tampered/unsafe artifacts, escaped HTML, transport/UI
behavior, frontend typecheck/build/tests and source regression suite. Use existing
recorded campaign evidence for live API checks; no robot motion is required.
Inspect the UI if browser access is available; report any verification limit.

## Research

- https://fastapi.tiangolo.com/advanced/custom-response/
- https://www.sqlite.org/lang_transaction.html

## Progress

Implemented: schema-3 report persistence, confined streaming artifact checks,
idempotent immutable snapshots, saved retrieval and JSON/HTML exports. UI presents
stored contact results and report selection/download without new browser truth.

Verification: 246 sourced unit/component tests, including 20 report cases; 15 frontend
transport/markup tests; TypeScript typecheck/build; Ruff check/format. A report for
existing campaign 9ca4924760684146ba5b9976aeda6bd3 verifies six artifact references,
preserves the three separate outcomes and survives backend restart unchanged.
Repeated generation reuses its ID. No campaign state, robot command or lease changes.
Live report: 420f2694f143a730be1ab0aba1ebee2ee3ecf1f25cc2e7b0b3d677444ca98520.

Evidence and metadata backup: ignored artifacts/experiment-reports-20261010/.
Existing AnyIO deprecation and Vite chunk warnings remain. No robot runtime suites
were rerun because no ROS/control code changed. Browser inventory shows a restored
connection-error page; prior URL security restrictions were respected. Interactive
browser/layout verification is not claimed; component markup and API checks pass.

Reports are explicitly generated, not an execution-finalization side effect. This
keeps file verification/failure outside mission completion and allows rechecking
old finalized records. Local hashes are not signed authenticity or atomic cross-file
snapshots. Stored JSON is immutable; HTML presentation is rendered from that JSON.
