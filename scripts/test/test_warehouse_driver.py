"""Offline coordinator/adapter fixtures; no ROS initialization or real subprocesses."""

import copy
import json
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "backend")]
from robotops_backend.campaigns.ownership import RuntimeOwnership  # noqa: E402
from robotops_backend.campaigns.repository import CampaignConflict  # noqa: E402
from warehouse_qualification import driver, runtime  # noqa: E402
from warehouse_qualification.journal import BufferedJournal  # noqa: E402


@pytest.fixture(autouse=True)
def no_robotics(monkeypatch):
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("Real process prohibited")
    )
    try:
        import rclpy
    except ImportError:
        return
    monkeypatch.setattr(rclpy, "init", lambda *a, **k: pytest.fail("ROS prohibited"))
    monkeypatch.setattr(rclpy, "create_node", lambda *a, **k: pytest.fail("ROS node prohibited"))


def manifest():
    return {
        "state": "completed",
        "trials": [
            {
                "action_status": 4,
                "mission_outcome": "succeeded",
                "validation": {"verdict": "POSE_VERIFIED"},
                "collision": {"verdict": "NO_CONTACT_OBSERVED"},
            }
        ],
    }


class FakeRuntime:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail
        self.report = manifest()
        self.gate = {"tf": True, "contact": True, "lidar": True, "localization": True}
        self.shutdown = dict.fromkeys(driver.REQUIRED_SHUTDOWN, True)

    def step(self, name):
        self.calls.append(name)
        if self.fail == name:
            raise RuntimeError(f"Synthetic {name} failure")

    def preflight(self):
        self.step("preflight")
        return {"verified": True}

    def open(self, fd):
        assert fd >= 0
        self.step("open")

    def gates(self):
        self.step("gates")
        return self.gate

    def run(self):
        self.step("run")
        return self.report

    def close(self, error):
        self.original_error = error
        self.step("close")
        return self.shutdown


@pytest.fixture
def prepared(tmp_path):
    for relative in (driver.GUARD, *driver.HISTORICAL_CLAIMS):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("immutable retained evidence")
    db = tmp_path / "artifacts/campaigns.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE runtime_lease (id INTEGER)")
    owner = RuntimeOwnership(tmp_path / "artifacts/runtime.lock", driver.ReadOnlyLease(db))
    plan = {
        "execution_approved": False,
        "attempt_set": driver.ATTEMPT_SET,
        "attempt_policy": copy.deepcopy(driver.ATTEMPT_POLICY),
        "evidence_contract": copy.deepcopy(driver.CONTRACT),
        "historical_claims": {p: driver.sha(tmp_path / p) for p in driver.HISTORICAL_CLAIMS},
        "guard": driver.identity(tmp_path / driver.GUARD),
        "original_claim_sha256": driver.sha(tmp_path / driver.ORIGINAL_CLAIM),
        "plan_sha256": "a" * 64,
    }
    return tmp_path, owner, plan


def execute(prepared, fake, profile="navfn_rpp"):
    root, owner, plan = prepared
    return driver.execute(root, profile, owner, fake, plan)


def test_success_and_second_profile_gating(prepared):
    first = FakeRuntime()
    original = copy.deepcopy(first.report)
    assert execute(prepared, first)["qualified"]
    assert first.calls == ["preflight", "open", "gates", "run", "close"]
    assert first.report == original
    assert execute(prepared, FakeRuntime(), "smac_dwb")["qualified"]
    with pytest.raises(RuntimeError):
        execute(prepared, FakeRuntime())


def test_smac_never_starts_without_first(prepared):
    fake = FakeRuntime()
    with pytest.raises(RuntimeError):
        execute(prepared, fake, "smac_dwb")
    assert not fake.calls


