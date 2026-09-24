"""GST reporting integration boundary (PROMPT-015 §22, rebuilt by
PROMPT-026 into a REAL GST transaction snapshot service).

This file used to be a stub (PROMPT-015 through PROMPT-025) that only
wrote an audit-log JSON blob and returned an opaque `GSTTXN-<id>`
string — no real `gst_transaction` table existed. It now creates REAL,
immutable `gst_transaction`/`gst_transaction_line` rows — the same
"authoritative GST calculation" principle PROMPT-026 §2 requires: this
service NEVER recalculates tax, it only copies the ALREADY-CALCULATED
totals a source document's own posting flow produced via the one shared
`app.services.sales.gst_calculation_service` (§2/AC-001/AC-002).

Every existing call site (`sales_invoice_service.py`, `sales_return_
service.py`, `credit_debit_note_service.py`) is unchanged: same method
names, same parameters, same `-> str` return (now the real
`gst_transaction.id` reference instead of an opaque `GSTTXN-<id>`
string built from the SOURCE document's own id — mirrors PROMPT-025's
own "zero call site changes" discipline exactly).

Two NEW methods close the Purchase-side gap PROMPT-015-025 never
touched (`record_purchase_invoice_transaction`/`record_purchase_return_
transaction`, wired into `purchase_invoice_service.post_invoice`/
`purchase_return_service.confirm_return`), plus their reversal
counterparts (wired into each service's own POSTED/CONFIRMED
cancellation-with-reversal branch, mirroring `AccountingPostingService`'s
identical `reverse_purchase_invoice`/`reverse_purchase_return` shape).

Sign convention (§21/§24 — this is what makes period-level SUM()
aggregation for GSTR-3B's "net GST position" correct without bucket-type
special-casing every query): a transaction that INCREASES the tenant's
GST position (Sales Invoice, Debit Note, Purchase Invoice) is stored
with POSITIVE amounts; one that DECREASES it (Sales Return, Credit Note,
Purchase Return) is stored with NEGATIVE amounts. A REVERSAL row (only
used when a POSTED/CONFIRMED document is itself cancelled-with-reversal,
today only Purchase Invoice/Purchase Return) negates whatever its
ORIGINAL row held. The ORIGINAL row is NEVER edited (§21 "historical GST
values are immutable") — only a new REVERSAL row is added.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.accounting_constants import (
    SRC_CREDIT_NOTE,
    SRC_DEBIT_NOTE,
    SRC_PURCHASE_INVOICE,
    SRC_PURCHASE_RETURN,
    SRC_SALES_INVOICE,
    SRC_SALES_RETURN,
)
from app.core.gst_constants import B2B, B2C, EVT_ORIGINAL, EVT_REVERSAL, INWARD, OUTWARD
from app.models.credit_debit_note import CREDIT_NOTE, CreditDebitNote
from app.models.credit_debit_note_line import CreditDebitNoteLine
from app.models.customer import Customer
from app.models.gst_transaction import GstTransaction
from app.models.gst_transaction_line import GstTransactionLine
from app.models.purchase_invoice import PurchaseInvoice
from app.models.purchase_invoice_line import PurchaseInvoiceLine
from app.models.purchase_return import PurchaseReturn
from app.models.purchase_return_line import PurchaseReturnLine
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.sales_return import SalesReturn
from app.models.sales_return_line import SalesReturnLine
from app.models.supplier import Supplier
from app.models.tenant import Tenant
from app.services.audit.audit_service import AuditService
from app.services.sales.document_numbering_service import get_financial_year_label

# §22/§48 traceability + audit: mirrors `AccountingPostingService`'s own
# `_SOURCE_ENTITY_TYPE` precedent (PROMPT-025) — every source document's
# own audit-history view (GET .../audit-history) reads AuditLog rows
# scoped to ITS OWN entity_type/entity_id, not `gst_transaction`'s. This
# preserves the "GST_TRANSACTION_CREATED" audit trail the pre-PROMPT-026
# stub already wrote under the source entity, now alongside a REAL
# gst_transaction row instead of only a JSON blob.
_SOURCE_ENTITY_TYPE = {
    SRC_SALES_INVOICE: "sales_invoice",
    SRC_SALES_RETURN: "sales_return",
    SRC_CREDIT_NOTE: "credit_debit_note",
    SRC_DEBIT_NOTE: "credit_debit_note",
    SRC_PURCHASE_INVOICE: "purchase_invoice",
    SRC_PURCHASE_RETURN: "purchase_return",
}


class _LineInput:
    __slots__ = ("hsn_code", "quantity", "unit_price", "gst_rate", "taxable_value", "cgst", "sgst", "igst", "cess", "line_total")

    def __init__(self, *, hsn_code, quantity, unit_price, gst_rate, taxable_value, cgst, sgst, igst, cess, line_total):
        self.hsn_code = hsn_code
        self.quantity = quantity
        self.unit_price = unit_price
        self.gst_rate = gst_rate
        self.taxable_value = taxable_value
        self.cgst = cgst
        self.sgst = sgst
        self.igst = igst
        self.cess = cess
        self.line_total = line_total


class GstReportingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared core (§17/§21/§22/§42) --------------------------------------

    async def _existing_transaction(
        self, *, tenant_id: uuid.UUID, source_type: str, source_id: uuid.UUID, event_type: str
    ) -> GstTransaction | None:
        result = await self._session.execute(
            select(GstTransaction).where(
                GstTransaction.tenant_id == tenant_id, GstTransaction.source_type == source_type,
                GstTransaction.source_id == source_id, GstTransaction.event_type == event_type,
            )
        )
        return result.scalar_one_or_none()

    async def _record(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_type: str, source_id: uuid.UUID,
        source_number: str | None, event_type: str, direction: str, classification: str,
        party_id: uuid.UUID | None, party_name: str | None, party_gstin: str | None,
        place_of_supply_state_code: str | None, document_date: date,
        taxable_value: Decimal, cgst: Decimal, sgst: Decimal, igst: Decimal, cess: Decimal, total_amount: Decimal,
        lines: list[_LineInput], ip_address: str | None, reversal_of_transaction_id: uuid.UUID | None = None,
    ) -> GstTransaction:
        # §42 idempotency: a duplicate recording attempt for the same
        # source+event returns the ALREADY-created row, never a second one.
        existing = await self._existing_transaction(tenant_id=tenant_id, source_type=source_type, source_id=source_id, event_type=event_type)
        if existing is not None:
            return existing

        tenant_result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = tenant_result.scalar_one()
        fy_label = get_financial_year_label(tenant, document_date)
        return_period = document_date.strftime("%Y-%m")

        transaction = GstTransaction(
            tenant_id=tenant_id, source_type=source_type, source_id=source_id, source_number=source_number,
            event_type=event_type, reversal_of_transaction_id=reversal_of_transaction_id, direction=direction,
            classification=classification, party_id=party_id, party_name=party_name, party_gstin=party_gstin,
            place_of_supply_state_code=place_of_supply_state_code, document_date=document_date,
            financial_year_label=fy_label, return_period=return_period, taxable_value=taxable_value,
            cgst_amount=cgst, sgst_amount=sgst, igst_amount=igst, cess_amount=cess, total_gst=cgst + sgst + igst + cess,
            total_amount=total_amount, created_by=actor_user_id, updated_by=actor_user_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(transaction)
                await self._session.flush()
                for idx, line in enumerate(lines, start=1):
                    self._session.add(
                        GstTransactionLine(
                            tenant_id=tenant_id, gst_transaction_id=transaction.id, line_no=idx, hsn_code=line.hsn_code,
                            quantity=line.quantity, unit_price=line.unit_price, gst_rate=line.gst_rate,
                            taxable_value=line.taxable_value, cgst_amount=line.cgst, sgst_amount=line.sgst,
                            igst_amount=line.igst, cess_amount=line.cess, line_total=line.line_total,
                            created_by=actor_user_id, updated_by=actor_user_id,
                        )
                    )
                await self._session.flush()
        except IntegrityError:
            # §43 concurrency: a concurrent request won the unique-
            # constraint race — re-query and return the row it created
            # instead of raising or creating a duplicate.
            existing = await self._existing_transaction(tenant_id=tenant_id, source_type=source_type, source_id=source_id, event_type=event_type)
            if existing is not None:
                return existing
            raise

        entity_type = _SOURCE_ENTITY_TYPE.get(source_type)
        if entity_type is not None:
            await AuditService(self._session).record(
                tenant_id=tenant_id, actor_user_id=actor_user_id,
                action="GST_TRANSACTION_REVERSED" if event_type == EVT_REVERSAL else "GST_TRANSACTION_CREATED",
                entity_type=entity_type, entity_id=source_id,
                after={
                    "gst_transaction_id": str(transaction.id), "source_type": source_type,
                    "taxable_value": str(taxable_value), "total_gst": str(cgst + sgst + igst + cess),
                },
                ip_address=ip_address,
            )
        return transaction

    # --- Sales Invoice (PROMPT-015 §22, real snapshot since PROMPT-026) -----

    async def record_invoice_transaction(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice: SalesInvoice, ip_address: str | None,
    ) -> str:
        customer_result = await self._session.execute(select(Customer.name).where(Customer.id == invoice.customer_id))
        customer_name = customer_result.scalar_one_or_none()
        lines_result = await self._session.execute(
            select(SalesInvoiceLine).where(SalesInvoiceLine.invoice_id == invoice.id).order_by(SalesInvoiceLine.line_no)
        )
        line_inputs = [
            _LineInput(
                hsn_code=ln.hsn_code, quantity=ln.quantity, unit_price=ln.unit_price, gst_rate=ln.gst_rate,
                taxable_value=ln.taxable_amount, cgst=ln.cgst_amount, sgst=ln.sgst_amount, igst=ln.igst_amount,
                cess=ln.cess_amount, line_total=ln.line_total,
            )
            for ln in lines_result.scalars().all()
        ]
        transaction = await self._record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_SALES_INVOICE, source_id=invoice.id,
            source_number=invoice.invoice_number, event_type=EVT_ORIGINAL, direction=OUTWARD,
            classification=invoice.customer_type, party_id=invoice.customer_id, party_name=customer_name,
            party_gstin=invoice.customer_gstin, place_of_supply_state_code=invoice.place_of_supply_state_code,
            document_date=invoice.invoice_date, taxable_value=invoice.taxable_total, cgst=invoice.cgst_total,
            sgst=invoice.sgst_total, igst=invoice.igst_total, cess=Decimal("0"), total_amount=invoice.grand_total,
            lines=line_inputs, ip_address=ip_address,
        )
        return str(transaction.id)

    # --- Sales Return (PROMPT-016 §22) --------------------------------------

    async def record_return_transaction(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, sales_return: SalesReturn, ip_address: str | None,
    ) -> str:
        """§17: a Sales Return reduces the tenant's Output GST position —
        stored with NEGATIVE amounts (module docstring's sign convention)
        so period-level aggregation nets correctly. Does NOT imply a
        Credit Note was created (§22 explicit boundary, unchanged)."""
        customer_result = await self._session.execute(select(Customer.name).where(Customer.id == sales_return.customer_id))
        customer_name = customer_result.scalar_one_or_none()
        lines_result = await self._session.execute(
            select(SalesReturnLine).where(SalesReturnLine.sales_return_id == sales_return.id).order_by(SalesReturnLine.line_no)
        )
        line_inputs = [
            _LineInput(
                hsn_code=ln.hsn_code, quantity=-ln.quantity, unit_price=ln.unit_price, gst_rate=ln.gst_rate,
                taxable_value=-ln.taxable_amount, cgst=-ln.cgst_amount, sgst=-ln.sgst_amount, igst=-ln.igst_amount,
                cess=-ln.cess_amount, line_total=-ln.line_total,
            )
            for ln in lines_result.scalars().all()
        ]
        # Determine B2B/B2C from GSTIN presence (Sales Return has no
        # `customer_type` column of its own — the source invoice's own
        # classification is the authoritative signal).
        classification = B2B if sales_return.customer_gstin else B2C
        transaction = await self._record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_SALES_RETURN, source_id=sales_return.id,
            source_number=sales_return.return_number, event_type=EVT_ORIGINAL, direction=OUTWARD,
            classification=classification, party_id=sales_return.customer_id, party_name=customer_name,
            party_gstin=sales_return.customer_gstin, place_of_supply_state_code=sales_return.place_of_supply_state_code,
            document_date=sales_return.return_date, taxable_value=-sales_return.taxable_total, cgst=-sales_return.cgst_total,
            sgst=-sales_return.sgst_total, igst=-sales_return.igst_total, cess=Decimal("0"), total_amount=-sales_return.grand_total,
            lines=line_inputs, ip_address=ip_address,
        )
        return str(transaction.id)

    # --- Credit Note / Debit Note (PROMPT-017 §21) --------------------------

    async def record_credit_debit_note_transaction(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, note: CreditDebitNote, ip_address: str | None,
    ) -> str:
        """§19/§20: CREDIT_NOTE reduces Output GST (negative, mirrors
        Sales Return's own sign); DEBIT_NOTE increases it (positive,
        mirror-opposite — §20/§56 OD-015, still a documented judgment
        call, unchanged from the pre-PROMPT-026 resolution)."""
        is_credit = note.note_type == CREDIT_NOTE
        sign = Decimal("-1") if is_credit else Decimal("1")

        customer_result = await self._session.execute(select(Customer.name).where(Customer.id == note.customer_id))
        customer_name = customer_result.scalar_one_or_none()
        lines_result = await self._session.execute(
            select(CreditDebitNoteLine).where(CreditDebitNoteLine.credit_debit_note_id == note.id).order_by(CreditDebitNoteLine.line_no)
        )
        line_inputs = [
            _LineInput(
                hsn_code=ln.hsn_code, quantity=sign * ln.quantity, unit_price=ln.unit_price, gst_rate=ln.gst_rate,
                taxable_value=sign * ln.taxable_amount, cgst=sign * ln.cgst_amount, sgst=sign * ln.sgst_amount,
                igst=sign * ln.igst_amount, cess=sign * ln.cess_amount, line_total=sign * ln.line_total,
            )
            for ln in lines_result.scalars().all()
        ]
        classification = B2B if note.customer_gstin else B2C
        transaction = await self._record(
            tenant_id=tenant_id, actor_user_id=actor_user_id,
            source_type=SRC_CREDIT_NOTE if is_credit else SRC_DEBIT_NOTE, source_id=note.id,
            source_number=note.note_number, event_type=EVT_ORIGINAL, direction=OUTWARD, classification=classification,
            party_id=note.customer_id, party_name=customer_name, party_gstin=note.customer_gstin,
            place_of_supply_state_code=note.place_of_supply_state_code, document_date=note.note_date,
            taxable_value=sign * note.taxable_total, cgst=sign * note.cgst_total, sgst=sign * note.sgst_total,
            igst=sign * note.igst_total, cess=Decimal("0"), total_amount=sign * note.grand_total, lines=line_inputs,
            ip_address=ip_address,
        )
        return str(transaction.id)

    # --- Purchase Invoice (PROMPT-026, closes the Purchase-side gap) -------

    async def record_purchase_invoice_transaction(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice: PurchaseInvoice, ip_address: str | None,
    ) -> str:
        supplier_result = await self._session.execute(select(Supplier.name).where(Supplier.id == invoice.supplier_id))
        supplier_name = supplier_result.scalar_one_or_none()
        lines_result = await self._session.execute(
            select(PurchaseInvoiceLine).where(PurchaseInvoiceLine.purchase_invoice_id == invoice.id).order_by(PurchaseInvoiceLine.line_no)
        )
        line_inputs = [
            _LineInput(
                hsn_code=ln.hsn_code, quantity=ln.quantity, unit_price=ln.unit_price, gst_rate=ln.gst_rate,
                taxable_value=ln.taxable_amount, cgst=ln.cgst_amount, sgst=ln.sgst_amount, igst=ln.igst_amount,
                cess=ln.cess_amount, line_total=ln.line_total,
            )
            for ln in lines_result.scalars().all()
        ]
        classification = B2B if invoice.supplier_gstin else B2C
        transaction = await self._record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PURCHASE_INVOICE, source_id=invoice.id,
            source_number=invoice.purchase_invoice_number, event_type=EVT_ORIGINAL, direction=INWARD,
            classification=classification, party_id=invoice.supplier_id, party_name=supplier_name,
            party_gstin=invoice.supplier_gstin, place_of_supply_state_code=invoice.place_of_supply_state_code,
            document_date=invoice.document_date, taxable_value=invoice.taxable_total, cgst=invoice.cgst_total,
            sgst=invoice.sgst_total, igst=invoice.igst_total, cess=Decimal("0"), total_amount=invoice.grand_total,
            lines=line_inputs, ip_address=ip_address,
        )
        return str(transaction.id)

    async def reverse_purchase_invoice_transaction(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID, ip_address: str | None,
    ) -> str | None:
        original = await self._existing_transaction(tenant_id=tenant_id, source_type=SRC_PURCHASE_INVOICE, source_id=invoice_id, event_type=EVT_ORIGINAL)
        if original is None:
            return None
        return await self._reverse(tenant_id=tenant_id, actor_user_id=actor_user_id, original=original, ip_address=ip_address)

    # --- Purchase Return (PROMPT-026) ---------------------------------------

    async def record_purchase_return_transaction(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_return: PurchaseReturn, ip_address: str | None,
    ) -> str:
        """A Purchase Return reduces the tenant's Input GST/ITC position
        — stored with NEGATIVE amounts (module docstring's sign
        convention), mirroring Sales Return's own resolution one level
        down the chain."""
        supplier_result = await self._session.execute(select(Supplier.name).where(Supplier.id == purchase_return.supplier_id))
        supplier_name = supplier_result.scalar_one_or_none()
        lines_result = await self._session.execute(
            select(PurchaseReturnLine).where(PurchaseReturnLine.purchase_return_id == purchase_return.id).order_by(PurchaseReturnLine.line_no)
        )
        line_inputs = [
            _LineInput(
                hsn_code=ln.hsn_code, quantity=-ln.quantity, unit_price=ln.unit_price, gst_rate=ln.gst_rate,
                taxable_value=-ln.taxable_amount, cgst=-ln.cgst_amount, sgst=-ln.sgst_amount, igst=-ln.igst_amount,
                cess=-ln.cess_amount, line_total=-ln.line_total,
            )
            for ln in lines_result.scalars().all()
        ]
        classification = B2B if purchase_return.supplier_gstin else B2C
        transaction = await self._record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PURCHASE_RETURN, source_id=purchase_return.id,
            source_number=purchase_return.purchase_return_number, event_type=EVT_ORIGINAL, direction=INWARD,
            classification=classification, party_id=purchase_return.supplier_id, party_name=supplier_name,
            party_gstin=purchase_return.supplier_gstin, place_of_supply_state_code=purchase_return.place_of_supply_state_code,
            document_date=purchase_return.document_date, taxable_value=-purchase_return.taxable_total, cgst=-purchase_return.cgst_total,
            sgst=-purchase_return.sgst_total, igst=-purchase_return.igst_total, cess=Decimal("0"), total_amount=-purchase_return.grand_total,
            lines=line_inputs, ip_address=ip_address,
        )
        return str(transaction.id)

    async def reverse_purchase_return_transaction(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, return_id: uuid.UUID, ip_address: str | None,
    ) -> str | None:
        original = await self._existing_transaction(tenant_id=tenant_id, source_type=SRC_PURCHASE_RETURN, source_id=return_id, event_type=EVT_ORIGINAL)
        if original is None:
            return None
        return await self._reverse(tenant_id=tenant_id, actor_user_id=actor_user_id, original=original, ip_address=ip_address)

    # --- reversal core (§21/§33) ---------------------------------------------

    async def _reverse(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, original: GstTransaction, ip_address: str | None,
    ) -> str:
        existing_reversal = await self._existing_transaction(
            tenant_id=tenant_id, source_type=original.source_type, source_id=original.source_id, event_type=EVT_REVERSAL
        )
        if existing_reversal is not None:
            return str(existing_reversal.id)

        original_lines_result = await self._session.execute(
            select(GstTransactionLine).where(GstTransactionLine.gst_transaction_id == original.id).order_by(GstTransactionLine.line_no)
        )
        reversal_lines = [
            _LineInput(
                hsn_code=ln.hsn_code, quantity=-ln.quantity, unit_price=ln.unit_price, gst_rate=ln.gst_rate,
                taxable_value=-ln.taxable_value, cgst=-ln.cgst_amount, sgst=-ln.sgst_amount, igst=-ln.igst_amount,
                cess=-ln.cess_amount, line_total=-ln.line_total,
            )
            for ln in original_lines_result.scalars().all()
        ]
        reversal = await self._record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=original.source_type, source_id=original.source_id,
            source_number=original.source_number, event_type=EVT_REVERSAL, direction=original.direction,
            classification=original.classification, party_id=original.party_id, party_name=original.party_name,
            party_gstin=original.party_gstin, place_of_supply_state_code=original.place_of_supply_state_code,
            document_date=date.today(), taxable_value=-original.taxable_value, cgst=-original.cgst_amount,
            sgst=-original.sgst_amount, igst=-original.igst_amount, cess=-original.cess_amount,
            total_amount=-original.total_amount, lines=reversal_lines, ip_address=ip_address,
            reversal_of_transaction_id=original.id,
        )
        return str(reversal.id)
