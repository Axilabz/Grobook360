"""Sales Return service (PROMPT-016).

The fifth Sales document type, and the first that reverses a prior
transaction instead of extending one. §2 is THE critical rule this file
is organized around: confirming a Sales Return creates exactly one STOCK
IN movement per line (through `InventoryService.post_movement`, never a
direct `stock_qty_cache` write) — the mirror image of Delivery Challan/
direct Sales Invoice's STOCK OUT.

Every return line MUST reference a specific Sales Invoice line
(`source_invoice_line_id`, §6/§12) so Returnable Quantity (§7 =
`invoice_line.quantity - invoice_line.returned_quantity`) can be computed
and validated — both at DRAFT time (a soft, non-authoritative convenience
check) and again under a row lock at confirm time (the authoritative
check; §18's mandatory concurrency test depends on this).

Pricing for a return line: a Sales Invoice line already carries its own
final price/discount/GST (unlike a Delivery Challan line, which has
none) — §15/§16/§17 resolve "does the return use the original invoice
price" as YES. The invoice line's absolute `discount_amount` (computed
for its FULL invoiced quantity) is converted to an equivalent discount
PERCENTAGE (`discount_amount / (quantity * unit_price) * 100`) before
calling `gst_calculation_service.calculate_line` with the RETURN's own
(possibly smaller, for a partial return) quantity — identical proration
technique to PROMPT-015's Delivery-Challan-to-Invoice pricing, for the
identical reason: a copied absolute discount would not scale correctly
for a partial return. GST treatment (intra/inter-state) is recomputed
via `determine_gst_treatment` using the invoice's own place-of-supply
snapshot, not re-derived from a possibly-since-changed Customer Master
row.

This service NEVER creates a Credit Note, NEVER posts a real accounting
reversal, and NEVER submits anything to GST — §21/§22's integration
boundaries are satisfied by calling `AccountingPostingService.
post_sales_return` / `GstReportingService.record_return_transaction`,
both of which only write an audit trail and return an opaque reference
string (see those services' own docstrings). §22 is explicit: Sales
Return and Credit Note are NOT the same entity, and no Credit Note
integration exists yet (PROMPT-017's own scope).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    SR_EXCEEDS_RETURNABLE,
    SR_INVALID_REASON,
    SR_INVALID_STATUS,
    SR_INVOICE_NOT_ELIGIBLE,
    SR_NOT_FOUND,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.sales_constants import SALES_RETURN
from app.models.customer import Customer
from app.models.sales_invoice import POSTED as SI_POSTED
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.sales_return import (
    CANCELLABLE_STATUSES,
    CANCELLED,
    CONFIRMED,
    DRAFT,
    OTHER,
    RETURN_REASONS,
    SalesReturn,
)
from app.models.sales_return_line import SalesReturnLine
from app.models.stock_ledger_entry import STOCK_IN
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.sales_return import ReturnLineInput
from app.services.accounting.accounting_posting_service import AccountingPostingService
from app.services.audit.audit_service import AuditService
from app.services.inventory.inventory_service import InventoryService
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.services.sales.gst_calculation_service import (
    calculate_document_totals,
    calculate_line,
    determine_gst_treatment,
)
from app.services.sales.gst_reporting_service import GstReportingService
from app.services.sales.sales_invoice_service import SalesInvoiceService
from app.services.sales.sales_validation_service import validate_customer_for_sale, validate_product_for_sale


@dataclass(frozen=True)
class SalesReturnPage:
    items: list[tuple[SalesReturn, str, str]]  # (return, customer_name, source_invoice_number)
    total_items: int


class SalesReturnService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared helpers -----------------------------------------------

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _get_return_locked(self, tenant_id: uuid.UUID, return_id: uuid.UUID) -> SalesReturn:
        result = await self._session.execute(
            select(SalesReturn)
            .where(SalesReturn.id == return_id, SalesReturn.tenant_id == tenant_id)
            .with_for_update()
        )
        sales_return = result.scalar_one_or_none()
        if sales_return is None:
            raise NotFoundError("Sales return not found", code=SR_NOT_FOUND)
        return sales_return

    async def _get_lines(self, return_id: uuid.UUID) -> list[tuple[SalesReturnLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(SalesReturnLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == SalesReturnLine.uom_id)
            .where(SalesReturnLine.sales_return_id == return_id)
            .order_by(SalesReturnLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    def _snapshot(self, sales_return: SalesReturn) -> dict:
        return {
            "source_invoice_id": str(sales_return.source_invoice_id),
            "customer_id": str(sales_return.customer_id),
            "return_date": sales_return.return_date.isoformat(),
            "status": sales_return.status,
            "return_reason": sales_return.return_reason,
            "grand_total": str(sales_return.grand_total),
        }

    # --- return eligibility (§7/§14 steps 5-7) -----------------------------

    async def get_return_eligibility(
        self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> tuple[SalesInvoice, str, list[tuple[SalesInvoiceLine, UnitOfMeasure]]]:
        invoice_service = SalesInvoiceService(self._session)
        invoice, customer_name, _dc_number, lines = await invoice_service.get_invoice(
            tenant_id=tenant_id, invoice_id=invoice_id
        )
        if invoice.status != SI_POSTED:
            raise ValidationAppError(
                f"An invoice in {invoice.status} status is not eligible for return.",
                code=SR_INVOICE_NOT_ELIGIBLE,
            )
        return invoice, customer_name, lines

    # --- queries ---------------------------------------------------------

    async def list_returns(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        search: str | None,
        status_filter: str | None,
        customer_id: uuid.UUID | None,
        return_reason_filter: str | None,
        source_invoice_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> SalesReturnPage:
        base = (
            select(SalesReturn, Customer.name, SalesInvoice.invoice_number)
            .join(Customer, Customer.id == SalesReturn.customer_id)
            .join(SalesInvoice, SalesInvoice.id == SalesReturn.source_invoice_id)
            .where(SalesReturn.tenant_id == tenant_id)
        )

        if search:
            like = f"%{search}%"
            base = base.where(
                or_(
                    SalesReturn.return_number.ilike(like),
                    SalesInvoice.invoice_number.ilike(like),
                    Customer.name.ilike(like),
                    Customer.customer_code.ilike(like),
                )
            )
        if status_filter:
            base = base.where(SalesReturn.status == status_filter)
        if customer_id:
            base = base.where(SalesReturn.customer_id == customer_id)
        if return_reason_filter:
            base = base.where(SalesReturn.return_reason == return_reason_filter)
        if source_invoice_id:
            base = base.where(SalesReturn.source_invoice_id == source_invoice_id)
        if date_from:
            base = base.where(SalesReturn.return_date >= date_from)
        if date_to:
            base = base.where(SalesReturn.return_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(SalesReturn.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(SalesReturn.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return SalesReturnPage(items=[(row[0], row[1], row[2]) for row in rows], total_items=total_items)

    async def get_return(
        self, *, tenant_id: uuid.UUID, return_id: uuid.UUID
    ) -> tuple[SalesReturn, str, str, list[tuple[SalesReturnLine, UnitOfMeasure]]]:
        result = await self._session.execute(
            select(SalesReturn, Customer.name, SalesInvoice.invoice_number)
            .join(Customer, Customer.id == SalesReturn.customer_id)
            .join(SalesInvoice, SalesInvoice.id == SalesReturn.source_invoice_id)
            .where(SalesReturn.id == return_id, SalesReturn.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Sales return not found", code=SR_NOT_FOUND)
        sales_return, customer_name, invoice_number = row
        lines = await self._get_lines(sales_return.id)
        return sales_return, customer_name, invoice_number, lines

    # --- line building (shared by create/update) ----------------------------

    def _validate_reason(self, return_reason: str, reason_description: str | None) -> None:
        if return_reason not in RETURN_REASONS:
            raise ValidationAppError(f"'{return_reason}' is not a recognized return reason.", code=SR_INVALID_REASON)
        if return_reason == OTHER and not (reason_description and reason_description.strip()):
            raise ValidationAppError("A reason description is required when return_reason is OTHER.", code=SR_INVALID_REASON)

    async def _build_lines(
        self,
        *,
        tenant_id: uuid.UUID,
        return_id: uuid.UUID,
        invoice_lines_by_id: dict[uuid.UUID, tuple[SalesInvoiceLine, UnitOfMeasure]],
        gst_treatment: str,
        line_inputs: list[ReturnLineInput],
    ) -> tuple[list[SalesReturnLine], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        """§7: validates each requested return quantity against the
        CURRENTLY-known returnable quantity (invoiced - returned_quantity).
        This is a DRAFT-time convenience check only — the authoritative,
        race-proof re-validation happens again in `confirm_return` under a
        lock (§18/§44), since a DRAFT by definition hasn't reserved
        anything yet."""
        lines: list[SalesReturnLine] = []
        calculated_lines = []
        total_quantity = Decimal("0")

        for index, line_input in enumerate(line_inputs, start=1):
            invoice_line_id = uuid.UUID(line_input.source_invoice_line_id)
            match = invoice_lines_by_id.get(invoice_line_id)
            if match is None:
                raise ValidationAppError(
                    "The selected invoice line does not belong to this sales invoice.",
                    code=SR_EXCEEDS_RETURNABLE,
                )
            invoice_line, uom = match

            returnable = invoice_line.quantity - invoice_line.returned_quantity
            if line_input.quantity > returnable:
                raise ValidationAppError(
                    f"Return quantity {line_input.quantity} exceeds returnable quantity {returnable}.",
                    code=SR_EXCEEDS_RETURNABLE,
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
            total_quantity += line_input.quantity

            lines.append(
                SalesReturnLine(
                    tenant_id=tenant_id,
                    sales_return_id=return_id,
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
            total_quantity,
            totals.subtotal,
            totals.total_discount,
            totals.total_taxable,
            totals.total_cgst,
            totals.total_sgst,
            totals.total_igst,
            totals.grand_total,
        )

    # --- create (DRAFT only) ------------------------------------------------

    async def create_return(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        source_invoice_id: uuid.UUID,
        return_date: date | None,
        return_reason: str,
        reason_description: str | None,
        notes: str | None,
        line_inputs: list[ReturnLineInput],
        ip_address: str | None,
    ) -> tuple[SalesReturn, str, str, list[tuple[SalesReturnLine, UnitOfMeasure]]]:
        self._validate_reason(return_reason, reason_description)

        tenant = await self._get_tenant(tenant_id)
        invoice, customer_name, invoice_lines = await self.get_return_eligibility(
            tenant_id=tenant_id, invoice_id=source_invoice_id
        )
        invoice_lines_by_id = {line.id: (line, uom) for line, uom in invoice_lines}

        # Tenant-scoped, active-customer re-check (§38 IDOR/tenant-isolation
        # discipline) even though the invoice already carries a snapshot.
        await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=invoice.customer_id)

        gst_treatment = determine_gst_treatment(
            supplier_state_code=tenant.state_code,
            customer_state_code=invoice.place_of_supply_state_code,
        )
        doc_date = return_date or date.today()

        numbering = DocumentNumberingService(self._session)
        return_number = await numbering.next_number(tenant=tenant, document_type=SALES_RETURN, prefix="SR")

        sales_return = SalesReturn(
            tenant_id=tenant_id,
            return_number=return_number,
            return_date=doc_date,
            source_invoice_id=invoice.id,
            customer_id=invoice.customer_id,
            customer_gstin=invoice.customer_gstin,
            billing_address=invoice.billing_address,
            shipping_address=invoice.shipping_address,
            place_of_supply_state_code=invoice.place_of_supply_state_code,
            status=DRAFT,
            return_reason=return_reason,
            reason_description=reason_description,
            notes=notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(sales_return)
        await self._session.flush()

        (
            lines,
            total_quantity,
            subtotal,
            discount_total,
            taxable_total,
            cgst_total,
            sgst_total,
            igst_total,
            grand_total,
        ) = await self._build_lines(
            tenant_id=tenant_id,
            return_id=sales_return.id,
            invoice_lines_by_id=invoice_lines_by_id,
            gst_treatment=gst_treatment,
            line_inputs=line_inputs,
        )
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        sales_return.total_return_quantity = total_quantity
        sales_return.subtotal = subtotal
        sales_return.discount_total = discount_total
        sales_return.taxable_total = taxable_total
        sales_return.cgst_total = cgst_total
        sales_return.sgst_total = sgst_total
        sales_return.igst_total = igst_total
        sales_return.tax_total = cgst_total + sgst_total + igst_total
        sales_return.grand_total = grand_total
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_RETURN_CREATED",
            entity_type="sales_return",
            entity_id=sales_return.id,
            after=self._snapshot(sales_return),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(sales_return.id)
        return sales_return, customer_name, invoice.invoice_number, lines_with_uom

    # --- update (DRAFT only) ------------------------------------------------

    async def update_return(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        return_id: uuid.UUID,
        expected_row_version: int,
        return_date: date | None,
        return_reason: str | None,
        reason_description: str | None,
        notes: str | None,
        line_inputs: list[ReturnLineInput] | None,
        ip_address: str | None,
    ) -> tuple[SalesReturn, str, str, list[tuple[SalesReturnLine, UnitOfMeasure]]]:
        sales_return = await self._get_return_locked(tenant_id, return_id)
        check_row_version(sales_return, expected_row_version)

        if sales_return.status != DRAFT:
            raise ValidationAppError(
                "This sales return has already been confirmed and cannot be edited.", code=SR_INVALID_STATUS
            )

        before = self._snapshot(sales_return)
        tenant = await self._get_tenant(tenant_id)

        effective_reason = return_reason if return_reason is not None else sales_return.return_reason
        effective_description = (
            reason_description if reason_description is not None else sales_return.reason_description
        )
        self._validate_reason(effective_reason, effective_description)

        if return_date is not None:
            sales_return.return_date = return_date
        if return_reason is not None:
            sales_return.return_reason = return_reason
        if reason_description is not None:
            sales_return.reason_description = reason_description
        if notes is not None:
            sales_return.notes = notes

        invoice_service = SalesInvoiceService(self._session)
        invoice, customer_name, _dc_number, invoice_lines = await invoice_service.get_invoice(
            tenant_id=tenant_id, invoice_id=sales_return.source_invoice_id
        )
        invoice_lines_by_id = {line.id: (line, uom) for line, uom in invoice_lines}

        if line_inputs is not None:
            gst_treatment = determine_gst_treatment(
                supplier_state_code=tenant.state_code,
                customer_state_code=invoice.place_of_supply_state_code,
            )
            existing_lines = await self._get_lines(sales_return.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            (
                lines,
                total_quantity,
                subtotal,
                discount_total,
                taxable_total,
                cgst_total,
                sgst_total,
                igst_total,
                grand_total,
            ) = await self._build_lines(
                tenant_id=tenant_id,
                return_id=sales_return.id,
                invoice_lines_by_id=invoice_lines_by_id,
                gst_treatment=gst_treatment,
                line_inputs=line_inputs,
            )
            for line in lines:
                line.created_by = actor_user_id
                line.updated_by = actor_user_id
                self._session.add(line)

            sales_return.total_return_quantity = total_quantity
            sales_return.subtotal = subtotal
            sales_return.discount_total = discount_total
            sales_return.taxable_total = taxable_total
            sales_return.cgst_total = cgst_total
            sales_return.sgst_total = sgst_total
            sales_return.igst_total = igst_total
            sales_return.tax_total = cgst_total + sgst_total + igst_total
            sales_return.grand_total = grand_total

        sales_return.updated_by = actor_user_id
        sales_return.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_RETURN_UPDATED",
            entity_type="sales_return",
            entity_id=sales_return.id,
            before=before,
            after=self._snapshot(sales_return),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(sales_return.id)
        return sales_return, customer_name, invoice.invoice_number, lines_with_uom

    # --- confirm (§17/§18: the atomic stock-IN + return-tracking core) -----

    async def confirm_return(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        return_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> tuple[SalesReturn, str, str, list[tuple[SalesReturnLine, UnitOfMeasure]]]:
        """One database transaction end-to-end (§16): validate -> lock
        source Sales Invoice -> re-validate returnable quantity against
        LIVE data -> post Stock IN per line -> update invoice
        returned_quantity -> record accounting/GST integration boundary
        entries -> mark CONFIRMED -> audit. Any failure anywhere rolls
        back everything (§16 explicit requirement: never CONFIRMED without
        Stock IN, never Stock IN without CONFIRMED)."""
        sales_return = await self._get_return_locked(tenant_id, return_id)
        check_row_version(sales_return, expected_row_version)

        if sales_return.status != DRAFT:
            raise ValidationAppError(f"Cannot confirm a sales return in {sales_return.status} status.", code=SR_INVALID_STATUS)

        invoice_service = SalesInvoiceService(self._session)
        # §18/§44: locks the Sales Invoice row so a concurrent confirm of a
        # DIFFERENT Sales Return against the SAME invoice cannot race — the
        # second transaction blocks here until the first fully commits,
        # the same pattern `DeliveryChallanService.confirm_challan` uses
        # against Sales Order.
        invoice = await invoice_service.get_invoice_locked(tenant_id, sales_return.source_invoice_id)
        if invoice.status != SI_POSTED:
            raise ValidationAppError(
                f"The source sales invoice is in {invoice.status} status and can no longer be returned against.",
                code=SR_INVOICE_NOT_ELIGIBLE,
            )

        # Fresh read, post-lock: sees any returned_quantity change already
        # committed by a concurrent Sales Return confirmation.
        invoice_lines = await invoice_service.get_lines(invoice.id)
        invoice_lines_by_id = {line.id: line for line, _uom in invoice_lines}

        return_lines = await self._get_lines(sales_return.id)
        inventory = InventoryService(self._session)
        location = await inventory.ensure_default_location(tenant_id)

        for return_line, return_uom in return_lines:
            invoice_line = invoice_lines_by_id.get(return_line.source_invoice_line_id)
            if invoice_line is None:
                raise ValidationAppError("The source invoice line no longer exists.", code=SR_EXCEEDS_RETURNABLE)

            live_returnable = invoice_line.quantity - invoice_line.returned_quantity
            if return_line.quantity > live_returnable:
                raise ValidationAppError(
                    f"Return quantity {return_line.quantity} exceeds returnable quantity {live_returnable}.",
                    code=SR_EXCEEDS_RETURNABLE,
                )

            invoice_line.returned_quantity += return_line.quantity
            invoice_line.updated_by = actor_user_id

            if return_line.product_id is not None:
                await validate_product_for_sale(self._session, tenant_id=tenant_id, product_id=return_line.product_id)
                product = await inventory.get_active_product_locked(tenant_id, return_line.product_id)

                await inventory.post_movement(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    product=product,
                    location=location,
                    movement_type=STOCK_IN,
                    quantity=return_line.quantity,
                    uom=return_uom,
                    # Per-line source_id — mirrors every prior stock-moving
                    # Sales document line's identical duplicate-movement
                    # protection reasoning.
                    source_type=SALES_RETURN,
                    source_id=return_line.id,
                    audit_action="STOCK_IN_CREATED",
                    audit_extra={
                        "sales_return_id": str(sales_return.id),
                        "sales_return_number": sales_return.return_number,
                        "source_invoice_id": str(invoice.id),
                    },
                    ip_address=ip_address,
                )

        accounting_reference = await AccountingPostingService(self._session).post_sales_return(
            tenant_id=tenant_id, actor_user_id=actor_user_id, sales_return=sales_return, ip_address=ip_address
        )
        gst_reference = await GstReportingService(self._session).record_return_transaction(
            tenant_id=tenant_id, actor_user_id=actor_user_id, sales_return=sales_return, ip_address=ip_address
        )

        previous_status = sales_return.status
        sales_return.status = CONFIRMED
        sales_return.accounting_posting_reference = accounting_reference
        sales_return.gst_transaction_reference = gst_reference
        sales_return.updated_by = actor_user_id
        sales_return.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_RETURN_CONFIRMED",
            entity_type="sales_return",
            entity_id=sales_return.id,
            before={"status": previous_status},
            after={
                "status": CONFIRMED,
                "accounting_posting_reference": accounting_reference,
                "gst_transaction_reference": gst_reference,
            },
            ip_address=ip_address,
        )

        customer_result = await self._session.execute(select(Customer.name).where(Customer.id == sales_return.customer_id))
        customer_name = customer_result.scalar_one()
        lines_with_uom = await self._get_lines(sales_return.id)
        return sales_return, customer_name, invoice.invoice_number, lines_with_uom

    # --- cancel (DRAFT only — see model docstring for why) ------------------

    async def cancel_return(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        return_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> SalesReturn:
        sales_return = await self._get_return_locked(tenant_id, return_id)
        check_row_version(sales_return, expected_row_version)

        if sales_return.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(
                "Only a draft sales return can be cancelled — a confirmed return has already increased "
                "stock and cancellation-with-reversal is not yet supported.",
                code=SR_INVALID_STATUS,
            )

        previous_status = sales_return.status
        sales_return.status = CANCELLED
        sales_return.updated_by = actor_user_id
        sales_return.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_RETURN_CANCELLED",
            entity_type="sales_return",
            entity_id=sales_return.id,
            before={"status": previous_status},
            after={"status": CANCELLED},
            ip_address=ip_address,
        )
        return sales_return
