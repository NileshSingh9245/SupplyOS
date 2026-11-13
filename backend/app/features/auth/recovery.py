"""Bounded, post-response best-effort recovery; no durable or plaintext-token outbox."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from threading import BoundedSemaphore
from typing import Callable, Literal

from fastapi import BackgroundTasks
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import Settings
from app.core.database import AsyncSessionLocal
from app.core.redis_client import redis_client
from app.features.auth import repositories, service
from app.infrastructure.external.smtp import SMTPPasswordResetSender

log = logging.getLogger(__name__)
_SLOT_SCOPE_KEY = "supplyos.password_reset_slot"

# One atomic fixed window for every identity, including nonexistent accounts. Shared hash tag
# also keeps these keys in one Redis Cluster slot; only HMAC digests enter the cache.
_ADMIT_SCRIPT = """
redis.call('SET', KEYS[1], '0', 'EX', ARGV[1], 'NX')
local ip_count = redis.call('INCR', KEYS[1])
if ip_count > tonumber(ARGV[2]) then
    return {0, math.max(redis.call('TTL', KEYS[1]), 1)}
end
redis.call('SET', KEYS[2], '0', 'EX', ARGV[1], 'NX')
local identity_count = redis.call('INCR', KEYS[2])
if identity_count > tonumber(ARGV[3]) then
    return {0, math.max(redis.call('TTL', KEYS[2]), 1)}
end
if redis.call('SET', KEYS[3], '1', 'EX', ARGV[4], 'NX') then return {1, 0} end
return {0, math.max(redis.call('TTL', KEYS[3]), 1)}
"""


@dataclass(frozen=True, slots=True)
class RecoveryAdmission:
    state: Literal["accepted", "limited", "unavailable"]
    retry_after: int | None = None


@dataclass(frozen=True, slots=True)
class _ResetRequest:
    email: str = field(repr=False)
    tenant_id: uuid.UUID | None = field(repr=False)


@dataclass(slots=True)
class _RecoverySlot:
    capacity: BoundedSemaphore = field(repr=False)
    released: bool = False

    def release(self) -> None:
        if not self.released:
            self.released = True
            self.capacity.release()


class RecoveryCapacityRelease:
    """Release admission even if ASGI response sending aborts before background work."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await self.app(scope, receive, send)
        finally:
            slot = scope.pop(_SLOT_SCOPE_KEY, None)
            if isinstance(slot, _RecoverySlot):
                slot.release()


class PasswordRecovery:
    def __init__(
        self, settings: Settings, *, cache: Redis = redis_client,
        session_factory: Callable[[], AsyncSession] = AsyncSessionLocal,
        sender: SMTPPasswordResetSender | None = None,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._session_factory = session_factory
        self._sender = sender if sender is not None else SMTPPasswordResetSender(settings)
        self._slots = BoundedSemaphore(settings.password_reset_capacity)
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def _rate_key(self, kind: str, value: str) -> str:
        digest = hmac.new(
            self._settings.jwt_secret.encode(),
            b"supplyos/password-reset/rate/v1\0" + kind.encode() + b"\0" + value.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"supplyos:auth:password-reset:{{v1}}:{kind}:{digest}"

    async def enqueue(
        self, *, email: str, tenant_id: uuid.UUID | None, client_host: str | None,
        background_tasks: BackgroundTasks, scope: Scope | None = None,
    ) -> RecoveryAdmission:
        if self._closed or not self._settings.can_send_password_reset or not self._slots.acquire(False):
            return RecoveryAdmission("unavailable")
        slot = _RecoverySlot(self._slots)
        queued = False
        try:
            if scope is not None:
                scope[_SLOT_SCOPE_KEY] = slot
            try:
                peer = ip_address(client_host or "").compressed
            except ValueError:
                return RecoveryAdmission("unavailable")
            request = _ResetRequest(email.lower().strip(), tenant_id)
            admission = await self._admit(request.email, peer)
            if self._closed:
                return RecoveryAdmission("unavailable")
            if admission.state == "accepted":
                background_tasks.add_task(self._deliver, request, slot)
                queued = True
            return admission
        except Exception:
            # Fail closed before issuance, without exposing cache replies or request data.
            log.warning("Password reset admission failed (limiter_unavailable)")
            return RecoveryAdmission("unavailable")
        finally:
            if not queued:
                slot.release()

    async def _admit(self, email: str, peer: str) -> RecoveryAdmission:
        allowed = await asyncio.wait_for(self._cache.eval(
            _ADMIT_SCRIPT, 3, self._rate_key("ip", peer), self._rate_key("identity", email),
            self._rate_key("cooldown", email), self._settings.password_reset_window_seconds,
            self._settings.password_reset_max_requests_per_ip,
            self._settings.password_reset_max_requests_per_identity,
            self._settings.password_reset_cooldown_seconds,
        ), timeout=self._settings.password_reset_rate_limit_timeout_seconds)
        if (
            not isinstance(allowed, (list, tuple)) or len(allowed) != 2
            or any(type(value) is not int for value in allowed)
        ):
            return RecoveryAdmission("unavailable")
        decision, retry_after = allowed
        if decision == 1 and retry_after == 0:
            return RecoveryAdmission("accepted")
        if decision == 0 and 1 <= retry_after <= self._settings.password_reset_window_seconds:
            return RecoveryAdmission("limited", retry_after=retry_after)
        return RecoveryAdmission("unavailable")

    async def _prepare(self, request: _ResetRequest) -> tuple[str, str] | None:
        async with self._session_factory() as db:
            token = await service.create_password_reset(db, request.email, request.tenant_id)
            if token is None:
                return None
            async with db.begin():
                recipient = await repositories.password_reset_recipient(
                    db, digest=hashlib.sha256(token.encode()).hexdigest(), email=request.email,
                    tenant_id=request.tenant_id, now=datetime.now(timezone.utc),
                )
            return (recipient, token) if recipient is not None else None

    async def _deliver(self, request: _ResetRequest, slot: _RecoverySlot) -> None:
        try:
            if self._closed or slot.released:
                return
            prepared = await asyncio.wait_for(
                self._prepare(request), timeout=self._settings.password_reset_work_timeout_seconds,
            )
            if prepared is not None and not self._closed:
                recipient, token = prepared
                await self._sender.send(recipient=recipient, token=token)
        except Exception:
            # No retry/cleanup can accidentally invalidate a newer committed reset.
            log.warning("Password reset background work failed (recovery)")
        finally:
            slot.release()
