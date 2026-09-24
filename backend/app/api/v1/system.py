"""System/foundation routes: health, version. No business endpoints in PROMPT-001."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.db.session import get_db_session

router = APIRouter(tags=["system"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


@router.get("/health")
async def health() -> dict:
    return {"data": {"status": "ok"}, "meta": _meta()}


@router.get("/health/db")
async def health_db(session: AsyncSession = Depends(get_db_session)) -> dict:
    await session.execute(text("SELECT 1"))
    return {"data": {"status": "ok", "database": "connected"}, "meta": _meta()}


@router.get("/version")
async def version() -> dict:
    return {"data": {"api_version": "v1"}, "meta": _meta()}
