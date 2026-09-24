"""Accounting reports — General Ledger, Trial Balance, Profit & Loss,
Balance Sheet (PROMPT-027 §33-§38).

Built entirely on top of POSTED `journal_line`/`journal_entry` rows —
never recalculates accounting logic (§2's mandatory "reports must not
become a second source of truth" principle). Date basis is
`journal_entry.posting_date` throughout (§45's own explicit mandate,
not `created_at`).

Normal-balance convention (standard double-entry accounting, not a
judgment call): ASSET/EXPENSE/COGS accounts have a DEBIT normal balance
(increase with a debit); LIABILITY/EQUITY/REVENUE accounts have a
CREDIT normal balance. Every calculation below is expressed in terms of
this convention.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.accounting_constants import ASSET, COGS, EQUITY, EXPENSE, JNL_POSTED, LIABILITY, REVENUE
from app.models.chart_of_account import ChartOfAccount
from app.models.journal_entry import JournalEntry
from app.models.journal_line import JournalLine

_ZERO = Decimal("0")
_DEBIT_NORMAL = frozenset({ASSET, EXPENSE, COGS})


@dataclass(frozen=True)
class LedgerEntry:
    journal_date: date
    journal_number: str
    source_type: str
    source_id: str
    source_number: str | None
    description: str | None
    debit: Decimal
    credit: Decimal
    running_balance: Decimal


@dataclass(frozen=True)
class AccountBalance:
    account_id: str
    account_code: str
    account_name: str
    account_type: str
    debit_total: Decimal
    credit_total: Decimal

    @property
    def net_debit_normal(self) -> Decimal:
        """Balance expressed as a signed debit-normal figure (positive
        means a debit balance) — the single number every report derives
        its own debit/credit-column presentation from."""
        net = self.debit_total - self.credit_total
        return net if self.account_type in _DEBIT_NORMAL else -net


class AccountingReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared aggregation core ---------------------------------------

    async def _account_balances(
        self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None, account_types: frozenset[str] | None = None,
    ) -> list[AccountBalance]:
        # Two chained outer joins would NOT correctly exclude a
        # JournalLine row when only the SECOND join (to JournalEntry,
        # carrying the status/date filter) fails to match — the first
        # join (JournalLine to ChartOfAccount) already succeeded, and a
        # later failed outer join never retroactively nulls an earlier
        # one's matched row. So the status/date-filtered line totals are
        # pre-aggregated in a subquery FIRST (a plain INNER JOIN + WHERE,
        # unambiguous), and ChartOfAccount is then left-joined to THAT —
        # this is what correctly returns a zero balance (not an
        # accidentally-unfiltered one) for an account with no qualifying
        # activity in the requested range.
        line_totals_conditions = [JournalLine.tenant_id == tenant_id, JournalEntry.status == JNL_POSTED]
        if date_from is not None:
            line_totals_conditions.append(JournalEntry.posting_date >= date_from)
        if date_to is not None:
            line_totals_conditions.append(JournalEntry.posting_date <= date_to)

        line_totals = (
            select(
                JournalLine.account_id.label("account_id"),
                func.sum(JournalLine.debit_amount).label("debit_total"),
                func.sum(JournalLine.credit_amount).label("credit_total"),
            )
            .select_from(JournalLine)
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
            .where(*line_totals_conditions)
            .group_by(JournalLine.account_id)
            .subquery()
        )

        stmt = (
            select(
                ChartOfAccount.id, ChartOfAccount.code, ChartOfAccount.name, ChartOfAccount.account_type,
                func.coalesce(line_totals.c.debit_total, _ZERO), func.coalesce(line_totals.c.credit_total, _ZERO),
            )
            .select_from(ChartOfAccount)
            .outerjoin(line_totals, line_totals.c.account_id == ChartOfAccount.id)
            .where(ChartOfAccount.tenant_id == tenant_id)
        )
        if account_types:
            stmt = stmt.where(ChartOfAccount.account_type.in_(account_types))
        stmt = stmt.order_by(ChartOfAccount.code)

        rows = (await self._session.execute(stmt)).all()
        return [
            AccountBalance(account_id=str(r[0]), account_code=r[1], account_name=r[2], account_type=r[3], debit_total=r[4] or _ZERO, credit_total=r[5] or _ZERO)
            for r in rows
        ]

    # --- General Ledger (§33/§34) ---------------------------------------

    async def get_general_ledger(
        self, *, tenant_id: uuid.UUID, account_id: uuid.UUID, date_from: date | None, date_to: date | None,
    ) -> tuple[ChartOfAccount, Decimal, list[LedgerEntry]]:
        account_result = await self._session.execute(select(ChartOfAccount).where(ChartOfAccount.id == account_id, ChartOfAccount.tenant_id == tenant_id))
        account = account_result.scalar_one()

        opening_balance = _ZERO
        if date_from is not None:
            opening_stmt = (
                select(func.coalesce(func.sum(JournalLine.debit_amount), _ZERO), func.coalesce(func.sum(JournalLine.credit_amount), _ZERO))
                .select_from(JournalLine)
                .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
                .where(
                    JournalLine.tenant_id == tenant_id, JournalLine.account_id == account_id,
                    JournalEntry.status == JNL_POSTED, JournalEntry.posting_date < date_from,
                )
            )
            opening_debit, opening_credit = (await self._session.execute(opening_stmt)).one()
            net = opening_debit - opening_credit
            opening_balance = net if account.account_type in _DEBIT_NORMAL else -net

        stmt = (
            select(JournalLine, JournalEntry)
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
            .where(JournalLine.tenant_id == tenant_id, JournalLine.account_id == account_id, JournalEntry.status == JNL_POSTED)
        )
        if date_from is not None:
            stmt = stmt.where(JournalEntry.posting_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(JournalEntry.posting_date <= date_to)
        stmt = stmt.order_by(JournalEntry.posting_date, JournalEntry.created_at)

        rows = (await self._session.execute(stmt)).all()
        running = opening_balance
        entries: list[LedgerEntry] = []
        for line, journal in rows:
            delta = (line.debit_amount - line.credit_amount) if account.account_type in _DEBIT_NORMAL else (line.credit_amount - line.debit_amount)
            running += delta
            entries.append(
                LedgerEntry(
                    journal_date=journal.posting_date, journal_number=journal.journal_number, source_type=journal.source_type,
                    source_id=str(journal.source_id), source_number=journal.source_number, description=journal.description,
                    debit=line.debit_amount, credit=line.credit_amount, running_balance=running,
                )
            )
        return account, opening_balance, entries

    # --- Trial Balance (§35) ---------------------------------------------

    async def get_trial_balance(self, *, tenant_id: uuid.UUID, date_to: date | None) -> tuple[list[AccountBalance], Decimal, Decimal, bool]:
        balances = await self._account_balances(tenant_id=tenant_id, date_from=None, date_to=date_to)
        total_debit = sum((b.debit_total for b in balances), _ZERO)
        total_credit = sum((b.credit_total for b in balances), _ZERO)
        is_balanced = total_debit == total_credit
        return balances, total_debit, total_credit, is_balanced

    # --- Profit & Loss (§36) ----------------------------------------------

    async def get_profit_and_loss(self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None) -> dict:
        revenue_accounts = await self._account_balances(tenant_id=tenant_id, date_from=date_from, date_to=date_to, account_types=frozenset({REVENUE}))
        cogs_accounts = await self._account_balances(tenant_id=tenant_id, date_from=date_from, date_to=date_to, account_types=frozenset({COGS}))
        expense_accounts = await self._account_balances(tenant_id=tenant_id, date_from=date_from, date_to=date_to, account_types=frozenset({EXPENSE}))

        total_revenue = sum((a.net_debit_normal for a in revenue_accounts), _ZERO)
        total_cogs = sum((a.net_debit_normal for a in cogs_accounts), _ZERO)
        gross_profit = total_revenue - total_cogs
        total_expenses = sum((a.net_debit_normal for a in expense_accounts), _ZERO)
        net_profit = gross_profit - total_expenses

        return {
            "revenue_accounts": revenue_accounts, "total_revenue": total_revenue,
            "cogs_accounts": cogs_accounts, "total_cogs": total_cogs, "gross_profit": gross_profit,
            "expense_accounts": expense_accounts, "total_expenses": total_expenses, "net_profit": net_profit,
        }

    # --- Balance Sheet (§37/§38) -------------------------------------------

    async def get_balance_sheet(self, *, tenant_id: uuid.UUID, as_of_date: date | None) -> dict:
        asset_accounts = await self._account_balances(tenant_id=tenant_id, date_from=None, date_to=as_of_date, account_types=frozenset({ASSET}))
        liability_accounts = await self._account_balances(tenant_id=tenant_id, date_from=None, date_to=as_of_date, account_types=frozenset({LIABILITY}))
        equity_accounts = await self._account_balances(tenant_id=tenant_id, date_from=None, date_to=as_of_date, account_types=frozenset({EQUITY}))

        total_assets = sum((a.net_debit_normal for a in asset_accounts), _ZERO)
        total_liabilities = sum((a.net_debit_normal for a in liability_accounts), _ZERO)
        total_equity_posted = sum((a.net_debit_normal for a in equity_accounts), _ZERO)

        # §37: "Retained Earnings / Current Period Result where
        # applicable" — no equity/capital account is seeded by default
        # (PROMPT-025's DEFAULT_ACCOUNT_SEED has none), so the ONLY
        # equity this MVP can show is the current period's own P&L
        # result, computed from the SAME posted journal lines (not a
        # plug — see module docstring: Assets = Liabilities + Equity +
        # NetProfit is a mathematical identity of double-entry
        # bookkeeping, not an assumption).
        pl = await self.get_profit_and_loss(tenant_id=tenant_id, date_from=None, date_to=as_of_date)
        current_period_earnings = pl["net_profit"]
        total_equity = total_equity_posted + current_period_earnings

        difference = total_assets - (total_liabilities + total_equity)
        is_balanced = difference == _ZERO

        return {
            "asset_accounts": asset_accounts, "total_assets": total_assets,
            "liability_accounts": liability_accounts, "total_liabilities": total_liabilities,
            "equity_accounts": equity_accounts, "total_equity_posted": total_equity_posted,
            "current_period_earnings": current_period_earnings, "total_equity": total_equity,
            "is_balanced": is_balanced, "difference": difference,
        }
