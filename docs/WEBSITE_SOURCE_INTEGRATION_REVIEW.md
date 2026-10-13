# Final website source integration — 2026-10-13

**Local verification PASS; hosted CI pending on the final pushed revision.**
Owner-approved integration of the six reviewed website commits into the corrected
clean publication source. No merge, deployment, dataset upload, new licence choice,
robotics workload or manual robotics workflow dispatch.

Starting point: `62d35ab1ea07aad0f40eb37d7be6c030da01e1d3`, the reviewed PR #1 head.
Branch: `codex/publication-clean-source`. Update the existing source-only PR against
`main`; do not import the original Claude integration ancestry. Final combined
commit and hosted results are recorded in the owner handoff.

## Commit and file identity

| Reviewed original commit | Applied patch commit |
| --- | --- |
| `446798b83f9349053826a49f544eb83e96da1013` | `17255f6a48b661d174fb5b353de326a7b65850f7` |
| `131cde238b4a2a18c59077b11015ea93d11748a2` | `1f594a07f358ca6f0802dd56aea2aa5cc4c64c48` |
| `bd21aa0e113ec001c2c60935838bd72582b40cd6` | `827b83a949b899755645d22cb93302a7762ddc49` |
| `4e9af619eecbc1d0c2adfd8dffd36db05515e26f` | `16b8172b377fa9c0faac4580524724306c80e99b` |
| `8544cfd2cb9cc4cdc1bee48d3947ffdc52d3d668` | `d1751a82de682e413d22425e05925ca2bcb2e448` |
| `d7cae95035fcd679896cd2237c6c23244627e63c` | `6e0ed9d40a23a7777a99bcc9ab520525ab11c6b1` |

