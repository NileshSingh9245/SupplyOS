"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Moon, Sun } from "lucide-react";
import { useThemeMode } from "@/lib/theme";

export function RecoveryFrame({
  title, description, children, label = "Account recovery",
}: {
  title: string;
  description: string;
  children: ReactNode;
  label?: string;
}) {
  const { mode, toggleMode } = useThemeMode();

  return (
    <main className="min-h-screen flex items-center justify-center p-4 sm:p-6 relative">
      <button
        type="button"
        className="btn-ghost absolute right-4 top-4 inline-flex items-center gap-2 text-xs"
        onClick={toggleMode}
        data-testid="recovery-theme-toggle"
      >
        {mode === "dark" ? <Sun size={14} /> : <Moon size={14} />}
        {mode === "dark" ? "Light" : "Dark"}
      </button>
      <section className="w-full max-w-md space-y-6 py-12">
        <p className="data-label">SupplyOS / {label}</p>
        <div className="space-y-3">
          <h1 className="font-display text-3xl sm:text-4xl font-black tracking-tightest">{title}</h1>
          <p className="text-text-secondary text-sm">{description}</p>
        </div>
        {children}
        <Link href="/login" className="text-volt text-sm hover:underline" data-testid="recovery-login-link">
          Back to sign in
        </Link>
      </section>
    </main>
  );
}
