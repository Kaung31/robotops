import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
async function component(path, imports = {}) {
  const source = await readFile(new URL(path, import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } });
  const module = { exports: {} };
  new Function("require", "exports", "module", outputText)(name => imports[name] ?? require(name), module.exports, module);
  return module.exports;
}
const { ContactEvidence } = await component("../src/components/ContactEvidence.tsx");
const { CampaignReports } = await component("../src/components/CampaignReports.tsx", {
  "../lib/campaignClient": { campaignClient: { reports: () => Promise.resolve([]) } },
});
const markup = evidence => renderToStaticMarkup(React.createElement(ContactEvidence, { evidence }));

test("missing contact evidence remains unvalidated; unknown is never rendered as zero", () => {
  assert.equal(markup(null), "Unvalidated");
  const unknown = markup({ verdict: "UNKNOWN", reasons: ["Missing source coverage"] });
  assert.match(unknown, /Unknown coverage/);
  assert.match(unknown, /Missing source coverage/);
  assert.doesNotMatch(unknown, /No contact observed/);
});

test("contact presentation preserves server verdict and escapes body names", () => {
  const detected = markup({ verdict: "CONTACT_DETECTED", reasons: [], contacts: [
    { body_a: "<script>body</script>", body_b: "wall" },
  ], frame_count: 2, monitored_bodies: ["robot"] });
  assert.match(detected, /Contact detected/);
  assert.match(detected, /2 contact windows/);
  assert.match(detected, /&lt;script&gt;/);
  assert.doesNotMatch(detected, /<script>/);
  assert.match(markup({ verdict: "NO_CONTACT_OBSERVED", reasons: [] }), /No contact observed/);
});

test("large contact lists remain bounded on screen with full evidence retained by backend", () => {
  const rendered = markup({ verdict: "CONTACT_DETECTED", reasons: [],
    contacts: Array.from({ length: 25 }, (_, i) => ({ body_a: `body-${i}`, body_b: "wall" })) });
  assert.match(rendered, /25 window entries/);
  assert.match(rendered, /body-19/);
  assert.doesNotMatch(rendered, /body-20/);
  assert.match(rendered, /report retains all stored entries/);
});

test("report generation stays disabled for an active campaign and starts by observing saved reports", () => {
  const rendered = renderToStaticMarkup(React.createElement(CampaignReports, {
    campaign: { id: "one", state: "running", updated_at: "now" },
  }));
  assert.match(rendered, /disabled=""/);
  assert.match(rendered, /Available after this campaign is finalized/);
  assert.match(rendered, /Loading saved reports/);
  assert.doesNotMatch(rendered, /Download JSON/);
});