@pytest.mark.parametrize("stage", ["preflight", "open", "gates", "run", "close"])
def test_failures_stop_and_preserve_claims(prepared, stage):
    root, owner, _ = prepared
    fake = FakeRuntime(stage)
    with pytest.raises(RuntimeError):
        execute(prepared, fake)
    claim = root / "artifacts" / driver.ATTEMPT_SET / "navfn_rpp.claim.json"
    if stage == "preflight":
        assert not claim.exists()
    else:
        assert claim.exists()
        saved = json.loads(claim.with_name("navfn_rpp-result.json").read_text())
        assert not saved["qualified"] and saved["error"]
        before = driver.sha(claim)
        with pytest.raises(RuntimeError):
            execute(prepared, FakeRuntime())
        assert driver.sha(claim) == before
        assert "close" in fake.calls
    fd = owner.acquire_manual()
    owner.release(fd)
    if stage in ("open", "gates"):
        assert "run" not in fake.calls


@pytest.mark.parametrize("key", ["tf", "contact", "lidar", "localization"])
def test_dispatch_requires_all_gates(prepared, key):
    fake = FakeRuntime()
    fake.gate[key] = False
    with pytest.raises(RuntimeError):
        execute(prepared, fake)
    assert "run" not in fake.calls


@pytest.mark.parametrize("key", sorted(driver.REQUIRED_SHUTDOWN))
def test_successful_mission_cannot_hide_teardown_or_evidence_failure(prepared, key):
    fake = FakeRuntime()
    fake.shutdown[key] = False
    with pytest.raises(RuntimeError):
        execute(prepared, fake)
    assert fake.report == manifest()


@pytest.mark.parametrize("part", ["mission", "pose", "collision", "incomplete"])
def test_original_verdicts_remain_authoritative(prepared, part):
    fake = FakeRuntime()
    if part == "mission":
        fake.report["trials"][0]["action_status"] = 6
    elif part == "pose":
        fake.report["trials"][0]["validation"]["verdict"] = "INCONCLUSIVE"
    elif part == "collision":
        fake.report["trials"][0]["collision"]["verdict"] = "UNKNOWN"
    else:
        fake.report["state"] = "failed"
    original = copy.deepcopy(fake.report)
    with pytest.raises(RuntimeError):
        execute(prepared, fake)
    assert fake.report == original


def test_lock_contention_and_readonly_campaign_lease(prepared):
    root, owner, _ = prepared
    lock = owner.acquire_manual()
    try:
        with pytest.raises(CampaignConflict):
            execute(prepared, FakeRuntime())
    finally:
        owner.release(lock)
    db = root / "artifacts/campaigns.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("INSERT INTO runtime_lease VALUES (1)")
    before = driver.sha(db)
    with pytest.raises(CampaignConflict):
        execute(prepared, FakeRuntime())
    assert driver.sha(db) == before


def test_guard_mutation_blocks_before_start(prepared):
    root, _, _ = prepared
    (root / driver.GUARD).write_text("changed fixture only")
    fake = FakeRuntime()
    with pytest.raises(RuntimeError):
        execute(prepared, fake)
    assert not fake.calls


def test_result_write_failure_never_returns_success(prepared, monkeypatch):
    original = driver.save_summary

    def save(path, value):
        if path.name.endswith("-result.json"):
            raise OSError("disk failed")
        original(path, value)

    monkeypatch.setattr(driver, "save_summary", save)
    with pytest.raises(OSError):
        execute(prepared, FakeRuntime())
    # Claim survives even when the independent terminal summary cannot be saved.
    root, owner, _ = prepared
    assert (root / "artifacts" / driver.ATTEMPT_SET / "navfn_rpp.claim.json").exists()
    fd = owner.acquire_manual()
    owner.release(fd)


@pytest.mark.parametrize(
    "forced,code,expected", [(False, 0, True), (False, 1, False), (True, -9, False)]
)
def test_runner_cancellation_and_forced_exit(tmp_path, forced, code, expected):
    events = []

    class Child:
        pid = 123

        def __init__(self):
            self.code = None
            self.waits = 0

        def poll(self):
            return self.code

        def send_signal(self, sig):
            events.append(sig)

        def wait(self, timeout):
            events.append(timeout)
            self.waits += 1
            if forced and self.waits == 1:
                raise subprocess.TimeoutExpired("fixture", timeout)
            self.code = code

    j = BufferedJournal(tmp_path / "journal.jsonl")
    assert runtime.stop_runner(Child(), j, killpg=lambda p, s: events.append((p, s))) == expected
    assert events[:2] == [signal.SIGINT, 35]
    if forced:
        assert events[2:] == [(123, signal.SIGKILL), 5]
    assert j.close()["complete"]


