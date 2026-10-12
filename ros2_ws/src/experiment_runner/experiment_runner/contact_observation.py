"""Read-only bounded contact evidence collector; no simulator imports."""

import time

import rclpy
from robotops_interfaces.msg import ContactEvidence

from experiment_runner.contacts import evaluate_contacts


class ContactObservation:
    def __init__(self, node):
        self.node = node
        self.latest = None
        self.frames = None
        self.overflow = False
        self.subscription = node.create_subscription(
            ContactEvidence, "validation/contacts", self.receive, 100
        )

    def receive(self, message):
        frame = {
            key: getattr(message, key)
            for key in (
                "source_id",
                "sequence",
                "start_ns",
                "end_ns",
                "physics_steps",
                "coverage_complete",
                "support_contact_steps",
            )
        }
        frame["monitored_bodies"] = list(message.monitored_bodies)
        frame["support_pairs"] = list(message.support_pairs)
        frame["contacts"] = [
            dict(body_a=p.body_a, body_b=p.body_b, first_ns=p.first_ns, last_ns=p.last_ns)
            for p in message.contacts
        ]
        self.latest = frame
        if self.frames is not None:
            if len(self.frames) < 100_000:
                self.frames.append(frame)
            else:
                self.overflow = True

    def begin(self):
        self.frames = [self.latest] if self.latest else []
        self.overflow = False

    def finish(self, start_ns, end_ns):
        # Wait only for evidence covering the terminal boundary, not for robot readiness.
        # An absent adapter costs at most one wall second and remains UNKNOWN.
        deadline = time.monotonic() + 1.0
        while (not self.latest or self.latest["end_ns"] < end_ns) and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=0.02)
        frames, self.frames = self.frames or [], None
        result = evaluate_contacts(frames, start_ns, end_ns)
        if self.overflow:
            result["reasons"].append("Contact evidence buffer overflow")
            if result["verdict"] == "NO_CONTACT_OBSERVED":
                result["verdict"] = "UNKNOWN"
        result["topic"] = self.node.resolve_topic_name("validation/contacts")
        return result, frames
