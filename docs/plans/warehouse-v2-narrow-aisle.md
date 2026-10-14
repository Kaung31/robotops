# Warehouse v2: narrow-aisle navigation — offline design and feasibility

Status: **offline design only** (2026-10-14). Nothing was launched: no Gazebo,
Nav2, mission, backend or fault injection. Warehouse v1, W01–W06, W3, W4, their
pins, evidence and `routing.guard` are unchanged; recorded evidence was only read.
Q1 remains INCONCLUSIVE / RECOVERY UNKNOWN. Live qualification needs separate
owner approval.

Research question: can NavFn + Regulated Pure Pursuit and Smac 2D + DWB reliably
navigate a genuinely constrained warehouse aisle, and what trade-offs emerge?

## 1. Why warehouse v1 never used its aisles

### Verified (geometry, configuration, recorded evidence)

- v1 has two 1.20 m aisles (x 2.4–3.6 and 4.4–5.6, y 1.5–5.5) between three
  0.8 × 4.0 m racks. The perimeter corridors are 3.5 m (west, east) and 2.9 m
  (south, north) wide.
- Planning footprint: the composer derives `robot_radius` 0.303 m from the
  bounding box of the URDF primitives (0.40 × 0.37 m, chassis offset 0.04 m
  rearward). With `footprint_padding` 0.015 m, Nav2's 16-point footprint has an
  inscribed radius of 0.312 m and a circumscribed radius of 0.324 m. Both costmaps
  inflate to 0.60 m with cost scaling 3.0.
- So every free cell of a 1.2 m aisle lies within 0.6 m of a rack face, and none is
  cost-free. Non-lethal robot centres span x 2.725–3.275 (12 cells; the continuous
  band is 0.576 m, ±0.29 m about the centreline). The cheapest cell on the
  centreline costs 106/252. Perimeter lanes reach zero cost 0.625 m from a rack face.
- Recorded trajectories (Recorded Lab exports, localized TF at 20 Hz, read-only):
  in all six trials **no sample lies inside either aisle**. The new validator finds
  complete, consistent evidence with zero traversals and two bypasses per trial
  (south→north along the west side, north→south along the east side). The west lane
  sits at median x 0.904 m (0.853–0.927) and the east lane at 7.049 m (6.991–7.105),
  about 0.70 m from the rack faces: just outside the inflation radius.

### Hypothesis (planner cost models, not Nav2 itself)

`scripts/nav2_costmap_model.py` rebuilds the static and inflation layers from the
analytic map and searches with simplified cell costs:

| Leg (3,0)→(3,7) | Perimeter (chosen) | Through aisle_1 | Aisle penalty |
|---|---|---|---|
| NavFn-like, (50 + 0.8·c)/50 per m, 16-connected | 9.12 (9.12 m) | 13.67 (6.97 m) | +50 % |
| Smac 2D-like, 1 + 2·c/252 per m, 8-connected | 9.43 (9.43 m) | 10.32 (6.95 m) | +9 % |

Both models put the lanes at x 0.975 m and 7.025 m, within 0.07 m of the recorded
lanes. The likely explanation: the aisles are not blocked (a non-lethal band
exists), but four metres of inflated aisle cost more than a 2.1 m longer, cost-free
detour. Smac's margin is small (9 %), so modest cost changes could flip its choice;
that is untested. The models omit NavFn's interpolated potentials, Smac's smoother,
the scan-only local costmap and all controller behaviour. Nothing in v1 tells us how
either controller behaves inside an aisle.

## 2. Warehouse v2 design

Descriptor: `ros2_ws/src/robot_simulation/config/warehouse_v2.json`; generated
world: `worlds/warehouse_v2.sdf`; generator: `scripts/warehouse_v2_scenario.py`.

- **Kept exactly:** v1's room, walls, three racks and aisle_1 (boxes 1–7 equal
  v1's; the descriptor records v1's descriptor hash), physics and map frame.
- **Added closures** (1.2 m high, overlapping neighbours by 0.1 m so no sliver can
  open): `closure_west` x −2.0–1.7, `closure_aisle_2` x 4.3–5.7, `closure_east`
  x 6.3–10.0, all y 1.5–5.5. They are drawn darker.
- **Result:** the rack band spans wall to wall except aisle_1 (x 2.4–3.6). The
  aisle stays 1.20 m wide and 4.0 m long, the width v1 meant to test.
- **Route** (map frame; yaw faces the next goal, as in v1):
  start (0, 0, 0) → W1 (3, 0, π/2) → W2 (3, 7, −π/2) → W3 (3, 0, π) → W4 (0, 0, 0).
  Each aisle leg is a straight 7 m line, so a trial contains one northbound and one
  southbound traversal. Every goal and turnaround is in open floor 1.4 m from the
  nearest box, at zero inflation cost.