def test_permission_denied_without_ros(prepared, tmp_path):
    root, _, plan = prepared
    plan_path, permission = tmp_path / "plan.json", tmp_path / "permission.json"
    plan_path.write_text(json.dumps(plan))
    permission.write_text(json.dumps({"execution_approved": False}))
    adapter = runtime.QualificationRuntime(root, "navfn_rpp", plan_path, permission)
    with pytest.raises(RuntimeError, match="owner execution approval"):
        adapter.preflight()


def test_process_census_ignores_shell_text_detects_real_argv(tmp_path):
    for pid, args in [
        (1, ["bash", "-c", "ros2 launch gazebo_runner"]),
        (2, ["/usr/bin/python3", "/opt/ros/jazzy/bin/ros2", "launch", "robot_bringup"]),
        (3, ["/opt/ros/jazzy/lib/nav2_controller/controller_server"]),
        (4, ["/usr/bin/ruby", "/usr/bin/gz", "sim", "-r"]),
        (5, ["/opt/ros/jazzy/lib/fault_injection/scan_fault_relay"]),
    ]:
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / "cmdline").write_bytes("\0".join(args).encode() + b"\0")
    assert sorted(r["pid"] for r in runtime.robotics_processes(tmp_path)) == [2, 3, 4, 5]


@pytest.fixture
def session_module():
    pytest.importorskip("rclpy")
    sys.path.insert(0, str(ROOT / "ros2_ws/src/robot_navigation/test"))
    import warehouse_session

    return warehouse_session


def test_partial_shutdown_continues_after_process_exception(session_module, tmp_path, monkeypatch):
    m = session_module
    s = m.WarehouseQualificationSession(tmp_path / "session", Path("/unused"), "navfn_rpp")
    calls = []

    class Child:
        def __init__(self, pid):
            self.pid = pid

        def poll(self):
            return None

        def send_signal(self, value):
            calls.append(("signal", self.pid))
            if self.pid == 2:
                raise OSError("synthetic signal error")

        def wait(self, timeout):
            calls.append(("wait", self.pid))

    s.processes = [Child(1), Child(2)]
    s.listener = SimpleNamespace(unregister=lambda: calls.append("listener"))
    s.node = SimpleNamespace(destroy_node=lambda: calls.append("node"))
    monkeypatch.setattr(
        pytest.importorskip("rclpy"), "shutdown", lambda: calls.append("ros_shutdown")
    )
    with pytest.raises(RuntimeError, match="teardown incomplete"):
        s._terminate_owned()
    assert ("wait", 1) in calls and calls[-3:] == ["listener", "node", "ros_shutdown"]
    assert s.journal.close()["complete"]


def test_costmap_receipts_need_real_ready_events_and_drained_logs(session_module, tmp_path):
    m = session_module
    s = m.WarehouseQualificationSession(tmp_path / "session", Path("/unused"), "navfn_rpp")
    path = s.directory / "pipeline.log"
    path.write_text(
        "".join(
            f"[{server}-3] MessageFilter [target={target}]: {event} "
            f"in frame lidar_link at time {i}.0\n"
            for server, target in [("controller_server", "odom"), ("planner_server", "map")]
            for event in ["Added message", "Message ready"]
            for i in range(1, 6)
        )
    )
    s.logs = [(path, None)]
    assert s.consumer_receipts_ready()
    assert len(s.consumer_stamps["controller_server"]) == 5
    assert s.journal.close()["complete"]


