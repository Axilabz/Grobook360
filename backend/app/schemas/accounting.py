"""Accounting Posting Matrix & Journal Engine schemas (PROMPT-025)."""

from pydantic import BaseModel


class JournalLineItem(BaseModel):
    id: str
    account_id: str
    account_code: str
    account_name: str
    debit_amount: str
    credit_amount: str
    description: str | None


class JournalListItem(BaseModel):
    id: str
    journal_number: str
    journal_date: str
    posting_date: str
    source_type: str
    source_id: str
    source_number: str | None
    posting_event_type: str
    description: str | None
    status: str
    reversal_of_journal_id: str | None
    total_debit: str
    total_credit: str
    created_by: str | None
    created_at: str
    updated_at: str
    row_version: int


class JournalDetail(JournalListItem):
    currency: str
    lines: list[JournalLineItem]


class JournalReverseRequest(BaseModel):
    pass


class ChartOfAccountItem(BaseModel):
    id: str
    code: str
    name: str
    account_type: str
    is_active: bool
    is_system_default: bool


class AccountMappingItem(BaseModel):
    posting_rule_code: str
    account_id: str
    account_code: str
    account_name: str


class PostingRuleItem(BaseModel):
    code: str
    description: str
