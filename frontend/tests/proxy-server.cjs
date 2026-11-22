const { createServer } = require("node:http");
const { handleFinanceFixture } = require("./finance-fixtures.cjs");

// Only the test runner starts this server; application flows never import it.
createServer(async (request, response) => {
  const path = new URL(request.url, "http://127.0.0.1:3801").pathname;
  if (path === "/health") {
    response.writeHead(200).end("ready");
    return;
  }
  if (await handleFinanceFixture(request, response)) return;
  if (!["/api/v1/__proxy-test", "/api/__proxy-test"].includes(path)) {
    response.writeHead(404, { "Content-Type": "application/json" });
    response.end(JSON.stringify({ detail: "Unexpected test backend route." }));
    return;
  }
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  response.writeHead(200, {
    "Content-Type": "application/json",
    "Set-Cookie": "proxy_test=ok; Path=/; HttpOnly; SameSite=Lax",
  });
  response.end(JSON.stringify({
    url: request.url,
    method: request.method,
    cookie: request.headers.cookie,
    authorization: request.headers.authorization,
    requestId: request.headers["x-request-id"],
    body: Buffer.concat(chunks).toString(),
  }));
}).listen(3801, "127.0.0.1");
