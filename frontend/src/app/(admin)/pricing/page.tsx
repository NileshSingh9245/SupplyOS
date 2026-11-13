"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth";
import { canPrice, pricingKey, pricingScope, tiersQuery, type Tier } from "@/lib/pricing";
import { PricingPicker } from "@/features/pricing/picker";
import { TierEditor } from "@/features/pricing/tier-editor";
import { CustomerPricing } from "@/features/pricing/customer-pricing";

export default function PricingPage() {
  const user = useAuth((state) => state.user);
  const version = useAuth((state) => state.sessionVersion);
  const scope = pricingScope(user, version);
  const query = useQuery(tiersQuery(scope));
  const [editor, setEditor] = useState<Tier | "new" | null>(null);
  const [customerId, setCustomerId] = useState("");
  const scopeKey = pricingKey(scope).join(":");
  if (!scope) return <p role="alert" className="p-6">Pricing is unavailable for this session.</p>;
  const editable = canPrice(scope, "tiers");
  function closeEditor() { setEditor(null); void query.refetch(); }
  return <div className="page-shell" data-testid="pricing-page">
    <header className="page-header"><div><p className="data-label">Merchandising</p><h1 className="page-title">Pricing</h1></div>
      <div className="flex flex-wrap gap-2"><button className="btn-ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>Refresh tiers</button>
        {editable ? <button className="btn-volt" disabled={query.isFetching || query.isError || !query.data} onClick={() => setEditor("new")} data-testid="pricing-tier-new">New pricing tier</button> : null}</div>
    </header>
    <div className="page-body space-y-5">
      <p className="text-sm text-text-secondary">Explicit customer price takes priority over a tier discount, then the base price. The server quotes and snapshots prices and tax when an order is created. Existing orders never reprice.</p>
      {query.isFetching ? <p role="status">Loading pricing tiers...</p> : null}
      {query.isError ? <div className="pane p-4"><p role="alert">Pricing tiers could not be loaded. Refresh tiers before changing prices.</p></div> : query.data ? <>
        <div className="pane overflow-x-auto mobile-cards"><table className="grid" data-testid="pricing-tiers-table"><caption className="sr-only">Tenant pricing tiers and server discount percentages</caption>
          <thead><tr><th>Tier name</th><th>Discount percent</th>{editable ? <th>Manage</th> : null}</tr></thead>
          <tbody>{query.data.length ? query.data.map((tier) => <tr key={tier.id}><td data-label="Tier name"><span className="min-w-0 break-words">{tier.name}</span></td><td data-label="Discount percent">{tier.discount_pct}%</td>
            {editable ? <td data-label="Manage"><button className="btn-ghost" disabled={query.isFetching} onClick={() => setEditor(tier)} aria-label={`Edit discount for ${tier.name}`}>Edit discount</button></td> : null}</tr>) : <tr><td colSpan={editable ? 3 : 2}><p role="status">No pricing tiers yet.</p></td></tr>}</tbody>
        </table></div>
        {canPrice(scope, "customers") ? <fieldset className="space-y-4 min-w-0" disabled={query.isFetching} key={scopeKey} data-testid="pricing-customer-section"><legend className="text-lg font-semibold">Customer tiers and overrides</legend>
          <PricingPicker scope={scope} kind="customers" value={customerId} onChange={setCustomerId} />
          {customerId ? <CustomerPricing key={`${scopeKey}:${customerId}`} scope={scope} customerId={customerId} tiers={query.data} /> : <p className="text-sm text-text-secondary">Choose a customer to review their server-owned pricing.</p>}
        </fieldset> : <p className="text-sm text-text-secondary">Only the owner or an accountant may assign customer tiers or override prices.</p>}
      </> : null}
    </div>
    {editor && editable ? <TierEditor key={`${scopeKey}:${editor === "new" ? "new" : editor.id}`} scope={scope} tier={editor === "new" ? null : editor} onClose={closeEditor} /> : null}
  </div>;
}
