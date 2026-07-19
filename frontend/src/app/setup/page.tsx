"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";

interface WarehouseInput {
  code: string; name: string; city?: string; state?: string; pincode?: string;
}

export default function SetupPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);

  const [company, setCompany] = useState({
    company_name: "", legal_name: "", gstin: "", phone: "", email: "",
    address: "", currency: "INR",
  });
  const [admin, setAdmin] = useState({
    admin_email: "", admin_password: "", admin_full_name: "",
  });
  const [warehouses, setWarehouses] = useState<WarehouseInput[]>([
    { code: "WH-1", name: "Main Warehouse", city: "", state: "", pincode: "" },
  ]);

  const canNext1 = company.company_name.trim().length >= 2;
  const canNext2 = admin.admin_email && admin.admin_password.length >= 8 && admin.admin_full_name.length >= 2;
  const canFinish = warehouses.every((w) => w.code.trim() && w.name.trim());

  async function submit() {
    setBusy(true);
    try {
      await api.post("/setup/initialize", {
        ...company,
        ...admin,
        warehouses,
      });
      toast.success("Setup complete. Please sign in.");
      router.replace("/login");
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen relative flex items-center justify-center p-6">
      <div
        className="absolute inset-0 -z-0 opacity-30"
        style={{
          backgroundImage: `url(https://images.unsplash.com/photo-1672552226669-f6c3041972ea?crop=entropy&cs=srgb&fm=jpg&ixid=M3w4NjAzMzN8MHwxfHNlYXJjaHw0fHxtb2Rlcm4lMjB3YXJlaG91c2UlMjBpbnRlcmlvcnxlbnwwfHx8fDE3ODQ0ODA2NzF8MA&ixlib=rb-4.1.0&q=85)`,
          backgroundSize: "cover", backgroundPosition: "center",
          filter: "grayscale(60%) blur(2px)",
        }}
      />
      <div className="absolute inset-0 bg-bg/85 -z-0" />

      <div className="relative z-10 w-full max-w-3xl pane p-8 md:p-12" data-testid="setup-wizard">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <p className="data-label">First-launch setup · Step {step} of 3</p>
            <h1 className="font-display text-3xl md:text-4xl font-black tracking-tightest mt-1">
              Configure your SupplyOS
            </h1>
          </div>
          <div className="hidden sm:flex gap-1">
            {[1, 2, 3].map((n) => (
              <span key={n}
                className={`w-8 h-1 ${n <= step ? "bg-volt" : "bg-border"}`}
              />
            ))}
          </div>
        </div>

        {step === 1 && (
          <div className="space-y-4">
            <div>
              <label className="data-label">Company / business name *</label>
              <input className="input mt-1" data-testid="setup-company-name"
                value={company.company_name}
                onChange={(e) => setCompany({ ...company, company_name: e.target.value })}
                placeholder="e.g. Acme Wholesale Pvt Ltd" />
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <div>
                <label className="data-label">Legal name</label>
                <input className="input mt-1" data-testid="setup-legal-name"
                  value={company.legal_name}
                  onChange={(e) => setCompany({ ...company, legal_name: e.target.value })} />
              </div>
              <div>
                <label className="data-label">GSTIN</label>
                <input className="input mt-1" data-testid="setup-gstin"
                  value={company.gstin}
                  onChange={(e) => setCompany({ ...company, gstin: e.target.value.toUpperCase() })}
                  placeholder="29ABCDE1234F1Z5" />
              </div>
              <div>
                <label className="data-label">Contact phone</label>
                <input className="input mt-1" data-testid="setup-phone"
                  value={company.phone}
                  onChange={(e) => setCompany({ ...company, phone: e.target.value })} />
              </div>
              <div>
                <label className="data-label">Contact email</label>
                <input className="input mt-1" data-testid="setup-email" type="email"
                  value={company.email}
                  onChange={(e) => setCompany({ ...company, email: e.target.value })} />
              </div>
              <div className="md:col-span-2">
                <label className="data-label">Address</label>
                <input className="input mt-1" data-testid="setup-address"
                  value={company.address}
                  onChange={(e) => setCompany({ ...company, address: e.target.value })} />
              </div>
            </div>
            <div className="flex justify-end pt-4">
              <button className="btn-volt" data-testid="setup-next-1"
                disabled={!canNext1} onClick={() => setStep(2)}>Next →</button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <p className="text-text-secondary text-sm">This account will have super-admin access to everything.</p>
            <div>
              <label className="data-label">Full name *</label>
              <input className="input mt-1" data-testid="setup-admin-name"
                value={admin.admin_full_name}
                onChange={(e) => setAdmin({ ...admin, admin_full_name: e.target.value })} />
            </div>
            <div>
              <label className="data-label">Email *</label>
              <input className="input mt-1" data-testid="setup-admin-email" type="email"
                value={admin.admin_email}
                onChange={(e) => setAdmin({ ...admin, admin_email: e.target.value })} />
            </div>
            <div>
              <label className="data-label">Password (min 8 chars) *</label>
              <input className="input mt-1" data-testid="setup-admin-password" type="password"
                value={admin.admin_password}
                onChange={(e) => setAdmin({ ...admin, admin_password: e.target.value })} />
            </div>
            <div className="flex justify-between pt-4">
              <button className="btn-ghost" data-testid="setup-back-2" onClick={() => setStep(1)}>← Back</button>
              <button className="btn-volt" data-testid="setup-next-2"
                disabled={!canNext2} onClick={() => setStep(3)}>Next →</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <p className="text-text-secondary text-sm">Add one or more warehouses. You can add racks/shelves later.</p>
            {warehouses.map((w, i) => (
              <div key={i} className="pane p-4 grid md:grid-cols-5 gap-3" data-testid={`setup-warehouse-${i}`}>
                <input className="input" placeholder="Code" value={w.code}
                  onChange={(e) => {
                    const c = [...warehouses]; c[i] = { ...c[i], code: e.target.value }; setWarehouses(c);
                  }} />
                <input className="input md:col-span-2" placeholder="Name" value={w.name}
                  onChange={(e) => {
                    const c = [...warehouses]; c[i] = { ...c[i], name: e.target.value }; setWarehouses(c);
                  }} />
                <input className="input" placeholder="City" value={w.city || ""}
                  onChange={(e) => {
                    const c = [...warehouses]; c[i] = { ...c[i], city: e.target.value }; setWarehouses(c);
                  }} />
                <div className="flex gap-2">
                  <input className="input" placeholder="Pin" value={w.pincode || ""}
                    onChange={(e) => {
                      const c = [...warehouses]; c[i] = { ...c[i], pincode: e.target.value }; setWarehouses(c);
                    }} />
                  {warehouses.length > 1 && (
                    <button className="btn-ghost text-status-alert" data-testid={`setup-warehouse-remove-${i}`}
                      onClick={() => setWarehouses(warehouses.filter((_, ix) => ix !== i))}>×</button>
                  )}
                </div>
              </div>
            ))}
            <button className="btn-ghost text-sm" data-testid="setup-warehouse-add"
              onClick={() => setWarehouses([...warehouses, { code: `WH-${warehouses.length + 1}`, name: "", city: "", state: "", pincode: "" }])}>
              + Add another warehouse
            </button>
            <div className="flex justify-between pt-4">
              <button className="btn-ghost" data-testid="setup-back-3" onClick={() => setStep(2)}>← Back</button>
              <button className="btn-volt" data-testid="setup-finish"
                disabled={!canFinish || busy} onClick={submit}>
                {busy ? "Setting up…" : "Finish setup →"}
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
