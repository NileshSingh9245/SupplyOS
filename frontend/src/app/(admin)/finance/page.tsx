"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { formatDateTime, formatINR } from "@/lib/utils";

interface Payment {
  id: string; customer_id: string; order_id: string | null;
  amount: string; mode: string; reference: string | null; note: string | null;
  created_at: string;
}
interface Customer { id: string; code: string; name: string; outstanding: string; }

export default function FinancePage() {
  const qc = useQueryClient();
  const [show, setShow] = useState(false);

  const { data: payments } = useQuery({
    queryKey: ["payments"],
    queryFn: async () => (await api.get<Payment[]>("/payments")).data,
  });
  const { data: customers } = useQuery({
    queryKey: ["customers-min"],
    queryFn: async () => (await api.get<{ items: Customer[] }>("/customers?page_size=200")).data.items,
  });

  const totalOutstanding = customers?.reduce((sum, c) => sum + parseFloat(c.outstanding || "0"), 0) ?? 0;
  const totalCollected = payments?.reduce((sum, p) => sum + parseFloat(p.amount || "0"), 0) ?? 0;

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex items-center justify-between">
        <div>
          <p className="data-label">Money in / out</p>
          <h1 className="font-display text-3xl font-black tracking-tightest">Finance</h1>
        </div>
        <button className="btn-volt inline-flex items-center gap-2" onClick={() => setShow(true)} data-testid="pay-new">
          <Plus size={14} /> Record payment
        </button>
      </header>
      <div className="flex-1 overflow-auto p-8 space-y-6">
        <div className="grid grid-cols-2 gap-0 border border-border">
          <div className="p-6 border-r border-border">
            <p className="data-label">Total collected</p>
            <p className="font-display text-4xl font-black tracking-tightest text-volt mt-2">{formatINR(totalCollected)}</p>
          </div>
          <div className="p-6">
            <p className="data-label">Outstanding across credit customers</p>
            <p className="font-display text-4xl font-black tracking-tightest text-status-warning mt-2">{formatINR(totalOutstanding)}</p>
          </div>
        </div>

        <div className="pane overflow-x-auto">
          <h3 className="font-display text-xl font-bold p-4 border-b border-border">Recent payments</h3>
          <table className="grid" data-testid="pay-table">
            <thead>
              <tr><th>Date</th><th>Customer</th><th>Mode</th><th className="text-right">Amount</th><th>Reference</th><th>Note</th></tr>
            </thead>
            <tbody>
              {!payments?.length && <tr><td colSpan={6} className="text-text-secondary">No payments yet.</td></tr>}
              {payments?.map((p) => {
                const cust = customers?.find((c) => c.id === p.customer_id);
                return (
                  <tr key={p.id} data-testid={`pay-row-${p.id}`}>
                    <td>{formatDateTime(p.created_at)}</td>
                    <td>{cust?.name || p.customer_id.slice(0, 8)}</td>
                    <td><span className="chip chip-info">{p.mode}</span></td>
                    <td className="text-right font-bold">{formatINR(p.amount)}</td>
                    <td>{p.reference || "—"}</td>
                    <td>{p.note || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      {show && customers && <NewPayment customers={customers} onClose={() => setShow(false)}
        onDone={() => { qc.invalidateQueries({ queryKey: ["payments"] }); qc.invalidateQueries({ queryKey: ["customers-min"] }); }} />}
    </div>
  );
}

function NewPayment({ customers, onClose, onDone }: { customers: Customer[]; onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ customer_id: "", amount: "0", mode: "cash", reference: "", note: "" });
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      await api.post("/payments", { ...form, reference: form.reference || null, note: form.note || null });
      toast.success("Payment recorded.");
      onDone(); onClose();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  }
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6" onClick={onClose} data-testid="pay-modal">
      <div className="pane w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-display text-2xl font-bold mb-4">Record payment</h3>
        <div className="space-y-3">
          <div><label className="data-label">Customer</label>
            <select className="input mt-1" value={form.customer_id} onChange={(e) => setForm({ ...form, customer_id: e.target.value })} data-testid="pay-customer">
              <option value="">Select…</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.code} — {c.name} ({formatINR(c.outstanding)} due)</option>)}
            </select></div>
          <div><label className="data-label">Amount (₹)</label>
            <input className="input mt-1" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="pay-amount" /></div>
          <div><label className="data-label">Mode</label>
            <select className="input mt-1" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })} data-testid="pay-mode">
              <option value="cash">Cash</option><option value="upi">UPI</option>
              <option value="bank_transfer">Bank transfer</option><option value="credit">Credit note</option>
            </select></div>
          <div><label className="data-label">Reference (UPI txn / cheque #)</label>
            <input className="input mt-1" value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} data-testid="pay-ref" /></div>
          <div><label className="data-label">Note</label>
            <input className="input mt-1" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} data-testid="pay-note" /></div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-volt" onClick={submit} disabled={busy || !form.customer_id || parseFloat(form.amount) <= 0} data-testid="pay-submit">
            {busy ? "Saving…" : "Record payment"}
          </button>
        </div>
      </div>
    </div>
  );
}
