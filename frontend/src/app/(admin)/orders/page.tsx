"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Search } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { formatDateTime, formatINR, formatQty } from "@/lib/utils";

interface OrderItem {
  id: string; product_id: string; product_sku: string; product_name: string;
  quantity: string; unit_price: string; line_subtotal: string; line_tax: string; line_total: string;
}
interface Order {
  id: string; order_number: string; customer_id: string; warehouse_id: string;
  status: string; channel: string; grand_total: string; subtotal: string; tax_total: string;
  created_at: string; delivered_at: string | null; items: OrderItem[];
  amount_paid: string;
}
interface Customer { id: string; name: string; code: string; customer_type: string; }
interface Warehouse { id: string; name: string; code: string; }
interface Product { id: string; sku: string; name: string; base_price: string; }

const STATUS_COLORS: Record<string, string> = {
  pending: "chip-muted", confirmed: "chip-info", reserved: "chip-volt",
  picked: "chip-info", packed: "chip-info", out_for_delivery: "chip-warning",
  delivered: "chip-success", paid: "chip-success", completed: "chip-success",
  cancelled: "chip-alert",
};

export default function OrdersPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [show, setShow] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: ["orders", q, statusFilter],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page_size", "100");
      if (q) params.set("q", q);
      if (statusFilter) params.set("status", statusFilter);
      return (await api.get<{ items: Order[] }>(`/orders?${params}`)).data;
    },
  });

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="data-label">Fulfilment</p>
          <h1 className="font-display text-3xl font-black tracking-tightest">Orders</h1>
        </div>
        <div className="flex gap-2 items-center">
          <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} data-testid="orders-status-filter">
            <option value="">All statuses</option>
            {Object.keys(STATUS_COLORS).map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </select>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
            <input className="input pl-8 w-64" placeholder="Order # search…"
              value={q} onChange={(e) => setQ(e.target.value)} data-testid="orders-search" />
          </div>
          <button className="btn-volt inline-flex items-center gap-2" onClick={() => setShow(true)} data-testid="orders-new">
            <Plus size={14} /> New order
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-8">
        <div className="pane overflow-x-auto">
          <table className="grid" data-testid="orders-table">
            <thead>
              <tr>
                <th>Order #</th><th>Status</th><th>Channel</th><th>Placed</th>
                <th className="text-right">Subtotal</th>
                <th className="text-right">GST</th>
                <th className="text-right">Total</th>
                <th className="text-right">Paid</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {!data?.items?.length && <tr><td colSpan={9} className="text-text-secondary">No orders yet.</td></tr>}
              {data?.items?.map((o) => (
                <tr key={o.id} data-testid={`order-row-${o.id}`} className="cursor-pointer" onClick={() => setOpenId(o.id)}>
                  <td>{o.order_number}</td>
                  <td><span className={`chip ${STATUS_COLORS[o.status] || "chip-muted"}`}>{o.status.replace("_", " ")}</span></td>
                  <td>{o.channel}</td>
                  <td>{formatDateTime(o.created_at)}</td>
                  <td className="text-right">{formatINR(o.subtotal)}</td>
                  <td className="text-right">{formatINR(o.tax_total)}</td>
                  <td className="text-right font-bold">{formatINR(o.grand_total)}</td>
                  <td className="text-right">{formatINR(o.amount_paid)}</td>
                  <td><span className="text-volt text-xs">Open →</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {show && <NewOrderModal onClose={() => setShow(false)}
        onDone={() => qc.invalidateQueries({ queryKey: ["orders"] })} />}
      {openId && <OrderDetail id={openId} onClose={() => setOpenId(null)}
        onChanged={() => qc.invalidateQueries({ queryKey: ["orders"] })} />}
    </div>
  );
}

function NewOrderModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { data: customers } = useQuery({
    queryKey: ["customers-min"],
    queryFn: async () => (await api.get<{ items: Customer[] }>("/customers?page_size=200")).data.items,
  });
  const { data: warehouses } = useQuery({
    queryKey: ["warehouses"],
    queryFn: async () => (await api.get<Warehouse[]>("/warehouses")).data,
  });
  const { data: products } = useQuery({
    queryKey: ["products-min"],
    queryFn: async () => (await api.get<{ items: Product[] }>("/products?page_size=200")).data.items,
  });

  const [customerId, setCustomerId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [isCredit, setIsCredit] = useState(false);
  const [items, setItems] = useState<{ product_id: string; quantity: string }[]>([{ product_id: "", quantity: "1" }]);
  const [busy, setBusy] = useState(false);

  const canSubmit = customerId && warehouseId && items.every((i) => i.product_id && parseFloat(i.quantity) > 0);

  async function submit() {
    setBusy(true);
    try {
      await api.post("/orders", {
        customer_id: customerId, warehouse_id: warehouseId, is_credit: isCredit,
        items: items.map((i) => ({ product_id: i.product_id, quantity: i.quantity })),
      });
      toast.success("Order created (status: pending).");
      onDone(); onClose();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6" onClick={onClose} data-testid="order-modal">
      <div className="pane w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <p className="data-label">Create order</p>
        <h3 className="font-display text-2xl font-bold mt-1 mb-4">New order</h3>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="data-label">Customer *</label>
            <select className="input mt-1" value={customerId} onChange={(e) => setCustomerId(e.target.value)} data-testid="order-customer">
              <option value="">Select…</option>
              {customers?.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name}</option>)}
            </select></div>
          <div><label className="data-label">Warehouse *</label>
            <select className="input mt-1" value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} data-testid="order-warehouse">
              <option value="">Select…</option>
              {warehouses?.map((w) => <option key={w.id} value={w.id}>{w.code} — {w.name}</option>)}
            </select></div>
        </div>
        <label className="flex items-center gap-2 mt-3 text-sm">
          <input type="checkbox" checked={isCredit} onChange={(e) => setIsCredit(e.target.checked)} data-testid="order-credit" />
          Credit sale (check customer credit limit)
        </label>

        <p className="data-label mt-4 mb-2">Line items</p>
        {items.map((it, i) => (
          <div key={i} className="grid grid-cols-6 gap-2 mb-2" data-testid={`order-line-${i}`}>
            <select className="input col-span-4" value={it.product_id}
              onChange={(e) => {
                const c = [...items]; c[i].product_id = e.target.value; setItems(c);
              }}>
              <option value="">Select product…</option>
              {products?.map((p) => <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>)}
            </select>
            <input className="input" value={it.quantity} inputMode="decimal"
              onChange={(e) => { const c = [...items]; c[i].quantity = e.target.value; setItems(c); }} />
            <button className="btn-ghost" onClick={() => setItems(items.filter((_, ix) => ix !== i))}>×</button>
          </div>
        ))}
        <button className="btn-ghost text-xs" data-testid="order-add-line"
          onClick={() => setItems([...items, { product_id: "", quantity: "1" }])}>+ Add line</button>

        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-ghost" onClick={onClose} data-testid="order-cancel">Cancel</button>
          <button className="btn-volt" onClick={submit} disabled={busy || !canSubmit} data-testid="order-submit">
            {busy ? "Saving…" : "Create order"}
          </button>
        </div>
      </div>
    </div>
  );
}