@pytest.mark.parametrize("failure", [None, "timeout", "contact", "tf", "logging", "sensor"])
def test_concrete_runner_dispatch_contract_and_failures(prepared, tmp_path, monkeypatch, failure):
    pytest.importorskip("experiment_runner.model")
    root, _, plan = prepared
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    a = runtime.QualificationRuntime(root, "navfn_rpp", plan_path, tmp_path / "permission.json")
    a.matrix = json.loads((ROOT / "benchmarks/warehouse_v1/matrix.json").read_text())
    a.directory.mkdir(parents=True)
    a.lock_fd = 42
    calls = []
    j = BufferedJournal(a.directory / "observations.jsonl")

    class Session:
        journal = j
        domain_id = 201
        partition = "fixture_only"
        map_file = Path("/fixture/map.yaml")
        observer = SimpleNamespace(check=lambda: None)

        def start(self, label, command):
            calls.append(("mission", command))

        def wait(self, predicate, reason, timeout):
            assert timeout == 650
            calls.append(("wait", timeout))
            if failure:
                raise RuntimeError(f"Synthetic {failure}")
            assert predicate()

    a.session = Session()
    monkeypatch.setattr(a, "gates", lambda: calls.append("dispatch_gates"))

    class Runner:
        pid = 999
        returncode = 0

        def poll(self):
            return 0

    def popen(command, **kwargs):
        assert kwargs["pass_fds"] == (42,)
        assert kwargs["start_new_session"]
        assert kwargs["env"]["ROS_DOMAIN_ID"] == "201"
        assert kwargs["env"]["GZ_PARTITION"] == "fixture_only"
        calls.append(("runner", command))
        path = a.directory / "experiments/fixture/manifest.json"
        path.parent.mkdir(parents=True)
        data = manifest()
        data["config"] = json.loads((a.directory / "qualification.json").read_text())
        path.write_text(json.dumps(data))
        return Runner()

    monkeypatch.setattr(subprocess, "Popen", popen)
    try:
        if failure:
            with pytest.raises(RuntimeError, match=failure):
                a.run()
        else:
            original = a.run()
            assert original["config"]["repetitions"] == 1
            assert original["config"]["mission"]["waypoints"] == a.matrix["mission"]["waypoints"]
            assert original["config"]["validation"]["tf_max_age_s"] == 1
            assert driver.sha(a.manifest_path) == a.manifest_hash
        assert [c[0] if isinstance(c, tuple) else c for c in calls] == [
            "mission",
            "dispatch_gates",
            "runner",
            "wait",
        ]
        assert all("fault" not in str(c) for c in calls)
    finally:
        if a.runner_log:
            a.runner_log.close()
        assert j.close()["complete"]


@pytest.mark.parametrize(
    "runner_error,session_error", [(False, False), (True, False), (False, True)]
)
def test_adapter_close_always_attempts_owned_shutdown(
    prepared, tmp_path, monkeypatch, runner_error, session_error
):
    root, _, plan = prepared
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    a = runtime.QualificationRuntime(root, "navfn_rpp", plan_path, tmp_path / "permission.json")
    a.directory.mkdir(parents=True)
    calls = []

    def close(*args):
        calls.append("session_close")
        (a.directory / "observer-shutdown.json").write_text(
            json.dumps({"observer_and_cleanup_complete": not session_error})
        )
        if session_error:
            raise RuntimeError("synthetic session cleanup error")

    a.session = SimpleNamespace(
        journal=SimpleNamespace(submit=lambda *a, **k: True), __exit__=close
    )

    def stop(*args, **kwargs):
        calls.append("runner_cancel")
        if runner_error:
            raise OSError("synthetic cancellation error")
        return True

    monkeypatch.setattr(runtime, "stop_runner", stop)
    monkeypatch.setattr(runtime, "robotics_processes", lambda: [])
    result = a.close(RuntimeError("synthetic original failure"))
    assert calls == ["runner_cancel", "session_close"]
    assert not result["recording_integrity_and_original_immutability"]
    assert result["cleanup_no_exception"] == (not runner_error and not session_error)


