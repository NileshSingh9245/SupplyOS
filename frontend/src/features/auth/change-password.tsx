"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import axios from "axios";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/lib/auth";
import { staffHome } from "@/lib/navigation";
import { accountPasswordSchema } from "@/lib/staff";
import { RecoveryFrame } from "./recovery-frame";

const passwordSchema = z.object({
  currentPassword: z.string().min(6, "Enter your current password.").max(200),
  newPassword: accountPasswordSchema,
  confirmation: z.string(),
}).refine((value) => value.newPassword === value.confirmation, {
  path: ["confirmation"], message: "The passwords do not match.",
}).refine((value) => value.newPassword !== value.currentPassword, {
  path: ["newPassword"], message: "Choose a password different from your current password.",
});
type PasswordFields = z.infer<typeof passwordSchema>;
const fields = [
  { name: "currentPassword", label: "Current password", autocomplete: "current-password" },
  { name: "newPassword", label: "New password", autocomplete: "new-password" },
  { name: "confirmation", label: "Confirm new password", autocomplete: "new-password" },
] as const;

function PasswordChangeForm() {
  const { register, handleSubmit, reset, formState: { errors } } = useForm<PasswordFields>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { currentPassword: "", newPassword: "", confirmation: "" },
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function submit(values: PasswordFields) {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(null);
    try {
      await useAuth.getState().changePassword(values.currentPassword, values.newPassword);
    } catch (failure) {
      if (!mounted.current || axios.isCancel(failure)) return;
      const status = axios.isAxiosError(failure) ? failure.response?.status : undefined;
      if (status === undefined || status === 401 || status === 408 || status >= 500) return;
      setError(status === 429 ? "Too many password checks. Wait before trying again."
        : status === 400 ? "Check your current password and choose a different new password."
        : "Password change was rejected. Check the requirements and try again.");
    } finally {
      pending.current = false;
      if (mounted.current) {
        reset();
        setBusy(false);
      }
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(submit)(event)} className="space-y-4" aria-busy={busy} data-testid="change-password-form">
      {fields.map(({ name, label, autocomplete }) => (
        <div key={name}>
          <label className="data-label" htmlFor={`change-${name}`}>{label}</label>
          <input
            {...register(name)} id={`change-${name}`} className="input mt-1" type="password"
            autoComplete={autocomplete} required disabled={busy}
            maxLength={name === "currentPassword" ? 200 : 72}
            aria-invalid={!!errors[name]} aria-describedby={errors[name] ? `change-${name}-error` : "change-password-help"}
            data-testid={`change-${name}`}
          />
          {errors[name] ? <p id={`change-${name}-error`} role="alert" className="text-sm text-red-400 mt-1">{errors[name]?.message}</p> : null}
        </div>
      ))}
      <p id="change-password-help" className="text-text-tertiary text-xs">
        At least 12 characters, up to 72 UTF-8 bytes. All sessions and outstanding reset links are retired on success.
      </p>
      {error ? <p role="alert" className="text-sm text-red-400">{error}</p> : null}
      <button className="btn-volt w-full" disabled={busy} data-testid="change-password-submit">
        {busy ? "Updating..." : "Change password and sign out"}
      </button>
    </form>
  );
}

export function ChangePassword() {
  const user = useAuth((state) => state.user);
  const bootstrapError = useAuth((state) => state.bootstrapError);
  const bootstrap = useAuth((state) => state.bootstrap);
  const sessionVersion = useAuth((state) => state.sessionVersion);
  const outcome = useAuth((state) => state.passwordChangeOutcome);
  const home = staffHome(user);

  return (
    <RecoveryFrame label="Account security" title="Change your password." description="Confirm your current password. A successful change signs out every device and requires a fresh login.">
      {outcome ? (
        <p role={outcome === "changed" ? "status" : "alert"} className="text-text-secondary text-sm" data-testid={`password-change-${outcome}`}>
          {outcome === "changed" ? "Your password has been changed. Sign in again with your new password."
            : outcome === "session-ended" ? "Your session is no longer valid. Sign in again before changing your password."
            : "The password change could not be confirmed. Sign in with your new password first; if it was not applied, use your current password. Do not submit the change again automatically."}
        </p>
      ) : user === undefined ? (
        <div className="space-y-3">
          <p role={bootstrapError ? "alert" : "status"} className="text-text-secondary text-sm">{bootstrapError || "Checking your session..."}</p>
          {bootstrapError ? <button className="btn-ghost" onClick={() => bootstrap()}>Retry session</button> : null}
        </div>
      ) : user?.is_active ? <PasswordChangeForm key={sessionVersion} /> : (
        <p role="status" className="text-text-secondary text-sm" data-testid="password-change-sign-in">Sign in before changing your password.</p>
      )}
      {home ? <Link href={home} className="text-volt text-sm hover:underline">Back to workspace</Link> : null}
    </RecoveryFrame>
  );
}
