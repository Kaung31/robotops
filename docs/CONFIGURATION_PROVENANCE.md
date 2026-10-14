# Navigation configuration provenance

Disposition dated 2026-10-13. This concerns the current source files, not a new
benchmark execution or permission to publish datasets. The existing Apache-2.0
project licence remains in force. Original evidence and recorded configurations
are not relicensed.

## Investigation and disposition

All five files first appear in the initial public import `ebdb551`; their bytes
remain unchanged through accepted integration
`8430110b583e97db9d3d0114e5b8061f3fb7df8d`. Available local Git history, the archived
source-finalisation review, its five-file hold inventory, ownership assessment
and upstream comparison record do not identify their original authoring process
or complete source chain. Earlier open-source/source-availability preferences
are history; they do not establish third-party rights. No source is attributed
solely because it shares ROS parameter names.

Paths below are relative to `ros2_ws/src/robot_navigation/config/`.

| File | Historical evidence | Current disposition / interface reference groups |
| --- | --- | --- |
| `navigation.yaml` | Nav2 functional similarities, no distinctive copied prose; authorship unresolved | Reconstructed: costmaps, controller/planner servers, progress/goal checkers, behavior server and BT navigator (N1–N4) |
| `localization.yaml` | AMCL/map-server keys and defaults do not prove derivation | Reconstructed: saved-map publication, localization frames, particle and observation settings (N5) |
| `profiles/navfn_rpp.yaml` | NavFn/RPP interfaces overlap available examples; source chain unresolved | Reconstructed: planner and controller plugin interfaces (N6) |
| `profiles/smac_dwb.yaml` | A 13-line normalized critic block matches a Nav2 Humble example; actual origin unresolved | Reconstructed: Smac search/smoothing and DWB kinematics, rollout and critic interfaces (N7) |
| `slam.yaml` | Shared SLAM Toolbox keys/defaults; no complete authorship evidence | Reconstructed: lifecycle, frames, input acceptance, matching and transform interfaces (S1) |

All five replacements are newly authored RobotOps configuration under Apache-2.0.
This does **not** assert that the historical files were original RobotOps work,
or retroactively clear the original public import.

## Reconstruction method and boundary

The owner authorised offline reconstruction on 2026-10-13. The accepted files
were reduced to a typed tuning inventory: ROS node/parameter identifiers, literal
values and order-sensitive arrays. That inventory is a functional compatibility
constraint, not a source-text template. The interface declarations and docs below
were consulted to identify the owning parameter APIs and their purpose. New YAML
was authored by operational concern (spatial horizons, motion limits, score terms,
input acceptance and timing), with new RobotOps explanations; no upstream prose,
implementation body, example comments or example block was transplanted.

The DWB critic names, evaluation order and scalar weights remain because changing
them can change short-circuit evaluation and motion. The old example-style critic
block was not reused: the API names/values were separately specified by scoring
purpose. No upstream defaults were substituted for RobotOps tuning. All original
mapping nesting, scalar types and list order are preserved; mapping key order,
comments and presentation are newly authored. This is a documented reconstruction,
not a claim of a clean-room process: the prior configurations were inspected to
retain their operational contract.

The YAML uses standard ROS parameter-file syntax. The pinned ROS parser reference
is included in the reference index. Launch-time clock, geometry, map filename,
initial pose, BT XML and topic overrides continue to come from existing launch
and composer code. No new defaults, plugins, launch behavior or runtime code were
introduced. Keeping an existing parameter does not assert that every upstream
release consumes it; no release migration or retuning was performed.

## Pinned upstream interfaces and file-specific licensing

Exact paths, immutable commit URLs, fetched SHA-256 identities and individual
licence observations are in [the reference index](configuration-upstream-references.json).
It contains metadata, not upstream source. Upstream contents were inspected in
ignored local review outputs and are not distributed with this change.

Nav2 reference N is Jazzy commit
`645abd95f2be02a13ca539b29c2ddc065db34f89` (bringup metadata version 1.3.13).
The separate historical example comparison H is Humble commit
`3c3db59d6969d8ecee8e68468693d006397f4a0c`. These pins describe references inspected,
not a claim that this project ran those precise upstream commits.

