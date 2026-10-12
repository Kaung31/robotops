from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass

from .models import ConnectionState, RobotSnapshot, RuntimeMode


@dataclass(frozen=True)
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[RobotSnapshot]


class TelemetryStore:
    """Thread-safe latest-state store; ROS callbacks may publish from another thread."""

    def __init__(self, stale_after_seconds: float = 2.0):
        self._lock = threading.Lock()
        self._snapshot = RobotSnapshot()
        self._subscribers: set[_Subscriber] = set()
        self._stale_ns = int(stale_after_seconds * 1e9)
        self._last_received_ns: int | None = None

    def latest(self) -> RobotSnapshot:
        with self._lock:
            snap = self._snapshot.model_copy(deep=True)
        with self._lock:
            last_received_ns = self._last_received_ns
        if last_received_ns is None:
            snap.connection = ConnectionState.DISCONNECTED
        elif time.monotonic_ns() - last_received_ns > self._stale_ns:
            snap.connection = ConnectionState.STALE
        else:
            snap.connection = ConnectionState.CONNECTED
        return snap

    def publish(self, **changes) -> RobotSnapshot:
        with self._lock:
            payload = self._snapshot.model_dump()
            payload.update(changes)
            self._last_received_ns = time.monotonic_ns()
            payload["received_monotonic_ns"] = str(self._last_received_ns)
            self._snapshot = RobotSnapshot.model_validate(payload)
            snap = self._snapshot.model_copy(deep=True)
            subscribers = tuple(self._subscribers)
        snap.connection = ConnectionState.CONNECTED
        for sub in subscribers:
            sub.loop.call_soon_threadsafe(self._offer, sub.queue, snap.model_copy(deep=True))
        return snap

    def set_mode(self, mode: RuntimeMode) -> None:
        with self._lock:
            self._snapshot.runtime_mode = mode

    def mark_disconnected(self, mode: RuntimeMode | None = None) -> None:
        """Mark the live transport unavailable without refreshing telemetry freshness."""
        with self._lock:
            if mode is not None:
                self._snapshot.runtime_mode = mode
            self._last_received_ns = None
            self._snapshot.received_monotonic_ns = None
            snap = self._snapshot.model_copy(deep=True)
            subscribers = tuple(self._subscribers)
        snap.connection = ConnectionState.DISCONNECTED
        for sub in subscribers:
            sub.loop.call_soon_threadsafe(self._offer, sub.queue, snap.model_copy(deep=True))

    @staticmethod
    def _offer(queue: asyncio.Queue[RobotSnapshot], snapshot: RobotSnapshot) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(snapshot)

    async def subscribe(self):
        sub = _Subscriber(asyncio.get_running_loop(), asyncio.Queue(maxsize=1))
        with self._lock:
            self._subscribers.add(sub)
        try:
            current = self.latest()
            yield current
            last_connection = current.connection
            timeout_seconds = max(0.05, self._stale_ns / 1e9)
            while True:
                try:
                    snapshot = await asyncio.wait_for(sub.queue.get(), timeout=timeout_seconds)
                    last_connection = snapshot.connection
                    yield snapshot
                except TimeoutError:
                    snapshot = self.latest()
                    if snapshot.connection != last_connection:
                        last_connection = snapshot.connection
                        yield snapshot
        finally:
            with self._lock:
                self._subscribers.discard(sub)
