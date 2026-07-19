"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/settings";

export function Providers({ children }: { children: React.ReactNode }) {
  const [qc] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 },
        },
      }),
  );
  const bootstrap = useAuth((s) => s.bootstrap);
  const loadSettings = useSettings((s) => s.load);

  useEffect(() => {
    (async () => {
      await bootstrap();
      await loadSettings();
    })();
  }, [bootstrap, loadSettings]);

  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}
