export interface RunAnnotation {
  note: string;
  tags: string[];
  pinned: boolean;
}

const KEY = "robotops.missionRunAnnotations.v1";
const EMPTY: RunAnnotation = { note: "", tags: [], pinned: false };

function normalize(value: unknown): RunAnnotation {
  if (!value || typeof value !== "object") return { ...EMPTY };
  const item = value as Partial<RunAnnotation>;
  const tags = Array.isArray(item.tags)
    ? item.tags.filter((tag): tag is string => typeof tag === "string").map((tag) => tag.trim()).filter(Boolean).slice(0, 12)
    : [];
  return {
    note: typeof item.note === "string" ? item.note.slice(0, 500) : "",
    tags: [...new Set(tags)],
    pinned: item.pinned === true,
  };
}

export function loadRunAnnotations(): Record<string, RunAnnotation> {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed as Record<string, unknown>).map(([id, value]) => [id, normalize(value)]));
  } catch {
    return {};
  }
}

export function saveRunAnnotation(runId: string, annotation: RunAnnotation): Record<string, RunAnnotation> {
  const next = { ...loadRunAnnotations(), [runId]: normalize(annotation) };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Annotations are optional metadata; mission operations must remain unaffected.
  }
  window.dispatchEvent(new CustomEvent("robotops-run-annotations-changed"));
  return next;
}

export function mergeRunAnnotations(value: unknown, validRunIds: Set<string>): Record<string, RunAnnotation> {
  if (value === undefined || value === null) return loadRunAnnotations();
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Benchmark annotations must be a JSON object.");
  }
  const current = loadRunAnnotations();
  const imported = Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([id]) => validRunIds.has(id))
      .map(([id, annotation]) => [id, normalize(annotation)]),
  );
  const next = { ...current, ...imported };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Imported annotations are optional metadata; keep the UI usable if storage is unavailable.
  }
  window.dispatchEvent(new CustomEvent("robotops-run-annotations-changed"));
  return next;
}

export function removeOrphanedRunAnnotations(validRunIds: Set<string>): void {
  const current = loadRunAnnotations();
  const next = Object.fromEntries(Object.entries(current).filter(([id]) => validRunIds.has(id)));
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // Ignore storage failures.
  }
}
