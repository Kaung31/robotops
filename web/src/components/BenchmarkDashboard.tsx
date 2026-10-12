import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { clearMissionRuns, loadMissionRuns, mergeMissionRuns, type MissionRunRecord } from "../lib/runHistory";
import { loadRunAnnotations, mergeRunAnnotations, removeOrphanedRunAnnotations, saveRunAnnotation, type RunAnnotation } from "../lib/runAnnotations";

function download(name: string, contents: string, type: string) {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

const EMPTY_ANNOTATION: RunAnnotation = { note: "", tags: [], pinned: false };

export function BenchmarkDashboard() {
  const [runs, setRuns] = useState<MissionRunRecord[]>(() => loadMissionRuns());
  const [annotations, setAnnotations] = useState<Record<string, RunAnnotation>>(() => loadRunAnnotations());
  const [mapFilter, setMapFilter] = useState("all");
  const [profileFilter, setProfileFilter] = useState("all");
  const [outcomeFilter, setOutcomeFilter] = useState("all");
  const [showPinnedOnly, setShowPinnedOnly] = useState(false);
  const [importMessage, setImportMessage] = useState("");
  const [editingRun, setEditingRun] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const refreshRuns = () => setRuns(loadMissionRuns());
    const refreshAnnotations = () => setAnnotations(loadRunAnnotations());
    window.addEventListener("robotops-runs-changed", refreshRuns);
    window.addEventListener("robotops-run-annotations-changed", refreshAnnotations);
    return () => {
      window.removeEventListener("robotops-runs-changed", refreshRuns);
      window.removeEventListener("robotops-run-annotations-changed", refreshAnnotations);
    };
  }, []);

  const maps = useMemo(() => [...new Set(runs.map((run) => run.mapId))].sort(), [runs]);
  const profilesList = useMemo(() => [...new Set(runs.map((run) => run.navigationProfile))].sort(), [runs]);

  const filteredRuns = useMemo(() => runs.filter((run) => {
    if (mapFilter !== "all" && run.mapId !== mapFilter) return false;
    if (profileFilter !== "all" && run.navigationProfile !== profileFilter) return false;
    if (outcomeFilter !== "all" && run.outcome !== outcomeFilter) return false;
    if (showPinnedOnly && !annotations[run.id]?.pinned) return false;
    return true;
  }), [runs, annotations, mapFilter, profileFilter, outcomeFilter, showPinnedOnly]);

  const groupedProfiles = useMemo(() => {
    const groups = new Map<string, MissionRunRecord[]>();
    for (const run of filteredRuns) {
      const key = `${run.mapId}::${run.navigationProfile}`;
      groups.set(key, [...(groups.get(key) ?? []), run]);
    }
    return [...groups.entries()].map(([key, items]) => {
      const [mapId, profile] = key.split("::", 2);
      const successful = items.filter((item) => item.outcome === "succeeded");
      return {
        key,
        mapId,
        profile,
        count: items.length,
        successfulCount: successful.length,
        success: items.length ? (100 * successful.length) / items.length : 0,
        duration: successful.length ? successful.reduce((sum, item) => sum + item.durationS, 0) / successful.length : null,
        distance: successful.length ? successful.reduce((sum, item) => sum + item.distanceM, 0) / successful.length : null,
      };
    }).sort((a, b) => a.mapId.localeCompare(b.mapId) || b.success - a.success || (a.duration ?? Number.POSITIVE_INFINITY) - (b.duration ?? Number.POSITIVE_INFINITY));
  }, [filteredRuns]);

  const leaders = useMemo(() => {
    // "Best profile" is an overall benchmark statistic. Outcome / pin / profile filters
    // must not turn it into a filtered, potentially misleading 100%-success view.
    const sourceRuns = runs.filter((run) => mapFilter === "all" || run.mapId === mapFilter);
    const groups = new Map<string, MissionRunRecord[]>();
    for (const run of sourceRuns) {
      const key = `${run.mapId}::${run.navigationProfile}`;
      groups.set(key, [...(groups.get(key) ?? []), run]);
    }
    const best = new Map<string, { mapId: string; profile: string; success: number; duration: number | null }>();
    for (const [key, items] of groups) {
      const [mapId, profile] = key.split("::", 2);
      const successful = items.filter((item) => item.outcome === "succeeded");
      const candidate = {
        mapId,
        profile,
        success: items.length ? (100 * successful.length) / items.length : 0,
        duration: successful.length ? successful.reduce((sum, item) => sum + item.durationS, 0) / successful.length : null,
      };
      const current = best.get(mapId);
      if (!current || candidate.success > current.success || (candidate.success === current.success && (candidate.duration ?? Infinity) < (current.duration ?? Infinity))) {
        best.set(mapId, candidate);
      }
    }
    return [...best.values()];
  }, [runs, mapFilter]);

  const summary = useMemo(() => {
    const successful = filteredRuns.filter((run) => run.outcome === "succeeded");
    return {
      total: filteredRuns.length,
      successful: successful.length,
      successRate: filteredRuns.length ? (100 * successful.length) / filteredRuns.length : 0,
      avgDuration: successful.length ? successful.reduce((sum, run) => sum + run.durationS, 0) / successful.length : null,
      avgDistance: successful.length ? successful.reduce((sum, run) => sum + run.distanceM, 0) / successful.length : null,
      pinned: filteredRuns.filter((run) => annotations[run.id]?.pinned).length,
    };
  }, [filteredRuns, annotations]);

  function exportJson() {
    const exportedAnnotations = Object.fromEntries(Object.entries(annotations).filter(([id]) => runs.some((run) => run.id === id)));
    download("robotops-mission-runs.json", JSON.stringify({
      schema_version: 2,
      exported_at: new Date().toISOString(),
      runs,
      annotations: exportedAnnotations,
    }, null, 2), "application/json");
  }
  function exportCsv() {
    const head = "started_at,outcome,profile,map,duration_s,distance_m,waypoints,run_id,tags,note";
    const rows = runs.map((r) => {
      const annotation = annotations[r.id] ?? EMPTY_ANNOTATION;
      return [r.startedAt, r.outcome, r.navigationProfile, r.mapId, r.durationS.toFixed(3), r.distanceM.toFixed(3), r.waypointCount, r.runId ?? "", annotation.tags.join("|"), annotation.note]
        .map((v) => `"${String(v).replaceAll('"', '""')}"`).join(",");
    });
    download("robotops-mission-runs.csv", [head, ...rows].join("\n"), "text/csv");
  }

  async function importJson(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      let importedRuns: unknown = parsed;
      let importedAnnotations: unknown = undefined;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        const envelope = parsed as { runs?: unknown; annotations?: unknown };
        if (!Array.isArray(envelope.runs)) throw new Error("Benchmark JSON must contain a runs array.");
        importedRuns = envelope.runs;
        importedAnnotations = envelope.annotations;
      }
      const next = mergeMissionRuns(importedRuns);
      const nextAnnotations = mergeRunAnnotations(importedAnnotations, new Set(next.map((run) => run.id)));
      setRuns(next);
      setAnnotations(nextAnnotations);
      setImportMessage(`Imported benchmark history. ${next.length} run${next.length === 1 ? "" : "s"} available.`);
    } catch (error) {
      setImportMessage(error instanceof Error ? error.message : "Benchmark import failed.");
    }
  }

  function updateAnnotation(runId: string, patch: Partial<RunAnnotation>) {
    const current = annotations[runId] ?? EMPTY_ANNOTATION;
    const next = saveRunAnnotation(runId, { ...current, ...patch });
    setAnnotations(next);
  }

  function clearAll() {
    if (!window.confirm("Clear benchmark history stored in this browser? Export first if you want a backup.")) return;
    clearMissionRuns();
    removeOrphanedRunAnnotations(new Set());
    setRuns([]);
    setAnnotations({});
  }

  return (
    <section className="panel benchmark-panel">
      <div className="panel-heading benchmark-heading">
        <div><h2>Navigation benchmark</h2><span className="muted">Browser mission history · approximate metrics · comparisons stay separated by map</span></div>
        <div className="benchmark-actions">
          <button type="button" className="secondary" disabled={!runs.length} onClick={exportCsv}>Export CSV</button>
          <button type="button" className="secondary" disabled={!runs.length} onClick={exportJson}>Export JSON</button>
          <button type="button" className="secondary" onClick={() => fileRef.current?.click()}>Import JSON</button>
          <button type="button" className="ghost" disabled={!runs.length} onClick={clearAll}>Clear</button>
          <input ref={fileRef} className="hidden-file-input" type="file" accept="application/json,.json" onChange={importJson} />
        </div>
      </div>

      {importMessage && <p className="benchmark-message">{importMessage}</p>}

      <div className="benchmark-filters">
        <label>Map<select value={mapFilter} onChange={(e) => setMapFilter(e.target.value)}><option value="all">All maps</option>{maps.map((map) => <option key={map} value={map}>{map}</option>)}</select></label>
        <label>Profile<select value={profileFilter} onChange={(e) => setProfileFilter(e.target.value)}><option value="all">All profiles</option>{profilesList.map((profile) => <option key={profile} value={profile}>{profile}</option>)}</select></label>
        <label>Result<select value={outcomeFilter} onChange={(e) => setOutcomeFilter(e.target.value)}><option value="all">All results</option><option value="succeeded">Succeeded</option><option value="failed">Failed</option><option value="canceled">Canceled</option><option value="cancellation_unconfirmed">Cancellation unconfirmed</option><option value="result_unavailable">Result unavailable</option></select></label>
        <label className="pinned-filter"><input type="checkbox" checked={showPinnedOnly} onChange={(e) => setShowPinnedOnly(e.target.checked)} /> Pinned only</label>
      </div>

      <div className="benchmark-summary">
        <article><span>Runs</span><strong>{summary.total}</strong></article>
        <article><span>Success</span><strong>{summary.successRate.toFixed(0)}%</strong></article>
        <article><span>Avg time</span><strong>{summary.avgDuration === null ? "—" : `${summary.avgDuration.toFixed(1)} s`}</strong></article>
        <article><span>Avg distance</span><strong>{summary.avgDistance === null ? "—" : `${summary.avgDistance.toFixed(2)} m`}</strong></article>
        <article><span>Pinned</span><strong>{summary.pinned}</strong></article>
      </div>

      {leaders.length > 0 && <div className="benchmark-leaders">
        {leaders.map((item) => <article key={`leader-${item.mapId}`}><span>Overall best on {item.mapId}</span><strong>{item.profile}</strong><small>{item.success.toFixed(0)}% success{item.duration === null ? "" : ` · ${item.duration.toFixed(1)} s avg`}</small></article>)}
      </div>}

      {groupedProfiles.length ? <div className="profile-comparison">
        {groupedProfiles.map((item) => <article key={item.key}><span>{item.mapId} · {item.profile}</span><strong>{item.success.toFixed(0)}% success</strong><small>{item.count} runs · {item.successfulCount} succeeded · {item.duration === null ? "—" : `${item.duration.toFixed(1)} s avg`} · {item.distance === null ? "—" : `${item.distance.toFixed(2)} m avg`}</small></article>)}
      </div> : <p className="muted">Complete missions or adjust filters to populate benchmark results.</p>}

      <div className="run-table-wrap">
        <table className="run-table extended-run-table">
          <thead><tr><th>Pin</th><th>Result</th><th>Profile</th><th>Map</th><th>Time</th><th>Distance</th><th>Goals</th><th>Notes</th></tr></thead>
          <tbody>{filteredRuns.slice(0, 30).map((run) => {
            const annotation = annotations[run.id] ?? EMPTY_ANNOTATION;
            const editing = editingRun === run.id;
            return <tr key={run.id}>
              <td><button type="button" className={`pin-button ${annotation.pinned ? "selected" : ""}`} aria-label={annotation.pinned ? "Unpin run" : "Pin run"} onClick={() => updateAnnotation(run.id, { pinned: !annotation.pinned })}>{annotation.pinned ? "★" : "☆"}</button></td>
              <td><span className={`outcome ${run.outcome}`}>{run.outcome}</span></td>
              <td>{run.navigationProfile}</td><td>{run.mapId}</td><td>{run.durationS.toFixed(1)} s</td><td>{run.distanceM.toFixed(2)} m</td><td>{run.waypointCount}</td>
              <td className="run-note-cell">{editing ? <div className="annotation-editor"><input aria-label="Run tags" placeholder="tags, comma separated" defaultValue={annotation.tags.join(", ")} id={`tags-${run.id}`} /><textarea aria-label="Run note" placeholder="Optional note" defaultValue={annotation.note} id={`note-${run.id}`} /><div><button type="button" className="secondary tiny" onClick={() => {
                const tagsInput = document.getElementById(`tags-${run.id}`) as HTMLInputElement | null;
                const noteInput = document.getElementById(`note-${run.id}`) as HTMLTextAreaElement | null;
                updateAnnotation(run.id, { tags: (tagsInput?.value ?? "").split(",").map((tag) => tag.trim()).filter(Boolean), note: noteInput?.value ?? "" });
                setEditingRun(null);
              }}>Save</button><button type="button" className="ghost tiny" onClick={() => setEditingRun(null)}>Cancel</button></div></div> : <button type="button" className="annotation-preview" onClick={() => setEditingRun(run.id)}>{annotation.tags.length ? annotation.tags.map((tag) => `#${tag}`).join(" ") : annotation.note ? annotation.note : "Add note"}</button>}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
    </section>
  );
}
