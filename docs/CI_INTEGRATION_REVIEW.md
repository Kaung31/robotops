# Local CI / warehouse integration review — 2026-10-13

**Local ordinary CI checks PASS. Ready for an owner-approved GitHub PR;
GitHub-hosted CI remains UNVERIFIED. No push, PR, merge or deployment performed.**

Branch: `codex/ci-warehouse-integration`.
Worktree: `$ROBOTOPS_INTEGRATION_WORKTREE`.
The exact final report commit is recorded in the owner handoff and local Git history.
The tested code/configuration revision before this documentation commit is
`ef663d5886f52c589619081380c35e55d62e54e4`.

## Commits incorporated

The base is reviewed `claude/warehouse-benchmark-lab` HEAD
`275f0c5f72bbb698ba8dbc3a572288130c18b5b3`, containing these seven commits:

| Original commit | Change |
| --- | --- |
| `354bada66efed2f956018ac94009acd370934e79` | Wrapped-launch shutdown, shutdown reports and software evidence |
| `61375fa8e4975232d67b4c28d1df7d4c9f096d0b` | Recorder loss accounting and storage readiness |
| `83ae886a7c07834ac2496368eb076a7076a0aec7` | Validation profile and aligned ground-truth comparison |
| `e2a70a9355f52347cec8a1ac6784cf4f62145fb9` | Warehouse exporter and independent audit |
| `6de34ad3e19b85b7f72547e6d89f39fa91f27a88` | Recorded Lab warehouse selection/comparison |
| `a706a4fcda34eeb920d6fd3c2819dd67310f459a` | Benchmark and lab documentation |
| `275f0c5f72bbb698ba8dbc3a572288130c18b5b3` | NumPy dependency explanation |

Additional integration commits:

| Integration commit | Origin / purpose |
| --- | --- |
| `f2efc157357284aaf714b5f9650dcb7d6d260540` | Cherry-pick of CI foundation `e373657e9574d35ac523b80f0ee9cd382fe7c14e` |
| `e2b02147509fce74099abbf1e3ccb74fd06aaee0` | Cherry-pick of formatting `d41a3a534bfb8d7d0a6cd97d5516325679ceaa41` |
| `1d10802ef03a94eb6408abc2c9a25677737324f9` | Separately reviewed pending recorder correction + regressions |
| `ef663d5886f52c589619081380c35e55d62e54e4` | Equivalent YAML formatting, ground-truth test selection, collection correction |

There were **no textual cherry-pick conflicts**. Dependency ranges/NumPy explanation
from Claude remain intact and satisfy the existing CI lock (`pip check` passed).
CI workflow configuration had no competing Claude edits. Formatting preserves
all seven native/CMake token streams and original include order; Claude's added
`experiment_ground_truth` CMake registration was retained and added to the explicit
passive test allowlist. No check, plugin, assertion or dependency gate was disabled.

## Independent recorder review

The uncommitted two-file patch was reviewed before incorporation. Its implementation
is byte-identical to Claude's retained installed `recording.py` and current working
source: SHA-256 `1724dae18113a45caf89473a41830eb43b8152ca3b1a9be4ff7bea0a4e3bd3d5`.
Only additional tests differ from the pending recorder test file.

For the installed Jazzy versions (rosbag2 0.26.11 / rclcpp 28.1.21), sim time creates
a TimeSource `/clock` subscription; recording `/clock` creates another. The correction
requires exactly two owned readers in that combination, otherwise the appropriate
single reader. It requires the recording subscription log acknowledgement and checks
**each** owned reader's topic type and offered/requested QoS. Unrelated nodes' readers
cannot complete the pair. Other topics retain exact-one cardinality and durable-history
requirements. Live-process, writer, clock-receipt, storage and final recording/loss
checks remain independent and strict. Readiness remains capability, not coverage.

The original acceptance event confirms two `/clock` readers: one best-effort,
one reliable, both volatile, with expected count two. The acknowledgement is in
its original recorder log. Missing/extra readers, bad QoS, missing acknowledgement,
second-reader type mismatch, unrelated ownership, wall-time recording and
TimeSource-only configurations are covered by regression tests. All 48 recorder
artifact/readiness tests pass in Jazzy, including the actual QoS compatibility check.
The reviewed profiles use canonical `/clock`; arbitrary remapping/relative aliases
were not live-tested.

