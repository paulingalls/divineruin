import { defineConfig, devices } from "@playwright/test";

const CI = !!process.env.CI;

export default defineConfig({
  testDir: "./specs",
  fullyParallel: false,
  workers: 1,
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
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: [
    {
      command: "bun run apps/server/src/index.ts",
      cwd: "../",
      port: 3001,
      reuseExistingServer: !CI,
      env: {
        DATABASE_URL:
          process.env.DATABASE_URL ??
          "postgresql://divineruin:divineruin@localhost:5432/divineruin",
        REDIS_URL: process.env.REDIS_URL ?? "redis://localhost:6379",
        JWT_SECRET:
          process.env.JWT_SECRET ??
          "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        NODE_ENV: "development",
      },
    },
    {
      command:
        "bunx --cwd apps/mobile expo start --web --port 8082 --non-interactive",
      cwd: "../",
      port: 8082,
      timeout: 120_000,
      reuseExistingServer: !CI,
      env: {
        EXPO_PUBLIC_API_URL: "http://localhost:3001",
      },
    },
  ],
});
