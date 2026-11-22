"""schema_baseline

Revision ID: 20261108_0001
Revises: 3a7b2a03cd3b
Create Date: 2026-11-09 00:52:50.343423

"""
from __future__ import annotations

from typing import Sequence, Union
import re

from alembic import context, op
import sqlalchemy as sa


revision: str = '20261108_0001'
down_revision: Union[str, None] = '3a7b2a03cd3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _normalized_sql(value: str | None) -> str:
    if value is None:
        return ""
    value = re.sub(r"::[a-zA-Z_][a-zA-Z_0-9]*(?:\([^)]*\))?", "", value)
    return re.sub(r"[\s()]", "", value).lower()


class _BaselineOperations:
    """Create fresh schema or validate the matching legacy create_all schema."""

    @staticmethod
    def f(name):
        return op.f(name)

    @staticmethod
    def create_table(name, *definitions, **kwargs):
        if op.get_context().as_sql:
            return op.create_table(name, *definitions, **kwargs)
        bind = op.get_bind()
        inspector = sa.inspect(bind)
        if not inspector.has_table(name):
            return op.create_table(name, *definitions, **kwargs)
        expected = sa.Table(name, sa.MetaData(), *definitions)
        actual_columns = {column["name"]: column for column in inspector.get_columns(name)}
        if set(actual_columns) != set(expected.columns.keys()):
            raise RuntimeError(f"Legacy column set mismatch in {name}; no adoption performed")
        for column in expected.columns:
            actual = actual_columns.get(column.name)
            if actual is None or actual["nullable"] != column.nullable:
                raise RuntimeError(f"Legacy schema mismatch in {name}.{column.name}; no adoption performed")
            if str(actual["type"].compile(dialect=bind.dialect)) != str(column.type.compile(dialect=bind.dialect)):
                raise RuntimeError(f"Legacy column type mismatch in {name}.{column.name}")
            default = str(column.server_default.arg) if column.server_default is not None else None
            if _normalized_sql(actual.get("default")) != _normalized_sql(default):
                raise RuntimeError(f"Legacy column default mismatch in {name}.{column.name}")
        if inspector.get_pk_constraint(name)["constrained_columns"] != list(expected.primary_key.columns.keys()):
            raise RuntimeError(f"Legacy primary key mismatch in {name}")
        actual_foreign_keys = {
            (
                tuple(key["constrained_columns"]), key["referred_table"],
                tuple(key["referred_columns"]), key.get("options", {}).get("ondelete", "").upper(),
            )
            for key in inspector.get_foreign_keys(name)
        }
        for constraint in expected.foreign_key_constraints:
            targets = [element.target_fullname.rsplit(".", 1) for element in constraint.elements]
            signature = (
                tuple(constraint.column_keys), targets[0][0], tuple(target[1] for target in targets),
                (constraint.ondelete or "").upper(),
            )
            if signature not in actual_foreign_keys:
                raise RuntimeError(f"Legacy foreign key mismatch in {name}")
        actual_unique = {
            tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints(name)
        }
        actual_checks = {
            str(constraint["name"]): _normalized_sql(constraint["sqltext"])
            for constraint in inspector.get_check_constraints(name)
        }
        for constraint in expected.constraints:
            if isinstance(constraint, sa.UniqueConstraint):
                if tuple(constraint.columns.keys()) not in actual_unique:
                    raise RuntimeError(f"Legacy unique constraint mismatch in {name}")
            if isinstance(constraint, sa.CheckConstraint):
                if actual_checks.get(str(constraint.name)) != _normalized_sql(str(constraint.sqltext)):
                    raise RuntimeError(f"Legacy check constraint mismatch in {name}")

    @staticmethod
    def create_index(name, table_name, columns, *, unique=False, **kwargs):
        if not op.get_context().as_sql:
            existing = {
                str(index["name"]): index for index in sa.inspect(op.get_bind()).get_indexes(table_name)
            }.get(str(name))
            if existing is not None:
                options = existing.get("dialect_options", {})
                signature_matches = (
                    existing["column_names"] == list(columns)
                    and existing["unique"] == unique
                    and _normalized_sql(options.get("postgresql_where")) == _normalized_sql(
                        str(kwargs["postgresql_where"]) if kwargs.get("postgresql_where") is not None else None
                    )
                    and tuple(options.get("postgresql_include") or ()) == tuple(kwargs.get("postgresql_include") or ())
                    and options.get("postgresql_using", "btree") == kwargs.get("postgresql_using", "btree")
                    and bool(options.get("postgresql_nulls_not_distinct")) == bool(kwargs.get("postgresql_nulls_not_distinct"))
                    and (options.get("postgresql_ops") or {}) == (kwargs.get("postgresql_ops") or {})
                )
                validity = op.get_bind().execute(sa.text(
                    "SELECT i.indisvalid, i.indisready FROM pg_index i "
                    "JOIN pg_class idx ON idx.oid = i.indexrelid "
                    "JOIN pg_class tbl ON tbl.oid = i.indrelid "
                    "JOIN pg_namespace ns ON ns.oid = tbl.relnamespace "
                    "WHERE ns.nspname = current_schema() AND tbl.relname = :table AND idx.relname = :index"
                ), {"table": table_name, "index": str(name)}).mappings().one_or_none()
                if not signature_matches or not validity or not validity["indisvalid"] or not validity["indisready"]:
                    raise RuntimeError(f"Legacy index mismatch in {table_name}.{name}")
                return
        op.create_index(name, table_name, columns, unique=unique, **kwargs)


