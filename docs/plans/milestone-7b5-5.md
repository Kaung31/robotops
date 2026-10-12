# Milestone 7B.5.5 — ordered Nav2 bringup audit

This corrective patch follows Nav2's current bringup pattern more closely by using
one lifecycle manager for saved-map localization and navigation in Navigation
mode. The ordered managed-node list is:

1. `map_server`
2. `amcl`
3. `controller_server`
4. `planner_server`
5. `behavior_server`
6. `bt_navigator`

The single manager autostarts the nodes sequentially. This removes the remaining
race between separate localization and navigation lifecycle managers. RobotOps
does not drive lifecycle transitions itself; it observes functional readiness
from odometry, LiDAR, TF, map data, and the `navigate_to_pose` action server.

Mapping mode continues to use `map.launch.py` and its mapping-specific lifecycle
manager. Manual initial-pose publication remains an operator recovery tool; the
normal simulation navigation path uses AMCL's configured initial pose.