@pytest.mark.parametrize(
    "mutation", [None, "source", "installed", "processes", "domain", "directory"]
)
def test_full_preflight_is_offline_and_fail_closed(prepared, tmp_path, monkeypatch, mutation):
    import robotops_backend.benchmarks.warehouse as warehouse

    root, _, plan = prepared
    matrix = root / "benchmarks/warehouse_v1/matrix.json"
    matrix.parent.mkdir(parents=True)
    matrix.write_text(json.dumps({"scenario": {"descriptor": {"path": "descriptor.json"}}}))
    (root / "descriptor.json").write_text("{}")
    source = root / "fixture-source.py"
    source.write_text("fixture only")
    plan.update(
        files={"fixture-source.py": driver.sha(source)}, installed={"fixture-installed": "a" * 64}
    )
    pp = tmp_path / "plan.json"
    pp.write_text(json.dumps(plan))
    permission = tmp_path / "permission.json"
    permission.write_text(
        json.dumps(
            {
                "execution_approved": True,
                "plan_sha256": driver.sha(pp),
                "attempt_set": driver.ATTEMPT_SET,
                "profiles": ["navfn_rpp", "smac_dwb"],
                "owner_approval_reference": "SYNTHETIC FIXTURE ONLY - NOT REAL APPROVAL",
            }
        )
    )
    a = runtime.QualificationRuntime(root, "navfn_rpp", pp, permission)
    checked = []
    monkeypatch.setattr(warehouse, "validate_matrix", lambda *args: checked.append("matrix"))
    monkeypatch.setattr(runtime, "installed_inventory", lambda *args: plan["installed"])
    monkeypatch.setattr(runtime, "robotics_processes", lambda: [])
    monkeypatch.setenv("ROS_DOMAIN_ID", "201")
    if mutation == "source":
        source.write_text("changed")
    if mutation == "installed":
        monkeypatch.setattr(runtime, "installed_inventory", lambda *args: {})
    if mutation == "processes":
        monkeypatch.setattr(runtime, "robotics_processes", lambda: [{"pid": 42}])
    if mutation == "domain":
        monkeypatch.delenv("ROS_DOMAIN_ID")
    if mutation == "directory":
        a.directory.mkdir(parents=True)
    if mutation:
        with pytest.raises((RuntimeError, FileExistsError)):
            a.preflight()
    else:
        assert a.preflight()["source_install_map_profile_floor_verified"]
        assert checked == ["matrix"]


def test_guard_change_after_run_blocks_qualification(prepared):
    root, _, _ = prepared
    fake = FakeRuntime()

    def run():
        (root / driver.GUARD).write_text("synthetic guard mutation")
        return manifest()

    fake.run = run
    with pytest.raises(RuntimeError):
        execute(prepared, fake)
    result = json.loads(
        (root / "artifacts" / driver.ATTEMPT_SET / "navfn_rpp-result.json").read_text()
    )
    assert not result["qualified"] and "guard identity" in result["cleanup_error"]


def test_journal_failure_during_cancel_still_waits(tmp_path):
    journal = SimpleNamespace(submit=lambda *a, **k: False)
    calls = []

    class Child:
        pid = 123

        def __init__(self):
            self.code = None

        def poll(self):
            return self.code

        def send_signal(self, sig):
            calls.append("sigint")

        def wait(self, timeout):
            calls.append("wait")
            self.code = 0

    assert runtime.stop_runner(Child(), journal)
    assert calls == ["sigint", "wait"]


