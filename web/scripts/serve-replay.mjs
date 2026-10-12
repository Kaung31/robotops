// Local-only static preview, deliberately independent of Vite's dev WebSocket
// client, the operational dashboard and FastAPI. No generic filesystem route.
import { createServer } from "node:http";
import { readFile, lstat, readdir, realpath } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
const web = fileURLToPath(new URL("../", import.meta.url));
const fixture = resolve(web, "../artifacts/p2-n0-20261011/dataset-final");
const dist = resolve(web, "dist/replay");
const v2 = new Map([
  ["n0", { root: resolve(web, "../artifacts/p4b-export-20261011/dataset-n0-final"), hash: "670ccd62c5b5d0e74fc379c2ce9e478534995fd6af2571fc9933fc377d1f85f8" }],
  ["n2", { root: resolve(web, "../artifacts/p4b-export-20261011/dataset-n2-final"), hash: "a4d2c77a28e74d7124429ccc7f8c56010f81802898315bcc1d3de097912028d4" }],
]);
const approved = "755424dae361089465281af6706e51852ed1aa221cffe9504434b0fb6419aab4";
const names = new Set(["manifest.json", "dataset.sha256", "map.pgm.gz", "poses-000.json.gz", "poses-001.json.gz", "poses-002.json.gz", "poses-003.json.gz", "scans-000.json.gz"]);
async function regular(root, name) {
  const path = resolve(root, name), stat = await lstat(path);
  if (!stat.isFile() || stat.size > 5 * 1024 * 1024 || stat.isSymbolicLink() || await realpath(path) !== path || !path.startsWith(root + "/")) throw Error("Not a regular approved file");
  return readFile(path);
}
const routes = new Map([["/", "replay.html"], ["/replay.html", "replay.html"]]);
for (const name of await readdir(resolve(dist, "assets"))) {
  if (!/^[a-zA-Z0-9_-]+\.(js|css)$/.test(name)) throw Error("Unexpected compiled asset");
  routes.set(`/assets/${name}`, `assets/${name}`);
}
await regular(dist, "replay.html");
const server = createServer(async (req, res) => {
  // Only request paths are logged; never cookies, headers, query values or data.
  const path = req.url?.split("?")[0]; console.log(`replay request ${req.method} ${path}`);
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'");
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  if (req.method !== "GET" || req.headers.host !== "127.0.0.1:5174" || req.socket.remoteAddress !== "127.0.0.1" || req.url !== path) {
    res.statusCode = 403; res.end("Local preview only"); return;
  }
  try {
    let bytes, mime;
    if (path.startsWith("/__local_v2/")) {
      const match = /^\/__local_v2\/(n0|n2)\/([a-z0-9.-]+)$/.exec(path);
      const source = match && v2.get(match[1]);
      if (!source || !names.has(match[2])) { res.statusCode = 404; res.end("Unknown fixture"); return; }
      const manifest = await regular(source.root, "manifest.json");
      if (createHash("sha256").update(manifest).digest("hex") !== source.hash) throw Error("Unapproved fixture");
      const name = match[2]; bytes = await regular(source.root, name);
      const parsed = JSON.parse(manifest);
      if (name === "dataset.sha256") {
        if (bytes.toString() !== `${source.hash}  manifest.json\n`) throw Error("Unapproved checksum");
      } else if (name !== "manifest.json") {
        const asset = parsed.assets.find(a => a.path === name);
        if (!asset || bytes.length !== asset.bytes || createHash("sha256").update(bytes).digest("hex") !== asset.sha256) throw Error("Unapproved asset");
      }
      mime = name.endsWith(".gz") ? "application/octet-stream" : "application/json";
    } else if (path.startsWith("/__local_n0/")) {
      const name = path.slice("/__local_n0/".length);
      if (!names.has(name)) { res.statusCode = 404; res.end("Unknown fixture"); return; }
      const manifest = await regular(fixture, "manifest.json");
      if (createHash("sha256").update(manifest).digest("hex") !== approved) throw Error("Unapproved fixture");
      bytes = await regular(fixture, name); mime = name.endsWith(".gz") ? "application/octet-stream" : "application/json";
    } else {
      const name = routes.get(path);
      if (!name) { res.statusCode = 404; res.end("Recorded preview only"); return; }
      bytes = await regular(dist, name); mime = name.endsWith(".html") ? "text/html" : name.endsWith(".js") ? "application/javascript" : "text/css";
    }
    res.setHeader("Content-Type", mime); res.end(bytes);
  } catch { res.statusCode = 503; res.end("Approved local asset unavailable"); }
});
server.on("upgrade", (_req, socket) => { console.warn("replay rejected WebSocket upgrade"); socket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n"); });
server.on("error", error => { console.error(error.message); process.exitCode = 1; });
server.listen(5174, "127.0.0.1", () => console.log("Private local N0/N2 preview: http://127.0.0.1:5174/replay.html"));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => { server.close(); server.closeAllConnections(); });