All six patches applied without textual conflict. Range-diff preserves the first
four patches exactly; the fifth's NOTICE context differs because the corrected
source-provenance declaration is retained. All **92 files under web/** match
accepted Claude revision `d7cae95` byte-for-byte, including source, tests, release
metadata, lockfile and build scripts. Current-status and website-plan changes are
also included. The reconstructed YAML, ROS/backend production code, frozen matrix,
campaign definitions, recording profiles, benchmark result table, reproduction
boundary and source LICENSE are unchanged from the starting point.

NOTICE retains the corrected navigation reconstruction/dependency terms and carries
the accepted website CC BY 4.0 metadata. An added sentence makes source exclusion
and lack of upload/deployment authority explicit. The current configuration
provenance document now reflects the accepted licence metadata, while retaining
historical authorship uncertainty. The dataset-licence plan keeps its corrected
source-rights paragraph. No new licence was selected, no manifest/export flag or
dataset byte was edited, and no dataset was published. Earlier dated remediation
reports remain historical records rather than being rewritten.

## Reproduced private launch build

The accepted launch inventory contains **235 files / 8,191,836 bytes**. Its inventory
SHA-256 is `49cb5e59d4d1475ddc93c4c21c9548991cf911fe23c690e406a0c51e25e34794`.
The SHA-256 of `site-final.SHA256SUMS` is
`ae8fc4420836c08dceb1b2061fd3ea31425b83cba0f03daebd52a4b2bbf7aca3`.
The original package was accessible: all 235 files were verified against both its
checksum list and inventory. A fresh build using the real private release inputs
reproduced all 235 files and the inventory byte-for-byte. Only `robots.txt` and
`THIRD_PARTY_NOTICES.txt` differ from the previous accepted launch package.

The rebuilt private stage has exactly the same path inventory and every file is
byte-identical, including hashed JS/CSS names, HTML, notices, licence/release
metadata, and all existing bundle bytes. There are 15 site-code/configuration files
and 220 private bundle files in that stage. No new dataset export was performed.

Verification used 228 isolated copied frontend fixture files, checked against their
original hashes (including the earlier compatibility fixture). Originals were read
only. The stage and copied fixtures live only in ignored local artifacts; they are
not part of the Git diff or CI uploads. The default build remains source-only and
requires no private recordings. The accepted homepage's 110-point W01 route
illustration and benchmark summary constants are reviewed website source; tests
re-derive them from the pinned copied datasets. Full replay bundles remain private.

## Final patch verification

The prepared handoff patch applied directly above `cd7952a`, without importing
unpublished ancestors. It changes only `web/scripts/finalize-site.mjs`,
`web/scripts/stage-release.mjs` and `web/tests/portfolio-release.test.mjs`.
Public indexing is now permitted by robots.txt. The generated third-party notice
includes the MIT copyright and permission text for the bundled Rollup CommonJS
helper, extracted from the installed, locked Vite licence. No root NOTICE or
dataset licence decision changed. This integration report is the only additional
tracked documentation correction.

The source-only frontend passed 79 tests with 8 expected private-data skips; the
real-fixture suite passed all 124 tests. Typecheck and all three production builds
passed. Complete web source matches `d7cae95`; all tracked paths outside web and
this report remain identical to `cd7952a`, including reconstructed navigation,
recording profiles, frozen benchmarks and historical reproduction instructions.

The final patch also passed static checks, portable Python (404 passed, 3 expected
ROS-dependent skips), 8 CI helper tests and scoped Pyright (zero errors). The first
host-shell lint attempt lacked container-installed Python modules; rerunning in
the configured Jazzy container passed without changing source or requirements.
The new preservation snapshot matches all 1,144 developer source files, all
27,042 original artifact/archive metadata entries and all 244 guard hashes.
Hosted CI on the final pushed revision is reported separately in the owner handoff.

## Earlier integration local checks

| Check | Result |
| --- | --- |
| Locked Python installation / pip consistency | Passed |
| Portable Python | 404 passed, 3 expected ROS-dependent skips |
| CI helper tests | 8 passed |
| Source-only frontend | 79 passed, 8 private-data skips |
| Copied-fixture frontend | 124 passed, no skips/failures |
| TypeScript / scoped Pyright | Passed; zero typing errors |
| Ruff, C++ format, YAML, CMake, XML | Passed |
| actionlint, ShellCheck, diff whitespace | Passed |
| Dashboard / replay / static-site production builds | Passed |
| Fresh Jazzy build | 11 packages passed |
| Explicit passive ROS tests | 286 aggregate results, zero errors/failures/skips |
| Installed resources/imports | 11 packages, 36 resources passed |
| Source-only ROS warehouse utilities | 193 passed, 70 private-data skips |
| Accepted private launch comparison | All 235 files byte-identical |

The initial online npm install timed out. An isolated copy of the previously
populated dependency cache allowed `npm ci --offline` using the unchanged lockfile
and integrity checks. No dependency/framework or test requirement was changed.
Hosted npm installation is verified separately by the ordinary PR job. ROS utility
checks used a clean source archive and newly generated analytic map fixtures,
without private replay bundles. No ROS/Gazebo nodes, experiments or fault injection
were started. Existing deprecation/update and Vite bundle-size warnings remain.

## Privacy, history and preservation

New commit ancestry extends only the reviewed clean source history. The original
Claude commits and unpublished integration/remediation histories are not ancestors.
Source scans cover the complete proposed public diff and tracked file inventory;
no credentials, actual machine/worktree paths, original MCAP, execution artifacts
or private dataset bundles may be included. Only explicitly reviewed site figure,
summary constants and release metadata are carried as website source.

Earlier integration before/after checks matched all three existing developer worktree HEADs, branches,
indices, source-file hashes and statuses (1144 files). All 26,799 protected original
artifact/archive metadata entries and all 244 guard hashes/identities match. The
three pending W3 harness edits remain untouched and excluded; original recordings,
reports and configuration identities are retained. This inventory/guard check is
not a new full-content hash of every archived recording. Q1 remains
**INCONCLUSIVE / RECOVERY UNKNOWN**.

## Exact changed files from the reviewed publication source

- `NOTICE`
- `docs/CONFIGURATION_PROVENANCE.md`
- `docs/CURRENT_STATUS.md`
- `docs/WEBSITE_SOURCE_INTEGRATION_REVIEW.md`
- `docs/plans/recorded-lab-dataset-licence.md`
- `docs/plans/website-experience.md`
- `docs/plans/website-source-integration.md`
- `web/README.md`
- `web/portfolio.html`
- `web/release-config/DATA-LICENSE.txt`
- `web/release-config/RELEASE.json`
- `web/replay.html`
- `web/scripts/finalize-site.mjs`
- `web/scripts/homepage-route.mjs`
- `web/scripts/stage-release.mjs`
- `web/src/components/MapView.tsx`
- `web/src/portfolio/Portfolio.tsx`
- `web/src/portfolio/benchmark.ts`
- `web/src/portfolio/main.tsx`
- `web/src/portfolio/portfolio.css`
- `web/src/portfolio/w01-route.ts`
- `web/src/replay/ComparisonPanel.tsx`
- `web/src/replay/LabSections.tsx`
- `web/src/replay/ReplayLab.tsx`
- `web/src/replay/ValidationPanel.tsx`
- `web/src/replay/WarehouseBanner.tsx`
- `web/src/replay/WarehouseComparisonPanel.tsx`
- `web/src/replay/data-warehouse.ts`
- `web/src/replay/main.tsx`
- `web/src/replay/presentation.ts`
- `web/src/replay/replay.css`
- `web/src/replay/warehouse-comparison.ts`
- `web/src/site/BenchmarkCautions.tsx`
- `web/src/site/SiteChrome.tsx`
- `web/src/site/StripChart.tsx`
- `web/src/site/release.ts`
- `web/src/site/site.css`
- `web/tests/lab-structure.test.mjs`
- `web/tests/portfolio-release.test.mjs`
- `web/tests/replay-presentation.test.mjs`
- `web/tests/replay-v2.test.mjs`
- `web/tests/replay-warehouse.test.mjs`

**Stop for owner review after hosted CI.** Updating the source PR does not authorise
merging, Cloudflare deployment, dataset publication or a GitHub Release.
