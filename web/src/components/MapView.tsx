import { PointerEvent, WheelEvent, useEffect, useMemo, useRef, useState } from "react";
import type { Pose2D, RobotSnapshot } from "../lib/types";

interface Props {
  snapshot: RobotSnapshot;
  selectedGoal: Pose2D | null;
  onGoalSelect: (goal: Pose2D) => void;
  trajectory?: Pose2D[];
  mappingActive?: boolean;
  readOnly?: boolean;
  recordedScan?: Array<{ x: number; y: number }>;
}

interface Viewport {
  zoom: number;
  panX: number;
  panY: number;
}

const MIN_ZOOM = 0.6;
const MAX_ZOOM = 8;

export function MapView({ snapshot, selectedGoal, onGoalSelect, trajectory = [], mappingActive = false, readOnly = false, recordedScan = [] }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Viewport>({ zoom: 1, panX: 0, panY: 0 });
  const drag = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    panX: number;
    panY: number;
    moved: boolean;
  } | null>(null);
  const [size, setSize] = useState({ width: 800, height: 560 });

  const mapBitmap = useMemo(() => {
    const map = snapshot.map;
    if (!map || map.width === 0 || map.height === 0) return null;
    const canvas = document.createElement("canvas");
    canvas.width = map.width;
    canvas.height = map.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    const image = ctx.createImageData(map.width, map.height);
    for (let i = 0; i < map.data.length; i += 1) {
      const occupancy = map.data[i] ?? -1;
      let shade = 35;
      if (occupancy < 0) shade = 47;
      else if (occupancy >= 65) shade = 18;
      else if (occupancy <= 25) shade = 235;
      else shade = Math.round(235 - (occupancy / 100) * 180);
      const row = Math.floor(i / map.width);
      const col = i % map.width;
      const y = map.height - 1 - row;
      const p = (y * map.width + col) * 4;
      image.data[p] = shade;
      image.data[p + 1] = shade;
      image.data[p + 2] = shade;
      image.data[p + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
    return canvas;
  }, [snapshot.map]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const rect = entry.contentRect;
      setSize({ width: Math.max(320, rect.width), height: Math.max(360, rect.height) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = ref.current;
    const map = snapshot.map;
    if (!canvas || !map || !mapBitmap) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(size.width * dpr);
    canvas.height = Math.round(size.height * dpr);
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.width, size.height);
    ctx.fillStyle = "#0a1118";
    ctx.fillRect(0, 0, size.width, size.height);

    const fitScale = Math.min(size.width / map.width, size.height / map.height) * 0.94;
    const scale = fitScale * viewport.zoom;
    const offsetX = size.width / 2 - (map.width * scale) / 2 + viewport.panX;
    const offsetY = size.height / 2 - (map.height * scale) / 2 + viewport.panY;

    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(mapBitmap, offsetX, offsetY, map.width * scale, map.height * scale);

    if (viewport.zoom >= 1.7) {
      const cellStep = Math.max(1, Math.round(1 / map.resolution));
      ctx.save();
      ctx.strokeStyle = "rgba(76, 116, 148, 0.10)";
      ctx.lineWidth = 1;
      for (let col = 0; col <= map.width; col += cellStep) {
        const gx = offsetX + col * scale;
        ctx.beginPath();
        ctx.moveTo(gx, offsetY);
        ctx.lineTo(gx, offsetY + map.height * scale);
        ctx.stroke();
      }
      for (let row = 0; row <= map.height; row += cellStep) {
        const gy = offsetY + row * scale;
        ctx.beginPath();
        ctx.moveTo(offsetX, gy);
        ctx.lineTo(offsetX + map.width * scale, gy);
        ctx.stroke();
      }
      ctx.restore();
    }

    ctx.strokeStyle = "rgba(120, 155, 184, 0.24)";
    ctx.lineWidth = 1;
    ctx.strokeRect(offsetX, offsetY, map.width * scale, map.height * scale);

    const worldToScreen = (pose: Pose2D) => {
      const dx = pose.x - map.origin.x;
      const dy = pose.y - map.origin.y;
      const c = Math.cos(-map.origin.yaw);
      const s = Math.sin(-map.origin.yaw);
      const mapX = c * dx - s * dy;
      const mapY = s * dx + c * dy;
      return {
        x: offsetX + (mapX / map.resolution) * scale,
        y: offsetY + (map.height - mapY / map.resolution) * scale,
      };
    };

    const drawPath = (poses: Pose2D[], strokeStyle: string, width: number) => {
      if (poses.length < 2) return;
      ctx.beginPath();
      poses.forEach((pose, index) => {
        const point = worldToScreen(pose);
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.strokeStyle = strokeStyle;
      ctx.lineWidth = width;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();
    };

    if (mappingActive && trajectory.length > 1) {
      drawPath(trajectory, "rgba(255, 171, 64, 0.95)", 3);
    }
    drawPath(snapshot.global_path, "rgba(58, 167, 255, 0.95)", 3);
    drawPath(snapshot.local_path, "rgba(87, 226, 176, 0.95)", 2);

    if (selectedGoal) {
      const goal = worldToScreen(selectedGoal);
      ctx.save();
      ctx.translate(goal.x, goal.y);
      ctx.shadowColor = "rgba(255, 209, 102, 0.8)";
      ctx.shadowBlur = 14;
      ctx.strokeStyle = "#ffd166";
      ctx.fillStyle = "rgba(255, 209, 102, 0.15)";
      ctx.lineWidth = 2.4;
      ctx.beginPath();
      ctx.arc(0, 0, 13, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.beginPath();
      ctx.arc(0, 0, 4, 0, Math.PI * 2);
      ctx.fillStyle = "#ffd166";
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(18 * Math.cos(-selectedGoal.yaw), -18 * Math.sin(-selectedGoal.yaw));
      ctx.stroke();
      ctx.restore();
    }

    for (const sample of recordedScan) {
      const point = worldToScreen({ ...sample, yaw: 0 });
      ctx.fillStyle = "#62e6c4";
      ctx.fillRect(point.x - 1.5, point.y - 1.5, 3, 3);
    }

    if (snapshot.pose) {
      const point = worldToScreen(snapshot.pose);
      ctx.save();
      ctx.translate(point.x, point.y);
      ctx.rotate(-(snapshot.pose.yaw - map.origin.yaw));
      ctx.shadowColor = "rgba(255, 61, 113, 0.72)";
      ctx.shadowBlur = 18;
      ctx.fillStyle = "rgba(255, 61, 113, 0.18)";
      ctx.beginPath();
      ctx.arc(0, 0, 18, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = "#ff3d71";
      ctx.strokeStyle = "#fff1f6";
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.roundRect(-11, -9, 22, 18, 6);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#ffd166";
      ctx.beginPath();
      ctx.moveTo(20, 0);
      ctx.lineTo(7, -6);
      ctx.lineTo(7, 6);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,.75)";
      ctx.beginPath();
      ctx.arc(0, 0, 4, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }, [mapBitmap, mappingActive, selectedGoal, size, snapshot.global_path, snapshot.local_path, snapshot.map, snapshot.pose, trajectory, viewport, recordedScan]);

  function screenToWorld(clientX: number, clientY: number): Pose2D | null {
    const canvas = ref.current;
    const map = snapshot.map;
    if (!canvas || !map) return null;
    const rect = canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const fitScale = Math.min(rect.width / map.width, rect.height / map.height) * 0.94;
    const scale = fitScale * viewport.zoom;
    const offsetX = rect.width / 2 - (map.width * scale) / 2 + viewport.panX;
    const offsetY = rect.height / 2 - (map.height * scale) / 2 + viewport.panY;
    const px = (x - offsetX) / scale;
    const py = (y - offsetY) / scale;
    if (px < 0 || py < 0 || px > map.width || py > map.height) return null;
    const mapX = px * map.resolution;
    const mapY = (map.height - py) * map.resolution;
    const c = Math.cos(map.origin.yaw);
    const s = Math.sin(map.origin.yaw);
    return {
      x: map.origin.x + c * mapX - s * mapY,
      y: map.origin.y + s * mapX + c * mapY,
      yaw: 0,
    };
  }

  function pointerDown(event: PointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      panX: viewport.panX,
      panY: viewport.panY,
      moved: false,
    };
  }

  function pointerMove(event: PointerEvent<HTMLCanvasElement>) {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    const dx = event.clientX - current.startX;
    const dy = event.clientY - current.startY;
    if (Math.hypot(dx, dy) > 4) current.moved = true;
    if (current.moved) {
      setViewport((value) => ({ ...value, panX: current.panX + dx, panY: current.panY + dy }));
    }
  }

  function pointerUp(event: PointerEvent<HTMLCanvasElement>) {
    const current = drag.current;
    if (!current || current.pointerId !== event.pointerId) return;
    if (!current.moved && !readOnly) {
      const goal = screenToWorld(event.clientX, event.clientY);
      if (goal) onGoalSelect(goal);
    }
    drag.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function wheel(event: WheelEvent<HTMLCanvasElement>) {
    event.preventDefault();
    const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    setViewport((value) => ({
      ...value,
      zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value.zoom * factor)),
    }));
  }

  return (
    <div className="map-view" ref={containerRef}>
      <canvas
        ref={ref}
        className="map-canvas interactive"
        aria-label={readOnly ? "Recorded occupancy map with robot trajectory" : "Interactive robot occupancy map"}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerUp}
        onPointerCancel={() => { drag.current = null; }}
        onWheel={wheel}
      />
      <div className="map-toolbar" aria-label="Map controls">
        <button className="map-tool" aria-label="Zoom in" onClick={() => setViewport((v) => ({ ...v, zoom: Math.min(MAX_ZOOM, v.zoom * 1.25) }))}>+</button>
        <button className="map-tool" aria-label="Zoom out" onClick={() => setViewport((v) => ({ ...v, zoom: Math.max(MIN_ZOOM, v.zoom / 1.25) }))}>−</button>
        <button className="map-tool fit" aria-label="Fit map to view" onClick={() => setViewport({ zoom: 1, panX: 0, panY: 0 })}>Fit</button>
      </div>
      <div className="map-legend">
        <span><i className="legend robot" />robot</span>
        {mappingActive && <span><i className="legend trail" />{readOnly ? "recorded trajectory" : "travel trail"}</span>}
        {readOnly && <span style={{ color: "#62e6c4" }}>recorded LiDAR</span>}
        {!readOnly && <span><i className="legend global" />global path</span>}
        {!readOnly && <span><i className="legend local" />local path</span>}
        {!readOnly && <span><i className="legend goal" />selected goal</span>}
      </div>
      <p className="map-hint">{readOnly ? "Recorded map · ROS metres · drag to pan · wheel to zoom" : "Click to choose a goal · drag to pan · wheel to zoom"}</p>
    </div>
  );
}
