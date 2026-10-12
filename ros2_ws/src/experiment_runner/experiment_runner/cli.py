"""Local CLI; offline comparison never initializes a ROS command client."""

import argparse
import json
from pathlib import Path

from experiment_runner.model import comparison, load, load_baseline, load_map_baseline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    execute = commands.add_parser("run")
    execute.add_argument("config", type=Path)
    execute.add_argument("--output", type=Path, default=Path("artifacts/experiments"))
    execute.add_argument("--baseline", type=Path)
    execute.add_argument("--map-baseline", type=Path)
    compare = commands.add_parser("compare")
    compare.add_argument("manifests", type=Path, nargs="+")
    args, ros_args = parser.parse_known_args()
    try:
        if args.command == "compare":
            if ros_args:
                parser.error("Unexpected comparison arguments")
            print(json.dumps(comparison(args.manifests), indent=2, allow_nan=False))
            return 0
        config = load(args.config)
        baseline = load_baseline(args.baseline, config) if args.baseline else None
        if args.map_baseline:
            map_baseline = load_map_baseline(args.map_baseline, config)
            if baseline and baseline["map_hashes"] != map_baseline["map_hashes"]:
                raise ValueError("Profile and campaign map baselines differ")
            baseline = baseline or map_baseline
        from experiment_runner.runner import run

        return run(config, args.output, ros_args, baseline=baseline)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"experiment: {error}\n")
