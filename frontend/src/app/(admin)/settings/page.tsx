"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { useSettings } from "@/lib/settings";

type SettingsMap = Record<string, unknown>;

const FIELD_GROUPS: {
  title: string;
  desc: string;
  fields: { key: string; label: string; type?: "text" | "number" | "boolean" | "select"; options?: string[]; help?: string; }[];
}[] = [
  {
    title: "Currency & rounding",
    desc: "Applied everywhere prices and totals are displayed. Indian defaults preloaded.",
    fields: [
      { key: "currency_code", label: "Currency code", help: "e.g. INR" },
      { key: "currency_symbol", label: "Currency symbol", help: "e.g. ₹" },
      { key: "locale", label: "Locale", help: "en-IN, hi-IN, ta-IN, etc." },
      { key: "money_rounding", label: "Rounding rule", type: "select",
        options: ["round_half_up", "bankers", "floor", "ceil"] },
      { key: "money_decimals", label: "Decimals", type: "number" },
    ],
  },
  {
    title: "GST / tax rules",
    desc: "Default tax rules for new products and invoices.",
    fields: [
      { key: "default_gst_rate", label: "Default GST rate (%)" },
      { key: "gst_type", label: "GST type", type: "select", options: ["cgst_sgst", "igst"],
        help: "cgst_sgst for intra-state, igst for inter-state" },
      { key: "gstin_required_for_credit", label: "Require GSTIN for credit customers", type: "boolean" },
      { key: "hsn_required", label: "Require HSN code on products", type: "boolean" },
    ],
  },
  {
    title: "Pricing engine",
    desc: "Controls how the system resolves a product price for a given customer.",
    fields: [
      { key: "allow_below_base_price", label: "Allow overrides below base price", type: "boolean" },
      { key: "min_margin_pct", label: "Minimum margin (%)" },
    ],
  },
  {
    title: "Credit / receivables",
    desc: "How the system enforces credit limits and warns about overdue receivables.",
    fields: [
      { key: "default_credit_limit", label: "Default credit limit for new credit customers (₹)" },
      { key: "credit_warning_threshold_pct", label: "Warning threshold (% of limit)" },
      { key: "block_orders_over_credit", label: "Block orders that exceed credit limit", type: "boolean" },
      { key: "auto_send_payment_reminder_days", label: "Reminder cadence (days)", type: "number" },
    ],
  },
  {
    title: "Order rules",
    desc: "State-machine defaults and reservation timeout.",
    fields: [
      { key: "auto_confirm_orders", label: "Auto-confirm new orders", type: "boolean" },
      { key: "auto_reserve_on_confirm", label: "Auto-reserve stock on confirm", type: "boolean" },
      { key: "reservation_ttl_hours", label: "Reservation TTL (hours)", type: "number" },
      { key: "allow_partial_fulfillment", label: "Allow partial fulfillment / backorders", type: "boolean" },
      { key: "cancellation_window_minutes", label: "Cancellation grace window (minutes)", type: "number" },
    ],
  },
  {
    title: "Delivery",
    desc: "Rules applied to every delivery in the field.",
    fields: [
      { key: "otp_length", label: "OTP length", type: "number" },
      { key: "require_photo_proof", label: "Require photo proof on completion", type: "boolean" },
      { key: "require_signature", label: "Require signature on completion", type: "boolean" },
      { key: "delivery_priority_default", label: "Default priority (1 = highest)", type: "number" },
    ],
  },
  {
    title: "Inventory defaults",
    desc: "Applied to new products and warehouse selection.",
    fields: [
      { key: "low_stock_threshold_default", label: "Default low-stock threshold", type: "number" },
      { key: "reorder_level_default", label: "Default reorder level", type: "number" },
      { key: "dead_stock_days", label: "Dead-stock cutoff (days without outbound)", type: "number" },
      { key: "warehouse_selection", label: "Warehouse selection strategy", type: "select",
        options: ["nearest_first", "most_stock_first"] },
    ],
  },
  {
    title: "AI Supervisor",
    desc: "Cadence of automatic checks. Set 0 to disable.",
    fields: [
      { key: "ai_enabled", label: "Enable AI Supervisor", type: "boolean" },
      { key: "ai_analyze_interval_minutes", label: "Rule-check cadence (minutes)", type: "number" },
      { key: "ai_summary_interval_minutes", label: "Claude summary cadence (minutes)", type: "number" },
    ],
  },
];

