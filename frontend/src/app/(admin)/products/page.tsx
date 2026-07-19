"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Search } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { formatINR } from "@/lib/utils";

interface Product {
  id: string; sku: string; name: string; unit: string; base_price: string;
  gst_rate: string; low_stock_threshold: number; reorder_level: number; is_active: boolean;
}

export default function ProductsPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [show, setShow] = useState(false);

  const { data } = useQuery({
    queryKey: ["products", q],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page_size", "200");
      if (q) params.set("q", q);
      return (await api.get<{ items: Product[] }>(`/products?${params}`)).data;
    },
  });

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="data-label">Catalog</p>
          <h1 className="font-display text-3xl font-black tracking-tightest">Products</h1>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
            <input className="input pl-8 w-64" placeholder="Search…"
              value={q} onChange={(e) => setQ(e.target.value)} data-testid="prod-search" />
          </div>
          <button className="btn-volt inline-flex items-center gap-2" onClick={() => setShow(true)} data-testid="prod-new">
            <Plus size={14} /> Add product
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-8">
        <div className="pane overflow-x-auto">
          <table className="grid" data-testid="products-table">
            <thead>
              <tr>
                <th>SKU</th><th>Name</th><th>Unit</th>
                <th className="text-right">Base price</th>
                <th className="text-right">GST</th>
                <th className="text-right">Reorder @</th>
                <th className="text-right">Low @</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {!data?.items?.length && <tr><td colSpan={8} className="text-text-secondary">No products yet.</td></tr>}
              {data?.items?.map((p) => (
                <tr key={p.id} data-testid={`prod-row-${p.id}`}>
                  <td>{p.sku}</td>
                  <td>{p.name}</td>
                  <td>{p.unit}</td>
                  <td className="text-right">{formatINR(p.base_price)}</td>
                  <td className="text-right">{p.gst_rate}%</td>
                  <td className="text-right">{p.reorder_level}</td>
                  <td className="text-right">{p.low_stock_threshold}</td>
                  <td>{p.is_active ? <span className="chip chip-success">Active</span> : <span className="chip chip-muted">Inactive</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {show && <NewProductModal onClose={() => setShow(false)} onDone={() => qc.invalidateQueries({ queryKey: ["products"] })} />}
    </div>
  );
}

function NewProductModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({
    sku: "", name: "", unit: "pcs", base_price: "0", gst_rate: "5", low_stock_threshold: 10, reorder_level: 50,
  });
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      await api.post("/products", form);
      toast.success("Product created.");
      onDone(); onClose();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  }
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6" onClick={onClose} data-testid="prod-modal">
      <div className="pane w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <p className="data-label">Add product</p>
        <h3 className="font-display text-2xl font-bold mt-1 mb-4">New product</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="data-label">SKU *</label>
            <input className="input mt-1" value={form.sku} onChange={(e) => setForm({ ...form, sku: e.target.value })} data-testid="prod-sku" />
          </div>
          <div className="col-span-2">
            <label className="data-label">Name *</label>
            <input className="input mt-1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="prod-name" />
          </div>
          <div>
            <label className="data-label">Unit</label>
            <select className="input mt-1" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} data-testid="prod-unit">
              <option>pcs</option><option>kg</option><option>gm</option><option>ltr</option><option>box</option><option>bag</option>
            </select>
          </div>
          <div>
            <label className="data-label">Base price (₹)</label>
            <input className="input mt-1" value={form.base_price} onChange={(e) => setForm({ ...form, base_price: e.target.value })} data-testid="prod-price" />
          </div>
          <div>
            <label className="data-label">GST %</label>
            <input className="input mt-1" value={form.gst_rate} onChange={(e) => setForm({ ...form, gst_rate: e.target.value })} data-testid="prod-gst" />
          </div>
          <div>
            <label className="data-label">Reorder level</label>
            <input className="input mt-1" type="number" value={form.reorder_level}
              onChange={(e) => setForm({ ...form, reorder_level: Number(e.target.value) })} data-testid="prod-reorder" />
          </div>
          <div className="col-span-2">
            <label className="data-label">Low-stock threshold</label>
            <input className="input mt-1" type="number" value={form.low_stock_threshold}
              onChange={(e) => setForm({ ...form, low_stock_threshold: Number(e.target.value) })} data-testid="prod-lst" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-ghost" onClick={onClose} data-testid="prod-cancel">Cancel</button>
          <button className="btn-volt" onClick={submit} disabled={busy || !form.sku || !form.name} data-testid="prod-submit">
            {busy ? "Saving…" : "Create product"}
          </button>
        </div>
      </div>
    </div>
  );
}
