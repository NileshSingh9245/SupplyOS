import { defineConfig } from "@playwright/test";

// Backend-backed checks stay outside the frontend-only suite; no application or preview startup.
export default defineConfig({
  testDir: ".",
  testMatch: "browser-security.isolated.ts",
  workers: 1,
  fullyParallel: false,
  timeout: 30_000,
  reporter: "list",
  outputDir: "../.runtime/browser-security-results",
  use: {
    browserName: "chromium",
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
  },
});
