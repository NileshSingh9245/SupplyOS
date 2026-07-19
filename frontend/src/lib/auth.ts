"use client";

import { create } from "zustand";
import { api } from "./api";

export type Role =
  | "super_admin"
  | "warehouse_manager"
  | "accountant"
  | "delivery_partner"
  | "customer";

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
  bootstrap: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

export const useAuth = create<AuthState>((set) => ({
  user: undefined,
  bootstrap: async () => {
    try {
      const { data } = await api.get<AuthUser>("/auth/me");
      set({ user: data });
    } catch {
      set({ user: null });
    }
  },
  login: async (email, password) => {
    const { data } = await api.post<{ user: AuthUser }>("/auth/login", { email, password });
    set({ user: data.user });
  },
  logout: async () => {
    try { await api.post("/auth/logout"); } catch { /* ignore */ }
    set({ user: null });
  },
}));
