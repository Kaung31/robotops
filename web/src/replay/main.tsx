import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { DATASETS, datasetId, loadDatasetV2, loadManifestV2 } from "./data-v2";
import { isWarehouseId, loadWarehouseDataset, loadWarehouseManifest, WAREHOUSE, WAREHOUSE_IDS, warehouseLabel } from "./data-warehouse";
import { createSelection, type LabId, type Selection } from "./selection";
import type { Originals } from "./comparison";
import type { WarehouseOriginals } from "./warehouse-comparison";
import { ComparisonPanel } from "./ComparisonPanel";
import { WarehouseComparisonPanel } from "./WarehouseComparisonPanel";
import { WarehouseBanner } from "./WarehouseBanner";
import { ReplayLab } from "./ReplayLab";
import "../styles.css";
import "./replay.css";

declare const __ROBOTOPS_SITE__: boolean;
const site = typeof __ROBOTOPS_SITE__ !== "undefined" && __ROBOTOPS_SITE__;
const navigation = site ? <nav className="site-return" aria-label="Portfolio navigation"><a href="/">← RobotOps overview</a><span>Private release candidate · not published</span></nav> : undefined;
// Visitor defaults for the warehouse mission mirror the original pose policy limits.
const WAREHOUSE_CRITERIA = { duration: "140", xy: "0.2", yaw: "0.25" };
const labId = (value: string): LabId => isWarehouseId(value) ? value : datasetId(value);
const loadLab = (id: LabId, signal: AbortSignal) => isWarehouseId(id) ? loadWarehouseDataset(id, fetch, signal) : loadDatasetV2(id, fetch, signal);

function App() {
  const [state, setState] = useState<Selection>({ id: "W01", generation: 0, phase: "loading", data: null, error: null });
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
  const [warehouse, setWarehouse] = useState<WarehouseOriginals>({}), [warehouseError, setWarehouseError] = useState("");
  useEffect(() => {
    const controller = createSelection(loadLab, setState);
    selection.current = controller; void controller.select("W01");
    return () => { controller.dispose(); selection.current = null; };
  }, []);
  useEffect(() => {
    const abort = new AbortController(); let stopped = false;
    // Comparisons read pinned original metadata only; one active playback scene.
    Promise.all([loadManifestV2("N0", fetch, abort.signal), loadManifestV2("N2", fetch, abort.signal)])
      .then(([N0, N2]) => { if (!stopped) { setOriginals({ N0, N2 }); setComparisonError(""); } })
      .catch((error: Error) => { if (!stopped) { setOriginals({}); setComparisonError(error.message); } });
    Promise.all(WAREHOUSE_IDS.map(id => loadWarehouseManifest(id, fetch, abort.signal)))
      .then(manifests => { if (!stopped) { setWarehouse(Object.fromEntries(manifests.map(m => [m.dataset_id, m]))); setWarehouseError(""); } })
      .catch((error: Error) => { if (!stopped) { setWarehouse({}); setWarehouseError(error.message); } });
    return () => { stopped = true; abort.abort(); };
  }, []);
  const benchmark = isWarehouseId(state.id);
  const selector = <section className="experiment-selector" aria-label="Experiment selection"><label htmlFor="experiment-select">Recorded experiment</label><select id="experiment-select" value={state.id} onChange={e => { restoreSelectionFocus.current = true; void selection.current?.select(labId(e.target.value)); }}>
    <optgroup label="Warehouse benchmark v1 · exploratory">{WAREHOUSE_IDS.map(id => <option key={id} value={id}>{warehouseLabel(id)}</option>)}</optgroup>
    <optgroup label="Earlier baselines · control pad">{Object.entries(DATASETS).map(([id, value]) => <option key={id} value={id}>{value.label}</option>)}</optgroup>
  </select><span>{benchmark ? "Six trials · two Nav2 configurations · frozen AB/BA/AB order" : "Same documented configuration · separate recorded runs"}</span></section>;
  const comparison = benchmark
    ? <WarehouseComparisonPanel originals={warehouse} error={warehouseError} selected={state.id as keyof typeof WAREHOUSE} />
    : <ComparisonPanel originals={originals} error={comparisonError} />;
  if (state.phase !== "ready") return <main className="replay-lab">{navigation}<header className="lab-header"><h1>RobotOps / Recorded Lab</h1><span className="recorded-badge">Private · Read-only</span></header>{selector}
    <section className="loading-experiment" aria-live="polite"><h2>{state.phase === "error" ? `${state.id} unavailable` : `Loading ${state.id}`}</h2>
    <p role={state.phase === "error" ? "alert" : "status"}>{state.error ?? "Checking the pinned manifest, source identities and asset hashes…"}</p><p>Playback paused; previous robot, LiDAR, trajectory and visitor results cleared. No live-backend or stale-data fallback.</p></section>{comparison}</main>;
  const data = state.data;
  const banner = data.manifest.schema_version === 3 ? <WarehouseBanner manifest={data.manifest} /> : undefined;
  const hash = isWarehouseId(state.id) ? WAREHOUSE[state.id].hash : DATASETS[state.id].hash;
  return <ReplayLab key={`${state.id}:${state.generation}`} data={data} navigation={navigation} selector={selector} comparison={comparison} banner={banner} manifestHash={hash} criteria={benchmark ? WAREHOUSE_CRITERIA : undefined} />;
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
