# CI readiness review — 2026-10-13

> Integration follow-up (2026-10-13): the combined branch now passes local YAML
> and ordinary CI checks. See [CI_INTEGRATION_REVIEW.md](CI_INTEGRATION_REVIEW.md).
> The review below records the accepted isolated foundation and formatting history;
> its earlier YAML blocker is resolved only in the separate integration worktree.

**Implemented and locally validated in isolation. GitHub Actions has not run.
CI must not be described as green: the recorder YAML gate still fails.
The approved C++/CMake formatting follow-up is complete; see section 9.**

Worktree: `$ROBOTOPS_CI_WORKTREE`.
Local branch: `codex/ci-foundation`, based on reviewed `main` / `origin/main`
`ebdb551` (Initial public release of RobotOps). No fetch changed that baseline.
The owner's active checkout and its uncommitted work were not checked out,
reset, cleaned, staged or edited. Git worktree registration necessarily adds
worktree/branch metadata to the shared repository, without changing its active index.

## 1. Existing foundation and coverage

The original `.github/workflows/ci.yml` supplied:

- Python 3.12, Ruff, C++ formatting, YAML/CMake/XML checks and the default pytest suite.
- Node 22 frontend tests, TypeScript checking, application and replay production builds.
- Six Jazzy suites (`mock`, `sim`, `mapping`, `navigation`, `mission`, `experiment`)
  on every push/PR. These build all packages and include live ROS/mock/Gazebo tests.
- Installation smoke checks, gateway callback regression, rendered shutdown regression,
  colcon result reporting and log upload.

Existing Python coverage includes backend API/persistence/ownership/reports,
geometry and configuration, recorder/mission validation and evidence contracts.
Frontend tests cover polling/campaign observations, replay schemas, read-only
boundaries, calculations and saved-report handling. Source-only testing cannot
replace private-recording correspondence tests or live robotics qualification.

The original root pytest configuration did not collect `scripts/test`. Its
warehouse tests are now included in the Jazzy job with their real Python/ROS
message dependencies, while remaining offline fixtures. Private replay export
suites (`test_n0_replay.py`, `test_baseline_v2.py`) remain unchanged and require
original private inputs; no synthetic recordings were supplied to replace them.

## 2. Workflow changes

`.github/workflows/ci.yml` now provides three independent jobs for PRs, pushes to
`main`, and manual dispatch:

| Job | Required checks |
| --- | --- |
| Python and static checks | Locked dependencies, `pip check`, actionlint/ShellCheck, inherited Ruff/C++/YAML/CMake/XML gates, scoped Pyright, backend/model and CI helper tests |
| Web tests, typecheck and build | Cached `npm ci`, existing tests, unchanged TypeScript check, application and read-only replay production builds |
| Jazzy build and passive package tests | rosdep install/check, all 11 packages built with colcon, installed-resource/import verification outside source, 19 named passive CTest registrations, offline warehouse utility fixtures |

`.github/workflows/robotics-integration.yml` preserves the original six Jazzy
suites and their runtime tests, smoke checks, result reporting and uploads.
It has **only `workflow_dispatch`**, with no push, PR or scheduled trigger. It
was not dispatched during this task. Dispatching it starts robotics workloads;
review and authorise that separately. Ordinary PR jobs start no robotics runtime.

Actions are pinned to full commit SHAs; the existing action major versions were
retained. Both workflows use read-only repository permissions, bounded job
timeouts and diagnostic artifacts. PR concurrency cancels obsolete checks;
manual robotics concurrency does not automatically cancel a running suite.
No deployment, publication or secret-dependent step was added. Uploads contain
CI logs/test XML/package inventories, not recordings or private datasets.

The static helper runs all its check families, records their failures, then exits
nonzero if any failed. Type checking and portable tests still run after a lint
failure when dependency installation succeeded, while the job remains failed.
Tests retain their original assertions. Colcon uses
`--return-code-on-test-failure`; its separate result step runs even after failure.
A pre-test inventory verifies every allowed CTest name appears exactly once, and
`--no-tests=error` prevents an empty selection passing silently. No
`continue-on-error`, ignored test exit code, assertion relaxation or new skip was added.

## 3. Python type scope and backlog

