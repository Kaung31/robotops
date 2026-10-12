import { FormEvent, useEffect, useState } from "react";
import { cancelMission, submitMission } from "../lib/api";
import type { ConnectionState, Pose2D, RuntimeMode } from "../lib/types";

interface Props {
  mode: RuntimeMode;
  connection: ConnectionState;
  selectedGoal: Pose2D | null;
  navigationReady: boolean;
}

export function MissionPanel({ mode, connection, selectedGoal, navigationReady }: Props) {
  const [x, setX] = useState("1.0");
  const [y, setY] = useState("0.0");
  const [yaw, setYaw] = useState("0.0");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const mutatingDisabled = mode === "replay" || mode === "unknown";
  const startDisabled = mutatingDisabled || connection !== "connected" || !navigationReady;

  useEffect(() => {
    if (!selectedGoal) return;
    setX(selectedGoal.x.toFixed(2));
    setY(selectedGoal.y.toFixed(2));
    setYaw(selectedGoal.yaw.toFixed(2));
    setMessage("Goal selected from map. Review coordinates, then send.");
  }, [selectedGoal]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const result = await submitMission(Number(x), Number(y), Number(yaw));
      setRequestId(result.request_id);
      setMessage(result.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Mission request failed");
    }
  }

  async function cancel() {
    if (!requestId) return;
    try {
      const result = await cancelMission(requestId);
      setMessage(result.message);
      if (result.confirmed) setRequestId(null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Cancellation failed");
    }
  }

  return (
    <section className="panel">
      <h2>Mission control</h2>
      {mode === "replay" && <p className="warning">Replay is read-only.</p>}
      {!navigationReady && mode !== "replay" && <p className="warning">Navigation is not ready yet. Wait for localization and Nav2 lifecycle activation.</p>}
      <form onSubmit={submit} className="mission-form">
        <label>X <input value={x} onChange={(e) => setX(e.target.value)} inputMode="decimal" /></label>
        <label>Y <input value={y} onChange={(e) => setY(e.target.value)} inputMode="decimal" /></label>
        <label>Yaw <input value={yaw} onChange={(e) => setYaw(e.target.value)} inputMode="decimal" /></label>
        <button disabled={startDisabled}>Send goal</button>
      </form>
      <button className="secondary" disabled={!requestId || mutatingDisabled} onClick={cancel}>Cancel active web mission</button>
      {message && <p className="message">{message}</p>}
    </section>
  );
}
