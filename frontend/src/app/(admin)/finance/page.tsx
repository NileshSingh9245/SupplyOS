"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api, apiError } from "@/lib/api";
import { customersQuery, refreshFinancialQueries, type Payment } from "@/lib/finance";
import { CustomerBalance } from "@/components/financial-summary";
import { PaymentForm } from "@/features/finance/payment-form";
import { formatDateTime, formatINR } from "@/lib/utils";

export default function FinancePage() {
  const qc = useQueryClient();
  const [show, setShow] = useState(false);
  const [customerId, setCustomerId] = useState("");

  const paymentsQuery = useQuery({
    queryKey: ["payments", customerId],
    queryFn: async ({ signal }) => (await api.get<Payment[]>("/payments", {
      params: customerId ? { customer_id: customerId } : {}, signal,
    })).data,
  });
  const customerQuery = useQuery(customersQuery);
  const customers = customerQuery.data;
  const payments = paymentsQuery.data;
  const customer = customers?.find((item) => item.id === customerId);

  return (
    <div className="page-shell">
      <header className="page-header">
        <div>
          <p className="data-label">Money in / out</p>
          <h1 className="page-title">Finance</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" onClick={() => void refreshFinancialQueries(qc)} data-testid="finance-refresh">Refresh</button>
          <button
            className="btn-volt inline-flex items-center gap-2"
            onClick={() => setShow(true)}
            data-testid="pay-new"
            disabled={!customers}
          >
            <Plus size={14} /> Record payment
          </button>
        </div>
      </header>
      <div className="page-body space-y-6">
        <div className="pane p-4 space-y-3">
          <label className="data-label" htmlFor="finance-customer">Customer / receipts and balance</label>
          <select id="finance-customer" className="input" value={customerId} onChange={(event) => setCustomerId(event.target.value)} data-testid="finance-customer">
            <option value="">All recent receipts</option>
            {customers?.map((item) => <option key={item.id} value={item.id}>{item.code} / {item.name}</option>)}
          </select>
          <p className="text-sm text-text-secondary">Choose a customer to see server-calculated credit and advance balances. Payments without an order are explicitly unallocated.</p>
          {customerQuery.isPending && <p role="status">Loading customers...</p>}
          {customerQuery.isError && <p role="alert">{apiError(customerQuery.error)}</p>}
        </div>
        {customer && <CustomerBalance customer={customer} />}
        {paymentsQuery.isPending && <p role="status">Loading receipts...</p>}
        {paymentsQuery.isError && <p role="alert">{apiError(paymentsQuery.error)}</p>}

        <div className="pane overflow-x-auto mobile-cards">
          <h3 className="font-display text-xl font-bold p-4 border-b border-border">
            Recent payments
          </h3>
          <table className="grid" data-testid="pay-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Customer</th>
                <th>Mode</th>
                <th>Allocation / order</th>
                <th className="text-right">Amount</th>
                <th>Reference</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {payments && !payments.length && (
                <tr>
                  <td colSpan={7} className="text-text-secondary">
                    No payments yet.
                  </td>
                </tr>
              )}
              {payments?.map((p) => {
                const cust = customers?.find((c) => c.id === p.customer_id);
                return (
                  <tr key={p.id} data-testid={`pay-row-${p.id}`}>
                    <td data-label="Date">{formatDateTime(p.created_at)}</td>
                    <td data-label="Customer">
                      {cust?.name || p.customer_id.slice(0, 8)}
                    </td>
                    <td data-label="Mode">
                      <span className="chip chip-info">{p.mode}</span>
                    </td>
                    <td data-label="Allocation / order">
                      {p.allocation_kind.replaceAll("_", " ")}
                      {p.order_id && <span className="block text-text-secondary">Order {p.order_id.slice(0, 8)}</span>}
                    </td>
                    <td data-label="Amount" className="text-right font-bold">
                      {formatINR(p.amount)}
                    </td>
                    <td data-label="Reference">{p.reference || "—"}</td>
                    <td data-label="Note">{p.note || "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      <PaymentForm open={show} customers={customers || []} onClose={() => setShow(false)} onDone={() => void refreshFinancialQueries(qc)} />
    </div>
  );
}
