"""Both shutdown signals while rendered sensors run; no forced termination allowed."""

import os
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

import pytest
from ament_index_python.packages import get_package_prefix, get_package_share_directory


@pytest.mark.parametrize("shutdown_signal", [signal.SIGINT, signal.SIGTERM])
def test_rendered_sensor_shutdown(tmp_path, shutdown_signal):
    root = ET.parse(
        Path(get_package_share_directory("robot_simulation")) / "worlds/mapping_lab.sdf"
    )
    root.getroot().find("world").append(
        ET.fromstring("""
      <model name="shutdown_sensor"><static>true</static><pose>0 0 1 0 0 0</pose>
        <link name="sensor_link"><sensor name="lidar" type="gpu_lidar">
          <topic>/shutdown_scan</topic><update_rate>30</update_rate>
          <lidar><scan><horizontal><samples>64</samples><resolution>1</resolution>
            <min_angle>-3.14</min_angle><max_angle>3.14</max_angle>
          </horizontal></scan><range><min>0.1</min><max>10</max><resolution>0.01</resolution></range></lidar>
        </sensor></link>
      </model>""")
    )
    world = tmp_path / "sensors.sdf"
    root.write(world)
    executable = (
        Path(get_package_prefix("robot_simulation")) / "lib/robot_simulation/gazebo_runner"
    )
    env = dict(
        os.environ,
        GZ_PARTITION=f"shutdown_{uuid4().hex}",
        LIBGL_ALWAYS_SOFTWARE="1",
        __EGL_VENDOR_LIBRARY_FILENAMES="/dev/null",
    )
    with (tmp_path / "server.log").open("w") as stream:
        process = subprocess.Popen(
            [str(executable), str(world), "false"],
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        try:
            scan = subprocess.run(
                ["gz", "topic", "-e", "-t", "/shutdown_scan", "-n", "1"],
                env=env,
                capture_output=True,
                text=True,
                timeout=25,
            )
            assert scan.returncode == 0 and "ranges:" in scan.stdout, scan.stderr
            # Every existing worker must inherit blocked INT/TERM. The main thread
            # receives those signals only in sigtimedwait, outside allocator locks.
            required = (1 << (signal.SIGINT - 1)) | (1 << (signal.SIGTERM - 1))
            checked = 0
            for task in Path(f"/proc/{process.pid}/task").iterdir():
                # Linux temporarily adjusts the waiting thread mask inside
                # sigtimedwait; the main thread is that synchronous receiver.
                if int(task.name) == process.pid:
                    continue
                try:
                    status = (task / "status").read_text()
                except FileNotFoundError:
                    continue
                mask = next(
                    line.split()[1] for line in status.splitlines() if line.startswith("SigBlk:")
                )
                assert int(mask, 16) & required == required, status
                checked += 1
            assert checked > 2
            time.sleep(0.13)
            process.send_signal(shutdown_signal)
            assert process.wait(timeout=8) == 0, (tmp_path / "server.log").read_text()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
