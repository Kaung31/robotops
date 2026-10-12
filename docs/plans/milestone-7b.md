# Milestone 7B — RobotOps Orchestrator and Production Control Center

## Goal

Turn the Milestone 7 telemetry/dashboard foundation into the normal local operations entry point for simulation. The browser selects approved RobotOps configurations; the backend owns ROS launch processes and keeps ROS-specific commands out of the browser.

## Scope implemented

- approved simulation world discovery (`control_pad`, `mapping_lab`);
- saved occupancy-map discovery from `artifacts/maps/*.yaml` with referenced image validation;
- selectable Nav2 profiles (`navfn_rpp`, `smac_dwb`);
- backend stack lifecycle API: start/status/stop;
- Mapping workflow: robot + sensors + SLAM;
- Navigation workflow: robot + saved-map AMCL/Nav2 + mission server;
- bounded process-group shutdown and per-process logs under `artifacts/logs/orchestrator/`;
- map saving through the approved `nav2_map_server map_saver_cli` command;
- AMCL initial-pose publishing through the ROS gateway;
- bounded teleoperation through `cmd_vel/teleop` (not direct drive-controller access);
- production-style React control-center UI for workflow/world/map/profile selection;
- press-and-hold teleoperation with stop-on-release;
- existing map/pose/LiDAR/mission visualization retained.

## Security and safety boundaries

- no arbitrary shell command or launch arguments are accepted from the browser;
- subprocesses use argument arrays with `shell=False`;
- only fixed worlds and navigation profiles are selectable;
- navigation can load only maps discovered below the repository `artifacts/maps` directory;
- teleop values are validated server-side to ±0.20 m/s linear and ±0.50 rad/s angular;
- the existing twist mux, command guard and drive watchdog remain authoritative;
- replay mutations remain rejected;
- real-hardware orchestration is not implemented;
- this is still a localhost/trusted-network application; authentication is required before remote physical operation.

## API additions

- `GET /api/v1/control/options`
- `GET /api/v1/control/stack`
- `POST /api/v1/control/stack`
- `DELETE /api/v1/control/stack`
- `POST /api/v1/maps/save`
- `POST /api/v1/localization/initial-pose`
- `POST /api/v1/teleop`

Existing mission and telemetry APIs remain unchanged.

## Start behavior

### Mapping

The orchestrator starts:

1. `robot_bringup robot.launch.py mode:=sim ...`
2. `robot_navigation map.launch.py workflow:=mapping ...`

The UI may teleoperate the robot and save the resulting occupancy map.

### Navigation

The orchestrator starts:

1. `robot_bringup robot.launch.py mode:=sim ...`
2. `robot_navigation navigation.launch.py map_file:=... profile:=...`
3. `mission_manager mission.launch.py mode:=sim`

The user then sets the AMCL initial pose from the control center and may send missions using the existing mission action gateway.

## Verification completed in the development sandbox

- Python modules compile.
- 22 focused backend tests pass.
- Tests cover stack API behavior, option discovery, replay restrictions, bounded teleop validation and map-path whitelisting.
- Production frontend build could not be re-run in the sandbox because package installation had no network access. The user previously verified the pre-7B Vite production build on Node 22; the updated 7B frontend must be typechecked/built in the Jazzy Distrobox before merge is considered complete.

## Required local verification

Inside the existing Ubuntu 24.04/Jazzy Distrobox:

```bash
cd ~/robotops_verified_source_v2/robotops
source /opt/ros/jazzy/setup.bash
source ros2_ws/install/setup.bash

.venv/bin/python -m pytest -q backend/tests
cd web
npm install
npm run typecheck
npm run build
```

Then start only the backend manually. The backend should start/stop the simulation/navigation stack from the web UI; separate manual Gazebo/Nav2 launch terminals should no longer be required for normal Milestone 7B use.

## Not included yet

- benchmark/experiment control UI (Milestone 8);
- replay orchestration/player UI;
- hard/extreme benchmark worlds;
- authentication/authorization;
- real robot lifecycle/power orchestration;
- automatic AMCL pose inference from simulator ground truth.
