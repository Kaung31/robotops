"""Isolated native relay transport/evidence tests; no Gazebo or robot commands."""

import copy
import hashlib
import json
import signal
import subprocess
import time
from pathlib import Path

import pytest
import rclpy
from ament_index_python.packages import get_package_prefix
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from rcl_interfaces.srv import SetParameters
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.serialization import serialize_message
from robotops_interfaces.msg import FaultEvent
from rosgraph_msgs.msg import Clock
from sensor_msgs.msg import LaserScan


def executable(package="fault_injection", name="scan_fault_relay"):
    return str(Path(get_package_prefix(package)) / "lib" / package / name)


def command(directory, **overrides):
    params = dict(
        mode="sim",
        use_sim_time="true",
        experiment_id="component",
        trial_id="trial",
        fault_type="dropout",
        delay_seconds=1.5,
        duration_seconds=1.0,
        evidence_directory=str(directory),
    )
    params.update(overrides)
    args = [executable(), "--ros-args", "-r", "__ns:=/fault_test"]
    for key, value in params.items():
        if value is not None:
            args += ["-p", f"{key}:={value}"]
    return args


@pytest.fixture
def runtime(tmp_path):
    context = Context()
    rclpy.init(context=context)
    driver = Node("fault_driver", context=context, namespace="fault_test")
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(driver)
    processes = []
    scans, events, diagnostics = [], [], []
    qos = QoSProfile(depth=32, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    subscriptions = [
        driver.create_subscription(LaserScan, "scan_output", scans.append, 10),
        driver.create_subscription(FaultEvent, "fault_events", events.append, qos),
        driver.create_subscription(DiagnosticArray, "diagnostics", diagnostics.append, 10),
    ]
    # Relay offers best effort; a reliable reader would be incompatible.
    driver.destroy_subscription(subscriptions.pop(0))
    subscriptions.append(
        driver.create_subscription(
            LaserScan,
            "scan_output",
            scans.append,
            QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT),
        )
    )

    def start(args, expected=0):
        log = (tmp_path / f"process-{len(processes)}.log").open("w+")
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
        processes.append((process, log, expected))
        return process

    def until(predicate, action=lambda: None, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            action()
            executor.spin_once(timeout_sec=0.02)
            for _ in range(16):
                executor.spin_once(timeout_sec=0)
            if predicate():
                return
        details = [(s.level, s.message) for s in diagnostics[-1].status] if diagnostics else []
        raise AssertionError(f"Timed out: scans={len(scans)}, diagnostics={details}")

    def stop(process):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
        assert process.wait(timeout=8) == 0

    try:
        yield driver, scans, events, diagnostics, start, until, stop, tmp_path
    finally:
        for process, log, expected in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            output = log.read()
            log.close()
            assert process.returncode == expected, output
        assert subscriptions
        executor.shutdown()
        driver.destroy_node()
        context.shutdown()


def evidence(directory):
    raw = (directory / "events.jsonl").read_bytes()
    seal = json.loads((directory / "seal.json").read_text())
    plan = (directory / "plan.json").read_bytes()
    assert seal["events_sha256"] == hashlib.sha256(raw).hexdigest()
    assert seal["plan_sha256"] == hashlib.sha256(plan).hexdigest()
    records = [json.loads(line) for line in raw.splitlines()]
    assert seal["event_count"] == len(records)
    for index, record in enumerate(records, 1):
        assert record["sequence"] == index
        assert record["plan_sha256"] == seal["plan_sha256"]
        assert record["experiment_id"] == "component"
        assert record["trial_id"] == "trial"
    return records


@pytest.mark.parametrize(
    "kind,reason", [("dropout", "receipt_timeout"), ("stamp_freeze", "stamp_timeout")]
)
@pytest.mark.parametrize(
    "reliability", [ReliabilityPolicy.BEST_EFFORT, ReliabilityPolicy.RELIABLE]
)
def test_fault_detection_payload_recovery_and_evidence(runtime, kind, reason, reliability):
    driver, scans, events, diagnostics, start, until, stop, directory = runtime
    relay = start(command(directory / "evidence", fault_type=kind))
    start(
        [
            executable("robot_diagnostics", "freshness_monitor"),
            "--ros-args",
            "-r",
            "__ns:=/fault_test",
            "-r",
            "scan:=scan_output",
            "-p",
            "enabled_streams:=[scan]",
            "-p",
            "use_sim_time:=true",
            "-p",
            "warn_seconds:=0.1",
            "-p",
            "error_seconds:=0.2",
            "-p",
            "publish_period_seconds:=0.02",
        ]
    )
    clock = driver.create_publisher(Clock, "/clock", 10)
    scan = driver.create_publisher(
        LaserScan, "scan_input", QoSProfile(depth=10, reliability=reliability)
    )
    until(lambda: scan.get_subscription_count() == 1 and driver.count_subscribers("/clock") >= 2)
    now = 100_000_000_000
    sent = {}

    def emit():
        nonlocal now
        now += 20_000_000
        tick = Clock()
        tick.clock.sec, tick.clock.nanosec = divmod(now, 1_000_000_000)
        clock.publish(tick)
        message = LaserScan()
        message.header.stamp = tick.clock
        message.header.frame_id = "laser"
        message.angle_min, message.angle_max, message.angle_increment = -1.0, 1.0, 0.5
        message.time_increment, message.scan_time = 0.001, 0.1
        message.range_min, message.range_max = 0.1, 20.0
        # Vary values to distinguish timestamp freeze from a frozen payload.
        message.ranges = [float(now) / 1e9, 2.0, 3.0]
        message.intensities = [4.0, 5.0, 6.0]
        sent[message.ranges[0]] = message
        scan.publish(message)
        time.sleep(0.02)

    def status():
        return diagnostics[-1].status[1] if diagnostics else None

    until(lambda: scans and status() and status().level == DiagnosticStatus.OK, emit)
    before = scans[-1]
    assert serialize_message(before) == serialize_message(sent[before.ranges[0]])
    until(lambda: any(e.state == "activated" for e in events), emit)
    activated = next(e for e in events if e.state == "activated")
    assert activated.applied_confirmed and activated.affected_samples == 1
    offset = len(scans)
    expected_level = DiagnosticStatus.STALE if kind == "dropout" else DiagnosticStatus.ERROR
    until(lambda: status().message == reason and status().level == expected_level, emit)
    assert now - activated.ros_time_ns < 800_000_000
    if kind == "dropout":
        assert len(scans) <= offset + 1  # one in-flight pre-activation sample is possible
    else:
        affected = scans[offset + 1 :]
        assert len(affected) >= 2
        assert len({(s.header.stamp.sec, s.header.stamp.nanosec) for s in affected}) == 1
        for sample in affected:
            original = copy.deepcopy(sent[sample.ranges[0]])
            original.header.stamp = sample.header.stamp
            assert serialize_message(sample) == serialize_message(original)
    until(lambda: any(e.state == "ended" for e in events), emit)
    until(lambda: status().level == DiagnosticStatus.OK, emit)
    until(
        lambda: serialize_message(scans[-1]) == serialize_message(sent[scans[-1].ranges[0]]), emit
    )
    assert driver.count_publishers("scan_output") == 1
    info = driver.get_publishers_info_by_topic("scan_output")[0]
    assert info.qos_profile.reliability == ReliabilityPolicy.BEST_EFFORT
    assert info.qos_profile.durability == DurabilityPolicy.VOLATILE
    client = driver.create_client(SetParameters, "scan_fault_relay/set_parameters")
    until(client.service_is_ready)
    request = SetParameters.Request()
    request.parameters = [Parameter("use_sim_time", value=False).to_parameter_msg()]
    future = client.call_async(request)
    until(future.done)
    assert not future.result().results[0].successful
    stop(relay)
    records = evidence(directory / "evidence")
    assert [r["state"] for r in records] == ["requested", "activated", "ended"]
    assert records[-1]["affected_samples"] > 1
    assert [e.sequence for e in events] == [1, 2, 3]


def test_clock_regression_aborts_and_shutdown_closes(runtime):
    driver, scans, events, _, start, until, stop, directory = runtime
    relay = start(command(directory / "evidence", delay_seconds=0.0, duration_seconds=60.0))
    clock = driver.create_publisher(Clock, "/clock", 10)
    scan = driver.create_publisher(LaserScan, "scan_input", 10)
    until(lambda: scan.get_subscription_count() == 1)

    def emit(second):
        tick = Clock()
        tick.clock.sec = second
        clock.publish(tick)
        message = LaserScan()
        message.header.stamp.sec = second
        scan.publish(message)

    until(lambda: any(e.state == "activated" for e in events), lambda: emit(100))
    until(lambda: any(e.state == "aborted_clock" for e in events), lambda: emit(1))
    until(lambda: scans and scans[-1].header.stamp.sec == 101, lambda: emit(101))
    stop(relay)
    records = evidence(directory / "evidence")
    assert records[-1]["state"] == "aborted_clock"
    assert records[-1]["clock_epoch"] == 1
    assert sum(r["state"] == "activated" for r in records) == 1


def test_shutdown_without_clock_is_unconfirmed(runtime):
    _, _, events, _, start, until, stop, directory = runtime
    relay = start(command(directory / "evidence"))
    until(lambda: events)
    stop(relay)
    records = evidence(directory / "evidence")
    assert [r["state"] for r in records] == ["requested", "aborted_shutdown"]
    assert not any(r["applied_confirmed"] for r in records)


@pytest.mark.parametrize(
    "overrides,remaps",
    [
        ({"mode": "real"}, []),
        ({"mode": "replay"}, []),
        ({"mode": "mock"}, []),
        ({"mode": None}, []),
        ({"use_sim_time": "false"}, []),
        ({"duration_seconds": -1.0}, []),
        ({"duration_seconds": 61.0}, []),
        ({"delay_seconds": -1.0}, []),
        ({"delay_seconds": ".nan"}, []),
        ({"fault_type": "noise"}, []),
        ({"fault_type": "dropout,stamp_freeze"}, []),
        ({"severity": 0.5}, []),
        ({"input_timeout_seconds": 0.2}, []),
        ({"input_timeout_seconds": -1.0}, []),
        ({"input_timeout_seconds": ".nan"}, []),
        ({"input_startup_seconds": 0.0}, []),
        ({"experiment_id": "../bad"}, []),
        ({}, ["-r", "scan_input:=scan_output"]),
        ({}, ["-r", "scan_input:=fault_events"]),
    ],
)
def test_reject_configuration_before_data_entities(tmp_path, overrides, remaps):
    directory = tmp_path / "rejected"
    result = subprocess.run(
        command(directory, **overrides) + remaps, capture_output=True, text=True, timeout=5
    )
    assert result.returncode == 1, result.stderr
    assert "[ERROR]" in result.stderr
    assert not directory.exists()


def test_paused_active_clock_and_cleanup_count(runtime):
    driver, _, events, _, start, until, stop, directory = runtime
    relay = start(command(directory / "evidence", delay_seconds=0.0))
    clock = driver.create_publisher(Clock, "/clock", 10)
    scan = driver.create_publisher(LaserScan, "scan_input", 10)
    until(lambda: scan.get_subscription_count() == 1)

    def emit():
        tick = Clock()
        tick.clock.sec = 100
        clock.publish(tick)
        message = LaserScan()
        message.header.stamp.sec = 100
        scan.publish(message)

    until(lambda: any(e.state == "activated" for e in events), emit)
    deadline = time.monotonic() + 1.2  # longer than fault duration in wall time
    while time.monotonic() < deadline:
        emit()
        until(lambda: True)
        time.sleep(0.02)
    assert not any(e.state == "ended" for e in events)
    stop(relay)
    records = evidence(directory / "evidence")
    assert records[-1]["state"] == "aborted_shutdown"
    assert records[-1]["applied_confirmed"]
    assert records[-1]["affected_samples"] > 2
    assert records[-1]["ros_time_ns"] == 100_000_000_000


def test_force_kill_cannot_seal_incomplete_evidence(runtime):
    _, _, events, _, start, until, _, directory = runtime
    relay = start(command(directory / "evidence"), expected=-signal.SIGKILL)
    until(lambda: events)
    relay.kill()
    assert relay.wait(timeout=5) == -signal.SIGKILL
    assert (directory / "evidence/events.jsonl").read_text()
    assert not (directory / "evidence/seal.json").exists()


def test_competing_output_publisher_fails_closed(runtime):
    driver, _, _, _, start, until, _, directory = runtime
    rival = driver.create_publisher(LaserScan, "scan_output", 10)
    relay = start(command(directory / "evidence"), expected=1)
    until(lambda: relay.poll() is not None)
    assert relay.returncode == 1
    assert rival is not None
    assert evidence(directory / "evidence")[-1]["state"] == "aborted_runtime"


def test_mcap_roundtrip_preserves_actual_fault_events(runtime):
    import rosbag2_py
    from rclpy.serialization import deserialize_message

    driver, _, events, _, start, until, stop, directory = runtime
    bag = directory / "recording"
    recorder = start(
        [
            "ros2",
            "bag",
            "record",
            "--disable-keyboard-controls",
            "-s",
            "mcap",
            "-o",
            str(bag),
            "/fault_test/fault_events",
            "/fault_test/scan_output",
            "/clock",
        ]
    )
    relay = start(command(directory / "evidence", delay_seconds=0.2, duration_seconds=0.3))
    clock = driver.create_publisher(Clock, "/clock", 10)
    scan = driver.create_publisher(LaserScan, "scan_input", 10)
    until(
        lambda: driver.count_subscribers("fault_events") == 2
        and scan.get_subscription_count() == 1
        and clock.get_subscription_count() >= 2
    )
    now = 100_000_000_000

    def emit():
        nonlocal now
        now += 20_000_000
        tick = Clock()
        tick.clock.sec, tick.clock.nanosec = divmod(now, 1_000_000_000)
        clock.publish(tick)
        message = LaserScan()
        message.header.stamp = tick.clock
        message.ranges = [1.0, 2.0]
        scan.publish(message)
        time.sleep(0.02)

    until(lambda: any(e.state == "ended" for e in events), emit)
    # Advance beyond the window and let all readers receive the terminal event.
    for _ in range(10):
        emit()
        until(lambda: True)
    stop(relay)
    stop(recorder)
    raw_records = evidence(directory / "evidence")
    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag), storage_id="mcap"),
        rosbag2_py.ConverterOptions("cdr", "cdr"),
    )
    recorded_events, scan_count = [], 0
    while reader.has_next():
        topic, data, _ = reader.read_next()
        if topic == "/fault_test/fault_events":
            message = deserialize_message(data, FaultEvent)
            recorded_events.append(
                {key: getattr(message, key) for key in message.get_fields_and_field_types()}
            )
        if topic == "/fault_test/scan_output":
            scan_count += 1
    assert recorded_events == raw_records
    assert scan_count > 2
    files = list(bag.glob("*.mcap"))
    assert len(files) == 1
    (directory / "recording-sha256.json").write_text(
        json.dumps({files[0].name: hashlib.sha256(files[0].read_bytes()).hexdigest()}) + "\n"
    )


