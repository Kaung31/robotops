"""Identify the exact source a stack was launched from, including uncommitted changes."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

_UNTRACKED_FILE_LIMIT = 16 * 1024 * 1024


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True, timeout=20
    ).stdout


def software_identity(root: Path) -> dict:
    """Git revision, branch and dirty state; hashes cover the diff and untracked files."""
    try:
        revision = _git(root, "rev-parse", "HEAD").decode().strip()
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").decode().strip()
        status = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        diff = _git(root, "diff", "HEAD", "--binary")
        untracked = [
            p
            for p in _git(root, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0")
            if p
        ]
    except (OSError, subprocess.SubprocessError) as error:
        return {"available": False, "reason": f"git unavailable: {error}"[:300]}
    files = hashlib.sha256()
    skipped = []
    for name in sorted(untracked):
        path = root / name.decode(errors="surrogateescape")
        files.update(name + b"\0")
        if path.is_file() and path.stat().st_size <= _UNTRACKED_FILE_LIMIT:
            files.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            skipped.append(name.decode(errors="replace"))
    changes = hashlib.sha256(status + b"\0" + diff + b"\0" + files.digest()).hexdigest()
    dirty = bool(status)
    return {
        "available": True,
        "revision": revision,
        "branch": branch,
        "dirty": dirty,
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "diff_sha256": hashlib.sha256(diff).hexdigest(),
        "untracked_files": len(untracked),
        "untracked_sha256": files.hexdigest(),
        "untracked_not_hashed": skipped,
        "describe": f"git:{revision}+dirty:{changes[:12]}" if dirty else f"git:{revision}",
    }
