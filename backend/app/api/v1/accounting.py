"""Accounting Posting Matrix & Journal Engine endpoints (PROMPT-025 §45).

Deliberately narrow: journals are only ever CREATED internally by a
business transaction's own posting rule (§45's own explicit
instruction — "Do NOT allow ordinary users to arbitrarily create
balanced journals through a generic endpoint unless manual journals are
explicitly approved"). Manual Journal Entry is NOT approved for M1
(§56 OD-017) — no POST /journals (create) endpoint exists here.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.accounting_constants import POSTING_RULE_CODES
from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.exceptions import AuthorizationError
from app.core.permissions import (
    ACCOUNTING_MANAGE_ACCOUNT_MAPPINGS,
    ACCOUNTING_REVERSE_JOURNAL,
    ACCOUNTING_VIEW_CHART_OF_ACCOUNTS,
    ACCOUNTING_VIEW_JOURNALS,
)
from app.db.session import get_db_session
from app.models.chart_of_account import ChartOfAccount
from app.models.journal_entry import JournalEntry
from app.models.journal_line import JournalLine
from app.schemas.accounting import (
    AccountMappingItem,
    ChartOfAccountItem,
    JournalDetail,
    JournalLineItem,
    JournalListItem,
    PostingRuleItem,
)
from app.schemas.envelopes import Pagination
from app.services.accounting.chart_of_accounts_service import ChartOfAccountsService
from app.services.accounting.journal_service import JournalService

router = APIRouter(prefix="/accounting", tags=["accounting"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


def _to_list_item(journal: JournalEntry, total_debit: Decimal, total_credit: Decimal) -> JournalListItem:
    return JournalListItem(
        id=str(journal.id), journal_number=journal.journal_number, journal_date=journal.journal_date.isoformat(),
        posting_date=journal.posting_date.isoformat(), source_type=journal.source_type, source_id=str(journal.source_id),
        source_number=journal.source_number, posting_event_type=journal.posting_event_type, description=journal.description,
        status=journal.status, reversal_of_journal_id=str(journal.reversal_of_journal_id) if journal.reversal_of_journal_id else None,
        total_debit=str(total_debit), total_credit=str(total_credit),
        created_by=str(journal.created_by) if journal.created_by else None,
        created_at=journal.created_at.isoformat(), updated_at=journal.updated_at.isoformat(), row_version=journal.row_version,
    )


def _to_line_item(line: JournalLine, account: ChartOfAccount) -> JournalLineItem:
    return JournalLineItem(
        id=str(line.id), account_id=str(account.id), account_code=account.code, account_name=account.name,
        debit_amount=str(line.debit_amount), credit_amount=str(line.credit_amount), description=line.description,
    )


@router.get("/journals")
async def list_journals(
    page: int = 1, page_size: int = 25, source_type: str | None = None, status: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
    context: AuthenticatedContext = Depends(require_permission(ACCOUNTING_VIEW_JOURNALS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    service = JournalService(session)
    journals, total_items = await service.list_journals(
        tenant_id=tenant_id, page=page, page_size=page_size, source_type=source_type, status_filter=status,
        date_from=date_from, date_to=date_to,
    )

    items = []
    for journal in journals:
        lines = await service.get_lines(journal.id)
        total_debit = sum((line.debit_amount for line, _acct in lines), Decimal("0"))
        total_credit = sum((line.credit_amount for line, _acct in lines), Decimal("0"))
        items.append(_to_list_item(journal, total_debit, total_credit).model_dump())

    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    return {
        "data": items,
        "pagination": Pagination(page=page, page_size=page_size, total_items=total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/journals/{journal_id}")
async def get_journal(
    journal_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(ACCOUNTING_VIEW_JOURNALS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = JournalService(session)
    result = await service.get_journal(tenant_id=tenant_id, journal_id=journal_id)
    total_debit = sum((line.debit_amount for line, _acct in result.lines), Decimal("0"))
    total_credit = sum((line.credit_amount for line, _acct in result.lines), Decimal("0"))
    detail = JournalDetail(
        **_to_list_item(result.journal, total_debit, total_credit).model_dump(), currency=result.journal.currency,
        lines=[_to_line_item(line, account) for line, account in result.lines],
    )
    return {"data": detail.model_dump(), "meta": _meta()}


@router.get("/journals/{journal_id}/lines")
async def get_journal_lines(
    journal_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(ACCOUNTING_VIEW_JOURNALS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = JournalService(session)
    result = await service.get_journal(tenant_id=tenant_id, journal_id=journal_id)
    return {"data": [_to_line_item(line, account).model_dump() for line, account in result.lines], "meta": _meta()}


@router.post("/journals/{journal_id}/reverse")
async def reverse_journal(
    journal_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(ACCOUNTING_REVERSE_JOURNAL)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = JournalService(session)
    reversal = await service.reverse_journal(tenant_id=tenant_id, actor_user_id=context.user_id, journal_id=journal_id, ip_address=None)
    await session.commit()
    result = await service.get_journal(tenant_id=tenant_id, journal_id=reversal.id)
    total_debit = sum((line.debit_amount for line, _acct in result.lines), Decimal("0"))
    total_credit = sum((line.credit_amount for line, _acct in result.lines), Decimal("0"))
    detail = JournalDetail(
        **_to_list_item(result.journal, total_debit, total_credit).model_dump(), currency=result.journal.currency,
        lines=[_to_line_item(line, account) for line, account in result.lines],
    )
    return {"data": detail.model_dump(), "meta": _meta()}


@router.get("/accounts")
async def list_accounts(
    context: AuthenticatedContext = Depends(require_permission(ACCOUNTING_VIEW_CHART_OF_ACCOUNTS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    coa = ChartOfAccountsService(session)
    await coa.ensure_default_chart_of_accounts(tenant_id)
    await session.commit()
    accounts = await coa.list_accounts(tenant_id=tenant_id)
    items = [
        ChartOfAccountItem(id=str(a.id), code=a.code, name=a.name, account_type=a.account_type, is_active=a.is_active, is_system_default=a.is_system_default).model_dump()
        for a in accounts
    ]
    return {"data": items, "meta": _meta()}


@router.get("/account-mappings")
async def list_account_mappings(
    context: AuthenticatedContext = Depends(require_permission(ACCOUNTING_MANAGE_ACCOUNT_MAPPINGS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    coa = ChartOfAccountsService(session)
    await coa.ensure_default_chart_of_accounts(tenant_id)
    await session.commit()
    mappings = await coa.list_mappings(tenant_id=tenant_id)
    items = [
        AccountMappingItem(posting_rule_code=m.posting_rule_code, account_id=str(a.id), account_code=a.code, account_name=a.name).model_dump()
        for m, a in mappings
    ]
    return {"data": items, "meta": _meta()}


@router.get("/posting-rules")
async def list_posting_rules(
    context: AuthenticatedContext = Depends(require_permission(ACCOUNTING_VIEW_JOURNALS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    items = [PostingRuleItem(code=code, description=code.replace("_", " ").title()).model_dump() for code in sorted(POSTING_RULE_CODES)]
    return {"data": items, "meta": _meta()}