- **No bypass is possible.** Analytically, the only free interval across the band is
  [2.4, 3.6]. On the rasterized map, an 8-connected flood fill from the start reaches
  the north area, but not once the aisle cells are blocked, so not even a point
  slipping diagonally between cells can bypass it.
- **Map:** analytic, same rasterization rule and frame as v1. Fed v1's geometry, the
  v2 generator reproduces v1's pinned world and map hashes byte for byte.

Why 1.2 m and not narrower: it answers v1's open question directly and is
constrained in costmap terms. The width is a single parameter for a later ladder:

| Aisle width | Non-lethal centres | Min. aisle cost | Wheel clearance, centred |
|---|---|---|---|
| 1.2 m | 0.60 m (12 cells) | 106 | 0.415 m |
| 1.1 m | 0.50 m | 123 | 0.365 m |
| 1.0 m | 0.40 m | 143 | 0.315 m |
| 0.9 m | 0.30 m | 166 | 0.265 m |
| 0.8 m | 0.20 m | 193 | 0.215 m |

## 3. Clearance and traversability (1.2 m)

Verified geometry:

- Physical width 0.37 m. Wheel-to-rack clearance: 0.415 m per side on the
  centreline, 0.127 m with the centre at the edge of the non-lethal band.
- The footprint bounding-box radius (0.303 m) is below the inscribed radius
  (0.312 m). Wherever the costmap allows the centre, the robot can turn in place
  without touching a rack: margin ≥ 0.009 m at the band edge, 0.297 m on the
  centreline. The exact union of primitives has a 0.278 m radius.
- Both cost models route the aisle within ±0.05 m of the centreline.
- Observed AMCL error so far: ≤ 0.074 m (warehouse_v1 open floor), against
  ±0.29 m of lateral room for the centre.

Hypotheses for qualification to test:

- RPP's cost-regulated speed estimates 0.60 m to the nearest obstacle on the
  centreline (cost 106), equal to `cost_scaling_dist`. So it should barely slow on
  centre and slow when off centre, never below 0.08 m/s.
- The scan-only local costmap reproduces the static geometry closely enough that
  RPP collision checking and the DWB obstacle critic do not reject the centred path.
- AMCL stays localized along the aisle (lateral features are strong; along-aisle
  cues come through the aisle mouths).
- Recovery behaviours, if triggered inside the aisle, stay collision-free.

## 4. Independent aisle-traversal validation

`ros2_ws/src/experiment_runner/experiment_runner/aisle_traversal.py` (pure, no ROS)
decides from time-stamped map-frame positions only; Nav2's waypoint reports are not
inputs.