@pytest.mark.parametrize("ready", [False, True])
def test_session_wait_timeout_and_readiness_loss(session_module, tmp_path, monkeypatch, ready):
    m = session_module
    s = m.WarehouseQualificationSession(tmp_path / "session", Path("/unused"), "navfn_rpp")
    ticks = iter([i * 0.1 for i in range(20)])
    monkeypatch.setattr(m.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(pytest.importorskip("rclpy"), "spin_once", lambda *a, **k: None)
    s.node = object()
    monkeypatch.setattr(s, "capture_logs", lambda: None)
    s.readiness_established = ready
    monkeypatch.setattr(s, "readiness", lambda: False)
    with pytest.raises((RuntimeError, AssertionError), match="readiness lost|offline deadline"):
        s.wait(lambda: False, "offline deadline", 0.5)
    s.journal.close()


@pytest.mark.parametrize(
    "mutation", [None, "map", "parameters", "covariance", "start", "route", "consumer"]
)
def test_concrete_dispatch_gates_with_ros_message_fixtures(
    prepared, tmp_path, monkeypatch, mutation
):
    pytest.importorskip("rclpy")
    from ament_index_python.packages import get_package_share_directory
    from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped
    from nav_msgs.msg import OccupancyGrid
    from robot_navigation.navigation_config import navigation_parameters

    root, _, plan = prepared
    pp = tmp_path / "plan.json"
    pp.write_text(json.dumps(plan))
    a = runtime.QualificationRuntime(ROOT, "navfn_rpp", pp, tmp_path / "permission.json")
    a.matrix = json.loads((ROOT / "benchmarks/warehouse_v1/matrix.json").read_text())
    a.descriptor = json.loads((ROOT / a.matrix["scenario"]["descriptor"]["path"]).read_text())
    spec = a.descriptor["map"]
    width, height = spec["width"], spec["height"]
    image = (ROOT / a.matrix["scenario"]["map_image"]["path"]).read_bytes().split(b"\n", 3)[3]
    grid = OccupancyGrid()
    grid.header.frame_id = "map"
    grid.info.width = width
    grid.info.height = height
    grid.info.resolution = spec["resolution_m"]
    grid.info.origin.position.x = spec["origin_m"][0]
    grid.info.origin.position.y = spec["origin_m"][1]
    grid.info.origin.orientation.w = 1.0
    grid.data = [
        100 if image[(height - 1 - y) * width + x] == 0 else 0
        for y in range(height)
        for x in range(width)
    ]
    pose = PoseWithCovarianceStamped()
    pose.header.stamp.sec = 2
    tf = TransformStamped()
    tf.transform.rotation.w = 1.0
    if mutation == "map":
        grid.data[0] = 50
    if mutation == "start":
        tf.transform.translation.x = 1.0
    if mutation == "covariance":
        pose.pose.covariance[0] = 0.3
    maps = ROOT / a.matrix["scenario"]["map_yaml"]["path"]
    publisher = SimpleNamespace(node_name="ordinary_scan")

    def pubs(topic):
        return [publisher] if topic == "/scan" else []

    node = SimpleNamespace(
        get_node_names=lambda: ["amcl", "local_costmap", "global_costmap"],
        get_publishers_info_by_topic=pubs,
        get_subscriptions_info_by_topic=lambda topic: [
            SimpleNamespace(node_name=n) for n in ["amcl", "local_costmap", "global_costmap"]
        ],
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=2_000_000_000)),
    )
    if mutation == "route":
        node.get_publishers_info_by_topic = lambda topic: [publisher, publisher]
    j = BufferedJournal(tmp_path / "gate-journal.jsonl")
    s = SimpleNamespace(
        node=node,
        journal=j,
        map_file=maps,
        maps=[grid],
        poses=[pose],
        buffer=SimpleNamespace(lookup_transform=lambda *args: tf),
        truth_pose=lambda: tf.transform,
        readiness=lambda: True,
        validate_tf_publishers=lambda: None,
        consumer_receipts_ready=lambda: mutation != "consumer",
        sampled_topics={"/local_costmap/costmap", "/global_costmap/costmap"},
    )

    def wait(predicate, reason, timeout=60):
        if not predicate():
            raise RuntimeError(reason)

    s.wait = wait
    a.session = s
    expected = navigation_parameters(
        Path(get_package_share_directory("robot_navigation")) / "config",
        "navfn_rpp",
        Path(get_package_share_directory("robot_description")) / "config/geometry.yaml",
        True,
    )
    flattened = {}
    for name, values in expected.items():
        if name in ("local_costmap", "global_costmap"):
            values = values[name]
            name = f"{name}/{name}"
        flattened[name] = runtime.flatten(values["ros__parameters"])

    def params(name, names):
        if names == ["yaml_filename"]:
            return {"yaml_filename": str(maps)}
        if mutation == "parameters":
            return {}
        return flattened[name]

    monkeypatch.setattr(a, "params", params)
    try:
        if mutation:
            with pytest.raises(RuntimeError):
                a.gates()
        else:
            assert all(a.gates().values())
    finally:
        assert j.close()["complete"]


