// Layout review of result pages using SYNTHETIC fixtures served by Playwright route
// interception. The page is stamped with a visible "synthetic fixture" banner and files are
// named *-synthetic.png. These numbers are invented for rendering only; they are not results.
// Output goes to test-results/ (git-ignored) by default; do not publish these images as results.
// Usage: node e2e/fixture-screens.mjs [baseUrl=http://localhost:4173] [outDir=test-results/fixture-screens]
import fs from "node:fs";
import path from "node:path";
import { launch } from "./browser.mjs";

const base = process.argv[2] ?? "http://localhost:4173";
const outDir = path.resolve(process.argv[3] ?? "test-results/fixture-screens");
fs.mkdirSync(outDir, { recursive: true });

let seed = 7;
const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
const gauss = () => Math.sqrt(-2 * Math.log(rnd())) * Math.cos(2 * Math.PI * rnd());

const REGIONS = ["Synthetic region A", "Synthetic region B", "Synthetic region C", "Synthetic region D", "Synthetic region E", "Synthetic region F", "Synthetic region G"];
const centres = REGIONS.map((_, i) => [Math.cos(i * 0.9) * 0.05, Math.sin(i * 1.3) * 0.04]);
const populations = [];
REGIONS.forEach((r, i) => {
  for (let j = 0; j < 14 - i; j++) {
    const coords = Array.from({ length: 10 }, (_, d) => (d < 2 ? centres[i][d] : 0) + gauss() * 0.008);
    populations.push({ population_id: `SYN_${i}_${j}`, name: `SYN_${i}_${j}`, region: r, coords, n_samples: 3 + Math.floor(rnd() * 20) });
  }
});
const space = {
  id: "synthetic-space", name: "synthetic space", version: "0", n_dims: 10, dim_names: [], level: "population",
  description: "", explained_variance_ratio: null, explained_variance: [0.11, 0.06, 0.03, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01],
  provenance: {}, populations,
};

const analysis = (id, kind, result, title) => ({
  id, kind, title, status: "succeeded", dataset_id: null, dataset_ids: [], params: { space: "synthetic-space", target: "SYN_target", sources: ["SYN source 1", "SYN source 2", "SYN source 3"] },
  result, error: null, provenance: { reference_version: "synthetic", note: "synthetic fixture" }, job_id: null,
  created_at: "2026-10-30T12:00:00Z", finished_at: "2026-10-30T12:00:04Z", expires_at: null,
});

const fixtures = {
  pca: analysis("pca", "pca_project", {
    type: "pca_project", kind: "exploratory", space: "synthetic-space",
    targets: [{ name: "SYN_target", coords: [0.012, -0.004, 0, 0, 0, 0, 0, 0, 0, 0] }], n_snps_used: 412345, caveat: "",
  }, "Synthetic PCA projection"),
  fit: analysis("fit", "admixture_fit", {
    type: "admixture_fit", kind: "exploratory", space: "synthetic-space", target: "SYN_target", method: "qp",
    weights: [
      { source: "SYN source 1", weight: 0.52, se: 0.04, ci_low: 0.44, ci_high: 0.6 },
      { source: "SYN source 2", weight: 0.33, se: 0.05, ci_low: 0.24, ci_high: 0.42 },
      { source: "SYN source 3", weight: 0.15, se: 0.03, ci_low: 0.09, ci_high: 0.21 },
    ],
    distance: 0.0214, residuals: Array.from({ length: 25 }, () => gauss() * 0.004), n_bootstrap: 500,
    quality: { label: "fair", distance: 0.0214, relative_distance: 0.4, best_single_source: "SYN source 1", best_single_distance: 0.051, improvement_over_single: 0.58, caveat: "Synthetic." },
    sensitivity: {
      leave_one_source_out: [
        { dropped: "SYN source 1", distance: 0.061, delta_distance: 0.0396 },
        { dropped: "SYN source 2", distance: 0.034, delta_distance: 0.0126 },
        { dropped: "SYN source 3", distance: 0.025, delta_distance: 0.0036 },
      ],
      leave_one_dimension_out: [],
      stable: true, stability_note: "Synthetic stability note.",
    },
    caveat: "",
  }, "Synthetic exploratory fit"),
  qpadm: analysis("qpadm", "qpadm", {
    type: "qpadm", kind: "formal", target: "SYN_target", left: ["SYN source 1", "SYN source 2"], right: ["SYN_R1", "SYN_R2", "SYN_R3", "SYN_R4", "SYN_R5"],
    weights: [{ source: "SYN source 1", weight: 0.64, se: 0.07, z: 9.1 }, { source: "SYN source 2", weight: 0.36, se: 0.07, z: 5.1 }],
    p_value: 0.214, chisq: 4.47, dof: 3, feasible: true,
    rank_tests: [{ rank: 0, dof: 4, chisq: 88.1, p: 3.2e-18, dofdiff: null, chisqdiff: null, p_nested: null }, { rank: 1, dof: 3, chisq: 4.47, p: 0.214, dofdiff: 1, chisqdiff: 83.6, p_nested: 6e-20 }],
    f4: Array.from({ length: 10 }, (_, i) => ({ pop1: "SYN_target", pop2: "SYN source 1", pop3: `SYN_R${1 + (i % 5)}`, pop4: `SYN_R${1 + ((i + 2) % 5)}`, est: 0.001 * gauss(), se: 0.0005, z: 0, fit: 0 })),
    notes: [], caveat: "",
  }, "Synthetic qpAdm model"),
};

