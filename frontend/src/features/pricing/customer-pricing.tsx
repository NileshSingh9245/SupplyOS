"use client";

import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { toast } from "sonner";
import { formatINR } from "@/lib/utils";
import { moneyInput } from "@/lib/finance";
import { assignCustomerTier, overridesQuery, pricingCustomerQuery, pricingIsCurrent, pricingKey, quoteQuery, removeOverride, saveOverride, type PricingScope, type Tier } from "@/lib/pricing";
import { PricingPicker } from "./picker";

const overrideForm = z.object({ price: z.string().refine((value) => moneyInput(value) !== null, "Enter an exact, non-negative price with at most two decimal places.") });
type Intent = { kind: "tier"; tier: Tier | null } | { kind: "save"; price: string } | { kind: "remove" };

export function CustomerPricing({ scope, customerId, tiers }: { scope: PricingScope; customerId: string; tiers: Tier[] }) {
  const client = useQueryClient();
  const customer = useQuery(pricingCustomerQuery(scope, customerId));
  const overrides = useQuery(overridesQuery(scope, customerId));
  const [productId, setProductId] = useState("");
  const quote = useQuery(quoteQuery(scope, customerId, productId));
  const [tierId, setTierId] = useState<string | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const controller = useRef(new AbortController());
  const pending = useRef(false);
  useEffect(() => { const active = new AbortController(); controller.current = active; return () => active.abort(); }, []);
  const form = useForm<z.infer<typeof overrideForm>>({ resolver: zodResolver(overrideForm), defaultValues: { price: "" } });
  const mutation = useMutation({ retry: false,
    mutationFn: async (intent: Intent): Promise<void> => {
      if (intent.kind === "tier") await assignCustomerTier(scope, customerId, intent.tier, controller.current.signal);
      else if (intent.kind === "save") await saveOverride(scope, customerId, productId, intent.price, controller.current.signal);
      else await removeOverride(scope, customerId, productId, controller.current.signal);
    },
    onSuccess: async () => {
      await Promise.all([client.invalidateQueries({ queryKey: pricingKey(scope) }), client.invalidateQueries({ queryKey: ["customers"] })]);
      if (!pricingIsCurrent(scope)) return;
      form.reset(); setReviewed(false); setTierId(null); toast.success("Customer pricing saved. Existing orders are unchanged.");
    },
  });
  const current = customer.data;
  const errorText = mutation.error?.message;
  const selectedTier = tierId ?? tiers.find((tier) => tier.name === current?.price_tier)?.id ?? "";
  const existing = overrides.data?.find((row) => row.product_id === productId);
  const blocked = mutation.isPending || mutation.isError || !reviewed || customer.isFetching || overrides.isFetching || !current || customer.isError || overrides.isError;
  async function write(intent: Intent) {
    if (blocked || pending.current) return;
    pending.current = true;
    try { await mutation.mutateAsync(intent); } catch { /* Only sanitized errors are rendered. */ }
    finally { pending.current = false; }
  }
  async function refresh() {
    setReviewed(false);
    const results = await Promise.all([customer.refetch(), overrides.refetch()]);
    if (pricingIsCurrent(scope) && results.every((result) => !result.isError && result.data !== undefined)) mutation.reset();
    if (productId) void quote.refetch();
  }
  return <div className="pane p-4 space-y-5" data-testid="pricing-customer-panel">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{current ? `${current.name} / ${current.code}` : "Customer pricing"}</h3>
      <button type="button" className="btn-ghost" disabled={mutation.isPending || customer.isFetching || overrides.isFetching} onClick={() => void refresh()}>Refresh pricing</button></div>
    {customer.isFetching || overrides.isFetching ? <p role="status">Loading customer pricing...</p> : null}
    {customer.isError || overrides.isError ? <p role="alert">Customer pricing could not be loaded. Refresh before making changes.</p> : current && overrides.data ? <>
      <p className="text-sm text-text-secondary">Current tier: {current.price_tier ?? "Base price"}. {overrides.data.length} product overrides configured. Only future orders use changes.</p>
      {!current.is_active ? <p role="status" className="text-sm">This customer is inactive. Pricing applies only after reactivation.</p> : null}
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={reviewed} disabled={mutation.isPending} onChange={(event) => setReviewed(event.target.checked)} />I reviewed this customer and the future-order price change.</label>
      <div className="space-y-2"><label className="data-label" htmlFor="pricing-customer-tier">Customer tier</label>
        <select id="pricing-customer-tier" className="input" value={selectedTier} disabled={mutation.isPending} onChange={(event) => setTierId(event.target.value)}>
          <option value="">Base price, no tier</option>{tiers.map((tier) => <option key={tier.id} value={tier.id} disabled={tier.name.length > 30}>{tier.name} / {tier.discount_pct}%{tier.name.length > 30 ? " / legacy name too long" : ""}</option>)}
        </select>
        {current.price_tier && !tiers.some((tier) => tier.name === current.price_tier) ? <p role="alert" className="text-sm">The legacy tier reference is unknown. Choose a valid tier or clear it explicitly.</p> : null}
        <button type="button" className="btn-ghost" disabled={blocked || tiers.some((tier) => tier.id === selectedTier && tier.name.length > 30)} onClick={() => void write({ kind: "tier", tier: tiers.find((tier) => tier.id === selectedTier) ?? null })} data-testid="pricing-tier-assign">Apply customer tier</button>
      </div>
      <PricingPicker scope={scope} kind="products" value={productId} disabled={mutation.isPending} onChange={(id) => { setProductId(id); setReviewed(false); form.reset(); }} />
      {productId ? <div className="space-y-3">
        {quote.isFetching ? <p role="status">Loading server price...</p> : quote.isError ? <p role="alert">The server price could not be quoted. No price is inferred.</p>
          : quote.data ? <p className="text-sm" data-testid="pricing-effective-price">Effective price before tax: {formatINR(quote.data.price)}</p> : null}
        <p className="text-xs">{existing ? `Current explicit override: ${formatINR(existing.price)}` : "No explicit override for this product."}</p>
        <form className="space-y-2" onSubmit={(event) => void form.handleSubmit((values) => write({ kind: "save", price: values.price }))(event)}>
          <label className="data-label" htmlFor="pricing-override-price">Customer price before tax</label><input id="pricing-override-price" className="input" {...form.register("price")} inputMode="decimal" maxLength={15} disabled={mutation.isPending} required />
          {form.formState.errors.price ? <p role="alert" className="text-sm text-red-400">{form.formState.errors.price.message}</p> : null}
          <div className="flex flex-wrap gap-2"><button className="btn-volt" disabled={blocked} data-testid="pricing-override-save">Save customer price</button>
            <button type="button" className="btn-ghost" disabled={blocked || !existing} onClick={() => void write({ kind: "remove" })} data-testid="pricing-override-remove">Remove override</button></div>
        </form>
      </div> : null}
    </> : null}
    {mutation.isError && !axios.isCancel(mutation.error) ? <p role="alert" className="text-sm text-red-400">{errorText} Refresh pricing and review it before submitting again.</p> : null}
  </div>;
}
