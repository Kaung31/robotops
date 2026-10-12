from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from robotops_backend.models import StackMode, StackRequest
from robotops_backend.orchestrator import StackOrchestrator


def test_wrapped_launch_matches_owned_child_and_exact_command(tmp_path, monkeypatch):
    import robotops_backend.orchestrator as module

    proc = tmp_path / "proc"
    children = proc / "44/task/44/children"
    children.parent.mkdir(parents=True)
    children.write_text("45 46")
    for pid in (45, 46):
        (proc / str(pid)).mkdir()
    (proc / "45/cmdline").write_bytes(b"Xvfb\0:99\0")
    command = ["ros2", "launch", "robot_bringup", "robot.launch.py", "mode:=sim"]
    (proc / "46/cmdline").write_bytes(
        b"/usr/bin/python3\0/opt/ros/jazzy/bin/ros2\0"
        + b"\0".join(os_arg.encode() for os_arg in command[1:])
        + b"\0"
    )
    (proc / "46/stat").write_text("46 (python3) " + " ".join(["S", "44", *(["0"] * 17), "123"]))

    def path(value):
        text = str(value)
        return proc / text.removeprefix("/proc/") if text.startswith("/proc/") else Path(value)

    monkeypatch.setattr(module, "Path", path)
    assert StackOrchestrator._wrapped_launch_child(44, command) == (46, 123)
    assert StackOrchestrator._wrapped_launch_child(44, [*command[:-1], "mode:=mock"]) is None
    (proc / "46/stat").write_text("46 (python3) " + " ".join(["S", "99", *(["0"] * 17), "123"]))
    assert StackOrchestrator._wrapped_launch_child(44, command) is None


@pytest.mark.parametrize("identity", [(44, 123), (44, 124), (99, 123), None])
def test_wrapped_shutdown_guards_parent_and_start_time(tmp_path, monkeypatch, identity):
    import robotops_backend.orchestrator as module

    orchestrator = StackOrchestrator(tmp_path)
    item = module._ManagedProcess("robot", SimpleNamespace(pid=44), None, tmp_path, 46, 123)
    monkeypatch.setattr(orchestrator, "_process_identity", lambda _pid: identity)
    signals = []
    monkeypatch.setattr(module.os, "kill", lambda pid, _sig: signals.append(("child", pid)))
    monkeypatch.setattr(module.os, "killpg", lambda pid, _sig: signals.append(("group", pid)))
    orchestrator._interrupt_managed(item)
    assert signals == ([("child", 46)] if identity == (44, 123) else [("group", 44)])


