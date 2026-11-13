import { test, expect } from "@playwright/test";
import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { QueryClient } from "@tanstack/react-query";
import { api, resetApiSession } from "../src/lib/api";
import { useAuth, type AuthUser } from "../src/lib/auth";
import { useSettings, type SettingsPayload } from "../src/lib/settings";
import { productsQuery } from "../src/lib/products";
import { canAccessStaffRoute, staffHome } from "../src/lib/navigation";
import nextConfig from "../next.config";

const user: AuthUser = {
  id: "staff-a", tenant_id: "tenant-a", email: "staff-a@example.test",
  full_name: "Staff A", role: "super_admin", is_active: true,
};
const otherUser: AuthUser = { ...user, id: "staff-b", tenant_id: "tenant-b" };
const settings: SettingsPayload = {
  tenant_id: "tenant-a", company_name: "Tenant A", currency_code: "INR",
  currency_symbol: "INR", locale: "en-IN", values: {},
};
const originalAdapter = api.defaults.adapter;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function response(config: InternalAxiosRequestConfig, data: unknown, status = 200): AxiosResponse {
  const result: AxiosResponse = { config, data, status, statusText: String(status), headers: {} };
  if (status >= 400) throw new AxiosError("Test API error", undefined, config, undefined, result);
  return result;
}

test.beforeEach(() => {
  useAuth.getState().expire();
  useAuth.setState({ user: undefined, bootstrapError: null });
});
test.afterEach(() => {
  useAuth.getState().expire();
  api.defaults.adapter = originalAdapter;
});

test("expired access during bootstrap refreshes once and keeps the staff session", async () => {
  const calls: string[] = [];
  let accessValid = false;
  api.defaults.adapter = async (config) => {
    calls.push(config.url!);
    if (config.url === "/auth/refresh") {
      accessValid = true;
      return response(config, {});
    }
    return response(config, user, accessValid ? 200 : 401);
  };
  const first = useAuth.getState().bootstrap();
  const second = useAuth.getState().bootstrap();
  expect(second).toBe(first);
  await first;
  expect(calls).toEqual(["/auth/me", "/auth/refresh", "/auth/me"]);
  expect(useAuth.getState().user).toEqual(user);
  expect(useAuth.getState().bootstrapError).toBeNull();
});

test("concurrent protected 401s share one refresh and each retry once", async () => {
  const refresh = deferred<void>();
  const started = deferred<void>();
  let refreshes = 0;
  const attempts: Record<string, number> = {};
  api.defaults.adapter = async (config) => {
    if (config.url === "/auth/refresh") {
      refreshes += 1;
      started.resolve();
      await refresh.promise;
      return response(config, {});
    }
    const url = config.url!;
    attempts[url] = (attempts[url] || 0) + 1;
    return response(config, [], attempts[url] === 1 ? 401 : 200);
  };
  const pending = Promise.all([api.get("/inventory"), api.get("/orders")]);
  await started.promise;
  refresh.resolve();
  await pending;
  expect(refreshes).toBe(1);
  expect(attempts).toEqual({ "/inventory": 2, "/orders": 2 });
});

test("a late 401 after completed refresh retries the new cookie without refreshing again", async () => {
  const late = deferred<void>();
  const started = deferred<void>();
  const attempts: Record<string, number> = {};
  let refreshes = 0;
  api.defaults.adapter = async (config) => {
    if (config.url === "/auth/refresh") {
      refreshes += 1;
      return response(config, {});
    }
    const url = config.url!;
    attempts[url] = (attempts[url] || 0) + 1;
    if (url === "/orders" && attempts[url] === 1) {
      started.resolve();
      await late.promise;
    }
    return response(config, [], attempts[url] === 1 ? 401 : 200);
  };
  const pending = api.get("/orders");
  await started.promise;
  await api.get("/inventory");
  late.resolve();
  await pending;
  expect(refreshes).toBe(1);
  expect(attempts).toEqual({ "/orders": 2, "/inventory": 2 });
});

for (const path of ["login", "logout", "refresh", "register-customer", "forgot-password", "reset-password", "change-password"]) {
  test(`401 from /auth/${path} never triggers a refresh loop`, async () => {
    const calls: string[] = [];
    api.defaults.adapter = async (config) => {
      calls.push(config.url!);
      return response(config, {}, 401);
    };
    await expect(api.post(`/auth/${path}`)).rejects.toMatchObject({ response: { status: 401 } });
    expect(calls).toEqual([`/auth/${path}`]);
  });
}

test("failed refresh is propagated without retrying the original request", async () => {
  const calls: string[] = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url!);
    return response(config, {}, 401);
  };
  await expect(api.get("/inventory")).rejects.toMatchObject({ response: { status: 401 } });
  expect(calls).toEqual(["/inventory", "/auth/refresh"]);
});

test("a retried 401 cannot start another refresh", async () => {
  const calls: string[] = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url!);
    return response(config, {}, config.url === "/auth/refresh" ? 200 : 401);
  };
  await expect(api.get("/inventory")).rejects.toMatchObject({ response: { status: 401 } });
  expect(calls).toEqual(["/inventory", "/auth/refresh", "/inventory"]);
});

