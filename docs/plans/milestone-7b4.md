# Milestone 7B.4 — Map Library & Teleop Profiles

## Goal

Make the Mapping → Save → Navigation workflow reliable and obvious in the web product without changing the working ROS navigation/SLAM interfaces.

## Scope

- persist saved-map metadata (source world, creation time, resolution, dimensions);
- expose a lightweight occupancy-map preview;
- sort maps newest-first and mark the newest map per environment;
- prefer the newest compatible map when switching from Mapping to Navigation;
- hide legacy maps by default and make them an explicit opt-in;
- warn before overwriting an existing map;
- suggest versioned map names per environment;
- add Precision / Normal / Fast teleop profiles while keeping acceleration limiting in the robot/controller layer.

## Safety / architecture

- browser still cannot send arbitrary ROS commands;
- teleop values remain inside the existing backend limits;
- acceleration is not user-controlled from the browser;
- known map/world mismatches remain rejected by the backend;
- legacy maps remain usable only when explicitly selected.

## Acceptance

- a newly saved mapping result appears in the map library without restarting RobotOps;
- switching to Navigation selects the newest map for the selected environment;
- selected map shows source environment, creation time, map size/resolution and preview;
- overwriting an existing map requires confirmation;
- teleop speed profile selection changes bounded linear/turn speed only;
- backend tests covering metadata/latest-map/preview pass.
