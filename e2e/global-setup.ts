import { APP_ORIGIN } from "./ports.js";
import { chromium, type FullConfig } from "@playwright/test";

// Metro compiles the bundle on demand, after its HTML probe passes. Warm it
// before Playwright starts the timed specs.

export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects.find((p) => p.name === "chromium")?.use?.baseURL ?? APP_ORIGIN;

  const startedAt = Date.now();
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(baseURL, { waitUntil: "load", timeout: 180_000 });
    // `load` alone can resolve once the bundle has DOWNLOADED but before it has
    // executed and mounted. The specs assert rendered text, so wait for the app
    // to actually paint something — any content, not a specific testid, so this
    // doesn't break when the landing screen changes.
    await page.waitForFunction(() => document.body.innerText.trim().length > 0, undefined, {
      timeout: 180_000,
    });
  } finally {
    await browser.close();
  }
  console.log(`[e2e] Metro bundle warmed in ${((Date.now() - startedAt) / 1000).toFixed(1)}s`);
}
