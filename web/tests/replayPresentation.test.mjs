import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import ts from "typescript";
const require = createRequire(import.meta.url);
const source = await readFile(new URL("../src/components/MapView.tsx", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } });
const module = { exports: {} }; new Function("require", "exports", "module", outputText)(require, module.exports, module);
const { MapView } = module.exports;
const props = { snapshot: { map: null }, selectedGoal: null, onGoalSelect: () => assert.fail("render must never select a goal") };
test("live map defaults retain goal hint and operational overlays", () => {
  const html = renderToStaticMarkup(React.createElement(MapView, props));
  assert.match(html, /Click to choose a goal/); assert.match(html, /global path/); assert.match(html, /selected goal/);
});
test("replay map is explicitly read-only with recorded labels", () => {
  const html = renderToStaticMarkup(React.createElement(MapView, { ...props, readOnly: true, mappingActive: true }));
  assert.doesNotMatch(html, /choose a goal|selected goal|global path|local path/); assert.match(html, /Recorded map/); assert.match(html, /recorded trajectory/);
  assert.match(source, /if \(!current.moved && !readOnly\)/);
});
test("loopback server has an explicit route allowlist and rejects upgrade requests", async () => {
  const text = await readFile(new URL("../scripts/serve-replay.mjs", import.meta.url), "utf8");
  assert.match(text, /server.listen\(5174, "127.0.0.1"/); assert.match(text, /req.headers.host !== "127.0.0.1:5174"/);
  assert.match(text, /names.has\(name\)/); assert.match(text, /routes.get\(path\)/); assert.match(text, /server.on\("upgrade"/);
  assert.doesNotMatch(text, /proxy|createConnection|WebSocket\(/);
});
