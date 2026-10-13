import { useState, type FormEvent } from "react";
import type { Dataset } from "./data";
import { CHECKS, visitorCheck, type CheckId, type CheckResult } from "./validation";

export type Criteria = Record<CheckId, string>;
export function ValidationPanel({ data, initial }: { data: Dataset; initial?: Criteria }) {
  const [criteria, setCriteria] = useState<Criteria>(initial ?? { duration: "25", xy: "0.2", yaw: "0.1" });
  const [results, setResults] = useState<Record<CheckId, CheckResult> | null>(null);
  function run(event: FormEvent) {
    event.preventDefault();
    setResults({ duration: visitorCheck("duration", data.manifest.metrics, criteria.duration, data.trusted), xy: visitorCheck("xy", data.manifest.metrics, criteria.xy, data.trusted), yaw: visitorCheck("yaw", data.manifest.metrics, criteria.yaw, data.trusted) });
  }
  return <section className="result-card visitor" aria-labelledby="validation-title">
    <div className="section-kicker">YOUR TESTS · ORIGINAL EVIDENCE STAYS UNCHANGED</div>
    <h2 id="validation-title">Set your acceptance criteria</h2>
    <form noValidate onSubmit={run}>
      <div className="validation-checks">{CHECKS.map(check => {
        const result = results?.[check.id];
        const metric = data.manifest.metrics.find(m => m.name === check.metric);
        const readable = metric?.value == null || !Number.isFinite(metric.value) ? "unavailable" : `${metric.value.toFixed(check.id === "duration" ? 2 : 4)} ${check.unit}`;
        return <div className="validation-check" key={check.id}>
          <label htmlFor={`criterion-${check.id}`}>Maximum {check.label.toLowerCase()} <span>({check.unitName} · {check.unit})</span></label>
          <div className="validation-input-result"><input id={`criterion-${check.id}`} aria-label={`Maximum ${check.label.toLowerCase()} ${check.unitName}`} type="number" min="0" step="any" value={criteria[check.id]} onChange={e => { setCriteria({ ...criteria, [check.id]: e.target.value }); setResults(null); }} aria-describedby={`reason-${check.id}`} /><output aria-label={`${check.label} result`} className={`verdict ${result?.outcome ?? "UNKNOWN"}`}>{result?.outcome ?? "UNKNOWN"}</output></div>
          <p id={`reason-${check.id}`} className="check-explanation">{!result ? "Run checks to evaluate current criteria." : result.outcome === "UNKNOWN" ? result.reason : `${readable} (rounded). Exact original value ${result.outcome === "PASS" ? "meets" : "exceeds"} your maximum.`}</p>
        </div>;
      })}</div>
      <div className="validation-run"><button type="submit">Run checks</button><span role="status">{results ? "Three visitor checks calculated. Originals unchanged." : "Criteria ready · run checks to calculate."}</span></div>
    </form>
    <p className="card-footnote">Inputs use seconds, metres and radians only. Equality passes using exact source values; displayed measurements are rounded. Invalid or missing evidence is UNKNOWN. These are visitor calculations, not new experiments.</p>
  </section>;
}
