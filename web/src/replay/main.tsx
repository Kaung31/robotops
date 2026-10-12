import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { DATASETS, datasetId, loadDatasetV2, loadManifestV2 } from "./data-v2";
import { createSelection, type Selection } from "./selection";
import type { Originals } from "./comparison";
import { ComparisonPanel } from "./ComparisonPanel";
import { ReplayLab } from "./ReplayLab";
import "../styles.css";
import "./replay.css";

declare const __ROBOTOPS_SITE__: boolean;
const site = typeof __ROBOTOPS_SITE__ !== "undefined" && __ROBOTOPS_SITE__;
const navigation = site ? <nav className="site-return" aria-label="Portfolio navigation"><a href="/">← RobotOps overview</a><span>Private release candidate · not published</span></nav> : undefined;

function App() {
  const [state, setState] = useState<Selection>({ id: "N0", generation: 0, phase: "loading", data: null, error: null });
  const selection = useRef<ReturnType<typeof createSelection> | null>(null);
  const restoreSelectionFocus = useRef(false);
  useEffect(() => {
    // A user selection unmounts the previous scene; restore keyboard position
    // after the latest load/error, without stealing focus on the initial preview.
    if (state.phase !== "loading" && restoreSelectionFocus.current) {
      document.getElementById("experiment-select")?.focus();
      restoreSelectionFocus.current = false;
    }
  }, [state.phase, state.generation]);
  const [originals, setOriginals] = useState<Originals>({}), [comparisonError, setComparisonError] = useState("");
  useEffect(() => {
    const controller = createSelection((id, signal) => loadDatasetV2(id, fetch, signal), setState);
    selection.current = controller; void controller.select("N0");
    return () => { controller.dispose(); selection.current = null; };
  }, []);
  useEffect(() => {
    const abort = new AbortController(); let stopped = false;
    // Comparison reads pinned original metadata only; one active playback scene.
    Promise.all([loadManifestV2("N0", fetch, abort.signal), loadManifestV2("N2", fetch, abort.signal)])
      .then(([N0, N2]) => { if (!stopped) { setOriginals({ N0, N2 }); setComparisonError(""); } })
      .catch((error: Error) => { if (!stopped) { setOriginals({}); setComparisonError(error.message); } });
    return () => { stopped = true; abort.abort(); };
  }, []);
  const selector = <section className="experiment-selector" aria-label="Experiment selection"><label htmlFor="experiment-select">Recorded experiment</label><select id="experiment-select" value={state.id} onChange={e => { restoreSelectionFocus.current = true; void selection.current?.select(datasetId(e.target.value)); }}>
    {Object.entries(DATASETS).map(([id, value]) => <option key={id} value={id}>{value.label}</option>)}
  </select><span>Same documented configuration · separate recorded runs</span></section>;
  const comparison = <ComparisonPanel originals={originals} error={comparisonError} />;
  if (state.phase !== "ready") return <main className="replay-lab">{navigation}<header className="lab-header"><h1>RobotOps / Recorded Lab</h1><span className="recorded-badge">Private · Read-only</span></header>{selector}
    <section className="loading-experiment" aria-live="polite"><h2>{state.phase === "error" ? `${state.id} unavailable` : `Loading ${state.id}`}</h2>
    <p role={state.phase === "error" ? "alert" : "status"}>{state.error ?? "Checking the pinned v2 manifest, source identities and asset hashes…"}</p><p>Playback paused; previous robot, LiDAR, trajectory and visitor results cleared. No live-backend or stale-data fallback.</p></section>{comparison}</main>;
  return <ReplayLab key={`${state.id}:${state.generation}`} data={state.data} navigation={navigation} selector={selector} comparison={comparison} />;
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
