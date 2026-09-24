"""Chart of Accounts + Account Mapping service (PROMPT-025 §9/§10).

Lazy per-tenant provisioning — the same "ensure default X exists"
pattern `InventoryService.ensure_default_location()` established
(PROMPT-010). The seeded set (`app.core.accounting_constants.
DEFAULT_ACCOUNT_SEED`) is an explicit DEFAULT, not an approved final
Chart of Accounts (§56 OD-001/OD-002).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.accounting_constants import DEFAULT_ACCOUNT_SEED
from app.core.error_codes import ACC_ACCOUNT_MAPPING_MISSING, ACC_ACCOUNT_NOT_FOUND
from app.core.exceptions import ValidationAppError
from app.models.account_mapping import AccountMapping
from app.models.chart_of_account import ChartOfAccount


class ChartOfAccountsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_default_chart_of_accounts(self, tenant_id: uuid.UUID) -> None:
        """Idempotent: if this tenant already has any mapping rows,
        assumes the COA/mapping set was already seeded and does nothing
        — so a tenant that later edits/removes a mapping is never
        silently re-seeded over."""
        existing = await self._session.execute(select(AccountMapping.id).where(AccountMapping.tenant_id == tenant_id).limit(1))
        if existing.scalar_one_or_none() is not None:
            return

        try:
            async with self._session.begin_nested():
                accounts_by_rule: dict[str, ChartOfAccount] = {}
                for rule_code, (code, name, account_type) in DEFAULT_ACCOUNT_SEED.items():
                    account = ChartOfAccount(
                        tenant_id=tenant_id, code=code, name=name, account_type=account_type, is_active=True, is_system_default=True,
                    )
                    self._session.add(account)
                    accounts_by_rule[rule_code] = account
                await self._session.flush()

                for rule_code, account in accounts_by_rule.items():
                    self._session.add(AccountMapping(tenant_id=tenant_id, posting_rule_code=rule_code, account_id=account.id))
                await self._session.flush()
        except IntegrityError:
            # Concurrent seeding by another request — the other one won,
            # nothing more to do here.
            pass

    async def resolve_account(self, *, tenant_id: uuid.UUID, posting_rule_code: str) -> ChartOfAccount:
        result = await self._session.execute(
            select(AccountMapping, ChartOfAccount)
            .join(ChartOfAccount, ChartOfAccount.id == AccountMapping.account_id)
            .where(AccountMapping.tenant_id == tenant_id, AccountMapping.posting_rule_code == posting_rule_code)
        )
        row = result.first()
        if row is None:
            raise ValidationAppError(
                f"No account mapping configured for posting rule '{posting_rule_code}'.", code=ACC_ACCOUNT_MAPPING_MISSING
            )
        _mapping, account = row
        if not account.is_active:
            raise ValidationAppError(f"The account mapped to '{posting_rule_code}' is inactive.", code=ACC_ACCOUNT_NOT_FOUND)
        return account

    async def list_accounts(self, *, tenant_id: uuid.UUID) -> list[ChartOfAccount]:
        result = await self._session.execute(
            select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id).order_by(ChartOfAccount.code)
        )
        return list(result.scalars().all())

    async def list_mappings(self, *, tenant_id: uuid.UUID) -> list[tuple[AccountMapping, ChartOfAccount]]:
        result = await self._session.execute(
            select(AccountMapping, ChartOfAccount)
            .join(ChartOfAccount, ChartOfAccount.id == AccountMapping.account_id)
            .where(AccountMapping.tenant_id == tenant_id)
            .order_by(AccountMapping.posting_rule_code)
        )
        return [(row[0], row[1]) for row in result.all()]
