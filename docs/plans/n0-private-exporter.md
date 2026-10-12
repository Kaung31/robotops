# P2 private N0 exporter — bounded implementation plan/status

Approved by Q1-T1 section7 after offline timing investigation was reported.
Acceptance criteria were the existing P1 playback contract, read fully before
implementation. This file records the implemented stages, not live authorization.

1. Verify stopped robotics, unchanged Q1 guard/history/N0 and independently restore
   source checkpoint — complete, artifacts/p2-n0-20261011/preflight.json.
2. Pin N0/report/map and verify canonical report/runner/run integrity. Decode MCAP
   offline; preserve exact times, frames, missing intervals and original metrics — complete.
3. Implement strict v1 schemas and deterministic private gzip chunks; no arbitrary
   labels/paths/logs/parameters; no invented events or report pose backfill — complete.
4. Compare all exported poses/scans/TF refs with decoded sources using independent
   composition; test precision, gaps, privacy, corruption, sizes and determinism — complete.
5. Report measured sizes/runtime and preserved hashes; stop before P3/publication — complete.

P1 targets retained: initial <=250KiB, scenario <=5MiB, chunk <=1MiB; poses <=20Hz,
scans <=5Hz. Actual total168356 bytes, initial7706, largest101438;47 P2 tests and
184 combined checks pass. No browser/hosting/remote verification is claimed.

N0-only implementation rejects unsupported paused/reset/reordered inputs rather
than guessing epochs; generalized multi-recording support remains future scope.
Public data approval, privacy/license review and frontend/deployment are separate
gates. Q1 remains INCONCLUSIVE/RECOVERY UNKNOWN; active guard unchanged. £0 unchanged.
