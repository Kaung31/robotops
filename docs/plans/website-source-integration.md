# Final website source integration

Starting point: reviewed clean publication `62d35ab1ea07aad0f40eb37d7be6c030da01e1d3`.
Owner accepts website commits 446798b, 131cde2, bd21aa0, 4e9af61 and 8544cfd.
Apply their patches in order, preserving clean publication ancestry. Update the
existing source-only PR; no merge, deployment, dataset publication or robotics run.

Success criteria:
- Every website file matches accepted Claude revision 8544cfd; review the complete
  changed-file inventory and any source/licensing documentation reconciliation.
- Rebuild site code and privately stage exact existing bundle copies in this
  isolated checkout; compare every byte with the accepted private launch inventory.
  No original evidence is overwritten or re-exported; no bundle is tracked/pushed.
- Preserve current reconstructed navigation YAML, frozen raw benchmark pins,
  historical reproduction instructions, production backend/ROS code and results.
- Carry the accepted website licence metadata without selecting a new licence or
  modifying dataset manifests; retain corrected source-provenance NOTICE text.
- Run source-only ordinary lint/typing/Python/frontend/ROS passive checks and all
  production builds. Separately run frontend checks with private copied fixtures.
- Audit source changes and reachable new commit history for accidental private
  paths, credentials, recordings, execution artifacts or dataset payloads.
- Preserve existing developer source/index/status, original artifacts/archives and
  routing.guard. Q1 remains INCONCLUSIVE / RECOVERY UNKNOWN.
- Push only the clean publication branch, update its PR, verify the three actual
  hosted CI jobs, and stop for owner review without manual robotics dispatch.

Local completion: all five patches applied; 92 web files match accepted source.
Private stage reproduces all 235 accepted files (8,190,310 bytes). Source-only and
private-fixture frontend checks, Python/lint/typing, full build/passive ROS and
installation checks pass. NOTICE/source provenance reconciled without changing
accepted licence decisions. Original developer trees/evidence/guards match.
Detailed identities/results are in docs/WEBSITE_SOURCE_INTEGRATION_REVIEW.md.
Hosted CI remains pending until this final source revision is pushed.
