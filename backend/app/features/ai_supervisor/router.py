"""AI supervisor API — trigger analyses, list alerts, dismiss."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.core.enums import AlertCategory, AlertSeverity
from app.core.exceptions import NotFound
from app.features.ai_supervisor import service as ai_service
from app.infrastructure.db.models.ai_alert import AIAlert
from app.shared.deps import get_current_user, require_staff
from app.shared.schemas import ORMModel

router = APIRouter(prefix="/ai", tags=["ai_supervisor"])


class AlertOut(ORMModel):
    id: uuid.UUID
    category: str
    severity: str
    title: str
    message: str
    action_hint: str | None
    resource_type: str | None
    resource_id: str | None
    meta: dict | None
    is_dismissed: bool
    created_at: datetime


class AnalyzeResult(BaseModel):
    counts: dict[str, int]


class PeakHourResponse(BaseModel):
    buckets: list[dict[str, Any]]


@router.get("/alerts", response_model=list[AlertOut])
async def list_alerts(
    category: AlertCategory | None = None,
    severity: AlertSeverity | None = None,
    include_dismissed: bool = False,
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    stmt = select(AIAlert).where(AIAlert.tenant_id == user.tenant_id)
    if category:
        stmt = stmt.where(AIAlert.category == category.value)
    if severity:
        stmt = stmt.where(AIAlert.severity == severity.value)
    if not include_dismissed:
        stmt = stmt.where(AIAlert.is_dismissed == False)  # noqa
    stmt = stmt.order_by(AIAlert.created_at.desc()).limit(limit)
    return (await db.execute(stmt)).scalars().all()


@router.post("/alerts/{alert_id}/dismiss", response_model=AlertOut)
async def dismiss(
    alert_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(require_staff)
):
    from datetime import datetime, timezone
    a = (await db.execute(
        select(AIAlert).where(AIAlert.id == alert_id, AIAlert.tenant_id == user.tenant_id)
    )).scalar_one_or_none()
    if not a:
        raise NotFound("Alert not found")
    a.is_dismissed = True
    a.dismissed_at = datetime.now(timezone.utc)
    a.dismissed_by = user.id
    await db.commit()
    await db.refresh(a)
    return a


@router.post("/analyze", response_model=AnalyzeResult)
async def run_analyze(
    db: AsyncSession = Depends(get_db), user=Depends(require_staff),
    background_tasks: BackgroundTasks = None,
    include_summary: bool = False,
):
    counts = await ai_service.run_all_analyses(db, user.tenant_id)
    if include_summary:
        # Run summarization in the background so response is fast
        tenant_id = user.tenant_id

        async def _bg():
            async with AsyncSessionLocal() as s:
                await ai_service.claude_summarize(s, tenant_id)

        if background_tasks:
            background_tasks.add_task(_bg)
    return AnalyzeResult(counts=counts)


@router.get("/insights/peak-hours", response_model=PeakHourResponse)
async def peak_hours(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    result = await ai_service.peak_hour_summary(db, user.tenant_id)
    return PeakHourResponse(**result)
