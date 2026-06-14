import { defineConfig, devices } from "@playwright/test";
import { DEFAULT_DB_URL } from "./fixtures/auth.js";
import { LH_DEBUG_PORT } from "./fixtures/lighthouse.js";

const CI = !!process.env.CI;

// Playwright starts EVERY `webServer` entry for ANY run, regardless of which
// project's specs execute. Parse the selected --project(s) from argv so we only
// start the servers a run actually needs: a web-only run skips the slow
// mobile-expo boot, and a non-web run skips the ~120s apps/web prerender build.
// The API server (:3001) is the exception — it starts for ANY run, because the
// chromium app specs AND the web-conversion waitlist spec (which POSTs to
// /api/waitlist) both need it. With no --project filter (CI's bare
// `playwright test`) every gate opens, matching the pre-split config.
function selectedProjects(): string[] {
  const out: string[] = [];
  const argv = process.argv;
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--project" || arg === "-p") {
      if (argv[i + 1]) out.push(argv[i + 1]);
    } else if (arg.startsWith("--project=")) {
      out.push(arg.slice("--project=".length));
    }
  }
  return out;
}

const selected = selectedProjects();
// Both web projects (marketing site + its Lighthouse capstone) serve the same
// apps/web prod build on :8085, so either one selected starts that webServer.
const WEB_PROJECTS = ["web", "web-lighthouse"];
const runsWeb = selected.length === 0 || selected.some((p) => WEB_PROJECTS.includes(p));
// "non-web" = any selected project that is neither web project (today only
// "chromium"). Defined as the complement of the web projects so adding a future
// project — firefox, webkit, etc. — keeps its server+mobile deps without editing
// this line; selecting only a web project skips the slow mobile-expo boot.
const runsNonWeb = selected.length === 0 || selected.some((p) => !WEB_PROJECTS.includes(p));

// reuseExistingServer is false everywhere (not !CI): two overlapping pre-push
// runs must never collapse onto one shared webServer — the first run's teardown
// would kill the second mid-test (the documented cross-kill flake). false makes
// an overlap fail loud on a port conflict instead of silently corrupting a run.
// (Per-run server PORTS were tried and reverted — expo bakes EXPO_PUBLIC_API_URL
// into the cached metro bundle, so a per-run API port breaks the mobile lane.)
const serverWebServer = {
  command: "bun run apps/server/src/index.ts",
  cwd: "../",
  port: 3001,
  reuseExistingServer: false,
  env: {
    DATABASE_URL: process.env.DATABASE_URL ?? DEFAULT_DB_URL,
    REDIS_URL: process.env.REDIS_URL ?? "redis://localhost:56379",
    JWT_SECRET:
      process.env.JWT_SECRET ?? "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    NODE_ENV: "development",
    RATE_LIMIT_BYPASS: "1",
    // Never hit the real Resend API from e2e. NODE_ENV=development leaves
    // IS_TEST_ENV false, so the email seam's auto-mock doesn't engage — set the
    // transport explicitly. The auth spec reads its code from the DB, so the
    // outbound send has no test value anyway.
    EMAIL_TRANSPORT: "mock",
  },
};

const mobileWebServer = {
  command: "cd apps/mobile && bunx expo start --web --port 8082 --non-interactive",
  cwd: "../",
  port: 8082,
  timeout: 120_000,
  reuseExistingServer: false,
  env: {
    EXPO_PUBLIC_API_URL: "http://localhost:3001",
  },
};

const webWebServer = {
  // Marketing site (apps/web): build the prerendered dist, then serve it via
  // the production static branch. The web specs use absolute :8085 URLs
  // (the global baseURL below is the mobile app on :8082).
  command: "bun run --cwd apps/web build && bun run --cwd apps/web start",
  cwd: "../",
  // Wait on an HTTP probe of the served page, not a bare TCP port: the command
  // prerenders the dist (`build`) BEFORE the server binds (`start`), and under
  // the pre-push gate's concurrent load (Docker acceptance + unit lanes) that
  // build is CPU-starved. A `port` probe can race the build; `url` polls for a
  // real 200 from the prod server, so Playwright only starts specs once dist is
  // actually served. timeout gives the build headroom under contention.
  url: "http://localhost:8085/",
  timeout: 180_000,
  // Never reuse an existing :8085 server. A leftover/half-dead server from a
  // killed run would serve stale (or empty) dist and silently fail the content
  // assertions; always build fresh and fail loud on a real port conflict.
  reuseExistingServer: false,
  env: {
    NODE_ENV: "production",
    PORT: "8085",
  },
};

export default defineConfig({
  testDir: "./specs",
  testMatch: "*.e2e.ts",
  // Distribute tests across workers (not just files). Safe because the
  // testUser fixture is worker-scoped (each worker gets its own account, see
  // e2e/fixtures/auth.ts ~L131), and Playwright still runs tests serially
  // within a worker — so worker-shared state isn't concurrent-mutated.
  fullyParallel: true,
  // workers=4 was previously 429-failing because middleware latched
  // RATE_LIMIT_BYPASS at import time before Playwright's webServer.env
  // applied. Now that checkRateLimit re-reads the env per request
  // (apps/server/src/middleware.ts), workers=4 is green.
  workers: 4,
  retries: CI ? 2 : 0,
  timeout: 30_000,
  reporter: CI ? [["html"], ["github"]] : [["html"], ["list"]],
  use: {
    baseURL: "http://localhost:8082",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      // App + API specs (auth, navigation, session-*, home, etc.) against the
      // mobile web app on :8082. Excludes the marketing-site specs so this
      // project never triggers the apps/web prerender build.
      name: "chromium",
      testIgnore: /web-.*\.e2e\.ts$/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
      },
    },
    {
      // Marketing site (apps/web) specs hit the prod build on :8085 at a
      // desktop viewport. Isolated so only this project starts the apps/web
      // webServer (see the gated webServer array below). Excludes the Lighthouse
      // capstone: it needs a fixed Chrome debug port + serial execution, which
      // would collide with this project's fullyParallel:true workers.
      name: "web",
      testMatch: /web-.*\.e2e\.ts$/,
      testIgnore: /web-production\.e2e\.ts$/,
      use: {
        ...devices["Desktop Chrome"],
      },
    },
    {
      // story-007 capstone: the Lighthouse + meta/crawl gate, against the same
      // prod build on :8085. fullyParallel:false so its single spec file runs
      // serially in one worker — the only Chrome that binds the fixed
      // remote-debugging-port playAudit attaches to, so it never collides with
      // the parallel "web" project's Chromes. (Playwright's `workers` is global-
      // only, not per-project, so serial-within-the-file is what isolates the
      // port.) launchOptions puts the debug-port arg on this project's fixture
      // browser — per-project, so only this Chrome opens the port — and the spec
      // audits the fixture `page`, letting Playwright own browser teardown.
      name: "web-lighthouse",
      testMatch: /web-production\.e2e\.ts$/,
      fullyParallel: false,
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: { args: [`--remote-debugging-port=${LH_DEBUG_PORT}`] },
      },
    },
  ],
  webServer: [
    // Always start the :3001 API server — the chromium app specs and the
    // web-conversion waitlist spec both depend on it (previously a web-only run
    // started only :8085, so a web spec POSTing to the API failed).
    serverWebServer,
    ...(runsNonWeb ? [mobileWebServer] : []),
    ...(runsWeb ? [webWebServer] : []),
  ],
});
