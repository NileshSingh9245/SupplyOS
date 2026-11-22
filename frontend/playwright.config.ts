import { defineConfig } from "@playwright/test";

const production = process.env.PLAYWRIGHT_PRODUCTION === "1";
const dist = process.env.NEXT_DIST_DIR || ".runtime/next";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: "list",
  outputDir: ".runtime/test-results",
  use: {
    baseURL: "http://127.0.0.1:3100",
    channel: process.env.PLAYWRIGHT_CHANNEL,
    browserName: "chromium",
    viewport: { width: 1280, height: 800 },
    trace: "off",
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
    },
  },
  webServer: [
    {
      command: "node tests/proxy-server.cjs",
      url: "http://127.0.0.1:3801/health",
      reuseExistingServer: false,
    },
    {
      command: `node --require ./tests/onboarding-env.cjs node_modules/next/dist/bin/next ${production ? "start" : "dev --webpack"} -p 3100 -H 127.0.0.1`,
      url: "http://127.0.0.1:3100/login",
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        BACKEND_URL: "http://127.0.0.1:3801",
        NEXT_PUBLIC_BACKEND_URL: "",
        REACT_APP_BACKEND_URL: "",
        NEXT_PUBLIC_API_BASE: "/api/v1",
        SUPPLYOS_TEST_NODE_ENV: production ? "production" : "development",
        SUPPLYOS_TEST_DIST_DIR: dist,
        SUPPLYOS_TEST_BACKEND: "http://127.0.0.1:3801",
        NEXT_DIST_DIR: dist,
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