@pytest.mark.parametrize(
    "observation_error,timeout", [(False, False), (True, False), (False, True)]
)
def test_cancellation_pumps_observations_and_keeps_deadline(observation_error, timeout):
    calls = []
    ticks = iter([0, 1, 36] if timeout else [0, 1, 2, 3])
    journal = SimpleNamespace(submit=lambda *a, **k: True)

    class Child:
        pid = 123

        def __init__(self):
            self.code = None
            self.waits = 0

        def poll(self):
            return self.code

        def send_signal(self, sig):
            calls.append("sigint")

        def wait(self, timeout):
            self.waits += 1
            if timeout == 5 or (self.waits >= 2 and not timeout == 0.1):
                self.code = 0
                return
            if self.waits == 1:
                raise subprocess.TimeoutExpired("fixture", timeout)
            self.code = 0

    def pump():
        calls.append("observe")
        if observation_error:
            raise RuntimeError("observation failed")

    clean = runtime.stop_runner(
        Child(),
        journal,
        pump=pump,
        clock=lambda: next(ticks),
        killpg=lambda *args: calls.append("kill"),
    )
    assert clean == (not observation_error and not timeout)
    assert calls[:2] == ["sigint", "observe"]
    assert ("kill" in calls) == timeout


@pytest.mark.parametrize(
    "mutation",
    [
        "qualified",
        "original",
        "runner_clean",
        "critical_lifecycle_complete",
        "two_stream_readback_complete",
        "cleanup_no_exception",
        "observer_and_cleanup_complete",
        "recording_integrity_and_original_immutability",
        "no_remaining_robotics_processes",
        "missing_shutdown_gate",
        "old_set",
        "plan",
        "claim",
        "history",
    ],
)
def test_smac_refuses_incomplete_or_mismatched_navfn(prepared, mutation):
    root, _, plan = prepared
    execute(prepared, FakeRuntime())
    directory = root / "artifacts" / driver.ATTEMPT_SET
    result_path = directory / "navfn_rpp-result.json"
    first = json.loads(result_path.read_text())
    if mutation == "qualified":
        first["qualified"] = False
    elif mutation == "original":
        first["original_result"]["trials"][0]["validation"]["verdict"] = "INCONCLUSIVE"
    elif mutation == "missing_shutdown_gate":
        first["shutdown"].pop("two_stream_readback_complete")
    elif mutation == "old_set":
        first["attempt_set"] = "warehouse-w3-requalification-v1"
    elif mutation == "plan":
        first["plan_sha256"] = "b" * 64
    elif mutation == "claim":
        (directory / "navfn_rpp.claim.json").write_text("{}")
    elif mutation == "history":
        (root / driver.HISTORICAL_CLAIMS[-1]).write_text("changed fixture")
    else:
        first["shutdown"][mutation] = False
    result_path.write_text(json.dumps(first))
    fake = FakeRuntime()
    with pytest.raises(RuntimeError):
        execute(prepared, fake, "smac_dwb")
    assert not fake.calls
    assert not (directory / "smac_dwb.claim.json").exists()


@pytest.mark.parametrize("missing", [False, True])
def test_adapter_close_requires_actual_two_stream_files(prepared, tmp_path, monkeypatch, missing):
    root, _, plan = prepared
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    adapter = runtime.QualificationRuntime(root, "navfn_rpp", plan_path, tmp_path / "none")
    adapter.directory.mkdir(parents=True)

    def close(*args):
        (adapter.directory / "observer-shutdown.json").write_text(
            json.dumps(
                {
                    "observer_and_cleanup_complete": True,
                    "evidence": {"complete": True},
                    "critical_lifecycle": {"complete": True},
                }
            )
        )
        if not missing:
            (adapter.directory / "observations.jsonl").write_text("{}\n")
            (adapter.directory / "observations.jsonl.lifecycle.jsonl").write_text("{}\n")

    adapter.session = SimpleNamespace(
        journal=SimpleNamespace(submit=lambda *a, **k: True), __exit__=close
    )
    monkeypatch.setattr(runtime, "stop_runner", lambda *a, **k: True)
    monkeypatch.setattr(runtime, "robotics_processes", lambda: [])
    result = adapter.close(None)
    assert not result["two_stream_readback_complete"]
    saved = json.loads((adapter.directory / "two-stream-verification.json").read_text())
    assert not saved["complete"] and saved["error"]