const libItems = populations.slice(0, 24).map((p, i) => ({
  id: p.population_id, group_id: null, name: p.name, region: p.region, country: null,
  lat: 30 + gauss() * 12, lon: 20 + gauss() * 30, period: ["Synthetic early", "Synthetic late"][i % 2], culture: null,
  date_mean_bp: 3000 + i * 150, date_sd: null, date_min_bp: 2900 + i * 150, date_max_bp: 3200 + i * 150,
  n_samples: p.n_samples, data_source: "synthetic", publication_ids: ["synpub"], spaces: ["synthetic-space"],
}));
const libPage = {
  items: libItems, total: 240, page: 1, page_size: 50,
  facets: { region: REGIONS, period: ["Synthetic early", "Synthetic late"], country: [], source_dataset: ["synthetic"] },
};

const browser = await launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
await ctx.route("**/api/v1/reference/spaces", (r) => r.fulfill({ json: [space] }));
await ctx.route("**/api/v1/analyses/*", (r) => {
  const id = r.request().url().split("/").pop().split("?")[0];
  return fixtures[id] ? r.fulfill({ json: fixtures[id] }) : r.continue();
});
await ctx.route("**/api/v1/reference/populations?**", (r) => r.fulfill({ json: libPage }));
await ctx.route("**/api/v1/reference/publications", (r) =>
  r.fulfill({ json: [{ id: "synpub", citation: "Synthetic, A., Fixture, B. (2026) Not a real publication", year: 2026, doi: null }] }),
);
const page = await ctx.newPage();
for (const [name, url] of [["library", "/library/"], ["landing", "/"]]) {
  await page.goto(base + url, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    const b = document.createElement("div");
    b.textContent = "SYNTHETIC FIXTURE: layout review only. All names and numbers are invented.";
    b.style.cssText = "position:absolute;top:0;left:0;right:0;padding:6px 12px;background:#8f1d1d;color:#fff;font:14px Georgia,serif;z-index:9999;text-align:center";
    document.body.prepend(b);
  });
  const file = path.join(outDir, `${name}-synthetic.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log(file);
}
for (const id of Object.keys(fixtures)) {
  await page.goto(`${base}/analysis/?id=${id}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.evaluate(() => {
    const b = document.createElement("div");
    b.textContent = "SYNTHETIC FIXTURE: layout review only. All names and numbers are invented; not an analysis result.";
    b.style.cssText = "position:absolute;top:0;left:0;right:0;padding:6px 12px;background:#8f1d1d;color:#fff;font:14px Georgia,serif;z-index:9999;text-align:center";
    document.body.prepend(b);
  });
  const file = path.join(outDir, `analysis-${id}-synthetic.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log(file);
}
await browser.close();
