#!/usr/bin/env bash
# Use an ordinary Python 3.12 venv, without system-site-packages or sourced ROS.
set -euo pipefail
mkdir -p .ci-results
python - <<'PYTHON'
import importlib.util

if importlib.util.find_spec("rclpy") is not None:
    raise SystemExit("Portable tests require a venv without ROS/system-site-packages")
PYTHON
python -m pip check
python -m pytest -q --junitxml=.ci-results/portable.xml
python -m pytest -q scripts/ci/test \
  --junitxml=.ci-results/utilities.xml
