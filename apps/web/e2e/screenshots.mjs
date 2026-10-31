// Capture full-page screenshots of key pages from a running static server.
// Usage: node e2e/screenshots.mjs [baseUrl=http://localhost:4173] [outDir=../../docs/screenshots]
import fs from "node:fs";
import path from "node:path";
import { launch } from "./browser.mjs";

const base = process.argv[2] ?? "http://localhost:4173";
const outDir = path.resolve(process.argv[3] ?? "../../docs/screenshots");
const extra = (process.env.SCREENSHOT_PAGES ?? "").split(",").filter(Boolean);
const pages = [
  ["landing", "/"],
  ["library", "/library/"],
  ["examples", "/examples/"],
  ["upload", "/upload/"],
  ["compose", "/analyses/new/"],
  ["workspace", "/workspace/"],
  ["assistant", "/assistant/"],
  ["methods", "/methods/"],
  ["data", "/data/"],
  ...extra.map((e) => e.split("=")),
];

fs.mkdirSync(outDir, { recursive: true });
const browser = await launch();
for (const width of [1280, 390]) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: width < 500 ? 2 : 1 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  for (const [name, url] of pages) {
    if (width < 500 && !["landing", "library", "compose", "analysis"].some((n) => name.startsWith(n))) continue;
    await page.goto(base + url, { waitUntil: "networkidle" });
    await page.waitForTimeout(Number(process.env.SCREENSHOT_WAIT ?? 800));
    const file = path.join(outDir, `${name}${width < 500 ? "-mobile" : ""}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(file, errors.length ? `errors: ${errors.join(" | ")}` : "");
    errors.length = 0;
  }
  await ctx.close();
}
await browser.close();