Pyright 1.1.407 uses Python 3.12 and `basic` mode, with no diagnostic suppression.
The initial enforced scope contains eight backend modules:
`models`, `gateway`, `state`, and campaign `models`, `ownership`, `repository`,
`service`, `report_models`; plus the three new CI Python helpers. These give useful
coverage of typed API/state contracts, persistence/ownership and CI verification
without changing campaign/runtime source owned by the other developer. CI helper
tests are excluded from type analysis, but run under pytest and Ruff.

The initial pre-configuration broad audit found 208 errors in 43 analyzed files.
The final broader audit with the new import paths and `basic` settings found
**199 errors across 46 analyzed files**; the enforced 11-file scope reports **zero
errors and warnings**. These are different audit configurations, not a claim that
runtime typing defects were repaired. Final broad counts include:

| Area outside enforced type scope | Errors |
| --- | ---: |
| Warehouse qualification runtime | 53 |
| Campaign reports | 24 |
| ROS gateway | 19 |
| N0 replay exporter | 18 |
| Baseline replay exporter | 17 |
| Orchestrator | 13 |
| Warehouse observer/driver tests | 21 |
| Other replay audits, models and warehouse helpers | 34 |

Missing ROS/generated imports contribute to the broader result; other errors
include optional accesses, argument mismatches and dynamic structures. The audit
used a portable venv, so it is not a definitive ROS typing verdict. Expand this
scope module by module after owner-reviewed fixes and suitable generated-message
stubs. Runtime/ROS adapters, app/API wiring, reports, exporters and tests remain
backlog. `basic` checking also permits unknown/Any types; this is an initial gate,
not complete strict typing. Reproduce the final broad audit with:

```bash
pyright --pythonpath .venv/bin/python backend/robotops_backend scripts --outputjson
```

## 4. Dependency and reproducibility decisions

- Existing `requirements-dev.txt` pins portable tools. The backend declares Python
  `>=3.12,<3.13` and bounded runtime dependencies in its existing pyproject. Neither
  file was changed, avoiding the other developer's pending backend dependency edits.
- New `requirements-ci.lock` pins the complete tested Python resolution for
  Ubuntu 24.04 / CPython 3.12, including Pyright and explicit setuptools/wheel build
  tools. Install it together with `requirements-dev.txt`: conflicting declarations
  fail resolution. Install the backend without a second dependency resolution or
  isolated unpinned build environment, then run `pip check` against its declarations.
  An early no-build-isolation probe failed because setuptools was absent; the
  explicit build-tool pins fix that, verified with a fresh venv.
- This pip freeze lock pins versions, not artifact hashes or operating-system
  libraries. Refresh deliberately in a clean Python 3.12 environment, run all
  checks, review transitive changes and regenerate with `pip freeze --exclude-editable`.
  Keep the three header comments. It is not a universal cross-platform lock.
- Frontend semver ranges and the existing npm lockfile remain untouched. `npm ci`
  replaces `npm install`, ensuring exact locked versions and rejecting lock drift.
  The workflow pins the Node 22 major, not a patch or npm binary. Local versions:
  Node 22.23.3 / npm 10.9.9. Python was 3.12.3.
- Jazzy/Noble uses the official ROS base image, pinned to its amd64 manifest digest
  `sha256:a5426de405f6f0a82b0f3def3bbd3bce2a71a91421fe980c17613b4e51ef38d9`.
  Hosted jobs explicitly install colcon/rosdep/venv, resolve package.xml dependencies
  and verify them with rosdep. Apt repositories and rosdep indexes still move;
  an uploaded `dpkg-query -W` inventory records the actual resolution. This is not
  a bit-for-bit rebuild guarantee, and the image pin requires deliberate refresh.
- The existing Podman `jazzy` container was reused locally. Its Ubuntu 24.04/Jazzy
  installation was not rebuilt, upgraded or globally changed. The isolated source
  workspace was built in this worktree. Local validation therefore does not prove
  installation into the freshly pinned hosted image will succeed.
- No colcon build/install cache is restored across revisions. Pip/npm download
  caches key on dependency inputs; caches do not replace installation/checks.
- actionlint 1.7.7 is downloaded from its official release and verified against the
  recorded SHA-256 before execution. ShellCheck comes from Ubuntu's package set.

