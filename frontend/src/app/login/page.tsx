"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { apiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/settings";

export default function LoginPage() {
  const router = useRouter();
  const login = useAuth((s) => s.login);
  const loadSettings = useSettings((s) => s.load);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email.trim(), password);
      await loadSettings();
      toast.success("Signed in.");
      router.replace("/dashboard");
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen flex">
      <div
        className="hidden md:block w-1/2 relative"
        style={{
          backgroundImage: `url(https://images.pexels.com/photos/9305407/pexels-photo-9305407.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940)`,
          backgroundSize: "cover", backgroundPosition: "center",
        }}
      >
        <div className="absolute inset-0 bg-gradient-to-br from-bg via-bg/60 to-transparent" />
        <div className="relative z-10 h-full flex flex-col justify-between p-10">
          <p className="data-label">SupplyOS · Admin</p>
          <div>
            <h2 className="font-display text-5xl font-black tracking-tightest leading-none">
              Run the warehouse<br/>like a mission control.
            </h2>
            <p className="text-text-secondary mt-4 max-w-md">
              Multi-warehouse inventory, credit ledger, AI supervisor. Made for Indian wholesalers.
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-md space-y-4" data-testid="login-form">
          <p className="data-label">Sign in</p>
          <h1 className="font-display text-4xl font-black tracking-tightest">Welcome back.</h1>
          <p className="text-text-secondary text-sm">Enter your admin credentials to continue.</p>

          <div className="pt-6 space-y-3">
            <div>
              <label className="data-label">Email</label>
              <input className="input mt-1" data-testid="login-email" type="email"
                value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            </div>
            <div>
              <label className="data-label">Password</label>
              <input className="input mt-1" data-testid="login-password" type="password"
                value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
          </div>

          <button className="btn-volt w-full mt-6" data-testid="login-submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in →"}
          </button>

          <p className="text-text-tertiary text-xs pt-2">
            Forgot your password? <a href="#" className="text-volt hover:underline">Reset via email</a>
          </p>
        </form>
      </div>
    </main>
  );
}
