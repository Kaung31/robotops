# Milestone 7B.5.2 — Nav2-native bringup

RobotOps supervises navigation readiness while Nav2 lifecycle managers own lifecycle transitions.

Simulation startup sequence:

1. Wait for fresh odometry, LiDAR, and `odom -> base_link`.
2. Start `map_lifecycle_manager` through `nav2_msgs/srv/ManageLifecycleNodes`.
3. AMCL initializes from the selected world's configured simulation spawn pose.
4. Wait for `/map`, `/amcl_pose`, and `map -> base_link`.
5. Start `navigation_lifecycle_manager` through `ManageLifecycleNodes`.
6. Verify all top-level Nav2 nodes are active before missions are accepted.

The web gateway does not directly configure or activate individual Nav2 lifecycle nodes. Manual Set Pose remains an operator recovery tool.
