#!/usr/bin/env bash
# No ROS sourcing or process launch; run from the repository root.
set -euo pipefail
status=0
check() {
  if "$@"; then
    printf 'PASS: %s\n' "$*"
  else
    printf 'FAIL: %s\n' "$*" >&2
    status=1
  fi
}
check ruff format --check .
check ruff check .
check find ros2_ws/src -type f \( -name '*.cpp' -o -name '*.hpp' \) \
  -exec clang-format --dry-run --Werror {} +
check bash -o pipefail -c \
  "git ls-files -z --cached --others --exclude-standard -- '*.yaml' '*.yml' | xargs -0 --no-run-if-empty yamllint"
check find ros2_ws/src -name CMakeLists.txt -exec cmake-lint {} +
check find ros2_ws/src -name CMakeLists.txt -exec cmake-format --check {} +
check find ros2_ws/src -type f \( -name '*.xml' -o -name '*.xacro' -o -name '*.sdf' \) \
  -exec xmllint --noout {} +
exit "$status"
