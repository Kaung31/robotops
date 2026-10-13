# Publication blocker remediation — 2026-10-13

**GO for owner review of the corrected source-only candidate.** Local verification
passes. No dataset, binary/container, deployment or historical-rights clearance is
implied. Hosted CI remains unverified and must be green before a later merge.
No push, PR, merge, data licence assignment or publication was performed.

Base: `8430110b583e97db9d3d0114e5b8061f3fb7df8d`.
Remediation branch: `codex/publication-remediation`.
Implementation commit: `6c32d3dcffca1b5baae5970f6eaf6555f435830d`.
The report commit and clean source-candidate commit are recorded in the owner handoff.

## Provenance and licensing

All five original files remain unresolved in historical authorship. Local history
starts with the initial public import; archived ownership/provenance comparisons
provide similarities, not a complete source chain. All five were therefore
reconstructed under the owner's explicit offline authority:

| File within robot_navigation/config | Replacement basis / disposition |
| --- | --- |
| `navigation.yaml` | Nav2 server/checker/costmap/behavior/BT parameter interfaces; newly authored RobotOps configuration |
| `localization.yaml` | Map-server and AMCL parameter interfaces; newly authored RobotOps configuration |
| `profiles/navfn_rpp.yaml` | NavFn and RPP parameter interfaces; newly authored RobotOps configuration |
| `profiles/smac_dwb.yaml` | Smac and DWB parameter interfaces; newly authored RobotOps configuration; ordered critics retained as a behavior contract, no example block transplanted |
| `slam.yaml` | SLAM Toolbox parameter interfaces; newly authored RobotOps configuration, no example/implementation text reused |

The new expression/comments are Apache-2.0 project source. API names, literal
settings and order-sensitive lists preserve accepted behavior. This is not a
clean-room or retroactive authorship claim. See
[the provenance record](CONFIGURATION_PROVENANCE.md) for reconstruction details and
[the exact reference index](configuration-upstream-references.json) for immutable
URLs, source versions, SHA-256 identities and file-specific licence observations.

NOTICE now distinguishes current reconstruction from unresolved historical versions,
and records Nav2's mixed Apache/BSD/LGPL licensing. AMCL's inspected node has an
LGPL-2.1-or-later header; configuring it does not copy its implementation. SLAM
Toolbox package/root LGPL metadata coexists with non-specific CCPL implementation
headers. No variant was guessed and none of that implementation/prose was reused.
No LGPL source-copy obligation is identified for these new parameter files.
`slam_runner` linkage and dependency/binary distribution compliance remain separate.
Root LICENSE and the exclusion of recordings/derived datasets are unchanged.
The dataset-licence recommendation no longer asserts historical YAML derivation as
fact; no dataset licence was assigned.

## Original / replacement comparison

Paths below are relative to `ros2_ws/src/robot_navigation/config/`.

| File | Accepted raw SHA-256 | Reconstructed raw SHA-256 |
| --- | --- | --- |
| `navigation.yaml` | `730e72a252dfc551a336295c110709cd5b7cd0a630c86fea8001778f94594d39` | `f11ee69137c8a8f6a0ddf4feeb05737eb8d37cb3937a899e407814bd26147c96` |
| `localization.yaml` | `37fda2bdb0dcc98ad5727d73b820fb11bf6847a016eafc452c2a720173ed466e` | `9e7ac1307c8173a735d1e69bd6763d6799af732dbcdc3650f0e268eb61a03a4d` |
| `profiles/navfn_rpp.yaml` | `b2773fafd39a85ce43b5ae3f90f015b314b12fdf469a26c5b999bdfac5694feb` | `8263bc434e9fb719e6df65528eaca6c45797f6f3980e989c48601650580b92b5` |
| `profiles/smac_dwb.yaml` | `c612b7a0f162854f9ecde5a270ca642a8bf35c3a3618ab411c01d33a2df18ba9` | `7d2ba7b558d5431030f23d20c6f3464b76119247fb36209135068588f8fd3ce4` |
| `slam.yaml` | `674fa9abefc5039fb6539f678b04fa6d6b6c36242602e04ec8c8c80e82b7c895` | `ac57e0a6315e99af191b7bf3f0d2af5b9f7a270c553bd1a9b0e52114d4863748` |

All five parsed structures, scalar types and list orders match exactly. The native
ROS C YAML parser confirms identical names/types/values for 244 parameters
(105 navigation, 37 localization, 28 NavFn/RPP, 49 Smac/DWB, 25 SLAM).
All eight composed profile/clock/normal-or-wider-geometry combinations match.
Accepted effective profile hashes remain unchanged and are regression-tested.
All 13 tracked recording-configuration/benchmark files are byte-identical to the
accepted integration; normal campaign recording profiles and production code
are unchanged.

