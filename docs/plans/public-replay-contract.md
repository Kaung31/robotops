# Static playback contract

## Status

Implemented: deterministic offline exporters (`scripts/export_n0_replay.py` for
v1, `scripts/export_baseline_v2.py` for v2) with strict schemas
(`scripts/replay-schema-v1.json`, `scripts/replay-schema-v2.json`), independent
audits, and the static Recorded Lab reader for the pinned N0/N2 datasets. v2 adds
the saved mission-action status, explicit trial identity and observational
condition metadata; pose/scan chunks and time/frame semantics are unchanged from
v1. Exports keep recording gaps, nanosecond timestamps as strings and the
original metrics/verdicts, with gzip chunks and no raw MCAP or private paths.
`dataset.sha256` hashes the manifest bytes. Clock resets and replay of arbitrary
recordings are not supported. The sections below are the original design. See
also [the public architecture](../PUBLIC_DEMO_ARCHITECTURE.md).

## Exact source availability drives the contract

Five audited mission bags provide /clock, /odom, /tf, /tf_static, /scan, /map,
/joint_states, /imu/data, command streams, diagnostics and monitored contacts.
They do **not** contain /amcl_pose, independent Gazebo pose truth, Nav2 action
status/feedback, planner paths or fault events. Localized motion can be derived
from recorded map→odom→base_link TF only where TF supports the requested time.
Original final pose/quality/verdict is a separate report snapshot. Never backfill
missing telemetry with that final pose or describe odometry as physical truth.

All five MCAP streams have contiguous 1 ms /clock samples within their recorded
interval, but start after dispatch and stop before final observation. Each has
five early scans without a map-frame TF lookup (AMCL forward-dated map→odom).
The source map is 199×159, 0.05 m/pixel, origin [-4.967,-3.969,0]; scans contain
360 rays at 10 Hz, frame lidar_link. No initial map transform may be invented.

Mission events.jsonl is not included in the original run artifact fingerprint.
Its fresh audit hash is an inventory snapshot, not retroactive authoritative
provenance. `navigating` is a coarse mission stage, never a Nav2 start event.
No Git revision is available in these source reports; keep null/reason. Current
source manifest cannot prove the source revision that created an older recording.

## JSON envelope and file layout

Proposed manifest `manifest.json` and lazy chunks for poses/scans/events. This is
a design schema, not generated example telemetry. Every object forbids unknown
versions; unrecognized fields affecting semantics require a new version.

| Field | Type / invariant |
|---|---|
| schema_version / kind | 1 / `robotops.recorded_playback`; never reuse CampaignReport schema/name. |
| dataset_id / dataset_sha256 | Opaque approved ID / exact canonical manifest bytes hash stored externally (avoid self-hashing recursion). |
| exporter | Version, code digest, configuration digest; absent until P2. Stable serializer/sample selection. |
| source_identity | Approved original experiment/trial/run/report opaque IDs, robot model, sim mode, environment, profile; nullable software revision with reason. Private source-location mapping stays local. |
| sources[] | Opaque reference ID, artifact kind, original SHA256, integrity state and scope (`original_bound`, `audit_snapshot_only`, `derived`). No absolute source paths, URLs or free-form private labels. |
| assets[] | Allowlisted relative path, kind, bytes, SHA256, segment/time bounds and schema_version. No `..`, absolute/backslash/scheme URLs, symlinks or off-origin assets. |
| time | ROS ns decimal strings, named clock domain, mission start/end plus runner dispatch/observation, duration source pointers; separate recorded/TF-replay coverage. Monotonic playback offsets, no implicit UTC/wall mapping. |
| segments[] | ID/epoch, start/end ROS ns strings, playback start/end integer µs, valid frames, quality, boundary/gap reason. No interpolation between segments. |
| coverage | Required streams and observed intervals, initial/terminal gaps, unsupported checks; full-mission replay false for current candidates. |
| scene | Map dimensions/resolution/origin yaw/encoding/hash, frame contract, approved robot visual model hash; schematic 3D occupancy label unless exact world/model provenance supports more. |
| metrics | Named finite values + units + exact source field pointer + source_ref + quality. Missing null/reason, never zero. Preserve original recorded precision. |
| original_validation | Original ROS outcome/action status, localized-pose policy/verdict/measured errors/quality, monitored-contact verdict/coverage separately, report ID/hash. Sanitized derivative is not byte-identical original report. |
| limitations / publication_review | Typed limitation codes and approved descriptions; owner-approved dataset/asset version receipt separate from deterministic content. No default publication permission. |

