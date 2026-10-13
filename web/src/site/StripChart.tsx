// One dot per trial on a labelled axis, a mean tick per configuration and
// optional reference lines. Presentation only: values are passed in exactly as
// the caller verified them; the axis range is printed, never implied.
export interface StripGroup { id: "navfn_rpp" | "smac_dwb"; label: string; values: { id: string; value: number }[] }
export interface StripChartProps {
  title: string; note?: string; unit: string; digits: number;
  min: number; max: number; ticks: number[]; tickDigits: number;
  groups: StripGroup[]; references?: { value: number; label: string }[];
}
const mean = (values: number[]) => values.reduce((a, b) => a + b, 0) / values.length;
export function StripChart({ title, note, unit, digits, min, max, ticks, tickDigits, groups, references = [] }: StripChartProps) {
  const at = (value: number) => `${((value - min) / (max - min)) * 100}%`;
  const show = (value: number) => `${value.toFixed(digits)} ${unit}`;
  const summary = `${title}. ${groups.map(g => `${g.label}: ${g.values.map(v => `${v.id} ${show(v.value)}`).join(", ")}; mean ${show(mean(g.values.map(v => v.value)))}`).join(". ")}. Axis ${show(min)} to ${show(max)}${references.length ? `; reference lines: ${references.map(r => `${r.label} ${show(r.value)}`).join(", ")}` : ""}.`;
  return <figure className="strip-chart">
    <figcaption><strong>{title}</strong>{note && <span>{note}</span>}</figcaption>
    <div className="strip-plot" role="img" aria-label={summary}>
      <div className="strip-overlay" aria-hidden="true">{references.map((r, i) => <span key={r.label} className={`strip-reference reference-${i}`} style={{ left: at(r.value) }} />)}</div>
      {groups.map(g => { const m = mean(g.values.map(v => v.value)); return <div className="strip-row" key={g.id} aria-hidden="true">
        <span className="strip-label"><span><i className={`swatch ${g.id}`} />{g.label}</span><small>mean {show(m)}</small></span>
        <div className="strip-track">{g.values.map(v => <span key={v.id} className={`strip-dot ${g.id}`} style={{ left: at(v.value) }} title={`${v.id}: ${show(v.value)}`} />)}
          <span className={`strip-mean ${g.id}`} style={{ left: at(m) }} /></div>
      </div>; })}
      <div className="strip-axis" aria-hidden="true"><span /><div>{ticks.map(t => <span key={t} style={{ left: at(t) }}>{t.toFixed(tickDigits)}</span>)}</div></div>
    </div>
    {references.length > 0 && <div className="strip-legend" aria-hidden="true">{references.map((r, i) => <span key={r.label}><i className={`reference-${i}`} />{r.label} {show(r.value)}</span>)}</div>}
  </figure>;
}
