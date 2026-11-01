// Shared Playwright launcher: uses the preinstalled Chromium when PLAYWRIGHT_CHROMIUM is set
// or /opt/pw-browsers holds one, else Playwright's own download.
import fs from "node:fs";
import { chromium } from "playwright";

export function chromiumPath() {
  if (process.env.PLAYWRIGHT_CHROMIUM) return process.env.PLAYWRIGHT_CHROMIUM;
  const base = "/opt/pw-browsers";
  if (!fs.existsSync(base)) return undefined;
  for (const d of fs.readdirSync(base).filter((x) => x.startsWith("chromium-")).sort().reverse()) {
    const p = `${base}/${d}/chrome-linux64/chrome`;
    if (fs.existsSync(p)) return p;
  }
  return undefined;
}

export function launch() {
  const executablePath = chromiumPath();
  return chromium.launch(executablePath ? { executablePath } : {});
}
