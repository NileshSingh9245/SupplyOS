"""Main FastAPI application entrypoint.

Loaded by uvicorn from the supervisor: `uvicorn server:app --host 0.0.0.0 --port 8001`.
"""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.api.v1 import api_v1  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, engine  # noqa: E402
from app.infrastructure.db.models import *  # noqa: F401,F403,E402  # register all models

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("supplyos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup for dev; production uses Alembic explicitly.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database schema ensured. Booting %s (%s)", settings.app_name, settings.app_env)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Smart Supply Chain OS — production-grade API",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS
allow_origins = ["*"] if settings.frontend_url == "*" else [settings.frontend_url]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=(settings.frontend_url != "*"),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/api/health/deep")
async def deep_health():
    from app.core.database import AsyncSessionLocal
    from app.core.redis_client import redis_client

    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
    pong = await redis_client.ping()
    return {"database": "ok", "redis": "ok" if pong else "fail"}


# Mount versioned API
app.include_router(api_v1, prefix=settings.api_v1_prefix)


# Legacy /api compatibility — mirror v1 without prefix stripping for smooth migration
# (Keeps supervisor's /api → 8001 routing valid regardless of client version.)
app.include_router(api_v1, prefix="/api")
