import type { ContactValidation } from "../lib/campaignTypes";

export function ContactEvidence({ evidence }: { evidence?: ContactValidation | null }) {
  if (!evidence) return <>Unvalidated</>;
  const labels = { NO_CONTACT_OBSERVED: "No contact observed", CONTACT_DETECTED: "Contact detected", UNKNOWN: "Unknown coverage" };
  return <details className="contact-evidence">
    <summary>{labels[evidence.verdict] ?? "Unavailable"}</summary>
    <p>{evidence.frame_count ?? "Unavailable"} contact windows · {evidence.monitored_bodies?.length ?? "Unavailable"} monitored bodies</p>
    <p className="muted">Normal configured wheel/caster-floor support is excluded. Contact windows are not unique collision episodes or physical safety certification.</p>
    {evidence.scope && <p>{evidence.scope}</p>}
    {evidence.reasons.map((reason, index) => <p key={index}>{reason}</p>)}
    {!!evidence.contacts?.length && <details><summary>Observed contact pairs ({evidence.contacts.length} window entries)</summary><ul>
      {evidence.contacts.slice(0, 20).map((pair, index) => <li key={index}>{pair.body_a} ↔ {pair.body_b}</li>)}
    </ul>{evidence.contacts.length > 20 && <p>First 20 shown. The report retains all stored entries.</p>}</details>}
    {evidence.artifact && <details><summary>Contact evidence reference</summary><p>{evidence.artifact.path}</p><p>SHA-256: {evidence.artifact.sha256}</p></details>}
  </details>;
}
