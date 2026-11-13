"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiError } from "@/lib/api";
import { refreshFinancialQueries } from "@/lib/finance";
import { DeliveryWorkflow, type Delivery } from "@/features/deliveries/workflow";
import { formatDateTime, formatDate, formatINR } from "@/lib/utils";

export default function DeliveriesPage() {
  return <Suspense fallback={<p role="status" className="p-6">Loading deliveries...</p>}><DeliveriesContent /></Suspense>;
}

function DeliveriesContent() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const deliveries = useQuery({
    queryKey: ["deliveries"],
    queryFn: async ({ signal }) => (await api.get<Delivery[]>("/deliveries", { signal })).data,
  });
  const data = deliveries.data;
  const requestedOrder = params.get("order_id");
  const requestedId = params.get("delivery_id") || data?.find((item) => item.order_id === requestedOrder)?.id || null;
  // Retain the hidden workflow's unconfirmed draft when its URL is closed and reopened.
  if (requestedId && focusedId !== requestedId) setFocusedId(requestedId);
  const delivery = data?.find((item) => item.id === (requestedId || focusedId));

  return (
    <div className="page-shell">
      <header className="page-header">
        <div><p className="data-label">Last mile</p><h1 className="page-title">Deliveries</h1></div>
        <button className="btn-ghost" onClick={() => void deliveries.refetch()} data-testid="deliveries-refresh">Refresh</button>
      </header>
      <div className="page-body">
        {deliveries.isPending && <p role="status">Loading deliveries...</p>}
        {deliveries.error && <p role="alert">{apiError(deliveries.error)}</p>}
        {data && (requestedOrder || params.get("delivery_id")) && !data.some((item) => item.id === requestedId) && <p role="alert">No delivery found for the requested order or delivery. Refresh after dispatch.</p>}
        <div className="pane overflow-x-auto mobile-cards">
          <table className="grid" data-testid="deliveries-table">
            <thead>
              <tr>
                <th>Order</th>
                <th>Priority</th>
                <th>Scheduled</th>
                <th>Partner</th>
                <th>Started</th>
                <th>Completed</th>
                <th>OTP</th>
                <th className="text-right">Cash</th>
                <th className="text-right">UPI</th>
                <th>Workflow</th>
              </tr>
            </thead>
            <tbody>
              {data && !data.length && (
                <tr>
                  <td colSpan={10} className="text-text-secondary">
                    No deliveries yet.
                  </td>
                </tr>
              )}
              {data?.map((d) => (
                <tr key={d.id} data-testid={`delivery-row-${d.id}`}>
                  <td data-label="Order" className="text-xs">
                    {d.order_id.slice(0, 8)}
                  </td>
                  <td data-label="Priority">P{d.priority}</td>
                  <td data-label="Scheduled">{formatDate(d.scheduled_date)}</td>
                  <td data-label="Partner">
                    {d.partner_id ? (
                      d.partner_id.slice(0, 8)
                    ) : (
                      <span className="chip chip-muted">unassigned</span>
                    )}
                  </td>
                  <td data-label="Started">{formatDateTime(d.started_at)}</td>
                  <td data-label="Completed">
                    {d.completed_at ? (
                      <span className="chip chip-success">
                        {formatDateTime(d.completed_at)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td data-label="OTP">
                    {d.otp_verified ? (
                      <span className="chip chip-success">✓</span>
                    ) : (
                      <span className="chip chip-muted">pending</span>
                    )}
                  </td>
                  <td data-label="Cash" className="text-right">
                    {formatINR(d.cash_collected)}
                  </td>
                  <td data-label="UPI" className="text-right">
                    {formatINR(d.upi_collected)}
                  </td>
                  <td data-label="Workflow"><Link className="btn-ghost text-xs" data-testid={`delivery-open-${d.id}`} href={`/deliveries?delivery_id=${encodeURIComponent(d.id)}`}>{d.completed_at ? "View proof" : "Open delivery"}</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {delivery && <DeliveryWorkflow key={delivery.id} open={requestedId === delivery.id} delivery={delivery} onClose={() => router.replace("/deliveries", { scroll: false })} onRefresh={() => deliveries.refetch()} onCompleted={(result) => {
        qc.setQueryData<Delivery[]>(["deliveries"], (rows) => rows?.map((item) => item.id === result.id ? result : item));
        void refreshFinancialQueries(qc);
      }} />}
    </div>
  );
}
