import type { CustomerFinance, OrderFinance } from "@/lib/finance";
import { formatINR } from "@/lib/utils";

export function CustomerBalance({ customer }: { customer: CustomerFinance }) {
  return (
    <div className="pane p-4 space-y-3" data-testid="customer-balance">
      <p className="data-label">{customer.name} / server balance</p>
      <span className="chip chip-info">{customer.customer_type} customer</span>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div><dt className="data-label">Account balance</dt><dd>{formatINR(customer.outstanding)}</dd></div>
        <div><dt className="data-label">Credit limit</dt><dd>{formatINR(customer.credit_limit)}</dd></div>
        <div><dt className="data-label">Credit held</dt><dd>{formatINR(customer.credit_held)}</dd></div>
        <div><dt className="data-label">Available credit</dt><dd>{formatINR(customer.available_credit)}</dd></div>
        <div><dt className="data-label">Credit exposure</dt><dd>{formatINR(customer.credit_exposure)}</dd></div>
        <div><dt className="data-label">Pending cash funding</dt><dd>{formatINR(customer.cash_funded_pending)}</dd></div>
        {customer.outstanding?.startsWith("-") && (
          <div data-testid="customer-advance"><dt className="data-label">Advance balance</dt><dd>{formatINR(customer.advance_balance)}</dd></div>
        )}
      </dl>
      <p className="text-xs text-text-secondary">Negative account balances are advances, not debt. An unallocated advance does not fund a cash order.</p>
    </div>
  );
}

export function OrderBalance({ order }: { order: OrderFinance }) {
  return (
    <div className="pane p-4 space-y-3" data-testid="order-balance">
      <div className="flex flex-wrap gap-2">
        <span className="chip chip-info">{order.payment_mode} order</span>
        <span className="chip chip-muted">Payment {order.payment_status}</span>
      </div>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
        <div><dt className="data-label">Total</dt><dd>{formatINR(order.grand_total)}</dd></div>
        <div><dt className="data-label">Allocated</dt><dd>{formatINR(order.amount_paid)}</dd></div>
        <div data-testid="order-amount-due"><dt className="data-label">Remainder due</dt><dd>{formatINR(order.amount_due)}</dd></div>
        <div><dt className="data-label">Credit hold</dt><dd>{formatINR(order.credit_hold_amount)}</dd></div>
      </dl>
      <p className="text-xs text-text-secondary">Amounts and funding eligibility are supplied and validated by the server.</p>
    </div>
  );
}