def owned_setup(runtime, expected_exit=0, **overrides):
    from action_msgs.msg import GoalStatus, GoalStatusArray
    from nav2_msgs.action._navigate_to_pose import NavigateToPose_FeedbackMessage
    from robotops_interfaces.srv import FaultControlV2

    driver, scans, events, _, start, until, stop, directory = runtime
    params = dict(
        lifecycle_mode="owned_v2",
        recovery_guard_path=str(directory / "recovery.guard"),
        delay_seconds=0.0,
        duration_seconds=0.3,
        wall_lease_seconds=8.0,
        recovery_seconds=1.0,
    )
    params.update(overrides)
    relay = start(command(directory / "owned", **params), expected=expected_exit)
    clock = driver.create_publisher(Clock, "/clock", 10)
    scan = driver.create_publisher(LaserScan, "scan_input", 10)
    status = driver.create_publisher(
        GoalStatusArray,
        "navigate_to_pose/_action/status",
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
    )
    feedback = driver.create_publisher(
        NavigateToPose_FeedbackMessage, "navigate_to_pose/_action/feedback", 10
    )
    client = driver.create_client(FaultControlV2, "fault_control")
    until(lambda: client.service_is_ready() and scan.get_subscription_count() == 1)
    plan = json.loads((directory / "owned/plan.json").read_text())
    plan_hash = hashlib.sha256((directory / "owned/plan.json").read_bytes()).hexdigest()
    now = 100_000_000_000

    def emit(advance=20_000_000):
        nonlocal now
        now += advance
        tick = Clock()
        tick.clock.sec, tick.clock.nanosec = divmod(now, 1_000_000_000)
        clock.publish(tick)
        message = LaserScan()
        # Independent /clock and sensor DDS writers have no delivery ordering.
        # Model acquisition one tick earlier; never assert recovery using a future stamp.
        stamp = now - 20_000_000 if advance else now
        message.header.stamp.sec, message.header.stamp.nanosec = divmod(stamp, 1_000_000_000)
        message.header.frame_id = "laser"
        message.ranges = [float(now) / 1e9, 2.0]
        scan.publish(message)
        time.sleep(0.02)

    def control(operation, **fields):
        request = FaultControlV2.Request(
            operation=operation,
            experiment_id="component",
            trial_id="trial",
            plan_sha256=plan_hash,
            session_id=plan["session_id"],
            clock_epoch=0,
            mission_id="a" * 32,
            nav_goal_id="b" * 32 if operation == 2 else "",
        )
        for key, value in fields.items():
            setattr(request, key, value)
        future = client.call_async(request)
        until(future.done)
        return future.result()

    def nav_status(value, goal="b" * 32):
        message = GoalStatusArray()
        item = GoalStatus()
        item.goal_info.goal_id.uuid = list(bytes.fromhex(goal))
        item.status = value
        message.status_list = [item]
        status.publish(message)

    def nav_feedback(goal="b" * 32):
        message = NavigateToPose_FeedbackMessage()
        message.goal_id.uuid = list(bytes.fromhex(goal))
        feedback.publish(message)

    until(lambda: scans, emit)
    return relay, emit, control, nav_status, nav_feedback


