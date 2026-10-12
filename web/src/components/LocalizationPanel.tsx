import { FormEvent, useState } from "react";
import { setInitialPose } from "../lib/api";
import type { ConnectionState } from "../lib/types";

export function LocalizationPanel({ connection }: { connection: ConnectionState }) {
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  const [yaw, setYaw] = useState("0");
  const [message, setMessage] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const result = await setInitialPose(Number(x), Number(y), Number(yaw));
      setMessage(result.message);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Initial pose failed");
    }
  }

  return (
    <section className="panel compact-panel">
      <h2>Localization</h2>
      <p className="muted">Set AMCL's initial pose in the saved map frame.</p>
      <form onSubmit={submit} className="inline-form">
        <label>X <input value={x} onChange={(e) => setX(e.target.value)} inputMode="decimal" /></label>
        <label>Y <input value={y} onChange={(e) => setY(e.target.value)} inputMode="decimal" /></label>
        <label>Yaw <input value={yaw} onChange={(e) => setYaw(e.target.value)} inputMode="decimal" /></label>
        <button disabled={connection !== "connected"}>Set pose</button>
      </form>
      {message && <p className="message">{message}</p>}
    </section>
  );
}