def write_map(root: Path, name: str = "lab") -> None:
    maps = root / "artifacts" / "maps"
    maps.mkdir(parents=True, exist_ok=True)
    (maps / f"{name}.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
    (maps / f"{name}.yaml").write_text(
        yaml.safe_dump(
            {
                "image": f"{name}.pgm",
                "resolution": 0.05,
                "origin": [0.0, 0.0, 0.0],
                "negate": 0,
                "occupied_thresh": 0.65,
                "free_thresh": 0.25,
            }
        ),
        encoding="utf-8",
    )


def test_options_discover_only_maps_with_images(tmp_path):
    write_map(tmp_path, "lab")
    maps = tmp_path / "artifacts" / "maps"
    (maps / "broken.yaml").write_text("image: absent.pgm\n", encoding="utf-8")
    orchestrator = StackOrchestrator(tmp_path)
    options = orchestrator.options()
    assert [item.id for item in options.maps] == ["lab"]
    assert {item.id for item in options.navigation_profiles} == {"navfn_rpp", "smac_dwb"}


def test_navigation_requires_approved_saved_map(tmp_path):
    orchestrator = StackOrchestrator(tmp_path)
    request = StackRequest(
        mode=StackMode.NAVIGATION,
        world="mapping_lab",
        map_id="../../etc/passwd",
        navigation_profile="navfn_rpp",
    )
    try:
        orchestrator.start(request)
    except ValueError as exc:
        assert "Unknown or invalid saved map" in str(exc)
    else:
        raise AssertionError("unapproved map path was accepted")


def test_commands_are_fixed_ros_launch_arguments(tmp_path):
    write_map(tmp_path)
    orchestrator = StackOrchestrator(tmp_path)
    request = StackRequest(
        mode=StackMode.NAVIGATION,
        world="mapping_lab",
        map_id="lab",
        navigation_profile="smac_dwb",
        headless_rendering=True,
    )
    map_path = orchestrator._resolve_map("lab")
    commands = orchestrator._commands(request, map_path)
    names = [item[0] for item in commands]
    assert names == ["robot", "navigation", "mission"]
    navigation = commands[1][1]
    assert "profile:=smac_dwb" in navigation
    assert f"map_file:={map_path}" in navigation
    assert "autostart:=true" in navigation
    mission = commands[2][1]
    assert "environment:=mapping_lab" in mission
    assert "navigation_profile:=smac_dwb" in mission
    assert f"map_file:={map_path}" in mission
    assert all(";" not in arg for _, command, _ in commands for arg in command)


def test_map_world_metadata_filters_mismatched_navigation(tmp_path):
    write_map(tmp_path, "lab")
    metadata = tmp_path / "artifacts" / "maps" / "lab.robotops.json"
    metadata.write_text('{"world_id": "mapping_lab"}\n', encoding="utf-8")
    orchestrator = StackOrchestrator(tmp_path)
    artifact = orchestrator.options().maps[0]
    assert artifact.world_id == "mapping_lab"
    try:
        orchestrator._resolve_map("lab", "control_pad")
    except ValueError as exc:
        assert "belongs to world 'mapping_lab'" in str(exc)
    else:
        raise AssertionError("map/world mismatch was accepted")


def test_legacy_map_without_world_metadata_remains_selectable(tmp_path):
    write_map(tmp_path, "legacy")
    orchestrator = StackOrchestrator(tmp_path)
    artifact = orchestrator.options().maps[0]
    assert artifact.world_id is None
    assert orchestrator._resolve_map("legacy", "control_pad").name == "legacy.yaml"


def test_map_library_exposes_metadata_latest_and_preview(tmp_path):
    import json

    write_map(tmp_path, "mapping_lab_v1")
    write_map(tmp_path, "mapping_lab_v2")
    maps = tmp_path / "artifacts" / "maps"
    (maps / "mapping_lab_v1.robotops.json").write_text(
        json.dumps({"world_id": "mapping_lab", "created_at_ns": "100"}), encoding="utf-8"
    )
    (maps / "mapping_lab_v2.robotops.json").write_text(
        json.dumps({"world_id": "mapping_lab", "created_at_ns": "200"}), encoding="utf-8"
    )

    orchestrator = StackOrchestrator(tmp_path)
    options = orchestrator.options()
    relevant = [item for item in options.maps if item.world_id == "mapping_lab"]
    assert [item.id for item in relevant] == ["mapping_lab_v2", "mapping_lab_v1"]
    assert relevant[0].is_latest is True
    assert relevant[1].is_latest is False
    assert relevant[0].resolution == 0.05
    assert relevant[0].width == 1
    assert relevant[0].height == 1
    assert relevant[0].preview_url == "/api/v1/maps/mapping_lab_v2/preview.svg"

    preview = orchestrator.map_preview_svg("mapping_lab_v2")
    assert preview.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "<rect" in preview


def test_legacy_map_stays_unassociated(tmp_path):
    write_map(tmp_path, "legacy")
    orchestrator = StackOrchestrator(tmp_path)
    artifact = next(item for item in orchestrator.options().maps if item.id == "legacy")
    assert artifact.world_id is None
    assert artifact.created_at_ns is not None


def test_stale_metadata_cannot_override_real_map_geometry(tmp_path):
    import json

    write_map(tmp_path, "lab")
    maps = tmp_path / "artifacts" / "maps"
    (maps / "lab.robotops.json").write_text(
        json.dumps(
            {
                "world_id": "mapping_lab",
                "created_at_ns": "200",
                "resolution": 9.9,
                "width": 999,
                "height": 888,
            }
        ),
        encoding="utf-8",
    )

    artifact = StackOrchestrator(tmp_path).options().maps[0]
    assert artifact.resolution == 0.05
    assert artifact.width == 1
    assert artifact.height == 1


def test_map_image_cannot_escape_approved_maps_directory(tmp_path):
    maps = tmp_path / "artifacts" / "maps"
    maps.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.pgm"
    outside.write_bytes(b"P5\n1 1\n255\n\xff")
    (maps / "escape.yaml").write_text(
        yaml.safe_dump(
            {
                "image": "../../outside.pgm",
                "resolution": 0.05,
                "origin": [0.0, 0.0, 0.0],
            }
        ),
        encoding="utf-8",
    )

    options = StackOrchestrator(tmp_path).options()
    assert all(item.id != "escape" for item in options.maps)


def test_navigation_launch_uses_one_ordered_nav2_lifecycle_manager():
    repo_root = Path(__file__).resolve().parents[2]
    source = (
        repo_root / "ros2_ws" / "src" / "robot_navigation" / "launch" / "navigation.launch.py"
    ).read_text(encoding="utf-8")
    assert 'name="lifecycle_manager_nav2"' in source
    assert '"node_names": lifecycle_nodes' in source
    assert 'lifecycle_nodes = ["map_server", "amcl", *nav_servers.keys()]' in source
    assert 'name="map_lifecycle_manager"' not in source
    assert 'name="navigation_lifecycle_manager"' not in source
    assert "IncludeLaunchDescription" not in source


def test_rviz_engineering_view_uses_mode_specific_config(tmp_path, monkeypatch):
    from robotops_backend.models import StackState, StackStatus

    rviz_dir = tmp_path / "ros2_ws" / "src" / "robot_navigation" / "rviz"
    rviz_dir.mkdir(parents=True)
    config = rviz_dir / "navigation.rviz"
    config.write_text("Visualization Manager: {}\n", encoding="utf-8")

    launched: list[list[str]] = []

    class FakeProcess:
        pid = 999999
        returncode = None

        def poll(self):
            return None

    def fake_popen(command, **_kwargs):
        launched.append(command)
        return FakeProcess()

    monkeypatch.setattr(
        "robotops_backend.orchestrator.shutil.which", lambda _name: "/usr/bin/ros2"
    )
    monkeypatch.setattr("robotops_backend.orchestrator.subprocess.Popen", fake_popen)
    monkeypatch.setattr("robotops_backend.orchestrator.time.sleep", lambda _seconds: None)

    orchestrator = StackOrchestrator(tmp_path)
    orchestrator._status = StackStatus(state=StackState.RUNNING, mode=StackMode.NAVIGATION)
    status = orchestrator.open_rviz()

    assert status.rviz_running is True
    assert launched
    assert launched[0][:4] == ["ros2", "run", "rviz2", "rviz2"]
    assert str(config) in launched[0]
    assert "use_sim_time:=true" in launched[0]
    assert orchestrator._rviz is not None
    orchestrator._rviz.log_handle.close()


def test_rviz_configs_include_robot_model_and_navigation_debug_views():
    repo_root = Path(__file__).resolve().parents[2]
    rviz_dir = repo_root / "ros2_ws" / "src" / "robot_navigation" / "rviz"
    mapping = (rviz_dir / "mapping.rviz").read_text(encoding="utf-8")
    navigation = (rviz_dir / "navigation.rviz").read_text(encoding="utf-8")

    for config in (mapping, navigation):
        assert "rviz_default_plugins/RobotModel" in config
        assert "/robot_description" in config
        assert "rviz_default_plugins/TF" in config
        assert "/scan" in config
        assert "/map" in config

    assert "/plan" in navigation
    assert "/global_costmap/costmap" in navigation
    assert "/local_costmap/costmap" in navigation
    assert "/local_costmap/published_footprint" in navigation


def test_navigation_launch_rviz_argument_starts_navigation_debug_config():
    repo_root = Path(__file__).resolve().parents[2]
    source = (
        repo_root / "ros2_ws" / "src" / "robot_navigation" / "launch" / "navigation.launch.py"
    ).read_text(encoding="utf-8")
    assert 'package="rviz2"' in source
    assert '"rviz/navigation.rviz"' in source
    assert 'condition=IfCondition(LaunchConfiguration("rviz"))' in source


def test_core_stack_failure_closes_robotops_managed_rviz(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from robotops_backend.models import StackState, StackStatus

    class ExitedProcess:
        returncode = 7

        def poll(self):
            return 7

    orchestrator = StackOrchestrator(tmp_path)
    orchestrator._status = StackStatus(state=StackState.RUNNING, mode=StackMode.NAVIGATION)
    orchestrator._processes = {
        "robot": SimpleNamespace(
            name="robot",
            process=ExitedProcess(),
            log_path=tmp_path / "artifacts" / "logs" / "orchestrator" / "robot.log",
        )
    }

    cleanup_calls: list[str] = []
    monkeypatch.setattr("robotops_backend.orchestrator.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(orchestrator, "_stop_rviz_locked", lambda: cleanup_calls.append("rviz"))
    monkeypatch.setattr(
        orchestrator,
        "_stop_locked",
        lambda: (cleanup_calls.append("stack"), orchestrator._processes.clear()),
    )

    orchestrator._monitor_processes()

    assert orchestrator._status.state == StackState.FAILED
    assert cleanup_calls == ["rviz", "stack"]


def test_direct_launch_interrupt_reaches_child_once(tmp_path):
    """A group signal plus launch forwarding must not double-interrupt children."""
    import json
    import subprocess
    import sys
    import time

    from robotops_backend.orchestrator import _ManagedProcess

    child = tmp_path / "child.py"
    child.write_text("""import json, signal, sys, time
from pathlib import Path
root = Path(sys.argv[1])
count = 0
deadline = None
def interrupt(*_):
    global count, deadline
    count += 1
    if deadline is None:
        deadline = time.monotonic() + 0.3
signal.signal(signal.SIGINT, interrupt)
(root / "child-ready").touch()
while deadline is None or time.monotonic() < deadline:
    time.sleep(0.01)
(root / "interrupts.json").write_text(json.dumps(count))
""")
    parent = tmp_path / "launch.py"
    parent.write_text("""import signal, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
child = subprocess.Popen([sys.executable, str(root / "child.py"), str(root)])
def interrupt(*_):
    time.sleep(0.05)
    child.send_signal(signal.SIGINT)
signal.signal(signal.SIGINT, interrupt)
while not (root / "child-ready").exists():
    time.sleep(0.01)
(root / "launch-ready").touch()
sys.exit(child.wait())
""")
    with (tmp_path / "launch.log").open("w") as log:
        process = subprocess.Popen(
            [sys.executable, str(parent), str(tmp_path)],
            start_new_session=True,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        item = _ManagedProcess("navigation", process, log, tmp_path / "launch.log")
        item.direct_ros_launch = True
        try:
            deadline = time.monotonic() + 10
            while not (tmp_path / "launch-ready").exists():
                assert process.poll() is None
                assert time.monotonic() < deadline
                time.sleep(0.01)
            StackOrchestrator(tmp_path)._interrupt_managed(item)
            assert process.wait(timeout=5) == 0
            assert json.loads((tmp_path / "interrupts.json").read_text()) == 1
        finally:
            if process.poll() is None:
                import os
                import signal

                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


@pytest.mark.parametrize(
    "command,expected",
    [
        (["ros2", "launch", "robot_navigation", "navigation.launch.py"], True),
        (["ros2", "run", "rviz2", "rviz2"], False),
    ],
)
def test_only_direct_ros_launch_uses_single_forwarded_interrupt(
    tmp_path, monkeypatch, command, expected
):
    import robotops_backend.orchestrator as module

    orchestrator = StackOrchestrator(tmp_path)
    orchestrator.logs_dir = tmp_path
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(pid=44)
    )
    orchestrator._start_process_locked("navigation", command, {})
    item = orchestrator._processes["navigation"]
    assert item.direct_ros_launch is expected
    item.log_handle.close()
