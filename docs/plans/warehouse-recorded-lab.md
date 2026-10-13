# Warehouse Benchmark v1 in the Recorded Lab — plan and status

Status 2026-10-13: implemented as a private release candidate. Publication,
deployment and the dataset licence are owner decisions and have not been made.

## Scope

Adopt the six 2026-10-12 warehouse trials (W01–W06) as an exploratory benchmark
and make them explorable in the static Recorded Lab, without rerunning them or
changing their original reports. W03's teardown crash is disclosed, not hidden.

## Success criteria

1. Only the six pinned trials export; every source (report, runner manifest, run
   metadata/result, bag metadata, MCAP, contact evidence, map, matrix) must match
   its pinned SHA-256, and the backend's own integrity check must say `VERIFIED`.
2. Metrics, verdicts, report IDs and report limitations are copied exactly and
   checked against JSON pointers into the original report.
3. Trajectories and LiDAR come only from the recorded MCAP: map→base_link poses
   at ≤20 Hz, every second scan with every fourth ray, explicit gaps, no
   interpolation across gaps and no extrapolation.
4. No absolute paths, logs, parameter dumps, hostnames or usernames in any file.
   Private logs are referenced by hash only.
5. Exports are byte-for-byte deterministic, and an independent audit re-decodes
   each MCAP and compares every exported sample, TF reference and ray.
6. The lab can select W01–W06 and compares them with original values only; the
   W03 disclosure, "exploratory, not qualified" status and limitations are shown.
   Visitor checks never change original verdicts.

## Implementation

- `scripts/replay_warehouse_models.py`: strict schema-3 manifest. Pose and scan
  chunks reuse the unchanged v1 models.
- `scripts/export_warehouse_v1.py`: pinned exporter (writes only under
  `artifacts/warehouse-lab-20261013/`, never overwrites).
- `scripts/audit_warehouse_v1.py`: independent source audit, privacy scan and
  byte-identical repeat check.
- `scripts/replay-schema-warehouse-v1.json` (copied to
  `web/src/replay/schema-warehouse-v1.json`; tests require identical bytes).
- Web: `data-warehouse.ts` (pinned loader), `warehouse-comparison.ts`,
  `WarehouseComparisonPanel.tsx`, `WarehouseBanner.tsx`; `ReplayLab` adapts its
  coverage text to full-window recordings. N0/N2 code and pins are unchanged.
- Release tooling (`stage-release.mjs`, `serve-replay.mjs`) accepts the six pinned
  warehouse bundles alongside N0/N2.

The N0/N2 exporters are not modified, so their pinned manifests still reproduce.

## Results

All six export in about 12 s each; the repeat exports are byte-identical. Each
dataset is 1.12–1.18 MB (33–35 files): ~2,270–2,365 pose samples and 681–710
scan samples, with one continuous TF segment. The only pose gap is about 0.54 s
before dispatch, while AMCL's future-dated map→odom transform is not yet
available, so every trial has supported poses for the whole navigation window.
The audit compared every sample (about 64,000 indexed ranges per trial) and found
no differences. The privacy scan found nothing.

## Limitations recorded in every manifest

Exploratory, not qualified; three trials per configuration; planner+controller
bundles; one world and start; simulation time on one host; localized TF rather
than physical truth; no Nav2 event reconstruction; downsampled display; no
original Git revision; hashes are not signatures; contact observation is scoped
to monitored geometry. W03 also carries `TEARDOWN_CRASH_AFTER_FINALIZATION`.

## Running it (private)

From a sourced Jazzy workspace with pydantic available:

```bash
python3 scripts/export_warehouse_v1.py --dataset W01 --output artifacts/warehouse-lab-20261013/dataset-w01-final --audit-output artifacts/warehouse-lab-20261013/export-receipt-w01-final.json
```

Repeat with the `-repeat` suffix, then run `scripts/audit_warehouse_v1.py` with
`--dataset`, `--repeat` and `--output`. Tests: `scripts/test/test_warehouse_export.py`
(needs the private artifacts) and `web/tests/replay-warehouse.test.mjs`.
