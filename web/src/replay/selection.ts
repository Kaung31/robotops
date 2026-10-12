import { type DatasetId, type DatasetV2 } from "./data-v2";
export type Selection = { id: DatasetId; generation: number } & (
  { phase: "loading"; data: null; error: null } |
  { phase: "ready"; data: DatasetV2; error: null } |
  { phase: "error"; data: null; error: string }
);
// One atomic state publication clears all mounted scene/validation state first.
// Abort is an optimization; the generation check also rejects ignored aborts.
export function createSelection(loader: (id: DatasetId, signal: AbortSignal) => Promise<DatasetV2>, publish: (state: Selection) => void) {
  let generation = 0, disposed = false, request: AbortController | null = null;
  return {
    async select(id: DatasetId) {
      if (disposed) return;
      request?.abort(); request = new AbortController(); const current = ++generation;
      publish({ id, generation: current, phase: "loading", data: null, error: null });
      try {
        const data = await loader(id, request.signal);
        if (!disposed && current === generation) {
          if (data.manifest.dataset_id !== id) throw Error("Selected experiment identity mismatch");
          publish({ id, generation: current, phase: "ready", data, error: null });
        }
      } catch (error) {
        if (!disposed && current === generation) publish({ id, generation: current, phase: "error", data: null, error: error instanceof Error ? error.message : "Experiment unavailable" });
      }
    },
    dispose() { disposed = true; ++generation; request?.abort(); },
  };
}
