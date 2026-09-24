"""GST reporting aggregation, GSTR-1/GSTR-3B preparation, pre-submission
validation and reconciliation (PROMPT-026 §27-§34).

Everything here is COMPUTED ON DEMAND from the already-recorded
`gst_transaction`/`gst_transaction_line` rows (`gst_reporting_service.py`)
— no editable/persisted "GST Return" entity exists (§31: no direct GST
portal submission is implemented in M1 — OD-010/OD-011 — so there is
nothing to legitimately mark SUBMITTED; a return's "status" is always
computed fresh: PREPARED, or VALIDATED/VALIDATION_FAILED after
`validate_*` is called). Values are never manually editable (§28's own
explicit instruction) since they are always re-derived from posted
transactions.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.accounting_constants import (
    INPUT_CGST,
    INPUT_IGST,
    INPUT_SGST,
    OUTPUT_CGST,
    OUTPUT_IGST,
    OUTPUT_SGST,
    SRC_CREDIT_NOTE,
    SRC_DEBIT_NOTE,
    SRC_PURCHASE_INVOICE,
    SRC_PURCHASE_RETURN,
    SRC_SALES_INVOICE,
    SRC_SALES_RETURN,
)
from app.core.gst_constants import B2B, B2C, INWARD, OUTWARD
from app.models.account_mapping import AccountMapping
from app.models.chart_of_account import ChartOfAccount
from app.models.gst_transaction import GstTransaction
from app.models.gst_transaction_line import GstTransactionLine
from app.models.journal_entry import JournalEntry
from app.models.journal_line import JournalLine
from app.services.gst.gst_validation_service import (
    ERROR,
    WARNING,
    ValidationIssue,
    is_valid_gstin_format,
)

_ZERO = Decimal("0")


def _sum(rows, attr) -> Decimal:
    return sum((getattr(r, attr) for r in rows), _ZERO)


@dataclass(frozen=True)
class GstTotals:
    taxable_value: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    cess: Decimal
    total_gst: Decimal

    @staticmethod
    def zero() -> "GstTotals":
        return GstTotals(_ZERO, _ZERO, _ZERO, _ZERO, _ZERO, _ZERO)


class GstrService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- raw transaction access (§36 GST Transaction list) ------------------

    async def list_transactions(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, return_period: str | None, source_type: str | None,
        classification: str | None, party_gstin: str | None, direction: str | None,
    ) -> tuple[list[GstTransaction], int]:
        base = select(GstTransaction).where(GstTransaction.tenant_id == tenant_id)
        if return_period:
            base = base.where(GstTransaction.return_period == return_period)
        if source_type:
            base = base.where(GstTransaction.source_type == source_type)
        if classification:
            base = base.where(GstTransaction.classification == classification)
        if party_gstin:
            base = base.where(GstTransaction.party_gstin == party_gstin)
        if direction:
            base = base.where(GstTransaction.direction == direction)

        count_stmt = select(func.count()).select_from(base.with_only_columns(GstTransaction.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(GstTransaction.document_date.desc(), GstTransaction.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).scalars().all()
        return list(rows), total_items

    async def get_transaction(self, *, tenant_id: uuid.UUID, transaction_id: uuid.UUID) -> tuple[GstTransaction | None, list[GstTransactionLine]]:
        result = await self._session.execute(
            select(GstTransaction).where(GstTransaction.id == transaction_id, GstTransaction.tenant_id == tenant_id)
        )
        transaction = result.scalar_one_or_none()
        if transaction is None:
            return None, []
        lines_result = await self._session.execute(
            select(GstTransactionLine).where(GstTransactionLine.gst_transaction_id == transaction.id).order_by(GstTransactionLine.line_no)
        )
        return transaction, list(lines_result.scalars().all())

    async def _period_transactions(self, *, tenant_id: uuid.UUID, return_period: str, direction: str | None = None) -> list[GstTransaction]:
        stmt = select(GstTransaction).where(GstTransaction.tenant_id == tenant_id, GstTransaction.return_period == return_period)
        if direction:
            stmt = stmt.where(GstTransaction.direction == direction)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # --- GSTR-1 (§28) --------------------------------------------------------

    async def gstr1_dataset(self, *, tenant_id: uuid.UUID, return_period: str) -> dict:
        outward = await self._period_transactions(tenant_id=tenant_id, return_period=return_period, direction=OUTWARD)

        def bucket(source_types: set[str], classification: str | None = None) -> tuple[list[GstTransaction], GstTotals]:
            rows = [t for t in outward if t.source_type in source_types and (classification is None or t.classification == classification)]
            totals = GstTotals(_sum(rows, "taxable_value"), _sum(rows, "cgst_amount"), _sum(rows, "sgst_amount"), _sum(rows, "igst_amount"), _sum(rows, "cess_amount"), _sum(rows, "total_gst"))
            return rows, totals

        b2b_rows, b2b_totals = bucket({SRC_SALES_INVOICE}, B2B)
        b2c_rows, b2c_totals = bucket({SRC_SALES_INVOICE}, B2C)
        credit_note_rows, credit_note_totals = bucket({SRC_CREDIT_NOTE, SRC_SALES_RETURN})
        debit_note_rows, debit_note_totals = bucket({SRC_DEBIT_NOTE})

        hsn_summary: dict[str, dict] = defaultdict(lambda: {"taxable_value": _ZERO, "cgst": _ZERO, "sgst": _ZERO, "igst": _ZERO, "cess": _ZERO, "quantity": _ZERO})
        transaction_ids = [t.id for t in outward]
        if transaction_ids:
            lines_result = await self._session.execute(select(GstTransactionLine).where(GstTransactionLine.gst_transaction_id.in_(transaction_ids)))
            for line in lines_result.scalars().all():
                key = line.hsn_code or "UNSPECIFIED"
                entry = hsn_summary[key]
                entry["taxable_value"] += line.taxable_value
                entry["cgst"] += line.cgst_amount
                entry["sgst"] += line.sgst_amount
                entry["igst"] += line.igst_amount
                entry["cess"] += line.cess_amount
                entry["quantity"] += line.quantity

        return {
            "return_period": return_period,
            "b2b": {"count": len(b2b_rows), "totals": b2b_totals, "transactions": b2b_rows},
            "b2c": {"count": len(b2c_rows), "totals": b2c_totals, "transactions": b2c_rows},
            "credit_notes": {"count": len(credit_note_rows), "totals": credit_note_totals, "transactions": credit_note_rows},
            "debit_notes": {"count": len(debit_note_rows), "totals": debit_note_totals, "transactions": debit_note_rows},
            "hsn_summary": [{"hsn_code": k, **v} for k, v in sorted(hsn_summary.items())],
        }

    # --- GSTR-3B (§29) --------------------------------------------------------

    async def gstr3b_dataset(self, *, tenant_id: uuid.UUID, return_period: str) -> dict:
        outward = await self._period_transactions(tenant_id=tenant_id, return_period=return_period, direction=OUTWARD)
        inward = await self._period_transactions(tenant_id=tenant_id, return_period=return_period, direction=INWARD)

        outward_totals = GstTotals(_sum(outward, "taxable_value"), _sum(outward, "cgst_amount"), _sum(outward, "sgst_amount"), _sum(outward, "igst_amount"), _sum(outward, "cess_amount"), _sum(outward, "total_gst"))
        inward_totals = GstTotals(_sum(inward, "taxable_value"), _sum(inward, "cgst_amount"), _sum(inward, "sgst_amount"), _sum(inward, "igst_amount"), _sum(inward, "cess_amount"), _sum(inward, "total_gst"))

        return {
            "return_period": return_period,
            "outward_taxable_supplies": outward_totals,
            "output_cgst": outward_totals.cgst,
            "output_sgst": outward_totals.sgst,
            "output_igst": outward_totals.igst,
            "inward_supplies": inward_totals,
            "input_tax_credit_cgst": inward_totals.cgst,
            "input_tax_credit_sgst": inward_totals.sgst,
            "input_tax_credit_igst": inward_totals.igst,
            "net_gst_payable": (outward_totals.total_gst - inward_totals.total_gst),
        }

    # --- Dashboard (§35) -------------------------------------------------------

    async def dashboard(self, *, tenant_id: uuid.UUID, return_period: str) -> dict:
        outward = await self._period_transactions(tenant_id=tenant_id, return_period=return_period, direction=OUTWARD)
        inward = await self._period_transactions(tenant_id=tenant_id, return_period=return_period, direction=INWARD)
        output_gst = _sum(outward, "total_gst")
        input_gst = _sum(inward, "total_gst")
        b2b_sales = sum((t.total_amount for t in outward if t.source_type == SRC_SALES_INVOICE and t.classification == B2B), _ZERO)
        b2c_sales = sum((t.total_amount for t in outward if t.source_type == SRC_SALES_INVOICE and t.classification == B2C), _ZERO)
        credit_notes = sum((t.total_amount for t in outward if t.source_type in (SRC_CREDIT_NOTE, SRC_SALES_RETURN)), _ZERO)
        debit_notes = sum((t.total_amount for t in outward if t.source_type == SRC_DEBIT_NOTE), _ZERO)
        errors = await self.validate_gstr1(tenant_id=tenant_id, return_period=return_period)
        return {
            "return_period": return_period,
            "output_gst": output_gst,
            "input_gst": input_gst,
            "net_gst_position": output_gst - input_gst,
            "b2b_sales": b2b_sales,
            "b2c_sales": b2c_sales,
            "credit_notes": credit_notes,
            "debit_notes": debit_notes,
            "validation_error_count": len([i for i in errors if i.severity == ERROR]),
        }

    # --- Pre-submission validation (§32/§33) ----------------------------------

    async def validate_gstr1(self, *, tenant_id: uuid.UUID, return_period: str) -> list[ValidationIssue]:
        outward = await self._period_transactions(tenant_id=tenant_id, return_period=return_period, direction=OUTWARD)
        issues: list[ValidationIssue] = []
        seen_numbers: dict[str, int] = defaultdict(int)

        for t in outward:
            if t.source_number:
                seen_numbers[t.source_number] += 1
            if t.classification == B2B and not t.party_gstin:
                issues.append(ValidationIssue(
                    code="GST-001", severity=ERROR, message=f"B2B document {t.source_number} is missing GSTIN.",
                    source_type=t.source_type, source_id=str(t.source_id), field="party_gstin",
                    suggested_action="Add the customer's GSTIN before finalizing GSTR-1.",
                ))
            if t.party_gstin and not is_valid_gstin_format(t.party_gstin):
                issues.append(ValidationIssue(
                    code="GST-002", severity=ERROR, message=f"Document {t.source_number} has an invalid GSTIN format ({t.party_gstin}).",
                    source_type=t.source_type, source_id=str(t.source_id), field="party_gstin",
                    suggested_action="Correct the GSTIN format (15 characters).",
                ))
            if not t.place_of_supply_state_code:
                issues.append(ValidationIssue(
                    code="GST-007", severity=WARNING, message=f"Document {t.source_number} has no place of supply recorded.",
                    source_type=t.source_type, source_id=str(t.source_id), field="place_of_supply_state_code",
                    suggested_action="Confirm the recipient's state code.",
                ))

        transaction_ids = [t.id for t in outward]
        if transaction_ids:
            lines_result = await self._session.execute(select(GstTransactionLine).where(GstTransactionLine.gst_transaction_id.in_(transaction_ids)))
            transactions_by_id = {t.id: t for t in outward}
            for line in lines_result.scalars().all():
                if not line.hsn_code:
                    parent = transactions_by_id.get(line.gst_transaction_id)
                    severity = ERROR if parent and parent.classification == B2B else WARNING
                    issues.append(ValidationIssue(
                        code="GST-003", severity=severity,
                        message=f"Line {line.line_no} of {parent.source_number if parent else line.gst_transaction_id} is missing an HSN code.",
                        source_type=parent.source_type if parent else "", source_id=str(parent.source_id) if parent else "",
                        field="hsn_code", suggested_action="Add the product's HSN/SAC code.",
                    ))

        for number, count in seen_numbers.items():
            if count > 1:
                dup = next(t for t in outward if t.source_number == number)
                issues.append(ValidationIssue(
                    code="GST-006", severity=ERROR, message=f"Document number {number} appears {count} times in this period.",
                    source_type=dup.source_type, source_id=str(dup.source_id), field="source_number",
                    suggested_action="Investigate duplicate document numbering.",
                ))
        return issues

    async def validate_gstr3b(self, *, tenant_id: uuid.UUID, return_period: str) -> list[ValidationIssue]:
        dataset = await self.gstr3b_dataset(tenant_id=tenant_id, return_period=return_period)
        issues: list[ValidationIssue] = []
        if dataset["outward_taxable_supplies"].taxable_value < 0:
            issues.append(ValidationIssue(
                code="GST-009", severity=WARNING, message="Net outward taxable value for the period is negative (returns/credit notes exceed sales).",
                source_type="GSTR3B", source_id=return_period, field="outward_taxable_supplies",
                suggested_action="Review Sales Returns/Credit Notes recorded this period.",
            ))
        return issues

    # --- Reconciliation (§24/§34) ---------------------------------------------

    async def reconciliation(self, *, tenant_id: uuid.UUID, return_period: str) -> dict:
        gst_dataset = await self.gstr3b_dataset(tenant_id=tenant_id, return_period=return_period)
        engine_output = gst_dataset["outward_taxable_supplies"].cgst + gst_dataset["outward_taxable_supplies"].sgst + gst_dataset["outward_taxable_supplies"].igst
        engine_input = gst_dataset["inward_supplies"].cgst + gst_dataset["inward_supplies"].sgst + gst_dataset["inward_supplies"].igst

        year, month = return_period.split("-")
        date_from = date(int(year), int(month), 1)
        # Cheap next-month boundary without a calendar dependency.
        next_month = int(month) + 1
        next_year = int(year)
        if next_month > 12:
            next_month = 1
            next_year += 1
        date_to = date(next_year, next_month, 1)

        rows = await self._session.execute(
            select(AccountMapping.posting_rule_code, JournalLine.debit_amount, JournalLine.credit_amount)
            .join(ChartOfAccount, ChartOfAccount.id == JournalLine.account_id)
            .join(AccountMapping, AccountMapping.account_id == ChartOfAccount.id)
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_id)
            .where(
                JournalLine.tenant_id == tenant_id, JournalEntry.journal_date >= date_from, JournalEntry.journal_date < date_to,
                AccountMapping.posting_rule_code.in_([OUTPUT_CGST, OUTPUT_SGST, OUTPUT_IGST, INPUT_CGST, INPUT_SGST, INPUT_IGST]),
            )
        )
        accounting_output = _ZERO
        accounting_input = _ZERO
        for code, debit, credit in rows.all():
            if code in (OUTPUT_CGST, OUTPUT_SGST, OUTPUT_IGST):
                accounting_output += credit - debit
            else:
                accounting_input += debit - credit

        return {
            "return_period": return_period,
            "gst_engine_output_gst": engine_output,
            "accounting_output_gst": accounting_output,
            "output_gst_difference": engine_output - accounting_output,
            "gst_engine_input_gst": engine_input,
            "accounting_input_gst": accounting_input,
            "input_gst_difference": engine_input - accounting_input,
        }
