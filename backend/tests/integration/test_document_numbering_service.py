"""PROMPT-011 tests for DocumentNumberingService."""

import asyncio
from datetime import date

from app.models.tenant import Tenant
from app.services.sales.document_numbering_service import (
    DocumentNumberingService,
    get_financial_year_label,
)


def _make_tenant(name: str, fy_start_month: int = 4) -> Tenant:
    return Tenant(business_name=name, financial_year_start_month=fy_start_month)


async def test_financial_year_label_after_fy_start(db_session):
    tenant = _make_tenant("FY Test Co", fy_start_month=4)
    assert get_financial_year_label(tenant, as_of=date(2026, 6, 15)) == "2026-27"


async def test_financial_year_label_before_fy_start(db_session):
    tenant = _make_tenant("FY Test Co 2", fy_start_month=4)
    assert get_financial_year_label(tenant, as_of=date(2026, 2, 15)) == "2025-26"


async def test_next_number_increments_sequentially(db_session):
    tenant = _make_tenant("Numbering Test Co")
    db_session.add(tenant)
    await db_session.flush()

    service = DocumentNumberingService(db_session)
    first = await service.next_number(tenant=tenant, document_type="SALES_INVOICE", prefix="INV", as_of=date(2026, 6, 1))
    second = await service.next_number(tenant=tenant, document_type="SALES_INVOICE", prefix="INV", as_of=date(2026, 6, 2))

    assert first == "INV-2026-27-0001"
    assert second == "INV-2026-27-0002"


async def test_next_number_scoped_per_document_type(db_session):
    tenant = _make_tenant("Numbering Test Co 2")
    db_session.add(tenant)
    await db_session.flush()

    service = DocumentNumberingService(db_session)
    invoice_number = await service.next_number(tenant=tenant, document_type="SALES_INVOICE", prefix="INV", as_of=date(2026, 6, 1))
    challan_number = await service.next_number(tenant=tenant, document_type="DELIVERY_CHALLAN", prefix="DC", as_of=date(2026, 6, 1))

    assert invoice_number == "INV-2026-27-0001"
    assert challan_number == "DC-2026-27-0001"  # independent sequence, not sharing the counter


async def test_next_number_resets_per_financial_year(db_session):
    tenant = _make_tenant("Numbering Test Co 3")
    db_session.add(tenant)
    await db_session.flush()

    service = DocumentNumberingService(db_session)
    fy26 = await service.next_number(tenant=tenant, document_type="SALES_INVOICE", prefix="INV", as_of=date(2026, 3, 1))
    fy27 = await service.next_number(tenant=tenant, document_type="SALES_INVOICE", prefix="INV", as_of=date(2026, 4, 1))

    assert fy26 == "INV-2025-26-0001"
    assert fy27 == "INV-2026-27-0001"  # new FY, sequence restarts


async def test_next_number_scoped_per_tenant(db_session):
    tenant_a = _make_tenant("Numbering Tenant A")
    tenant_b = _make_tenant("Numbering Tenant B")
    # Phase 1C: a tenant row is only insertable under its own tenant context,
    # so each tenant is flushed separately (the session follows the tenant being added).
    db_session.add(tenant_a)
    await db_session.flush()
    db_session.add(tenant_b)
    await db_session.flush()

    service = DocumentNumberingService(db_session)
    a_number = await service.next_number(tenant=tenant_a, document_type="SALES_INVOICE", prefix="INV", as_of=date(2026, 6, 1))
    b_number = await service.next_number(tenant=tenant_b, document_type="SALES_INVOICE", prefix="INV", as_of=date(2026, 6, 1))

    assert a_number == "INV-2026-27-0001"
    assert b_number == "INV-2026-27-0001"  # independent tenant scope, not a shared global counter


async def test_next_number_concurrent_calls_produce_unique_numbers(db_session):
    from app.db.session import AsyncSessionLocal

    tenant = _make_tenant("Numbering Concurrency Co")
    db_session.add(tenant)
    await db_session.commit()

    from app.db.tenant_context import set_tenant_context

    tenant_id = tenant.id  # captured while still loaded (see commit() below)

    async def _allocate() -> str:
        async with AsyncSessionLocal() as session:
            await set_tenant_context(session, tenant_id)
            service = DocumentNumberingService(session)
            number = await service.next_number(
                tenant=tenant, document_type="SALES_INVOICE", prefix="INV", as_of=date(2026, 6, 1)
            )
            await session.commit()
            return number

    numbers = await asyncio.gather(_allocate(), _allocate(), _allocate())
    assert len(set(numbers)) == 3  # no duplicate allocated despite concurrent requests
