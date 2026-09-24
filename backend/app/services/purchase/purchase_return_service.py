"""Purchase Return service (PROMPT-019).

Mirrors `sales_return_service.py`'s exact structure and safety
guarantees, mirrored: §13's critical rule — confirming a Purchase Return
creates exactly one STOCK OUT movement per line (goods physically moving
back to the supplier), the inverse of Sales Return's STOCK IN.

Every return line MUST reference a specific Purchase Invoice line
(`source_purchase_invoice_line_id`) so eligible remaining quantity can
be computed and validated — both at DRAFT time (soft check) and again
under a row lock at confirm time (authoritative check).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    PRET_EXCEEDS_RETURNABLE,
    PRET_INVALID_REASON,
    PRET_INVALID_STATUS,
    PRET_INVOICE_NOT_ELIGIBLE,
    PRET_NOT_FOUND,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.purchase_constants import PURCHASE_RETURN, PURCHASE_RETURN_REVERSAL
from app.models.audit_log import AuditLog
from app.models.goods_receipt import GoodsReceipt
from app.models.purchase_invoice import POSTED as PINV_POSTED
from app.models.purchase_invoice import PurchaseInvoice
from app.models.purchase_invoice_line import PurchaseInvoiceLine
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_return import (
    CANCELLABLE_STATUSES,
    CANCELLED,
    CONFIRMED,
    DRAFT,
    OTHER,
    RETURN_REASONS,
    PurchaseReturn,
)
from app.models.purchase_return_line import PurchaseReturnLine
from app.models.stock_ledger_entry import STOCK_IN, STOCK_OUT, StockLedgerEntry
from app.models.supplier import Supplier
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.purchase import ReturnLineInput
from app.services.accounting.accounting_posting_service import AccountingPostingService
from app.services.sales.gst_reporting_service import GstReportingService
from app.services.audit.audit_service import AuditService
from app.services.inventory.inventory_service import InventoryService
from app.services.purchase.purchase_invoice_service import PurchaseInvoiceService
from app.services.purchase.purchase_validation_service import validate_product_for_purchase
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.services.sales.gst_calculation_service import (
    calculate_document_totals,
    calculate_line,
    determine_gst_treatment,
)


@dataclass(frozen=True)
class PurchaseReturnPage:
    items: list[tuple[PurchaseReturn, str, str]]  # (return, supplier_name, source_invoice_number)
    total_items: int


class PurchaseReturnService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _get_return_locked(self, tenant_id: uuid.UUID, return_id: uuid.UUID) -> PurchaseReturn:
        result = await self._session.execute(
            select(PurchaseReturn).where(PurchaseReturn.id == return_id, PurchaseReturn.tenant_id == tenant_id).with_for_update()
        )
        purchase_return = result.scalar_one_or_none()
        if purchase_return is None:
            raise NotFoundError("Purchase return not found", code=PRET_NOT_FOUND)
        return purchase_return

    async def _get_lines(self, return_id: uuid.UUID) -> list[tuple[PurchaseReturnLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(PurchaseReturnLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == PurchaseReturnLine.uom_id)
            .where(PurchaseReturnLine.purchase_return_id == return_id)
            .order_by(PurchaseReturnLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    def _snapshot(self, purchase_return: PurchaseReturn) -> dict:
        return {
            "source_purchase_invoice_id": str(purchase_return.source_purchase_invoice_id),
            "supplier_id": str(purchase_return.supplier_id),
            "document_date": purchase_return.document_date.isoformat(),
            "status": purchase_return.status,
            "return_reason": purchase_return.return_reason,
            "grand_total": str(purchase_return.grand_total),
        }

    @staticmethod
    def _validate_reason(return_reason: str, reason_description: str | None) -> None:
        if return_reason not in RETURN_REASONS:
            raise ValidationAppError(f"'{return_reason}' is not a recognized return reason.", code=PRET_INVALID_REASON)
        if return_reason == OTHER and not (reason_description and reason_description.strip()):
            raise ValidationAppError("A reason description is required when return_reason is OTHER.", code=PRET_INVALID_REASON)

    async def stock_movement_info_for_lines(
        self, tenant_id: uuid.UUID, line_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID | None, bool]]:
        """§18/§42 Stock Impact Visibility, mirrors `GoodsReceiptService`/
        `PurchaseInvoiceService`'s own — for each Purchase Return line,
        the `stock_ledger_entry.id` its STOCK_OUT posted as, plus whether
        a compensating `PURCHASE_RETURN_REVERSAL` STOCK_IN has since been
        posted against it."""
        if not line_ids:
            return {}
        result = await self._session.execute(
            select(StockLedgerEntry.source_id, StockLedgerEntry.source_type, StockLedgerEntry.id)
            .where(
                StockLedgerEntry.tenant_id == tenant_id,
                StockLedgerEntry.source_type.in_([PURCHASE_RETURN, PURCHASE_RETURN_REVERSAL]),
                StockLedgerEntry.source_id.in_(line_ids),
            )
        )
        info: dict[uuid.UUID, tuple[uuid.UUID | None, bool]] = {}
        for source_id, source_type, entry_id in result.all():
            movement_id, reversed_flag = info.get(source_id, (None, False))
            if source_type == PURCHASE_RETURN:
                movement_id = entry_id
            else:
                reversed_flag = True
            info[source_id] = (movement_id, reversed_flag)
        return info

    # --- return eligibility ------------------------------------------------

    async def get_return_eligibility(
        self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> tuple[PurchaseInvoice, str, list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]]:
        invoice_service = PurchaseInvoiceService(self._session)
        invoice, supplier_name, _grn, _po, lines = await invoice_service.get_invoice(tenant_id=tenant_id, invoice_id=invoice_id)
        if invoice.status != PINV_POSTED:
            raise ValidationAppError(
                f"An invoice in {invoice.status} status is not eligible for return.", code=PRET_INVOICE_NOT_ELIGIBLE
            )
        return invoice, supplier_name, lines

    # --- queries ---------------------------------------------------------

    async def list_returns(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, search: str | None, status_filter: str | None,
        supplier_id: uuid.UUID | None, return_reason_filter: str | None, source_purchase_invoice_id: uuid.UUID | None,
        date_from: date | None, date_to: date | None,
    ) -> PurchaseReturnPage:
        base = (
            select(PurchaseReturn, Supplier.name, PurchaseInvoice.purchase_invoice_number)
            .join(Supplier, Supplier.id == PurchaseReturn.supplier_id)
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseReturn.source_purchase_invoice_id)
            .where(PurchaseReturn.tenant_id == tenant_id)
        )
        if search:
            like = f"%{search}%"
            base = base.where(or_(PurchaseReturn.purchase_return_number.ilike(like), PurchaseInvoice.purchase_invoice_number.ilike(like), Supplier.name.ilike(like)))
        if status_filter:
            base = base.where(PurchaseReturn.status == status_filter)
        if supplier_id:
            base = base.where(PurchaseReturn.supplier_id == supplier_id)
        if return_reason_filter:
            base = base.where(PurchaseReturn.return_reason == return_reason_filter)
        if source_purchase_invoice_id:
            base = base.where(PurchaseReturn.source_purchase_invoice_id == source_purchase_invoice_id)
        if date_from:
            base = base.where(PurchaseReturn.document_date >= date_from)
        if date_to:
            base = base.where(PurchaseReturn.document_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(PurchaseReturn.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(PurchaseReturn.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        return PurchaseReturnPage(items=[(row[0], row[1], row[2]) for row in rows], total_items=total_items)

    async def get_return(
        self, *, tenant_id: uuid.UUID, return_id: uuid.UUID
    ) -> tuple[PurchaseReturn, str, str, list[tuple[PurchaseReturnLine, UnitOfMeasure]]]:
        result = await self._session.execute(
            select(PurchaseReturn, Supplier.name, PurchaseInvoice.purchase_invoice_number)
            .join(Supplier, Supplier.id == PurchaseReturn.supplier_id)
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseReturn.source_purchase_invoice_id)
            .where(PurchaseReturn.id == return_id, PurchaseReturn.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Purchase return not found", code=PRET_NOT_FOUND)
        purchase_return, supplier_name, invoice_number = row
        lines = await self._get_lines(purchase_return.id)
        return purchase_return, supplier_name, invoice_number, lines

    # --- line building -------------------------------------------------

    def _eligible_quantity(self, invoice_line: PurchaseInvoiceLine) -> Decimal:
        return invoice_line.quantity - invoice_line.returned_quantity

    async def _build_lines(
        self, *, tenant_id: uuid.UUID, return_id: uuid.UUID, invoice_lines_by_id: dict[uuid.UUID, tuple[PurchaseInvoiceLine, UnitOfMeasure]],
        gst_treatment: str, line_inputs: list[ReturnLineInput],
    ) -> tuple[list[PurchaseReturnLine], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        lines: list[PurchaseReturnLine] = []
        calculated_lines = []

        for index, line_input in enumerate(line_inputs, start=1):
            invoice_line_id = uuid.UUID(line_input.source_purchase_invoice_line_id)
            match = invoice_lines_by_id.get(invoice_line_id)
            if match is None:
                raise ValidationAppError("The selected invoice line does not belong to this purchase invoice.", code=PRET_EXCEEDS_RETURNABLE)
            invoice_line, uom = match

            eligible = self._eligible_quantity(invoice_line)
            if line_input.quantity > eligible:
                raise ValidationAppError(f"Return quantity {line_input.quantity} exceeds returnable quantity {eligible}.", code=PRET_EXCEEDS_RETURNABLE)

            gross_invoiced = invoice_line.quantity * invoice_line.unit_price
            effective_discount_percent = (invoice_line.discount_amount / gross_invoiced * Decimal("100")) if gross_invoiced > 0 else Decimal("0")

            result = calculate_line(
                quantity=line_input.quantity, unit_price=invoice_line.unit_price, discount_percent=effective_discount_percent,
                discount_amount=None, gst_rate=invoice_line.gst_rate, gst_treatment=gst_treatment,
            )
            calculated_lines.append(result)

            lines.append(
                PurchaseReturnLine(
                    tenant_id=tenant_id, purchase_return_id=return_id, line_no=index, source_purchase_invoice_line_id=invoice_line.id,
                    product_id=invoice_line.product_id, description=invoice_line.description, hsn_code=invoice_line.hsn_code,
                    quantity=line_input.quantity, uom_id=uom.id, unit_price=invoice_line.unit_price,
                    discount_amount=result.discount_amount, taxable_amount=result.taxable_amount, gst_rate=invoice_line.gst_rate,
                    cgst_amount=result.cgst_amount, sgst_amount=result.sgst_amount, igst_amount=result.igst_amount, line_total=result.line_total,
                )
            )

        totals = calculate_document_totals(calculated_lines)
        return (lines, totals.subtotal, totals.total_discount, totals.total_taxable, totals.total_cgst, totals.total_sgst, totals.total_igst, totals.grand_total)

    # --- create (DRAFT only) ------------------------------------------------

    async def create_return(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_purchase_invoice_id: uuid.UUID, document_date: date | None,
        return_reason: str, reason_description: str | None, notes: str | None, line_inputs: list[ReturnLineInput], ip_address: str | None,
    ) -> tuple[PurchaseReturn, str, str, list[tuple[PurchaseReturnLine, UnitOfMeasure]]]:
        self._validate_reason(return_reason, reason_description)

        tenant = await self._get_tenant(tenant_id)
        invoice, supplier_name, invoice_lines = await self.get_return_eligibility(tenant_id=tenant_id, invoice_id=source_purchase_invoice_id)
        invoice_lines_by_id = {line.id: (line, uom) for line, uom in invoice_lines}

        gst_treatment = determine_gst_treatment(supplier_state_code=tenant.state_code, customer_state_code=invoice.place_of_supply_state_code)
        doc_date = document_date or date.today()

        numbering = DocumentNumberingService(self._session)
        return_number = await numbering.next_number(tenant=tenant, document_type=PURCHASE_RETURN, prefix="PRET")

        purchase_return = PurchaseReturn(
            tenant_id=tenant_id, purchase_return_number=return_number, supplier_id=invoice.supplier_id,
            supplier_gstin=invoice.supplier_gstin, place_of_supply_state_code=invoice.place_of_supply_state_code,
            source_purchase_invoice_id=invoice.id, document_date=doc_date, status=DRAFT, return_reason=return_reason,
            reason_description=reason_description, notes=notes, created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(purchase_return)
        await self._session.flush()

        lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
            await self._build_lines(
                tenant_id=tenant_id, return_id=purchase_return.id, invoice_lines_by_id=invoice_lines_by_id,
                gst_treatment=gst_treatment, line_inputs=line_inputs,
            )
        )
        total_quantity = sum((li.quantity for li in line_inputs), Decimal("0"))
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        purchase_return.total_return_quantity = total_quantity
        purchase_return.subtotal = subtotal
        purchase_return.discount_total = discount_total
        purchase_return.taxable_total = taxable_total
        purchase_return.cgst_total = cgst_total
        purchase_return.sgst_total = sgst_total
        purchase_return.igst_total = igst_total
        purchase_return.tax_total = cgst_total + sgst_total + igst_total
        purchase_return.grand_total = grand_total
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_RETURN_CREATED",
            entity_type="purchase_return", entity_id=purchase_return.id, after=self._snapshot(purchase_return), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(purchase_return.id)
        return purchase_return, supplier_name, invoice.purchase_invoice_number, lines_with_uom

    # --- update (DRAFT only) ------------------------------------------------

    async def update_return(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, return_id: uuid.UUID, expected_row_version: int,
        document_date: date | None, return_reason: str | None, reason_description: str | None, notes: str | None,
        line_inputs: list[ReturnLineInput] | None, ip_address: str | None,
    ) -> tuple[PurchaseReturn, str, str, list[tuple[PurchaseReturnLine, UnitOfMeasure]]]:
        purchase_return = await self._get_return_locked(tenant_id, return_id)
        check_row_version(purchase_return, expected_row_version)

        if purchase_return.status != DRAFT:
            raise ValidationAppError("This purchase return has already been confirmed and cannot be edited.", code=PRET_INVALID_STATUS)

        before = self._snapshot(purchase_return)
        tenant = await self._get_tenant(tenant_id)

        effective_reason = return_reason if return_reason is not None else purchase_return.return_reason
        effective_description = reason_description if reason_description is not None else purchase_return.reason_description
        self._validate_reason(effective_reason, effective_description)

        if document_date is not None:
            purchase_return.document_date = document_date
        if return_reason is not None:
            purchase_return.return_reason = return_reason
        if reason_description is not None:
            purchase_return.reason_description = reason_description
        if notes is not None:
            purchase_return.notes = notes

        invoice_service = PurchaseInvoiceService(self._session)
        invoice, supplier_name, _grn, _po, invoice_lines = await invoice_service.get_invoice(tenant_id=tenant_id, invoice_id=purchase_return.source_purchase_invoice_id)
        invoice_lines_by_id = {line.id: (line, uom) for line, uom in invoice_lines}

        if line_inputs is not None:
            gst_treatment = determine_gst_treatment(supplier_state_code=tenant.state_code, customer_state_code=invoice.place_of_supply_state_code)
            existing_lines = await self._get_lines(purchase_return.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
                await self._build_lines(
                    tenant_id=tenant_id, return_id=purchase_return.id, invoice_lines_by_id=invoice_lines_by_id,
                    gst_treatment=gst_treatment, line_inputs=line_inputs,
                )
            )
            total_quantity = sum((li.quantity for li in line_inputs), Decimal("0"))
            for line in lines:
                line.created_by = actor_user_id
                line.updated_by = actor_user_id
                self._session.add(line)

            purchase_return.total_return_quantity = total_quantity
            purchase_return.subtotal = subtotal
            purchase_return.discount_total = discount_total
            purchase_return.taxable_total = taxable_total
            purchase_return.cgst_total = cgst_total
            purchase_return.sgst_total = sgst_total
            purchase_return.igst_total = igst_total
            purchase_return.tax_total = cgst_total + sgst_total + igst_total
            purchase_return.grand_total = grand_total

        purchase_return.updated_by = actor_user_id
        purchase_return.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_RETURN_UPDATED",
            entity_type="purchase_return", entity_id=purchase_return.id, before=before, after=self._snapshot(purchase_return), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(purchase_return.id)
        return purchase_return, supplier_name, invoice.purchase_invoice_number, lines_with_uom

    # --- confirm (§13/§28: the atomic stock-OUT + return-tracking core) ----

    async def confirm_return(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, return_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> tuple[PurchaseReturn, str, str, list[tuple[PurchaseReturnLine, UnitOfMeasure]]]:
        purchase_return = await self._get_return_locked(tenant_id, return_id)
        check_row_version(purchase_return, expected_row_version)

        if purchase_return.status != DRAFT:
            raise ValidationAppError(f"Cannot confirm a purchase return in {purchase_return.status} status.", code=PRET_INVALID_STATUS)

        invoice_service = PurchaseInvoiceService(self._session)
        invoice = await invoice_service.get_invoice_locked(tenant_id, purchase_return.source_purchase_invoice_id)
        if invoice.status != PINV_POSTED:
            raise ValidationAppError(
                f"The source purchase invoice is in {invoice.status} status and can no longer be returned against.", code=PRET_INVOICE_NOT_ELIGIBLE
            )

        invoice_lines = await invoice_service.get_lines(invoice.id)
        invoice_lines_by_id = {line.id: line for line, _uom in invoice_lines}

        return_lines = await self._get_lines(purchase_return.id)
        inventory = InventoryService(self._session)
        location = await inventory.ensure_default_location(tenant_id)

        for return_line, return_uom in return_lines:
            invoice_line = invoice_lines_by_id.get(return_line.source_purchase_invoice_line_id)
            if invoice_line is None:
                raise ValidationAppError("The source invoice line no longer exists.", code=PRET_EXCEEDS_RETURNABLE)

            live_eligible = self._eligible_quantity(invoice_line)
            if return_line.quantity > live_eligible:
                raise ValidationAppError(f"Return quantity {return_line.quantity} exceeds returnable quantity {live_eligible}.", code=PRET_EXCEEDS_RETURNABLE)

            invoice_line.returned_quantity += return_line.quantity
            invoice_line.updated_by = actor_user_id

            if return_line.product_id is not None:
                await validate_product_for_purchase(self._session, tenant_id=tenant_id, product_id=return_line.product_id)
                product = await inventory.get_active_product_locked(tenant_id, return_line.product_id)

                await inventory.post_movement(
                    tenant_id=tenant_id, actor_user_id=actor_user_id, product=product, location=location,
                    movement_type=STOCK_OUT, quantity=return_line.quantity, uom=return_uom, source_type=PURCHASE_RETURN,
                    source_id=return_line.id, audit_action="STOCK_OUT_CREATED",
                    audit_extra={"purchase_return_id": str(purchase_return.id), "purchase_return_number": purchase_return.purchase_return_number, "source_purchase_invoice_id": str(invoice.id)},
                    ip_address=ip_address,
                )

        previous_status = purchase_return.status
        purchase_return.status = CONFIRMED
        purchase_return.updated_by = actor_user_id
        purchase_return.row_version += 1
        await self._session.flush()

        # PROMPT-025 §19: DR Accounts Payable, CR Purchase Return/
        # Inventory Adjustment + Input GST reversal.
        accounting_reference = await AccountingPostingService(self._session).post_purchase_return(
            tenant_id=tenant_id, actor_user_id=actor_user_id, purchase_return=purchase_return, ip_address=ip_address,
        )
        purchase_return.accounting_posting_reference = accounting_reference
        await self._session.flush()

        # PROMPT-026: reduces the tenant's Input GST/ITC position — the
        # return's own already-calculated GST totals (never recalculated)
        # are snapshotted with negative amounts (module docstring's sign
        # convention).
        gst_reference = await GstReportingService(self._session).record_purchase_return_transaction(
            tenant_id=tenant_id, actor_user_id=actor_user_id, purchase_return=purchase_return, ip_address=ip_address,
        )
        purchase_return.gst_transaction_reference = gst_reference
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_RETURN_CONFIRMED",
            entity_type="purchase_return", entity_id=purchase_return.id, before={"status": previous_status},
            after={
                "status": CONFIRMED, "accounting_posting_reference": accounting_reference,
                "gst_transaction_reference": gst_reference,
            },
            ip_address=ip_address,
        )

        supplier_result = await self._session.execute(select(Supplier.name).where(Supplier.id == purchase_return.supplier_id))
        supplier_name = supplier_result.scalar_one()
        lines_with_uom = await self._get_lines(purchase_return.id)
        return purchase_return, supplier_name, invoice.purchase_invoice_number, lines_with_uom

    # --- cancel (DRAFT: pure status flip; CONFIRMED: controlled reversal) --

    async def cancel_return(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, return_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> PurchaseReturn:
        """§33-35: cancelling a DRAFT return is a pure status change (no
        stock ever moved for it, INVARIANT 2). Cancelling a CONFIRMED
        return is a controlled REVERSAL, not a deletion — mirrors Goods
        Receipt's PROMPT-021 precedent exactly, one level down the chain
        (STOCK_IN compensating a STOCK_OUT, rather than the other way
        round). Unlike a DIRECT Purchase Invoice's own reversal, this can
        never be rejected for going negative — restocking previously
        removed goods can never drive stock negative. The original
        STOCK_OUT ledger entries are NEVER edited or deleted (INVARIANT
        10) — only compensated via a NEW `PURCHASE_RETURN_REVERSAL` entry
        per line (INVARIANT 11), and the source invoice line's own
        `returned_quantity` bookkeeping claim is released (§35)."""
        purchase_return = await self._get_return_locked(tenant_id, return_id)
        check_row_version(purchase_return, expected_row_version)

        if purchase_return.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(f"Cannot cancel a purchase return in {purchase_return.status} status.", code=PRET_INVALID_STATUS)

        previous_status = purchase_return.status

        if previous_status == DRAFT:
            purchase_return.status = CANCELLED
            purchase_return.updated_by = actor_user_id
            purchase_return.row_version += 1
            await self._session.flush()

            await AuditService(self._session).record(
                tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_RETURN_CANCELLED",
                entity_type="purchase_return", entity_id=purchase_return.id, before={"status": previous_status},
                after={"status": CANCELLED, "stock_reversed": False}, ip_address=ip_address,
            )
            return purchase_return

        # previous_status == CONFIRMED: controlled reversal.
        return_lines = await self._get_lines(purchase_return.id)

        invoice_service = PurchaseInvoiceService(self._session)
        invoice = await invoice_service.get_invoice_locked(tenant_id, purchase_return.source_purchase_invoice_id)
        invoice_lines = await invoice_service.get_lines(invoice.id)
        invoice_lines_by_id = {line.id: line for line, _uom in invoice_lines}

        inventory = InventoryService(self._session)
        location = await inventory.ensure_default_location(tenant_id)

        for return_line, return_uom in return_lines:
            if return_line.product_id is not None:
                product = await inventory.get_active_product_locked(tenant_id, return_line.product_id)

                # A compensating STOCK_IN can never fail the negative-stock
                # guard (it only ever increases stock), unlike a DIRECT
                # Purchase Invoice's own STOCK_OUT reversal.
                await inventory.post_movement(
                    tenant_id=tenant_id, actor_user_id=actor_user_id, product=product, location=location,
                    movement_type=STOCK_IN, quantity=return_line.quantity, uom=return_uom,
                    source_type=PURCHASE_RETURN_REVERSAL, source_id=return_line.id, audit_action="STOCK_OUT_REVERSED",
                    audit_extra={"purchase_return_id": str(purchase_return.id), "purchase_return_number": purchase_return.purchase_return_number, "reason": "PURCHASE_RETURN_CANCELLED"},
                    ip_address=ip_address,
                )

            invoice_line = invoice_lines_by_id.get(return_line.source_purchase_invoice_line_id)
            if invoice_line is not None:
                invoice_line.returned_quantity = max(Decimal("0"), invoice_line.returned_quantity - return_line.quantity)
                invoice_line.updated_by = actor_user_id

        purchase_return.status = CANCELLED
        purchase_return.updated_by = actor_user_id
        purchase_return.row_version += 1
        await self._session.flush()

        # PROMPT-025 §33/§34: reverses the ORIGINAL purchase return
        # journal via a new REVERSAL journal — never edits it.
        accounting_reference = await AccountingPostingService(self._session).reverse_purchase_return(
            tenant_id=tenant_id, actor_user_id=actor_user_id, return_id=purchase_return.id, ip_address=ip_address,
        )

        # PROMPT-026 §21/§33: reverses the ORIGINAL GST snapshot via a new
        # REVERSAL row — never edits it.
        gst_reversal_reference = await GstReportingService(self._session).reverse_purchase_return_transaction(
            tenant_id=tenant_id, actor_user_id=actor_user_id, return_id=purchase_return.id, ip_address=ip_address,
        )

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_RETURN_CANCELLED",
            entity_type="purchase_return", entity_id=purchase_return.id, before={"status": previous_status},
            after={
                "status": CANCELLED, "stock_reversed": True, "accounting_reversal_reference": accounting_reference,
                "gst_reversal_reference": gst_reversal_reference,
            },
            ip_address=ip_address,
        )
        return purchase_return

    # --- related documents / audit history (PROMPT-023) ---------------------

    async def get_related_documents(
        self, *, tenant_id: uuid.UUID, return_id: uuid.UUID
    ) -> tuple[PurchaseReturn, PurchaseInvoice, PurchaseOrder | None, list[GoodsReceipt]]:
        """§4/§44: the source Purchase Invoice this return was created
        against, plus (transitively, via that invoice's own related
        documents) the source Purchase Order and contributing Goods
        Receipts where applicable — reuses `PurchaseInvoiceService.
        get_related_documents` rather than re-deriving that traceability
        logic."""
        result = await self._session.execute(
            select(PurchaseReturn).where(PurchaseReturn.id == return_id, PurchaseReturn.tenant_id == tenant_id)
        )
        purchase_return = result.scalar_one_or_none()
        if purchase_return is None:
            raise NotFoundError("Purchase return not found", code=PRET_NOT_FOUND)

        invoice_service = PurchaseInvoiceService(self._session)
        invoice, order, goods_receipts, _returns = await invoice_service.get_related_documents(
            tenant_id=tenant_id, invoice_id=purchase_return.source_purchase_invoice_id
        )
        return purchase_return, invoice, order, goods_receipts

    async def get_audit_history(self, *, tenant_id: uuid.UUID, return_id: uuid.UUID) -> list[AuditLog]:
        """§48: the audit trail shown on the return detail screen —
        mirrors `PurchaseOrderService`/`GoodsReceiptService`/
        `PurchaseInvoiceService`'s own `get_audit_history` discipline
        (narrow, entity-scoped, tenant-ownership-checked first)."""
        exists_result = await self._session.execute(
            select(PurchaseReturn.id).where(PurchaseReturn.id == return_id, PurchaseReturn.tenant_id == tenant_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Purchase return not found", code=PRET_NOT_FOUND)

        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "purchase_return", AuditLog.entity_id == return_id)
            .order_by(AuditLog.occurred_at.asc())
        )
        return list(result.scalars().all())
