// Playwright smoke test against the static export (run `pnpm build` first).
// Starts e2e/serve.mjs on out/, visits every page, and fails on uncaught errors or CSP
// violations. If the API named at build time is reachable, it also uploads a G25 row
// (SYNTHETIC coordinates, used only to exercise the upload path) and checks the QC table.
import { spawn } from "node:child_process";
import { launch } from "./browser.mjs";

const PORT = Number(process.env.SMOKE_PORT ?? 4174);
const BASE = `http://localhost:${PORT}`;
const API = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

const PAGES = [
  ["/", /population genetics/],
  ["/library/", /Reference populations/],
  ["/library/population/", /No population was specified|Loading/],
  ["/examples/", /Example analyses/],
  ["/examples/view/", /No example was specified/],
  ["/upload/", /Upload a dataset/],
  ["/analyses/new/", /New analysis/],
  ["/analysis/", /No analysis was specified/],
  ["/workspace/", /Your analyses and datasets/],
  ["/assistant/", /Ask a question/],
  ["/methods/", /Methods/],
  ["/data/", /Data sources and licences/],
  ["/account/", /Your workspace/],
];

const server = spawn(process.execPath, ["e2e/serve.mjs", "out", String(PORT)], { stdio: "pipe" });
await new Promise((r) => server.stdout.once("data", r));

let failures = 0;
const fail = (msg) => {
  failures += 1;
  console.error(`FAIL ${msg}`);
};

const apiUp = await fetch(`${API}/api/v1/health`).then((r) => r.ok).catch(() => false);
const browser = await launch();
try {
  const page = await browser.newPage();
  const problems = [];
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    const t = m.text();
    if (/Content Security Policy|Refused to/.test(t)) problems.push(`csp: ${t}`);
  });

  for (const [path, expected] of PAGES) {
    problems.length = 0;
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    const h1 = (await page.locator("h1").first().textContent({ timeout: 5000 }).catch(() => "")) ?? "";
    const body = (await page.locator("main").textContent()) ?? "";
    if (!expected.test(h1) && !expected.test(body)) fail(`${path}: expected ${expected}, h1 was "${h1}"`);
    if (problems.length) fail(`${path}: ${problems.join(" | ")}`);
    else console.log(`ok   ${path}`);
  }

  // Keyboard: the skip link is the first focusable element.
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.textContent);
  if (focused !== "Skip to content") fail(`first tab stop was "${focused}"`);
  else console.log("ok   skip link");

  if (apiUp) {
    await page.goto(BASE + "/upload/", { waitUntil: "networkidle" });
    const row = ["SYNTHETIC_smoke", ...Array.from({ length: 25 }, (_, i) => (0.001 * (i + 1)).toFixed(4))].join(",");
    await page.getByLabel(/One sample per line/).fill(row);
    await page.getByText("1 sample recognised").waitFor({ timeout: 5000 });
    await page.getByRole("button", { name: "Upload coordinates" }).click();
    try {
      await page.getByRole("heading", { name: /Quality control/ }).waitFor({ timeout: 15000 });
      console.log("ok   G25 upload and QC report");
    } catch {
      fail(`G25 upload: ${(await page.locator("[role=alert]").allTextContents()).join(" ")}`);
    }
  } else {
    console.log(`skip upload flow (API not reachable at ${API})`);
  }
} finally {
  await browser.close();
  server.kill();
}

if (failures) {
  console.error(`${failures} failure(s)`);
  process.exit(1);
}
console.log("smoke test passed");
