"""Company Profile — extend `tenant` with the remaining fields the frontend's
Company Profile screen (`ViewCompany.tsx`) always displayed.

Revision ID: 0033_tenant_profile_fields
Revises: 0032_invoice_template_config
Create Date: 2026-10-22

Proposed schema addition (the usual "propose, document, implement" pattern
for a gap against the Data Dictionary — see CLAUDE.md §3): the baseline
`tenant` table has no PAN, business type, phone/email/website, or bank
detail columns at all. `ViewCompany.tsx` previously showed these as
entirely hardcoded, unsaved mock data; migration 0033 is the backend half
of wiring that screen to real per-tenant data (the frontend half replaces
the "coming soon"-disabled fields with real ones).

- `pan`/`business_type`/`phone`/`email`/`website`: organization-level
  contact/registration fields, nullable (a tenant signing up today has
  none of these yet — PROMPT-002's sign-up flow only captures
  business_name/GSTIN/address).
- `bank_*`: a single primary bank account for the organization (the one
  printed on invoices, e.g. `InvoiceTemplateConfiguration`'s own
  `bank_name`/`bank_account_name`/`bank_account_number`/`bank_ifsc`/
  `bank_upi_id` fields, migration 0032 — this is deliberately a SEPARATE
  set of columns on `tenant` itself, not a dependency on that
  invoice-template row: a tenant's registered bank details and the bank
  details shown on invoices are two different concerns that happen to
  default from the same real-world bank account, consistent with this
  codebase's "don't couple two unrelated concepts just because they'd
  usually agree" discipline).
- `bank_account_type`: free text here (not a CHECK-constrained enum) —
  no approved account-type taxonomy exists; mirrors `salary_component`'s
  own free-text-over-premature-enum precedent elsewhere in this codebase.

No RLS change needed — `tenant` itself was never RLS-protected (it's the
tenant-isolation ROOT, not a tenant-scoped table), matching migration
0001's own scoping decision.
"""

from alembic import op
import sqlalchemy as sa

revision = "0033_tenant_profile_fields"
down_revision = "0032_invoice_template_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenant", sa.Column("pan", sa.CHAR(10), nullable=True))
    op.add_column("tenant", sa.Column("business_type", sa.String(50), nullable=True))
    op.add_column("tenant", sa.Column("phone", sa.CHAR(10), nullable=True))
    op.add_column("tenant", sa.Column("email", sa.String(255), nullable=True))
    op.add_column("tenant", sa.Column("website", sa.String(255), nullable=True))
    op.add_column("tenant", sa.Column("bank_name", sa.String(100), nullable=True))
    op.add_column("tenant", sa.Column("bank_account_number", sa.String(30), nullable=True))
    op.add_column("tenant", sa.Column("bank_account_holder_name", sa.String(200), nullable=True))
    op.add_column("tenant", sa.Column("bank_ifsc", sa.CHAR(11), nullable=True))
    op.add_column("tenant", sa.Column("bank_branch_name", sa.String(100), nullable=True))
    op.add_column("tenant", sa.Column("bank_account_type", sa.String(20), nullable=True))
    op.add_column("tenant", sa.Column("bank_upi_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant", "bank_upi_id")
    op.drop_column("tenant", "bank_account_type")
    op.drop_column("tenant", "bank_branch_name")
    op.drop_column("tenant", "bank_ifsc")
    op.drop_column("tenant", "bank_account_holder_name")
    op.drop_column("tenant", "bank_account_number")
    op.drop_column("tenant", "bank_name")
    op.drop_column("tenant", "website")
    op.drop_column("tenant", "email")
    op.drop_column("tenant", "phone")
    op.drop_column("tenant", "business_type")
    op.drop_column("tenant", "pan")
