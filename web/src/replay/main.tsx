import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { DATASETS, datasetId, loadDatasetV2, loadManifestV2 } from "./data-v2";
import { isWarehouseId, loadWarehouseDataset, loadWarehouseManifest, WAREHOUSE, WAREHOUSE_IDS, warehouseLabel } from "./data-warehouse";
import { createSelection, type LabId, type Selection } from "./selection";
import type { Originals } from "./comparison";
import type { WarehouseOriginals } from "./warehouse-comparison";
import { ComparisonPanel } from "./ComparisonPanel";
import { WarehouseComparison, WarehouseResults } from "./WarehouseComparisonPanel";
import { WarehouseBanner } from "./WarehouseBanner";
import { BaselineBanner, BaselinesSection, ExperimentSection, LabIntro, SectionHeading } from "./LabSections";
import { EvidenceHeading, ReplayHeading, ReplayLab } from "./ReplayLab";
import { SiteFooter, SiteHeader } from "../site/SiteChrome";
import { RELEASE } from "../site/release";
import "../styles.css";
import "../site/site.css";
import "./replay.css";

declare const __ROBOTOPS_SITE__: boolean;
const site = typeof __ROBOTOPS_SITE__ !== "undefined" && __ROBOTOPS_SITE__;
// Visitor defaults for the warehouse mission mirror the original pose policy limits.
const WAREHOUSE_CRITERIA = { duration: "140", xy: "0.2", yaw: "0.25" };
// Every visit opens on the featured first warehouse trial; no selection is stored.
const DEFAULT_ID: LabId = "W01";
const labId = (value: string): LabId => isWarehouseId(value) ? value : datasetId(value);
const loadLab = (id: LabId, signal: AbortSignal) => isWarehouseId(id) ? loadWarehouseDataset(id, fetch, signal) : loadDatasetV2(id, fetch, signal);

function App() {
  const [state, setState] = useState<Selection>({ id: DEFAULT_ID, generation: 0, phase: "loading", data: null, error: null });
  const selection = useRef<ReturnType<typeof createSelection> | null>(null);
  // Element to focus once a visitor-initiated load settles (the scene remounts).
  const restoreFocus = useRef<string | null>(null);
  useEffect(() => {
    if (state.phase !== "loading" && restoreFocus.current) {
      document.getElementById(restoreFocus.current)?.focus({ preventScroll: true });
      restoreFocus.current = null;
    }
  }, [state.phase, state.generation]);
  const [originals, setOriginals] = useState<Originals>({}), [comparisonError, setComparisonError] = useState("");
  const [warehouse, setWarehouse] = useState<WarehouseOriginals>({}), [warehouseError, setWarehouseError] = useState("");
  useEffect(() => {
    const controller = createSelection(loadLab, setState);
    selection.current = controller; void controller.select(DEFAULT_ID);
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
  function choose(id: LabId, focus: string) {
    restoreFocus.current = focus;
    if (id !== state.id || state.phase === "error") void selection.current?.select(id);
    else { document.getElementById(focus)?.focus({ preventScroll: true }); restoreFocus.current = null; }
  }
  // Replay buttons elsewhere on the page load the trial and bring the player into view.
  function replay(id: LabId) {
    document.getElementById("replay")?.scrollIntoView({ block: "start" });
    choose(id, "replay-title");
  }
  const benchmark = isWarehouseId(state.id);
  const selector = <div className="experiment-selector" role="group" aria-label="Experiment selection"><label htmlFor="experiment-select">Recorded trial</label><select id="experiment-select" value={state.id} onChange={e => choose(labId(e.target.value), "experiment-select")}>
    <optgroup label="Warehouse benchmark v1 · exploratory">{WAREHOUSE_IDS.map(id => <option key={id} value={id}>{warehouseLabel(id)}</option>)}</optgroup>
    <optgroup label="Earlier baselines · not part of the benchmark">{Object.entries(DATASETS).map(([id, value]) => <option key={id} value={id}>{value.label}</option>)}</optgroup>
  </select><span>{benchmark ? "Six trials · two Nav2 configurations · run order AB/BA/AB" : "Earlier baseline · same configuration as its repeat · separate recorded runs"}</span></div>;
  const compare = <section id="compare" className="lab-section" aria-labelledby="compare-title">
    <SectionHeading id="compare-title" step={4} eyebrow="Compare configurations" title="NavFn + RPP against Smac 2D + DWB">Each dot is one trial; the vertical tick marks the configuration's mean. Three trials per configuration describe these runs only: there is no winner and no statistical claim.</SectionHeading>
    <WarehouseComparison originals={warehouse} error={warehouseError} />
  </section>;
  const ready = state.phase === "ready" ? state.data : null;
  const banner = ready ? (ready.manifest.schema_version === 3 ? <WarehouseBanner manifest={ready.manifest} /> : <BaselineBanner id={datasetId(state.id)} />) : undefined;
  const hash = isWarehouseId(state.id) ? WAREHOUSE[state.id].hash : DATASETS[state.id].hash;
  return <div className="site-page lab-page"><a className="skip-link" href="#main">Skip to content</a>
    {site && <SiteHeader current="lab" />}
    <main id="main" className="replay-lab">
      <LabIntro status={RELEASE.status} overview={site} />
      <ExperimentSection />
      <section id="results" className="lab-section" aria-labelledby="results-title">
        <SectionHeading id="results-title" step={2} eyebrow="Results" title="Results at a glance">Original outcomes and measurements from the six campaign reports, read from the verified datasets. Choose Replay on any row to watch that trial.</SectionHeading>
        <WarehouseResults originals={warehouse} error={warehouseError} selected={benchmark ? state.id as keyof typeof WAREHOUSE : null} onReplay={replay} />
      </section>
      {ready
        ? <ReplayLab key={`${state.id}:${state.generation}`} data={ready} selector={selector} banner={banner} between={compare} manifestHash={hash} criteria={benchmark ? WAREHOUSE_CRITERIA : undefined} />
        : <>
          <section id="replay" className="lab-section replay-section" aria-labelledby="replay-title"><ReplayHeading id={state.id} />{selector}
            <div className="loading-experiment" aria-live="polite"><h3>{state.phase === "error" ? `${state.id} unavailable` : `Loading ${state.id}`}</h3>
            <p role={state.phase === "error" ? "alert" : "status"}>{state.error ?? "Checking the pinned manifest, source identities and asset hashes…"}</p><p>Playback paused; previous robot, LiDAR, trajectory and visitor results cleared. No live-backend or stale-data fallback.</p></div></section>
          {compare}
          <section id="evidence" className="lab-section evidence-section" aria-labelledby="evidence-title"><EvidenceHeading id={state.id} /><p className="evidence-unavailable">Original results and visitor checks appear once {state.id} has loaded and verified.</p></section>
        </>}
      <BaselinesSection selected={state.id} onReplay={replay}><ComparisonPanel originals={originals} error={comparisonError} /></BaselinesSection>
    </main>
    {site ? <SiteFooter /> : <footer className="lab-local-footer">RobotOps Recorded Lab · {RELEASE.status} · no live robot connection</footer>}
  </div>;
}
createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
