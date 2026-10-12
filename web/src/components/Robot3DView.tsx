import { useEffect, useRef } from "react";
import * as THREE from "three";
import type { RobotSnapshot } from "../lib/types";

interface Props {
  snapshot: RobotSnapshot;
  trajectory?: Array<{ x: number; y: number; yaw: number }>;
  mappingActive?: boolean;
}

interface CameraState {
  azimuth: number;
  elevation: number;
  distance: number;
}

function buildMapTexture(map: NonNullable<RobotSnapshot["map"]>) {
  const canvas = document.createElement("canvas");
  canvas.width = map.width;
  canvas.height = map.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  const image = ctx.createImageData(map.width, map.height);
  for (let i = 0; i < map.data.length; i += 1) {
    const occupancy = map.data[i] ?? -1;
    let rgb: [number, number, number];
    if (occupancy < 0) rgb = [24, 33, 43];
    else if (occupancy >= 65) rgb = [8, 13, 19];
    else if (occupancy <= 25) rgb = [214, 223, 232];
    else {
      const shade = Math.round(214 - (occupancy / 100) * 158);
      rgb = [shade, shade + 3, shade + 7];
    }

    const row = Math.floor(i / map.width);
    const col = i % map.width;
    const y = map.height - 1 - row;
    const p = (y * map.width + col) * 4;
    image.data[p] = rgb[0];
    image.data[p + 1] = rgb[1];
    image.data[p + 2] = rgb[2];
    image.data[p + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.LinearFilter;
  return texture;
}

export function Robot3DView({ snapshot, trajectory = [], mappingActive = false }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const robotRef = useRef<THREE.Group | null>(null);
  const scanGeometryRef = useRef<THREE.BufferGeometry | null>(null);
  const mapGroupRef = useRef<THREE.Group | null>(null);
  const mapTextureRef = useRef<THREE.CanvasTexture | null>(null);
  const trailRef = useRef<THREE.Line | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const cameraStateRef = useRef<CameraState>({
    azimuth: Math.PI * 0.22,
    elevation: Math.PI * 0.27,
    distance: mappingActive ? 3.2 : 8.2,
  });
  const poseRef = useRef(snapshot.pose);

  function updateCamera() {
    const camera = cameraRef.current;
    if (!camera) return;
    const pose = poseRef.current;
    const { azimuth, elevation, distance } = cameraStateRef.current;
    const targetX = pose?.x ?? 0;
    const targetZ = -(pose?.y ?? 0);
    const planar = Math.cos(elevation) * distance;
    camera.position.set(
      targetX + Math.cos(azimuth) * planar,
      Math.max(1.4, Math.sin(elevation) * distance),
      targetZ + Math.sin(azimuth) * planar,
    );
    camera.lookAt(targetX, 0.16, targetZ);
  }

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b121a);
    scene.fog = new THREE.Fog(0x0b121a, 7, 24);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(52, 1, 0.05, 100);
    cameraRef.current = camera;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.HemisphereLight(0xbfdcff, 0x17202a, 2.3));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(4, 8, 3);
    key.castShadow = true;
    scene.add(key);

    const grid = new THREE.GridHelper(20, 40, 0x35506a, 0x1e2d3b);
    grid.position.y = 0.002;
    scene.add(grid);

    const groundMaterial = new THREE.MeshStandardMaterial({ color: 0x101820, roughness: 0.96 });
    const groundGeometry = new THREE.PlaneGeometry(20, 20);
    const ground = new THREE.Mesh(groundGeometry, groundMaterial);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    const robot = new THREE.Group();
    robotRef.current = robot;

    const bodyMaterial = new THREE.MeshStandardMaterial({ color: 0xff3d71, roughness: 0.42, metalness: 0.08 });
    // Match robot_description/config/geometry.yaml (base_link is at the drive axle).
    const bodyGeometry = new THREE.BoxGeometry(0.40, 0.12, 0.28);
    const body = new THREE.Mesh(bodyGeometry, bodyMaterial);
    body.position.set(-0.04, 0.06, 0);
    body.castShadow = true;
    robot.add(body);

    const topMaterial = new THREE.MeshStandardMaterial({ color: 0xe9f1f8, roughness: 0.3 });
    const topGeometry = new THREE.CylinderGeometry(0.12, 0.14, 0.08, 24);
    const top = new THREE.Mesh(topGeometry, topMaterial);
    top.position.set(0, 0.14, 0);
    robot.add(top);

    const noseMaterial = new THREE.MeshStandardMaterial({ color: 0xffd166, roughness: 0.45 });
    const noseGeometry = new THREE.ConeGeometry(0.085, 0.2, 3);
    const nose = new THREE.Mesh(noseGeometry, noseMaterial);
    nose.rotation.z = -Math.PI / 2;
    nose.position.set(0.24, 0.09, 0);
    robot.add(nose);

    const wheelMaterial = new THREE.MeshStandardMaterial({ color: 0x11161d, roughness: 0.85 });
    const wheelGeometries: THREE.CylinderGeometry[] = [];
    for (const z of [-0.17, 0.17]) {
      const geometry = new THREE.CylinderGeometry(0.075, 0.075, 0.03, 20);
      wheelGeometries.push(geometry);
      const wheel = new THREE.Mesh(geometry, wheelMaterial);
      wheel.rotation.x = Math.PI / 2;
      wheel.position.set(0, 0.075, z);
      wheel.castShadow = true;
      robot.add(wheel);
    }

    const scanGeometry = new THREE.BufferGeometry();
    scanGeometryRef.current = scanGeometry;
    const scanMaterial = new THREE.PointsMaterial({ color: 0x62e6c4, size: 0.055, sizeAttenuation: true });
    robot.add(new THREE.Points(scanGeometry, scanMaterial));
    scene.add(robot);

    const trailGeometry = new THREE.BufferGeometry();
    const trailMaterial = new THREE.LineBasicMaterial({ color: 0xffab40, transparent: true, opacity: 0.95 });
    const trail = new THREE.Line(trailGeometry, trailMaterial);
    trail.position.y = 0.035;
    trailRef.current = trail;
    scene.add(trail);

    let dragging = false;
    let previousX = 0;
    let previousY = 0;

    const pointerDown = (event: PointerEvent) => {
      dragging = true;
      previousX = event.clientX;
      previousY = event.clientY;
      renderer.domElement.setPointerCapture(event.pointerId);
    };
    const pointerMove = (event: PointerEvent) => {
      if (!dragging) return;
      const dx = event.clientX - previousX;
      const dy = event.clientY - previousY;
      previousX = event.clientX;
      previousY = event.clientY;
      const state = cameraStateRef.current;
      state.azimuth -= dx * 0.008;
      state.elevation = Math.min(1.25, Math.max(0.18, state.elevation + dy * 0.006));
      updateCamera();
    };
    const pointerUp = (event: PointerEvent) => {
      dragging = false;
      if (renderer.domElement.hasPointerCapture(event.pointerId)) {
        renderer.domElement.releasePointerCapture(event.pointerId);
      }
    };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const state = cameraStateRef.current;
      state.distance = Math.min(18, Math.max(2.2, state.distance * (event.deltaY > 0 ? 1.08 : 0.92)));
      updateCamera();
    };

    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointermove", pointerMove);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    renderer.domElement.addEventListener("pointercancel", pointerUp);
    renderer.domElement.addEventListener("wheel", wheel, { passive: false });

    const resize = () => {
      const width = Math.max(320, mount.clientWidth);
      const height = Math.max(420, mount.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();
    updateCamera();

    let frame = 0;
    const animate = () => {
      frame = requestAnimationFrame(animate);
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointermove", pointerMove);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      renderer.domElement.removeEventListener("pointercancel", pointerUp);
      renderer.domElement.removeEventListener("wheel", wheel);

      if (mapGroupRef.current) {
        scene.remove(mapGroupRef.current);
        const mesh = mapGroupRef.current.children[0] as THREE.Mesh | undefined;
        mesh?.geometry.dispose();
        (mesh?.material as THREE.Material | undefined)?.dispose();
      }
      mapTextureRef.current?.dispose();
      scanGeometry.dispose();
      scanMaterial.dispose();
      trailGeometry.dispose();
      trailMaterial.dispose();
      bodyGeometry.dispose();
      bodyMaterial.dispose();
      topGeometry.dispose();
      topMaterial.dispose();
      noseGeometry.dispose();
      noseMaterial.dispose();
      wheelGeometries.forEach((geometry) => geometry.dispose());
      wheelMaterial.dispose();
      groundGeometry.dispose();
      groundMaterial.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);

      sceneRef.current = null;
      robotRef.current = null;
      scanGeometryRef.current = null;
      mapGroupRef.current = null;
      trailRef.current = null;
      mapTextureRef.current = null;
      cameraRef.current = null;
    };
  }, []);

  useEffect(() => {
    poseRef.current = snapshot.pose;
    const robot = robotRef.current;
    if (!robot) return;
    if (snapshot.pose) {
      robot.visible = true;
      robot.position.set(snapshot.pose.x, 0, -snapshot.pose.y);
      robot.rotation.y = snapshot.pose.yaw;
    } else {
      robot.visible = false;
    }
    updateCamera();
  }, [snapshot.pose]);

  useEffect(() => {
    const geometry = scanGeometryRef.current;
    if (!geometry) return;
    const points = new Float32Array(snapshot.scan.length * 3);
    snapshot.scan.forEach((point, index) => {
      points[index * 3] = point.x;
      points[index * 3 + 1] = 0.14;
      points[index * 3 + 2] = -point.y;
    });
    geometry.setAttribute("position", new THREE.BufferAttribute(points, 3));
    geometry.computeBoundingSphere();
  }, [snapshot.scan]);

  useEffect(() => {
    const trail = trailRef.current;
    if (!trail) return;
    const positions = new Float32Array(trajectory.length * 3);
    trajectory.forEach((point, index) => {
      positions[index * 3] = point.x;
      positions[index * 3 + 1] = 0.035;
      positions[index * 3 + 2] = -point.y;
    });
    trail.geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    trail.geometry.computeBoundingSphere();
    trail.visible = mappingActive && trajectory.length > 1;
  }, [mappingActive, trajectory]);

  useEffect(() => {
    if (!mappingActive) return;
    const hasContext = Boolean(snapshot.map) || snapshot.scan.length > 0;
    if (!hasContext && cameraStateRef.current.distance > 4.0) {
      cameraStateRef.current.distance = 3.2;
      updateCamera();
    }
  }, [mappingActive, snapshot.map, snapshot.scan.length]);

  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    if (mapGroupRef.current) {
      scene.remove(mapGroupRef.current);
      const oldMesh = mapGroupRef.current.children[0] as THREE.Mesh | undefined;
      oldMesh?.geometry.dispose();
      (oldMesh?.material as THREE.Material | undefined)?.dispose();
      mapGroupRef.current = null;
    }
    mapTextureRef.current?.dispose();
    mapTextureRef.current = null;

    const map = snapshot.map;
    if (!map) return;
    const texture = buildMapTexture(map);
    if (!texture) return;
    mapTextureRef.current = texture;

    const widthM = map.width * map.resolution;
    const heightM = map.height * map.resolution;
    const geometry = new THREE.PlaneGeometry(widthM, heightM);
    const material = new THREE.MeshStandardMaterial({
      map: texture,
      transparent: true,
      opacity: snapshot.connection === "connected" ? 0.88 : 0.52,
      roughness: 0.95,
      side: THREE.DoubleSide,
    });
    // Represent the ROS map frame explicitly. ROS +Y maps to Three.js -Z,
    // and a positive ROS yaw is therefore a positive rotation about Three.js +Y.
    const mapGroup = new THREE.Group();
    mapGroup.position.set(map.origin.x, 0, -map.origin.y);
    mapGroup.rotation.y = map.origin.yaw;

    const mesh = new THREE.Mesh(geometry, material);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(widthM / 2, 0.012, -heightM / 2);
    mapGroup.add(mesh);
    scene.add(mapGroup);
    mapGroupRef.current = mapGroup;
  }, [snapshot.map, snapshot.connection]);

  return (
    <div className="robot-3d-shell">
      <div ref={mountRef} className="robot-3d-view" aria-label="Interactive 3D robot visualization" />
      <div className="view-overlay view-overlay-top">
        <span className={`live-dot ${snapshot.connection}`} />
        <span>{snapshot.connection === "connected" ? "live telemetry" : "last known telemetry"}</span>
      </div>
      {mappingActive && !snapshot.map && snapshot.scan.length === 0 && (
        <div className="view-overlay view-overlay-center">
          {snapshot.pose ? "Robot pose is live · waiting for first SLAM map / LiDAR context" : "Waiting for mapping telemetry"}
        </div>
      )}
      <p className="view-help">Drag to orbit · wheel to zoom · view follows robot pose</p>
    </div>
  );
}
