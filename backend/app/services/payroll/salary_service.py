"""Salary Component catalogue + Salary Structure service (PROMPT-029
§8-§12).

`ensure_default_components` mirrors `ChartOfAccountsService.ensure_
default_chart_of_accounts`'s own lazy per-tenant seeding precedent
(PROMPT-025) exactly.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import PAYROLL_SALARY_STRUCTURE_INVALID
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.payroll_constants import DEFAULT_SALARY_COMPONENT_SEED
from app.models.salary_component import CALCULATION_TYPES, SalaryComponent
from app.models.salary_structure import SalaryStructure
from app.models.salary_structure_line import SalaryStructureLine
from app.services.audit.audit_service import AuditService
from app.services.payroll.payroll_calculation_service import StructureLineInput


class SalaryComponentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_default_components(self, tenant_id: uuid.UUID) -> None:
        existing = await self._session.execute(select(SalaryComponent.id).where(SalaryComponent.tenant_id == tenant_id).limit(1))
        if existing.scalar_one_or_none() is not None:
            return
        for code, (name, component_type, calc_type) in DEFAULT_SALARY_COMPONENT_SEED.items():
            self._session.add(
                SalaryComponent(tenant_id=tenant_id, code=code, name=name, component_type=component_type, default_calculation_type=calc_type, is_active=True)
            )
        await self._session.flush()

    async def list_components(self, tenant_id: uuid.UUID) -> list[SalaryComponent]:
        await self.ensure_default_components(tenant_id)
        result = await self._session.execute(select(SalaryComponent).where(SalaryComponent.tenant_id == tenant_id).order_by(SalaryComponent.code))
        return list(result.scalars().all())

    async def get_component(self, tenant_id: uuid.UUID, component_id: uuid.UUID) -> SalaryComponent:
        result = await self._session.execute(select(SalaryComponent).where(SalaryComponent.id == component_id, SalaryComponent.tenant_id == tenant_id))
        component = result.scalar_one_or_none()
        if component is None:
            raise NotFoundError("Salary component not found", code=PAYROLL_SALARY_STRUCTURE_INVALID)
        return component


class SalaryStructureLineInputDTO:
    def __init__(self, *, component_id: uuid.UUID, calculation_type: str, amount, percentage, percentage_of_component_code: str | None):
        self.component_id = component_id
        self.calculation_type = calculation_type
        self.amount = amount
        self.percentage = percentage
        self.percentage_of_component_code = percentage_of_component_code


class SalaryStructureService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_structures(self, tenant_id: uuid.UUID, employee_id: uuid.UUID) -> list[SalaryStructure]:
        result = await self._session.execute(
            select(SalaryStructure).where(SalaryStructure.tenant_id == tenant_id, SalaryStructure.employee_id == employee_id)
            .order_by(SalaryStructure.effective_from.desc())
        )
        return list(result.scalars().all())

    async def get_structure(self, tenant_id: uuid.UUID, structure_id: uuid.UUID) -> SalaryStructure:
        result = await self._session.execute(select(SalaryStructure).where(SalaryStructure.id == structure_id, SalaryStructure.tenant_id == tenant_id))
        structure = result.scalar_one_or_none()
        if structure is None:
            raise NotFoundError("Salary structure not found", code=PAYROLL_SALARY_STRUCTURE_INVALID)
        return structure

    async def get_lines(self, structure_id: uuid.UUID) -> list[tuple[SalaryStructureLine, SalaryComponent]]:
        result = await self._session.execute(
            select(SalaryStructureLine, SalaryComponent)
            .join(SalaryComponent, SalaryComponent.id == SalaryStructureLine.component_id)
            .where(SalaryStructureLine.salary_structure_id == structure_id)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_effective_structure(self, tenant_id: uuid.UUID, employee_id: uuid.UUID, as_of: date) -> SalaryStructure | None:
        """§11/§12: the structure applicable for `as_of` is the one with
        the LATEST `effective_from` <= `as_of` — never a live/mutable
        join, and never affected by a structure created AFTER `as_of`
        (§11's own "historical payroll must not change" guarantee)."""
        result = await self._session.execute(
            select(SalaryStructure)
            .where(SalaryStructure.tenant_id == tenant_id, SalaryStructure.employee_id == employee_id, SalaryStructure.effective_from <= as_of)
            .order_by(SalaryStructure.effective_from.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_structure(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, employee_id: uuid.UUID, effective_from: date,
        lines: list[SalaryStructureLineInputDTO], ip_address: str | None,
    ) -> SalaryStructure:
        if not lines:
            raise ValidationAppError("A salary structure must have at least one component line.", code=PAYROLL_SALARY_STRUCTURE_INVALID)

        components_by_id: dict[uuid.UUID, SalaryComponent] = {}
        for line in lines:
            if line.calculation_type not in CALCULATION_TYPES:
                raise ValidationAppError(f"Invalid calculation_type '{line.calculation_type}'.", code=PAYROLL_SALARY_STRUCTURE_INVALID)
            component = await SalaryComponentService(self._session).get_component(tenant_id, line.component_id)
            components_by_id[line.component_id] = component
            if line.calculation_type == "FIXED_AMOUNT" and (line.amount is None or line.amount < 0):
                raise ValidationAppError("A FIXED_AMOUNT line requires a non-negative amount.", code=PAYROLL_SALARY_STRUCTURE_INVALID)
            if line.calculation_type == "PERCENTAGE" and (line.percentage is None or not line.percentage_of_component_code):
                raise ValidationAppError("A PERCENTAGE line requires both percentage and percentage_of_component_code.", code=PAYROLL_SALARY_STRUCTURE_INVALID)

        structure = SalaryStructure(tenant_id=tenant_id, employee_id=employee_id, effective_from=effective_from, created_by=actor_user_id, updated_by=actor_user_id)
        self._session.add(structure)
        await self._session.flush()

        for line in lines:
            component = components_by_id[line.component_id]
            self._session.add(
                SalaryStructureLine(
                    tenant_id=tenant_id, salary_structure_id=structure.id, component_id=component.id, calculation_type=line.calculation_type,
                    amount=line.amount or 0, percentage=line.percentage, percentage_of_component_code=line.percentage_of_component_code,
                    created_by=actor_user_id, updated_by=actor_user_id,
                )
            )
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="SALARY_STRUCTURE_CREATED",
            entity_type="salary_structure", entity_id=structure.id,
            after={"employee_id": str(employee_id), "effective_from": effective_from.isoformat(), "line_count": len(lines)},
            ip_address=ip_address,
        )
        return structure

    async def to_calculation_inputs(self, structure_id: uuid.UUID) -> list[StructureLineInput]:
        rows = await self.get_lines(structure_id)
        return [
            StructureLineInput(
                component_id=line.component_id, code=component.code, name=component.name, component_type=component.component_type,
                calculation_type=line.calculation_type, amount=line.amount, percentage=line.percentage,
                percentage_of_component_code=line.percentage_of_component_code,
            )
            for line, component in rows
        ]
