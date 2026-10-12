"""Shared adversarial traces compare native policy to the offline Python reference."""

import os
import random
import subprocess

import pytest
from robot_diagnostics.freshness import Monitor


@pytest.mark.parametrize("seed", range(10))
def test_native_policy_matches_reference(seed):
    randomizer = random.Random(seed)
    monitor = Monitor(("odom", "scan", "imu"))
    commands = []
    expected = []
    now = 10_000_000_000
    steady = 0.0
    last = {name: now for name in monitor.streams}
    for _ in range(300):
        steady += randomizer.choice([0.001, 0.1, 0.5, 1.0001, 2.1])
        now += randomizer.choice([0, 100_000_000, 500_000_000, 1_000_100_000])
        if randomizer.random() < 0.08:
            now = randomizer.choice([0, 1_000_000_000])
        if randomizer.random() < 0.05:
            monitor.reset_clock()
            commands.append("reset")
        if randomizer.random() < 0.8:
            stream = randomizer.choice(monitor.streams)
            stamp = randomizer.choice([now, now + 200_000_000, last[stream], 0, -1])
            last[stream] = stamp
            monitor.observe(stream, stamp, now, steady)
            commands.append(f"observe {stream} {stamp} {now} {steady:.17g}")
        commands.append(f"evaluate {now} {steady:.17g}")
        for name, status in sorted(monitor.evaluate(now, steady).items()):
            expected.append((name, status))
    result = subprocess.run(
        [os.environ["ROBOTOPS_POLICY_TRACE"]],
        input="\n".join(commands),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    lines = result.stdout.splitlines()
    assert len(lines) == len(expected)
    for line, (name, status) in zip(lines, expected, strict=True):
        actual_name, level, reason, *pairs = line.split()
        assert (actual_name, int(level), reason) == (name, status.level, status.reason)
        values = dict(pair.split("=", 1) for pair in pairs)
        assert values.keys() == status.values.keys()
        for key, value in values.items():
            assert float(value) == pytest.approx(float(status.values[key]), abs=1e-9)
