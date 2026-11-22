"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { staffHome } from "@/lib/navigation";

export default function RootPage() {
  const router = useRouter();
  const user = useAuth((s) => s.user);
  const bootstrap = useAuth((s) => s.bootstrap);
  const bootstrapError = useAuth((s) => s.bootstrapError);
  const { data, error, refetch } = useQuery({
    queryKey: ["setup-status"],
    queryFn: async ({ signal }) =>
      (await api.get<{ is_setup_complete: boolean }>("/setup/status", { signal })).data,
    retry: false,
  });

  useEffect(() => {
    if (!data) return;
    if (!data.is_setup_complete) router.replace("/setup");
    else if (user !== undefined) router.replace(staffHome(user) || "/login");
  }, [router, user, data]);

  const message = error ? apiError(error) : bootstrapError;
  return (
    <div className="min-h-screen flex flex-col gap-4 items-center justify-center px-4 text-center" data-testid="root-loading">
      <p className="text-text-secondary font-mono text-xs" role={message ? "alert" : "status"}>
        {message || "Initializing SupplyOS..."}
      </p>
      {message && (
        <button className="btn-ghost" onClick={() => { void refetch(); void bootstrap(); }}>
          Retry
        </button>
      )}
    </div>
  );
}
