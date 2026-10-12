import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Use the project's compiler without introducing a test framework or build artifacts.
const source = await readFile(new URL("../src/lib/refreshGate.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
});
const { createRefreshGate } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
function deferred() {
  let resolve;
  const promise = new Promise(r => { resolve = r; });
  return { promise, resolve };
}

test("slow polling stays single-flight and resumes after completion", async () => {
  const gate = createRefreshGate();
  const response = deferred();
  let calls = 0;
  const work = async () => { calls += 1; await response.promise; };
  const first = gate.run(work);
  for (let tick = 0; tick < 10; tick += 1) assert.equal(gate.run(work), first);
  await Promise.resolve();
  assert.equal(calls, 1);
  response.resolve();
  await first;
  await gate.run(work);
  assert.equal(calls, 2);
});

test("a stack action discards an older readiness response and pauses polling", async () => {
  const gate = createRefreshGate();
  const response = deferred();
  let displayed = "stopped";
  const old = gate.run(async isCurrent => {
    await response.promise;
    if (isCurrent()) displayed = "ready";
  });
  await Promise.resolve();
  const resume = gate.suspend();
  await gate.run(async () => { assert.fail("poll during control action"); });
  resume();
  response.resolve();
  await old;
  assert.equal(displayed, "stopped");
  await gate.run(async isCurrent => { if (isCurrent()) displayed = "new stack"; });
  assert.equal(displayed, "new stack");
});

test("cleanup invalidates late responses; failed requests release the gate", async () => {
  const gate = createRefreshGate();
  const response = deferred();
  let applied = false;
  const old = gate.run(async isCurrent => {
    await response.promise;
    applied = isCurrent();
  });
  await Promise.resolve();
  gate.invalidate();
  response.resolve();
  await old;
  assert.equal(applied, false);
  await assert.rejects(gate.run(async () => { throw new Error("offline"); }), /offline/);
  await gate.run(async isCurrent => { applied = isCurrent(); });
  assert.equal(applied, true);
});

test("a poll invalidated before it starts does not issue requests", async () => {
  const gate = createRefreshGate();
  const poll = gate.run(async () => { assert.fail("obsolete poll started"); });
  gate.invalidate();
  await poll;
});
