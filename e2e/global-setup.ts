import { chromium, type FullConfig } from "@playwright/test";

/**
 * Compile the Metro web bundle ONCE, before any spec's clock starts.
 *
 * Expo serves :8082 the moment Metro boots, but the JS bundle is compiled on
 * DEMAND, when a browser first requests it. mobileWebServer's `url` probe only
 * proves the HTML shell is served — which is why adding it (f3ee336) did not stop
 * the failure recurring. The cost simply moved into whichever specs raced the
 * compile: in flake-artifacts/20260802-230841-018c810, test #1 passed at 12.7s,
 * then the first parallel wave ran 24-39s against the 30s test timeout (4 failed)
 * before everything settled to a steady 9-13s.
 *
 * Playwright starts webServers as PLUGINS, and plugin setup runs before
 * globalSetup (playwright 1.58 runner/tasks.js createGlobalSetupTasks), so :8082
 * is already live here. One real browser load pays the compile off the clock;
 * every worker afterwards is served the warm bundle. A plain fetch cannot do
 * this — only a browser executes the shell HTML and requests the bundle.
 *
 * Fails loud. The webServer probe already proved :8082 answers, so a failure here
 * is a real break, and letting it through would just resurface as timeouts.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL =
    config.projects.find((p) => p.name === "chromium")?.use?.baseURL ?? "http://localhost:8082";

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
