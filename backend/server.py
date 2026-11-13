"""Main FastAPI application entrypoint.

Loaded by uvicorn from the supervisor: `uvicorn server:app --host 0.0.0.0 --port 8001`.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.engine import Connection

from app.api.v1 import api_v1  # noqa: E402
from app.core.browser_security import BrowserSecurityMiddleware, normalize_trusted_origins
from app.core.config import get_settings  # noqa: E402
from app.features.proofs.middleware import ProofBodyLimit
from app.features.auth.recovery import PasswordRecovery, RecoveryCapacityRelease
from app.features.tenants.security import SetupAuthorizationMiddleware
from app.core.database import engine  # noqa: E402
from app.infrastructure.db.base import Base
from app.infrastructure.db import models as _models  # noqa: F401,E402 register models

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("supplyos")


def require_current_schema(connection: Connection) -> None:
    scripts = ScriptDirectory.from_config(Config(str(Path(__file__).parent / "alembic.ini")))
    applied = set(MigrationContext.configure(connection).get_current_heads())
    inspector = inspect(connection)
    if applied != set(scripts.get_heads()) or set(Base.metadata.tables) - set(inspector.get_table_names()):
        raise RuntimeError("Database schema is not current. Run 'alembic upgrade head' first.")
    for table in Base.metadata.sorted_tables:
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        if set(table.columns.keys()) - columns:
            raise RuntimeError("Database columns are not current. Run 'alembic upgrade head' first.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.connect() as conn:
            await conn.run_sync(require_current_schema)
        log.info("Migration schema verified. Booting %s (%s)", settings.app_name, settings.app_env)
        yield
    finally:
        app.state.password_recovery.close()
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Smart Supply Chain OS API",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# Browser trust is explicit and shared with CORS; invalid/wildcard configuration fails startup.
allow_origins = normalize_trusted_origins(settings.cors_origins)
app.add_middleware(ProofBodyLimit, prefixes=tuple(set(["/api", "/api/v1", settings.api_v1_prefix])))
app.add_middleware(RecoveryCapacityRelease)
app.add_middleware(
    SetupAuthorizationMiddleware, settings=settings,
    prefixes=tuple(set(["/api", "/api/v1", settings.api_v1_prefix])),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)
app.add_middleware(
    BrowserSecurityMiddleware,
    trusted_origins=allow_origins,
    hsts=settings.app_env in {"staging", "production"},
)
app.state.password_recovery = PasswordRecovery(settings)


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/api/health/deep")
async def deep_health():
    from app.core.database import AsyncSessionLocal
    from app.core.redis_client import redis_client

    async def check_database():
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))

    result = {"database": "unavailable", "redis": "unavailable"}
    try:
        await asyncio.wait_for(check_database(), timeout=3)
        result["database"] = "ok"
    except Exception as exc:
        log.warning("Database health check failed (%s)", type(exc).__name__)
    try:
        if await asyncio.wait_for(redis_client.ping(), timeout=3):
            result["redis"] = "ok"
    except Exception as exc:
        log.warning("Redis health check failed (%s)", type(exc).__name__)
    if any(status != "ok" for status in result.values()):
        return JSONResponse(status_code=503, content=result)
    return result


# Mount versioned API
app.include_router(api_v1, prefix=settings.api_v1_prefix)


# Legacy /api compatibility — mirror v1 without prefix stripping for smooth migration
# (Keeps supervisor's /api → 8001 routing valid regardless of client version.)
app.include_router(api_v1, prefix="/api")
