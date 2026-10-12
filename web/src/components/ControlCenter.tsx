import { useEffect, useMemo, useState } from "react";
import type { ControlOptions, MapArtifact, StackMode, StackRequest, StackStatus } from "../lib/types";

interface Props {
  options: ControlOptions;
  stack: StackStatus;
  busy: boolean;
  onStart: (request: StackRequest) => Promise<void>;
  onStop: () => Promise<void>;
  onOpenRviz: () => Promise<void>;
  onCloseRviz: () => Promise<void>;
  onSaveMap: (name: string, overwrite?: boolean) => Promise<MapArtifact | null>;
}

function mapSortValue(item: MapArtifact): bigint {
  try { return BigInt(item.created_at_ns ?? "0"); } catch { return 0n; }
}

function formatCreated(item: MapArtifact): string {
  if (!item.created_at_ns) return "Unknown creation time";
  try {
    const milliseconds = Number(BigInt(item.created_at_ns) / 1_000_000n);
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(milliseconds));
  } catch {
    return "Unknown creation time";
  }
}

function sizeLabel(item: MapArtifact): string | null {
  if (!item.width || !item.height || !item.resolution) return null;
  return `${(item.width * item.resolution).toFixed(1)} × ${(item.height * item.resolution).toFixed(1)} m`;
}

function suggestedMapName(world: string, maps: MapArtifact[]): string {
  let version = 1;
  while (maps.some((item) => item.id === `${world}_v${version}`)) version += 1;
  return `${world}_v${version}`;
}