The utility suite requires an analytic map that is deliberately untracked. The CI
fixture helper uses the existing deterministic `warehouse_scenario.generate`,
checks all three generated map hashes against the frozen committed matrix, and
writes only those exact new test inputs. It refuses any existing `artifacts`
directory and rejects hash drift before writing inputs. It changes no world,
profile, matrix, campaign or original recording; it creates no result, claim or
permission. Its temporary generated SDF is discarded, and nothing is qualified
by these fixtures. This follows the existing backend tests' deterministic map
fixture approach. Private replay recordings remain absent.

References: [GitHub action pinning guidance](https://docs.github.com/en/actions/reference/security/secure-use),
[Pyright configuration](https://github.com/microsoft/pyright/blob/main/docs/configuration.md),
[official ROS image definitions](https://github.com/osrf/docker_images),
[actionlint release](https://github.com/rhysd/actionlint/releases/tag/v1.7.7).

## 5. Actual local validation — foundation commit e373657

All commands below ran only in the isolated worktree. Local diagnostic outputs
are in its ignored `.ci-results/` directory, not original warehouse evidence.

| Check | Actual result |
| --- | --- |
| Fresh locked Python install + editable backend + `pip check` | Passed in a new `.ci-results/clean-venv` |
| Default portable pytest | 351 passed, 3 existing ROS-dependent skips; one Starlette/AnyIO deprecation warning |
| New CI helper tests | 8 passed, including overwrite/hash-drift and installed-resource tampering rejection |
| Warehouse utility tests with ROS dependencies + exact map inputs | 193 passed, no skips |
| Pyright enforced scope | 11 files, zero errors/warnings |
| Ruff lint and format | Passed across the source tree |
| XML/Xacro/SDF syntax | Passed |
| actionlint + ShellCheck | Passed, including checksum verification of the actionlint archive |
| Frontend tests | 63 passed, 5 existing private-dataset skips (68 discovered) |
| TypeScript, app build, replay build | Passed; Vite warns about bundles over 500 kB |
| Fresh isolated colcon build | 11 packages finished, 4 min 16 s |
| Passive ROS package tests | 19 CTest registrations; 229 individual JUnit/GTest cases, no failures/skips |
| Colcon aggregate result | Reports 248 tests, zero errors/failures/skips; includes the 19 CTest wrapper results, not 248 unique cases |
| Installation consistency | 11 installed manifests/ament markers, 35 resources and 8 Python import targets verified outside source |
| rosdep check | All system dependencies satisfied; existing pkg_resources deprecation warning |
| C++/YAML/CMake gates | Failed on inherited source issues listed below; intentionally not bypassed |

Early utility runs failed three cases without rclpy, then seven cases without the
untracked map. All 193 passed after supplying their real ROS Python dependencies
and exact pinned static map inputs. No test or runtime implementation was changed.
The three portable skips are mission recorder preparation, recorder QoS and the
live ROS gateway callback test. Preparation and QoS tests run in passive Jazzy
CTest; the live gateway callback test stays in the preserved manual suite and
was **not run** locally. Frontend skips require deliberately absent private data.

### Exact commands tested

From the host, commands inside Jazzy used:

```bash
cd "$ROBOTOPS_CI_WORKTREE"
podman exec --workdir "$PWD" jazzy bash -c '<command below>'
```

Portable environment and final fresh-install reproduction (without sourcing ROS):

```bash
python3 -m venv .ci-results/clean-venv
.ci-results/clean-venv/bin/python -m pip install -r requirements-ci.lock -r requirements-dev.txt
.ci-results/clean-venv/bin/python -m pip install --no-deps --no-build-isolation -e backend
.ci-results/clean-venv/bin/python -m pip check
export PATH="$PWD/.ci-results/clean-venv/bin:$PATH"
bash scripts/ci/test_python.sh
```

Ruff, static checks and type checking used the initially installed `.venv` with
the same locked package versions:

```bash
export PATH="$PWD/.venv/bin:$PATH"
bash scripts/ci/check_static.sh
pyright --pythonpath .venv/bin/python --outputjson
```

The Podman user mapping requires a transient Git trust setting for `git ls-files`
inside the static helper. Its final run passed these additional **per-process**
options to `podman exec`; no global or repository Git configuration was changed:

```bash
--env GIT_CONFIG_COUNT=1 --env GIT_CONFIG_KEY_0=safe.directory \
--env GIT_CONFIG_VALUE_0="$ROBOTOPS_CI_WORKTREE"
```

Workflow validation ran on the host using Ubuntu ShellCheck extracted locally
from its downloaded package, without installing into the shared container:

```bash
PATH="$PWD/.ci-results/tools/shellcheck/usr/bin:$PATH" bash scripts/ci/check_workflows.sh
```

ROS package commands inside the existing container:

```bash
bash scripts/ci/build_ros.sh
bash scripts/ci/test_ros.sh
rosdep check --from-paths ros2_ws/src --ignore-src --rosdistro jazzy
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
repository="$PWD"
cd /tmp
python3 "$repository/scripts/ci/verify_ros_install.py" "$repository"
```

Offline ROS-dependent utility fixtures, from the worktree inside Jazzy:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
python3 -m venv --system-site-packages .ci-results/ros-venv
.ci-results/ros-venv/bin/pip install -c requirements-ci.lock pytest pydantic lark PyYAML
.ci-results/ros-venv/bin/python scripts/ci/prepare_ros_fixtures.py
.ci-results/ros-venv/bin/python -m pytest -q scripts/test/test_warehouse*.py \
  --junitxml=.ci-results/ros-utilities-final.xml
```

Fixture preparation is new-only: on subsequent runs reuse the verified fixture
and run pytest, or use a new clean worktree. Do not delete/reset original artifacts
to satisfy this helper. Portable tests refuse an environment exposing rclpy, to
avoid inadvertently enabling the live gateway regression.

Frontend commands ran inside Jazzy from the repository root:

```bash
npm ci --no-audit --no-fund --prefix web
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web run build:replay
```

## 6. Remaining failures and limitations

The following issues were present at the foundation handoff. The C++ and CMake
items are now resolved by the formatting-only follow-up in section 9; the YAML
item remains unchanged and blocking:

- clang-format: `robot_simulation/src/contact_evidence.cpp` and
  `robot_diagnostics/{include/robot_diagnostics/freshness.hpp,src/freshness_monitor.cpp,test/policy_trace.cpp}`.
- CMake lint: five line-length violations across `robot_simulation`, `mission_manager`
  and `robot_diagnostics` CMakeLists; cmake-format rejects those same three files.
- YAML: `robot_recorder/config/warehouse_qualification.yaml` indentation at lines
  3, 16 and 49. New workflow YAML passes its checks.

Paths above are beneath `ros2_ws/src/`. The approved follow-up changes only
formatting in the seven C++/CMake files. Recorder YAML remains owned by Claude
and requires a separate correction before CI can pass. No exclusion was added
to hide the remaining failure.

GitHub event routing, permissions, caching, hosted apt/rosdep installation, pinned
container startup, uploads, timeouts and branch protection remain **unverified**.
Local checks are not a GitHub run. After owner-approved integration/push, execute
`RobotOps CI` on the exact combined commit and inspect all three job conclusions,
test counts and retained logs. Do not dispatch `Robotics integration (manual)`
as part of that verification without separate robotics authorisation. Configure
branch protection to require the three ordinary CI jobs after their names/results
have been verified. No hosted job or branch-protection setting was changed here.

No navigation success, W3/W4 qualification, collision-free operation or recorder
runtime reliability is established by these tests. No ROS node, Gazebo session,
mission, recording experiment, fault relay or fault injection was started by this
work. No active `routing.guard` was modified or bypassed. Existing unit fixtures
use temporary test directories; they are not operational guard state. Q1 remains
**INCONCLUSIVE / RECOVERY UNKNOWN**. Claude's independently running work was not
interrupted, its processes were not signalled, and its overlays were not sourced.

## 7. Exact changed files — foundation commit e373657

1. `.github/workflows/ci.yml`
2. `.github/workflows/robotics-integration.yml`
3. `.gitignore`
4. `pyrightconfig.json`
5. `requirements-ci.lock`
6. `scripts/ci/check_static.sh`
7. `scripts/ci/check_workflows.sh`
8. `scripts/ci/test_python.sh`
9. `scripts/ci/build_ros.sh`
10. `scripts/ci/test_ros.sh`
11. `scripts/ci/check_ros_test_selection.py`
12. `scripts/ci/verify_ros_install.py`
13. `scripts/ci/prepare_ros_fixtures.py`
14. `scripts/ci/test/test_install_contract.py`
15. `scripts/ci/test/test_ci_fixtures.py`
16. `docs/plans/ci-foundation.md`
17. `docs/CI_READINESS_REVIEW.md`

No backend, frontend implementation, ROS package, navigation/configuration,
benchmark definition/result, original evidence or archive file changed in the
foundation commit. Section 9 records the separately approved formatting follow-up.

## 8. Safe integration recommendation

Keep this branch/worktree isolated for owner review. This is an implementation
handoff with known blocking lint debt and unverified hosted execution, not a green
CI declaration. No merge, remote PR, push or deployment was performed.

After Claude's work is committed and the owner approves integration, apply the
local CI commit in a separate integration checkout based on the updated reviewed
revision. Review dependency declarations against this lock, reconcile workflow
changes, resolve the inherited lint backlog with the relevant owner, and rerun
local checks there before an approved push/PR. Do not switch, reset or cherry-pick
into Claude's dirty checkout. The pinned static fixture hashes will deliberately
reject incompatible benchmark changes rather than silently substitute inputs.

**STOP after isolated implementation and local validation.**


## 9. Approved static-check cleanup — 2026-10-13

**C++/CMake cleanup PASSED. Overall CI remains BLOCKED by recorder YAML and
UNVERIFIED on GitHub-hosted runners.**

This follow-up stays on `codex/ci-foundation`, based on parent `e373657`.
Before formatting, all seven target files in Claude's active checkout matched
`ebdb551` byte-for-byte. A second comparison after validation found no concurrent
changes to those files, including their inode/mtime/mode/size. No active checkout,
branch, index or uncommitted file was modified.

clang-format 18.1.8 and cmake-format 0.6.13 changed indentation, brace layout,
blank lines and line wrapping only. The exact before/after diff was reviewed.
Automatic include sorting was corrected using blank-line grouping so original
header order remains intact while the default formatter check passes. A lexical
comparison against the parent confirmed identical non-whitespace token spelling
and order in all seven files, preserving comments and string/character literals;
CMake comparison used its tokenizer. Preprocessor directives also retain their
original order. No logic, compiler option, target, test semantics, dependency,
navigation setting or benchmark asset was changed.

### Exact files in the separate cleanup commit

1. `ros2_ws/src/robot_simulation/src/contact_evidence.cpp`
2. `ros2_ws/src/robot_simulation/CMakeLists.txt`
3. `ros2_ws/src/robot_diagnostics/include/robot_diagnostics/freshness.hpp`
4. `ros2_ws/src/robot_diagnostics/src/freshness_monitor.cpp`
5. `ros2_ws/src/robot_diagnostics/test/policy_trace.cpp`
6. `ros2_ws/src/robot_diagnostics/CMakeLists.txt`
7. `ros2_ws/src/mission_manager/CMakeLists.txt`
8. `docs/CI_READINESS_REVIEW.md`

The exact cleanup commit hash is recorded in the owner handoff and local Git
history. No workflow, lockfile, lint configuration or test assertion changed.

### Follow-up verification

| Check | Actual follow-up result |
| --- | --- |
| clang-format across C++ source | Passed |
| cmake-lint and cmake-format across all package CMakeLists | Passed |
| Ruff lint/format and XML/Xacro/SDF syntax | Passed |
| YAML gate | Still fails only on recorder qualification YAML indentation at lines 3, 16, 49; static helper exits 1 |
| Rebuild affected packages | robot_simulation, robot_diagnostics, mission_manager passed; final rebuild 1 min 13 s |
| Affected passive tests, explicitly rerun after final rebuild | 64 individual cases across six CTest registrations, no failures/skips |
| Full ordinary passive ROS suite | 229 individual cases passed, no failures/skips |
| Additional simulation CLI validation | Three invalid-argument cases passed; returns before Gazebo server construction |
| Combined colcon aggregate | 252 results = 232 individual cases + 20 CTest wrappers; zero errors/failures/skips |
| Portable Python and CI helpers | 351 passed / 3 existing ROS-dependent skips; 8 helpers passed |
| Offline warehouse utility fixtures | 193 passed; existing verified map inputs reused, no new preparation |
| Pyright | Existing 11-file scope, zero errors/warnings; broad backlog unchanged |
| Frontend | 63 passed / 5 existing private-data skips; TypeScript and both production builds passed |
| actionlint/ShellCheck | Passed |
| Installation verifier | 11 manifests/ament markers, 35 resources and 8 import targets passed |
| Diff / preservation | git diff --check passed; seven token streams unchanged; recorder YAML and 244 snapshotted guard paths unchanged |

The simulator's argument-validation test starts only the CLI executable with
invalid inputs. Source inspection confirms each case throws before constructing
`gz::sim::ServerConfig` or `gz::sim::Server`. Neither that test nor any other check
started Gazebo, a ROS node/executor, a mission, recording, campaign or fault relay.
Live contact-plugin behaviour and live diagnostics operation were not tested.
The diagnostics parity test runs a stdin/stdout policy executable, not a ROS node.

Existing warnings remain: Starlette/AnyIO deprecation, Pyright update notification,
and Vite bundle size. Existing skips remain visible; none were added. Package
rebuilding reused the installed Jazzy environment and unchanged compiler arguments.

### Exact additional commands

Commands ran in the isolated worktree; container commands used the same
`podman exec --workdir "$PWD" jazzy bash -c '<command>'` wrapper as section 5.

```bash
# Formatter commands, restricted to the seven files listed above:
.venv/bin/clang-format -i \
  ros2_ws/src/robot_simulation/src/contact_evidence.cpp \
  ros2_ws/src/robot_diagnostics/include/robot_diagnostics/freshness.hpp \
  ros2_ws/src/robot_diagnostics/src/freshness_monitor.cpp \
  ros2_ws/src/robot_diagnostics/test/policy_trace.cpp
.venv/bin/cmake-format -i \
  ros2_ws/src/robot_simulation/CMakeLists.txt \
  ros2_ws/src/robot_diagnostics/CMakeLists.txt \
  ros2_ws/src/mission_manager/CMakeLists.txt

# Final affected-package rebuild (no runtime):
source /opt/ros/jazzy/setup.bash
cd ros2_ws
colcon build --packages-select robot_simulation robot_diagnostics mission_manager \
  --executor sequential --event-handlers console_direct+ \
  --cmake-args -DBUILD_TESTING=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo
```

Full passive suite: `bash scripts/ci/test_ros.sh`. After the final rebuild,
affected-package passive tests were explicitly rerun using:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
cd ros2_ws
colcon test --packages-select robot_simulation robot_diagnostics mission_manager \
  --return-code-on-test-failure --event-handlers console_direct+ \
  --ctest-args -R '^(diagnostics_freshness|diagnostics_parity|mission_validation|recording_preparation|mission_launch_validation|gazebo_runner_validation)$' \
  --no-tests=error
colcon test-result --verbose
```

The section 5 commands for static checks (including the transient Git trust
environment), Pyright, portable tests, workflow lint, frontend and installation
verification were rerun. The existing ROS fixture venv ran:

```bash
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash
.ci-results/ros-venv/bin/python -m pytest -q scripts/test/test_warehouse*.py \
  --junitxml=.ci-results/static-cleanup/utilities.xml
```

Follow-up logs and reviewed patch are local to
`.ci-results/static-cleanup/`: `formatting.patch`, `token-review.json`,
`build-final.log`, `affected-passive-tests.log`, `ros-tests.log`,
`static-final.log`, `python.log`, `utilities.log`, `web.log`, `workflows.log`,
`install.log`, and `preservation-final.json`. No original experiment evidence,
archives or benchmark results were changed. Guard verification compares original
content SHA-256, inode, mtime, mode and size. Q1 remains
**INCONCLUSIVE / RECOVERY UNKNOWN**.

The recorder YAML is deliberately untouched and still blocking. GitHub Actions
has not executed; no hosted-green or navigation claim is made. Keep this commit
isolated for owner review and reconcile with Claude's completed work in a separate
integration checkout after approval. No merge, push, publication or deployment.

**STOP for review.**
