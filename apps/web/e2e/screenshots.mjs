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
  ...extra.map((e) => [e.slice(0, e.indexOf("=")), e.slice(e.indexOf("=") + 1)]),
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
  if (width > 500 && process.env.UPLOAD_DEMO) {
    // Exercise the upload path with one SYNTHETIC G25 row (the sample is named as such) and
    // capture the QC report and the workspace that lists the dataset.
    await page.goto(`${base}/upload/`, { waitUntil: "networkidle" });
    const row = ["SYNTHETIC_upload_check", ...Array.from({ length: 25 }, (_, i) => (0.002 * ((i % 7) - 3)).toFixed(4))].join(",");
    await page.getByLabel(/Dataset name/).fill("Synthetic G25 row (upload check)");
    await page.getByLabel(/One sample per line/).fill(row);
    await page.getByRole("button", { name: "Upload coordinates" }).click();
    await page.getByRole("heading", { name: /Quality control/ }).waitFor({ timeout: 15000 });
    await page.screenshot({ path: path.join(outDir, "upload-qc.png"), fullPage: true });
    await page.goto(`${base}/workspace/`, { waitUntil: "networkidle" });
    await page.getByRole("button", { name: "Synthetic G25 row (upload check)" }).first().click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(outDir, "workspace-dataset.png"), fullPage: true });
    console.log("upload-qc.png, workspace-dataset.png");
    // Submit a real analysis; without a built reference library the API fails it honestly.
    await page.goto(`${base}/analyses/new/`, { waitUntil: "networkidle" });
    await page.getByLabel(/Nearest populations/).check();
    await page.getByRole("button", { name: /Run nearest populations/ }).click();
    await page.waitForURL(/\/analysis\/\?id=/, { timeout: 15000 });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(outDir, "analysis-status.png"), fullPage: true });
    console.log("analysis-status.png");
  }
  await ctx.close();
}
await browser.close();
