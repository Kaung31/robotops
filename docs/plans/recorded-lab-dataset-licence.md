# Recorded Lab datasets — licence recommendation

Status: CC BY 4.0 approved by the owner on 2026-10-13 and applied in the website
launch build: `web/release-config/DATA-LICENSE.txt` and `RELEASE.json` (the eight
pinned manifest hashes), `NOTICE` and the site footer. The datasets are published
only when the owner deploys the site.
This is an engineering summary, not legal advice.

## What would be licensed

The exported replay bundles (N0, N2, W01–W06): a JSON manifest of metrics,
verdicts, hashes and conditions; downsampled robot poses and LiDAR ranges; and a
grayscale occupancy map. The code that produces and displays them is already
Apache-2.0. `NOTICE` says datasets are excluded from that licence.

## Rights check

- The worlds are original RobotOps primitive geometry: the warehouse descriptor
  states "no external models, textures or assets". The maps are derived from them.
- The robot model, missions and configuration selection are the project's own.
  The current navigation configurations were reconstructed from parameter
  interfaces; historical authorship remains unresolved. See
  [configuration provenance](../CONFIGURATION_PROVENANCE.md). Exported bundles
  identify their historical parameters by hash, not by copying YAML source.
- Telemetry is simulator output. Gazebo, Nav2 and ROS do not claim rights in
  data they produce.
- No personal data: the exporter removes paths, usernames, hostnames, logs and
  wall-clock timestamps, and the audit checks for them.
- In the UK and EU a dataset can carry database rights as well as copyright, so
  the licence chosen should cover both. CC licences version 4.0 and CC0 do.

## Options

| Licence | Reuse | Credit to RobotOps | Notes |
|---|---|---|---|
| **CC BY 4.0** | Any use, including commercial | Required | Widely understood for research data; covers database rights. |
| CC0 1.0 | Any use | Not required (customary only) | Maximum reuse; common for benchmarks. Gives up the attribution requirement. |
| CDLA-Permissive-2.0 | Any use | Licence text only | Designed for data, but less familiar to most readers. |
| Apache-2.0 | Any use | NOTICE retention | Written for software; awkward for data. |
| CC BY-NC / BY-ND | Restricted | Required | Not open data. "Non-commercial" is ambiguous and blocks inclusion in other benchmarks. Not recommended. |

## Recommendation

Use **CC BY 4.0** for the dataset bundles and keep Apache-2.0 for code. It keeps
the data fully reusable while requiring credit, which suits a portfolio project,
and it covers database rights. Choose CC0 1.0 instead if maximum reuse matters
more than credit.

Suggested attribution: "RobotOps Recorded Lab datasets (Warehouse Navigation
Benchmark v1), RobotOps Authors, 2026, CC BY 4.0".

## Steps after the decision

1. Done: dataset licence file and release record next to the published bundles,
   `NOTICE` updated. The licence stays outside the manifests: putting it inside
   would change every pinned manifest hash and require a re-export.
2. Change `publication_review` only through a reviewed re-export, never by
   editing files.
3. Publishing the datasets still needs explicit owner approval.
