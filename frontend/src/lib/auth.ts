"use client";

import { create } from "zustand";
import axios from "axios";
import { api, apiError, resetApiSession } from "./api";
import { useSettings } from "./settings";

export type Role =
  | "super_admin"
  | "warehouse_manager"
  | "accountant"
  | "delivery_partner"
  | "customer";

export type PasswordChangeOutcome = "changed" | "unconfirmed" | "session-ended";

export interface AuthUser {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
}

interface AuthState {
  user: AuthUser | null | undefined; // undefined = loading, null = anonymous
  sessionVersion: number;
  bootstrapError: string | null;
  passwordChangeOutcome: PasswordChangeOutcome | null;
  bootstrap: () => Promise<void>;
  login: (email: string, password: string) => Promise<AuthUser>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  logout: () => Promise<void>;
  expire: (outcome?: PasswordChangeOutcome) => void;
}

export const useAuth = create<AuthState>((set, get) => {
  let operation = 0;
  let bootstrapInFlight: Promise<void> | null = null;
  let authController: AbortController | null = null;

  function setUser(user: AuthState["user"], passwordChangeOutcome: PasswordChangeOutcome | null = null) {
    const previous = get().user;
    const changed = previous?.id !== user?.id || previous?.tenant_id !== user?.tenant_id ||
      previous?.role !== user?.role || previous?.is_active !== user?.is_active;
    if (changed) {
      resetApiSession();
      useSettings.getState().reset();
    }
    set({
      user,
      bootstrapError: null,
      passwordChangeOutcome,
      sessionVersion: get().sessionVersion + (changed ? 1 : 0),
    });
  }

  function beginAuthRequest() {
    const current = ++operation;
    bootstrapInFlight = null;
    authController?.abort();
    const controller = new AbortController();
    authController = controller;
    resetApiSession();
    set({ passwordChangeOutcome: null });
    return { current, controller };
  }

  return {
    user: undefined,
    sessionVersion: 0,
    bootstrapError: null,
    passwordChangeOutcome: null,
    bootstrap: () => {
      if (authController) return Promise.resolve();
      if (bootstrapInFlight) return bootstrapInFlight;
      const current = operation;
      set({ bootstrapError: null });
      const request = (async () => {
        try {
          const { data } = await api.get<AuthUser>("/auth/me");
          if (current === operation) setUser(data);
        } catch (error) {
          if (current !== operation || axios.isCancel(error)) return;
          if (axios.isAxiosError(error) && [401, 403].includes(error.response?.status || 0)) {
            setUser(null);
          } else {
            set({ bootstrapError: apiError(error) });
          }
        }
      })().finally(() => {
        if (bootstrapInFlight === request) bootstrapInFlight = null;
      });
      bootstrapInFlight = request;
      return request;
    },
    login: async (email, password) => {
      const { current, controller } = beginAuthRequest();
      setUser(undefined);
      try {
        const { data } = await api.post<{ user: AuthUser }>(
          "/auth/login", { email, password }, { signal: controller.signal },
        );
        if (current !== operation) throw new axios.CanceledError("Session changed.");
        setUser(data.user);
        return data.user;
      } catch (error) {
        if (current === operation) setUser(null);
        throw error;
      } finally {
        if (authController === controller) authController = null;
      }
    },
    changePassword: async (currentPassword, newPassword) => {
      if (!get().user?.is_active) throw new Error("Sign in to change your password.");
      if (authController) throw new axios.CanceledError("An account request is already in progress.");
      const { current, controller } = beginAuthRequest();
      try {
        const response = await api.post("/auth/change-password", {
          current_password: currentPassword, new_password: newPassword,
        }, { signal: controller.signal, timeout: 30_000 });
        if (current !== operation) throw new axios.CanceledError("Session changed.");
        if (response.status !== 200 || response.data?.message !== "Password changed. Sign in again.") {
          throw new Error("Password change could not be confirmed.");
        }
        get().expire("changed");
      } catch (error) {
        if (current !== operation || axios.isCancel(error)) throw error;
        const status = axios.isAxiosError(error) ? error.response?.status : undefined;
        // A lost reply can follow a committed change. Require re-login, never replay credentials.
        if (status === 401) get().expire("session-ended");
        else if (status === undefined || status === 408 || status >= 500) get().expire("unconfirmed");
        throw error;
      } finally {
        if (authController === controller) authController = null;
      }
    },
    logout: async () => {
      const { controller } = beginAuthRequest();
      setUser(null);
      try {
        await api.post("/auth/logout", undefined, { signal: controller.signal });
      } catch {
        /* Local data is cleared even offline or when a new login supersedes logout. */
      } finally {
        if (authController === controller) authController = null;
      }
    },
    expire: (outcome) => {
      ++operation;
      bootstrapInFlight = null;
      authController?.abort();
      authController = null;
      resetApiSession();
      setUser(null, outcome);
    },
  };
});
