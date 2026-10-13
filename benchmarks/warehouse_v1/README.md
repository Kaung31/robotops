# Warehouse navigation matrix v1 — offline specifications

W1/W2 only. Six PLANNED slots; no execution or publication authority. The actual
world/map/mission has not been qualified in Gazebo/Nav2. This compares two complete
planner/controller configurations, not isolated algorithms or statistical superiority.

- `matrix.json`: exact ordered 3+3 slots, scenario/source/profile/effective parameter
  hashes, common mission/policy and unknown initial-state/seed declarations.
- `campaigns/W01.json` … `W06.json`: proposed existing `CampaignDefinition` inputs,
  each one profile and one repetition. They contain no generated runtime identities.
- `matrix.schema.json`, `evidence.schema.json`: structural schemas. Python model
  and filesystem validation are also mandatory for ordering, cross-field conditions,
  path confinement, file hashes, composition and deterministic geometry checks.
- Private initial index: `artifacts/warehouse-w3-offline-20261012/evidence-index.json`.
  Never move it into public assets. PLANNED/NOT_RUN have no runtime observations.
  ATTEMPTED can retain incomplete/unassessed references and real generated IDs after
  future approval; reference hashing is not a source-chain qualification or verdict.
  Manual original-measurement import is rejected until the later qualified audit.

Geometry source: `ros2_ws/src/robot_simulation/config/warehouse_v1.json`. Original
static primitives implement the owner-approved plan. No external assets. Generated
SDF lives in `robot_simulation/worlds/warehouse_v1.sdf`; analytic map/association live
privately in `artifacts/maps/warehouse_v1.*`. Occupancy is not SLAM or sensor evidence.

Offline regeneration into a NEW inspection directory (never overwrite history):

```bash
python scripts/warehouse_scenario.py \
  --descriptor ros2_ws/src/robot_simulation/config/warehouse_v1.json \
  --output /tmp/robotops-warehouse-new-inspection
```

The frozen matrix binds historical **raw configuration bytes**, including the
pre-reconstruction navigation YAML. Current YAML preserves effective values but
cannot be substituted into this matrix; the strict checker correctly rejects its
new hashes. Do not update historical pins or weaken validation. Use matching
original source/configuration and the preserved private index for a historical
check. The exact dirty software state of W01–W06 is not fully identified, so this
is not a claim of exact runtime reproduction. Current source can support new
normal campaigns, which require their own identities and do not rewrite v1.
See [reproduction limits](../../docs/WAREHOUSE_BENCHMARK.md#reproduce) and
[configuration provenance](../../docs/CONFIGURATION_PROVENANCE.md).

With matching historical source and backend dependencies, check the existing plan:

```bash
python scripts/prepare_warehouse_matrix.py check \
  --evidence-index artifacts/warehouse-w3-offline-20261012/evidence-index.json
```

`prepare` is deliberately new-only and refuses existing proposals/indexes. Do not
remove reviewed files merely to run it again; preserve/version changes for review.
Do not submit campaign definitions to an operational API under the W1/W2 approval.
No Start button, execution service, fault route or recording exporter was added.

See `docs/warehouse-w1-w2-implementation-review.md` for results and W3 approval gates.
The historical five-file YAML provenance holds were addressed prospectively by
an owner-approved offline reconstruction. Their original authorship remains
unresolved; the new configuration does not retroactively clear historical rights.
The frozen matrix retains the old raw identities.

## Offline floor-contract correction — 2026-10-12

W3 stopped before mission and remains NOT QUALIFIED. The original floor identifier
was incompatible with the unchanged contact adapter. Corrected floor names preserve
all physical geometry; the matrix now binds corrected world/association/generator
hashes. All six slots remain PLANNED. The W1/W2 index and W3 evidence are historical
and unchanged; use the new corrected private index above for current hash checks.
No replacement or delayed qualification is authorised. See
`docs/warehouse-w3-offline-corrections-review.md` before requesting requalification.
