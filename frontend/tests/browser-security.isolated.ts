import { test, expect } from "@playwright/test";
import { spawn, execFile, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createServer, type Server } from "node:http";
import { resolve } from "node:path";
import nextConfig from "../next.config";

const fixtureCode = String.raw`
import asyncio, io, json, socket, sys
import uvicorn
from PIL import Image
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from app.core.browser_security import BrowserSecurityMiddleware

origins = json.loads(sys.argv[1])
state = {"mutations": 0, "body_reads": 0}
image = io.BytesIO()
Image.new("RGB", (2, 2), "blue").save(image, format="PNG")

async def fixture(scope, receive, send):
    headers = dict(scope["headers"])
    if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
        state["mutations"] += 1
        while True:
            message = await receive()
            state["body_reads"] += 1
            if not message.get("more_body", False):
                break
    if scope["path"] == "/proof.png":
        response = Response(image.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})
    else:
        response = JSONResponse({**state, "origin": headers.get(b"origin", b"").decode(),
            "referer": headers.get(b"referer", b"").decode(),
            "fetch_site": headers.get(b"sec-fetch-site", b"").decode(), "path": scope["path"]})
    await response(scope, receive, send)

app = BrowserSecurityMiddleware(CORSMiddleware(fixture, allow_origins=origins,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    expose_headers=["X-Request-Id"]), trusted_origins=origins)
sock = socket.socket()
sock.bind(("127.0.0.1", 0))

class ReadyServer(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        print("FIXTURE_PORT=" + str(sock.getsockname()[1]), flush=True)

asyncio.run(ReadyServer(uvicorn.Config(app, log_level="critical", access_log=False,
    lifespan="off")).serve(sockets=[sock]))
`;

let apiProcess: ChildProcessWithoutNullStreams | undefined;
let apiOrigin = "";
let siteOrigin = "";
let attackerOrigin = "";
const sites: Server[] = [];

async function headerRules(environment: "development" | "production") {
  const previous = process.env.NODE_ENV;
  Object.assign(process.env, { NODE_ENV: environment });
  try {
    if (!nextConfig.headers) throw new Error("Missing Next browser security headers");
    return await nextConfig.headers();
  } finally {
    if (previous === undefined) Reflect.deleteProperty(process.env, "NODE_ENV");
    else Object.assign(process.env, { NODE_ENV: previous });
  }
}

async function createSite() {
  const rules = await headerRules("development");
  const server = createServer((request, response) => {
    const path = new URL(request.url || "/", "http://isolated.test").pathname;
    for (const rule of rules) {
      if (rule.source === "/:path*" || rule.source === path) {
        for (const header of rule.headers) response.setHeader(header.key, header.value);
      }
    }
    if (path === "/download") {
      response.setHeader("Content-Type", "text/plain");
      response.setHeader("Content-Disposition", 'attachment; filename="isolated-proof.txt"');
      response.end("isolated download bytes");
      return;
    }
    response.setHeader("Content-Type", "text/html");
    response.end(`<!doctype html><html><head><style>#styled { color: rgb(1, 2, 3); }</style></head>
      <body><div id="styled" style="background-color: rgb(4, 5, 6)">Styled fixture</div>
      <script>document.documentElement.dataset.script = "ran";</script>
      <a href="/download" id="download">Download</a>
      ${path === "/frame" ? `<iframe src="${siteOrigin}/document"></iframe>` : ""}
      </body></html>`);
  });
  sites.push(server);
  await new Promise<void>((done, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", done);
  });
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing isolated fixture port");
  return `http://localhost:${address.port}`;
}

