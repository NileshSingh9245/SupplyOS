const path = require("node:path");
const fs = require("node:fs");

const mode = process.env.SUPPLYOS_TEST_NODE_ENV || "development";
const dist = process.env.SUPPLYOS_TEST_DIST_DIR || ".runtime/next-tests";
const backend = process.env.SUPPLYOS_TEST_BACKEND || "http://127.0.0.1:3809";
if (!["development", "production"].includes(mode) ||
    !/^\.runtime\/[a-zA-Z0-9_-]+$/.test(dist) ||
    !["http://127.0.0.1:3801", "http://127.0.0.1:3809"].includes(backend)) {
  throw new Error("Invalid isolated frontend test configuration.");
}

// Test servers must not inherit private configuration or read workspace .env files.
const environment = {};
for (const name of ["PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "ComSpec", "PATHEXT", "NUMBER_OF_PROCESSORS", "USERPROFILE", "NEXT_PRIVATE_WORKER", "PORT", "__NEXT_PRIVATE_ORIGIN", "__NEXT_DEV_SERVER"]) {
  if (process.env[name] !== undefined) environment[name] = process.env[name];
}
process.env = {
  ...environment, NODE_ENV: mode, NEXT_TELEMETRY_DISABLED: "1",
  SUPPLYOS_TEST_NODE_ENV: mode, SUPPLYOS_TEST_DIST_DIR: dist, SUPPLYOS_TEST_BACKEND: backend,
  NEXT_DIST_DIR: dist, BACKEND_URL: backend,
  NEXT_PUBLIC_BACKEND_URL: "", REACT_APP_BACKEND_URL: "", NEXT_PUBLIC_API_BASE: "/api/v1",
  NODE_OPTIONS: `--require=${JSON.stringify(__filename)}`,
};

function guardEnvironmentFile(file) {
  if (typeof file === "string" && path.basename(file).startsWith(".env")) {
    throw new Error("Private environment file reads are forbidden in onboarding fixtures.");
  }
}
for (const name of ["readFileSync", "readFile"]) {
  const original = fs[name];
  fs[name] = function (file, ...args) {
    guardEnvironmentFile(file);
    return original.call(this, file, ...args);
  };
}
const readFile = fs.promises.readFile;
fs.promises.readFile = function (file, ...args) {
  guardEnvironmentFile(file);
  return readFile.call(this, file, ...args);
};

const envPath = require.resolve("@next/env");
const envModule = require(envPath);
require.cache[envPath].exports = {
  ...envModule,
  loadEnvConfig: () => ({ combinedEnv: process.env, parsedEnv: {}, loadedEnvFiles: [] }),
};
