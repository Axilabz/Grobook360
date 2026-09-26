"""Credit Note / Debit Note service (PROMPT-017).

The sixth Sales document type, and the first that is a PURE FINANCIAL
ADJUSTMENT with NO inventory effect whatsoever. §2/§3/§22 are the
critical rules this file is organized around: this module NEVER imports
`InventoryService` and NEVER calls `post_movement` — the double
guarantee is structural (no import exists to misuse) and verified by a
dedicated test asserting zero new `stock_ledger_entry` rows for both
note types.

Every note line MUST reference a specific Sales Invoice line
(`source_invoice_line_id`, §17/§18) so eligible remaining quantity can be
computed and validated — both at DRAFT time (a soft, non-authoritative
convenience check) and again under a row lock at post time (the
authoritative check; §28's mandatory concurrency test depends on this).

Eligibility is tracked separately per note type on the SAME source
line (`sales_invoice_line.credited_quantity` / `.debited_quantity`) —
`CREDIT_NOTE` reduces "creditable quantity" (`quantity -
credited_quantity`); `DEBIT_NOTE` reduces "debitable quantity" (`quantity
- debited_quantity`). The Debit Note eligibility rule is a documented,
conservative placeholder (§53 open decision #10/#28) — no approved
source confirms whether a Debit Note should really be bounded by the
ORIGINAL invoiced quantity at all (e.g. a short-billing correction may
need to exceed it) — see PROMPT-017-NOTES.md for the full discussion.

Pricing for a note line: a Sales Invoice line already carries its own
final price/discount/GST — §18 resolves "use the original transaction's
commercial values" as YES. The invoice line's absolute `discount_amount`
(computed for its FULL invoiced quantity) is converted to an equivalent
discount PERCENTAGE before calling `gst_calculation_service.calculate_line`
with the note's own (possibly smaller) quantity — identical proration
technique to Sales Return's own line pricing (PROMPT-016). GST treatment
(intra/inter-state) is recomputed via `determine_gst_treatment` using the
invoice's own place-of-supply snapshot.

This service calls the SAME accounting/GST integration-boundary pattern
established in PROMPT-015/016 (`AccountingPostingService.
post_credit_debit_note`, `GstReportingService.
record_credit_debit_note_transaction`) — conceptual audit-trail entries
plus opaque reference strings only, no real GL/GST schema.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    CDN_EXCEEDS_ELIGIBLE,
    CDN_INVALID_NOTE_TYPE,
    CDN_INVALID_STATUS,
    CDN_INVOICE_NOT_ELIGIBLE,
    CDN_NOT_FOUND,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.sales_constants import CREDIT_NOTE as CREDIT_NOTE_DOC_TYPE
from app.core.sales_constants import DEBIT_NOTE as DEBIT_NOTE_DOC_TYPE
from app.models.credit_debit_note import (
    CANCELLABLE_STATUSES,
    CANCELLED,
    CREDIT_NOTE,
    DEBIT_NOTE,
    DRAFT,
    NOTE_TYPES,
    POSTED,
    CreditDebitNote,
)
from app.models.credit_debit_note_line import CreditDebitNoteLine
from app.models.customer import Customer
from app.models.user import User
from app.models.sales_invoice import POSTED as SI_POSTED
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.credit_debit_note import AdjustmentLineInput
from app.services.accounting.accounting_posting_service import AccountingPostingService
from app.services.audit.audit_service import AuditService
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.services.sales.gst_calculation_service import (
    calculate_document_totals,
    calculate_line,
    determine_gst_treatment,
)
from app.services.sales.gst_reporting_service import GstReportingService
from app.services.sales.sales_invoice_service import SalesInvoiceService
from app.services.sales.sales_validation_service import validate_customer_for_sale

_NUMBERING = {
    CREDIT_NOTE: (CREDIT_NOTE_DOC_TYPE, "CN"),
    DEBIT_NOTE: (DEBIT_NOTE_DOC_TYPE, "DN"),
}


@dataclass(frozen=True)
class CreditDebitNotePage:
    items: list[tuple[CreditDebitNote, str, str, str | None, str | None]]  # (note, customer_name, source_invoice_number, created_by_name, updated_by_name)
    total_items: int


class CreditDebitNoteService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared helpers -----------------------------------------------

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _get_note_locked(self, tenant_id: uuid.UUID, note_id: uuid.UUID) -> CreditDebitNote:
        result = await self._session.execute(
            select(CreditDebitNote)
            .where(CreditDebitNote.id == note_id, CreditDebitNote.tenant_id == tenant_id)
            .with_for_update()
        )
        note = result.scalar_one_or_none()
        if note is None:
            raise NotFoundError("Credit/debit note not found", code=CDN_NOT_FOUND)
        return note

    async def _get_lines(self, note_id: uuid.UUID) -> list[tuple[CreditDebitNoteLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(CreditDebitNoteLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == CreditDebitNoteLine.uom_id)
            .where(CreditDebitNoteLine.credit_debit_note_id == note_id)
            .order_by(CreditDebitNoteLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    def _snapshot(self, note: CreditDebitNote) -> dict:
        return {
            "note_type": note.note_type,
            "source_invoice_id": str(note.source_invoice_id),
            "customer_id": str(note.customer_id),
            "note_date": note.note_date.isoformat(),
            "status": note.status,
            "reason": note.reason,
            "grand_total": str(note.grand_total),
        }

    @staticmethod
    def _validate_note_type(note_type: str) -> None:
        if note_type not in NOTE_TYPES:
            raise ValidationAppError(f"'{note_type}' is not a recognized note type.", code=CDN_INVALID_NOTE_TYPE)

    # --- adjustment eligibility (§17/§24 steps 4-6) -------------------------

    async def get_adjustment_eligibility(
        self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> tuple[SalesInvoice, str, list[tuple[SalesInvoiceLine, UnitOfMeasure]]]:
        invoice_service = SalesInvoiceService(self._session)
        invoice, customer_name, _dc_number, lines = await invoice_service.get_invoice(
            tenant_id=tenant_id, invoice_id=invoice_id
        )
        if invoice.status != SI_POSTED:
            raise ValidationAppError(
                f"An invoice in {invoice.status} status is not eligible for a credit/debit note.",
                code=CDN_INVOICE_NOT_ELIGIBLE,
            )
        return invoice, customer_name, lines

    # --- queries ---------------------------------------------------------

    async def list_notes(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        search: str | None,
        note_type_filter: str | None,
        status_filter: str | None,
        customer_id: uuid.UUID | None,
        source_invoice_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> CreditDebitNotePage:
        creator = aliased(User)
        updater = aliased(User)
        base = (
            select(CreditDebitNote, Customer.name, SalesInvoice.invoice_number, creator.name, updater.name)
            .join(Customer, Customer.id == CreditDebitNote.customer_id)
            .join(SalesInvoice, SalesInvoice.id == CreditDebitNote.source_invoice_id)
            .outerjoin(creator, creator.id == CreditDebitNote.created_by)
            .outerjoin(updater, updater.id == CreditDebitNote.updated_by)
            .where(CreditDebitNote.tenant_id == tenant_id)
        )

        if search:
            like = f"%{search}%"
            base = base.where(
                or_(
                    CreditDebitNote.note_number.ilike(like),
                    SalesInvoice.invoice_number.ilike(like),
                    Customer.name.ilike(like),
                    Customer.customer_code.ilike(like),
                )
            )
        if note_type_filter:
            base = base.where(CreditDebitNote.note_type == note_type_filter)
        if status_filter:
            base = base.where(CreditDebitNote.status == status_filter)
        if customer_id:
            base = base.where(CreditDebitNote.customer_id == customer_id)
        if source_invoice_id:
            base = base.where(CreditDebitNote.source_invoice_id == source_invoice_id)
        if date_from:
            base = base.where(CreditDebitNote.note_date >= date_from)
        if date_to:
            base = base.where(CreditDebitNote.note_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(CreditDebitNote.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(CreditDebitNote.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return CreditDebitNotePage(items=[(row[0], row[1], row[2], row[3], row[4]) for row in rows], total_items=total_items)

    async def get_note(
        self, *, tenant_id: uuid.UUID, note_id: uuid.UUID
    ) -> tuple[CreditDebitNote, str, str, str | None, str | None, list[tuple[CreditDebitNoteLine, UnitOfMeasure]]]:
        creator = aliased(User)
        updater = aliased(User)
        result = await self._session.execute(
            select(CreditDebitNote, Customer.name, SalesInvoice.invoice_number, creator.name, updater.name)
            .join(Customer, Customer.id == CreditDebitNote.customer_id)
            .join(SalesInvoice, SalesInvoice.id == CreditDebitNote.source_invoice_id)
            .outerjoin(creator, creator.id == CreditDebitNote.created_by)
            .outerjoin(updater, updater.id == CreditDebitNote.updated_by)
            .where(CreditDebitNote.id == note_id, CreditDebitNote.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Credit/debit note not found", code=CDN_NOT_FOUND)
        note, customer_name, invoice_number, created_by_name, updated_by_name = row
        lines = await self._get_lines(note.id)
        return note, customer_name, invoice_number, created_by_name, updated_by_name, lines

    # --- line building (shared by create/update) ----------------------------

    def _eligible_quantity(self, invoice_line: SalesInvoiceLine, note_type: str) -> Decimal:
        if note_type == CREDIT_NOTE:
            return invoice_line.quantity - invoice_line.credited_quantity
        return invoice_line.quantity - invoice_line.debited_quantity

    async def _build_lines(
        self,
        *,
        tenant_id: uuid.UUID,
        note_id: uuid.UUID,
        note_type: str,
        invoice_lines_by_id: dict[uuid.UUID, tuple[SalesInvoiceLine, UnitOfMeasure]],
        gst_treatment: str,
        line_inputs: list[AdjustmentLineInput],
    ) -> tuple[list[CreditDebitNoteLine], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        """§17: validates each requested adjustment quantity against the
        CURRENTLY-known eligible quantity for this note_type. This is a
        DRAFT-time convenience check only — the authoritative, race-proof
        re-validation happens again in `post_note` under a lock (§28)."""
        lines: list[CreditDebitNoteLine] = []
        calculated_lines = []

        for index, line_input in enumerate(line_inputs, start=1):
            invoice_line_id = uuid.UUID(line_input.source_invoice_line_id)
            match = invoice_lines_by_id.get(invoice_line_id)
            if match is None:
                raise ValidationAppError(
                    "The selected invoice line does not belong to this sales invoice.",
                    code=CDN_EXCEEDS_ELIGIBLE,
                )
            invoice_line, uom = match

            eligible = self._eligible_quantity(invoice_line, note_type)
            if line_input.quantity > eligible:
                raise ValidationAppError(
                    f"Adjustment quantity {line_input.quantity} exceeds eligible quantity {eligible}.",
                    code=CDN_EXCEEDS_ELIGIBLE,
                )

            gross_invoiced = invoice_line.quantity * invoice_line.unit_price
            effective_discount_percent = (
                (invoice_line.discount_amount / gross_invoiced * Decimal("100")) if gross_invoiced > 0 else Decimal("0")
            )

            result = calculate_line(
                quantity=line_input.quantity,
                unit_price=invoice_line.unit_price,
                discount_percent=effective_discount_percent,
                discount_amount=None,
                gst_rate=invoice_line.gst_rate,
                gst_treatment=gst_treatment,
            )
            calculated_lines.append(result)

            lines.append(
                CreditDebitNoteLine(
                    tenant_id=tenant_id,
                    credit_debit_note_id=note_id,
                    line_no=index,
                    source_invoice_line_id=invoice_line.id,
                    product_id=invoice_line.product_id,
                    description=invoice_line.description,
                    hsn_code=invoice_line.hsn_code,
                    quantity=line_input.quantity,
                    uom_id=uom.id,
                    unit_price=invoice_line.unit_price,
                    discount_amount=result.discount_amount,
                    taxable_amount=result.taxable_amount,
                    gst_rate=invoice_line.gst_rate,
                    cgst_amount=result.cgst_amount,
                    sgst_amount=result.sgst_amount,
                    igst_amount=result.igst_amount,
                    line_total=result.line_total,
                )
            )

        totals = calculate_document_totals(calculated_lines)
        return (
            lines,
            totals.subtotal,
            totals.total_discount,
            totals.total_taxable,
            totals.total_cgst,
            totals.total_sgst,
            totals.total_igst,
            totals.grand_total,
        )

    # --- create (DRAFT only) ------------------------------------------------

    async def create_note(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        source_invoice_id: uuid.UUID,
        note_type: str,
        note_date: date | None,
        reason: str,
        notes: str | None,
        line_inputs: list[AdjustmentLineInput],
        ip_address: str | None,
    ) -> tuple[CreditDebitNote, str, str, list[tuple[CreditDebitNoteLine, UnitOfMeasure]]]:
        self._validate_note_type(note_type)

        tenant = await self._get_tenant(tenant_id)
        invoice, customer_name, invoice_lines = await self.get_adjustment_eligibility(
            tenant_id=tenant_id, invoice_id=source_invoice_id
        )
        invoice_lines_by_id = {line.id: (line, uom) for line, uom in invoice_lines}

        # Tenant-scoped, active-customer re-check (§44 IDOR/tenant-isolation
        # discipline) even though the invoice already carries a snapshot.
        await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=invoice.customer_id)

        gst_treatment = determine_gst_treatment(
            supplier_state_code=tenant.state_code,
            customer_state_code=invoice.place_of_supply_state_code,
        )
        doc_date = note_date or date.today()

        document_type, prefix = _NUMBERING[note_type]
        numbering = DocumentNumberingService(self._session)
        note_number = await numbering.next_number(tenant=tenant, document_type=document_type, prefix=prefix)

        note = CreditDebitNote(
            tenant_id=tenant_id,
            note_number=note_number,
            note_type=note_type,
            note_date=doc_date,
            source_invoice_id=invoice.id,
            customer_id=invoice.customer_id,
            customer_gstin=invoice.customer_gstin,
            billing_address=invoice.billing_address,
            shipping_address=invoice.shipping_address,
            place_of_supply_state_code=invoice.place_of_supply_state_code,
            status=DRAFT,
            reason=reason,
            notes=notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(note)
        await self._session.flush()

        lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
            await self._build_lines(
                tenant_id=tenant_id,
                note_id=note.id,
                note_type=note_type,
                invoice_lines_by_id=invoice_lines_by_id,
                gst_treatment=gst_treatment,
                line_inputs=line_inputs,
            )
        )
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        note.subtotal = subtotal
        note.discount_total = discount_total
        note.taxable_total = taxable_total
        note.cgst_total = cgst_total
        note.sgst_total = sgst_total
        note.igst_total = igst_total
        note.tax_total = cgst_total + sgst_total + igst_total
        note.grand_total = grand_total
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=f"{note_type}_CREATED",
            entity_type="credit_debit_note",
            entity_id=note.id,
            after=self._snapshot(note),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(note.id)
        return note, customer_name, invoice.invoice_number, lines_with_uom

    # --- update (DRAFT only) ------------------------------------------------

    async def update_note(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        note_id: uuid.UUID,
        expected_row_version: int,
        note_date: date | None,
        reason: str | None,
        notes: str | None,
        line_inputs: list[AdjustmentLineInput] | None,
        ip_address: str | None,
    ) -> tuple[CreditDebitNote, str, str, list[tuple[CreditDebitNoteLine, UnitOfMeasure]]]:
        note = await self._get_note_locked(tenant_id, note_id)
        check_row_version(note, expected_row_version)

        if note.status != DRAFT:
            raise ValidationAppError(
                "This note has already been posted and cannot be edited.", code=CDN_INVALID_STATUS
            )

        before = self._snapshot(note)
        tenant = await self._get_tenant(tenant_id)

        if note_date is not None:
            note.note_date = note_date
        if reason is not None:
            note.reason = reason
        if notes is not None:
            note.notes = notes

        invoice_service = SalesInvoiceService(self._session)
        invoice, customer_name, _dc_number, invoice_lines = await invoice_service.get_invoice(
            tenant_id=tenant_id, invoice_id=note.source_invoice_id
        )
        invoice_lines_by_id = {line.id: (line, uom) for line, uom in invoice_lines}

        if line_inputs is not None:
            gst_treatment = determine_gst_treatment(
                supplier_state_code=tenant.state_code,
                customer_state_code=invoice.place_of_supply_state_code,
            )
            existing_lines = await self._get_lines(note.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
                await self._build_lines(
                    tenant_id=tenant_id,
                    note_id=note.id,
                    note_type=note.note_type,
                    invoice_lines_by_id=invoice_lines_by_id,
                    gst_treatment=gst_treatment,
                    line_inputs=line_inputs,
                )
            )
            for line in lines:
                line.created_by = actor_user_id
                line.updated_by = actor_user_id
                self._session.add(line)

            note.subtotal = subtotal
            note.discount_total = discount_total
            note.taxable_total = taxable_total
            note.cgst_total = cgst_total
            note.sgst_total = sgst_total
            note.igst_total = igst_total
            note.tax_total = cgst_total + sgst_total + igst_total
            note.grand_total = grand_total

        note.updated_by = actor_user_id
        note.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=f"{note.note_type}_UPDATED",
            entity_type="credit_debit_note",
            entity_id=note.id,
            before=before,
            after=self._snapshot(note),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(note.id)
        return note, customer_name, invoice.invoice_number, lines_with_uom

    # --- post (§26/§28: the atomic accounting/GST core, NO stock code) ------

    async def post_note(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        note_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> tuple[CreditDebitNote, str, str, list[tuple[CreditDebitNoteLine, UnitOfMeasure]]]:
        """One database transaction end-to-end (§26): validate -> lock
        source Sales Invoice -> re-validate live eligible quantity per
        line -> increment invoice_line.credited_quantity/debited_quantity
        -> record accounting/GST integration entries -> mark POSTED ->
        audit. §2/§3/§22: this method NEVER imports or calls
        `InventoryService`/`post_movement` — no stock code exists here to
        accidentally run."""
        note = await self._get_note_locked(tenant_id, note_id)
        check_row_version(note, expected_row_version)

        if note.status != DRAFT:
            raise ValidationAppError(f"Cannot post a note in {note.status} status.", code=CDN_INVALID_STATUS)

        invoice_service = SalesInvoiceService(self._session)
        # §28/§50: locks the Sales Invoice row so a concurrent post of a
        # DIFFERENT note against the SAME invoice cannot race — the second
        # transaction blocks here until the first fully commits, the same
        # pattern `SalesReturnService.confirm_return` uses against Sales
        # Invoice.
        invoice = await invoice_service.get_invoice_locked(tenant_id, note.source_invoice_id)
        if invoice.status != SI_POSTED:
            raise ValidationAppError(
                f"The source sales invoice is in {invoice.status} status and can no longer be adjusted.",
                code=CDN_INVOICE_NOT_ELIGIBLE,
            )

        # Fresh read, post-lock: sees any credited/debited_quantity change
        # already committed by a concurrent note posting.
        invoice_lines = await invoice_service.get_lines(invoice.id)
        invoice_lines_by_id = {line.id: line for line, _uom in invoice_lines}

        note_lines = await self._get_lines(note.id)

        for note_line, _uom in note_lines:
            invoice_line = invoice_lines_by_id.get(note_line.source_invoice_line_id)
            if invoice_line is None:
                raise ValidationAppError("The source invoice line no longer exists.", code=CDN_EXCEEDS_ELIGIBLE)

            live_eligible = self._eligible_quantity(invoice_line, note.note_type)
            if note_line.quantity > live_eligible:
                raise ValidationAppError(
                    f"Adjustment quantity {note_line.quantity} exceeds eligible quantity {live_eligible}.",
                    code=CDN_EXCEEDS_ELIGIBLE,
                )

            if note.note_type == CREDIT_NOTE:
                invoice_line.credited_quantity += note_line.quantity
            else:
                invoice_line.debited_quantity += note_line.quantity
            invoice_line.updated_by = actor_user_id

        # §2/§3/§22: no InventoryService import, no post_movement call —
        # structurally impossible for this method to move stock.

        accounting_reference = await AccountingPostingService(self._session).post_credit_debit_note(
            tenant_id=tenant_id, actor_user_id=actor_user_id, note=note, ip_address=ip_address
        )
        gst_reference = await GstReportingService(self._session).record_credit_debit_note_transaction(
            tenant_id=tenant_id, actor_user_id=actor_user_id, note=note, ip_address=ip_address
        )

        previous_status = note.status
        note.status = POSTED
        note.accounting_posting_reference = accounting_reference
        note.gst_transaction_reference = gst_reference
        note.updated_by = actor_user_id
        note.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=f"{note.note_type}_POSTED",
            entity_type="credit_debit_note",
            entity_id=note.id,
            before={"status": previous_status},
            after={
                "status": POSTED,
                "accounting_posting_reference": accounting_reference,
                "gst_transaction_reference": gst_reference,
            },
            ip_address=ip_address,
        )

        customer_result = await self._session.execute(select(Customer.name).where(Customer.id == note.customer_id))
        customer_name = customer_result.scalar_one()
        lines_with_uom = await self._get_lines(note.id)
        return note, customer_name, invoice.invoice_number, lines_with_uom

    # --- cancel (DRAFT only — see model docstring for why) ------------------

    async def cancel_note(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        note_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> CreditDebitNote:
        note = await self._get_note_locked(tenant_id, note_id)
        check_row_version(note, expected_row_version)

        if note.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(
                "Only a draft note can be cancelled — a posted note has already affected accounting/GST "
                "and cancellation-with-reversal is not yet supported.",
                code=CDN_INVALID_STATUS,
            )

        previous_status = note.status
        note.status = CANCELLED
        note.updated_by = actor_user_id
        note.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=f"{note.note_type}_CANCELLED",
            entity_type="credit_debit_note",
            entity_id=note.id,
            before={"status": previous_status},
            after={"status": CANCELLED},
            ip_address=ip_address,
        )
        return note
