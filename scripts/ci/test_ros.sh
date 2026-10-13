#!/usr/bin/env bash
# Explicit non-runtime CTest allowlist. No launch tests, ROS nodes or bag recording.
set -eo pipefail
# shellcheck source=/dev/null
source /opt/ros/jazzy/setup.bash
# shellcheck source=/dev/null
source ros2_ws/install/setup.bash
set -u
pattern='^(description_model|command_validation|control_config|backend_models|launch_validation|map_configuration|map_launch_validation|navigation_configuration|navigation_launch_validation|mission_validation|recording_preparation|mission_launch_validation|recording_artifacts|recording_readiness|experiment_model|experiment_validation|experiment_contacts|experiment_ground_truth|diagnostics_freshness|diagnostics_parity)$'
cd ros2_ws
# Ensure a deleted/renamed test cannot silently leave the selected suite empty.
python3 ../scripts/ci/check_ros_test_selection.py build "$pattern"
colcon test --packages-select robot_description robot_control robot_bringup \
  robot_navigation mission_manager robot_recorder experiment_runner robot_diagnostics \
  --return-code-on-test-failure --event-handlers console_direct+ \
  --ctest-args -R "$pattern" --no-tests=error
colcon test-result --verbose
