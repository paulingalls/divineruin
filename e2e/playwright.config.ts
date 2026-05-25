import { defineConfig, devices } from "@playwright/test";
import { DEFAULT_DB_URL } from "./fixtures/auth.js";

const CI = !!process.env.CI;

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
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
  webServer: [
    {
      command: "bun run apps/server/src/index.ts",
      cwd: "../",
      port: 3001,
      reuseExistingServer: !CI,
      env: {
        DATABASE_URL: process.env.DATABASE_URL ?? DEFAULT_DB_URL,
        REDIS_URL: process.env.REDIS_URL ?? "redis://localhost:6379",
        JWT_SECRET:
          process.env.JWT_SECRET ??
          "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        NODE_ENV: "development",
        RATE_LIMIT_BYPASS: "1",
      },
    },
    {
      command:
        "cd apps/mobile && bunx expo start --web --port 8082 --non-interactive",
      cwd: "../",
      port: 8082,
      timeout: 120_000,
      reuseExistingServer: !CI,
      env: {
        EXPO_PUBLIC_API_URL: "http://localhost:3001",
      },
    },
    {
      // Marketing site (apps/web): build the prerendered dist, then serve it via
      // the production static branch. The web specs use absolute :8085 URLs
      // (the global baseURL above is the mobile app on :8082).
      command: "bun run --cwd apps/web build && bun run --cwd apps/web start",
      cwd: "../",
      port: 8085,
      timeout: 120_000,
      reuseExistingServer: !CI,
      env: {
        NODE_ENV: "production",
        PORT: "8085",
      },
    },
  ],
});
