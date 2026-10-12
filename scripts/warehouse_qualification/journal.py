"""Bounded asynchronous evidence journal. No ROS, launch or command interfaces."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path


class EvidenceFailure(RuntimeError):
    """Incomplete observation cannot qualify a run."""


class LifecycleJournal:
    """Independent bounded asynchronous lifecycle receipts, ordered locally.

    No disk I/O occurs in submit, so slow storage cannot delay a stop signal.
    This stream has its own writer and budget; observation failure is unrelated.
    Both streams must close durably to qualify. Shared-device failure may still
    defeat both; bounded close reports failure rather than inventing durability.
    """

    def __init__(self, path: Path):
        self.condition = threading.Condition()
        self.queue: deque[str] = deque()
        self.accepted = self.written = self.bytes = self.dropped = 0
        self.error: str | None = None
        self.closed = False
        self.stream = path.open("x", encoding="utf-8")
        fsync_directory(path.parent)
        self.worker = threading.Thread(target=self._write, daemon=True, name="w3-lifecycle-writer")
        self.worker.start()

    def submit(self, kind: str, **fields) -> bool:
        with self.condition:
            try:
                if self.error or self.closed:
                    raise EvidenceFailure("Critical lifecycle closed or failed")
                row = (
                    json.dumps(
                        dict(
                            fields,
                            kind=kind,
                            sequence=self.accepted + 1,
                            monotonic_ns=time.monotonic_ns(),
                        ),
                        allow_nan=False,
                    )
                    + "\n"
                )
                size = len(row.encode())
                if size > 8192 or self.accepted >= 512 or self.bytes + size > 2 * 1024 * 1024:
                    raise EvidenceFailure("Critical lifecycle storage budget exhausted")
                self.accepted += 1
                self.bytes += size
                self.queue.append(row)
                self.condition.notify()
                return True
            except Exception as exc:
                self.dropped += 1
                self.error = self.error or f"{type(exc).__name__}: {exc}"
                return False

    def _write(self):
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.queue or self.closed)
                    if not self.queue:
                        return
                    row = self.queue.popleft()
                self.stream.write(row)
                self.stream.flush()
                os.fsync(self.stream.fileno())
                with self.condition:
                    self.written += 1
        except BaseException as exc:
            with self.condition:
                self.error = self.error or f"Critical lifecycle write failed: {exc}"
        finally:
            try:
                self.stream.close()
            except Exception as exc:
                with self.condition:
                    self.error = self.error or f"Critical lifecycle close failed: {exc}"

    def status(self) -> dict:
        with self.condition:
            return {
                "accepted": self.accepted,
                "written": self.written,
                "bytes": self.bytes,
                "dropped": self.dropped,
                "error": self.error,
                "accepted_not_durable": self.accepted - self.written,
                "closed": self.closed,
                "writer_alive": self.worker.is_alive(),
                "complete": self.closed
                and not self.worker.is_alive()
                and self.error is None
                and self.accepted == self.written
                and self.dropped == 0,
            }

    def close(self, timeout: float = 5.0) -> dict:
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.worker.join(timeout)
        if self.worker.is_alive():
            with self.condition:
                self.error = self.error or "Critical lifecycle close deadline exceeded"
        return self.status()


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def critical_event(journal, kind: str, **fields) -> bool:
    """Production journals always own an independent lifecycle stream.

    The fallback supports existing minimal test doubles, never BufferedJournal.
    """
    if isinstance(journal, BufferedJournal):
        return journal.lifecycle.submit(kind, **fields)
    return journal.submit(kind, **fields)


def critical_status(journal) -> dict:
    if isinstance(journal, BufferedJournal):
        return journal.lifecycle.status()
    return {"complete": True, "test_double": True}


class BufferedJournal:
    """Callbacks enqueue bounded JSON; one writer flushes/fsyncs bounded batches.

    Overflow/write failure is sticky and fails supervision. Accepted-but-unwritten
    observations and rejected observations are reported separately. A stuck writer
    cannot be declared clean, even if a bounded close returns. No queue waits or
    filesystem calls occur in submit(). JSON encoding has a per-record size limit.
    """

    def __init__(
        self,
        path: Path,
        *,
        capacity: int = 4096,
        byte_capacity: int = 8 * 1024 * 1024,
        max_record_bytes: int = 256 * 1024,
        persist: Callable[[str], None] | None = None,
        persist_batch: Callable[[list[str]], None] | None = None,
        batch_records: int = 64,
        batch_bytes: int = 256 * 1024,
        batch_wait_s: float = 0.02,
        storage_bytes: int = 1024 * 1024 * 1024,
        storage_records: int = 2_000_000,
    ):
        if any(
            type(v) is not int or v <= 0
            for v in (
                capacity,
                byte_capacity,
                max_record_bytes,
                batch_records,
                batch_bytes,
                storage_bytes,
                storage_records,
            )
        ):
            raise ValueError("Journal limits must be positive integers")
        if persist is not None and persist_batch is not None:
            raise ValueError("Choose one persistence test hook")
        if not 0 <= batch_wait_s <= 0.1:
            raise ValueError("Batch wait must be between zero and 0.1 seconds")
        self.batch_records, self.batch_bytes, self.batch_wait_s = (
            batch_records,
            batch_bytes,
            batch_wait_s,
        )
        self.storage_bytes, self.storage_records = storage_bytes, storage_records
        self.admitted_bytes = self.generated = self.batches = 0
        self.generated_by_kind: dict[str, int] = {}
        self.rejected_by_reason: dict[str, int] = {}
        self.capacity = capacity
        self.byte_capacity = byte_capacity
        self.max_record_bytes = max_record_bytes
        self.condition = threading.Condition()
        self.queue: deque[tuple[str, int, int]] = deque()
        self.accepted = self.written = self.dropped = self.pending_bytes = 0
        self.peak_pending = self.peak_bytes = 0
        self.max_queue_delay_ns = self.max_persist_duration_ns = 0
        self.oldest_pending_ns: int | None = None
        self.error: str | None = None
        self.closed = False
        self.stream = (
            path.open("x", encoding="utf-8") if persist is None and persist_batch is None else None
        )
        self.persist = persist
        self.persist_batch = persist_batch or self._persist_batch
        if self.stream is not None:
            fsync_directory(path.parent)
        self.lifecycle = LifecycleJournal(path.with_name(path.name + ".lifecycle.jsonl"))
        # On a stuck filesystem close reports failure; it never waits indefinitely
        # or claims the daemon has stopped. Caller must treat writer_alive as unsafe.
        self.worker = threading.Thread(target=self._write, name="w3-evidence-writer", daemon=True)
        self.worker.start()

    def _persist_batch(self, rows: list[str]) -> None:
        if self.persist is not None:
            # Compatibility hook: each callback must acknowledge durability.
            for row in rows:
                self.persist(row)
        else:
            assert self.stream is not None
            self.stream.writelines(rows)
            self.stream.flush()
            os.fsync(self.stream.fileno())

    def reject(self, reason: str, *, counted: bool = False) -> None:
        with self.condition:
            if not counted:
                self.generated += 1
            self.dropped += 1
            self.error = self.error or reason
            key = (
                reason
                if reason in self.rejected_by_reason or len(self.rejected_by_reason) < 64
                else "other"
            )
            self.rejected_by_reason[key] = self.rejected_by_reason.get(key, 0) + 1

    def submit(self, kind: str, **fields) -> bool:
        """Nonblocking enqueue; failures are counted and observed by check()."""
        with self.condition:
            self.generated += 1
            if (
                type(kind) is not str
                or len(kind) > 64
                or (kind not in self.generated_by_kind and len(self.generated_by_kind) >= 64)
            ):
                self.reject("Invalid or excessive event kinds", counted=True)
                return False
            self.generated_by_kind[kind] = self.generated_by_kind.get(kind, 0) + 1
        if any(
            key in fields
            for key in ("sequence", "callback_monotonic_ns", "writer_started_monotonic_ns")
        ):
            self.reject("Reserved journal field supplied", counted=True)
            return False
        # Encode a detached snapshot before enqueuing; later input mutation cannot
        # change evidence. Callers cap CDR size before base64/JSON conversion.
        try:
            encoded = json.dumps(
                {"kind": kind, "callback_monotonic_ns": time.monotonic_ns(), **fields},
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            self.reject(f"Evidence encoding failed: {exc}", counted=True)
            return False
        size = len(encoded.encode("utf-8")) + 128
        with self.condition:
            pending = self.accepted - self.written
            if self.closed or self.error:
                self.dropped += 1
                reason = "after_close" if self.closed else "after_failure"
                self.rejected_by_reason[reason] = self.rejected_by_reason.get(reason, 0) + 1
                self.error = self.error or "Observation submitted after journal close"
                return False
            reason = None
            if size > self.max_record_bytes:
                reason = "oversized_record"
            elif pending >= self.capacity:
                reason = "record_capacity_overflow"
            elif self.pending_bytes + size > self.byte_capacity:
                reason = "byte_capacity_overflow"
            elif (
                self.accepted >= self.storage_records
                or self.admitted_bytes + size > self.storage_bytes
            ):
                reason = "storage_budget_exhausted"
            if reason:
                self.reject(reason, counted=True)
                return False
            self.admitted_bytes += size
            self.accepted += 1
            # Sequence assignment and append share the lock, including concurrent producers.
            row = f'{{"sequence":{self.accepted},' + encoded[1:] + "\n"
            self.pending_bytes += size
            self.peak_pending = max(self.peak_pending, pending + 1)
            self.peak_bytes = max(self.peak_bytes, self.pending_bytes)
            enqueued = time.monotonic_ns()
            if self.oldest_pending_ns is None:
                self.oldest_pending_ns = enqueued
            self.queue.append((row, size, enqueued))
            self.condition.notify()
            return True

    def _write(self) -> None:
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self.queue or self.closed)
                    if not self.queue:
                        return
                    deadline = time.monotonic() + self.batch_wait_s
                    while not self.closed and len(self.queue) < self.batch_records:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        self.condition.wait(remaining)
                    batch = []
                    total = 0
                    while self.queue and len(batch) < self.batch_records:
                        if batch and total + self.queue[0][1] > self.batch_bytes:
                            break
                        item = self.queue.popleft()
                        batch.append(item)
                        total += item[1]
                started = time.monotonic_ns()
                rows = [
                    f'{{"writer_started_monotonic_ns":{started},' + item[0][1:] for item in batch
                ]
                self.persist_batch(rows)
                finished = time.monotonic_ns()
                with self.condition:
                    # No row is acknowledged until the entire batch's fsync succeeds.
                    self.written += len(batch)
                    self.batches += 1
                    self.pending_bytes -= total
                    self.max_queue_delay_ns = max(self.max_queue_delay_ns, started - batch[0][2])
                    self.max_persist_duration_ns = max(
                        self.max_persist_duration_ns, finished - started
                    )
                    self.oldest_pending_ns = self.queue[0][2] if self.queue else None
                    self.condition.notify_all()
        except BaseException as exc:
            with self.condition:
                self.error = self.error or f"Evidence write failed: {type(exc).__name__}: {exc}"
        finally:
            if self.stream is not None:
                try:
                    self.stream.close()
                except BaseException as exc:
                    with self.condition:
                        self.error = self.error or f"Evidence close failed: {exc}"

    def check(self, now_ns: int | None = None) -> None:
        critical = self.lifecycle.status()
        if critical["error"]:
            raise EvidenceFailure(critical["error"])
        with self.condition:
            now = time.monotonic_ns() if now_ns is None else now_ns
            if self.oldest_pending_ns is not None and now - self.oldest_pending_ns > 5_000_000_000:
                self.error = self.error or "Evidence writer made no timely durable progress"
            if self.error:
                raise EvidenceFailure(self.error)
            if not self.worker.is_alive() and not self.closed:
                raise EvidenceFailure("Evidence writer stopped unexpectedly")

    def status(self) -> dict:
        critical_error = self.lifecycle.status()["error"]
        with self.condition:
            alive = self.worker.is_alive()
            return {
                "generated": self.generated,
                "generated_by_kind": dict(self.generated_by_kind),
                "rejected_by_reason": dict(self.rejected_by_reason),
                "durable_batches": self.batches,
                "admitted_storage_budget_bytes": self.admitted_bytes,
                "storage_byte_limit": self.storage_bytes,
                "storage_record_limit": self.storage_records,
                "batch_record_limit": self.batch_records,
                "batch_byte_limit": self.batch_bytes,
                "batch_wait_s": self.batch_wait_s,
                "accepted": self.accepted,
                "written": self.written,
                "dropped": self.dropped,
                "accepted_not_durable": self.accepted - self.written,
                "pending_bytes": self.pending_bytes,
                "peak_pending": self.peak_pending,
                "peak_bytes": self.peak_bytes,
                "oldest_pending_ns": self.oldest_pending_ns,
                "max_queue_delay_ns": self.max_queue_delay_ns,
                "max_persist_duration_ns": self.max_persist_duration_ns,
                "error": self.error,
                "critical_error": critical_error,
                "closed": self.closed,
                "writer_alive": alive,
                "complete": self.closed
                and not alive
                and not self.error
                and not critical_error
                and self.accepted == self.written
                and self.dropped == 0,
            }

    def close(self, timeout: float = 5.0, *, close_lifecycle: bool = True) -> dict:
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError("Bounded journal close needs 0 < timeout <= 30 seconds")
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.worker.join(timeout)
        if self.worker.is_alive():
            with self.condition:
                self.error = self.error or "Evidence writer did not stop before close deadline"
        if close_lifecycle:
            self.lifecycle.close(timeout)
        return self.status()


def shutdown_summary(
    *,
    exception: str | None,
    cleanup_completed: bool,
    exits: list[int | None],
    failed_children: list[str],
    robot_stop_verified: bool,
    journal: dict,
) -> dict:
    """Qualification and cleanup are independent, including assertion paths."""
    clean = bool(
        cleanup_completed and exits and all(v == 0 for v in exits) and not failed_children
    )
    return {
        "exception": exception,
        "cleanup_completed": cleanup_completed,
        "owned_exit_codes": exits,
        "failed_children": failed_children,
        "robot_stop_verified": robot_stop_verified,
        "clean_process_shutdown_verified": clean,
        "evidence": journal,
        "observer_and_cleanup_complete": exception is None
        and clean
        and robot_stop_verified
        and journal["complete"],
    }


def save_summary(path: Path, summary: dict) -> None:
    """Durable, exclusive final receipt outside callbacks; failure must propagate."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(path.parent)
