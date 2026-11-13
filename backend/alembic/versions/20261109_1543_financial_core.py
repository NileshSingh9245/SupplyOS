"""Freeze server payment mode, gross credit commitments, and atomic request replay.

Legacy delivery charged according to customer_type, not the discarded is_credit input.
Undelivered orders adopt that behavior; historical order debits identify actual credit sales.
Over-limit live commitments are preserved but cannot reserve/deliver until funded or released.
Ambiguous/clamped ledger credits and inconsistent allocation require reviewed reconciliation.
No historical balances, payments, order totals, or ledger entries are repaired by this revision.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261109_0004"
down_revision = "20261109_0003"
branch_labels = None
depends_on = None

LIVE = "('pending', 'confirmed', 'reserved', 'picked', 'packed', 'out_for_delivery')"
FINISHED = "('delivered', 'paid', 'completed')"
CHECKS = (
    ("customers", "financial_balances",
     "credit_limit >= 0 AND credit_limit <= 999999999999.99 "
     "AND outstanding >= -999999999999.99 AND outstanding <= 999999999999.99 "
     "AND credit_held >= 0 AND credit_held <= 999999999999.99 "
     "AND cash_funded_pending >= 0 AND cash_funded_pending <= 999999999999.99"),
    ("orders", "payment_mode", "payment_mode IN ('cash', 'credit')"),
    ("orders", "financial_totals",
     "subtotal >= 0 AND subtotal <= 999999999999.99 "
     "AND tax_total >= 0 AND tax_total <= 999999999999.99 "
     "AND discount_total >= 0 AND discount_total <= 999999999999.99 "
     "AND grand_total >= 0 AND grand_total <= 999999999999.99 "
     "AND amount_paid >= 0 AND amount_paid <= grand_total"),
    ("orders", "credit_hold",
     "credit_hold_amount >= 0 AND credit_hold_amount <= grand_total "
     "AND ((payment_mode = 'credit' AND status IN "
     "('pending', 'confirmed', 'reserved', 'picked', 'packed', 'out_for_delivery') "
     "AND credit_hold_amount = grand_total) "
     "OR (credit_hold_amount = 0 AND (payment_mode = 'cash' OR status IN "
     "('delivered', 'paid', 'completed', 'cancelled'))))"),
    ("order_items", "financial_line",
     "quantity > 0 AND quantity <= 9999999999999.999 "
     "AND picked_qty >= 0 AND picked_qty <= quantity "
     "AND unit_price >= 0 AND unit_price <= 999999999999.99 "
     "AND gst_rate >= 0 AND gst_rate <= 999.99 "
     "AND line_subtotal >= 0 AND line_subtotal <= 999999999999.99 "
     "AND line_tax >= 0 AND line_tax <= 999999999999.99 "
     "AND line_total >= 0 AND line_total <= 999999999999.99"),
    ("order_reservations", "quantity", "quantity > 0 AND quantity <= 9999999999999.999"),
    ("payments", "positive_amount", "amount > 0 AND amount <= 999999999999.99"),
    ("payments", "funding_mode",
     "mode IN ('cash', 'upi', 'bank_transfer', 'credit') "
     "AND (mode <> 'credit' OR order_id IS NULL)"),
    ("deliveries", "collections",
     "cash_collected >= 0 AND cash_collected <= 999999999999.99 "
     "AND upi_collected >= 0 AND upi_collected <= 999999999999.99"),
    ("ledger_entries", "financial_amounts",
     "debit >= 0 AND debit <= 999999999999.99 "
     "AND credit >= 0 AND credit <= 999999999999.99 "
     "AND (debit = 0 OR credit = 0) "
     "AND balance_after >= -999999999999.99 AND balance_after <= 999999999999.99"),
)


def _validate_legacy() -> None:
    connection = op.get_bind()
    # Migration locks are table-wide: no old writer can slip a payment into the backfill.
    connection.execute(sa.text(
        "LOCK TABLE orders, customers, deliveries, order_items, order_reservations, payments, "
        "ledger_entries IN ACCESS EXCLUSIVE MODE"
    ))
    checks = [
        ("customer type or balance", "SELECT 1 FROM customers WHERE "
         "customer_type NOT IN ('cash', 'credit') OR NOT (credit_limit >= 0 AND "
         "credit_limit <= 999999999999.99 AND outstanding >= -999999999999.99 "
         "AND outstanding <= 999999999999.99) LIMIT 1"),
        ("order status or tenant", "SELECT 1 FROM orders o JOIN customers c ON c.id=o.customer_id "
         "JOIN warehouses w ON w.id=o.warehouse_id WHERE c.tenant_id<>o.tenant_id "
         "OR w.tenant_id<>o.tenant_id OR o.status NOT IN "
         "('pending','confirmed','reserved','picked','packed','out_for_delivery',"
         "'delivered','paid','completed','cancelled') LIMIT 1"),
        ("payment tenant, customer, or allocation", "SELECT 1 FROM payments p "
         "JOIN customers c ON c.id=p.customer_id LEFT JOIN orders o ON o.id=p.order_id "
         "WHERE p.tenant_id<>c.tenant_id OR (p.order_id IS NOT NULL AND "
         "(p.tenant_id<>o.tenant_id OR p.customer_id<>o.customer_id)) LIMIT 1"),
        ("linked payments disagree with amount_paid", "SELECT 1 FROM orders o LEFT JOIN "
         "(SELECT order_id, SUM(amount) amount FROM payments WHERE order_id IS NOT NULL "
         "GROUP BY order_id) p ON p.order_id=o.id "
         "WHERE o.amount_paid<>COALESCE(p.amount,0) LIMIT 1"),
        ("ledger tenant", "SELECT 1 FROM ledger_entries l LEFT JOIN customers c ON c.id=l.customer_id "
         "WHERE c.id IS NULL OR l.tenant_id<>c.tenant_id LIMIT 1"),
        ("delivery tenant", "SELECT 1 FROM deliveries d JOIN orders o ON o.id=d.order_id "
         "WHERE d.tenant_id<>o.tenant_id LIMIT 1"),
        ("order line or reservation reference", "SELECT 1 FROM order_items i JOIN orders o "
         "ON o.id=i.order_id JOIN products p ON p.id=i.product_id WHERE "
         "i.tenant_id<>o.tenant_id OR i.tenant_id<>p.tenant_id UNION ALL "
         "SELECT 1 FROM order_reservations r JOIN orders o ON o.id=r.order_id "
         "JOIN order_items i ON i.id=r.order_item_id JOIN inventory_items v "
         "ON v.id=r.inventory_item_id WHERE r.tenant_id<>o.tenant_id OR "
         "r.tenant_id<>i.tenant_id OR i.order_id<>r.order_id OR r.tenant_id<>v.tenant_id "
         "OR i.product_id<>v.product_id OR o.warehouse_id<>v.warehouse_id LIMIT 1"),
        ("reservation lifecycle", "SELECT 1 FROM order_reservations r JOIN orders o "
         "ON o.id=r.order_id WHERE (r.fulfilled_at IS NOT NULL AND r.released_at IS NOT NULL) "
         f"OR (r.fulfilled_at IS NOT NULL AND o.status NOT IN {FINISHED}) "
         f"OR (r.fulfilled_at IS NULL AND r.released_at IS NULL AND o.status NOT IN {LIVE}) LIMIT 1"),
        ("historical order debit reference", "SELECT 1 FROM ledger_entries l LEFT JOIN orders o "
         "ON o.id=l.reference_id WHERE l.reference_type='order' AND "
         "(l.reference_id IS NULL OR o.id IS NULL OR l.customer_id<>o.customer_id "
         "OR l.tenant_id<>o.tenant_id OR "
         f"o.status NOT IN {FINISHED} OR l.debit<>o.grand_total OR l.credit<>0) LIMIT 1"),
        ("duplicate historical order debits", "SELECT 1 FROM ledger_entries WHERE "
         "reference_type='order' GROUP BY reference_id HAVING COUNT(*)>1 LIMIT 1"),
        ("historical payment credit reference", "SELECT 1 FROM ledger_entries l LEFT JOIN payments p "
         "ON p.id=l.reference_id WHERE l.reference_type='payment' AND "
         "(l.reference_id IS NULL OR p.id IS NULL OR l.customer_id<>p.customer_id "
         "OR l.tenant_id<>p.tenant_id OR l.debit<>0 OR l.credit<=0 "
         "OR l.credit<>p.amount) LIMIT 1"),
        ("duplicate historical payment credits", "SELECT 1 FROM ledger_entries WHERE "
         "reference_type='payment' GROUP BY reference_id HAVING COUNT(*)>1 LIMIT 1"),
        ("unverifiable historical credit reference", "SELECT 1 FROM ledger_entries WHERE credit>0 "
         "AND COALESCE(reference_type,'') NOT IN ('payment','delivery_payment') LIMIT 1"),
        ("legacy delivery_payment reference or unsupported completion", "SELECT 1 FROM ledger_entries l "
         "LEFT JOIN deliveries d ON d.id=l.reference_id LEFT JOIN orders o ON o.id=d.order_id "
         "WHERE l.reference_type='delivery_payment' AND (l.reference_id IS NULL OR d.id IS NULL "
         "OR o.id IS NULL OR d.tenant_id<>l.tenant_id OR o.tenant_id<>l.tenant_id "
         "OR o.customer_id<>l.customer_id OR d.completed_at IS NULL OR NOT d.otp_verified "
         f"OR o.status NOT IN {FINISHED} OR l.debit<>0 OR l.credit<=0 "
         "OR l.credit<>d.cash_collected+d.upi_collected) LIMIT 1"),
        ("duplicate legacy delivery_payment credits", "SELECT 1 FROM ledger_entries WHERE "
         "reference_type='delivery_payment' GROUP BY reference_id HAVING COUNT(*)>1 LIMIT 1"),
        # The legacy producer wrote one receipt per nonzero mode in the ledger's transaction.
        # An individually referenced receipt can never also fund an aggregated delivery credit.
        ("ambiguous legacy delivery_payment receipt attribution", "SELECT 1 FROM ledger_entries l "
         "JOIN deliveries d ON d.id=l.reference_id LEFT JOIN LATERAL (SELECT "
         "COUNT(*) FILTER (WHERE p.mode='cash') cash_count, "
         "COUNT(*) FILTER (WHERE p.mode='upi') upi_count, "
         "COALESCE(SUM(p.amount) FILTER (WHERE p.mode='cash'),0) cash_amount, "
         "COALESCE(SUM(p.amount) FILTER (WHERE p.mode='upi'),0) upi_amount, "
         "BOOL_AND(p.created_at=l.created_at) same_transaction FROM payments p "
         "WHERE p.order_id=d.order_id AND p.customer_id=l.customer_id AND p.tenant_id=l.tenant_id "
         "AND p.mode IN ('cash','upi') AND NOT EXISTS (SELECT 1 FROM ledger_entries direct "
         "WHERE direct.reference_type='payment' AND direct.reference_id=p.id)) receipts ON TRUE "
         "WHERE l.reference_type='delivery_payment' AND "
         "(receipts.cash_count<>CASE WHEN d.cash_collected>0 THEN 1 ELSE 0 END "
         "OR receipts.upi_count<>CASE WHEN d.upi_collected>0 THEN 1 ELSE 0 END "
         "OR receipts.cash_amount<>d.cash_collected OR receipts.upi_amount<>d.upi_collected "
         "OR receipts.same_transaction IS NOT TRUE) LIMIT 1"),
        ("historical receipt must be credited exactly once", "WITH attribution AS ("
         "SELECT p.id receipt_id,l.id ledger_id,l.credit credited_amount FROM payments p "
         "JOIN ledger_entries l ON l.reference_type='payment' AND l.reference_id=p.id "
         "UNION ALL SELECT p.id,l.id,p.amount FROM ledger_entries l JOIN deliveries d "
         "ON l.reference_type='delivery_payment' AND l.reference_id=d.id JOIN payments p "
         "ON p.order_id=d.order_id AND p.customer_id=l.customer_id AND p.tenant_id=l.tenant_id "
         "AND p.created_at=l.created_at AND p.mode IN ('cash','upi') WHERE NOT EXISTS "
         "(SELECT 1 FROM ledger_entries direct WHERE direct.reference_type='payment' "
         "AND direct.reference_id=p.id)) SELECT 1 FROM payments p LEFT JOIN attribution a "
         "ON a.receipt_id=p.id GROUP BY p.id,p.amount HAVING COUNT(a.ledger_id)<>1 "
         "OR COALESCE(SUM(a.credited_amount),0)<>p.amount LIMIT 1"),
        ("ambiguous delivered credit mode", "SELECT 1 FROM orders o JOIN customers c "
         f"ON c.id=o.customer_id WHERE o.status IN {FINISHED} AND c.customer_type='credit' "
         "AND NOT EXISTS (SELECT 1 FROM ledger_entries l WHERE l.reference_type='order' "
         "AND l.reference_id=o.id) LIMIT 1"),
        ("inconsistent or ambiguous running ledger balance", "WITH ordered AS (SELECT l.*, "
         "LAG(balance_after) OVER (PARTITION BY customer_id ORDER BY created_at, "
         "CASE WHEN reference_type='order' THEN 0 ELSE 1 END, id) previous_balance, "
         "ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_at DESC, "
         "CASE WHEN reference_type='order' THEN 0 ELSE 1 END DESC, id DESC) latest "
         "FROM ledger_entries l) SELECT 1 FROM ordered l JOIN customers c ON c.id=l.customer_id "
         "WHERE (previous_balance IS NOT NULL AND "
         "balance_after<>previous_balance+debit-credit) OR (latest=1 AND "
         "balance_after<>c.outstanding) OR (previous_balance IS NULL AND credit>0 "
         "AND balance_after=0) LIMIT 1"),
    ]
    # These predicates are frozen here, not imported from mutable application metadata.
    for table, name, condition in CHECKS:
        if name in {"financial_balances", "payment_mode", "credit_hold"}:
            continue
        checks.append((name, f"SELECT 1 FROM {table} WHERE NOT ({condition}) LIMIT 1"))
    for reason, query in checks:
        if connection.execute(sa.text(query)).first() is not None:
            raise RuntimeError(
                f"Unsafe legacy financial state ({reason}) requires reviewed reconciliation; "
                "no historical orders, payments, or ledger entries were rewritten."
            )


def upgrade() -> None:
    if not op.get_context().as_sql:
        _validate_legacy()
    op.add_column("customers", sa.Column(
        "credit_held", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False,
    ))
    op.add_column("customers", sa.Column(
        "cash_funded_pending", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False,
    ))
    op.add_column("orders", sa.Column("payment_mode", sa.String(20), nullable=True))
    op.add_column("orders", sa.Column(
        "credit_hold_amount", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False,
    ))
    op.execute(sa.text(
        "UPDATE orders o SET payment_mode=CASE WHEN EXISTS (SELECT 1 FROM ledger_entries l "
        "WHERE l.reference_type='order' AND l.reference_id=o.id) THEN 'credit' "
        f"WHEN o.status IN {LIVE} THEN c.customer_type ELSE 'cash' END "
        "FROM customers c WHERE c.id=o.customer_id AND c.tenant_id=o.tenant_id"
    ))
    op.execute(sa.text(
        f"UPDATE orders SET credit_hold_amount=grand_total WHERE status IN {LIVE} "
        "AND payment_mode='credit'"
    ))
    op.execute(sa.text(
        "UPDATE customers c SET credit_held=COALESCE((SELECT SUM(o.credit_hold_amount) "
        "FROM orders o WHERE o.customer_id=c.id AND o.tenant_id=c.tenant_id),0), "
        "cash_funded_pending=COALESCE((SELECT SUM(o.amount_paid) FROM orders o "
        f"WHERE o.customer_id=c.id AND o.tenant_id=c.tenant_id AND o.status IN {LIVE} "
        "AND o.payment_mode='cash'),0)"
    ))
    op.alter_column("orders", "payment_mode", nullable=False, server_default=sa.text("'cash'"))
    for table, name, condition in CHECKS:
        op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, condition)
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_body", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("resource_type", sa.String(30), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_records")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE",
                                name=op.f("fk_idempotency_records_tenant_id_tenants")),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="RESTRICT",
                                name=op.f("fk_idempotency_records_actor_id_users")),
        sa.CheckConstraint(
            "(response_body IS NULL AND response_status IS NULL AND resource_id IS NULL "
            "AND resource_type IS NULL) OR (response_body IS NOT NULL "
            "AND response_status BETWEEN 200 AND 299 AND resource_id IS NOT NULL "
            "AND resource_type IS NOT NULL)", name=op.f("ck_idempotency_records_response_state"),
        ),
    )
    op.create_index("ix_idempotency_scope", "idempotency_records",
                    ["tenant_id", "actor_id", "operation", "key"], unique=True)
    for column in ("tenant_id", "actor_id", "expires_at"):
        op.create_index(f"ix_idempotency_records_{column}", "idempotency_records", [column])


def downgrade() -> None:
    if not op.get_context().as_sql:
        if op.get_bind().execute(sa.text(
            "SELECT 1 FROM idempotency_records UNION ALL SELECT 1 FROM orders "
            "UNION ALL SELECT 1 FROM payments UNION ALL SELECT 1 FROM ledger_entries LIMIT 1"
        )).first():
            raise RuntimeError(
                "Financial modes, balances, and replay records must be preserved; downgrade needs review"
            )
    op.drop_table("idempotency_records")
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.drop_column("orders", "credit_hold_amount")
    op.drop_column("orders", "payment_mode")
    op.drop_column("customers", "cash_funded_pending")
    op.drop_column("customers", "credit_held")
