import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

export default defineConfig({
  testDir: ".", testMatch: ["setup-security.spec.ts", "staff-onboarding.spec.ts"],
  fullyParallel: false, workers: 1, timeout: 45_000, expect: { timeout: 10_000 }, reporter: "list",
  outputDir: "../.runtime/onboarding-ui-results",
  use: {
    baseURL: "http://127.0.0.1:3100", channel: process.env.PLAYWRIGHT_CHANNEL,
    browserName: "chromium", viewport: { width: 1280, height: 800 }, trace: "off",
  },
  webServer: {
    cwd: resolve(__dirname, ".."),
    command: "node --require ./tests/onboarding-env.cjs node_modules/next/dist/bin/next dev -p 3100 -H 127.0.0.1",
    url: "http://127.0.0.1:3100/login", timeout: 120_000, reuseExistingServer: false,
  },
});