| Group | Files within `ros-navigation/navigation2` at N | File-specific observation |
| --- | --- | --- |
| N1 | `nav2_costmap_2d/src/costmap_2d_ros.cpp`; `nav2_costmap_2d/plugins/{static_layer,obstacle_layer,inflation_layer}.cpp` | Each has a BSD-3-Clause header; costmap/layer/scan APIs consulted |
| N2 | `nav2_controller/src/controller_server.cpp`; `nav2_controller/plugins/simple_progress_checker.cpp`; `nav2_planner/src/planner_server.cpp` | Each has an Apache-2.0 header |
| N3 | `nav2_controller/plugins/simple_goal_checker.cpp` | BSD-3-Clause header, not inferred from the package's other files |
| N4 | `nav2_behaviors/src/behavior_server.cpp`; `nav2_behaviors/include/nav2_behaviors/timed_behavior.hpp`; `nav2_bt_navigator/src/bt_navigator.cpp` | Apache-2.0 headers |
| N5 | `nav2_map_server/src/map_server/map_server.cpp`; `nav2_amcl/src/amcl_node.cpp` | Map server: Apache-2.0. AMCL node: explicit LGPL-2.1-or-later, not Apache |
| N6 | `nav2_navfn_planner/src/navfn_planner.cpp`; `nav2_regulated_pure_pursuit_controller/src/parameter_handler.cpp` | Apache-2.0 headers; RPP README also checked, without copying its text/example |
| N7 | `nav2_smac_planner/src/smac_planner_2d.cpp`; `nav2_dwb_controller/dwb_core/src/dwb_local_planner.cpp`; `nav2_dwb_controller/dwb_plugins/src/{standard_traj_generator,kinematic_parameters}.cpp`; `nav2_dwb_controller/dwb_critics/src/{rotate_to_goal,path_align,goal_align,base_obstacle}.cpp` | Smac source: Apache-2.0; listed DWB sources: BSD-3-Clause. Smac README also checked |
| Historical comparison | `nav2_bringup/params/nav2_params.yaml` at N and H | Unmarked examples; Nav2 LICENSE explicitly defaults unmarked files to Apache-2.0, and bringup declares Apache-2.0. This confirms the identified examples' terms, not the old local files' derivation |

SLAM Toolbox reference S is Jazzy commit
`02afdde003313a10b8d21461a92d9e5f4f0bc5f2` (package metadata version 2.8.5).
S1 covers `README.md`, `src/slam_toolbox_common.cpp`, `src/slam_mapper.cpp`,
`src/laser_utils.cpp` and their inspected headers; the async implementation and
Ceres solver interface were also inspected. The package declares LGPL and the
root LICENSE contains LGPL 2.1. Several inspected implementation/header files,
however, invoke a non-specific CCPL without a variant/version; the solver has a
copyright header without a specific grant. The sample YAML and README have no
file-specific grant. The root licence alone is therefore **not** treated as
clearance to copy every file. No such source, prose or sample block was reused.
The unclear headers do not supply a licence we can safely guess.

The reconstructed YAML specifies interface facts and project tuning; it contains
no AMCL or SLAM Toolbox implementation or copyrightable example text. No LGPL
source-copy obligation is identified for these replacement configurations, and
they are not labelled LGPL merely for configuring an LGPL dependency. This is a
limited source-publication conclusion, not a legal warranty of all historical
material or a binary-distribution clearance. `slam_runner` still links the installed
SLAM Toolbox library. Distribution of compiled binaries/containers requires its
own review of dependency notices, LGPL compliance and the SLAM header discrepancy.
Nav2 is mixed-license. NOTICE now distinguishes these facts.

## Configuration identity and historical evidence

Typed parsed structures were compared against `8430110`, including all scalar
types and list order. Both profiles were composed with simulation time on/off,
using both normal geometry and a wider-wheel-separation override: all eight
combinations match. Semantic SHA-256 pins are covered by portable/passive tests;
ROS's parameter-file reader is checked separately without starting a node.

The frozen `benchmarks/warehouse_v1/matrix.json` continues to bind the **old raw
YAML bytes**. It and every campaign/result/recording/hash remain unchanged. Its
strict validator correctly rejects the new YAML byte identities; no compatibility
exception was added. Reproduce that historical source using its original Git
revision and preserved evidence. A future new benchmark specification needs a
separately reviewed identity; this change grants no run authority.

Ordinary tests create temporary current-source matrix fixtures, updating only the
four affected raw YAML pins in those temporary copies. Since 2026-10-14 the same
applies to `robot_bringup/launch/robot.launch.py` and
`robot_simulation/launch/gazebo.launch.py`, which gained the owner-approved
`warehouse_v2` world choice; warehouse_v1 launch behaviour is unchanged and the
frozen matrix still rejects their new bytes. Effective-parameter pins,
all other source pins and the production validator remain strict. A separate test
checks rejection of the frozen matrix against reconstructed bytes. The normal
campaign service does not call that historical matrix validator and continues to
use the unchanged composer and recording profiles.

The accepted website release metadata records the owner-approved CC BY 4.0
decision for the eight pinned derived bundles. This source integration does not
select a new licence, change bundle bytes, or authorise dataset publication.
Q1 remains **INCONCLUSIVE / RECOVERY UNKNOWN**.