export function ControlCenter({ options, stack, busy, onStart, onStop, onOpenRviz, onCloseRviz, onSaveMap }: Props) {
  const [mode, setMode] = useState<StackMode>("navigation");
  const [world, setWorld] = useState(options.worlds[0]?.id ?? "mapping_lab");
  const [mapId, setMapId] = useState("");
  const [profile, setProfile] = useState(options.navigation_profiles[0]?.id ?? "navfn_rpp");
  const [mapName, setMapName] = useState(() => suggestedMapName(world, options.maps));
  const [showLegacy, setShowLegacy] = useState(false);
  const [lastSavedMapId, setLastSavedMapId] = useState<string | null>(null);
  const [openRvizOnStart, setOpenRvizOnStart] = useState(false);

  const worldMaps = useMemo(
    () => options.maps.filter((item) => item.world_id === world).sort((a, b) => mapSortValue(a) === mapSortValue(b) ? 0 : mapSortValue(a) > mapSortValue(b) ? -1 : 1),
    [options.maps, world],
  );
  const legacyMaps = useMemo(
    () => options.maps.filter((item) => item.world_id === null).sort((a, b) => mapSortValue(a) === mapSortValue(b) ? 0 : mapSortValue(a) > mapSortValue(b) ? -1 : 1),
    [options.maps],
  );
  const selectableMaps = useMemo(
    () => showLegacy ? [...worldMaps, ...legacyMaps] : worldMaps,
    [showLegacy, worldMaps, legacyMaps],
  );

  useEffect(() => {
    if (!options.worlds.some((item) => item.id === world)) setWorld(options.worlds[0]?.id ?? "");
    if (!options.navigation_profiles.some((item) => item.id === profile)) {
      setProfile(options.navigation_profiles[0]?.id ?? "");
    }
  }, [options, world, profile]);

  useEffect(() => {
    if (selectableMaps.some((item) => item.id === mapId)) return;
    const preferred = worldMaps.find((item) => item.id === lastSavedMapId)
      ?? worldMaps.find((item) => item.is_latest)
      ?? worldMaps[0]
      ?? (showLegacy ? legacyMaps[0] : undefined);
    setMapId(preferred?.id ?? "");
  }, [selectableMaps, worldMaps, legacyMaps, mapId, lastSavedMapId, showLegacy]);

  const active = ["starting", "running", "stopping"].includes(stack.state);
  const selectedMap = useMemo(
    () => options.maps.find((item) => item.id === mapId) ?? null,
    [options.maps, mapId],
  );
  const selectedProfile = useMemo(
    () => options.navigation_profiles.find((item) => item.id === profile),
    [options.navigation_profiles, profile],
  );
  const startDisabled = busy || active || !world || (mode === "navigation" && (!mapId || !profile));

  async function start() {
    await onStart({
      mode,
      runtime_mode: "sim",
      world,
      map_id: mode === "navigation" ? mapId : null,
      navigation_profile: mode === "navigation" ? profile : null,
      headless_rendering: false,
      open_rviz: openRvizOnStart,
    });
  }

  function switchMode(next: StackMode) {
    setMode(next);
    if (next === "navigation") {
      setShowLegacy(false);
      const preferred = worldMaps.find((item) => item.id === lastSavedMapId)
        ?? worldMaps.find((item) => item.is_latest)
        ?? worldMaps[0];
      setMapId(preferred?.id ?? "");
    } else {
      setMapName(suggestedMapName(world, options.maps));
    }
  }

  async function saveCurrentMap() {
    const name = mapName.trim();
    if (!name) return;
    const existing = options.maps.find((item) => item.id === name);
    let overwrite = false;
    if (existing) {
      overwrite = window.confirm(`Map '${name}' already exists. Replace it with the current mapping result?`);
      if (!overwrite) return;
    }
    const saved = await onSaveMap(name, overwrite);
    if (saved) {
      setLastSavedMapId(saved.id);
      setMapId(saved.id);
    }
  }

  return (
    <section className="panel control-center">
      <div className="panel-heading">
        <div><p className="eyebrow">CONTROL CENTER</p><h2>Robot stack</h2></div>
        <span className={`stack-state ${stack.state}`}>{stack.state}</span>
      </div>

      <div className="mode-switch" role="group" aria-label="Operating mode">
        <button className={mode === "navigation" ? "selected" : "ghost"} disabled={active} onClick={() => switchMode("navigation")}>Navigation</button>
        <button className={mode === "mapping" ? "selected" : "ghost"} disabled={active} onClick={() => switchMode("mapping")}>Mapping</button>
      </div>

      <div className="control-grid">
        <label>Environment
          <select value={world} disabled={active} onChange={(event) => {
            const nextWorld = event.target.value;
            setWorld(nextWorld);
            setMapId("");
            if (mode === "mapping") setMapName(suggestedMapName(nextWorld, options.maps));
          }}>
            {options.worlds.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.difficulty}</option>)}
          </select>
        </label>
        {mode === "navigation" && <>
          <label>Saved map
            <select value={mapId} disabled={active || selectableMaps.length === 0} onChange={(event) => setMapId(event.target.value)}>
              {selectableMaps.length === 0 && <option value="">No compatible maps</option>}
              {worldMaps.length > 0 && <optgroup label="Maps for this environment">
                {worldMaps.map((item) => (
                  <option key={item.id} value={item.id}>{item.label}{item.is_latest ? " · latest" : ""}</option>
                ))}
              </optgroup>}
              {showLegacy && legacyMaps.length > 0 && <optgroup label="Legacy / unknown environment">
                {legacyMaps.map((item) => <option key={item.id} value={item.id}>{item.label} · legacy</option>)}
              </optgroup>}
            </select>
          </label>
          <label>Navigation profile
            <select value={profile} disabled={active} onChange={(event) => setProfile(event.target.value)}>
              {options.navigation_profiles.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
        </>}
      </div>

      {mode === "navigation" && legacyMaps.length > 0 && (
        <label className="legacy-toggle"><input type="checkbox" checked={showLegacy} disabled={active} onChange={(event) => setShowLegacy(event.target.checked)} />Show legacy maps with unknown environment metadata</label>
      )}

      {mode === "navigation" && selectedMap && (
        <div className="map-library-card">
          <div className="map-preview-shell">
            {selectedMap.preview_url ? <img src={selectedMap.preview_url} alt={`${selectedMap.label} occupancy preview`} /> : <span>No preview</span>}
          </div>
          <div className="map-library-copy">
            <div className="map-title-row"><strong>{selectedMap.label}</strong>{selectedMap.is_latest && <span className="latest-badge">LATEST</span>}{selectedMap.world_id === null && <span className="legacy-badge">LEGACY</span>}</div>
            <span>{selectedMap.world_id ? options.worlds.find((item) => item.id === selectedMap.world_id)?.label ?? selectedMap.world_id : "Unknown source environment"}</span>
            <span>{formatCreated(selectedMap)}</span>
            {sizeLabel(selectedMap) && <span>{sizeLabel(selectedMap)} · {selectedMap.resolution?.toFixed(3)} m/cell</span>}
          </div>
        </div>
      )}

      {mode === "navigation" && selectedProfile && (
        <p className="profile-detail"><strong>{selectedProfile.planner}</strong> planner · <strong>{selectedProfile.controller}</strong> controller</p>
      )}
      <label className="rviz-toggle">
        <input
          type="checkbox"
          checked={openRvizOnStart}
          disabled={active}
          onChange={(event) => setOpenRvizOnStart(event.target.checked)}
        />
        Open RViz engineering view when the stack starts
      </label>

      {mode === "navigation" && worldMaps.length === 0 && !showLegacy && (
        <p className="warning">No map has been saved for this environment yet. Build one in Mapping mode. Legacy maps stay hidden unless you explicitly enable them.</p>
      )}

      <div className="button-row">
        <button disabled={startDisabled} onClick={() => void start()}>Start system</button>
        {stack.state === "running" && !stack.rviz_running && (
          <button className="secondary" disabled={busy} onClick={() => void onOpenRviz()}>Open RViz</button>
        )}
        {stack.state === "running" && stack.rviz_running && (
          <button className="secondary" disabled={busy} onClick={() => void onCloseRviz()}>Close RViz</button>
        )}
        <button className="danger" disabled={busy || !active} onClick={() => void onStop()}>Stop system</button>
      </div>

      {stack.state === "running" && (
        <div className="stack-summary">
          <span>{stack.mode}</span><span>{stack.world}</span>{stack.navigation_profile && <span>{stack.navigation_profile}</span>}
          <span>{stack.processes.join(" + ")}</span>{stack.rviz_running && <span>rviz</span>}
        </div>
      )}
      {stack.error && <p className="warning">{stack.error}</p>}
      {stack.rviz_error && <p className="warning">RViz: {stack.rviz_error}</p>}

      {stack.state === "running" && stack.mode === "mapping" && (
        <div className="save-map-row">
          <label>Save map as <input value={mapName} onChange={(event) => setMapName(event.target.value)} /></label>
          <button className="secondary compact" disabled={busy || !mapName.trim()} onClick={() => void saveCurrentMap()}>Save map</button>
        </div>
      )}
    </section>
  );
}