- **Zones:** "low" (south of the south gate band), "high" (north of the north gate
  band) and "inside" (between the bands and within the aisle's lateral bounds),
  with 0.15 m hysteresis bands. Positions in a band keep the previous zone, so
  jitter at a gate creates no crossings.
- **Traversal:** low → inside → high (or the reverse). Gate times are interpolated
  where the path crosses the gate line, and the crossing must lie inside the
  opening. Entries that turn back and low↔high moves that skip the aisle are
  reported separately (as aborted entries and bypasses).
- **Evidence checks** (any failure ⇒ INCONCLUSIVE, never a guess): ordered, finite
  samples; no gap over 0.25 s; no jump beyond 0.5 m/s·Δt + 0.1 m; no position over
  0.1 m inside an obstacle. Each mission-window edge must be covered, unless the
  robot could not have reached any zone boundary in the uncovered time.
- **Verdicts:** `TRAVERSAL_VERIFIED`, `ROUTE_REQUIREMENT_NOT_MET` (complete evidence,
  wrong or missing traversals, a bypass or wrong end zone) and `INCONCLUSIVE`.
  Ground truth is required by default and compared, never preferred. Directions,
  time-overlapping intervals, start/end zones and bypass counts must agree.
- **Inputs:** the localized trajectory is tf2 map→base_link at each `/odom` stamp,
  only where both map→odom and odom→base_link have samples bracketing it within
  0.25 s (the Recorded Lab exporter's rule). Ground truth is `simulation/ground_truth`
  (child `robotops`, parent `warehouse_v2`). The map frame is declared to equal the
  world frame; confirm this at runtime.
- `scripts/assess_warehouse_v2_trial.py` applies this to a finished run read-only
  and writes one new file. Its `measure()` is pure and unit-tested.
- `experiment_runner/footprint_clearance.py`: exact rectangle-to-box distance for
  clearance from ground truth.

## 5. Comparison and measurements

The comparison is between configuration bundles (planner, controller and
parameters), used as reconstructed on 2026-10-13 and not retuned. The new identities
live in `benchmarks/warehouse_v2/plan.json`:

- raw hashes of the current profile and shared files;
- composed-parameter hashes;
- scenario, world, generator and map hashes;
- the validator's code.

The v1 matrix is not reused. Per trial:

| Measurement | Source | Limit |
|---|---|---|
| ROS outcome | mission action result | Never sufficient alone |
| Final pose | existing localized validator (0.20 m, 0.25 rad) | Localized, not physical |
| Aisle traversal | validator, localized and ground truth | Route only |
| Mission time | ROS time | Simulation time, one host |
| Aisle transit time | gate-to-gate, per traversal | Excludes approach and turnaround |
| Path length | odometry and ground truth | Odometry drifts |
| Lateral offset | max off the centreline in the aisle | Centre point only |
| Localization error | aligned AMCL TF vs truth, whole mission and in the aisle | Needs ground truth |
| Contact | existing Gazebo contact evidence | Monitored bodies only |
| Footprint clearance | truth + analytic boxes + conservative rectangle | Simulation only |
| Aborted entries | validator | Counts, not causes |

Report per-trial values, counts (k of n) and ranges; no significance claims.
Navigation failures (ROS outcome, final pose, aisle requirement) are kept apart from
INCONCLUSIVE evidence, which counts for neither configuration. Proposed sequence:

1. Qualification Q01 (navfn_rpp) and Q02 (smac_dwb).
2. If both are evidence-complete, 5 + 5 trials in the order AB BA AB BA AB.

## 6. Offline verification (2026-10-14)

- New tests: 15 validator, 4 clearance, 14 scenario/costmap/plan (all pass).
  Portable suite: 407 passed. The local venv still lacks `xacro`, so the three known
  description/bringup/map test files fail at collection, as before.
- Generated world equals the committed SDF; xmllint passes; the support-floor
  identity matches the contact adapter.
- Recorded evidence, read-only:

| Recording | Evidence | Result |
|---|---|---|
| W01–W06 exports | complete | 0 traversals, 2 bypasses each, `ROUTE_REQUIREMENT_NOT_MET` (correct) |
| W01 raw MCAP | 7045 localized samples | same classification; odometry path 28.05 m equals the published value |
| Infra acceptance MCAP (validation profile, warehouse_v1) | localized and truth complete and agreeing | truth path 4.59 m = odometry; max localization error 0.073 m over 1557 aligned samples; minimum footprint clearance 1.10 m |

- First run of the infra recording exposed two issues, both fixed. The mission window
  must end at navigation end, not result finalization. The 0.56 s with no
  bracketed map→odom at dispatch is now accepted only because the robot could not
  have reached a zone boundary in that time.

## 7. Remaining uncertainties

1. Nav2 and controller behaviour inside the aisle has never been observed; §1–§3
   planner statements are model-based hypotheses.
2. Footprint padding, inscribed radius and inflation follow a reading of Nav2 Jazzy
   source. Confirm them against the published footprint and costmap at runtime.
3. The SDF was not checked with SDFormat/Gazebo tools (no `gz` command was run).
   Its structure matches v1's generator, which v1 runs loaded.
4. The map = world frame identity is assumed; it must be confirmed at the start pose.
5. The ground-truth model pose is assumed to coincide with `base_link` in the plane.
   The 7 cm AMCL agreement in v1 is consistent with this but does not prove it.
6. AMCL accuracy inside an aisle is unknown.
7. Recovery counts are not extracted yet.
8. Validator thresholds are design choices. They did not fire on seven real
   recordings, but none of those entered an aisle.
9. The assessment is a separate post-run script, not yet wired into campaign
   reports, so its output is not yet hash-bound in the report.
10. Runtime registration and map installation are not done (§8).

## 8. Steps before the first qualification (each needs approval)

1. **Register the world.** Add `warehouse_v2` to the world choices in
   `robot_bringup/launch/robot.launch.py` and `robot_simulation/launch/gazebo.launch.py`,
   and add a `WorldOption` and a `SIM_SPAWNS` (0, 0, 0) entry in
   `backend/robotops_backend/orchestrator.py`. The two launch files are shared files
   pinned by the frozen v1 matrix: their raw hashes would change, but the v1 pins
   would not. The v2 plan lists them as `not_pinned`, and each trial's
   `software.json` binds the exact revision.
2. **Install the map.** Run `python scripts/warehouse_v2_scenario.py generate --output <new dir>`,
   then copy the four `warehouse_v2.*` files into `artifacts/maps/` (new names
   only). Rebuild `robot_simulation`; then run `gz sdf -k` on the installed world.
3. **Run qualification.** Start the backend with `ROBOTOPS_CAMPAIGN_EXECUTION=1` and
   `ROBOTOPS_RECORDING_PROFILE=validation`, then submit `campaigns/Q01.json` and
   `Q02.json`.
4. **Assess.** Run `scripts/assess_warehouse_v2_trial.py <run dir> <new file>`
   for each trial, then review the results before any benchmark trials.

## Recommendation

v2 is ready for its first controlled simulation qualification once step 1 is
approved and applied. The design forces the aisle, the clearances are sufficient on
paper, and the validator and reader work on real recorded evidence. The open risks
are behavioural, and they are exactly what qualification is meant to test.
