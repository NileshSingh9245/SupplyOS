"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatINR } from "@/lib/utils";
import {
  AlertTriangle, TrendingUp, PackageCheck, Boxes, Sparkles, ArrowRight,
} from "lucide-react";

interface InventoryStats {
  total_products: number; low_stock: number; out_of_stock: number;
  total_inventory_value: string; total_reserved: string;
}
interface OrderStats {
  total_orders: number; pending: number; confirmed: number; reserved: number;
  out_for_delivery: number; delivered_today: number; revenue_today: string;
}
interface Alert {
  id: string; category: string; severity: string; title: string;
  message: string; action_hint: string | null; created_at: string;
}

export default function DashboardPage() {
  const { data: inv } = useQuery({
    queryKey: ["inv-stats"],
    queryFn: async () => (await api.get<InventoryStats>("/inventory/stats")).data,
  });
  const { data: ord } = useQuery({
    queryKey: ["order-stats"],
    queryFn: async () => (await api.get<OrderStats>("/orders/stats")).data,
  });
  const { data: alerts } = useQuery({
    queryKey: ["alerts"],
    queryFn: async () => (await api.get<Alert[]>("/ai/alerts?limit=6")).data,
  });

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex items-center justify-between">
        <div>
          <p className="data-label">Command centre</p>
          <h1 className="font-display text-3xl font-black tracking-tightest">Today · Overview</h1>
        </div>
        <Link href="/ai-supervisor" className="btn-volt inline-flex items-center gap-2" data-testid="dashboard-ai-cta">
          <Sparkles size={16} /> AI Supervisor
        </Link>
      </header>

      <div className="p-8 space-y-6 overflow-y-auto">
        {/* KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-0 border border-border">
          <KpiCell label="Revenue today" value={formatINR(ord?.revenue_today ?? "0")} sub="Delivered orders" />
          <KpiCell label="Orders" value={ord?.total_orders ?? 0} sub={`${ord?.pending ?? 0} pending`} />
          <KpiCell label="Inventory value" value={formatINR(inv?.total_inventory_value ?? "0")} sub={`${inv?.total_products ?? 0} SKUs`} />
          <KpiCell
            label="Stock alerts"
            value={(inv?.low_stock ?? 0) + (inv?.out_of_stock ?? 0)}
            sub={`${inv?.out_of_stock ?? 0} out of stock`}
            tone={((inv?.out_of_stock ?? 0) > 0) ? "alert" : ((inv?.low_stock ?? 0) > 0 ? "warning" : "success")}
          />
        </div>

        <div className="grid lg:grid-cols-3 gap-6">
          {/* Order state pipeline */}
          <div className="pane p-6 lg:col-span-2">
            <div className="flex items-center justify-between mb-6">
              <div>
                <p className="data-label">Order pipeline</p>
                <h3 className="font-display text-xl font-bold mt-1">In-flight orders</h3>
              </div>
              <Link href="/orders" className="text-volt text-sm hover:underline inline-flex items-center gap-1">
                Open orders <ArrowRight size={14} />
              </Link>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-0 border border-border">
              <Stage label="Pending" value={ord?.pending ?? 0} />
              <Stage label="Confirmed" value={ord?.confirmed ?? 0} />
              <Stage label="Reserved" value={ord?.reserved ?? 0} />
              <Stage label="Out for delivery" value={ord?.out_for_delivery ?? 0} />
              <Stage label="Delivered today" value={ord?.delivered_today ?? 0} accent />
            </div>
            <div className="mt-6 grid grid-cols-2 gap-6 text-sm text-text-secondary">
              <div>
                <p className="data-label mb-1">Reserved stock (units)</p>
                <p className="font-mono text-2xl text-text-primary">{inv?.total_reserved ?? "0"}</p>
              </div>
              <div>
                <p className="data-label mb-1">Total SKUs</p>
                <p className="font-mono text-2xl text-text-primary">{inv?.total_products ?? 0}</p>
              </div>
            </div>
          </div>

          {/* AI alerts */}
          <div className="pane p-6 relative overflow-hidden">
            <div
              className="absolute -top-8 -right-8 w-40 h-40 opacity-20 pointer-events-none"
              style={{ backgroundImage: `url(https://images.pexels.com/photos/10325707/pexels-photo-10325707.png?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940)`,
                backgroundSize: "cover", filter: "hue-rotate(60deg)" }}
            />
            <p className="data-label">AI Supervisor</p>
            <h3 className="font-display text-xl font-bold mt-1 mb-4">Active alerts</h3>
            <div className="space-y-3">
              {(alerts ?? []).slice(0, 5).map((a) => (
                <div key={a.id} className="border-l-2 pl-3 py-2 relative"
                  style={{ borderColor: severityColor(a.severity) }}
                  data-testid={`alert-${a.id}`}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`chip chip-${chipTone(a.severity)}`}>{a.severity}</span>
                    <span className="data-label">{a.category}</span>
                  </div>
                  <p className="text-sm font-medium">{a.title}</p>
                  <p className="text-xs text-text-secondary line-clamp-2">{a.message}</p>
                </div>
              ))}
              {!alerts?.length && (
                <p className="text-text-secondary text-sm">No active alerts. All systems calm.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function KpiCell({ label, value, sub, tone }: {
  label: string; value: string | number; sub: string; tone?: "alert" | "warning" | "success";
}) {
  return (
    <div className="p-6 border-r border-border last:border-r-0 relative">
      <p className="data-label">{label}</p>
      <p className={`font-display text-3xl font-black mt-2 tracking-tightest ${tone === "alert" ? "text-status-alert" : tone === "warning" ? "text-status-warning" : tone === "success" ? "text-status-success" : ""}`}>
        {value}
      </p>
      <p className="text-xs text-text-tertiary mt-1">{sub}</p>
    </div>
  );
}

function Stage({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="p-4 border-r border-border last:border-r-0">
      <p className="data-label truncate">{label}</p>
      <p className={`font-mono text-3xl mt-2 ${accent ? "text-volt" : ""}`}>{value}</p>
    </div>
  );
}

function severityColor(s: string) {
  switch (s) {
    case "critical": return "#FF3B30";
    case "warning": return "#FFD600";
    case "info": return "#007AFF";
    default: return "#4A4A4A";
  }
}

function chipTone(s: string) {
  return s === "critical" ? "alert" : s === "warning" ? "warning" : s === "info" ? "info" : "muted";
}
