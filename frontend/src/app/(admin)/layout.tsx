"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  LayoutDashboard, Boxes, Warehouse, Package, Users, Wallet,
  Sparkles, Settings, Truck, ScrollText, ShoppingBag, LogOut, Menu, X,
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
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    if (user === null) router.replace("/login");
  }, [user, router]);

  // Close drawer on route change
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // Lock body scroll when drawer is open (mobile)
  useEffect(() => {
    if (drawerOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => { document.body.style.overflow = ""; };
  }, [drawerOpen]);

  if (user === undefined || user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center text-text-secondary font-mono text-xs px-4 text-center">
        Loading…
      </div>
    );
  }

  const activePageLabel =
    NAV.find((n) => pathname === n.href || pathname.startsWith(n.href + "/"))?.label ?? "";

  const SidebarInner = (
    <>
      <div className="px-5 py-5 border-b border-border flex items-center justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <div className="w-2 h-6 bg-volt shrink-0" />
            <span className="font-display text-lg font-black tracking-tightest">SupplyOS</span>
          </div>
          <p className="data-label mt-1 truncate">{settings?.company_name || "—"}</p>
        </div>
        {/* Close button visible only when drawer is open on mobile */}
        <button
          className="md:hidden text-text-secondary hover:text-text-primary p-1"
          onClick={() => setDrawerOpen(false)}
          data-testid="drawer-close"
          aria-label="Close menu"
        >
          <X size={20} />
        </button>
      </div>

      <nav className="flex-1 py-3 overflow-y-auto">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link key={href} href={href}
              data-testid={`nav-${href.slice(1)}`}
              className={cn(
                "flex items-center gap-3 px-5 py-3 md:py-2.5 text-sm border-l-2 transition-colors",
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
        <div className="min-w-0">
          <p className="text-sm truncate" data-testid="me-name">{user.full_name}</p>
          <p className="data-label truncate">{user.role.replace("_", " ")}</p>
        </div>
        <button className="btn-ghost w-full text-xs flex items-center justify-center gap-2"
          data-testid="logout-button"
          onClick={async () => { await logout(); router.replace("/login"); }}>
          <LogOut size={14} /> Sign out
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen md:flex" data-testid="admin-shell">
      {/* --- Mobile top bar (hamburger) — sticky --- */}
      <div className="md:hidden sticky top-0 z-40 bg-surface1 border-b border-border flex items-center justify-between px-4 h-14">
        <button
          className="p-2 -ml-2 text-text-primary"
          onClick={() => setDrawerOpen(true)}
          data-testid="mobile-menu-open"
          aria-label="Open menu"
        >
          <Menu size={22} />
        </button>
        <div className="flex items-center gap-2 min-w-0">
          <div className="w-1.5 h-5 bg-volt shrink-0" />
          <span className="font-display text-base font-black tracking-tightest truncate">
            {activePageLabel || "SupplyOS"}
          </span>
        </div>
        <div className="w-8" /> {/* spacer for symmetry */}
      </div>

      {/* --- Desktop sidebar --- */}
      <aside className="hidden md:flex w-56 lg:w-60 shrink-0 border-r border-border bg-surface1 flex-col relative z-10">
        {SidebarInner}
      </aside>

      {/* --- Mobile drawer + backdrop --- */}
      {drawerOpen && (
        <>
          <div
            className="md:hidden fixed inset-0 bg-black/70 z-40"
            onClick={() => setDrawerOpen(false)}
            data-testid="mobile-drawer-backdrop"
          />
          <aside
            className="md:hidden fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] bg-surface1 border-r border-border flex flex-col animate-slide-in"
            data-testid="mobile-drawer"
          >
            {SidebarInner}
          </aside>
        </>
      )}

      {/* --- Main --- */}
      <main className="flex-1 min-w-0 relative z-0 md:overflow-hidden">
        {children}
      </main>
    </div>
  );
}
