"""Pure W3 observation policy. No ROS initialisation or simulator commands."""

from __future__ import annotations

from dataclasses import dataclass

from .journal import BufferedJournal, EvidenceFailure

TF_MAX_AGE_NS = 1_000_000_000  # Existing qualification limit; never relaxed.
CALLBACK_DELAY_NS = 250_000_000  # Diagnostic classification, not a readiness exemption.
REQUIRED_EDGES = (("map", "odom"), ("odom", "base_link"))


@dataclass(frozen=True)
class Edge:
    stamp_ns: int
    receipt_ros_ns: int
    receipt_monotonic_ns: int
    callback_delay_ns: int | None


class QualificationObserver:
    def __init__(
        self,
        journal: BufferedJournal,
        *,
        expected_bodies: list[str] | None = None,
        expected_support_pairs: list[str] | None = None,
    ):
        self.journal = journal
        self.expected_bodies = expected_bodies
        self.expected_support_pairs = expected_support_pairs
        self.edges: dict[tuple[str, str], Edge] = {}
        self.faults: list[str] = []
        self.last_clock: int | None = None
        self.clock_receipt_ns: int | None = None
        self.previous_contact: dict | None = None
        self.assessments = self.assessments_emitted = 0
        self.last_assessment_record_ns: int | None = None
        self.last_assessment_signature = None
        self.contact_ready = False
        self.contact_count = 0
        self.last_contact_receipt_ns: int | None = None

    def fail(self, reason: str) -> None:
        # Bound retained fault reasons even if supervision is delayed.
        if reason not in self.faults and len(self.faults) < 16:
            self.faults.append(reason)
        self.journal.submit("observer_fault", reason=reason)

    def clock(self, ros_ns: int, receipt_monotonic_ns: int) -> None:
        if type(ros_ns) is not int or ros_ns < 0:
            self.fail("Invalid ROS clock")
            return
        if self.last_clock is not None and ros_ns < self.last_clock:
            self.fail("ROS clock regressed")
        self.last_clock = ros_ns
        self.clock_receipt_ns = receipt_monotonic_ns

    def tf(
        self,
        parent: str,
        child: str,
        stamp_ns: int,
        *,
        receipt_ros_ns: int,
        receipt_monotonic_ns: int,
        callback_wall_ns: int,
        middleware_received_wall_ns: int | None = None,
        static: bool = False,
    ) -> None:
        if (
            type(parent) is not str
            or type(child) is not str
            or type(stamp_ns) is not int
            or any(
                type(v) is not int or v < 0
                for v in (receipt_ros_ns, receipt_monotonic_ns, callback_wall_ns)
            )
            or (
                middleware_received_wall_ns is not None
                and type(middleware_received_wall_ns) is not int
            )
        ):
            self.fail("Malformed TF timestamp or frame representation")
            return
        edge = (parent, child)
        delay = None
        if middleware_received_wall_ns is not None and middleware_received_wall_ns > 0:
            delay = callback_wall_ns - middleware_received_wall_ns
            if delay < 0:
                # Different clocks or wall clock adjustment: retain raw values,
                # but never interpret them as evidence of low callback latency.
                delay = None
        self.journal.submit(
            "tf_edge",
            parent=parent,
            child=child,
            stamp_ns=stamp_ns,
            static=static,
            receipt_ros_ns=receipt_ros_ns,
            receipt_monotonic_ns=receipt_monotonic_ns,
            callback_wall_ns=callback_wall_ns,
            middleware_received_wall_ns=middleware_received_wall_ns,
            callback_delay_ns=delay,
        )
        if (
            not parent
            or not child
            or parent == child
            or type(stamp_ns) is not int
            or stamp_ns < 0
            or (not static and stamp_ns == 0)
        ):
            self.fail("Malformed TF edge")
            return
        if static:
            return  # Static stamp zero is valid and is not a dynamic freshness sample.
        if edge not in self.edges and len(self.edges) >= 64:
            self.fail("TF edge inventory overflow")
            return
        old = self.edges.get(edge)
        if old and stamp_ns < old.stamp_ns:
            self.fail(f"TF edge regressed: {parent}->{child}")
            return
        self.edges[edge] = Edge(stamp_ns, receipt_ros_ns, receipt_monotonic_ns, delay)

    def assess_tf(
        self, now_ros_ns: int, now_monotonic_ns: int, buffer_stamp_ns: int | None
    ) -> dict:
        node_clock_ns = now_ros_ns
        # A queued node TimeSource must not make old TF appear fresh when a
        # newer raw /clock callback is already available in this same epoch.
        if self.last_clock is not None:
            now_ros_ns = max(now_ros_ns, self.last_clock)
        clock_skew = None if self.last_clock is None else node_clock_ns - self.last_clock
        observed = {}
        ready = True
        for parent, child in REQUIRED_EDGES:
            edge = self.edges.get((parent, child))
            if edge is None:
                observed[f"{parent}->{child}"] = {"classification": ["MISSING"]}
                ready = False
                continue
            age = now_ros_ns - edge.stamp_ns
            receipt_age = now_monotonic_ns - edge.receipt_monotonic_ns
            flags = []
            if edge.callback_delay_ns is None:
                flags.append("MIDDLEWARE_RECEIPT_TIME_UNAVAILABLE")
            elif edge.callback_delay_ns > CALLBACK_DELAY_NS:
                flags.append("OBSERVER_CALLBACK_DELAY")
            if age > TF_MAX_AGE_NS:
                flags.append("STALE_AT_OBSERVER")
                ready = False
                if edge.receipt_ros_ns - edge.stamp_ns > TF_MAX_AGE_NS:
                    flags.append("OLD_STAMP_AT_CALLBACK_UPSTREAM_OR_TRANSPORT_UNRESOLVED")
            # AMCL intentionally postdates map->odom by configured 0.5 s.
            # This edge diagnostic never permits a future common-chain lookup.
            if age < -500_000_000:
                flags.append("UNEXPECTED_FUTURE_EDGE")
                ready = False
            if receipt_age < 0 or receipt_age > TF_MAX_AGE_NS:
                flags.append("EDGE_RECEIPT_SILENCE_OR_OBSERVER_DELAY")
                ready = False
            observed[f"{parent}->{child}"] = {
                "stamp_ns": edge.stamp_ns,
                "age_ns": age,
                "receipt_age_ns": receipt_age,
                "callback_delay_ns": edge.callback_delay_ns,
                "classification": flags or ["FRESH"],
            }
        buffer_age = None if buffer_stamp_ns is None else now_ros_ns - buffer_stamp_ns
        buffer_ready = buffer_age is not None and 0 <= buffer_age <= TF_MAX_AGE_NS
        discrepancy = ready and not buffer_ready
        clock_ready = (
            self.last_clock is not None
            and self.last_clock > 0
            and self.clock_receipt_ns is not None
            and 0 <= now_monotonic_ns - self.clock_receipt_ns <= TF_MAX_AGE_NS
        )
        # Callback delay is disqualifying, not merely an informative flag.
        delayed = any(
            e.callback_delay_ns is not None and e.callback_delay_ns > CALLBACK_DELAY_NS
            for key, e in self.edges.items()
            if key in REQUIRED_EDGES
        )
        result = {
            "ready": (
                ready
                and buffer_ready
                and clock_ready
                and not delayed
                and not self.faults
                and clock_skew is not None
                and abs(clock_skew) <= CALLBACK_DELAY_NS
            ),
            "max_tf_age_ns": TF_MAX_AGE_NS,
            "buffer_age_ns": buffer_age,
            "buffer_observer_discrepancy": discrepancy,
            "clock_ready": clock_ready,
            "node_vs_observed_clock_ns": clock_skew,
            "edges": observed,
            "causality_note": (
                "Header age alone cannot distinguish upstream stale publication, transport delay "
                "and callback delay. Valid middleware receipt timing measures only callback delay."
            ),
        }
        self.assessments += 1
        signature = (
            result["ready"],
            result["clock_ready"],
            discrepancy,
            tuple((k, tuple(v["classification"])) for k, v in observed.items()),
        )
        # Every call still evaluates current clocks, TF edges, receipt ages and
        # thresholds. Only redundant DERIVED logging is coalesced (10 Hz maximum
        # for unchanged classification); raw TF/clock/contact observations remain.
        if (
            signature != self.last_assessment_signature
            or self.last_assessment_record_ns is None
            or now_monotonic_ns < self.last_assessment_record_ns
            or now_monotonic_ns - self.last_assessment_record_ns >= 100_000_000
        ):
            self.journal.submit("tf_assessment", assessment_ordinal=self.assessments, **result)
            self.assessments_emitted += 1
            self.last_assessment_record_ns = now_monotonic_ns
            self.last_assessment_signature = signature
        return result

    def assessment_status(self) -> dict:
        return {
            "evaluated": self.assessments,
            "emission_attempts": self.assessments_emitted,
            "coalesced": self.assessments - self.assessments_emitted,
            "unchanged_period_ns": 100_000_000,
            "semantics": (
                "All calls evaluate; raw observations unchanged; transitions emitted immediately"
            ),
        }

    def contact(self, frame: dict, receipt_monotonic_ns: int) -> None:
        self.journal.submit(
            "contact_policy_observation", frame=frame, receipt_monotonic_ns=receipt_monotonic_ns
        )
        self.contact_count += 1
        self.last_contact_receipt_ns = receipt_monotonic_ns
        if (
            self.expected_bodies is not None
            and set(frame["monitored_bodies"]) != set(self.expected_bodies)
        ) or (
            self.expected_support_pairs is not None
            and set(frame["support_pairs"]) != set(self.expected_support_pairs)
        ):
            self.fail("Contact inventory differs from configured adapter policy")
        if frame["contacts"]:
            self.fail("Unexpected non-support contact during qualification startup/execution")
        valid = (
            isinstance(frame["source_id"], str)
            and bool(frame["source_id"])
            and type(frame["sequence"]) is int
            and frame["sequence"] >= 1
            and type(frame["start_ns"]) is int
            and frame["start_ns"] >= 0
            and type(frame["end_ns"]) is int
            and frame["end_ns"] > frame["start_ns"]
            and frame["end_ns"] - frame["start_ns"] <= 250_000_000
            and type(frame["physics_steps"]) is int
            and frame["physics_steps"] > 0
            and type(frame["coverage_complete"]) is bool
            and bool(frame["monitored_bodies"])
            and bool(frame["support_pairs"])
        )
        if not valid:
            self.fail("Malformed contact observation")
        old = self.previous_contact
        if old and (
            frame["source_id"] != old["source_id"]
            or frame["monitored_bodies"] != old["monitored_bodies"]
            or frame["support_pairs"] != old["support_pairs"]
            or frame["sequence"] != old["sequence"] + 1
            or frame["start_ns"] != old["end_ns"]
        ):
            self.fail("Contact source, policy or observation continuity changed")
        complete = (
            valid
            and bool(frame["source_id"])
            and bool(frame["monitored_bodies"])
            and frame["coverage_complete"] is True
            and frame["physics_steps"] > 0
            and 0 < frame["end_ns"] - frame["start_ns"] <= 250_000_000
        )
        if self.contact_ready and not complete:
            self.fail("Contact coverage lost after becoming ready")
        # Initial settling may be incomplete; it stays explicitly UNREADY and can
        # never certify safety. The harness imposes a bounded startup wait.
        self.contact_ready = complete and not frame["contacts"] and not self.faults
        self.previous_contact = dict(frame)

    def check(self, now_monotonic_ns: int | None = None) -> None:
        self.journal.check()
        if (
            now_monotonic_ns is not None
            and self.contact_ready
            and self.last_contact_receipt_ns is not None
            and now_monotonic_ns - self.last_contact_receipt_ns > 250_000_000
        ):
            self.fail("Contact observation stream stopped after becoming ready")
        if self.faults:
            raise EvidenceFailure("; ".join(self.faults))

    def ready(self, now_monotonic_ns: int) -> bool:
        self.check()
        return bool(
            self.contact_ready
            and self.last_contact_receipt_ns is not None
            and 0 <= now_monotonic_ns - self.last_contact_receipt_ns <= 250_000_000
        )
