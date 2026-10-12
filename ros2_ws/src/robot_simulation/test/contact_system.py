"""Independent physics contacts: normal support, obstacle and incomplete inventory."""

import os
import signal
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest
import rclpy
from ament_index_python.packages import get_package_prefix
from rclpy.context import Context
from rclpy.executors import SingleThreadedExecutor
from robotops_interfaces.msg import ContactEvidence


@pytest.mark.parametrize("obstacle,inventory_ok", [(False, True), (True, True), (False, False)])
def test_physics_contact_evidence(tmp_path, obstacle, inventory_ok):
    extra = (
        """<model name="obstacle"><static>true</static><pose>0.45 0 0.5 0 0 0</pose>
      <link name="body"><collision name="collision"><geometry><box><size>0.2 2 1</size>
      </box></geometry></collision></link></model>"""
        if obstacle
        else ""
    )
    body = "body::collision"
    extra_body = "" if inventory_ok else "<body>missing::collision</body>"
    world = tmp_path / "contacts.sdf"
    world.write_text(f"""<sdf version="1.9"><world name="contact_test">
      <physics name="physics" type="ignored"><max_step_size>0.001</max_step_size>
        <real_time_factor>1</real_time_factor></physics>
      <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
      <model name="floor"><static>true</static><link name="body">
        <collision name="collision"><geometry><plane><normal>0 0 1</normal><size>20 20</size>
        </plane></geometry></collision></link></model>
      {extra}
      <model name="robot"><pose>0 0 0.5 0 0 0</pose><link name="body">
        <inertial><mass>1</mass><inertia><ixx>0.1</ixx><iyy>0.1</iyy><izz>0.1</izz>
        </inertia></inertial><collision name="collision"><geometry><box><size>1 1 1</size>
        </box></geometry></collision></link>
        <plugin filename="librobotops_contact_evidence.so"
          name="robot_simulation::ContactEvidence">
          <body>{body}</body>{extra_body}<support_body>{body}</support_body>
          <floor>floor::body::collision</floor><topic>validation/contacts</topic>
        </plugin>
      </model></world></sdf>""")
    prefix = Path(get_package_prefix("robot_simulation"))
    env = dict(
        os.environ,
        ROS_DOMAIN_ID="196",
        GZ_PARTITION=uuid4().hex,
        GZ_SIM_SYSTEM_PLUGIN_PATH=str(prefix / "lib")
        + os.pathsep
        + os.environ.get("GZ_SIM_SYSTEM_PLUGIN_PATH", ""),
    )
    context = Context()
    rclpy.init(context=context, domain_id=196)
    node = rclpy.create_node("contact_probe", context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(node)
    frames = []
    subscription = node.create_subscription(
        ContactEvidence, "validation/contacts", frames.append, 100
    )
    with (tmp_path / "server.log").open("w") as output:
        process = subprocess.Popen(
            [str(prefix / "lib/robot_simulation/gazebo_runner"), str(world), "false"],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            while len(frames) < 50 and time.monotonic() < deadline:
                executor.spin_once(timeout_sec=0.05)
                assert process.poll() is None, (tmp_path / "server.log").read_text()
            assert len(frames) >= 50, (tmp_path / "server.log").read_text()
            assert any(f.support_contact_steps > 0 for f in frames) or not inventory_ok
            assert any(f.coverage_complete for f in frames) == inventory_ok
            pairs = [p for f in frames for p in f.contacts]
            assert bool(pairs) == obstacle
            if obstacle:
                assert any("obstacle" in p.body_a or "obstacle" in p.body_b for p in pairs)
            assert all(f.physics_steps > 0 for f in frames)
            assert all(
                b.start_ns == a.end_ns and b.sequence == a.sequence + 1
                for a, b in zip(frames, frames[1:], strict=False)
            )
            print(
                f"obstacle={obstacle} inventory_ok={inventory_ok} frames={len(frames)} "
                f"complete={sum(f.coverage_complete for f in frames)} pairs={len(pairs)}"
            )
            if not obstacle and inventory_ok:

                def control(request):
                    reply = subprocess.run(
                        [
                            "gz",
                            "service",
                            "-s",
                            "/world/contact_test/control",
                            "--reqtype",
                            "gz.msgs.WorldControl",
                            "--reptype",
                            "gz.msgs.Boolean",
                            "--timeout",
                            "3000",
                            "--req",
                            request,
                        ],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    assert reply.returncode == 0 and "true" in reply.stdout, reply.stderr

                control("pause: true")
                # Drain in-flight deliveries, then require silence while physics is paused.
                until = time.monotonic() + 0.3
                while time.monotonic() < until:
                    executor.spin_once(timeout_sec=0.02)
                paused_count = len(frames)
                until = time.monotonic() + 0.3
                while time.monotonic() < until:
                    executor.spin_once(timeout_sec=0.02)
                assert len(frames) == paused_count
                old_source = frames[-1].source_id
                control("pause: false reset: {all: true}")
                until = time.monotonic() + 8
                while len(frames) < paused_count + 10 and time.monotonic() < until:
                    executor.spin_once(timeout_sec=0.05)
                reset_frames = frames[paused_count:]
                assert reset_frames
                assert all(
                    f.source_id != old_source or not f.coverage_complete for f in reset_frames
                )
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=10) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            node.destroy_subscription(subscription)
            executor.shutdown()
            node.destroy_node()
            context.shutdown()
