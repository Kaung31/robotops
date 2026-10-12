from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .models import (
    ControlOptions,
    MapArtifact,
    MapSaveRequest,
    MapSaveResult,
    NavigationProfile,
    StackMode,
    StackRequest,
    StackState,
    StackStatus,
    WorldOption,
)

_MAP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass
class _ManagedProcess:
    name: str
    process: subprocess.Popen
    log_handle: object
    log_path: Path
    wrapped_launch_pid: int | None = None
    wrapped_launch_start: int | None = None
    direct_ros_launch: bool = False


class StackOrchestrator:
    """Own approved RobotOps launch processes without exposing arbitrary shell execution."""

    WORLDS = (
        WorldOption(id="control_pad", label="Control Pad", difficulty="easy"),
        WorldOption(id="mapping_lab", label="Mapping Lab", difficulty="medium"),
        WorldOption(id="warehouse_v1", label="Warehouse v1 (unqualified)", difficulty="medium"),
    )
    SIM_SPAWNS = {
        "control_pad": (0.0, 0.0, 0.0),
        "mapping_lab": (0.0, 0.0, 0.0),
        "warehouse_v1": (0.0, 0.0, 0.0),
    }
    NAVIGATION_PROFILES = (
        NavigationProfile(
            id="navfn_rpp",
            label="NavFn + Regulated Pure Pursuit",
            planner="NavFn / Dijkstra",
            controller="Regulated Pure Pursuit",
        ),
        NavigationProfile(
            id="smac_dwb",
            label="Smac 2D + DWB",
            planner="Smac 2D / A*",
            controller="Dynamic Window Approach (DWB)",
        ),
    )

    def __init__(self, repo_root: Path | None = None):
        default_root = Path(__file__).resolve().parents[2]
        self.repo_root = Path(
            os.getenv("ROBOTOPS_REPO_ROOT", str(repo_root or default_root))
        ).resolve()
        self.maps_dir = self.repo_root / "artifacts" / "maps"
        self.logs_dir = self.repo_root / "artifacts" / "logs" / "orchestrator"
        self._lock = threading.RLock()
        self._processes: dict[str, _ManagedProcess] = {}
        self._rviz: _ManagedProcess | None = None
        self._status = StackStatus()
        self._monitor: threading.Thread | None = None
        self._stop_requested = False

    def options(self) -> ControlOptions:
        return ControlOptions(
            worlds=list(self.WORLDS),
            navigation_profiles=list(self.NAVIGATION_PROFILES),
            maps=self._discover_maps(),
        )

    def status(self) -> StackStatus:
        with self._lock:
            self._refresh_locked()
            return self._status.model_copy(deep=True)

    def start(self, request: StackRequest) -> StackStatus:
        if request.runtime_mode != "sim":
            raise ValueError("Milestone 7B orchestration currently supports simulation only")
        if request.world not in {world.id for world in self.WORLDS}:
            raise ValueError(f"Unknown world '{request.world}'")
        if request.mode == StackMode.NAVIGATION:
            if request.navigation_profile not in {
                profile.id for profile in self.NAVIGATION_PROFILES
            }:
                raise ValueError("A valid navigation profile is required")
            map_path = self._resolve_map(request.map_id, request.world)
        else:
            map_path = None

        with self._lock:
            self._refresh_locked()
            if self._status.state in (
                StackState.STARTING,
                StackState.RUNNING,
                StackState.STOPPING,
            ):
                raise RuntimeError("RobotOps stack is already active")
            self._stop_requested = False
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            self._status = StackStatus(
                state=StackState.STARTING,
                mode=request.mode,
                runtime_mode=request.runtime_mode,
                world=request.world,
                map_id=request.map_id if request.mode == StackMode.NAVIGATION else None,
                navigation_profile=(
                    request.navigation_profile if request.mode == StackMode.NAVIGATION else None
                ),
                started_at_ns=str(time.time_ns()),
            )

            commands = self._commands(request, map_path)
            started: list[str] = []
            try:
                for name, command, env in commands:
                    self._start_process_locked(name, command, env)
                    started.append(name)
                    # Fail early for launch/configuration errors while keeping startup bounded.
                    time.sleep(0.35)
                    proc = self._processes[name].process
                    if proc.poll() is not None:
                        raise RuntimeError(
                            f"{name} exited during startup with code {proc.returncode}; "
                            f"see {self._processes[name].log_path}"
                        )
            except Exception as exc:
                self._status.state = StackState.FAILED
                self._status.error = str(exc)
                self._stop_locked()
                raise

            self._status.state = StackState.RUNNING
            self._status.processes = started
            self._monitor = threading.Thread(target=self._monitor_processes, daemon=True)
            self._monitor.start()
            if request.open_rviz:
                try:
                    self._open_rviz_locked(request.mode)
                except RuntimeError as exc:
                    # RViz is an optional engineering view. A GUI failure must not
                    # tear down an otherwise healthy robot/navigation stack.
                    self._status.rviz_error = str(exc)
            return self._status.model_copy(deep=True)

    def stop(self) -> StackStatus:
        with self._lock:
            self._refresh_locked()
            self._stop_rviz_locked()
            if not self._processes:
                self._status.state = StackState.STOPPED
                self._status.processes = []
                self._status.stopped_at_ns = str(time.time_ns())
                return self._status.model_copy(deep=True)
            self._stop_requested = True
            self._status.state = StackState.STOPPING
            self._stop_locked()
            self._status.state = StackState.STOPPED
            self._status.processes = []
            self._status.stopped_at_ns = str(time.time_ns())
            return self._status.model_copy(deep=True)

    def open_rviz(self) -> StackStatus:
        with self._lock:
            self._refresh_locked()
            if self._status.state != StackState.RUNNING or self._status.mode is None:
                raise RuntimeError("A running RobotOps stack is required before opening RViz")
            self._open_rviz_locked(self._status.mode)
            return self._status.model_copy(deep=True)

    def close_rviz(self) -> StackStatus:
        with self._lock:
            self._refresh_locked()
            self._stop_rviz_locked()
            return self._status.model_copy(deep=True)

    def save_map(self, request: MapSaveRequest) -> MapSaveResult:
        with self._lock:
            self._refresh_locked()
            if self._status.state != StackState.RUNNING or self._status.mode != StackMode.MAPPING:
                raise RuntimeError("A running mapping stack is required before saving a map")
        if not _MAP_NAME.fullmatch(request.name):
            raise ValueError(
                "Map name must use letters, numbers, '_' or '-' and be at most 64 chars"
            )
        self.maps_dir.mkdir(parents=True, exist_ok=True)
        prefix = (self.maps_dir / request.name).resolve()
        if prefix.parent != self.maps_dir.resolve():
            raise ValueError("Invalid map path")
        yaml_path = prefix.with_suffix(".yaml")
        image_path = prefix.with_suffix(".pgm")
        if (yaml_path.exists() or image_path.exists()) and not request.overwrite:
            raise FileExistsError(f"Map '{request.name}' already exists")

        command = [
            "ros2",
            "run",
            "nav2_map_server",
            "map_saver_cli",
            "-f",
            str(prefix),
            "--ros-args",
            "-p",
            "use_sim_time:=true",
            "-p",
            "save_map_timeout:=10.0",
        ]
        try:
            result = subprocess.run(
                command,
                cwd=self.repo_root,
                env=os.environ.copy(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Map save timed out") from exc
        if result.returncode != 0 or not yaml_path.is_file() or not image_path.is_file():
            raise RuntimeError(
                "Map save failed" + (f": {result.stdout.strip()}" if result.stdout else "")
            )
        world_id = self.status().world
        created_at_ns = str(time.time_ns())
        map_info = self._read_map_info(yaml_path)
        metadata_path = prefix.with_suffix(".robotops.json")
        metadata_path.write_text(
            json.dumps(
                {
                    "world_id": world_id,
                    "created_at_ns": created_at_ns,
                    "resolution": map_info.get("resolution"),
                    "width": map_info.get("width"),
                    "height": map_info.get("height"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        artifact = self._artifact_from_yaml(yaml_path)
        if artifact is None:
            raise RuntimeError("Map saved but metadata could not be reloaded")
        artifact.is_latest = True
        return MapSaveResult(map=artifact, message="Map saved")

    def close(self) -> None:
        try:
            self.stop()
        except Exception:
            pass

    def _open_rviz_locked(self, mode: StackMode) -> None:
        self._refresh_rviz_locked()
        if self._rviz is not None and self._rviz.process.poll() is None:
            self._status.rviz_running = True
            self._status.rviz_error = None
            return

        config_name = "navigation.rviz" if mode == StackMode.NAVIGATION else "mapping.rviz"
        config_path = (
            self.repo_root / "ros2_ws" / "src" / "robot_navigation" / "rviz" / config_name
        )
        if not config_path.is_file():
            raise RuntimeError(f"RViz configuration is missing: {config_path}")
        if shutil.which("ros2") is None:
            raise RuntimeError("ROS 2 is not available in the backend environment")

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.logs_dir / f"{int(time.time())}-rviz.log"
        handle = log_path.open("a", encoding="utf-8")
        command = [
            "ros2",
            "run",
            "rviz2",
            "rviz2",
            "-d",
            str(config_path),
            "--ros-args",
            "-p",
            "use_sim_time:=true",
        ]
        try:
            process = subprocess.Popen(
                command,
                cwd=self.repo_root,
                env=os.environ.copy(),
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
        except Exception as exc:
            handle.close()
            raise RuntimeError(f"Could not start RViz: {exc}") from exc

        self._rviz = _ManagedProcess("rviz", process, handle, log_path)
        # Catch immediate display/plugin/configuration errors without delaying stack bringup.
        time.sleep(0.25)
        if process.poll() is not None:
            code = process.returncode
            handle.close()
            self._rviz = None
            self._status.rviz_running = False
            raise RuntimeError(
                f"RViz exited during startup with code {code}; "
                f"see {log_path.relative_to(self.repo_root)}"
            )
        self._status.rviz_running = True
        self._status.rviz_error = None

    def _refresh_rviz_locked(self) -> None:
        if self._rviz is None:
            self._status.rviz_running = False
            return
        code = self._rviz.process.poll()
        if code is None:
            self._status.rviz_running = True
            return
        log_path = self._rviz.log_path
        self._rviz.log_handle.close()
        self._rviz = None
        self._status.rviz_running = False
        if code != 0:
            self._status.rviz_error = (
                f"RViz exited with code {code}; see {log_path.relative_to(self.repo_root)}"
            )

    def _stop_rviz_locked(self) -> None:
        if self._rviz is None:
            self._status.rviz_running = False
            return
        item = self._rviz
        if item.process.poll() is None:
            try:
                os.killpg(item.process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            try:
                item.process.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(item.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    item.process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(item.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        item.process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
        item.log_handle.close()
        self._rviz = None
        self._status.rviz_running = False
        self._status.rviz_error = None

    def _commands(self, request: StackRequest, map_path: Path | None):
        robot_cmd = [
            "ros2",
            "launch",
            "robot_bringup",
            "robot.launch.py",
            "mode:=sim",
            f"world:={request.world}",
            "sensors:=true",
            f"headless_rendering:={'true' if request.headless_rendering else 'false'}",
            "gui:=false",
        ]
        robot_env = os.environ.copy()
        if not request.headless_rendering:
            robot_env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
            robot_env.setdefault("__EGL_VENDOR_LIBRARY_FILENAMES", "/dev/null")
            if self._use_xvfb() and shutil.which("xvfb-run"):
                robot_cmd = ["xvfb-run", "-a", *robot_cmd]

        if request.mode == StackMode.MAPPING:
            secondary = [
                "ros2",
                "launch",
                "robot_navigation",
                "map.launch.py",
                "workflow:=mapping",
                "use_sim_time:=true",
                "rviz:=false",
            ]
            return [
                ("robot", robot_cmd, robot_env),
                ("mapping", secondary, os.environ.copy()),
            ]

        assert map_path is not None
        spawn_x, spawn_y, spawn_yaw = self.SIM_SPAWNS.get(request.world, (0.0, 0.0, 0.0))
        navigation = [
            "ros2",
            "launch",
            "robot_navigation",
            "navigation.launch.py",
            f"map_file:={map_path}",
            "use_sim_time:=true",
            f"profile:={request.navigation_profile}",
            f"initial_pose_x:={spawn_x}",
            f"initial_pose_y:={spawn_y}",
            f"initial_pose_yaw:={spawn_yaw}",
            "autostart:=true",
            "rviz:=false",
        ]
        mission = [
            "ros2",
            "launch",
            "mission_manager",
            "mission.launch.py",
            "mode:=sim",
            f"environment:={request.world}",
            f"navigation_profile:={request.navigation_profile}",
            f"map_file:={map_path}",
        ]
        return [
            ("robot", robot_cmd, robot_env),
            ("navigation", navigation, os.environ.copy()),
            ("mission", mission, os.environ.copy()),
        ]

    def _use_xvfb(self) -> bool:
        value = os.getenv("ROBOTOPS_USE_XVFB", "true").strip().lower()
        return value not in ("0", "false", "no", "off")

    def _start_process_locked(self, name: str, command: list[str], env: dict[str, str]) -> None:
        log_path = self.logs_dir / f"{int(time.time())}-{name}.log"
        handle = log_path.open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                cwd=self.repo_root,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                text=True,
            )
        except Exception:
            handle.close()
            raise
        item = _ManagedProcess(
            name, process, handle, log_path, direct_ros_launch=command[:2] == ["ros2", "launch"]
        )
        self._processes[name] = item
        if command[:2] == ["xvfb-run", "-a"]:
            # Keep the X server alive until ROS launch has stopped its renderer.
            # xvfb-run owns both children and cleans up Xvfb after launch returns.
            deadline = time.monotonic() + 5.0
            while process.poll() is None and time.monotonic() < deadline:
                child = self._wrapped_launch_child(process.pid, command[2:])
                if child is not None:
                    item.wrapped_launch_pid, item.wrapped_launch_start = child
                    return
                time.sleep(0.05)
            raise RuntimeError(
                f"Could not identify owned ROS launch under xvfb-run; see {log_path}"
            )

    @staticmethod
    def _process_identity(pid: int) -> tuple[int, int] | None:
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
            return int(fields[1]), int(fields[19])  # parent PID and Linux start ticks
        except (OSError, ValueError, IndexError):
            return None

    @classmethod
    def _wrapped_launch_child(cls, parent: int, command: list[str]) -> tuple[int, int] | None:
        try:
            children = Path(f"/proc/{parent}/task/{parent}/children").read_text().split()
            for child in children:
                pid = int(child)
                args = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                args = [os.fsdecode(arg) for arg in args if arg]
                for index, arg in enumerate(args):
                    if Path(arg).name == command[0] and args[index + 1 :] == command[1:]:
                        identity = cls._process_identity(pid)
                        if identity is not None and identity[0] == parent:
                            return pid, identity[1]
        except (OSError, ValueError):
            pass
        return None

    def _interrupt_managed(self, item: _ManagedProcess) -> None:
        if item.direct_ros_launch:
            # Launch forwards SIGINT to its children. A group signal would reach
            # them twice and can interrupt rclcpp after its handler is removed.
            item.process.send_signal(signal.SIGINT)
            return
        pid = item.wrapped_launch_pid
        if pid is not None and self._process_identity(pid) == (
            item.process.pid,
            item.wrapped_launch_start,
        ):
            # Signal the verified child, not its wrapper/display process group.
            os.kill(pid, signal.SIGINT)
        else:
            os.killpg(item.process.pid, signal.SIGINT)

    def _monitor_processes(self) -> None:
        while True:
            time.sleep(0.5)
            with self._lock:
                if not self._processes:
                    return
                failed = [
                    managed
                    for managed in self._processes.values()
                    if managed.process.poll() is not None
                ]
                if not failed:
                    continue
                if self._stop_requested:
                    return
                first = failed[0]
                self._status.state = StackState.FAILED
                self._status.error = (
                    f"{first.name} exited with code {first.process.returncode}; "
                    f"see {first.log_path.relative_to(self.repo_root)}"
                )
                # RViz is managed separately from the robot stack so it can be
                # opened/closed without disturbing Nav2. If a core process dies,
                # however, close the RobotOps-owned RViz as part of failure cleanup
                # so we do not leave an orphan engineering window behind.
                self._stop_rviz_locked()
                self._stop_locked()
                return

    def _refresh_locked(self) -> None:
        self._refresh_rviz_locked()
        if not self._processes:
            return
        failed = [
            managed for managed in self._processes.values() if managed.process.poll() is not None
        ]
        if failed and self._status.state == StackState.RUNNING:
            first = failed[0]
            self._status.state = StackState.FAILED
            self._status.error = (
                f"{first.name} exited with code {first.process.returncode}; "
                f"see {first.log_path.relative_to(self.repo_root)}"
            )

    def _stop_locked(self) -> None:
        managed = list(reversed(list(self._processes.values())))
        for item in managed:
            if item.process.poll() is None:
                try:
                    self._interrupt_managed(item)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 12.0
        for item in managed:
            remaining = max(0.0, deadline - time.monotonic())
            if item.process.poll() is None:
                try:
                    item.process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(item.process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
        deadline = time.monotonic() + 5.0
        for item in managed:
            remaining = max(0.0, deadline - time.monotonic())
            if item.process.poll() is None:
                try:
                    item.process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(item.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        item.process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        pass
            item.log_handle.close()
        self._processes.clear()

    def _discover_maps(self) -> list[MapArtifact]:
        if not self.maps_dir.is_dir():
            return []
        maps: list[MapArtifact] = []
        for path in sorted(self.maps_dir.glob("*.yaml")):
            artifact = self._artifact_from_yaml(path)
            if artifact is not None:
                maps.append(artifact)

        latest_by_world: dict[str | None, MapArtifact] = {}
        for artifact in maps:
            current = latest_by_world.get(artifact.world_id)
            if current is None or self._created_sort_key(artifact) > self._created_sort_key(
                current
            ):
                latest_by_world[artifact.world_id] = artifact
        for artifact in maps:
            artifact.is_latest = latest_by_world.get(artifact.world_id) is artifact
        return sorted(maps, key=self._created_sort_key, reverse=True)

    def _artifact_from_yaml(self, path: Path) -> MapArtifact | None:
        try:
            info = self._read_map_info(path)
        except Exception:
            return None
        image_path = info.get("image_path")
        if not isinstance(image_path, Path) or not image_path.is_file():
            return None

        world_id = None
        created_at_ns: str | None = None
        resolution = info.get("resolution")
        width = info.get("width")
        height = info.get("height")
        metadata_path = path.with_suffix(".robotops.json")
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                candidate = metadata.get("world_id")
                if isinstance(candidate, str) and candidate in {w.id for w in self.WORLDS}:
                    world_id = candidate
                raw_created = metadata.get("created_at_ns")
                if isinstance(raw_created, str | int):
                    created_at_ns = str(raw_created)
                # Map geometry comes from the actual YAML/PGM on disk. Metadata is
                # descriptive only and must never override the source map contents.
            except Exception:
                pass
        if created_at_ns is None:
            created_at_ns = str(path.stat().st_mtime_ns)

        return MapArtifact(
            id=path.stem,
            label=path.stem.replace("_", " ").replace("-", " ").title(),
            yaml_path=str(path.relative_to(self.repo_root)),
            world_id=world_id,
            created_at_ns=created_at_ns,
            resolution=float(resolution) if resolution is not None else None,
            width=int(width) if width is not None else None,
            height=int(height) if height is not None else None,
            preview_url=f"/api/v1/maps/{path.stem}/preview.svg",
        )

    @staticmethod
    def _created_sort_key(artifact: MapArtifact) -> int:
        try:
            return int(artifact.created_at_ns or 0)
        except ValueError:
            return 0

    def _read_map_info(self, yaml_path: Path) -> dict[str, object]:
        import yaml

        content = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        image = content.get("image")
        if not isinstance(image, str):
            raise ValueError("map yaml has no image")
        image_path = (yaml_path.parent / image).resolve()
        maps_root = self.maps_dir.resolve()
        try:
            image_path.relative_to(maps_root)
        except ValueError as exc:
            raise ValueError("map image must stay inside the approved maps directory") from exc
        width, height, pixels = self._read_pgm(image_path)
        resolution = float(content.get("resolution", 0.0) or 0.0)
        return {
            "image_path": image_path,
            "resolution": resolution if resolution > 0 else None,
            "width": width,
            "height": height,
            "pixels": pixels,
        }

    @staticmethod
    def _read_pgm(path: Path) -> tuple[int, int, list[int]]:
        data = path.read_bytes()
        index = 0

        def token() -> bytes:
            nonlocal index
            while index < len(data):
                if data[index : index + 1] == b"#":
                    while index < len(data) and data[index : index + 1] not in (b"\n", b"\r"):
                        index += 1
                elif data[index : index + 1].isspace():
                    index += 1
                else:
                    break
            start = index
            while index < len(data) and not data[index : index + 1].isspace():
                index += 1
            return data[start:index]

        magic = token()
        width = int(token())
        height = int(token())
        max_value = int(token())
        if width <= 0 or height <= 0 or max_value <= 0:
            raise ValueError("invalid PGM dimensions")
        count = width * height
        if magic == b"P5":
            # P5 has exactly one whitespace separator after max_value.
            # CRLF counts as one line ending.
            if data[index : index + 2] == b"\r\n":
                index += 2
            elif index < len(data) and data[index : index + 1].isspace():
                index += 1
            raw = data[index : index + count]
            if len(raw) < count:
                raise ValueError("truncated PGM")
            pixels = list(raw)
        elif magic == b"P2":
            rest = data[index:].decode("ascii", errors="strict").split()
            pixels = [int(value) for value in rest[:count]]
            if len(pixels) < count:
                raise ValueError("truncated PGM")
        else:
            raise ValueError("unsupported PGM format")
        if max_value != 255:
            pixels = [max(0, min(255, round(value * 255 / max_value))) for value in pixels]
        return width, height, pixels

    def map_preview_svg(self, map_id: str) -> str:
        options = {item.id: item for item in self._discover_maps()}
        artifact = options.get(map_id)
        if artifact is None:
            raise ValueError(f"Unknown or invalid saved map '{map_id}'")
        yaml_path = (self.repo_root / artifact.yaml_path).resolve(strict=True)
        info = self._read_map_info(yaml_path)
        width = int(info["width"])
        height = int(info["height"])
        pixels = list(info["pixels"])
        max_cells = 96
        step = max(1, (max(width, height) + max_cells - 1) // max_cells)
        rects: list[str] = []
        for y in range(0, height, step):
            for x in range(0, width, step):
                idx = y * width + x
                value = pixels[idx]
                shade = int(value)
                cell_width = min(step, width - x)
                cell_height = min(step, height - y)
                rects.append(
                    f'<rect x="{x}" y="{height - y - cell_height}" '
                    f'width="{cell_width}" height="{cell_height}" '
                    f'fill="rgb({shade},{shade},{shade})"/>'
                )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            'preserveAspectRatio="xMidYMid meet" shape-rendering="crispEdges">'
            '<rect width="100%" height="100%" fill="#252525"/>' + "".join(rects) + "</svg>"
        )

    def _resolve_map(self, map_id: str | None, world_id: str | None = None) -> Path:
        if not map_id:
            raise ValueError("A saved map is required for navigation")
        options = {item.id: item for item in self._discover_maps()}
        if map_id not in options:
            raise ValueError(f"Unknown or invalid saved map '{map_id}'")
        artifact = options[map_id]
        if (
            artifact.world_id is not None
            and world_id is not None
            and artifact.world_id != world_id
        ):
            raise ValueError(
                f"Saved map '{map_id}' belongs to world '{artifact.world_id}', not '{world_id}'"
            )
        path = (self.repo_root / artifact.yaml_path).resolve(strict=True)
        if world_id == "warehouse_v1" or artifact.world_id == "warehouse_v1":
            from .benchmarks.warehouse import validate_warehouse_map

            if artifact.world_id != "warehouse_v1":
                raise ValueError("Warehouse requires explicit map/world association")
            validate_warehouse_map(self.repo_root, path)
        return path