Primary source review: [rosbag2 recorder](https://raw.githubusercontent.com/ros2/rosbag2/0.26.11/rosbag2_transport/src/rosbag2_transport/recorder.cpp),
[rclcpp TimeSource](https://raw.githubusercontent.com/ros2/rclcpp/28.1.21/rclcpp/src/rclcpp/time_source.cpp).

## Configuration identities and collection correction

Only list indentation changed in
`ros2_ws/src/robot_recorder/config/warehouse_qualification.yaml`. PyYAML structures
compare equal before/after; canonical structure SHA-256 is
`3450bb577db66c98a853b0272b8259fd7298811bfebebe39aa8a07890b3b73a0`.

- Original file: `a6fc485cbc999f74c75c4d756414e8b0f2cc19655242fde7ab334cbb457c02ab`.
- Current integration file: `65c00bb2ffd2524a18b1af992a63588c21566b8e1896b63da0ad9663905e555d`.

Historical hashes/records remain unchanged. Old plans pinning the original source
bytes do not identify this integration revision and must not be reused as execution
permission. The normal campaign's default and validation recording profiles are
unchanged. The frozen matrix, navigation profiles, world/configuration assets and
historical map identities remain unchanged.

A demonstrated collection failure required a narrow test-only correction:
Jazzy's `launch_testing` hook imports test modules before pytest's ordinary module
collector. The private warehouse module's existing module-level skip consequently
aborted collection of sibling utility files. Replacing it with `pytest.mark.skipif`
retains the exact same private-data availability condition and all test assertions,
while permitting ordinary fixtures to collect. No plugin was disabled. Both paths
were verified: 193 ordinary utility cases pass without private results (70 existing
private cases explicitly skip); all 219 private replay/export cases pass with originals.
A CLI import-mode change was investigated and did not solve the problem; no such
configuration change was retained.

## Local verification

| Check | Result |
| --- | --- |
| Locked Python install, editable backend, `pip check` | Passed |
| Portable Python tests | 394 passed, 3 existing ROS-dependent skips |
| CI helper tests | 8 passed |
| Scoped Pyright | 11 files, zero errors/warnings; broader typing backlog remains |
| Ruff, C++ formatting, YAML, CMake lint/format, XML/Xacro/SDF | All passed |
| actionlint + ShellCheck | Passed, actionlint download checksum verified |
| Frontend tests with original private bundles | 111 passed, no skips |
| TypeScript and application/replay/site production builds | Passed; code-only site build, no publication |
| Fresh isolated Jazzy colcon build | All 11 packages passed, 2 min 41 s |
| Passive ROS tests | 20 CTest registrations, 257 individual JUnit/GTest cases, no skips/failures |
| Colcon aggregate | 277 results (257 cases + 20 CTest wrappers), zero errors/failures/skips |
| Public-source ROS utility collection | 193 passed, 70 private-data skips |
| Original-fixture warehouse + N0/N2 exporter/compatibility suites | 219 passed, no skips |
| Six warehouse exports | W01–W06 rebuilt in memory, byte-identical to originals; independent audits passed |
| Installation consistency | 11 installed manifests/ament markers, 36 resources, 8 Python import targets passed |
| rosdep consistency | All system dependencies satisfied |
| Actual acceptance evidence parsing | `/clock` assessment, loss accounting, shutdown report and software metadata verified |

Warnings: existing Starlette/AnyIO and rosdep/pkg_resources deprecations, a Pyright
update notification, Vite bundle-size warnings, and a local pip cache ownership
warning (installation still succeeded). No local test failure remains in the
applicable scope. Portable ROS skips are covered by passive Jazzy tests except
the live gateway callback regression, which remains in manual robotics integration
and was not run. The broad type backlog, physical hardware and live navigation are
outside this local validation. GitHub-hosted execution has **not** been tested.

Reproduction uses the existing `scripts/ci/{test_python,check_static,check_workflows,
build_ros,test_ros}.sh` entry points and the locked installation commands in
[CI_READINESS_REVIEW.md](CI_READINESS_REVIEW.md). Frontend commands were `npm ci`,
`npm test`, `npm run typecheck`, `npm run build`, `npm run build:replay` and
`npm run build:site`, within `web/`. Installation verification ran outside source
in `/tmp`; rosdep dependency checking passed. Local Podman Git trust settings were
per-process and restricted to this new worktree.

Private suites ran `test_n0_replay.py`, `test_baseline_v2.py` and
`test_warehouse_export.py` using the isolated ROS fixture venv. The local-only
`private_fixture_plugin.py` retains original absolute fixture paths because reports
hash-bind them, verifies schemas/matrix against this integration copy, prohibits
Python-level writes into both developer checkouts and blocks process/ROS-node
initialization. No source assertion or provenance path was rewritten. Six export
builds/audits kept generated payloads in memory. Frontend checks used 228 copied
private bundle files with identical hashes; nothing was published or relicensed.

## Differences from the accepted runtime

Acceptance campaign `8838d36bbefb4e8e859937810891d6f7` recorded
`git:ebdb551…+dirty:c4afea26d3db`. Its actual clean three-process shutdown report
parses exactly with the integrated model. Recomputed recorder loss accounting
matches `message_loss.json` exactly (complete, zero lost). Its mission metadata
matches recorded software identity and source `git`.

38 relevant campaign/mission/recorder/experiment source files were compared with
Claude's current reviewed source: 37 match byte-for-byte; the remaining W3 YAML
has the verified formatting-only difference. Recorder and mission-server Python
also match the retained installed files byte-for-byte. The native/CMake changes
retain tokens and include order. Added recorder tests, CI selection/collection,
documentation and commit identity do not alter campaign logic.

**The new binaries are not asserted identical to the acceptance binaries.**
The CI helper selects `RelWithDebInfo`; retained acceptance-workspace CMake caches
have an empty build type for ten packages (diagnostics already has RelWithDebInfo).
Compiler path is `/usr/bin/c++` in both. Actual target flags confirm additional
`-O2 -g -DNDEBUG` for the new contact plugin, SLAM runner and command guard;
diagnostics and the compiled-but-never-run fault relay retain matching flags.
Build paths/debug information also differ.
No compiler/configuration retuning was introduced during integration, but these
existing CI build choices preclude claiming identical runtime timing or newly
validated navigation. The acceptance dirty-source record is an aggregate identity,
not a full per-file archived snapshot; retained source/install comparison is the
available evidence. No new live acceptance campaign was run under this authority.

## Preservation and W3 harness disposition

Both existing developer worktrees retain their exact HEAD, branch, index hash,
tracked/untracked source contents and status. `codex/ci-foundation` stays at
`d41a3a5` with both accepted commits intact. Claude's checkout retains all five
original pending files: the recorder pair was copied here, not committed/reset there.

The following **three pending W3 harness files remain exactly in Claude's checkout**
and were not integrated, discarded or reclassified as completed work:

- `ros2_ws/src/robot_navigation/test/warehouse_session.py`
- `scripts/test/test_warehouse_driver.py`
- `scripts/warehouse_qualification/driver.py`

The committed historical harness baseline remains in the repository. Its pending
changes are independent of the normal campaign workflow and still need their own
review/disposition. No W3 verdict or attempt budget was changed.

Preservation checks: 974 historical SHA-256 pins match; the complete 25,362-entry
original artifact/archive metadata inventory is unchanged; all 244 snapshotted
`routing.guard` paths retain contents and filesystem identities. This includes
W01–W06 evidence/reports, historical W3 material, archives and Q1. Metadata inventory
is not a new full-content hash of every archived file; the 974 pins and guard hashes
provide the explicit byte checks. No source evidence directory was reset or relocated.
Q1 remains **INCONCLUSIVE / RECOVERY UNKNOWN**.

Private diagnostics are in this worktree's ignored `.ci-results/integration/`,
including test XML/logs, YAML equivalence, acceptance-source comparison, native token
comparison, six independent export audits and preservation receipts. No ROS/Gazebo
runtime, campaign, mission, recording or fault injection was started. The existing
Jazzy container was resumed solely for offline checks; no developer overlay was
rebuilt or sourced.

**Recommendation:** ready for owner review and, after explicit approval, an approved
GitHub PR/push. Require all ordinary hosted CI jobs on that exact revision before
merging. Hosted cache/image/dependency/event behaviour remains unverified. Keep
robotics integration manual; do not dispatch it under this task. No licences assigned,
public PR opened, data published, main merge, push or deployment performed.

**STOP for owner review.**