Source refs use canonical JSON Pointer where applicable, e.g.
`/campaign/trials/0/evidence/validation/xy_error_m`. MCAP refs include approved
artifact hash, topic, source stamp and message ordinal; no local filename. Retain
precise provenance for measured metrics distinct from downsampled display data.

Pose chunk records: `segment_id`, `ros_ns` decimal string, `offset_us` integer,
`frame`, position [x,y,z] in metres, quaternion [x,y,z,w], optional derived yaw in
radians, source refs, `quality` and reason. Source kind explicitly
`localized_tf` or `odometry`, never `ground_truth` for these candidates. Validate
finite normalized orientation; do not substitute identity on invalid quaternion.
Trajectory references this ordered pose stream; unavailable points break paths.

LiDAR chunk records: segment/stamp/offset/frame, radians angular minimum/increment,
range bounds/metres, original ray count, explicit selected original indices,
ranges and validity reasons. JSON has no NaN/Infinity. Null+`no_return` differs
from corrupted data; absent scan differs from all-invalid ranges. Each sample has
a valid-time base→lidar transform or is unavailable. Projection into map needs
valid map→base at the same source time. Preserve original data source hashes.

Events: source timestamp/segment/ordinal, kind, exact stage and actor/goal IDs
where available, provenance quality. Mission-stage JSON events can be offered as
exploratory annotations with audit-snapshot provenance; do not silently promote
them to originally sealed evidence. Current bags have no Nav2 execution/fault
channels. R1 component evidence is a different dataset kind, not navigation fault
validation. Future faults require qualified mission/trial/session/plan identities
and independent event/MCAP checks, with requested/armed/accepted/started/applied/
recovery concepts kept separate.

## Coordinate transform contract

ROS frames are right-handed, metres, z up; planar yaw is counterclockwise about
+z. For PGM image pixel (column u, top-down row v), cell-centre map position is
`origin_xy + R(origin_yaw) * [resolution*(u+0.5), resolution*(height-v-0.5)]`.
OccupancyGrid row indexing is bottom-up; do not flip both the array and its
transform. Preserve map origin yaw, even though current candidate yaw is zero.

Three.js y-up display uses the proper rotation `(x,y,z)_ROS -> (x,z,-y)_Three`.
Transform sensor points through timestamp-valid lidar→base→map first, then apply
this display rotation once. ROS quaternion [qx,qy,qz,qw] maps to
[qx,qz,-qy,qw] in this display basis; normalize/validate before interpolation.
Robot geometry axes and model origin must be verified against URDF, not inferred
from an attractive animation. P2 fixtures must verify an origin pixel, both map
corners, positive yaw, laser forward direction and a known TF composition.
Do not bake display-axis conversion into the archived ROS pose coordinates.

## Precision, ROS clock and coverage rules

ROS epoch nanoseconds are decimal strings matching `^[0-9]+$`, parsed with BigInt
for ordering/difference arithmetic. Offset µs are nonnegative integers <=2^53-1,
computed with integer division; preserve ns remainder/source stamp separately.
Browser display milliseconds/seconds are derived only after safe bounded relative
conversion. Original double-valued metric precision is retained; never compare
rounded display strings. Time domain is explicit per metric.

Split epochs on clock reversal/source restart; split TF/frame discontinuities
and missing intervals. Within continuous time, proposed display thresholds are
pose gap <=100 ms and relevant dynamic TF bracket gap <=250 ms. These are
export/display policies, not original experiment acceptance policies; declare them
in extraction config. Current audited odom gaps <=25 ms and map→odom gaps 100 ms;
P2 must verify each individual sample and temporal TF bracket, not assume these
aggregate counts prove all transformations trustworthy. Static TF does not expire.

Position linear interpolation and shortest-path quaternion/yaw interpolation are
allowed only between valid same-frame/same-epoch bracketing samples within bounds.
No extrapolation, path joining across gaps, fabricated scans or inferred movement
from commands. At a missing interval show unavailable/frozen-last-known labelled
stale, never animate it as measured motion. Final report pose appears in an
independent evidence panel/marker with its own timestamp; no connecting animation
across an unrecorded terminal interval. Report mission duration remains unchanged.

Paused/repeated ROS stamps do not create ROS duration or motion. Coalesce only
identical samples with explicit duplicate count; preserve conflicting observations
as a quality issue. Represent wall pause length only if trustworthy wall timestamps
and clock-domain mapping exist. rosbag record time here is ROS time and cannot
supply wall pause length. Original result has total elapsed wall seconds, but
that total alone does not locate pauses or map individual samples to wall time. Clock resets never share interpolation state. Missing
clock association means UNKNOWN time mapping, not an inferred epoch.

