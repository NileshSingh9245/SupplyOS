"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { api, apiError } from "@/lib/api";

interface Warehouse {
  id: string; code: string; name: string; city: string | null; state: string | null;
  pincode: string | null; is_active: boolean;
}

export default function WarehousesPage() {
  const qc = useQueryClient();
  const [show, setShow] = useState(false);
  const { data } = useQuery({
    queryKey: ["warehouses"],
    queryFn: async () => (await api.get<Warehouse[]>("/warehouses")).data,
  });

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex items-center justify-between">
        <div>
          <p className="data-label">Locations</p>
          <h1 className="font-display text-3xl font-black tracking-tightest">Warehouses</h1>
        </div>
        <button className="btn-volt inline-flex items-center gap-2" onClick={() => setShow(true)} data-testid="wh-new">
          <Plus size={14} /> Add warehouse
        </button>
      </header>
      <div className="flex-1 overflow-auto p-8">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {data?.map((w) => (
            <div key={w.id} className="pane p-5" data-testid={`wh-card-${w.id}`}>
              <p className="data-label">{w.code}</p>
              <h3 className="font-display text-xl font-bold mt-1">{w.name}</h3>
              <p className="text-text-secondary text-sm mt-2">
                {[w.city, w.state, w.pincode].filter(Boolean).join(" · ") || "No address"}
              </p>
              <div className="mt-4">
                {w.is_active ? <span className="chip chip-success">Active</span> : <span className="chip chip-muted">Inactive</span>}
              </div>
            </div>
          ))}
          {!data?.length && <p className="text-text-secondary">No warehouses yet.</p>}
        </div>
      </div>
      {show && <NewWarehouse onClose={() => setShow(false)} onDone={() => qc.invalidateQueries({ queryKey: ["warehouses"] })} />}
    </div>
  );
}

function NewWarehouse({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [form, setForm] = useState({ code: "", name: "", city: "", state: "", pincode: "", address: "" });
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    try {
      await api.post("/warehouses", form);
      toast.success("Warehouse created.");
      onDone(); onClose();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  }
  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-6" onClick={onClose} data-testid="wh-modal">
      <div className="pane w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-display text-2xl font-bold mb-4">New warehouse</h3>
        <div className="grid grid-cols-2 gap-3">
          <div><label className="data-label">Code</label><input className="input mt-1" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} data-testid="wh-code" /></div>
          <div><label className="data-label">Name</label><input className="input mt-1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="wh-name" /></div>
          <div className="col-span-2"><label className="data-label">Address</label><input className="input mt-1" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} /></div>
          <div><label className="data-label">City</label><input className="input mt-1" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} /></div>
          <div><label className="data-label">State</label><input className="input mt-1" value={form.state} onChange={(e) => setForm({ ...form, state: e.target.value })} /></div>
          <div><label className="data-label">Pincode</label><input className="input mt-1" value={form.pincode} onChange={(e) => setForm({ ...form, pincode: e.target.value })} /></div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-volt" onClick={submit} disabled={busy || !form.code || !form.name} data-testid="wh-submit">
            {busy ? "Saving…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
