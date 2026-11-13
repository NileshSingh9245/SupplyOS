"""Real PostgreSQL schema regressions, opted in explicitly and always disposable."""
from __future__ import annotations

import logging
import os
from argparse import Namespace
import secrets
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from psycopg2 import sql

from app.core.config import get_settings
from app.infrastructure.db.base import Base
from app.infrastructure.db import models  # noqa: F401

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def isolated_urls():
    if os.environ.get("SUPPLYOS_LOCAL_POSTGRES_TESTS") == "1" and sys.platform == "win32":
        from tools.local_postgres import LocalPostgres
        with LocalPostgres() as pg:
            yield pg.sync_url, pg.async_url
        return
    if os.environ.get("SUPPLYOS_POSTGRES_MIGRATION_TESTS") != "1":
        pytest.skip("Opt in to an identified PostgreSQL migration test service")
    value = os.environ.get("TEST_DATABASE_URL_SYNC", "")
    if not value:
        pytest.fail("TEST_DATABASE_URL_SYNC is required for isolated migration databases", pytrace=False)
    url = make_url(value)
    if (
        url.drivername not in {"postgresql", "postgresql+psycopg2"}
        or url.host not in {"127.0.0.1", "localhost", "::1"}
        or not (url.database or "").startswith("supplyos_test_")
    ):
        pytest.fail("Migration tests require an explicitly identified loopback test database", pytrace=False)
    database_name = "supplyos_test_migration_" + uuid.uuid4().hex
    admin = create_engine(url)
    created = False
    try:
        raw = admin.raw_connection()
        try:
            raw.driver_connection.autocommit = True
            with raw.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
            created = True
        finally:
            raw.close()
        sync_url = url.set(database=database_name, drivername="postgresql+psycopg2")
        async_query = dict(sync_url.query)
        if "sslmode" in async_query:
            async_query["ssl"] = async_query.pop("sslmode")
        async_url = sync_url.set(drivername="postgresql+asyncpg", query=async_query)
        yield sync_url.render_as_string(hide_password=False), async_url.render_as_string(hide_password=False)
    finally:
        if created:
            raw = admin.raw_connection()
            try:
                raw.driver_connection.autocommit = True
                with raw.cursor() as cursor:
                    cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
            finally:
                raw.close()
        admin.dispose()


@pytest.fixture
def database(monkeypatch):
    with isolated_urls() as (sync_url, async_url):
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("DATABASE_URL_SYNC", sync_url)
        monkeypatch.setenv("DATABASE_URL", async_url)
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(48))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        get_settings.cache_clear()
        engine = create_engine(sync_url)
        try:
            yield engine, Config(str(BACKEND_ROOT / "alembic.ini"))
        finally:
            engine.dispose()
            get_settings.cache_clear()


def _create_frozen_legacy_schema(config):
    # Historical startup predates auth session columns in the current models.
    command.upgrade(config, "20261108_0001")
    command.stamp(config, "base")


def test_fresh_database_migrates_to_matching_models(database):
    engine, config = database
    transport_log = logging.getLogger("app.infrastructure.external.smtp")
    command.upgrade(config, "head")
    assert transport_log.disabled is False
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        if differences:
            pytest.fail("Migration schema differs from the application models", pytrace=False)
        assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names())
        from server import require_current_schema
        require_current_schema(connection)


def test_matching_legacy_schema_is_preserved(database):
    engine, config = database
    _create_frozen_legacy_schema(config)
    marker_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(Base.metadata.tables["tenants"].insert().values(
            id=marker_id, name="Preserved verification tenant", currency="INR",
            is_setup_complete=True, settings={},
        ))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        name = connection.execute(
            Base.metadata.tables["tenants"].select().where(
                Base.metadata.tables["tenants"].c.id == marker_id
            )
        ).mappings().one()["name"]
        assert name == "Preserved verification tenant"
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_mismatched_legacy_schema_is_not_stamped(database):
    engine, config = database
    _create_frozen_legacy_schema(config)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE tenants ALTER COLUMN name TYPE TEXT"))
    with pytest.raises(RuntimeError, match="Legacy column type mismatch"):
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert "20261108_0001" not in MigrationContext.configure(connection).get_current_heads()


def test_disposable_schema_can_downgrade_and_upgrade(database):
    engine, config = database
    command.upgrade(config, "head")
    config.cmd_opts = Namespace(x=["allow_destructive_downgrade=1"])
    command.downgrade(config, "3a7b2a03cd3b")
    with engine.connect() as connection:
        assert not set(Base.metadata.tables) & set(inspect(connection).get_table_names())
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_startup_does_not_create_an_unmigrated_schema(database):
    engine, _ = database
    from server import require_current_schema
    with engine.connect() as connection:
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            require_current_schema(connection)
        assert not set(Base.metadata.tables) & set(inspect(connection).get_table_names())


def test_unexpected_legacy_columns_are_not_adopted(database):
    engine, config = database
    _create_frozen_legacy_schema(config)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE tenants ADD COLUMN unexpected_required TEXT NOT NULL"))
    with pytest.raises(RuntimeError, match="Legacy column set mismatch"):
        command.upgrade(config, "head")
    with engine.connect() as connection:
        assert "20261108_0001" not in MigrationContext.configure(connection).get_current_heads()


def test_partial_unique_index_is_not_adopted_as_unconditional(database):
    engine, config = database
    _create_frozen_legacy_schema(config)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_products_tenant_sku"))
        connection.execute(text(
            "CREATE UNIQUE INDEX ix_products_tenant_sku ON products (tenant_id, sku) WHERE is_active"
        ))
    with pytest.raises(RuntimeError, match="Legacy index mismatch"):
        command.upgrade(config, "head")


def test_downgrade_refuses_to_delete_adopted_legacy_data_without_opt_in(database):
    engine, config = database
    _create_frozen_legacy_schema(config)
    marker_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(Base.metadata.tables["tenants"].insert().values(
            id=marker_id, name="Rollback must preserve this tenant", currency="INR",
            is_setup_complete=True, settings={},
        ))
    command.upgrade(config, "head")
    with pytest.raises(RuntimeError, match="including adopted legacy tables"):
        command.downgrade(config, "3a7b2a03cd3b")
    with engine.connect() as connection:
        assert connection.execute(
            Base.metadata.tables["tenants"].select().where(
                Base.metadata.tables["tenants"].c.id == marker_id
            )
        ).mappings().one()["name"] == "Rollback must preserve this tenant"
