import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { displayPoint, displayQuaternion, type Transform, type Vec3 } from "./data";

// Dedicated recorded-data renderer: no live state, command callbacks or assumed
// scan-to-current-robot association. All input points already share ROS map frame.
export function RecordedScene({ pose, points, trail }: { pose: Transform | null; points: Vec3[]; trail: Vec3[] }) {
  const mount = useRef<HTMLDivElement>(null);
  const objects = useRef<{ robot: THREE.Group; scans: THREE.BufferGeometry; trail: THREE.BufferGeometry; focus: (point: Vec3) => void } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const element = mount.current!; let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true }); } catch { setError("3D unavailable: WebGL required. Recorded map and validation remain available."); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); element.appendChild(renderer.domElement);
    const scene = new THREE.Scene(); scene.background = new THREE.Color("#101e2a");
    const camera = new THREE.PerspectiveCamera(48, 1, .05, 100);
    let azimuth = .8, distance = 2.1;
    const target = new THREE.Vector3();
    const update = () => { camera.position.set(target.x + Math.cos(azimuth) * distance, target.y + distance * .65, target.z + Math.sin(azimuth) * distance); camera.lookAt(target); };
    update(); scene.add(new THREE.HemisphereLight(0xffffff, 0x213244, 3));
    const grid = new THREE.GridHelper(8, 16, 0x34505d, 0x1c303e); scene.add(grid);
    // Illustrative differential-drive silhouette, not measured CAD geometry.
    // Decorative parts are rigid: no invented wheel/sensor motion.
    const robot = new THREE.Group(); robot.visible = false;
    const body = new THREE.Mesh(new THREE.BoxGeometry(.4, .12, .28), new THREE.MeshStandardMaterial({ color: "#a4c3d5", roughness: .55, metalness: .15 }));
    body.position.y = .12; robot.add(body);
    const deck = new THREE.Mesh(new THREE.BoxGeometry(.32, .025, .23), new THREE.MeshStandardMaterial({ color: "#3c7d91" })); deck.position.y = .195; robot.add(deck);
    for (const z of [-.17, .17]) {
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(.085, .085, .045, 20), new THREE.MeshStandardMaterial({ color: "#222e38", roughness: .9 }));
      wheel.rotation.x = Math.PI / 2; wheel.position.set(0, .085, z); robot.add(wheel);
    }
    const puck = new THREE.Mesh(new THREE.CylinderGeometry(.065, .065, .045, 24), new THREE.MeshStandardMaterial({ color: "#72c6d3" })); puck.position.y = .23; robot.add(puck);
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, .13, 0), .42, 0xf5c278); robot.add(arrow); scene.add(robot);
    const key = new THREE.DirectionalLight(0xffffff, 2); key.position.set(2, 4, 3); scene.add(key);
    const scans = new THREE.BufferGeometry(); const scanMaterial = new THREE.PointsMaterial({ color: "#62e6c4", size: .055 }); scene.add(new THREE.Points(scans, scanMaterial));
    const trail = new THREE.BufferGeometry(); const trailMaterial = new THREE.LineBasicMaterial({ color: "#ffb64a" }); scene.add(new THREE.Line(trail, trailMaterial));
    objects.current = { robot, scans, trail, focus: point => { target.set(...displayPoint(point)); target.y += .12; update(); } };
    let dragging = false, last = 0;
    const down = (e: PointerEvent) => { dragging = true; last = e.clientX; element.setPointerCapture(e.pointerId); };
    const move = (e: PointerEvent) => { if (dragging) { azimuth -= (e.clientX - last) * .01; last = e.clientX; update(); } };
    const up = () => { dragging = false; };
    const wheel = (e: WheelEvent) => { e.preventDefault(); distance = Math.max(1.2, Math.min(12, distance * (e.deltaY > 0 ? 1.1 : .9))); update(); };
    element.addEventListener("pointerdown", down); element.addEventListener("pointermove", move); element.addEventListener("pointerup", up); element.addEventListener("pointercancel", up); element.addEventListener("wheel", wheel, { passive: false });
    const resize = new ResizeObserver(() => { const w = element.clientWidth, h = element.clientHeight; if (!w || !h) return; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }); resize.observe(element);
    let frame = 0; const draw = () => { renderer.render(scene, camera); frame = requestAnimationFrame(draw); }; draw();
    return () => {
      cancelAnimationFrame(frame); resize.disconnect(); element.removeEventListener("pointerdown", down); element.removeEventListener("pointermove", move); element.removeEventListener("pointerup", up); element.removeEventListener("pointercancel", up); element.removeEventListener("wheel", wheel);
      scene.traverse(o => { if (o instanceof THREE.Mesh || o instanceof THREE.Line || o instanceof THREE.Points) { o.geometry.dispose(); const materials = Array.isArray(o.material) ? o.material : [o.material]; materials.forEach(m => m.dispose()); } });
      renderer.dispose(); element.removeChild(renderer.domElement); objects.current = null;
    };
  }, []);
  useEffect(() => {
    const view = objects.current; if (!view) return;
    view.robot.visible = pose !== null;
    if (pose) { view.robot.position.set(...displayPoint(pose.position)); view.robot.quaternion.set(...displayQuaternion(pose.quaternion)); view.focus(pose.position); }
    view.scans.setAttribute("position", new THREE.Float32BufferAttribute(points.flatMap(displayPoint), 3)); view.scans.computeBoundingSphere();
    view.trail.setAttribute("position", new THREE.Float32BufferAttribute(trail.flatMap(displayPoint), 3)); view.trail.computeBoundingSphere();
  }, [pose, points, trail]);
  return <><div ref={mount} className="recorded-scene" aria-label="Recorded schematic robot in ROS map frame" />{error && <p role="alert">{error}</p>}<p className="caption">Illustrative geometry · no physics · drag to orbit, wheel to zoom</p></>;
}
