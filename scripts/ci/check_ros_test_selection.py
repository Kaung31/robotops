"""Check the passive CTest allowlist exists exactly once before running it."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def check_selection(build: Path, pattern: str) -> int:
    if not pattern.startswith("^(") or not pattern.endswith(")$"):
        raise ValueError("Expected an anchored explicit CTest allowlist")
    expected = set(pattern[2:-2].split("|"))
    found: list[str] = []
    for package in sorted(build.iterdir()):
        if not (package / "CTestTestfile.cmake").is_file():
            continue
        result = subprocess.run(
            ["ctest", "--test-dir", str(package), "--show-only=json-v1"],
            check=True,
            capture_output=True,
            text=True,
        )
        found.extend(
            test["name"]
            for test in json.loads(result.stdout)["tests"]
            if re.fullmatch(pattern, test["name"])
        )
    if set(found) != expected or len(found) != len(expected):
        raise RuntimeError(f"CTest selection mismatch: expected={sorted(expected)}, found={found}")
    return len(found)


if __name__ == "__main__":
    print(f"Selected {check_selection(Path(sys.argv[1]), sys.argv[2])} passive CTest tests")
