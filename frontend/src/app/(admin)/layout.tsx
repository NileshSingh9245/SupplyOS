"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import {
  LayoutDashboard, Boxes, Warehouse, Package, Users, Wallet,
  Sparkles, Settings, Truck, ScrollText, ShoppingBag, LogOut,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useSettings } from "@/lib/settings";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/inventory", label: "Inventory", icon: Boxes },
  { href: "/warehouses", label: "Warehouses", icon: Warehouse },
  { href: "/products", label: "Products", icon: Package },
  { href: "/customers", label: "Customers", icon: Users },
  { href: "/orders", label: "Orders", icon: ShoppingBag },
  { href: "/deliveries", label: "Deliveries", icon: Truck },
  { href: "/finance", label: "Finance", icon: Wallet },
  { href: "/ai-supervisor", label: "AI Supervisor", icon: Sparkles },
  { href: "/settings", label: "Rules & Settings", icon: Settings },
  { href: "/audit", label: "Audit Log", icon: ScrollText },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const settings = useSettings((s) => s.data);

  useEffect(() => {
    if (user === null) router.replace("/login");
  }, [user, router]);

  if (user === undefined || user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center text-text-secondary font-mono text-xs">
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen flex" data-testid="admin-shell">
      {/* Sidebar */}
      <aside className="w-60 shrink-0 border-r border-border bg-surface1 flex flex-col relative z-10">
        <div className="px-5 py-6 border-b border-border">
          <div className="flex items-center gap-2">
            <div className="w-2 h-6 bg-volt" />
            <span className="font-display text-lg font-black tracking-tightest">SupplyOS</span>
          </div>
          <p className="data-label mt-1">{settings?.company_name || "—"}</p>
        </div>

        <nav className="flex-1 py-3 overflow-y-auto">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || pathname.startsWith(href + "/");
            return (
              <Link key={href} href={href}
                data-testid={`nav-${href.slice(1)}`}
                className={cn(
                  "flex items-center gap-3 px-5 py-2.5 text-sm border-l-2 transition-colors",
                  active
                    ? "text-volt border-volt bg-white/[0.03]"
                    : "text-text-secondary border-transparent hover:text-text-primary hover:bg-white/[0.02]",
                )}
              >
                <Icon size={16} strokeWidth={active ? 2.5 : 1.75} />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-border p-4 space-y-2">
          <div>
            <p className="text-sm truncate" data-testid="me-name">{user.full_name}</p>
            <p className="data-label truncate">{user.role.replace("_", " ")}</p>
          </div>
          <button className="btn-ghost w-full text-xs flex items-center justify-center gap-2"
            data-testid="logout-button"
            onClick={async () => { await logout(); router.replace("/login"); }}>
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-hidden relative z-10">{children}</main>
    </div>
  );
}
