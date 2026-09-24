"""Journal Engine (PROMPT-025 §4-§8, §32-§43) — the centralized posting
service every business-transaction posting rule calls through. No
module implements its own accounting logic (§4); they all build a list
of `JournalLineInput` (posting_rule_code + amount) and hand it to
`post_journal`, which resolves accounts, validates the debit=credit
balance (§8), checks the accounting period (§35), and atomically
creates the `JournalEntry`/`JournalLine` rows (§42).

Idempotency (§32): `(tenant_id, source_type, source_id, posting_event_type)`
is unique at the DB level. `post_journal` checks for an existing journal
first (cheap, avoids the round-trip through an IntegrityError in the
common case) and ALSO catches `IntegrityError` on insert (the race-safe
backstop — mirrors `DocumentNumberingService`'s own retry-on-conflict
precedent) so two concurrent postings of the same source can never
create two journals (§43/TC-027/TC-028).

Reversal (§33): a brand-new journal with swapped debit/credit lines,
`posting_event_type=REVERSAL`, `reversal_of_journal_id` set — the
original's own lines/amounts are NEVER touched, only its `status`
transitions POSTED -> REVERSED.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.accounting_constants import (
    EVT_ORIGINAL,
    EVT_REVERSAL,
    JNL_POSTED,
    JNL_REVERSED,
    JOURNAL,
)
from app.core.error_codes import (
    ACC_JOURNAL_NOT_FOUND,
    ACC_JOURNAL_UNBALANCED,
    ACC_NOT_REVERSIBLE,
    ACC_PERIOD_CLOSED,
    ACC_REVERSAL_ALREADY_EXISTS,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.accounting_period import CLOSED, OPEN, AccountingPeriod
from app.models.chart_of_account import ChartOfAccount
from app.models.journal_entry import JournalEntry
from app.models.journal_line import JournalLine
from app.models.tenant import Tenant
from app.services.accounting.chart_of_accounts_service import ChartOfAccountsService
from app.services.audit.audit_service import AuditService
from app.services.sales.document_numbering_service import DocumentNumberingService, get_financial_year_label


@dataclass(frozen=True)
class JournalLineInput:
    posting_rule_code: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    description: str | None = None


@dataclass(frozen=True)
class JournalWithLines:
    journal: JournalEntry
    lines: list[tuple[JournalLine, ChartOfAccount]]


class JournalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _ensure_open_period(self, *, tenant: Tenant, as_of: date) -> None:
        """§35: posting guard only — no close/reopen workflow exists in
        this prompt (OD-018/OD-019). A period row is lazily created OPEN
        the first time it's needed for that financial year."""
        label = get_financial_year_label(tenant, as_of)
        result = await self._session.execute(
            select(AccountingPeriod).where(AccountingPeriod.tenant_id == tenant.id, AccountingPeriod.financial_year_label == label)
        )
        period = result.scalar_one_or_none()
        if period is None:
            try:
                async with self._session.begin_nested():
                    period = AccountingPeriod(tenant_id=tenant.id, financial_year_label=label, status=OPEN)
                    self._session.add(period)
                    await self._session.flush()
            except IntegrityError:
                # Another concurrent request created it first — retry the
                # SELECT to pick up the row it made (mirrors
                # DocumentNumberingService's own SAVEPOINT-retry precedent;
                # a bare session.rollback() here would discard the whole
                # outer request transaction, not just this insert attempt).
                result = await self._session.execute(
                    select(AccountingPeriod).where(AccountingPeriod.tenant_id == tenant.id, AccountingPeriod.financial_year_label == label)
                )
                period = result.scalar_one()
        if period.status == CLOSED:
            raise ValidationAppError(f"Accounting period {label} is closed for posting.", code=ACC_PERIOD_CLOSED)

    async def _existing_journal(
        self, *, tenant_id: uuid.UUID, source_type: str, source_id: uuid.UUID, posting_event_type: str
    ) -> JournalEntry | None:
        result = await self._session.execute(
            select(JournalEntry).where(
                JournalEntry.tenant_id == tenant_id, JournalEntry.source_type == source_type,
                JournalEntry.source_id == source_id, JournalEntry.posting_event_type == posting_event_type,
            )
        )
        return result.scalar_one_or_none()

    # --- post (§4-§8, §11-§21, §42) -----------------------------------------

    async def post_journal(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_type: str, source_id: uuid.UUID,
        source_number: str | None, journal_date: date, description: str | None, lines: list[JournalLineInput],
        ip_address: str | None,
    ) -> JournalEntry:
        # §32 idempotency: a duplicate posting attempt for the same
        # source returns the ALREADY-created journal, never a second one.
        existing = await self._existing_journal(tenant_id=tenant_id, source_type=source_type, source_id=source_id, posting_event_type=EVT_ORIGINAL)
        if existing is not None:
            return existing

        journal = await self._create_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=source_type, source_id=source_id,
            source_number=source_number, journal_date=journal_date, description=description, lines=lines,
            posting_event_type=EVT_ORIGINAL, ip_address=ip_address,
        )
        return journal

    async def _create_journal(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_type: str, source_id: uuid.UUID,
        source_number: str | None, journal_date: date, description: str | None, lines: list[JournalLineInput],
        posting_event_type: str, ip_address: str | None, reversal_of_journal_id: uuid.UUID | None = None,
    ) -> JournalEntry:
        total_debit = sum((line.debit for line in lines), Decimal("0"))
        total_credit = sum((line.credit for line in lines), Decimal("0"))
        if total_debit != total_credit:
            raise ValidationAppError(
                f"Journal is unbalanced: total debit {total_debit} != total credit {total_credit}.", code=ACC_JOURNAL_UNBALANCED
            )
        if total_debit <= 0:
            raise ValidationAppError("A journal must have a positive, non-zero total.", code=ACC_JOURNAL_UNBALANCED)

        tenant = await self._get_tenant(tenant_id)
        await self._ensure_open_period(tenant=tenant, as_of=journal_date)

        coa = ChartOfAccountsService(self._session)
        await coa.ensure_default_chart_of_accounts(tenant_id)

        numbering = DocumentNumberingService(self._session)
        journal_number = await numbering.next_number(tenant=tenant, document_type=JOURNAL, prefix="JRN")

        journal = JournalEntry(
            tenant_id=tenant_id, journal_number=journal_number, journal_date=journal_date, posting_date=date.today(),
            source_type=source_type, source_id=source_id, source_number=source_number, posting_event_type=posting_event_type,
            description=description, status=JNL_POSTED, reversal_of_journal_id=reversal_of_journal_id,
            created_by=actor_user_id, updated_by=actor_user_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(journal)
                await self._session.flush()

                for line in lines:
                    if (line.debit > 0) == (line.credit > 0):
                        raise ValidationAppError(
                            "Each journal line must have either a debit or a credit amount, never both.", code=ACC_JOURNAL_UNBALANCED
                        )
                    account = await coa.resolve_account(tenant_id=tenant_id, posting_rule_code=line.posting_rule_code)
                    self._session.add(
                        JournalLine(
                            tenant_id=tenant_id, journal_id=journal.id, account_id=account.id, debit_amount=line.debit,
                            credit_amount=line.credit, description=line.description, created_by=actor_user_id, updated_by=actor_user_id,
                        )
                    )
                await self._session.flush()
        except IntegrityError:
            # §43: a concurrent request won the unique-constraint race —
            # re-query and return the journal it created instead of
            # raising or creating a duplicate.
            existing = await self._existing_journal(tenant_id=tenant_id, source_type=source_type, source_id=source_id, posting_event_type=posting_event_type)
            if existing is not None:
                return existing
            raise

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id,
            action="JOURNAL_REVERSED" if posting_event_type == EVT_REVERSAL else "JOURNAL_POSTED",
            entity_type="journal_entry", entity_id=journal.id,
            after={
                "journal_number": journal_number, "source_type": source_type, "source_id": str(source_id),
                "total_debit": str(total_debit), "total_credit": str(total_credit),
            },
            ip_address=ip_address,
        )
        return journal

    # --- reverse (§33/§34/§45) ----------------------------------------------

    async def reverse_journal(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, journal_id: uuid.UUID, ip_address: str | None,
    ) -> JournalEntry:
        result = await self._session.execute(
            select(JournalEntry).where(JournalEntry.id == journal_id, JournalEntry.tenant_id == tenant_id).with_for_update()
        )
        journal = result.scalar_one_or_none()
        if journal is None:
            raise NotFoundError("Journal not found", code=ACC_JOURNAL_NOT_FOUND)
        return await self._reverse_journal_row(tenant_id=tenant_id, actor_user_id=actor_user_id, journal=journal, ip_address=ip_address)

    async def reverse_journal_for_source(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_type: str, source_id: uuid.UUID, ip_address: str | None,
    ) -> JournalEntry | None:
        """Convenience wrapper for business-module cancel/reverse flows
        (Purchase Invoice cancellation, Purchase Return cancellation,
        Payment reversal/cheque-bounce) that know the SOURCE document,
        not the journal id. Returns None if no ORIGINAL journal exists
        for this source (e.g. accounting posting failed silently upstream
        — should not happen in practice, but this stays a safe no-op
        rather than raising, since the source's own reversal must still
        proceed)."""
        original = await self._existing_journal(tenant_id=tenant_id, source_type=source_type, source_id=source_id, posting_event_type=EVT_ORIGINAL)
        if original is None:
            return None
        result = await self._session.execute(select(JournalEntry).where(JournalEntry.id == original.id).with_for_update())
        journal = result.scalar_one()
        return await self._reverse_journal_row(tenant_id=tenant_id, actor_user_id=actor_user_id, journal=journal, ip_address=ip_address)

    async def _reverse_journal_row(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, journal: JournalEntry, ip_address: str | None,
    ) -> JournalEntry:
        if journal.status != JNL_POSTED:
            if journal.status == JNL_REVERSED:
                raise ValidationAppError("This journal has already been reversed.", code=ACC_REVERSAL_ALREADY_EXISTS)
            raise ValidationAppError(f"Cannot reverse a journal in {journal.status} status.", code=ACC_NOT_REVERSIBLE)

        existing_reversal = await self._existing_journal(
            tenant_id=tenant_id, source_type=journal.source_type, source_id=journal.source_id, posting_event_type=EVT_REVERSAL
        )
        if existing_reversal is not None:
            raise ValidationAppError("A reversal journal already exists for this source document.", code=ACC_REVERSAL_ALREADY_EXISTS)

        original_lines = await self._get_lines(journal.id)
        reversal_lines = [
            JournalLineInput(
                posting_rule_code=await self._posting_rule_code_for_account(tenant_id, line.account_id),
                debit=line.credit_amount, credit=line.debit_amount, description=line.description,
            )
            for line, _account in original_lines
        ]

        reversal_journal = await self._create_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=journal.source_type, source_id=journal.source_id,
            source_number=journal.source_number, journal_date=date.today(), description=f"Reversal of {journal.journal_number}",
            lines=reversal_lines, posting_event_type=EVT_REVERSAL, ip_address=ip_address, reversal_of_journal_id=journal.id,
        )

        previous_status = journal.status
        journal.status = JNL_REVERSED
        journal.updated_by = actor_user_id
        journal.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="JOURNAL_REVERSED",
            entity_type="journal_entry", entity_id=journal.id, before={"status": previous_status},
            after={"status": JNL_REVERSED, "reversal_journal_id": str(reversal_journal.id)}, ip_address=ip_address,
        )
        return reversal_journal

    async def _posting_rule_code_for_account(self, tenant_id: uuid.UUID, account_id: uuid.UUID) -> str:
        """Reversal lines must still resolve through a posting_rule_code
        (never a raw account id) to keep `_create_journal`'s single
        account-resolution code path — looks up whichever mapping
        currently points at this account."""
        from app.models.account_mapping import AccountMapping

        result = await self._session.execute(
            select(AccountMapping.posting_rule_code).where(AccountMapping.tenant_id == tenant_id, AccountMapping.account_id == account_id).limit(1)
        )
        code = result.scalar_one_or_none()
        if code is None:
            raise ValidationAppError("Cannot resolve the posting rule for a reversed account — mapping may have changed.", code=ACC_JOURNAL_UNBALANCED)
        return code

    # --- queries (§45/§49/§50) ----------------------------------------------

    async def get_lines(self, journal_id: uuid.UUID) -> list[tuple[JournalLine, ChartOfAccount]]:
        return await self._get_lines(journal_id)

    async def _get_lines(self, journal_id: uuid.UUID) -> list[tuple[JournalLine, ChartOfAccount]]:
        result = await self._session.execute(
            select(JournalLine, ChartOfAccount)
            .join(ChartOfAccount, ChartOfAccount.id == JournalLine.account_id)
            .where(JournalLine.journal_id == journal_id)
            .order_by(JournalLine.created_at)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_journal(self, *, tenant_id: uuid.UUID, journal_id: uuid.UUID) -> JournalWithLines:
        result = await self._session.execute(select(JournalEntry).where(JournalEntry.id == journal_id, JournalEntry.tenant_id == tenant_id))
        journal = result.scalar_one_or_none()
        if journal is None:
            raise NotFoundError("Journal not found", code=ACC_JOURNAL_NOT_FOUND)
        lines = await self._get_lines(journal.id)
        return JournalWithLines(journal=journal, lines=lines)

    async def list_journals(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, source_type: str | None, status_filter: str | None,
        date_from: date | None, date_to: date | None,
    ) -> tuple[list[JournalEntry], int]:
        base = select(JournalEntry).where(JournalEntry.tenant_id == tenant_id)
        if source_type:
            base = base.where(JournalEntry.source_type == source_type)
        if status_filter:
            base = base.where(JournalEntry.status == status_filter)
        if date_from:
            base = base.where(JournalEntry.journal_date >= date_from)
        if date_to:
            base = base.where(JournalEntry.journal_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(JournalEntry.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(JournalEntry.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).scalars().all()
        return list(rows), total_items