@pytest.mark.parametrize("kind", ["dropout", "stamp_freeze"])
def test_owned_execution_gate_and_verified_local_restoration(runtime, kind):
    _, scans, events, _, _, until, stop, directory = runtime
    relay, emit, control, status, feedback = owned_setup(runtime, fault_type=kind)
    assert control(1).accepted
    assert not control(1).accepted
    assert not control(2, trial_id="previous").accepted
    assert not control(2, session_id="old-process").accepted
    assert not control(2, plan_sha256="0" * 64).accepted
    assert not control(2, clock_epoch=1).accepted
    assert control(2).accepted
    assert not control(2, nav_goal_id="c" * 32).accepted
    for _ in range(5):
        status(1)
        emit()
        until(lambda: True)
    assert not any(e.state == "execution_started" for e in events)
    for _ in range(5):
        status(2)
        feedback("c" * 32)
        emit()
        until(lambda: True)
    assert not any(e.state == "effect_observed" for e in events)
    until(lambda: any(e.state == "effect_observed" for e in events), lambda: (feedback(), emit()))
    assert any(e.state == "activation_acknowledged" and not e.applied_confirmed for e in events)
    assert any(e.state == "effect_observed" and e.applied_confirmed for e in events)
    until(lambda: any(e.state == "recovery_verified" for e in events), emit)
    assert not (directory / "recovery.guard").exists()
    assert scans[-1].header.stamp.sec > 0
    assert not control(1).accepted
    stop(relay)
    records = evidence(directory / "owned")
    assert records[-1]["state"] == "recovery_verified"
    assert records[-1]["recovery_verified"]
    assert records[-1]["mission_id"] == "a" * 32
    assert records[-1]["nav_goal_id"] == "b" * 32


