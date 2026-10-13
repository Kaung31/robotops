# Isolated CI foundation

Base: reviewed main ebdb551, branch codex/ci-foundation, isolated worktree.

Success criteria:
- Keep the active checkout, runtime source/configuration and historical evidence untouched.
- Preserve existing checks; move live integration suites to explicit manual dispatch.
- Required PR jobs: portable lint/tests/type scope, frontend locked install/tests/builds,
  Jazzy package build and explicitly selected non-runtime package tests.
- Fail on check errors and dependency/installation inconsistencies; retain logs/results.
- Record exact local commands/results, type backlog and hosted-CI uncertainty in
  docs/CI_READINESS_REVIEW.md. No robotics execution, publication, merge or push.

Stages:
1. Audit workflow/dependencies/test safety and reuse the existing Jazzy container.
2. Implement narrowly scoped CI configuration and reproducible local entry points.
3. Run safe checks/builds in this worktree, record failures without weakening tests.
4. Review diff and recommend isolated owner-reviewed integration; stop.

Audit: baseline CI has portable lint/tests, web tests/type/build/replay, and six
Jazzy suites on every push/PR. Default Jazzy tests include live mock/ROS tests;
sim/mapping/navigation/mission/experiment suites start Gazebo. Existing scripts
replay tests require private untracked evidence and cannot be ordinary public CI.

Completed: all four stages. Three ordinary CI jobs and a preserved manual runtime
workflow are implemented. Fresh dependency install, 351 portable tests + 8 CI
helpers, 193 offline ROS-dependent utility cases, 11-package build and 229 unique
passive package cases pass. Type scope and workflow checks pass. Inherited C++,
CMake and recorder YAML formatting/lint remain blocking and were not modified.
Full results, commands, broader type backlog and hosted uncertainty are recorded
in docs/CI_READINESS_REVIEW.md. No robotics runtime or original evidence writes.
Work stays isolated; no push, merge or deployment. Stop for owner review.
