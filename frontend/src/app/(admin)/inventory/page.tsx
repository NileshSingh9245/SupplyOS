"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, RefreshCw, Search } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { formatINR, formatQty } from "@/lib/utils";

interface InvRow {
  id: string; product_id: string; product_sku: string; product_name: string;
  warehouse_id: string; warehouse_name: string; quantity: string;
  reserved_qty: string; available_qty: string; damaged_qty: string; low_stock: boolean;
}
interface Warehouse { id: string; name: string; code: string; }
interface Product { id: string; sku: string; name: string; unit: string; }

export default function InventoryPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const [showAdjust, setShowAdjust] = useState(false);

  const { data: rows, isLoading, refetch } = useQuery({
    queryKey: ["inventory", q, lowOnly],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (lowOnly) params.set("low_stock_only", "true");
      return (await api.get<InvRow[]>(`/inventory?${params}`)).data;
    },
  });

  const { data: warehouses } = useQuery({
    queryKey: ["warehouses"],
    queryFn: async () => (await api.get<Warehouse[]>("/warehouses")).data,
  });
  const { data: productsPaged } = useQuery({
    queryKey: ["products-min"],
    queryFn: async () => (await api.get<{ items: Product[] }>("/products?page_size=200")).data,
  });

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="data-label">Warehouse core</p>
          <h1 className="font-display text-3xl font-black tracking-tightest">Inventory</h1>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
            <input className="input pl-8 w-64" placeholder="Search SKU or name…"
              value={q} onChange={(e) => setQ(e.target.value)} data-testid="inv-search" />
          </div>
          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)}
              data-testid="inv-low-only" />
            Low stock only
          </label>
          <button className="btn-ghost inline-flex items-center gap-2" onClick={() => refetch()} data-testid="inv-refresh">
            <RefreshCw size={14} /> Refresh
          </button>
          <button className="btn-volt inline-flex items-center gap-2"
            data-testid="inv-adjust-open" onClick={() => setShowAdjust(true)}>
            <Plus size={14} /> Adjust stock
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-8">
        <div className="pane overflow-x-auto">
          <table className="grid" data-testid="inv-table">
            <thead>
              <tr>
                <th>SKU</th>
                <th>Product</th>
                <th>Warehouse</th>
                <th className="text-right">On-hand</th>
                <th className="text-right">Reserved</th>
                <th className="text-right">Available</th>
                <th className="text-right">Damaged</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && <tr><td colSpan={8} className="text-text-secondary">Loading…</td></tr>}
              {!isLoading && !rows?.length && <tr><td colSpan={8} className="text-text-secondary">No inventory yet. Add products &amp; adjust stock to begin.</td></tr>}
              {rows?.map((r) => (
                <tr key={r.id} data-testid={`inv-row-${r.id}`}>
                  <td>{r.product_sku}</td>
                  <td>{r.product_name}</td>
                  <td>{r.warehouse_name}</td>
                  <td className="text-right">{formatQty(r.quantity)}</td>
                  <td className="text-right">{formatQty(r.reserved_qty)}</td>
                  <td className="text-right font-bold">{formatQty(r.available_qty)}</td>
                  <td className="text-right">{formatQty(r.damaged_qty)}</td>
                  <td>
                    {parseFloat(r.available_qty) <= 0
                      ? <span className="chip chip-alert">Out</span>
                      : r.low_stock
                        ? <span className="chip chip-warning">Low</span>
                        : <span className="chip chip-success">OK</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {showAdjust && (
        <AdjustModal
          warehouses={warehouses ?? []}
          products={productsPaged?.items ?? []}
          onClose={() => setShowAdjust(false)}
          onDone={() => { qc.invalidateQueries({ queryKey: ["inventory"] }); qc.invalidateQueries({ queryKey: ["inv-stats"] }); }}
        />
      )}
    </div>
  );
}

function AdjustModal({ warehouses, products, onClose, onDone }: {
  warehouses: Warehouse[]; products: Product[]; onClose: () => void; onDone: () => void;
}) {
  const [productId, setProductId] = useState(products[0]?.id ?? "");
  const [warehouseId, setWarehouseId] = useState(warehouses[0]?.id ?? "");
  const [delta, setDelta] = useState("0");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      await api.post("/inventory/adjust", {
        product_id: productId, warehouse_id: warehouseId,
        delta_qty: delta, note: note || null,
      });
      toast.success("Stock adjusted.");
      onDone();
      onClose();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6" onClick={onClose} data-testid="adjust-modal">
      <div className="pane w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <p className="data-label">Adjust stock</p>
        <h3 className="font-display text-2xl font-bold mt-1 mb-6">Add or remove inventory</h3>

        <div className="space-y-3">
          <div>
            <label className="data-label">Product</label>
            <select className="input mt-1" value={productId} onChange={(e) => setProductId(e.target.value)} data-testid="adjust-product">
              {products.map((p) => <option key={p.id} value={p.id}>{p.sku} — {p.name}</option>)}
            </select>
          </div>
          <div>
            <label className="data-label">Warehouse</label>
            <select className="input mt-1" value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} data-testid="adjust-warehouse">
              {warehouses.map((w) => <option key={w.id} value={w.id}>{w.code} — {w.name}</option>)}
            </select>
          </div>
          <div>
            <label className="data-label">Delta quantity (use negative to remove)</label>
            <input className="input mt-1" type="text" inputMode="decimal"
              value={delta} onChange={(e) => setDelta(e.target.value)} data-testid="adjust-delta" />
          </div>
          <div>
            <label className="data-label">Note (optional)</label>
            <input className="input mt-1" value={note} onChange={(e) => setNote(e.target.value)} data-testid="adjust-note" />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <button className="btn-ghost" onClick={onClose} data-testid="adjust-cancel">Cancel</button>
          <button className="btn-volt" onClick={submit} disabled={busy || !productId || !warehouseId}
            data-testid="adjust-submit">
            {busy ? "Saving…" : "Save adjustment"}
          </button>
        </div>
      </div>
    </div>
  );
}