export default function SettingsPage() {
  const settings = useSettings((s) => s.data);
  const update = useSettings((s) => s.update);
  const load = useSettings((s) => s.load);
  const [values, setValues] = useState<SettingsMap>({});
  const [companyName, setCompanyName] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (settings) {
      setValues({ ...settings.values });
      setCompanyName(settings.company_name);
    }
  }, [settings]);

  function set(k: string, v: unknown) { setValues((prev) => ({ ...prev, [k]: v })); setDirty(true); }

  async function save() {
    setBusy(true);
    try {
      const patch: SettingsMap = { ...values };
      if (companyName !== settings?.company_name) patch.company_name = companyName;
      await update(patch);
      toast.success("Settings saved.");
      setDirty(false);
      await load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  }

  if (!settings) return <div className="p-8 text-text-secondary">Loading settings…</div>;

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5 flex items-center justify-between flex-wrap gap-3">
        <div>
          <p className="data-label">Business rules</p>
          <h1 className="font-display text-3xl font-black tracking-tightest">Rules &amp; Settings</h1>
          <p className="text-text-secondary text-sm mt-1">
            Every pricing, tax, credit, delivery, and AI rule the system enforces — editable here.
          </p>
        </div>
        <button className="btn-volt" onClick={save} disabled={busy || !dirty} data-testid="settings-save">
          {busy ? "Saving…" : dirty ? "Save changes" : "All saved"}
        </button>
      </header>

      <div className="flex-1 overflow-auto p-8 space-y-8 max-w-4xl">
        <div className="pane p-6">
          <p className="data-label">Company</p>
          <div className="mt-3 max-w-lg">
            <label className="data-label">Company / business name</label>
            <input className="input mt-1" value={companyName}
              onChange={(e) => { setCompanyName(e.target.value); setDirty(true); }}
              data-testid="settings-company-name" />
          </div>
        </div>

        {FIELD_GROUPS.map((g) => (
          <div key={g.title} className="pane p-6" data-testid={`settings-group-${g.title.toLowerCase().replace(/\W+/g,"-")}`}>
            <p className="data-label">{g.title}</p>
            <p className="text-text-secondary text-sm mt-1 mb-5">{g.desc}</p>
            <div className="grid md:grid-cols-2 gap-4">
              {g.fields.map((f) => {
                const v = values[f.key];
                if (f.type === "boolean") {
                  return (
                    <label key={f.key} className="flex items-center gap-3 text-sm">
                      <input type="checkbox" checked={Boolean(v)}
                        onChange={(e) => set(f.key, e.target.checked)}
                        data-testid={`settings-${f.key}`} />
                      <span>
                        <span className="block">{f.label}</span>
                        {f.help && <span className="data-label mt-0.5">{f.help}</span>}
                      </span>
                    </label>
                  );
                }
                if (f.type === "select") {
                  return (
                    <div key={f.key}>
                      <label className="data-label">{f.label}</label>
                      <select className="input mt-1" value={String(v ?? "")}
                        onChange={(e) => set(f.key, e.target.value)}
                        data-testid={`settings-${f.key}`}>
                        {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                      {f.help && <p className="data-label mt-1">{f.help}</p>}
                    </div>
                  );
                }
                return (
                  <div key={f.key}>
                    <label className="data-label">{f.label}</label>
                    <input className="input mt-1"
                      type={f.type === "number" ? "number" : "text"}
                      value={String(v ?? "")}
                      onChange={(e) => set(f.key, f.type === "number" ? Number(e.target.value) : e.target.value)}
                      data-testid={`settings-${f.key}`} />
                    {f.help && <p className="data-label mt-1">{f.help}</p>}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