@pytest.mark.parametrize("failure", ["tf", "contact", "scan", "amcl"])
def test_readiness_reports_exact_predicate_and_measurement(
    session_module, tmp_path, monkeypatch, failure
):
    m = session_module
    s = m.WarehouseQualificationSession(tmp_path / "session", Path("/unused"), "navfn_rpp")
    ns = 10**9
    monkeypatch.setattr(m.time, "monotonic_ns", lambda: 8 * ns)
    s.node = SimpleNamespace(
        get_clock=lambda: SimpleNamespace(now=lambda: SimpleNamespace(nanoseconds=8 * ns))
    )
    s.buffer = SimpleNamespace(can_transform=lambda *a: False)
    monkeypatch.setattr(
        s.observer,
        "assess_tf",
        lambda *a: {
            "ready": failure != "tf",
            "max_tf_age_ns": ns,
            "buffer_age_ns": 2 * ns if failure == "tf" else 0,
        },
    )
    monkeypatch.setattr(s.observer, "ready", lambda *a: failure != "contact")
    s.observer.last_contact_receipt_ns = 8 * ns if failure != "contact" else 7 * ns
    s.last_scan_stamp = 8 * ns
    s.last_scan_change_mono = 8 * ns if failure != "scan" else 4 * ns
    for tick in range(10, 81):
        for name in ("odom", "truth"):
            s.localisation.observe(name, tick * ns // 10, tick * ns // 10, 0.0, 0.0, 0.0, 0.0, 0.0)
        if tick == 30:
            s.localisation.arm(3 * ns, 3 * ns, ns, [0.04] * 3)
    pose = m.PoseWithCovarianceStamped()
    pose.header.frame_id = "map"
    pose.header.stamp.sec = 1
    pose.pose.pose.orientation.w = 1.0
    pose.pose.covariance[0] = pose.pose.covariance[7] = pose.pose.covariance[35] = 0.04
    if failure == "amcl":
        pose.pose.covariance[0] = 0.3
    s.poses.append(pose)
    s.readiness_established = True
    with pytest.raises(RuntimeError, match="Established readiness lost"):
        s.require_readiness()
    expected = {
        "tf": "tf.readiness",
        "contact": "contact.coverage_or_silence",
        "scan": "sensor.scan_stamp_not_advancing",
        "amcl": "amcl.covariance_invalid",
    }
    assert expected[failure] in s.last_readiness["causes"]
    assert s.last_readiness["now_ros_ns"] == 8 * ns
    assert s.last_readiness["localisation"]["pose_stamp_ns"] == ns
    assert s.last_readiness["tf"]["max_tf_age_ns"] == ns
    assert s.journal.close()["complete"]
    rows = [
        json.loads(line) for line in (s.directory / "observations.jsonl").read_text().splitlines()
    ]
    assert rows[-1]["kind"] == "readiness_assessment"
    assert rows[-1]["causes"] == s.last_readiness["causes"]


@pytest.mark.parametrize(
    "old_set",
    [
        None,
        "warehouse-w3-requalification-v1",
        "warehouse-w3-requalification-v2",
        "warehouse-w3-requalification-v3",
    ],
)
def test_consumed_or_unbound_contract_cannot_start(prepared, old_set):
    root, owner, plan = prepared
    plan["attempt_set"] = old_set
    fake = FakeRuntime()
    with pytest.raises(RuntimeError):
        driver.execute(root, "navfn_rpp", owner, fake, plan)
    assert not fake.calls
    assert not (root / "artifacts" / driver.ATTEMPT_SET / "navfn_rpp.claim.json").exists()


def test_v2_consumed_claim_is_mandatory_history(prepared):
    _, _, plan = prepared
    assert driver.ATTEMPT_SET == "warehouse-w3-requalification-v4"
    plan["historical_claims"].pop("artifacts/warehouse-w3-requalification-v2/navfn_rpp.claim.json")
    with pytest.raises(RuntimeError, match="Fresh attempt-set"):
        driver.validate_contract(plan)


def test_missing_permission_stops_before_any_runtime(prepared, tmp_path):
    root, _, plan = prepared
    pp = tmp_path / "review-plan.json"
    pp.write_text(json.dumps(plan))
    adapter = runtime.QualificationRuntime(
        root, "navfn_rpp", pp, tmp_path / "absent-permission.json"
    )
    with pytest.raises(FileNotFoundError):
        adapter.preflight()
    assert not adapter.directory.exists()
