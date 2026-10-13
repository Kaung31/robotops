#!/usr/bin/env bash
# Build this worktree only; never reuse an active robotics overlay.
set -eo pipefail
# shellcheck source=/dev/null
source /opt/ros/jazzy/setup.bash
set -u
cd ros2_ws
colcon build --executor sequential --event-handlers console_direct+ \
  --cmake-args -DBUILD_TESTING=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo
