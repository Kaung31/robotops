import { useEffect, useMemo, useRef, useState } from "react";
import { sendTeleop } from "../lib/api";
import type { ConnectionState, RuntimeMode } from "../lib/types";

type TeleopProfileId = "precision" | "normal" | "fast";

const PROFILES = {
  precision: { label: "Precision", linear: 0.06, reverse: -0.05, angular: 0.18 },
  normal: { label: "Normal", linear: 0.12, reverse: -0.10, angular: 0.35 },
  fast: { label: "Fast", linear: 0.18, reverse: -0.15, angular: 0.48 },
} satisfies Record<TeleopProfileId, { label: string; linear: number; reverse: number; angular: number }>;

export function TeleopPanel({ mode, connection }: { mode: RuntimeMode; connection: ConnectionState }) {
  const [message, setMessage] = useState<string | null>(null);
  const [profileId, setProfileId] = useState<TeleopProfileId>("normal");
  const timer = useRef<number | null>(null);
  const disabled = mode === "replay" || mode === "unknown" || connection !== "connected";
  const profile = useMemo(() => PROFILES[profileId], [profileId]);

  async function command(linearX: number, angularZ: number) {
    try {
      await sendTeleop(linearX, angularZ);
      setMessage(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Teleop failed");
    }
  }

  function stopTimer() {
    if (timer.current !== null) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
  }

  function begin(linearX: number, angularZ: number) {
    if (disabled) return;
    stopTimer();
    void command(linearX, angularZ);
    timer.current = window.setInterval(() => void command(linearX, angularZ), 100);
  }

  function release() {
    stopTimer();
    if (!disabled) void command(0, 0);
  }

  useEffect(() => () => {
    stopTimer();
    void sendTeleop(0, 0).catch(() => undefined);
  }, []);

  const hold = (linearX: number, angularZ: number) => ({
    onPointerDown: () => begin(linearX, angularZ),
    onPointerUp: release,
    onPointerCancel: release,
    onPointerLeave: release,
  });

  return (
    <section className="panel compact-panel">
      <div className="panel-heading teleop-heading">
        <div><h2>Teleoperation</h2><p className="muted">Press and hold. Release sends stop.</p></div>
        <span className="teleop-profile-readout">{profile.label}</span>
      </div>
      <div className="teleop-profiles" role="group" aria-label="Teleoperation speed profile">
        {(Object.keys(PROFILES) as TeleopProfileId[]).map((id) => (
          <button
            type="button"
            key={id}
            className={profileId === id ? "selected" : "ghost"}
            disabled={disabled}
            onClick={() => setProfileId(id)}
          >{PROFILES[id].label}</button>
        ))}
      </div>
      <p className="teleop-limits">Linear {profile.linear.toFixed(2)} m/s · turn {profile.angular.toFixed(2)} rad/s · acceleration remains controller-limited.</p>
      <div className="teleop-grid">
        <button disabled={disabled} {...hold(profile.linear, 0)}>Forward</button>
        <button disabled={disabled} {...hold(0, profile.angular)}>Left</button>
        <button className="danger" disabled={disabled} onClick={() => void command(0, 0)}>Stop</button>
        <button disabled={disabled} {...hold(0, -profile.angular)}>Right</button>
        <button disabled={disabled} {...hold(profile.reverse, 0)}>Reverse</button>
      </div>
      {message && <p className="warning">{message}</p>}
    </section>
  );
}