@pytest.mark.parametrize("stage", ["pending", "armed", "active"])
def test_owned_cancel_prevents_late_callbacks_and_rearming(runtime, stage):
    _, _, events, _, _, until, stop, directory = runtime
    relay, emit, control, status, feedback = owned_setup(runtime, duration_seconds=60.0)
    if stage != "pending":
        assert control(1).accepted
        assert control(2).accepted
    if stage == "active":
        until(
            lambda: any(e.state == "effect_observed" for e in events),
            lambda: (status(2), feedback(), emit()),
        )
    assert control(3).accepted
    until(
        lambda: any(e.state == "recovery_verified" for e in events),
        lambda: (status(2), feedback(), emit()),
    )
    assert not control(1).accepted
    if stage != "active":
        assert not any(e.state == "effect_observed" for e in events)
    stop(relay)
    assert evidence(directory / "owned")[-1]["state"] == "recovery_verified"


def test_owned_wall_expiry_paused_clock_and_restart_quarantine(runtime):
    _, _, events, _, start, until, stop, directory = runtime
    relay, emit, control, status, feedback = owned_setup(
        runtime, duration_seconds=60.0, wall_lease_seconds=1.5, recovery_seconds=0.2
    )
    assert control(1).accepted and control(2).accepted
    until(
        lambda: any(e.state == "effect_observed" for e in events),
        lambda: (status(2), feedback(), emit(0)),
    )
    until(lambda: any(e.state == "recovery_uncertain" for e in events), timeout=4)
    assert (directory / "recovery.guard").exists()
    assert not control(1).accepted
    stop(relay)
    assert evidence(directory / "owned")[-1]["state"] == "recovery_uncertain"
    rejected = start(
        command(
            directory / "restart",
            lifecycle_mode="owned_v2",
            recovery_guard_path=str(directory / "recovery.guard"),
        ),
        expected=1,
    )
    until(lambda: rejected.poll() is not None)
    assert rejected.returncode == 1
    assert (directory / "recovery.guard").exists()


