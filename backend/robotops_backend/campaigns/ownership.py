"""Local runtime arbitration across API requests and backend processes."""

import fcntl
import os
from pathlib import Path

from .repository import CampaignConflict, CampaignRepository, CampaignStorageError


class RuntimeOwnership:
    def __init__(self, path: Path, repository: CampaignRepository):
        self.path = path
        self.repository = repository

    def acquire(self) -> int:
        fd = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError as exc:
            if fd is not None:
                os.close(fd)
            raise CampaignConflict("Robot runtime is owned by another operation") from exc
        except OSError as exc:
            if fd is not None:
                os.close(fd)
            raise CampaignStorageError("Runtime ownership lock unavailable") from exc

    @staticmethod
    def release(fd: int) -> None:
        # Do not explicitly LOCK_UN: a ROS runner inheriting this FD must retain
        # the lock if the backend dies before the runner reaches a terminal state.
        os.close(fd)

    def acquire_manual(self) -> int:
        fd = self.acquire()
        try:
            if self.repository.lease() is not None:
                raise CampaignConflict("Campaign owns runtime; cancel or reconcile it first")
            return fd
        except BaseException:
            self.release(fd)
            raise
