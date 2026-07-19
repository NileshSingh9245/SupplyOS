"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDateTime, formatDate } from "@/lib/utils";

interface Delivery {
  id: string; order_id: string; partner_id: string | null;
  scheduled_date: string | null; priority: number; otp_verified: boolean;
  signature_url: string | null; proof_photo_url: string | null;
  cash_collected: string; upi_collected: string;
  started_at: string | null; completed_at: string | null; created_at: string;
}

export default function DeliveriesPage() {
  const { data } = useQuery({
    queryKey: ["deliveries"],
    queryFn: async () => (await api.get<Delivery[]>("/deliveries")).data,
  });

  return (
    <div className="h-screen flex flex-col">
      <header className="border-b border-border px-8 py-5">
        <p className="data-label">Last mile</p>
        <h1 className="font-display text-3xl font-black tracking-tightest">Deliveries</h1>
      </header>
      <div className="flex-1 overflow-auto p-8">
        <div className="pane overflow-x-auto">
          <table className="grid" data-testid="deliveries-table">
            <thead>
              <tr>
                <th>Order</th><th>Priority</th><th>Scheduled</th>
                <th>Partner</th><th>Started</th><th>Completed</th>
                <th>OTP</th><th className="text-right">Cash</th><th className="text-right">UPI</th>
              </tr>
            </thead>
            <tbody>
              {!data?.length && <tr><td colSpan={9} className="text-text-secondary">No deliveries yet.</td></tr>}
              {data?.map((d) => (
                <tr key={d.id} data-testid={`delivery-row-${d.id}`}>
                  <td className="text-xs">{d.order_id.slice(0, 8)}</td>
                  <td>P{d.priority}</td>
                  <td>{formatDate(d.scheduled_date)}</td>
                  <td>{d.partner_id ? d.partner_id.slice(0, 8) : <span className="chip chip-muted">unassigned</span>}</td>
                  <td>{formatDateTime(d.started_at)}</td>
                  <td>{d.completed_at ? <span className="chip chip-success">{formatDateTime(d.completed_at)}</span> : "—"}</td>
                  <td>{d.otp_verified ? <span className="chip chip-success">✓</span> : <span className="chip chip-muted">pending</span>}</td>
                  <td className="text-right">₹{d.cash_collected}</td>
                  <td className="text-right">₹{d.upi_collected}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
