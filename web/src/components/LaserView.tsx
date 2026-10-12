import { useEffect, useRef } from "react";
import type { ScanPoint } from "../lib/types";

export function LaserView({ points }: { points: ScanPoint[] }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const size = 360;
    canvas.width = size;
    canvas.height = size;
    ctx.clearRect(0, 0, size, size);
    ctx.fillStyle = "#111a23";
    ctx.fillRect(0, 0, size, size);
    const maxRadius = Math.max(1, ...points.map((p) => Math.hypot(p.x, p.y)));
    const scale = (size * 0.44) / maxRadius;
    ctx.strokeStyle = "#2c4055";
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, size * 0.44, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "#79e2c0";
    for (const p of points) {
      ctx.fillRect(size / 2 + p.x * scale, size / 2 - p.y * scale, 2, 2);
    }
    ctx.fillStyle = "#ff3d71";
    ctx.beginPath();
    ctx.arc(size / 2, size / 2, 4, 0, Math.PI * 2);
    ctx.fill();
  }, [points]);

  return <canvas ref={ref} className="laser-canvas" aria-label="LiDAR scan in sensor frame" />;
}
