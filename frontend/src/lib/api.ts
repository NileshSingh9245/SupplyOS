import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from "axios";

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  process.env.REACT_APP_BACKEND_URL ||
  "";
const apiBase = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";

export const API_BASE = `${backendUrl.replace(/\/$/, "")}/${apiBase.replace(/^\//, "")}`;

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

interface SessionRequestConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
  _sessionVersion?: number;
  _accessVersion?: number;
  _isPublic?: boolean;
}

export const SESSION_EXPIRED_EVENT = "supplyos:session-expired";
let sessionVersion = 0;
let accessVersion = 0;
let refreshInFlight: Promise<void> | null = null;
let refreshController: AbortController | null = null;

export function resetApiSession() {
  sessionVersion += 1;
  accessVersion = 0;
  refreshController?.abort();
  refreshController = null;
  refreshInFlight = null;
}

function canRefresh(config: SessionRequestConfig) {
  const path = new URL(config.url || "", "http://supplyos.local").pathname;
  const isAuthEndpoint = /(?:^|\/)auth(?:\/|$)/.test(path);
  return !isAuthEndpoint || (
    /(?:^|\/)auth\/me\/?$/.test(path) && config.method === "get"
  );
}

function expireSession(version: number) {
  if (version === sessionVersion && typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
}

api.interceptors.request.use((config: SessionRequestConfig) => {
  // Public setup and recovery requests may finish while anonymous bootstrap resolves.
  config._isPublic = (config.method === "get" && config.url === "/setup/status") || (
    config.method === "post" && [
      "/setup/initialize", "/auth/forgot-password", "/auth/reset-password",
    ].includes(config.url || "")
  );
  config._sessionVersion ??= sessionVersion;
  if (config._sessionVersion !== sessionVersion && !config._isPublic) {
    throw new axios.CanceledError("Session changed.");
  }
  config._accessVersion = accessVersion;
  return config;
});

api.interceptors.response.use(
  (response) => {
    const config = response.config as SessionRequestConfig;
    if (config._sessionVersion !== sessionVersion && !config._isPublic) {
      throw new axios.CanceledError("Session changed.");
    }
    return response;
  },
  async (error) => {
    if (!axios.isAxiosError(error)) throw error;
    const original = error.config as SessionRequestConfig | undefined;
    if (!original) throw error;
    if (original._isPublic) throw error;
    const version = original._sessionVersion;
    if (version !== sessionVersion) throw new axios.CanceledError("Session changed.");
    if (error.response?.status !== 401 || !canRefresh(original)) throw error;

    if (original._retried) {
      expireSession(version);
      throw error;
    }
    original._retried = true;
    // A late 401 may belong to the access cookie replaced by an already-finished refresh.
    if (original._accessVersion !== accessVersion) return api.request(original);
    if (!refreshInFlight) {
      const controller = new AbortController();
      refreshController = controller;
      refreshInFlight = api.post("/auth/refresh", undefined, { signal: controller.signal })
        .then(() => {
          if (version === sessionVersion) accessVersion += 1;
        })
        .finally(() => {
          if (refreshController === controller) {
            refreshController = null;
            refreshInFlight = null;
          }
        });
    }
    try {
      await refreshInFlight;
    } catch (refreshError) {
      if (axios.isAxiosError(refreshError) && [401, 403].includes(refreshError.response?.status || 0)) {
        expireSession(version);
      }
      throw refreshError;
    }
    if (version !== sessionVersion) throw new axios.CanceledError("Session changed.");
    return api.request(original);
  },
);

export function apiError(err: unknown): string {
  const anyErr = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = anyErr?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((e: { msg?: string }) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e)))
      .filter(Boolean)
      .join(" ");
  if (detail && typeof (detail as { msg?: string }).msg === "string")
    return (detail as { msg: string }).msg;
  return anyErr?.message || "Something went wrong.";
}
