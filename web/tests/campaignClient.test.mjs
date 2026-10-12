import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/campaignClient.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { campaignClient, submitCampaignIntent, campaignDefinition, summarizeCampaign } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const intent = { key: "stable-request", definition: { name: "Round trip" } };
const response = body => new Response(JSON.stringify(body), { status: 200 });

test("lost creation response retries with the same key and never sends robot commands", async () => {
  const calls = [];
  let first = true;
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push([url, options]);
    if (first) { first = false; throw new Error("connection lost after saving draft"); }
    return response({ id: "one", state: url.endsWith("/start") ? "queued" : "draft" });
  };
  try {
    await assert.rejects(submitCampaignIntent(intent), /connection lost/);
    assert.equal((await submitCampaignIntent(intent)).state, "queued");
    assert.equal(calls[0][1].headers["Idempotency-Key"], calls[1][1].headers["Idempotency-Key"]);
    assert.deepEqual(calls.map(([url]) => url), ["/api/v1/campaigns", "/api/v1/campaigns", "/api/v1/campaigns/one/start"]);
  } finally { globalThis.fetch = original; }
});

test("retry after a lost start response observes active or finalized campaigns without restarting", async () => {
  const original = globalThis.fetch;
  try {
    for (const state of ["queued", "running", "canceling", "completed", "failed", "interrupted", "canceled"]) {
      const calls = [];
      globalThis.fetch = async url => { calls.push(url); return response({ id: "same", state }); };
      assert.equal((await submitCampaignIntent(intent)).state, state);
      assert.deepEqual(calls, ["/api/v1/campaigns"]);
    }
  } finally { globalThis.fetch = original; }
});

test("observation uses read APIs and event cursors, cancellation only requests backend cancellation", async () => {
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => { calls.push([url, options.method ?? "GET"]); return response([]); };
  try {
    await campaignClient.runtime(); await campaignClient.history(20);
    await campaignClient.get("id"); await campaignClient.events("id", 19); await campaignClient.cancel("id");
    assert.deepEqual(calls, [
      ["/api/v1/campaigns/runtime", "GET"], ["/api/v1/campaigns?limit=20&offset=20", "GET"],
      ["/api/v1/campaigns/id", "GET"], ["/api/v1/campaigns/id/events?after=19", "GET"],
      ["/api/v1/campaigns/id/cancel", "POST"],
    ]);
  } finally { globalThis.fetch = original; }
});

test("HTTP failures remain failures, including disabled execution and structured validation", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Execution disabled" }), { status: 501 });
    await assert.rejects(campaignClient.start("id"), /Execution disabled/);
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ msg: "Invalid pose" }] }), { status: 422 });
    await assert.rejects(campaignClient.start("id"), /422/);
  } finally { globalThis.fetch = original; }
});

test("fixed start return waypoint is independent of live pose and does not mutate the route", () => {
  const route = [{ x: 1, y: 2, yaw: 0 }];
  const config = { start: { x: 0, y: 0, yaw: .3 } };
  const defined = campaignDefinition(config, route, true);
  assert.deepEqual(defined.waypoints, [route[0], { x: 0, y: 0, yaw: .3 }]);
  assert.equal(route.length, 1);
  assert.equal(campaignDefinition(config, defined.waypoints, true).waypoints.length, 2);
  assert.equal(campaignDefinition(config, route, false).waypoints.length, 1);
});

test("missing metrics stay unavailable and failures remain in the success population", () => {
  const record = { definition: { profiles: ["navfn", "other"] }, trials: [
    { profile: "navfn", state: "succeeded", evidence: { outcome: "succeeded", metrics: { mission_ros_seconds: 10, odom_path_metres: 2 } } },
    { profile: "navfn", state: "succeeded", evidence: { outcome: "succeeded", metrics: { mission_ros_seconds: null, odom_path_metres: "3" } } },
    { profile: "navfn", state: "failed", evidence: null },
    { profile: "navfn", state: "canceled", evidence: null },
    { profile: "other", state: "planned", evidence: null },
  ] };
  const [result, empty] = summarizeCampaign(record);
  assert.equal(result.attempted, 3);
  assert.equal(result.successes, 2);
  assert.equal(result.successRate, 200 / 3);
  assert.deepEqual(result.time, { value: 10, samples: 1 });
  assert.deepEqual(result.distance, { value: 2, samples: 1 });
  assert.equal(empty.successRate, null);
  assert.deepEqual(empty.time, { value: null, samples: 0 });
});

test("report generation uses only metadata APIs and downloads refer to persisted report IDs", async () => {
  const { reportDownloadUrl } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
  const original = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push([url, options.method ?? "GET"]);
    return response(url.endsWith("/reports") ? [] : {});
  };
  try {
    await campaignClient.reports("campaign");
    await campaignClient.generateReport("campaign");
    assert.deepEqual(calls, [["/api/v1/campaigns/campaign/reports", "GET"], ["/api/v1/campaigns/campaign/reports", "POST"]]);
    assert.equal(reportDownloadUrl("a/b", "r/s", "html"), "/api/v1/campaigns/a%2Fb/reports/r%2Fs/download?format=html");
  } finally { globalThis.fetch = original; }
});
