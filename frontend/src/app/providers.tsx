"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/settings";
import { SESSION_EXPIRED_EVENT } from "@/lib/api";
import { staffHome } from "@/lib/navigation";
import { Toaster } from "sonner";
import { useThemeMode } from "@/lib/theme";

export function Providers({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 },
        },
      }),
  );
  const bootstrap = useAuth((s) => s.bootstrap);
  const user = useAuth((s) => s.user);
  const sessionVersion = useAuth((s) => s.sessionVersion);
  const { mode } = useThemeMode();
  // Recovery links and change outcomes survive self-revocation; account forms reset by identity.
  const pageKey = ["/forgot-password", "/reset-password", "/change-password"].includes(pathname) ? pathname : sessionVersion;

  useEffect(() => {
    const unsubscribe = useAuth.subscribe((state, previous) => {
      if (state.sessionVersion !== previous.sessionVersion) qc.clear();
    });
    const expire = () => useAuth.getState().expire();
    window.addEventListener(SESSION_EXPIRED_EVENT, expire);
    void bootstrap();
    return () => {
      unsubscribe();
      window.removeEventListener(SESSION_EXPIRED_EVENT, expire);
    };
  }, [bootstrap, qc]);

  const settingsScope = staffHome(user) ? `${user?.tenant_id}:${user?.id}:${user?.role}` : null;
  useEffect(() => {
    if (settingsScope) void useSettings.getState().load();
  }, [settingsScope]);

  return (
    <QueryClientProvider client={qc}>
      <Fragment key={pageKey}>{children}</Fragment>
      <Toaster
        theme={mode}
        position="top-right"
        toastOptions={{
          style: {
            background: "var(--surface1)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
            borderRadius: 2,
          },
        }}
      />
    </QueryClientProvider>
  );
}
