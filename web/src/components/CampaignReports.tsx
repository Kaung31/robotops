import { useEffect, useRef, useState } from "react";
import { campaignClient, reportDownloadUrl } from "../lib/campaignClient";
import type { BackendCampaign, CampaignReport } from "../lib/campaignTypes";

export function CampaignReports({ campaign }: { campaign: BackendCampaign }) {
  const [reports, setReports] = useState<CampaignReport[]>([]);
  const [selected, setSelected] = useState<CampaignReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const epoch = useRef(0);
  const finalized = ["completed", "failed", "canceled", "interrupted"].includes(campaign.state);
  useEffect(() => {
    const request = ++epoch.current;
    setBusy(false);
    setLoading(true);
    void campaignClient.reports(campaign.id).then(items => {
      if (request !== epoch.current) return;
      setReports(items); setSelected(previous => items.find(item => item.id === previous?.id) ?? items[0] ?? null);
      setError(null);
    }).catch(reason => {
      if (request === epoch.current) setError(reason instanceof Error ? reason.message : "Reports unavailable");
    }).finally(() => { if (request === epoch.current) setLoading(false); });
    return () => { ++epoch.current; };
  }, [campaign.id, campaign.updated_at]);

  async function generate() {
    if (busy || loading || !finalized) return;
    const request = ++epoch.current;
    setBusy(true); setError(null);
    try {
      const report = await campaignClient.generateReport(campaign.id);
      if (request !== epoch.current) return;
      setSelected(report);
      setReports(items => [report, ...items.filter(item => item.id !== report.id)].slice(0, 20));
    } catch (reason) {
      if (request === epoch.current) setError(reason instanceof Error ? reason.message : "Report generation failed");
    } finally { if (request === epoch.current) setBusy(false); }
  }
  return <section className="campaign-reports" aria-label="Saved experiment reports">
    <h3>Saved experiment reports</h3>
    <p className="muted">Reports retain separate ROS, pose and contact results. Artifact integrity is checked when generated; saved downloads keep that snapshot.</p>
    <button type="button" className="secondary" disabled={busy || loading || !finalized} onClick={() => void generate()}>{busy ? "Checking evidence…" : "Generate report and check evidence"}</button>
    {!finalized && <p className="muted">Available after this campaign is finalized.</p>}
    {error && <p role="alert" className="warning">{error}</p>}
    {loading ? <p role="status">Loading saved reports…</p> : !reports.length && <p className="muted">No saved reports yet.</p>}
    {!!reports.length && <label>Saved snapshot<select disabled={busy} value={selected?.id ?? ""} onChange={event => setSelected(reports.find(item => item.id === event.target.value) ?? null)}>
      {reports.map(report => <option key={report.id} value={report.id}>{new Date(report.created_at).toLocaleString()} · {report.id.slice(0, 12)}</option>)}
    </select></label>}
    {selected && <>
      <p>Report <code>{selected.id.slice(0, 12)}</code> · generated {new Date(selected.created_at).toLocaleString()}</p>
      <div className="campaign-actions"><a href={reportDownloadUrl(campaign.id, selected.id, "json")} download>Download JSON</a><a href={reportDownloadUrl(campaign.id, selected.id, "html")} download>Download HTML report</a></div>
      {selected.integrity.map(check => <details key={check.trial_id}><summary>Trial {check.trial_id.slice(0, 8)} · artifact integrity: {check.state.toLowerCase()}</summary>
        {check.reasons.map((reason, index) => <p key={index}>{reason}</p>)}
        <ul>{check.artifacts.map((artifact, index) => <li key={index}><strong>{artifact.state}</strong> · {artifact.reference}{artifact.reason ? ` · ${artifact.reason}` : ""}</li>)}</ul>
      </details>)}
      <p className="muted">Integrity issues do not rewrite recorded outcomes. Local hashes are not signed authenticity.</p>
    </>}
  </section>;
}
