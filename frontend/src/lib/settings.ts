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
  reset: () => void;
}

export const useSettings = create<SettingsState>((set) => {
  let requestVersion = 0;
  return {
    data: null,
    load: async () => {
      const version = ++requestVersion;
      try {
        const { data } = await api.get<SettingsPayload>("/settings");
        if (version === requestVersion) set({ data });
      } catch {
        /* Settings are optional until an authenticated staff session is available. */
      }
    },
    update: async (patch) => {
      const version = ++requestVersion;
      const { data } = await api.patch<SettingsPayload>("/settings", { patch });
      if (version === requestVersion) set({ data });
    },
    reset: () => {
      ++requestVersion;
      set({ data: null });
    },
  };
});