@pytest.mark.parametrize("status_value", [3, 4, 5, 6])
def test_owned_terminal_status_before_execution_never_activates(runtime, status_value):
    _, _, events, _, _, until, stop, directory = runtime
    relay, emit, control, status, feedback = owned_setup(runtime)
    assert control(1).accepted and control(2).accepted
    until(
        lambda: any(e.state.startswith("stopped_nav") for e in events),
        lambda: (status(status_value), emit()),
    )
    until(
        lambda: any(e.state == "recovery_verified" for e in events), lambda: (feedback(), emit())
    )
    assert not any(e.state == "effect_observed" for e in events)
    stop(relay)
    assert evidence(directory / "owned")[-1]["state"] == "recovery_verified"


def test_owned_typed_evidence_and_unverified_shutdown_guard(runtime):
    from robotops_interfaces.msg import FaultLifecycleEvent

    driver, _, events, _, start, until, _, directory = runtime
    received = []
    subscription = driver.create_subscription(
        FaultLifecycleEvent,
        "fault_lifecycle_events",
        received.append,
        QoSProfile(depth=32, durability=DurabilityPolicy.TRANSIENT_LOCAL),
    )
    relay, emit, control, status, feedback = owned_setup(runtime, duration_seconds=60.0)
    assert control(1).accepted and control(2).accepted
    until(
        lambda: any(e.evidence.state == "effect_observed" for e in received),
        lambda: (status(2), feedback(), emit()),
    )
    item = next(e for e in received if e.evidence.state == "effect_observed")
    assert item.evidence.schema_version == 2
    assert item.mission_id == "a" * 32 and item.nav_goal_id == "b" * 32
    assert item.session_id and item.wall_monotonic_ns > 0 and not item.recovery_verified
    # A graceful process exit is not proof of sensor restoration.
    relay.send_signal(signal.SIGINT)
    until(lambda: relay.poll() is not None)
    assert relay.returncode == 0
    assert (directory / "recovery.guard").exists()
    assert not evidence(directory / "owned")[-1]["recovery_verified"]
    assert events and subscription


