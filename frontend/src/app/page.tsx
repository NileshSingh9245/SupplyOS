"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RootPage() {
  const router = useRouter();
  const user = useAuth((s) => s.user);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get<{ is_setup_complete: boolean }>("/setup/status");
        if (!data.is_setup_complete) {
          router.replace("/setup");
          return;
        }
        if (user === undefined) return; // still bootstrapping
        if (user === null) {
          router.replace("/login");
        } else {
          router.replace("/dashboard");
        }
      } finally {
        setChecking(false);
      }
    })();
  }, [router, user]);

  return (
    <div className="min-h-screen flex items-center justify-center" data-testid="root-loading">
      <div className="text-text-secondary font-mono text-xs uppercase tracking-widestUp">
        {checking ? "Initializing SupplyOS…" : ""}
      </div>
    </div>
  );
}
