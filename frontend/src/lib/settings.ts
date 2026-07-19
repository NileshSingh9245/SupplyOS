"use client";

import { create } from "zustand";
import { api } from "./api";

export interface SettingsPayload {
  tenant_id: string;
  company_name: string;
  currency_code: string;
  currency_symbol: string;
  locale: string;
  values: Record<string, unknown>;
}

interface SettingsState {
  data: SettingsPayload | null;
  load: () => Promise<void>;
  update: (patch: Record<string, unknown>) => Promise<void>;
}

export const useSettings = create<SettingsState>((set) => ({
  data: null,
  load: async () => {
    try {
      const { data } = await api.get<SettingsPayload>("/settings");
      set({ data });
    } catch {
      /* ignore — not authenticated yet */
    }
  },
  update: async (patch) => {
    const { data } = await api.patch<SettingsPayload>("/settings", { patch });
    set({ data });
  },
}));
