# Milestone 7B.3 — Mapping Progress & 3D Mapping Feedback

## Goal
Make Mapping mode observable enough that the operator can decide when to keep exploring, save a map, or stop the mapping stack.

## Added
- mapping travel trail in 2D and 3D;
- travelled-distance and trail-sample metrics;
- known/unknown occupancy-grid progress and known mapped area;
- grid extent and LiDAR status;
- operator guidance for first-map, missing-scan, incomplete-coverage, and high-coverage states;
- closer 3D camera during mapping before map/LiDAR context exists;
- explicit 3D waiting overlay instead of an apparently blank scene.

## Important limitation
The known/unknown percentage is calculated only inside the current occupancy-grid bounds. It is a progress indicator, not proof that the environment has been completely explored.
