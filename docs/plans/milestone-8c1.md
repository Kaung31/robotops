# Milestone 8C.1 — Campaign startup reliability fix

> Planning status, 2026-10-11: Historical browser campaign startup patch, retained as technical history. Later backend ownership/readiness work supersedes it for planning.

This corrective patch keeps manual navigation and ROS/Nav2 configuration untouched.

Changes:
- Automated campaigns now use the same rendered-sensor startup mode as the working manual Control Center (`headless_rendering=false`).
- Campaign restart waits for several consecutive `stopped` observations plus a short teardown quiet period before relaunching Gazebo/ROS.
- Readiness polling now also watches stack state and surfaces the orchestrator error immediately if startup fails.
- Infrastructure startup failures abort the remaining campaign instead of being counted repeatedly as navigation benchmark failures.
- Campaign trial table shows the recorded failure detail.

This patch is intentionally frontend-only and does not modify Nav2, AMCL, lifecycle, mapping, teleop, missions, or planner/controller parameters.