@pytest.mark.parametrize("mode", ["real", "mock", "replay", None])
def test_owned_rejects_non_sim_before_guard_or_data(tmp_path, mode):
    guard = tmp_path / "guard"
    result = subprocess.run(
        command(
            tmp_path / "rejected",
            mode=mode,
            lifecycle_mode="owned_v2",
            recovery_guard_path=str(guard),
        ),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 1
    assert not guard.exists() and not (tmp_path / "rejected").exists()


def test_owned_binding_refreshes_already_published_durable_executing_status(runtime):
    _, _, events, _, _, until, stop, directory = runtime
    relay, emit, control, status, feedback = owned_setup(runtime)
    # Real Nav2 may publish EXECUTING once before bind, then only terminal status.
    assert control(1).accepted
    status(2)
    for _ in range(4):
        emit()
        until(lambda: True)
    assert not any(e.state == "execution_started" for e in events)
    assert control(2).accepted
    until(
        lambda: any(e.state == "effect_observed" for e in events),
        lambda: (feedback(), emit()),
    )
    until(lambda: any(e.state == "recovery_verified" for e in events), emit)
    stop(relay)
    assert evidence(directory / "owned")[-1]["recovery_verified"]


def test_owned_force_kill_keeps_guard_and_missing_seal(runtime):
    _, _, events, _, _, until, _, directory = runtime
    relay, emit, control, status, feedback = owned_setup(
        runtime, expected_exit=-signal.SIGKILL, duration_seconds=60.0
    )
    assert control(1).accepted and control(2).accepted
    until(
        lambda: any(e.state == "effect_observed" for e in events),
        lambda: (status(2), feedback(), emit()),
    )
    relay.kill()
    assert relay.wait(timeout=5) == -signal.SIGKILL
    assert (directory / "recovery.guard").exists()
    assert not (directory / "owned/seal.json").exists()


def test_owned_clean_restart_rejects_previous_process_commands(runtime):
    _, _, events, _, start, until, stop, directory = runtime
    relay, emit, control, _, _ = owned_setup(runtime)
    assert control(3).accepted
    until(lambda: any(e.state == "recovery_verified" for e in events), emit)
    stop(relay)
    restarted = start(
        command(
            directory / "restarted",
            lifecycle_mode="owned_v2",
            recovery_guard_path=str(directory / "recovery.guard"),
        )
    )
    until(lambda: sum(e.state == "requested" for e in events) >= 2)
    assert not control(1).accepted
    plan = directory / "restarted/plan.json"
    assert control(
        3,
        session_id=json.loads(plan.read_text())["session_id"],
        plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
        mission_id="",
    ).accepted
    until(lambda: sum(e.state == "recovery_verified" for e in events) >= 2, emit)
    stop(restarted)
    assert not (directory / "recovery.guard").exists()


def test_owned_input_loss_is_bounded_and_quarantined(runtime):
    driver, _, events, _, _, until, _, directory = runtime
    relay, emit, _, _, _ = owned_setup(runtime, expected_exit=1, input_timeout_seconds=0.2)
    for _ in range(5):
        emit()
        until(lambda: True)
    # Destroy the raw publisher, leaving relay alive initially. No robot/Nav2 exists.
    for publisher in list(driver.publishers):
        if publisher.topic_name == "/fault_test/scan_input":
            driver.destroy_publisher(publisher)
    until(lambda: relay.poll() is not None, timeout=2)
    assert relay.returncode == 1 and (directory / "recovery.guard").exists()
    records = evidence(directory / "owned")
    assert any(e["state"] == "stopped_runtime_failure" for e in records)
    assert not any(e["state"] == "recovery_verified" for e in records)
    assert any(e.state == "requested" for e in events)


def test_owned_input_watchdog_does_not_confuse_output_dropout(runtime):
    _, _, events, _, _, until, stop, directory = runtime
    relay, emit, control, status, feedback = owned_setup(
        runtime, input_timeout_seconds=0.2, duration_seconds=0.4
    )
    assert control(1).accepted and control(2).accepted
    status(2)
    until(lambda: any(e.state == "effect_observed" for e in events), lambda: (feedback(), emit()))
    until(lambda: any(e.state == "recovery_verified" for e in events), emit)
    assert relay.poll() is None and not (directory / "recovery.guard").exists()
    stop(relay)


def test_owned_missing_initial_input_times_out(runtime):
    _, _, _, _, start, until, _, directory = runtime
    relay = start(
        command(
            directory / "missing-input",
            lifecycle_mode="owned_v2",
            recovery_guard_path=str(directory / "recovery.guard"),
            input_timeout_seconds=0.2,
            input_startup_seconds=0.2,
        ),
        expected=1,
    )
    until(lambda: relay.poll() is not None, timeout=2)
    assert (directory / "recovery.guard").exists()
    assert "upstream_scan_startup_timeout" in (directory / "process-0.log").read_text()


def test_owned_dropout_real_monitor_diagnostic_window(runtime):
    """Synthetic ROS only: no robot, Gazebo, mission server or actual Nav2 route."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from probe_evidence import OUTPUT_MONITOR, assess_diagnostic_window, diagnostic_level

    _, _, events, diagnostics, start, until, stop, directory = runtime
    relay, emit, control, status, feedback = owned_setup(
        runtime, input_timeout_seconds=2.0, delay_seconds=0.2, duration_seconds=1.0
    )
    monitor = start(
        [
            executable("robot_diagnostics", "freshness_monitor"),
            "--ros-args",
            "-r",
            "__ns:=/fault_test",
            "-r",
            "__node:=output_scan_monitor",
            "-p",
            "use_sim_time:=true",
            "-p",
            "enabled_streams:=[scan]",
            "-p",
            f"hardware_id:={OUTPUT_MONITOR}",
            "-r",
            "scan:=scan_output",
        ]
    )
    until(
        lambda: diagnostics
        and all(diagnostic_level(s.level) == 0 for s in diagnostics[-1].status),
        emit,
    )
    # Keep a recent healthy pre-window diagnostic; startup STALE must never count.
    for _ in range(15):
        emit()
        until(lambda: True)
    assert control(1).accepted and control(2).accepted
    status(2)
    until(
        lambda: any(e.state == "recovery_verified" for e in events), lambda: (feedback(), emit())
    )
    for _ in range(35):
        emit()
        until(lambda: True)
    rows = [
        {
            "stamp_ns": d.header.stamp.sec * 10**9 + d.header.stamp.nanosec,
            "status": [
                {
                    "name": s.name,
                    "hardware_id": s.hardware_id,
                    "level": diagnostic_level(s.level),
                    "message": s.message,
                    "values": {v.key: v.value for v in s.values},
                }
                for s in d.status
            ],
        }
        for d in diagnostics
    ]
    times = {e.state: e.ros_time_ns for e in events}
    checked = assess_diagnostic_window(
        rows,
        times["activation_acknowledged"],
        times["stopped_ended"],
        times["recovery_verified"],
        rows[-1]["stamp_ns"],
    )
    (directory / "diagnostic-window.json").write_text(
        json.dumps(
            {"scope": "synthetic_ROS_no_robot_or_Nav2", "rows": rows, "verified": checked},
            indent=2,
        )
        + "\n"
    )
    assert checked["degraded_ns"] and len(checked["recovered_ns"]) == 2
    stop(monitor)
    stop(relay)