test.beforeAll(async () => {
  siteOrigin = await createSite();
  attackerOrigin = await createSite();
  const backend = resolve(__dirname, "../../backend");
  const python = resolve(backend, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
  apiProcess = spawn(python, [
    "-B", "-c", fixtureCode, JSON.stringify([siteOrigin]),
  ], { cwd: backend, stdio: "pipe" });
  apiOrigin = await new Promise<string>((done, reject) => {
    const timeout = setTimeout(() => reject(new Error("Isolated ASGI fixture did not start")), 15_000);
    let output = "";
    apiProcess!.once("error", (error) => { clearTimeout(timeout); reject(error); });
    apiProcess!.once("exit", () => {
      clearTimeout(timeout);
      reject(new Error("Isolated ASGI fixture exited before readiness"));
    });
    apiProcess!.stdout.on("data", (chunk: Buffer) => {
      output += chunk.toString();
      const match = /FIXTURE_PORT=(\d+)/.exec(output);
      if (match) { clearTimeout(timeout); done(`http://127.0.0.1:${match[1]}`); }
    });
  });
});

test.afterAll(async () => {
  if (apiProcess?.pid && apiProcess.exitCode === null) {
    const child = apiProcess;
    await new Promise<void>((done) => {
      if (process.platform === "win32") {
        execFile("taskkill", ["/PID", String(child.pid), "/T", "/F"], () => done());
      } else {
        child.once("exit", () => done());
        child.kill("SIGTERM");
      }
    });
  }
  await Promise.all(sites.map((server) => new Promise<void>((done) => server.close(() => done()))));
});

test("Next headers cover pages, API rewrites and assets without a wildcard CSP", async () => {
  const rules = await headerRules("development");
  const headers = Object.fromEntries(rules[0].headers.map((header) => [header.key, header.value]));
  expect(rules[0].source).toBe("/:path*");
  expect(headers["X-Content-Type-Options"]).toBe("nosniff");
  expect(headers["X-Frame-Options"]).toBe("DENY");
  expect(headers["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["Content-Security-Policy"]).toBe("frame-ancestors 'none'; base-uri 'self'; object-src 'none'");
  expect(headers["Strict-Transport-Security"]).toBeUndefined();
  expect(nextConfig.poweredByHeader).toBe(false);
});

test("HSTS is production-only and recovery keeps no-referrer/no-store overrides", async () => {
  const rules = await headerRules("production");
  expect(rules[0].headers).toContainEqual({ key: "Strict-Transport-Security", value: "max-age=31536000" });
  for (const path of ["/forgot-password", "/reset-password"]) {
    expect(rules.find((rule) => rule.source === path)?.headers).toEqual([
      { key: "Referrer-Policy", value: "no-referrer" }, { key: "Cache-Control", value: "no-store" },
    ]);
  }
});

test("real cross-site recovery JSON keeps trustworthy Origin even with no-referrer", async ({ page }) => {
  const document = await page.goto(`${siteOrigin}/reset-password`);
  expect(document?.headers()["referrer-policy"]).toBe("no-referrer");
  const result = await page.evaluate(async (url) => {
    const response = await fetch(url, { method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" }, body: "{}" });
    return { status: response.status, id: response.headers.get("x-request-id"), data: await response.json() };
  }, `${apiOrigin}/api/auth/reset-password`);
  expect(result.status).toBe(200);
  expect(result.id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(result.data).toMatchObject({ origin: siteOrigin, referer: "", fetch_site: "cross-site" });
});

test("trusted multipart proof and JSON mutations work under canonical, legacy and custom paths", async ({ page }) => {
  await page.goto(`${siteOrigin}/document`);
  for (const prefix of ["/api/v1", "/api", "/custom/v1"]) {
    for (const suffix of ["/auth/login", "/setup/initialize", "/payments", "/deliveries/isolated/proofs"]) {
      const status = await page.evaluate(async ({ url, multipart }) => {
        const form = new FormData();
        form.set("kind", "photo");
        form.set("file", new Blob(["isolated parser fixture"], { type: "image/png" }), "fixture.png");
        return (await fetch(url, { method: "POST", credentials: "include",
          headers: multipart ? undefined : { "Content-Type": "application/json" },
          body: multipart ? form : "{}" })).status;
      }, { url: apiOrigin + prefix + suffix, multipart: suffix.endsWith("/proofs") });
      expect(status).toBe(200);
    }
  }
});

test("an unapproved browser no-cors POST is blocked before body parsing", async ({ page, request }) => {
  const before = await (await request.get(`${apiOrigin}/stats`)).json();
  await page.goto(`${attackerOrigin}/document`);
  await page.evaluate(async (url) => {
    await fetch(url, { method: "POST", mode: "no-cors", credentials: "include", body: "forged" });
  }, `${apiOrigin}/api/payments`);
  const after = await (await request.get(`${apiOrigin}/stats`)).json();
  expect(after.mutations).toBe(before.mutations);
  expect(after.body_reads).toBe(before.body_reads);
});

test("cross-site HTML form posts cannot initialize setup without an approved origin", async ({ page, request }) => {
  const before = await (await request.get(`${apiOrigin}/stats`)).json();
  await page.goto(`${attackerOrigin}/forgot-password`);
  const response = page.waitForResponse(`${apiOrigin}/api/v1/setup/initialize`);
  await page.evaluate((url) => {
    const form = document.createElement("form");
    form.action = url; form.method = "POST";
    document.body.append(form); form.submit();
  }, `${apiOrigin}/api/v1/setup/initialize`);
  expect((await response).status()).toBe(403);
  const after = await (await request.get(`${apiOrigin}/stats`)).json();
  expect(after.mutations).toBe(before.mutations);
  expect(after.body_reads).toBe(before.body_reads);
});

test("opaque sandbox Origin null cannot upload a proof", async ({ page, request }) => {
  const before = await (await request.get(`${apiOrigin}/stats`)).json();
  await page.goto(`${siteOrigin}/document`);
  const url = `${apiOrigin}/custom/v1/deliveries/isolated/proofs`;
  const response = page.waitForResponse(url);
  await page.evaluate((url) => {
    const frame = document.createElement("iframe");
    // A form navigation reaches loopback even when Chrome blocks opaque-origin fetch via PNA.
    frame.sandbox.add("allow-scripts", "allow-forms", "allow-top-navigation");
    frame.srcdoc = `<form id="proof" method="POST" enctype="multipart/form-data" target="_top"></form>
      <script>const form = document.getElementById("proof"); form.action = ${JSON.stringify(url)}; form.submit();</script>`;
    document.body.append(frame);
  }, url);
  const rejected = await response;
  expect(await rejected.request().headerValue("origin")).toBe("null");
  expect(rejected.status()).toBe(403);
  const after = await (await request.get(`${apiOrigin}/stats`)).json();
  expect(after.mutations).toBe(before.mutations);
  expect(after.body_reads).toBe(before.body_reads);
});

test("inline Next-style code, cross-origin proof blobs and downloads still work", async ({ page }) => {
  await page.goto(`${siteOrigin}/document`);
  await expect(page.locator("html")).toHaveAttribute("data-script", "ran");
  await expect(page.locator("#styled")).toHaveCSS("color", "rgb(1, 2, 3)");
  await expect(page.locator("#styled")).toHaveCSS("background-color", "rgb(4, 5, 6)");
  const image = await page.evaluate(async (url) => {
    const response = await fetch(url, { credentials: "include" });
    const source = URL.createObjectURL(await response.blob());
    const image = document.createElement("img");
    image.src = source; document.body.append(image);
    await image.decode(); URL.revokeObjectURL(source);
    return { width: image.naturalWidth, type: response.headers.get("content-type"), status: response.status };
  }, `${apiOrigin}/proof.png`);
  expect(image).toEqual({ width: 2, type: "image/png", status: 200 });
  const download = page.waitForEvent("download");
  await page.locator("#download").click();
  expect((await download).suggestedFilename()).toBe("isolated-proof.txt");
});

test("frame-ancestors policy blocks embedding the protected site", async ({ page }) => {
  await page.goto(`${attackerOrigin}/frame`);
  await expect(page.locator("iframe")).toBeVisible();
  await expect(page.locator("iframe").contentFrame().locator("#styled")).toHaveCount(0);
});

test("no-Origin native request context still reaches API v1", async ({ request }) => {
  const response = await request.post(`${apiOrigin}/api/v1/auth/refresh`, {
    headers: { Cookie: "refresh_token=isolated-native-cookie", Authorization: "Bearer isolated-native-token" },
    data: {},
  });
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ origin: "", fetch_site: "" });
});
