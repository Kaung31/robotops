# Milestone 8B audit

Hardening-only follow-up to the additive operations patch.

- JSON benchmark exports now include run annotations (notes, tags, pins) and imports remain backward-compatible with the older array-only format.
- Best-profile cards are computed from the complete run history for the selected map and are not distorted by result, profile, or pinned-only table filters.
- No ROS, Nav2, mapping, teleoperation, mission submission, waypoint execution, or backend behavior is changed.