Frozen benchmark manifests still pin the old raw YAML. The strict validator
correctly rejects reconstructed bytes, with an explicit regression test. Only
new temporary test matrices bind new raw pins; their effective-parameter pins
remain frozen. No historical matrix, report, result or source hash was rewritten.
Historical reproduction uses the original revision; new benchmark specifications
require their own review. This grants no W01–W06/W3/W4 execution authority.

## Privacy and history

Four actual worktree-path occurrences in the two CI reports now use portable
`ROBOTOPS_CI_WORKTREE` / `ROBOTOPS_INTEGRATION_WORKTREE` placeholders. Historical
test results and verification claims are unchanged. One adversarial warehouse
fixture uses a generic private path instead of a real local username. The full
proposed public diff has no detected actual worktree paths, credential patterns,
recordings, historical execution files or unintended generated dataset files.
Intentional public author identity and generic privacy-test inputs remain.

Sanitising a tip does not sanitise unpublished ancestors. Retain this integration-
based remediation branch locally. A separate `codex/publication-clean-source`
commit is prepared with the exact final tree, parented to public main `ebdb551`;
it avoids incorporating the unredacted unpublished report commits into public
ancestry. This creates new local history without rewriting any existing branch
or public history. Use that candidate for later publication review, not a direct
push/merge of the remediation branch. Already-public original YAML remains
historical material; the new source/NOTICE correct it prospectively, without
claiming retroactive rights clearance.

## Actual local verification

Fresh isolated Python/npm dependencies; no private recording/replay fixtures.

| Check | Result |
| --- | --- |
| Dependency consistency | pip check passed |
| Portable Python | 404 passed, 3 expected ROS-dependent skips |
| CI helper tests | 8 passed |
| Frontend | 67 passed, 7 private-data skips |
| TypeScript / scoped Pyright | Passed; zero typing errors |
| Ruff, C++ format, YAML, CMake, XML | Passed |
| actionlint, ShellCheck, diff whitespace | Passed |
| Dashboard / replay / static-site builds | Passed; code only, no datasets |
| Fresh Jazzy build | 11 packages passed |
| Passive ROS aggregate | 286 results, zero errors/failures/skips (266 cases plus 20 CTest wrappers) |
| Installed resources/imports | 11 packages, 36 resources passed |
| Offline warehouse utilities | 193 passed, 70 private-evidence skips |
| Native ROS YAML comparison | 244 named/typed values identical |

A provisional rclpy-helper test failed on nested target lookup and scientific-value
string reparsing for **both original and replacement** files. That helper is not
the native parser used by the launch parameter files. The incorrect added test was
removed and native C-parser equality verified instead; no configuration was changed
to accommodate it. Final passive results above have no failures. Existing production
validators/assertions remain strict. Known deprecation/update and Vite size warnings
remain; no live operation, mock/Gazebo launch, fault injection, recording, or private
replay suite was run. Test-generated analytic maps are isolated new fixture inputs.

Preservation comparison: all three existing developer HEADs, branches, indices,
1131 source-file hashes and statuses match the before snapshot; all 25,362 protected
artifact/archive metadata entries and all 244 guard hashes/identities match.
This is an inventory/guard check, not a fresh full-content hash of every recording.
The three pending W3 harness files remain unmodified and excluded from this change.
Q1 remains **INCONCLUSIVE / RECOVERY UNKNOWN**.

## Exact files changed from accepted integration

- `NOTICE`
- `backend/tests/test_warehouse_benchmark.py`
- `docs/CI_INTEGRATION_REVIEW.md`
- `docs/CI_READINESS_REVIEW.md`
- `docs/CONFIGURATION_PROVENANCE.md`
- `docs/PUBLICATION_REMEDIATION_REPORT.md`
- `docs/configuration-upstream-references.json`
- `docs/plans/publication-remediation.md`
- `docs/plans/recorded-lab-dataset-licence.md`
- `ros2_ws/src/robot_navigation/config/localization.yaml`
- `ros2_ws/src/robot_navigation/config/navigation.yaml`
- `ros2_ws/src/robot_navigation/config/profiles/navfn_rpp.yaml`
- `ros2_ws/src/robot_navigation/config/profiles/smac_dwb.yaml`
- `ros2_ws/src/robot_navigation/config/slam.yaml`
- `ros2_ws/src/robot_navigation/test/test_navigation_configuration.py`
- `scripts/test/test_warehouse_export.py`

No remaining technical blocker was found for the corrected source snapshot.
Historical authorship uncertainty and upstream header discrepancies are explicitly
retained; binary distribution and historical-rights advice are outside this scoped
source decision. Stop for owner review. No public action is authorised by this report.