test("transient refresh failure leaves a retryable bootstrap error", async () => {
  api.defaults.adapter = async (config) => response(config, {}, config.url === "/auth/me" ? 401 : 503);
  await useAuth.getState().bootstrap();
  expect(useAuth.getState().user).toBeUndefined();
  expect(useAuth.getState().bootstrapError).toBeTruthy();
  api.defaults.adapter = async (config) => response(config, user);
  await useAuth.getState().bootstrap();
  expect(useAuth.getState().user).toEqual(user);
});

test("a late bootstrap response cannot overwrite a newer login", async () => {
  const pendingMe = deferred<AuthUser>();
  const started = deferred<void>();
  api.defaults.adapter = async (config) => {
    if (config.url === "/auth/me") {
      started.resolve();
      return response(config, await pendingMe.promise);
    }
    return response(config, { user: otherUser });
  };
  const bootstrap = useAuth.getState().bootstrap();
  await started.promise;
  await useAuth.getState().login("staff-b@example.test", "test-password");
  pendingMe.resolve(user);
  await bootstrap;
  expect(useAuth.getState().user).toEqual(otherUser);
});

test("a newer login aborts the older cookie-setting request", async () => {
  const oldLogin = deferred<void>();
  const started = deferred<void>();
  let oldSignal: AbortSignal | undefined;
  let calls = 0;
  api.defaults.adapter = async (config) => {
    calls += 1;
    if (calls === 1) {
      oldSignal = config.signal as AbortSignal;
      started.resolve();
      await oldLogin.promise;
      return response(config, { user });
    }
    return response(config, { user: otherUser });
  };
  const first = useAuth.getState().login(user.email, "test-password").catch((error: unknown) => error);
  await started.promise;
  await useAuth.getState().login(otherUser.email, "test-password");
  expect(oldSignal?.aborted).toBe(true);
  oldLogin.resolve();
  expect(axios.isCancel(await first)).toBe(true);
  expect(useAuth.getState().user).toEqual(otherUser);
});

test("bootstrap cannot restore the old cookie identity while a new login is pending", async () => {
  const login = deferred<void>();
  const started = deferred<void>();
  const calls: string[] = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url!);
    if (config.url === "/auth/login") {
      started.resolve();
      await login.promise;
      return response(config, { user: otherUser });
    }
    return response(config, user);
  };
  const pending = useAuth.getState().login(otherUser.email, "test-password");
  await started.promise;
  await useAuth.getState().bootstrap();
  expect(useAuth.getState().user).toBeUndefined();
  login.resolve();
  await pending;
  expect(calls).toEqual(["/auth/login"]);
  expect(useAuth.getState().user).toEqual(otherUser);
});

test("signing in during pending logout aborts the old cookie-clearing response", async () => {
  useAuth.setState({ user });
  const oldLogout = deferred<void>();
  const started = deferred<void>();
  let logoutSignal: AbortSignal | undefined;
  api.defaults.adapter = async (config) => {
    if (config.url === "/auth/logout") {
      logoutSignal = config.signal as AbortSignal;
      started.resolve();
      await oldLogout.promise;
      return response(config, {});
    }
    return response(config, { user: otherUser });
  };
  const logout = useAuth.getState().logout();
  await started.promise;
  await useAuth.getState().login(otherUser.email, "test-password");
  expect(logoutSignal?.aborted).toBe(true);
  oldLogout.resolve();
  await logout;
  expect(useAuth.getState().user).toEqual(otherUser);
});

test("logout clears identity and settings immediately even when the server fails", async () => {
  useAuth.setState({ user });
  useSettings.setState({ data: settings });
  const pendingLogout = deferred<void>();
  api.defaults.adapter = async (config) => {
    await pendingLogout.promise;
    return response(config, {}, 503);
  };
  const logout = useAuth.getState().logout();
  expect(useAuth.getState().user).toBeNull();
  expect(useSettings.getState().data).toBeNull();
  pendingLogout.resolve();
  await logout;
});

test("a pending settings response cannot refill settings after logout", async () => {
  useAuth.setState({ user });
  const pendingSettings = deferred<SettingsPayload>();
  const started = deferred<void>();
  api.defaults.adapter = async (config) => {
    if (config.url === "/settings") {
      started.resolve();
      return response(config, await pendingSettings.promise);
    }
    return response(config, {});
  };
  const load = useSettings.getState().load();
  await started.promise;
  await useAuth.getState().logout();
  pendingSettings.resolve(settings);
  await load;
  expect(useSettings.getState().data).toBeNull();
});

test("session reset cancels an old refresh without retrying its protected request", async () => {
  const refresh = deferred<void>();
  const started = deferred<void>();
  const calls: string[] = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url!);
    if (config.url === "/auth/refresh") {
      started.resolve();
      await refresh.promise;
      return response(config, {});
    }
    return response(config, {}, 401);
  };
  const pending = api.get("/inventory").catch((error: unknown) => error);
  await started.promise;
  resetApiSession();
  refresh.resolve();
  expect(axios.isCancel(await pending)).toBe(true);
  expect(calls).toEqual(["/inventory", "/auth/refresh"]);
});

