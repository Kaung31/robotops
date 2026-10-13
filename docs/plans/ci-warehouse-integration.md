# Isolated CI / warehouse integration

Base: reviewed claude/warehouse-benchmark-lab HEAD 275f0c5 (seven commits).
Integrate e373657 and d41a3a5 locally, then independently review/commit the two
pending recorder clock-readiness files. Preserve the three W3 harness files in
Claude's checkout; do not include them. No robotics execution or public actions.

Success criteria:
- Existing developer checkout contents, indices, branches and protected evidence unchanged.
- Frozen benchmark/map/profile identities and original historical hashes preserved.
- Clock correction models recorder subscriptions, with unrelated gates still strict.
- YAML indentation changes only after parsed-structure equivalence verification.
- Complete ordinary CI, new ground-truth package test, and private exporter/compatibility
  checks run with original fixtures where safely available; disclose gaps/failures.
- Compare relevant runtime source against acceptance evidence and retained installed files.
- Local descriptive commits and concise integration report; stop for owner review.

Progress: new worktree/branch created at reviewed HEAD. Both CI commits applied
without textual conflict. Backend dependency comment and Claude's new ground-truth
CMake registration remain present. Existing Jazzy container resumed for offline work.

Completed: recorder correction separately committed with extra regressions;
YAML equivalence verified before formatting; ground-truth passive test added;
existing private-data skip converted to marks after a proven collection-hook failure.
All ordinary local checks pass. Original-fixture tests 219/219, frontend 111/111,
and all six warehouse exports byte-reproduce with independent audit passes.
974 historical pins and full original artifact/archive metadata remain unchanged;
both developer trees/indices/branches and all 244 guard identities are preserved.
Source/build differences and hosted uncertainty are in docs/CI_INTEGRATION_REVIEW.md.
Stop for owner review. No robotics execution, public action or integration into main.
