"""Unit of Measure service (PROMPT-009).

Minimal list/create surface — no update/delete in this MVP (open decision,
see PROMPT-009-NOTES.md). A unit, once referenced by a product or
conversion, should not silently change meaning underneath them.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import PROD_DUPLICATE_UOM_CODE
from app.core.exceptions import ConflictError
from app.models.unit_of_measure import UnitOfMeasure
from app.services.audit.audit_service import AuditService


class UnitOfMeasureService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_units(self, *, tenant_id: uuid.UUID) -> list[UnitOfMeasure]:
        result = await self._session.execute(
            select(UnitOfMeasure).where(UnitOfMeasure.tenant_id == tenant_id).order_by(UnitOfMeasure.code)
        )
        return list(result.scalars().all())

    async def create_unit(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        code: str,
        name: str,
        precision: int,
        ip_address: str | None,
    ) -> UnitOfMeasure:
        existing = await self._session.execute(
            select(UnitOfMeasure).where(UnitOfMeasure.tenant_id == tenant_id, UnitOfMeasure.code == code)
        )
        if existing.scalars().first() is not None:
            raise ConflictError("A unit with this code already exists.", code=PROD_DUPLICATE_UOM_CODE)

        unit = UnitOfMeasure(
            tenant_id=tenant_id,
            code=code,
            name=name,
            precision=precision,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(unit)
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="UNIT_OF_MEASURE_CREATED",
            entity_type="unit_of_measure",
            entity_id=unit.id,
            after={"code": code, "name": name, "precision": precision},
            ip_address=ip_address,
        )
        return unit
