import { useEffect, useState } from "react";
import { getRobot } from "./api";
import type { RobotSnapshot } from "./types";

export function useTelemetry() {
  const [snapshot, setSnapshot] = useState<RobotSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let retryTimer: number | null = null;

    getRobot()
      .then((value) => !stopped && setSnapshot(value))
      .catch((e: Error) => !stopped && setError(e.message));

    const connect = () => {
      if (stopped) return;
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${window.location.host}/api/v1/telemetry/ws`);
      socket.onopen = () => !stopped && setError(null);
      socket.onmessage = (event) => {
        if (!stopped) {
          setSnapshot(JSON.parse(event.data) as RobotSnapshot);
          setError(null);
        }
      };
      socket.onerror = () => !stopped && setError("Telemetry connection error");
      socket.onclose = () => {
        if (stopped) return;
        setError("Telemetry disconnected; reconnecting…");
        retryTimer = window.setTimeout(connect, 1000);
      };
    };

    connect();

    return () => {
      stopped = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  return { snapshot, error };
}
