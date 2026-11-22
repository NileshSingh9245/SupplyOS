"use client";

import { useState } from "react";
import { api, apiError } from "@/lib/api";
import { RecoveryFrame } from "@/features/auth/recovery-frame";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [busy, setBusy] = useState(false);
  const [requested, setRequested] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      await api.post("/auth/forgot-password", {
        email: email.trim(),
        ...(tenantId.trim() ? { tenant_id: tenantId.trim() } : {}),
      });
      setEmail("");
      setTenantId("");
      setRequested(true);
    } catch (failure) {
      setError(apiError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <RecoveryFrame title="Recover your account." description="Request a private reset link for your existing account.">
      {requested ? (
        <div className="space-y-4" data-testid="forgot-requested">
          <p role="status" className="text-text-secondary text-sm">
            If an active account matches these details, a reset email has been requested.
            Check your inbox. Contact your business administrator if it does not arrive.
          </p>
          <button type="button" className="btn-ghost" onClick={() => setRequested(false)}>
            Request another link
          </button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4" aria-busy={busy} data-testid="forgot-form">
          <div>
            <label className="data-label" htmlFor="forgot-email">Account email</label>
            <input
              id="forgot-email" className="input mt-1" type="email" autoComplete="email"
              value={email} onChange={(event) => setEmail(event.target.value)}
              required maxLength={200} disabled={busy} autoFocus data-testid="forgot-email"
            />
          </div>
          <div>
            <label className="data-label" htmlFor="forgot-tenant">Business ID (optional)</label>
            <input
              id="forgot-tenant" className="input mt-1" autoComplete="off" maxLength={36}
              pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
              title="Enter a valid business UUID."
              value={tenantId} onChange={(event) => setTenantId(event.target.value)} disabled={busy}
              aria-describedby="forgot-tenant-help" data-testid="forgot-tenant"
            />
            <p id="forgot-tenant-help" className="text-text-tertiary text-xs mt-2">
              If you use the same email for multiple businesses, enter the ID supplied by your administrator.
            </p>
          </div>
          {error ? <p role="alert" className="text-sm text-red-400">{error}</p> : null}
          <button className="btn-volt w-full" disabled={busy} data-testid="forgot-submit">
            {busy ? "Requesting..." : "Request reset email"}
          </button>
        </form>
      )}
    </RecoveryFrame>
  );
}
