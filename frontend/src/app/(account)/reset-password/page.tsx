"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import axios from "axios";
import { api, apiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { RecoveryFrame } from "@/features/auth/recovery-frame";

export default function ResetPasswordPage() {
  const token = useRef<string | null>(null);
  const [linkState, setLinkState] = useState<"loading" | "ready" | "missing">("loading");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function readLink() {
      // Fragments never reach the server; also accept a newly opened email link in this tab.
      if (window.location.hash) {
        const values = new URLSearchParams(window.location.hash.slice(1)).getAll("token");
        token.current = values.length === 1 && values[0].length > 0 && values[0].length <= 128
          ? values[0] : null;
        setPassword("");
        setConfirmation("");
        setError(null);
        setCompleted(false);
      }
      window.history.replaceState(window.history.state, "", window.location.pathname);
      setLinkState(token.current ? "ready" : "missing");
    }
    readLink();
    window.addEventListener("hashchange", readLink);
    return () => window.removeEventListener("hashchange", readLink);
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !token.current || completed) return;
    setError(null);
    if (Array.from(password).length < 12 || new TextEncoder().encode(password).length > 72) {
      setError("Use at least 12 characters and no more than 72 UTF-8 bytes.");
      return;
    }
    if (password !== confirmation) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    const submittedToken = token.current;
    try {
      await api.post("/auth/reset-password", { token: submittedToken, new_password: password });
      useAuth.getState().expire();
      if (token.current !== submittedToken) return;
      token.current = null;
      setPassword("");
      setConfirmation("");
      setCompleted(true);
    } catch (failure) {
      if (token.current !== submittedToken) return;
      setError(axios.isAxiosError(failure) && !failure.response
        ? "The reset could not be confirmed. Try signing in with your new password before requesting another link."
        : apiError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <RecoveryFrame title="Set a new password." description="Your reset link is single-use. Updating your password signs out existing sessions.">
      {completed ? (
        <p role="status" className="text-text-secondary text-sm" data-testid="reset-completed">
          Your password has been updated. Sign in again with your new password.
        </p>
      ) : linkState === "loading" ? (
        <p role="status" className="text-text-secondary text-sm">Checking your reset link...</p>
      ) : linkState === "missing" ? (
        <div className="space-y-3" data-testid="reset-missing">
          <p role="alert" className="text-text-secondary text-sm">
            This page has no valid reset link. Open the link from your email or request a new one.
          </p>
          <Link href="/forgot-password" className="text-volt text-sm hover:underline">Request a new link</Link>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4" aria-busy={busy} data-testid="reset-form">
          <div>
            <label className="data-label" htmlFor="reset-password">New password</label>
            <input
              id="reset-password" className="input mt-1" type="password" autoComplete="new-password"
              required minLength={12} maxLength={72} autoFocus disabled={busy}
              value={password} onChange={(event) => setPassword(event.target.value)}
              aria-describedby="reset-password-help" data-testid="reset-password"
            />
            <p id="reset-password-help" className="text-text-tertiary text-xs mt-2">
              At least 12 characters, up to 72 UTF-8 bytes. Longer Unicode passwords can reach the byte limit sooner.
            </p>
          </div>
          <div>
            <label className="data-label" htmlFor="reset-confirmation">Confirm new password</label>
            <input
              id="reset-confirmation" className="input mt-1" type="password" autoComplete="new-password"
              required minLength={12} maxLength={72} disabled={busy}
              value={confirmation} onChange={(event) => setConfirmation(event.target.value)}
              data-testid="reset-confirmation"
            />
          </div>
          {error ? <p role="alert" className="text-sm text-red-400">{error}</p> : null}
          <button className="btn-volt w-full" disabled={busy} data-testid="reset-submit">
            {busy ? "Updating..." : "Update password"}
          </button>
          <Link href="/forgot-password" className="text-volt text-sm hover:underline">Request a new link</Link>
        </form>
      )}
    </RecoveryFrame>
  );
}
