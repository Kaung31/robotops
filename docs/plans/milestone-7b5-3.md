# Milestone 7B.5.3 — Idempotent Nav2 lifecycle readiness

This corrective patch keeps Nav2 Lifecycle Manager ownership and fixes retry/readiness behavior observed during integration.

- Query each Lifecycle Manager's `/is_active` service before `STARTUP`.
- Never send `STARTUP` to an already-active manager (Nav2 STARTUP is not idempotent).
- Re-check manager active state after a failed STARTUP to handle concurrent bringup races.
- Treat the manager group state as authoritative for readiness; per-node `get_state` remains diagnostic.
- Treat a valid `map -> base_link` transform with active localization manager as sufficient localization evidence even if the web gateway misses `/amcl_pose`.
- Keep `/amcl_pose` as useful telemetry, not a hard startup gate.
