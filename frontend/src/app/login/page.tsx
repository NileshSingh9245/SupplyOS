"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { apiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { staffHome } from "@/lib/navigation";
import { useThemeMode } from "@/lib/theme";
import { Moon, Sun } from "lucide-react";

export default function LoginPage() {
  const router = useRouter();
  const login = useAuth((s) => s.login);
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const { mode, toggleMode } = useThemeMode();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const home = staffHome(user);
  useEffect(() => {
    if (home) router.replace(home);
  }, [home, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const signedIn = await login(email.trim(), password);
      const destination = staffHome(signedIn);
      if (destination) {
        toast.success("Signed in.");
        router.replace(destination);
      }
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
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
      >
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(140deg, var(--hero-overlay-start) 0%, var(--hero-overlay-mid) 52%, var(--hero-overlay-end) 100%)",
          }}
        />
        <div className="relative z-10 h-full flex flex-col justify-between p-10">
          <p className="data-label">SupplyOS · Admin</p>
          <div>
            <h2 className="font-display text-5xl font-black tracking-tightest leading-none">
              Run the warehouse
              <br />
              like a mission control.
            </h2>
            <p className="text-text-secondary mt-4 max-w-md">
              Multi-warehouse inventory, credit ledger, AI supervisor. Made for
              Indian wholesalers.
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 flex items-center justify-center p-4 sm:p-6 relative">
        <button
          className="btn-ghost absolute right-4 top-4 inline-flex items-center gap-2 text-xs"
          type="button"
          onClick={toggleMode}
          data-testid="login-theme-toggle"
        >
          {mode === "dark" ? <Sun size={14} /> : <Moon size={14} />}
          {mode === "dark" ? "Light" : "Dark"}
        </button>
        {user && !home ? (
          <section className="w-full max-w-md space-y-4" data-testid="staff-access-denied">
            <p className="data-label">Staff access required</p>
            <h1 className="font-display text-3xl font-black tracking-tightest">
              This account cannot access the staff dashboard.
            </h1>
            <p className="text-text-secondary text-sm">
              Sign in with an active admin, warehouse manager, or accountant account.
              Customer and delivery accounts use their respective applications.
            </p>
            <button className="btn-volt" onClick={() => logout()} data-testid="staff-sign-out">
              Sign out
            </button>
          </section>
        ) : <form
          onSubmit={submit}
          className="w-full max-w-md space-y-4"
          data-testid="login-form"
        >
          <p className="data-label">Sign in</p>
          <h1 className="font-display text-3xl sm:text-4xl font-black tracking-tightest">
            Welcome back.
          </h1>
          <p className="text-text-secondary text-sm">
            Enter your staff credentials to continue.
          </p>

          <div className="pt-6 space-y-3">
            <div>
              <label className="data-label" htmlFor="login-email">Email</label>
              <input
                id="login-email"
                className="input mt-1"
                data-testid="login-email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div>
              <label className="data-label" htmlFor="login-password">Password</label>
              <input
                id="login-password"
                className="input mt-1"
                data-testid="login-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <button
            className="btn-volt w-full mt-6"
            data-testid="login-submit"
            disabled={busy}
          >
            {busy ? "Signing in…" : "Sign in →"}
          </button>

          <p className="text-text-tertiary text-xs pt-2">
            Forgot your password?{" "}
            <Link href="/forgot-password" className="text-volt hover:underline" data-testid="forgot-password-link">
              Reset via email
            </Link>
          </p>
        </form>}
      </div>
    </main>
  );
}