test("public setup status survives anonymous session resolution without auth retries", async () => {
  const setup = deferred<void>();
  const started = deferred<void>();
  api.defaults.adapter = async (config) => {
    started.resolve();
    await setup.promise;
    return response(config, { is_setup_complete: false });
  };
  const pending = api.get("/setup/status");
  await started.promise;
  resetApiSession();
  setup.resolve();
  expect((await pending).data).toEqual({ is_setup_complete: false });
  const calls: string[] = [];
  api.defaults.adapter = async (config) => {
    calls.push(config.url!);
    return response(config, {}, 401);
  };
  await expect(api.get("/setup/status")).rejects.toMatchObject({ response: { status: 401 } });
  expect(calls).toEqual(["/setup/status"]);
});

for (const path of ["/auth/forgot-password", "/auth/reset-password"]) {
  test(`public ${path} survives anonymous bootstrap without replaying credentials`, async () => {
    const gate = deferred<void>();
    const started = deferred<void>();
    const calls: string[] = [];
    api.defaults.adapter = async (config) => {
      calls.push(config.url!);
      started.resolve();
      await gate.promise;
      return response(config, { message: "Accepted" });
    };
    const pending = api.post(path, { email: "account@example.test" });
    await started.promise;
    resetApiSession();
    gate.resolve();
    expect((await pending).data).toEqual({ message: "Accepted" });
    expect(calls).toEqual([path]);
  });
}

test("product selectors share a cached array rather than incompatible response envelopes", async () => {
  const products = [{ id: "product-a", sku: "A", name: "Product A", unit: "kg", base_price: "10.00" }];
  let calls = 0;
  api.defaults.adapter = async (config) => {
    calls += 1;
    return response(config, { items: products, total: 1, page: 1, page_size: 200 });
  };
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });
  expect(await client.fetchQuery(productsQuery)).toEqual(products);
  expect(await client.fetchQuery(productsQuery)).toEqual(products);
  expect(calls).toBe(1);
  client.clear();
});

test("role policy fails closed for non-staff, inactive users and unrelated route prefixes", () => {
  expect(staffHome(user)).toBe("/dashboard");
  expect(staffHome({ ...user, role: "warehouse_manager" })).toBe("/inventory");
  expect(staffHome({ ...user, role: "accountant" })).toBe("/finance");
  for (const role of ["customer", "delivery_partner"] as const) {
    expect(staffHome({ ...user, role })).toBeNull();
    expect(canAccessStaffRoute({ ...user, role }, "/inventory")).toBe(false);
  }
  expect(staffHome({ ...user, is_active: false })).toBeNull();
  expect(canAccessStaffRoute({ ...user, role: "warehouse_manager" }, "/finance")).toBe(false);
  expect(canAccessStaffRoute({ ...user, role: "accountant" }, "/inventory")).toBe(false);
  expect(canAccessStaffRoute(user, "/orders/123")).toBe(true);
  expect(canAccessStaffRoute(user, "/orders-other")).toBe(false);
});

test("proxy config uses a server-only origin and retains public origin fallbacks", async () => {
  const rewrites = nextConfig.rewrites as () => Promise<{ source: string; destination: string }[]>;
  const previous = {
    BACKEND_URL: process.env.BACKEND_URL,
    NEXT_PUBLIC_BACKEND_URL: process.env.NEXT_PUBLIC_BACKEND_URL,
    REACT_APP_BACKEND_URL: process.env.REACT_APP_BACKEND_URL,
  };
  try {
    process.env.NEXT_PUBLIC_BACKEND_URL = "http://127.0.0.1:3802";
    process.env.BACKEND_URL = "http://127.0.0.1:3801/";
    expect(await rewrites()).toEqual([
      { source: "/api/:path*", destination: "http://127.0.0.1:3801/api/:path*" },
    ]);
    delete process.env.BACKEND_URL;
    expect((await rewrites())[0].destination).toBe("http://127.0.0.1:3802/api/:path*");
    delete process.env.NEXT_PUBLIC_BACKEND_URL;
    process.env.REACT_APP_BACKEND_URL = "http://127.0.0.1:3803";
    expect((await rewrites())[0].destination).toBe("http://127.0.0.1:3803/api/:path*");
    delete process.env.REACT_APP_BACKEND_URL;
    expect((await rewrites())[0].destination).toBe("http://127.0.0.1:8001/api/:path*");
    process.env.BACKEND_URL = "http://127.0.0.1:3801/api/v1";
    await expect(rewrites()).rejects.toThrow(/origin/);
  } finally {
    for (const key of ["BACKEND_URL", "NEXT_PUBLIC_BACKEND_URL", "REACT_APP_BACKEND_URL"] as const) {
      if (previous[key] === undefined) delete process.env[key];
      else process.env[key] = previous[key];
    }
  }
});