function OrderDetail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const { data: order, refetch } = useQuery({
    queryKey: ["order", id],
    queryFn: async () => (await api.get<Order>(`/orders/${id}`)).data,
  });

  async function action(path: string, body?: unknown) {
    try {
      await api.post(`/orders/${id}/${path}`, body ?? {});
      toast.success(`Order → ${path}`);
      await refetch();
      onChanged();
    } catch (e) { toast.error(apiError(e)); }
  }

  const status = order?.status;
  const nextActions: { key: string; label: string; body?: unknown }[] = [];
  if (status === "pending") nextActions.push({ key: "confirm", label: "Confirm →" });
  if (status === "confirmed") nextActions.push({ key: "reserve", label: "Reserve stock →" });
  if (status === "reserved") nextActions.push({ key: "pick", label: "Pick →" });
  if (status === "picked") nextActions.push({ key: "pack", label: "Pack →" });
  if (status === "packed") nextActions.push({ key: "dispatch", label: "Dispatch →" });
  if (status === "out_for_delivery") nextActions.push({ key: "deliver", label: "Mark delivered ✓" });
  if (status && !["completed", "cancelled", "paid"].includes(status)) {
    nextActions.push({ key: "cancel", label: "Cancel order", body: { note: "cancelled from admin" } });
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6" onClick={onClose} data-testid="order-detail">
      <div className="pane w-full max-w-3xl p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <p className="data-label">Order</p>
            <h3 className="font-display text-3xl font-black tracking-tightest">{order?.order_number || "…"}</h3>
            <p className="text-text-secondary text-sm mt-1">{order && formatDateTime(order.created_at)} · via {order?.channel}</p>
          </div>
          <span className={`chip ${order ? (STATUS_COLORS[order.status] || "chip-muted") : ""}`}>{order?.status?.replace("_", " ")}</span>
        </div>

        {order && (
          <>
            <table className="grid w-full mb-4">
              <thead><tr><th>SKU</th><th>Product</th><th className="text-right">Qty</th><th className="text-right">Unit ₹</th><th className="text-right">Line ₹</th></tr></thead>
              <tbody>
                {order.items.map((it) => (
                  <tr key={it.id}>
                    <td>{it.product_sku}</td>
                    <td>{it.product_name}</td>
                    <td className="text-right">{formatQty(it.quantity)}</td>
                    <td className="text-right">{formatINR(it.unit_price)}</td>
                    <td className="text-right">{formatINR(it.line_total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pane p-4 flex justify-end gap-8 font-mono text-sm">
              <div><span className="data-label mr-2">Sub</span>{formatINR(order.subtotal)}</div>
              <div><span className="data-label mr-2">GST</span>{formatINR(order.tax_total)}</div>
              <div><span className="data-label mr-2">Total</span><span className="text-volt text-lg font-bold">{formatINR(order.grand_total)}</span></div>
            </div>
          </>
        )}

        <div className="flex flex-wrap gap-2 mt-6">
          {nextActions.map((a) => (
            <button key={a.key} className={a.key === "cancel" ? "btn-ghost text-status-alert" : "btn-volt"}
              data-testid={`order-action-${a.key}`}
              onClick={() => action(a.key, a.body)}>
              {a.label}
            </button>
          ))}
          <button className="btn-ghost ml-auto" onClick={onClose} data-testid="order-close">Close</button>
        </div>
      </div>
    </div>
  );
}
