# Milestone 7B.2 — Visual Experience Upgrade

Incremental frontend-only enhancement. ROS, orchestration, mission, mapping, and navigation interfaces remain unchanged.

## Added

- 2D / 3D visualization switch.
- Three.js robot scene driven by current robot pose.
- Live LiDAR point cloud around the 3D robot.
- Occupancy map projected into the 3D scene when available.
- Interactive 3D orbit/zoom camera.
- Clear live / stale / offline visualization state.
- Improved 2D robot marker, goal marker, path presentation, and high-zoom grid.
- Improved empty-map state.

## Local verification

```bash
cd web
npm install
npm run typecheck
npm run build
```

The patch intentionally does not modify ROS packages or backend APIs.
