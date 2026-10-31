// Post-build: write Cloudflare Pages `_headers` into out/ with a strict CSP.
// connect-src admits the API origin (NEXT_PUBLIC_API_URL) and Supabase when configured.
// Inline scripts emitted by Next.js are admitted by SHA-256 hash, not 'unsafe-inline'.
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const OUT = path.resolve(process.argv[2] ?? "out");

function origin(u) {
  if (!u) return null;
  try {
    return new URL(u).origin;
  } catch {
    return null;
  }
}

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((d) => {
    const p = path.join(dir, d.name);
    return d.isDirectory() ? walk(p) : [p];
  });
}

// Hash the inline scripts of each exported page separately: one CSP rule per route keeps every
// header well under Cloudflare's 2000-character limit. The CSP is attached only to page routes,
// never to "/*", because Cloudflare joins repeated headers and two CSPs would intersect.
const pages = [];
for (const file of walk(OUT).filter((f) => f.endsWith(".html"))) {
  const html = fs.readFileSync(file, "utf8");
  const hashes = new Set();
  for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) {
    if (!m[1]) continue;
    hashes.add(`'sha256-${createHash("sha256").update(m[1], "utf8").digest("base64")}'`);
  }
  const rel = path.relative(OUT, file).split(path.sep).join("/");
  const route = rel === "index.html" ? "/" : rel.endsWith("/index.html") ? `/${rel.slice(0, -10)}` : `/${rel}`;
  pages.push({ route, rel, hashes });
}

const api = origin(process.env.NEXT_PUBLIC_API_URL);
const supa = origin(process.env.NEXT_PUBLIC_SUPABASE_URL);
const connect = ["'self'", api, supa, supa ? supa.replace(/^https/, "wss") : null].filter(Boolean);

function csp(hashes) {
  let scriptSrc = ["'self'", ...hashes].join(" ");
  if (scriptSrc.length > 1400) scriptSrc = "'self' 'unsafe-inline'";
  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    // Plotly injects its stylesheet at runtime.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${connect.join(" ")}`,
    "worker-src 'self' blob:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
}

const rules = [
  `/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()
  Strict-Transport-Security: max-age=63072000; includeSubDomains; preload
  Cross-Origin-Opener-Policy: same-origin`,
  `/_next/static/*
  Cache-Control: public, max-age=31536000, immutable`,
];
for (const p of pages) {
  const paths = p.route === `/${p.rel}` ? [p.route] : [p.route, `/${p.rel}`];
  for (const r of paths) rules.push(`${r}\n  Content-Security-Policy: ${csp(p.hashes)}`);
}
const headers = rules.join("\n\n") + "\n";
if (rules.length > 100) throw new Error(`_headers has ${rules.length} rules; Cloudflare allows 100`);

fs.writeFileSync(path.join(OUT, "_headers"), headers);
console.log(`_headers written: ${pages.length} pages, ${rules.length} rules; connect-src ${connect.join(" ")}`);
