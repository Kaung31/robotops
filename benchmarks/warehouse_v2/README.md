# Warehouse navigation benchmark v2 — narrow aisle (offline specification)

Status: **PLANNED, offline only.** Not run, not approved for execution or
publication. Design, findings and limits: [the plan](../../docs/plans/warehouse-v2-narrow-aisle.md).

Warehouse v1's room and 1.2 m `aisle_1`, with every alternative route between the
south and north areas closed. A trial drives start → (3, 0) → (3, 7) → (3, 0) → home,
so it must traverse the aisle northbound and then southbound. Success requires
an independent trajectory check, not just Nav2 reporting waypoints reached.

- `plan.json`: new identity (current profile and shared-file hashes, composed
  parameters, scenario/world/generator/map hashes, validator code), route, aisle
  requirement, measurements and proposed order. It does not reuse or rewrite the
  frozen v1 matrix.
- `campaigns/Q01.json`, `Q02.json`: proposed qualification inputs for the existing
  campaign API, one per configuration.

Offline checks (no ROS, no launch):

```bash
python scripts/warehouse_v2_scenario.py check
python -m pytest backend/tests/test_warehouse_v2.py ros2_ws/src/experiment_runner/test
```

`check` fails if any pinned file changed. That is intended: a changed configuration
is a new benchmark identity, not an edit to this one.

After an approved trial, in a sourced Jazzy shell with nothing running:

```bash
python scripts/assess_warehouse_v2_trial.py artifacts/runs/<run_id> <new-output>.json
```
