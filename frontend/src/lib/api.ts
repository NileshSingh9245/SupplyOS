import axios, { type AxiosInstance } from "axios";

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  process.env.REACT_APP_BACKEND_URL ||
  "";
const apiBase = process.env.NEXT_PUBLIC_API_BASE || "/api/v1";

export const API_BASE = `${backendUrl}${apiBase}`;

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

// Auto-refresh on 401 once
let refreshInFlight: Promise<void> | null = null;
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (
      error.response?.status === 401 &&
      original &&
      !original._retried &&
      !original.url?.includes("/auth/")
    ) {
      original._retried = true;
      if (!refreshInFlight) {
        refreshInFlight = api.post("/auth/refresh").then(() => {
          refreshInFlight = null;
        }).catch(() => {
          refreshInFlight = null;
        });
      }
      await refreshInFlight;
      return api.request(original);
    }
    return Promise.reject(error);
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
