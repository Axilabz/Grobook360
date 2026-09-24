"""Generic tenant-scoped repository base.

Future module repositories inherit this so tenant filtering is never
hand-rolled per-query. This is the application-level line of defense; PostgreSQL
RLS (app.db.tenant_context) is the second line of defense — the frontend is never
treated as a security boundary (PROMPT-001 S5).
"""

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class TenantScopedRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._session = session
        self._tenant_id = tenant_id

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelT | None:
        stmt = select(self.model).where(
            self.model.id == entity_id,
            self.model.tenant_id == self._tenant_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