## Deterministic visitor validation (design, not implemented)

Each check records policy version, finite nonnegative threshold + explicit units,
source metric/value/quality, outcome and reasons. Invalid thresholds are input
errors, not PASS/FAIL. Quality prerequisites are evaluated before thresholds.

| Check | Calculation / boundaries | Unknown or not assessable |
|---|---|---|
| ROS mission duration | Original `mission_ros_seconds <= threshold_s` PASS, greater FAIL. Equality passes. | Missing/corrupt provenance, regressed/undefined metric clock. Partial visual replay alone does not invalidate an independently bound original duration. |
| Localized final XY | hypot(final map x-goal x, final map y-goal y) <= metres threshold. Match original unrounded error as independent P2 check. | Missing/invalid TF/final observation, stale source quality or untrusted provenance; do not use last rendered pose. |
| Localized yaw | abs(atan2(sin(final yaw-goal yaw),cos(final yaw-goal yaw))) <= threshold_rad; threshold [0,pi]. ±pi wraps identically. | Missing/nonfinite orientation or frame/time/quality invalidity. |
| Odometry distance | Existing measured `odom_path_metres <= threshold_m`; label odometry estimate. | Missing value/provenance; do not recalculate from downsampled display path and impersonate original metric. |
| No observed non-support contact | Covered scoped contact detected → FAIL; original valid monitored coverage and no detections → PASS for this explicitly scoped observation criterion. | Missing/incomplete coverage → UNKNOWN; universal physical collision freedom → NOT_ASSESSABLE. |
| Planned-path smoothness, planning latency, physical pose accuracy | Unsupported by the inspected recorded channels. | NOT_ASSESSABLE; do not infer from duration, command stream or 3D animation. |

A valid originally failed tolerance check may pass a looser visitor threshold;
original verdict remains visible and unchanged. Invalid evidence may never become
PASS by relaxing a threshold. Do not conflate original threshold failure with
missing provenance. Preserve original stale/TF/provenance quality reasons.

No authoritative combined success. Optional visitor summary includes every check,
UNKNOWN and NOT_ASSESSABLE; no dropping unavailable checks or combining ROS/pose/
contact into a new engineering verdict. Download format is distinct:
`kind: robotops.visitor_analysis`, analysis_version, dataset/source hashes,
selected checks/thresholds/units, measured values, outcomes/reasons and
`not_an_authoritative_experiment_report: true`. Unique analysis ID in its own
namespace; never reuse original report IDs or filenames. No backend writes.

P2 acceptance fixtures (before any UI): exact threshold/below/above; NaN/negative
inputs; pi wrap; valid original FAIL with looser visitor PASS; missing/corrupt
metric always UNKNOWN; incomplete contact coverage; paused/reset clock; unsafe
integer conversion; initial TF gap and unrecorded tail; same inputs/config byte-
identical exports; decoded MCAP sample comparisons and tampered-hash rejection.
These are proposed tests, not a claim browser validation already exists.

## Size, privacy and smallest next task

Candidate bags are 4.08–6.13 MB each, but include ~20,000–30,000 clock messages.
Do not upload raw bags. Proposed initial budget: manifest/map/overview <=250 KiB
compressed initial transfer, <=5 MiB compressed per lazily loaded scenario,
<=1 MiB chunks (well below Pages asset ceiling), pose display <=20 Hz, scans
<=5 Hz with deterministic selection and original indices. Benchmark after export;
these are targets, not measured export sizes. Load one scenario at a time, retain
original metrics independently of display downsampling. No ROS/backend/network
control imports. £0 Pages static assets only; no Functions/storage upgrade.

Privacy allowlist excludes absolute paths, usernames/machine names, IPs/ports,
account/session secrets, raw logs, arbitrary mission labels, internal config
paths and full parameter dumps. Raw records demonstrably contain home paths,
UTC labels and robot-internal names; do not copy wholesale. Publish only approved
opaque IDs/hashes, parameters that explain the comparison, map/robot visuals,
metric/verdict values and typed quality limitations. Exact approved asset list,
source/data license and sanitized preview require owner approval **before upload**.

Smallest P2 proposal: one private deterministic exporter for normal N0 only,
fixed JSON envelope and map/TF/pose/scan chunks, explicit coverage gaps,
provenance/size/privacy report, byte-identical fixtures and decoded-source checks.
No public frontend or upload. Scope/files/tests must be reviewed before P2 starts;
P1 approval does not authorize this implementation. Stop here after R1/P1.
