"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useForm, useWatch } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { api, apiError } from "@/lib/api";
import { moneyInput, type CustomerFinance, type OrderFinance, type Payment } from "@/lib/finance";
import { useIntentPost } from "@/lib/intent";
import { Modal } from "@/components/modal";
import { CustomerBalance, OrderBalance } from "@/components/financial-summary";
import { formatINR } from "@/lib/utils";

const schema = z.object({
  customer_id: z.string().min(1, "Choose a customer."),
  order_id: z.string(),
  amount: z.string().refine((value) => {
    const amount = moneyInput(value);
    return amount !== null && amount !== "0.00";
  }, "Enter a positive amount with at most two decimal places (no commas or exponent)."),
  mode: z.enum(["cash", "upi", "bank_transfer", "credit"]),
  reference: z.string().max(120),
  note: z.string().max(500),
});
type Fields = z.infer<typeof schema>;
const defaults: Fields = { customer_id: "", order_id: "", amount: "", mode: "cash", reference: "", note: "" };

export function PaymentForm({ open, customers, onClose, onDone }: {
  open: boolean;
  customers: CustomerFinance[];
  onClose: () => void;
  onDone: () => void;
}) {
  const mutation = useIntentPost();
  const [page, setPage] = useState(1);
  const { register, control, handleSubmit, setValue, reset, formState: { isValid, errors } } = useForm<Fields>({
    defaultValues: defaults, resolver: zodResolver(schema), mode: "onChange",
  });
  const [customerId, orderId, mode] = useWatch({ control, name: ["customer_id", "order_id", "mode"] });
  const customer = customers.find((item) => item.id === customerId);
  const orders = useQuery({
    queryKey: ["payment-orders", customerId, page],
    enabled: open && !!customerId && mode !== "credit",
    staleTime: 0,
    queryFn: async ({ signal }) => (await api.get<{ items: OrderFinance[]; total: number }>("/orders", {
      params: { customer_id: customerId, page, page_size: 200 }, signal,
    })).data,
  });
  const order = orders.data?.items.find((item) => item.id === orderId && item.customer_id === customerId);

  async function submit(form: Fields) {
    if (form.order_id && (!order || form.mode === "credit")) return;
    const result = await mutation.post<Payment>("/payments", {
      customer_id: form.customer_id,
      ...(form.order_id ? { order_id: form.order_id } : {}),
      amount: moneyInput(form.amount), mode: form.mode,
      reference: form.reference.trim() || null, note: form.note.trim() || null,
    });
    if (!result) return;
    toast.success(result.allocation_kind === "order_payment" ? "Payment allocated to order." : "Unallocated account credit recorded.");
    reset(defaults);
    setPage(1);
    onDone();
    onClose();
  }

  return (
    <Modal open={open} busy={mutation.busy} onClose={onClose} labelledBy="payment-title" testId="pay-modal">
      <h2 id="payment-title" className="font-display text-2xl font-bold mb-4">Record payment</h2>
      <form onSubmit={handleSubmit(submit)} onChange={mutation.payloadChanged}>
        <fieldset disabled={mutation.busy} className="space-y-4">
          <div>
            <label className="data-label" htmlFor="pay-customer">Customer</label>
            <select id="pay-customer" className="input mt-1" data-testid="pay-customer" {...register("customer_id", {
              onChange: () => { setValue("order_id", ""); setValue("amount", "", { shouldValidate: true }); setPage(1); },
            })}>
              <option value="">Select customer...</option>
              {customers.map((item) => <option key={item.id} value={item.id}>{item.code} / {item.name}{item.is_active ? "" : " (inactive)"}</option>)}
            </select>
          </div>
          {customer && <CustomerBalance customer={customer} />}
          <div>
            <label className="data-label" htmlFor="pay-order">Order (optional)</label>
            <select id="pay-order" className="input mt-1" data-testid="pay-order" disabled={!customerId || mode === "credit"} {...register("order_id")}>
              <option value="">No order / unallocated advance</option>
              {orders.data?.items.filter((item) => item.status !== "cancelled" && item.payment_status !== "paid").map((item) => (
                <option key={item.id} value={item.id}>{item.order_number} / {item.payment_mode} / {formatINR(item.amount_due)} due</option>
              ))}
            </select>
            {orders.isFetching && <p role="status" className="text-xs mt-1">Loading customer orders...</p>}
            {orders.isError && <p role="alert">{apiError(orders.error)} <button type="button" className="btn-ghost" onClick={() => void orders.refetch()}>Retry orders</button></p>}
            {customerId && mode !== "credit" && <div className="flex items-center gap-2 mt-2 text-xs">
              <button type="button" className="btn-ghost" disabled={page === 1} onClick={() => { mutation.payloadChanged(); setValue("order_id", ""); setPage(page - 1); }}>Previous orders</button>
              <span>Page {page}</span>
              <button type="button" className="btn-ghost" disabled={!orders.data || page * 200 >= orders.data.total} onClick={() => { mutation.payloadChanged(); setValue("order_id", ""); setPage(page + 1); }}>More orders</button>
            </div>}
          </div>
          {order ? <OrderBalance order={order} /> : <p className="text-sm text-text-secondary" data-testid="pay-unallocated">No order selected: this is unallocated account credit, not payment of an order.</p>}
          <div>
            <label className="data-label" htmlFor="pay-amount">Amount (INR)</label>
            <input id="pay-amount" className="input mt-1" inputMode="decimal" data-testid="pay-amount" aria-invalid={!!errors.amount} {...register("amount")} />
            {errors.amount && <p role="alert" className="text-sm">{errors.amount.message}</p>}
            {order && <button type="button" className="btn-ghost text-xs mt-2" data-testid="pay-use-due" onClick={() => {
              mutation.payloadChanged(); setValue("amount", order.amount_due, { shouldValidate: true });
            }}>Use server remainder due</button>}
          </div>
          <div>
            <label className="data-label" htmlFor="pay-mode">Mode</label>
            <select id="pay-mode" className="input mt-1" data-testid="pay-mode" {...register("mode", {
              onChange: (event) => { if (event.target.value === "credit") setValue("order_id", ""); },
            })}>
              <option value="cash">Cash</option><option value="upi">UPI</option><option value="bank_transfer">Bank transfer</option><option value="credit">Credit note (unallocated only)</option>
            </select>
            <p className="text-xs text-text-secondary mt-1">Manual receipt recording only; no live payment gateway verification.</p>
          </div>
          <div>
            <label className="data-label" htmlFor="pay-ref">Receipt reference (optional)</label>
            <input id="pay-ref" className="input mt-1" maxLength={120} data-testid="pay-ref" {...register("reference")} />
          </div>
          <div>
            <label className="data-label" htmlFor="pay-note">Note (optional)</label>
            <input id="pay-note" className="input mt-1" maxLength={500} data-testid="pay-note" {...register("note")} />
          </div>
        </fieldset>
        {mutation.error && <p role="alert" className="mt-3" data-testid="pay-error">{mutation.error}</p>}
        {mutation.unconfirmed && <p role="status" className="text-sm mt-2" data-testid="pay-unconfirmed">Result unconfirmed. Retry unchanged to recover safely with the same request key. Changing fields starts a new payment intent.</p>}
        <div className="flex flex-wrap justify-end gap-2 mt-5">
          <button type="button" className="btn-ghost" disabled={mutation.busy} onClick={onClose} data-testid="pay-close">Close</button>
          <button type="submit" className="btn-volt" disabled={mutation.busy || !isValid || (!!orderId && !order)} data-testid="pay-submit">{mutation.busy ? "Saving..." : mutation.unconfirmed ? "Retry payment" : "Record payment"}</button>
        </div>
      </form>
    </Modal>
  );
}
