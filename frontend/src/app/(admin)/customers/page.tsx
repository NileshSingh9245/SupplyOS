"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus, Search } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { formatINR } from "@/lib/utils";

interface Customer {
  id: string; code: string; name: string; business_name: string | null;
  phone: string | null; gstin: string | null; customer_type: string;
  credit_limit: string; outstanding: string; price_tier: string | null;
  is_active: boolean;
}

export default function CustomersPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [show, setShow] = useState(false);

  const { data } = useQuery({
    queryKey: ["customers", q],
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("page_size", "200");
      if (q) params.set("q", q);
      return (await api.get<{ items: Customer[] }>(`/customers?${params}`)).data;
    },
  });

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="data-label">Directory</p>
          <h1 className="font-display text-3xl font-black tracking-tightest">Customers</h1>
        </div>
        <div className="flex gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary" />
            <input className="input pl-8 w-64" placeholder="Name, code, phone…"
              value={q} onChange={(e) => setQ(e.target.value)} data-testid="cust-search" />
          </div>
          <button className="btn-volt inline-flex items-center gap-2" onClick={() => setShow(true)} data-testid="cust-new">
            <Plus size={14} /> Add customer
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-auto p-8">
        <div className="pane overflow-x-auto">
          <table className="grid" data-testid="cust-table">
            <thead>
              <tr>
                <th>Code</th><th>Name</th><th>Business</th><th>Phone</th><th>Type</th>
                <th className="text-right">Credit limit</th>
                <th className="text-right">Outstanding</th>
                <th>Utilization</th>
              </tr>
            </thead>
            <tbody>
              {!data?.items?.length && <tr><td colSpan={8} className="text-text-secondary">No customers yet.</td></tr>}
              {data?.items?.map((c) => {
                const limit = parseFloat(c.credit_limit);
                const out = parseFloat(c.outstanding);
                const util = limit > 0 ? out / limit : 0;
                return (
                  <tr key={c.id} data-testid={`cust-row-${c.id}`}>
                    <td>{c.code}</td>
                    <td>{c.name}</td>
                    <td>{c.business_name || "—"}</td>
                    <td>{c.phone || "—"}</td>
                    <td>
                      {c.customer_type === "credit"
                        ? <span className="chip chip-warning">Credit</span>
                        : <span className="chip chip-info">Cash</span>}
                    </td>
                    <td className="text-right">{formatINR(c.credit_limit)}</td>
                    <td className="text-right">{formatINR(c.outstanding)}</td>
                    <td>
                      {limit === 0
                        ? <span className="chip chip-muted">n/a</span>
                        : util > 1
                          ? <span className="chip chip-alert">{Math.round(util*100)}%</span>
                          : util > 0.8
                            ? <span className="chip chip-warning">{Math.round(util*100)}%</span>
                            : <span className="chip chip-success">{Math.round(util*100)}%</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {show && <NewCustomerModal onClose={() => setShow(false)} onDone={() => qc.invalidateQueries({ queryKey: ["customers"] })} />}
    </div>
  );
}

function NewCustomerModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({
    name: "", business_name: "", phone: "", email: "", gstin: "",
    address: "", city: "", state: "", pincode: "",
    customer_type: "cash", credit_limit: "0", price_tier: "",
  });
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      const payload = { ...form, price_tier: form.price_tier || null };
      await api.post("/customers", payload);
      toast.success("Customer created.");
      onDone(); onClose();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  }
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6" onClick={onClose} data-testid="cust-modal">
      <div className="pane w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <p className="data-label">Add customer</p>
        <h3 className="font-display text-2xl font-bold mt-1 mb-4">New customer</h3>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="data-label">Name *</label>
            <input className="input mt-1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="cust-name" /></div>
          <div><label className="data-label">Business name</label>
            <input className="input mt-1" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} data-testid="cust-business" /></div>
          <div><label className="data-label">Phone</label>
            <input className="input mt-1" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} data-testid="cust-phone" /></div>
          <div><label className="data-label">Email</label>
            <input className="input mt-1" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="cust-email" /></div>
          <div><label className="data-label">GSTIN</label>
            <input className="input mt-1" value={form.gstin} onChange={(e) => setForm({ ...form, gstin: e.target.value.toUpperCase() })} data-testid="cust-gstin" /></div>
          <div><label className="data-label">Type</label>
            <select className="input mt-1" value={form.customer_type} onChange={(e) => setForm({ ...form, customer_type: e.target.value })} data-testid="cust-type">
              <option value="cash">Cash</option><option value="credit">Credit</option>
            </select></div>
          <div><label className="data-label">Credit limit (₹)</label>
            <input className="input mt-1" value={form.credit_limit} onChange={(e) => setForm({ ...form, credit_limit: e.target.value })} data-testid="cust-limit" /></div>
          <div><label className="data-label">Price tier</label>
            <input className="input mt-1" placeholder="e.g. wholesale-a" value={form.price_tier}
              onChange={(e) => setForm({ ...form, price_tier: e.target.value })} data-testid="cust-tier" /></div>
          <div className="col-span-2"><label className="data-label">Address</label>
            <input className="input mt-1" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} data-testid="cust-address" /></div>
          <div><label className="data-label">City</label>
            <input className="input mt-1" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} /></div>
          <div><label className="data-label">Pincode</label>
            <input className="input mt-1" value={form.pincode} onChange={(e) => setForm({ ...form, pincode: e.target.value })} /></div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-ghost" onClick={onClose} data-testid="cust-cancel">Cancel</button>
          <button className="btn-volt" onClick={submit} disabled={busy || !form.name} data-testid="cust-submit">
            {busy ? "Saving…" : "Create customer"}
          </button>
        </div>
      </div>
    </div>
  );
}
