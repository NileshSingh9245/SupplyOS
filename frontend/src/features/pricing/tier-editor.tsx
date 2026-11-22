"use client";

import { useEffect, useRef } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { toast } from "sonner";
import { Modal } from "@/components/modal";
import { pricingIsCurrent, pricingKey, saveTier, tierFormSchema, type PricingScope, type Tier } from "@/lib/pricing";

type Fields = z.infer<typeof tierFormSchema>;
export function TierEditor({ scope, tier, onClose }: { scope: PricingScope; tier: Tier | null; onClose: () => void }) {
  const client = useQueryClient();
  const controller = useRef(new AbortController());
  const pending = useRef(false);
  useEffect(() => { const active = new AbortController(); controller.current = active; return () => active.abort(); }, []);
  const form = useForm<Fields>({ resolver: zodResolver(tierFormSchema),
    defaultValues: { name: tier?.name ?? "", discount_pct: tier?.discount_pct ?? "0.00", reviewed: false } });
  const mutation = useMutation({ retry: false,
    mutationFn: (values: Fields) => saveTier(scope, tier, values.name, values.discount_pct, controller.current.signal),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: pricingKey(scope) });
      if (pricingIsCurrent(scope)) { toast.success("Tier saved. Existing orders are unchanged."); onClose(); } },
  });
  async function submit(values: Fields) {
    if (pending.current || mutation.isError) return;
    pending.current = true;
    try { await mutation.mutateAsync(values); } catch { /* The private mutation message is rendered below. */ }
    finally { pending.current = false; }
  }
  const errorText = mutation.error?.message;
  return <Modal open busy={mutation.isPending} onClose={onClose} labelledBy="pricing-tier-heading" testId="pricing-tier-dialog">
    <div className="space-y-4">
      <h2 id="pricing-tier-heading" className="text-lg font-semibold">{tier ? "Edit tier discount" : "Create pricing tier"}</h2>
      <p className="text-sm text-text-secondary">Tier names stay fixed. Discounts affect future orders; existing price and tax snapshots do not change.</p>
      <form className="space-y-4" onSubmit={(event) => void form.handleSubmit(submit)(event)}>
        <label className="data-label" htmlFor="pricing-tier-name">Tier name</label>
        <input id="pricing-tier-name" className="input" {...form.register("name")} maxLength={tier ? 60 : 30} readOnly={!!tier} disabled={mutation.isPending} required />
        <label className="data-label" htmlFor="pricing-tier-discount">Discount percent</label>
        <input id="pricing-tier-discount" className="input" {...form.register("discount_pct")} inputMode="decimal" maxLength={6} disabled={mutation.isPending} required />
        <p className="text-xs text-text-secondary">0 to 100, up to two decimal places. New assignable names are limited to 30 characters.</p>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" {...form.register("reviewed")} disabled={mutation.isPending} />I reviewed the tier and future-order pricing change.</label>
        {Object.values(form.formState.errors).map((error, index) => <p key={index} role="alert" className="text-sm text-red-400">{error.message}</p>)}
        {mutation.isError && !axios.isCancel(mutation.error) ? <p role="alert" className="text-sm text-red-400">{errorText} Close and refresh tiers before trying again.</p> : null}
        <div className="flex flex-wrap justify-end gap-2"><button type="button" className="btn-ghost" disabled={mutation.isPending} onClick={onClose}>Close</button>
          <button className="btn-volt" disabled={mutation.isPending || mutation.isError} data-testid="pricing-tier-save">{mutation.isPending ? "Saving..." : "Save tier"}</button></div>
      </form>
    </div>
  </Modal>;
}
