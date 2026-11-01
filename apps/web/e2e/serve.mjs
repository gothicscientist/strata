// Minimal static server for the exported site (out/). Applies Cloudflare-style `_headers`
// so the CSP is exercised locally exactly as Pages would serve it.
// Usage: node e2e/serve.mjs [dir=out] [port=4173]
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const root = path.resolve(process.argv[2] ?? "out");
const port = Number(process.argv[3] ?? 4173);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".txt": "text/plain; charset=utf-8",
};

function parseHeaders(file) {
  if (!fs.existsSync(file)) return [];
  const rules = [];
  let cur = null;
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    if (!line.trim() || line.trim().startsWith("#")) continue;
    if (!/^\s/.test(line)) {
      cur = { pattern: line.trim(), headers: [] };
      rules.push(cur);
    } else if (cur) {
      const i = line.indexOf(":");
      cur.headers.push([line.slice(0, i).trim(), line.slice(i + 1).trim()]);
    }
  }
  return rules.map((r) => ({
    ...r,
    re: new RegExp(`^${r.pattern.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*")}$`),
  }));
}


function resolve(urlPath) {
  const clean = decodeURIComponent(urlPath.split("?")[0] ?? "/");
  const p = path.normalize(path.join(root, clean));
  if (!p.startsWith(root)) return null;
  if (fs.existsSync(p) && fs.statSync(p).isFile()) return p;
  const idx = path.join(p, "index.html");
  if (fs.existsSync(idx)) return idx;
  if (fs.existsSync(`${p}.html`)) return `${p}.html`;
  return null;
}

http
  .createServer((req, res) => {
    const urlPath = (req.url ?? "/").split("?")[0];
    let file = resolve(req.url ?? "/");
    let status = 200;
    if (!file) {
      file = path.join(root, "404.html");
      status = 404;
    }
    // Re-read per request so a rebuild never pairs new HTML with stale CSP hashes.
    const rules = parseHeaders(path.join(root, "_headers"));
    const merged = new Map();
    for (const r of rules) {
      if (!r.re.test(urlPath)) continue;
      for (const [k, v] of r.headers) merged.set(k, merged.has(k) ? `${merged.get(k)}, ${v}` : v);
    }
    for (const [k, v] of merged) if (k.toLowerCase() !== "strict-transport-security") res.setHeader(k, v);
    res.setHeader("Content-Type", TYPES[path.extname(file)] ?? "application/octet-stream");
    res.writeHead(status);
    fs.createReadStream(file).pipe(res);
  })
  .listen(port, () => console.log(`serving ${root} on http://localhost:${port}`));
