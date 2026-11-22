"use client";

import { useEffect, useState } from "react";

export type ThemeMode = "dark" | "light";

const STORAGE_KEY = "supplyos-theme";

function readStoredTheme(): ThemeMode | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  return raw === "light" || raw === "dark" ? raw : null;
}

function detectPreferredTheme(): ThemeMode {
  if (typeof window === "undefined") return "dark";
  const stored = readStoredTheme();
  if (stored) return stored;
  return window.matchMedia("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

export function applyTheme(mode: ThemeMode) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.toggle("light", mode === "light");
  root.dataset.theme = mode;
}

export function setThemeMode(mode: ThemeMode) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, mode);
    window.dispatchEvent(
      new CustomEvent("supplyos-theme-change", { detail: mode }),
    );
  }
  applyTheme(mode);
}

export function useThemeMode() {
  const [mode, setMode] = useState<ThemeMode>("dark");

  useEffect(() => {
    const next = detectPreferredTheme();
    // Client-only storage cannot be read during the server's initial theme render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMode(next);
    applyTheme(next);

    const onThemeEvent = (event: Event) => {
      const custom = event as CustomEvent<ThemeMode>;
      if (custom.detail === "dark" || custom.detail === "light") {
        setMode(custom.detail);
        applyTheme(custom.detail);
      }
    };

    const onStorage = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY) return;
      const nextMode = detectPreferredTheme();
      setMode(nextMode);
      applyTheme(nextMode);
    };

    window.addEventListener(
      "supplyos-theme-change",
      onThemeEvent as EventListener,
    );
    window.addEventListener("storage", onStorage);

    return () => {
      window.removeEventListener(
        "supplyos-theme-change",
        onThemeEvent as EventListener,
      );
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const updateMode = (nextMode: ThemeMode) => {
    setMode(nextMode);
    setThemeMode(nextMode);
  };

  const toggleMode = () => updateMode(mode === "dark" ? "light" : "dark");

  return { mode, setMode: updateMode, toggleMode };
}