def upgrade() -> None:
    # Definitions are frozen here; never import mutable application models.
    op = _BaselineOperations()
    op.create_table('ai_alerts',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.String(length=1000), nullable=False),
    sa.Column('action_hint', sa.String(length=300), nullable=True),
    sa.Column('resource_type', sa.String(length=30), nullable=True),
    sa.Column('resource_id', sa.String(length=64), nullable=True),
    sa.Column('meta', sa.JSON(), nullable=True),
    sa.Column('is_dismissed', sa.Boolean(), nullable=False),
    sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dismissed_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_alerts'))
    )
    op.create_index('ix_alerts_tenant_created', 'ai_alerts', ['tenant_id', 'created_at'], unique=False)
    op.create_index('ix_alerts_tenant_dismissed', 'ai_alerts', ['tenant_id', 'is_dismissed'], unique=False)
    op.create_table('audit_logs',
    sa.Column('tenant_id', sa.UUID(), nullable=True),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_email', sa.String(length=200), nullable=True),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('resource_type', sa.String(length=64), nullable=True),
    sa.Column('resource_id', sa.String(length=64), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index('ix_audit_actor', 'audit_logs', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_tenant_id'), 'audit_logs', ['tenant_id'], unique=False)
    op.create_index('ix_audit_tenant_created', 'audit_logs', ['tenant_id', 'created_at'], unique=False)
    op.create_table('categories',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['categories.id'], name=op.f('fk_categories_parent_id_categories'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_categories'))
    )
    op.create_index(op.f('ix_categories_tenant_id'), 'categories', ['tenant_id'], unique=False)
    op.create_index('ix_categories_tenant_name', 'categories', ['tenant_id', 'name'], unique=True)
    op.create_table('customers',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('business_name', sa.String(length=200), nullable=True),
    sa.Column('gstin', sa.String(length=20), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=200), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('state', sa.String(length=120), nullable=True),
    sa.Column('pincode', sa.String(length=15), nullable=True),
    sa.Column('customer_type', sa.String(length=20), nullable=False),
    sa.Column('credit_limit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('outstanding', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('price_tier', sa.String(length=30), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers'))
    )
    op.create_index('ix_customers_tenant_code', 'customers', ['tenant_id', 'code'], unique=True)
    op.create_index(op.f('ix_customers_tenant_id'), 'customers', ['tenant_id'], unique=False)
    op.create_table('login_attempts',
    sa.Column('identifier', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_attempts'))
    )
    op.create_index('ix_login_attempts_identifier', 'login_attempts', ['identifier'], unique=False)
    op.create_table('price_tiers',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=60), nullable=False),
    sa.Column('discount_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_price_tiers'))
    )
    op.create_index(op.f('ix_price_tiers_tenant_id'), 'price_tiers', ['tenant_id'], unique=False)
    op.create_index('ix_tier_tenant_name', 'price_tiers', ['tenant_id', 'name'], unique=True)
    op.create_table('stock_movements',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('warehouse_id', sa.UUID(), nullable=False),
    sa.Column('inventory_item_id', sa.UUID(), nullable=True),
    sa.Column('movement_type', sa.String(length=30), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=16, scale=3), nullable=False),
    sa.Column('reference_type', sa.String(length=30), nullable=True),
    sa.Column('reference_id', sa.UUID(), nullable=True),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('meta', sa.JSON(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_movements'))
    )
    op.create_index('ix_stock_mov_product', 'stock_movements', ['product_id'], unique=False)
    op.create_index('ix_stock_mov_tenant_created', 'stock_movements', ['tenant_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_stock_movements_tenant_id'), 'stock_movements', ['tenant_id'], unique=False)
    op.create_table('tenants',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('legal_name', sa.String(length=200), nullable=True),
    sa.Column('gstin', sa.String(length=20), nullable=True),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=200), nullable=True),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('is_setup_complete', sa.Boolean(), nullable=False),
    sa.Column('settings', sa.JSON(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenants'))
    )
    op.create_table('ledger_entries',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('debit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('credit', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('balance_after', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('reference_type', sa.String(length=30), nullable=True),
    sa.Column('reference_id', sa.UUID(), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_ledger_entries_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ledger_entries'))
    )
    op.create_index('ix_ledger_customer_created', 'ledger_entries', ['customer_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_ledger_entries_tenant_id'), 'ledger_entries', ['tenant_id'], unique=False)
    op.create_table('products',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('sku', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('barcode', sa.String(length=64), nullable=True),
    sa.Column('hsn_code', sa.String(length=20), nullable=True),
    sa.Column('category_id', sa.UUID(), nullable=True),
    sa.Column('unit', sa.String(length=20), nullable=False),
    sa.Column('pack_size', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('base_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('mrp', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('gst_rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('reorder_level', sa.Integer(), nullable=False),
    sa.Column('low_stock_threshold', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('image_url', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name=op.f('fk_products_category_id_categories'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_products'))
    )
    op.create_index('ix_products_barcode', 'products', ['barcode'], unique=False)
    op.create_index(op.f('ix_products_tenant_id'), 'products', ['tenant_id'], unique=False)
    op.create_index('ix_products_tenant_sku', 'products', ['tenant_id', 'sku'], unique=True)
    op.create_table('users',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('role', sa.String(length=30), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_email_verified', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_login_attempts', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_users_customer_id_customers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_users_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index('ix_users_tenant_email', 'users', ['tenant_id', 'email'], unique=True)
    op.create_table('batches',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('batch_code', sa.String(length=64), nullable=False),
    sa.Column('manufacture_date', sa.Date(), nullable=True),
    sa.Column('expiry_date', sa.Date(), nullable=True),
    sa.Column('supplier', sa.String(length=200), nullable=True),
    sa.Column('purchase_cost', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_batches_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_batches'))
    )
    op.create_index('ix_batches_product_code', 'batches', ['product_id', 'batch_code'], unique=True)
    op.create_index(op.f('ix_batches_tenant_id'), 'batches', ['tenant_id'], unique=False)
    op.create_table('customer_prices',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_prices_customer_id_customers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_customer_prices_product_id_products'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_prices'))
    )
    op.create_index('ix_cprice_customer_product', 'customer_prices', ['customer_id', 'product_id'], unique=True)
    op.create_index(op.f('ix_customer_prices_tenant_id'), 'customer_prices', ['tenant_id'], unique=False)
    op.create_table('password_reset_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token', sa.String(length=128), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_password_reset_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset_tokens')),
    sa.UniqueConstraint('token', name=op.f('uq_password_reset_tokens_token'))
    )
    op.create_index(op.f('ix_password_reset_tokens_user_id'), 'password_reset_tokens', ['user_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('jti', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('device_info', sa.String(length=255), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
    sa.UniqueConstraint('jti', name=op.f('uq_refresh_tokens_jti'))
    )
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('warehouses',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('address', sa.String(length=500), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('state', sa.String(length=120), nullable=True),
    sa.Column('pincode', sa.String(length=15), nullable=True),
    sa.Column('manager_id', sa.UUID(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['manager_id'], ['users.id'], name=op.f('fk_warehouses_manager_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_warehouses_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_warehouses'))
    )
    op.create_index('ix_warehouses_tenant_code', 'warehouses', ['tenant_id', 'code'], unique=True)
    op.create_table('orders',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('order_number', sa.String(length=32), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('warehouse_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('channel', sa.String(length=20), nullable=False),
    sa.Column('subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('tax_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('discount_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('grand_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('amount_paid', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('scheduled_delivery_date', sa.Date(), nullable=True),
    sa.Column('delivery_address', sa.String(length=500), nullable=True),
    sa.Column('notes', sa.String(length=500), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('meta', sa.JSON(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_orders_customer_id_customers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], name=op.f('fk_orders_warehouse_id_warehouses'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_orders'))
    )
    op.create_index('ix_orders_customer', 'orders', ['customer_id'], unique=False)
    op.create_index('ix_orders_tenant_number', 'orders', ['tenant_id', 'order_number'], unique=True)
    op.create_index('ix_orders_tenant_status', 'orders', ['tenant_id', 'status'], unique=False)
    op.create_table('racks',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('warehouse_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], name=op.f('fk_racks_warehouse_id_warehouses'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_racks'))
    )
    op.create_index(op.f('ix_racks_tenant_id'), 'racks', ['tenant_id'], unique=False)
    op.create_index('ix_racks_warehouse_code', 'racks', ['warehouse_id', 'code'], unique=True)
    op.create_table('deliveries',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('partner_id', sa.UUID(), nullable=True),
    sa.Column('scheduled_date', sa.Date(), nullable=True),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('otp_code', sa.String(length=10), nullable=True),
    sa.Column('otp_verified', sa.Boolean(), nullable=False),
    sa.Column('signature_url', sa.String(length=500), nullable=True),
    sa.Column('proof_photo_url', sa.String(length=500), nullable=True),
    sa.Column('cash_collected', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('upi_collected', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_deliveries_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['partner_id'], ['users.id'], name=op.f('fk_deliveries_partner_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_deliveries'))
    )
    op.create_index('ix_deliveries_order', 'deliveries', ['order_id'], unique=True)
    op.create_index('ix_deliveries_partner_date', 'deliveries', ['partner_id', 'scheduled_date'], unique=False)
    op.create_table('order_items',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('product_sku', sa.String(length=64), nullable=False),
    sa.Column('product_name', sa.String(length=255), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=16, scale=3), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('gst_rate', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('line_subtotal', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('line_tax', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('line_total', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('picked_qty', sa.Numeric(precision=16, scale=3), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_items_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_order_items_product_id_products'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_items'))
    )
    op.create_index('ix_order_items_order', 'order_items', ['order_id'], unique=False)
    op.create_table('order_status_history',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('from_status', sa.String(length=30), nullable=True),
    sa.Column('to_status', sa.String(length=30), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_status_history_order_id_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_status_history'))
    )
    op.create_index('ix_osh_order', 'order_status_history', ['order_id'], unique=False)
    op.create_table('payments',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=True),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('reference', sa.String(length=120), nullable=True),
    sa.Column('collected_by', sa.UUID(), nullable=True),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_payments_customer_id_customers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_payments_order_id_orders'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments'))
    )
    op.create_index('ix_payments_customer', 'payments', ['customer_id'], unique=False)
    op.create_index('ix_payments_order', 'payments', ['order_id'], unique=False)
    op.create_table('shelves',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('warehouse_id', sa.UUID(), nullable=False),
    sa.Column('rack_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['rack_id'], ['racks.id'], name=op.f('fk_shelves_rack_id_racks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_shelves'))
    )
    op.create_index('ix_shelves_rack_code', 'shelves', ['rack_id', 'code'], unique=True)
    op.create_index(op.f('ix_shelves_tenant_id'), 'shelves', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_shelves_warehouse_id'), 'shelves', ['warehouse_id'], unique=False)
    op.create_table('inventory_items',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('warehouse_id', sa.UUID(), nullable=False),
    sa.Column('rack_id', sa.UUID(), nullable=True),
    sa.Column('shelf_id', sa.UUID(), nullable=True),
    sa.Column('batch_id', sa.UUID(), nullable=True),
    sa.Column('quantity', sa.Numeric(precision=16, scale=3), nullable=False),
    sa.Column('reserved_qty', sa.Numeric(precision=16, scale=3), nullable=False),
    sa.Column('in_transit_qty', sa.Numeric(precision=16, scale=3), nullable=False),
    sa.Column('damaged_qty', sa.Numeric(precision=16, scale=3), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('quantity >= 0', name=op.f('ck_inventory_items_quantity_nonneg')),
    sa.CheckConstraint('reserved_qty <= quantity', name=op.f('ck_inventory_items_reserved_le_quantity')),
    sa.CheckConstraint('reserved_qty >= 0', name=op.f('ck_inventory_items_reserved_nonneg')),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name=op.f('fk_inventory_items_batch_id_batches'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_inventory_items_product_id_products'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['rack_id'], ['racks.id'], name=op.f('fk_inventory_items_rack_id_racks'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['shelf_id'], ['shelves.id'], name=op.f('fk_inventory_items_shelf_id_shelves'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['warehouse_id'], ['warehouses.id'], name=op.f('fk_inventory_items_warehouse_id_warehouses'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inventory_items'))
    )
    op.create_index('ix_inv_tenant_product', 'inventory_items', ['tenant_id', 'product_id'], unique=False)
    op.create_index('ix_inv_tenant_warehouse', 'inventory_items', ['tenant_id', 'warehouse_id'], unique=False)
    op.create_index('ix_inv_unique_location', 'inventory_items', ['tenant_id', 'product_id', 'warehouse_id', 'rack_id', 'shelf_id', 'batch_id'], unique=True)
    op.create_table('order_reservations',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('order_item_id', sa.UUID(), nullable=False),
    sa.Column('inventory_item_id', sa.UUID(), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=16, scale=3), nullable=False),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['inventory_item_id'], ['inventory_items.id'], name=op.f('fk_order_reservations_inventory_item_id_inventory_items'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_order_reservations_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['order_item_id'], ['order_items.id'], name=op.f('fk_order_reservations_order_item_id_order_items'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_reservations'))
    )
    op.create_index('ix_reservations_order', 'order_reservations', ['order_id'], unique=False)


def downgrade() -> None:
    if context.get_x_argument(as_dictionary=True).get("allow_destructive_downgrade") != "1":
        raise RuntimeError(
            "Schema baseline downgrade deletes application data, including adopted legacy tables. "
            "Use -x allow_destructive_downgrade=1 only for disposable data or a reviewed backup."
        )
    op.drop_index('ix_reservations_order', table_name='order_reservations')
    op.drop_table('order_reservations')
    op.drop_index('ix_inv_unique_location', table_name='inventory_items')
    op.drop_index('ix_inv_tenant_warehouse', table_name='inventory_items')
    op.drop_index('ix_inv_tenant_product', table_name='inventory_items')
    op.drop_table('inventory_items')
    op.drop_index(op.f('ix_shelves_warehouse_id'), table_name='shelves')
    op.drop_index(op.f('ix_shelves_tenant_id'), table_name='shelves')
    op.drop_index('ix_shelves_rack_code', table_name='shelves')
    op.drop_table('shelves')
    op.drop_index('ix_payments_order', table_name='payments')
    op.drop_index('ix_payments_customer', table_name='payments')
    op.drop_table('payments')
    op.drop_index('ix_osh_order', table_name='order_status_history')
    op.drop_table('order_status_history')
    op.drop_index('ix_order_items_order', table_name='order_items')
    op.drop_table('order_items')
    op.drop_index('ix_deliveries_partner_date', table_name='deliveries')
    op.drop_index('ix_deliveries_order', table_name='deliveries')
    op.drop_table('deliveries')
    op.drop_index('ix_racks_warehouse_code', table_name='racks')
    op.drop_index(op.f('ix_racks_tenant_id'), table_name='racks')
    op.drop_table('racks')
    op.drop_index('ix_orders_tenant_status', table_name='orders')
    op.drop_index('ix_orders_tenant_number', table_name='orders')
    op.drop_index('ix_orders_customer', table_name='orders')
    op.drop_table('orders')
    op.drop_index('ix_warehouses_tenant_code', table_name='warehouses')
    op.drop_table('warehouses')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_password_reset_tokens_user_id'), table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
    op.drop_index(op.f('ix_customer_prices_tenant_id'), table_name='customer_prices')
    op.drop_index('ix_cprice_customer_product', table_name='customer_prices')
    op.drop_table('customer_prices')
    op.drop_index(op.f('ix_batches_tenant_id'), table_name='batches')
    op.drop_index('ix_batches_product_code', table_name='batches')
    op.drop_table('batches')
    op.drop_index('ix_users_tenant_email', table_name='users')
    op.drop_table('users')
    op.drop_index('ix_products_tenant_sku', table_name='products')
    op.drop_index(op.f('ix_products_tenant_id'), table_name='products')
    op.drop_index('ix_products_barcode', table_name='products')
    op.drop_table('products')
    op.drop_index(op.f('ix_ledger_entries_tenant_id'), table_name='ledger_entries')
    op.drop_index('ix_ledger_customer_created', table_name='ledger_entries')
    op.drop_table('ledger_entries')
    op.drop_table('tenants')
    op.drop_index(op.f('ix_stock_movements_tenant_id'), table_name='stock_movements')
    op.drop_index('ix_stock_mov_tenant_created', table_name='stock_movements')
    op.drop_index('ix_stock_mov_product', table_name='stock_movements')
    op.drop_table('stock_movements')
    op.drop_index('ix_tier_tenant_name', table_name='price_tiers')
    op.drop_index(op.f('ix_price_tiers_tenant_id'), table_name='price_tiers')
    op.drop_table('price_tiers')
    op.drop_index('ix_login_attempts_identifier', table_name='login_attempts')
    op.drop_table('login_attempts')
    op.drop_index(op.f('ix_customers_tenant_id'), table_name='customers')
    op.drop_index('ix_customers_tenant_code', table_name='customers')
    op.drop_table('customers')
    op.drop_index('ix_categories_tenant_name', table_name='categories')
    op.drop_index(op.f('ix_categories_tenant_id'), table_name='categories')
    op.drop_table('categories')
    op.drop_index('ix_audit_tenant_created', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_tenant_id'), table_name='audit_logs')
    op.drop_index('ix_audit_actor', table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('ix_alerts_tenant_dismissed', table_name='ai_alerts')
    op.drop_index('ix_alerts_tenant_created', table_name='ai_alerts')
    op.drop_table('ai_alerts')
