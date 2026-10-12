"""Missing, stale or discontinuous contact evidence cannot certify zero contacts."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_runner.contacts import evaluate_contacts


def frames():
    return [
        dict(
            source_id="source",
            sequence=i,
            start_ns=i * 50_000_000,
            end_ns=(i + 1) * 50_000_000,
            physics_steps=50,
            coverage_complete=True,
            monitored_bodies=["body"],
            support_pairs=["wheel|floor"],
            support_contact_steps=50,
            contacts=[],
        )
        for i in range(1, 5)
    ]


def evaluate(data):
    return evaluate_contacts(data, 60_000_000, 240_000_000)


def test_complete_coverage_and_absent_adapter():
    assert evaluate(frames())["verdict"] == "NO_CONTACT_OBSERVED"
    assert evaluate([])["verdict"] == "UNKNOWN"


@pytest.mark.parametrize(
    "mutation",
    [
        "drop",
        "source",
        "inventory",
        "policy",
        "coverage",
        "steps",
        "sequence",
        "clock",
        "start",
        "end",
    ],
)
def test_coverage_failure_is_unknown(mutation):
    data = frames()
    if mutation == "drop":
        del data[1]
    elif mutation == "source":
        data[1]["source_id"] = "restarted"
    elif mutation == "inventory":
        data[1]["monitored_bodies"] = ["different"]
    elif mutation == "policy":
        data[1]["support_pairs"] = ["chassis|floor"]
    elif mutation == "coverage":
        data[1]["coverage_complete"] = False
    elif mutation == "steps":
        data[1]["physics_steps"] = 0
    elif mutation == "sequence":
        data[1]["sequence"] += 10
    elif mutation == "clock":
        data[1]["start_ns"] -= 1
    elif mutation == "start":
        data = data[1:]
    elif mutation == "end":
        data = data[:-1]
    assert evaluate(data)["verdict"] == "UNKNOWN"


def test_positive_contact_survives_missing_coverage():
    data = frames()
    pair = dict(body_a="robot", body_b="wall", first_ns=110_000_000, last_ns=140_000_000)
    data[1]["contacts"] = [pair]
    data[2]["coverage_complete"] = False
    assert evaluate(data)["verdict"] == "CONTACT_DETECTED"
    assert evaluate(data)["contacts"] == [pair]
    data[1]["contacts"][0]["first_ns"] = 0
    assert evaluate(data)["verdict"] == "UNKNOWN"


def test_contacts_outside_mission_not_counted_and_invalid_clock():
    data = frames()
    data[0]["contacts"] = [dict(body_a="a", body_b="b", first_ns=51_000_000, last_ns=52_000_000)]
    assert evaluate(data)["verdict"] == "NO_CONTACT_OBSERVED"
    assert evaluate_contacts(copy.deepcopy(data), 100, 0)["verdict"] == "UNKNOWN"
