import { test, expect } from "@playwright/test";
import { AxiosError, type AxiosResponse } from "axios";
import { createRequestIntent } from "../src/lib/intent";
import { moneyInput } from "../src/lib/finance";

function failure(status?: number) {
  return new AxiosError("Fixture failure", undefined, undefined, undefined, status ? { status } as AxiosResponse : undefined);
}

for (const status of [undefined, 408, 500, 503]) {
  test(`one request intent retains its UUID after ${status ?? "network"} failure`, () => {
    const intent = createRequestIntent();
    const key = intent.begin({ amount: "10.00" });
    expect(key).toMatch(/^[0-9a-f-]{36}$/i);
    expect(intent.begin({ amount: "10.00" })).toBeNull();
    intent.finish(failure(status));
    expect(intent.unresolved).toBe(true);
    expect(intent.begin({ amount: "10.00" })).toBe(key);
  });
}

for (const status of [400, 401, 403, 409, 422, 429]) {
  test(`definitive ${status} rejection ends the previous request intent`, () => {
    const intent = createRequestIntent();
    const key = intent.begin({ amount: "10.00" });
    intent.finish(failure(status));
    expect(intent.unresolved).toBe(false);
    expect(intent.begin({ amount: "10.00" })).not.toBe(key);
  });
}

test("successful identical payments are distinct intents, never body-deduplicated", () => {
  const intent = createRequestIntent();
  const key = intent.begin({ amount: "10.00" });
  intent.finish();
  expect(intent.begin({ amount: "10.00" })).not.toBe(key);
});

test("editing and restoring a payload still starts a new intent", () => {
  const intent = createRequestIntent();
  const key = intent.begin({ amount: "10.00" });
  intent.finish(failure());
  intent.change();
  expect(intent.begin({ amount: "10.00" })).not.toBe(key);
  intent.finish(failure(503));
  expect(intent.begin({ amount: "11.00" })).not.toBe(key);
});

test("money input stays exact decimal text and rejects invalid precision and magnitudes", () => {
  expect(moneyInput(" 0010.5 ")).toBe("10.50");
  expect(moneyInput("0")).toBe("0.00");
  expect(moneyInput("999999999999.99")).toBe("999999999999.99");
  for (const value of ["NaN", "Infinity", "1e3", "-1", "1,000", "1.001", "1000000000000", "", "1x"]) {
    expect(moneyInput(value)).toBeNull();
  }
});
