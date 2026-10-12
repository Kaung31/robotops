"""Header/receipt freshness, independent of ROS and robot runtime backend."""

from dataclasses import dataclass
from math import isfinite

OK, WARN, ERROR, STALE = range(4)


@dataclass(frozen=True)
class Policy:
    warn_seconds: float = 0.5
    error_seconds: float = 1.0
    future_seconds: float = 0.1
    clock_stall_seconds: float = 2.0

    def __post_init__(self):
        for value in vars(self).values():
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError("Freshness thresholds must be finite positive numbers")
        if self.warn_seconds >= self.error_seconds:
            raise ValueError("Warning age must be less than error age")


@dataclass(frozen=True)
class Status:
    level: int
    reason: str
    values: dict[str, str]


@dataclass
class Sample:
    stamp_ns: int
    receipt_ns: int
    advancing: int
    error: str = ""


class Monitor:
    def __init__(self, streams: tuple[str, ...], policy: Policy | None = None):
        if not streams or len(set(streams)) != len(streams):
            raise ValueError("Streams must be nonempty and unique")
        self.streams = streams
        self.policy = policy or Policy()
        self.samples: dict[str, Sample] = {}
        self.last_ros_ns: int | None = None
        self.last_advance: float | None = None
        self.blocked = True
        self.epoch = 0

    def reset_clock(self) -> None:
        """Invalidate evidence even when a backward jump occurs between evaluations."""
        self.samples.clear()
        self.last_ros_ns = None
        self.last_advance = None
        self.blocked = True
        self.epoch += 1

    def _clock(self, now_ns: int, steady: float) -> str:
        if now_ns <= 0:
            if self.last_ros_ns is not None:
                self.samples.clear()
                self.epoch += 1
            self.last_ros_ns = None
            self.last_advance = None
            self.blocked = True
            return "clock_uninitialized"
        backward = self.last_ros_ns is not None and now_ns < self.last_ros_ns
        advancing = self.last_ros_ns is None or now_ns > self.last_ros_ns
        if backward or (advancing and self.blocked):
            self.samples.clear()
            self.epoch += 1
        if advancing or backward:
            self.last_advance = steady
        self.last_ros_ns = now_ns
        self.blocked = steady - self.last_advance > self.policy.clock_stall_seconds
        return "clock_not_advancing" if self.blocked else "clock_advancing"

    def observe(self, stream: str, stamp_ns: int, now_ns: int, steady: float) -> None:
        if stream not in self.streams:
            raise ValueError(f"Unknown stream: {stream}")
        self._clock(now_ns, steady)
        if self.blocked:
            return
        previous = self.samples.get(stream)
        error = ""
        if type(stamp_ns) is not int or stamp_ns <= 0:
            error = "invalid_stamp"
        elif stamp_ns - now_ns > self.policy.future_seconds * 1e9:
            error = "future_stamp"
        elif previous and stamp_ns < previous.stamp_ns:
            error = "stamp_regressed"
        count = 0
        if not error:
            expired = previous is not None and (
                now_ns - previous.receipt_ns > self.policy.error_seconds * 1e9
                or now_ns - previous.stamp_ns > self.policy.error_seconds * 1e9
            )
            if previous is None or previous.error or expired:
                count = 1
            elif stamp_ns > previous.stamp_ns:
                count = min(previous.advancing + 1, 2)
            else:
                count = previous.advancing
        # Invalid stamps never enter arithmetic or qualify as a healthy baseline.
        safe_stamp = stamp_ns if type(stamp_ns) is int and stamp_ns > 0 else 0
        self.samples[stream] = Sample(safe_stamp, now_ns, count, error)

    def evaluate(self, now_ns: int, steady: float) -> dict[str, Status]:
        clock_reason = self._clock(now_ns, steady)
        clock_level = STALE if self.blocked else OK
        common = {"schema_version": "1", "clock_epoch": str(self.epoch)}
        result = {"clock": Status(clock_level, clock_reason, dict(common))}
        for stream in self.streams:
            sample = self.samples.get(stream)
            values = dict(common)
            if self.blocked:
                level, reason = STALE, clock_reason
            elif sample is None:
                level, reason = STALE, "not_observed"
            else:
                receipt_age = (now_ns - sample.receipt_ns) / 1e9
                stamp_age = (now_ns - sample.stamp_ns) / 1e9
                values.update(
                    receipt_age_seconds=str(receipt_age),
                    stamp_age_seconds=str(stamp_age),
                    stamp_ns=str(sample.stamp_ns),
                    advancing_samples=str(sample.advancing),
                    warn_seconds=str(self.policy.warn_seconds),
                    error_seconds=str(self.policy.error_seconds),
                )
                if receipt_age > self.policy.error_seconds:
                    level, reason = STALE, "receipt_timeout"
                elif sample.error:
                    level, reason = ERROR, sample.error
                elif stamp_age > self.policy.error_seconds:
                    level, reason = ERROR, "stamp_timeout"
                elif max(receipt_age, stamp_age) > self.policy.warn_seconds:
                    level, reason = WARN, "age_warning"
                elif sample.advancing < 2:
                    level, reason = STALE, "awaiting_advancing_samples"
                else:
                    level, reason = OK, "fresh"
            result[stream] = Status(level, reason, values)
        return result
