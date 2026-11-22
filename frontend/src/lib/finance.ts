import { queryOptions, type QueryClient } from "@tanstack/react-query";
import { api } from "./api";

export interface CustomerFinance {
  id: string;
  code: string;
  name: string;
  customer_type: string;
  credit_limit: string;
  outstanding: string;
  credit_held: string;
  cash_funded_pending: string;
  credit_exposure: string;
  available_credit: string;
  advance_balance: string;
  is_active: boolean;
}

export interface OrderFinance {
  id: string;
  order_number: string;
  customer_id: string;
  status: string;
  grand_total: string;
  amount_paid: string;
  amount_due: string;
  payment_mode: "cash" | "credit";
  payment_status: "unpaid" | "partial" | "paid";
  credit_hold_amount: string;
}

export interface Payment {
  id: string;
  customer_id: string;
  order_id: string | null;
  amount: string;
  mode: string;
  allocation_kind: "order_payment" | "unallocated_advance" | "credit_note";
  reference: string | null;
  note: string | null;
  created_at: string;
}

export const customersQuery = queryOptions({
  queryKey: ["customers-min"],
  queryFn: async ({ signal }) => (
    await api.get<{ items: CustomerFinance[] }>("/customers?page_size=200", { signal })
  ).data.items,
});

// Normalize input as decimal text, never through floating-point money arithmetic.
export function moneyInput(value: string): string | null {
  const text = value.trim();
  if (!/^\d{1,12}(?:\.\d{1,2})?$/.test(text)) return null;
  const [whole, fraction = ""] = text.split(".");
  return `${whole.replace(/^0+(?=\d)/, "")}.${fraction.padEnd(2, "0")}`;
}

export async function refreshFinancialQueries(client: QueryClient) {
  await Promise.all([
    "payments", "customers", "customers-min", "orders", "order", "payment-orders",
    "deliveries", "inventory", "inv-stats", "order-stats",
  ].map((key) => client.invalidateQueries({ queryKey: [key] })));
}
