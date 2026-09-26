"""Sales Invoice service (PROMPT-015).

The fourth and final MVP Sales document type — the authoritative billing
transaction — built directly on PROMPT-011's foundation and reusing
PROMPT-013/014's Sales Order and Delivery Challan services.

§2 is THE critical rule this entire file is organized around:
- DIRECT_SALES_INVOICE posting calls `InventoryService.post_movement`
  itself (like `DeliveryChallanService.confirm_challan` does).
- DELIVERY_CHALLAN_SALES_INVOICE posting NEVER calls it — the source
  Delivery Challan already reduced stock at ITS OWN confirm time. Instead,
  posting increments `delivery_challan_line.invoiced_quantity`, the same
  deterministic per-line counter pattern `sales_order_line.delivered_quantity`
  already established for Sales Order fulfillment. This is how "has stock
  already been consumed by the source Delivery Challan" is answered
  deterministically (§16): it is answered by which CODE PATH executes
  (`invoice_type` branches BEFORE any stock code runs), not by inspecting
  the ledger and guessing.

Pricing for a DELIVERY_CHALLAN_SALES_INVOICE line: a Delivery Challan
line carries NO price/GST at all (PROMPT-014 — pure dispatch record).
Pricing is derived from the ORIGINATING Sales Order line (via
`delivery_challan_line.source_sales_order_line_id`), and PRORATED for the
invoice quantity being billed now (which may be less than what was
delivered, if partially invoicing): the Sales Order line's own
`discount_amount` was computed for its full ordered quantity, so it is
converted to an equivalent discount PERCENTAGE
(`discount_amount / (quantity * unit_price) * 100`) and then
`gst_calculation_service.calculate_line` is called with the invoice's own
(possibly smaller) quantity — the percentage naturally scales, which a
copied absolute amount would not. GST treatment (intra/inter-state) is
recomputed fresh via `determine_gst_treatment` using the invoice's own
customer/place-of-supply snapshot, since that is a property of
tenant+customer location, not of quantity, and recomputing it is no
different from what a manual/direct invoice already does.

Server-side calculation is authoritative (§17): a Direct Invoice's client-
submitted `SalesLineInput` values are always input only, recalculated
here — never trusted as pre-computed. A DC-based invoice never accepts
price/GST from the client at all (`InvoiceFromChallanLineInput` has no
such fields) — there is nothing to distrust because nothing is asked for.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    SI_EXCEEDS_INVOICEABLE,
    SI_INVALID_STATUS,
    SI_NOT_FOUND,
    SI_SOURCE_DC_NOT_CONFIRMED,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.sales_constants import SALES_INVOICE
from app.models.customer import Customer
from app.models.delivery_challan import CONFIRMED as DC_CONFIRMED
from app.models.delivery_challan import DeliveryChallan
from app.models.delivery_challan_line import DeliveryChallanLine
from app.models.sales_invoice import (
    B2B,
    B2C,
    CANCELLABLE_STATUSES,
    CANCELLED,
    DELIVERY_CHALLAN_SALES_INVOICE,
    DIRECT_SALES_INVOICE,
    DRAFT,
    POSTED,
    SalesInvoice,
)
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.sales_order_line import SalesOrderLine
from app.models.stock_ledger_entry import STOCK_OUT
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.sales_common import SalesLineInput
from app.schemas.sales_invoice import InvoiceFromChallanLineInput
from app.services.accounting.accounting_posting_service import AccountingPostingService
from app.services.audit.audit_service import AuditService
from app.services.inventory.inventory_service import InventoryService
from app.services.sales.delivery_challan_service import DeliveryChallanService
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.services.sales.gst_calculation_service import (
    calculate_document_totals,
    calculate_line,
    determine_gst_treatment,
)
from app.services.sales.gst_reporting_service import GstReportingService
from app.services.sales.sales_order_service import SalesOrderService
from app.services.sales.sales_validation_service import (
    validate_customer_for_sale,
    validate_product_for_sale,
)


@dataclass(frozen=True)
class SalesInvoicePage:
    items: list[tuple[SalesInvoice, str, str | None]]  # (invoice, customer_name, source_dc_number)
    total_items: int


class SalesInvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared helpers -----------------------------------------------

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _get_uom_or_raise(self, tenant_id: uuid.UUID, uom_id: uuid.UUID) -> UnitOfMeasure:
        result = await self._session.execute(
            select(UnitOfMeasure).where(UnitOfMeasure.id == uom_id, UnitOfMeasure.tenant_id == tenant_id)
        )
        unit = result.scalar_one_or_none()
        if unit is None:
            raise ValidationAppError("Select a valid unit.", code=SI_NOT_FOUND)
        return unit

    async def _get_invoice_locked(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> SalesInvoice:
        result = await self._session.execute(
            select(SalesInvoice)
            .where(SalesInvoice.id == invoice_id, SalesInvoice.tenant_id == tenant_id)
            .with_for_update()
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Sales invoice not found", code=SI_NOT_FOUND)
        return invoice

    async def _get_lines(self, invoice_id: uuid.UUID) -> list[tuple[SalesInvoiceLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(SalesInvoiceLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == SalesInvoiceLine.uom_id)
            .where(SalesInvoiceLine.invoice_id == invoice_id)
            .order_by(SalesInvoiceLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    # --- public entrypoints for PROMPT-016's SalesReturnService ------------

    async def get_invoice_locked(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> SalesInvoice:
        """Locks the Sales Invoice row so two concurrent return
        confirmations against the same invoice serialize instead of
        racing (§18/§44 of PROMPT-016) — the exact same pattern
        `DeliveryChallanService.get_challan_locked` already established
        for Sales Invoice's own confirm-time concurrency guarantee."""
        return await self._get_invoice_locked(tenant_id, invoice_id)

    async def get_lines(self, invoice_id: uuid.UUID) -> list[tuple[SalesInvoiceLine, UnitOfMeasure]]:
        return await self._get_lines(invoice_id)

    def _snapshot(self, invoice: SalesInvoice) -> dict:
        return {
            "customer_id": str(invoice.customer_id),
            "invoice_date": invoice.invoice_date.isoformat(),
            "invoice_type": invoice.invoice_type,
            "status": invoice.status,
            "grand_total": str(invoice.grand_total),
            "source_delivery_challan_id": str(invoice.source_delivery_challan_id)
            if invoice.source_delivery_challan_id
            else None,
        }

    # --- invoice eligibility (§13 steps 3-4 / DC line invoiceable qty) -----

    async def get_invoice_eligibility(
        self, *, tenant_id: uuid.UUID, challan_id: uuid.UUID
    ) -> tuple[DeliveryChallan, str, str, list[tuple[DeliveryChallanLine, UnitOfMeasure, SalesOrderLine]]]:
        dc_service = DeliveryChallanService(self._session)
        challan, customer_name, so_number, _created_by_name, _updated_by_name, dc_lines = await dc_service.get_challan(
            tenant_id=tenant_id, challan_id=challan_id
        )

        if challan.status != DC_CONFIRMED:
            raise ValidationAppError(
                f"A delivery challan in {challan.status} status is not eligible for invoicing.",
                code=SI_SOURCE_DC_NOT_CONFIRMED,
            )

        so_service = SalesOrderService(self._session)
        so_lines = await so_service.get_lines(challan.source_sales_order_id)
        so_lines_by_id = {line.id: line for line, _uom in so_lines}

        enriched = [(dc_line, uom, so_lines_by_id[dc_line.source_sales_order_line_id]) for dc_line, uom in dc_lines]
        return challan, customer_name, so_number, enriched

    # --- queries ---------------------------------------------------------

    async def list_invoices(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        search: str | None,
        status_filter: str | None,
        invoice_type_filter: str | None,
        customer_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> SalesInvoicePage:
        base = (
            select(SalesInvoice, Customer.name, DeliveryChallan.challan_number)
            .join(Customer, Customer.id == SalesInvoice.customer_id)
            .outerjoin(DeliveryChallan, DeliveryChallan.id == SalesInvoice.source_delivery_challan_id)
            .where(SalesInvoice.tenant_id == tenant_id)
        )

        if search:
            like = f"%{search}%"
            base = base.where(
                or_(
                    SalesInvoice.invoice_number.ilike(like),
                    DeliveryChallan.challan_number.ilike(like),
                    Customer.name.ilike(like),
                    Customer.customer_code.ilike(like),
                )
            )
        if status_filter:
            base = base.where(SalesInvoice.status == status_filter)
        if invoice_type_filter:
            base = base.where(SalesInvoice.invoice_type == invoice_type_filter)
        if customer_id:
            base = base.where(SalesInvoice.customer_id == customer_id)
        if date_from:
            base = base.where(SalesInvoice.invoice_date >= date_from)
        if date_to:
            base = base.where(SalesInvoice.invoice_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(SalesInvoice.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(SalesInvoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return SalesInvoicePage(items=[(row[0], row[1], row[2]) for row in rows], total_items=total_items)

    async def get_invoice(
        self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> tuple[SalesInvoice, str, str | None, list[tuple[SalesInvoiceLine, UnitOfMeasure]]]:
        result = await self._session.execute(
            select(SalesInvoice, Customer.name, DeliveryChallan.challan_number)
            .join(Customer, Customer.id == SalesInvoice.customer_id)
            .outerjoin(DeliveryChallan, DeliveryChallan.id == SalesInvoice.source_delivery_challan_id)
            .where(SalesInvoice.id == invoice_id, SalesInvoice.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Sales invoice not found", code=SI_NOT_FOUND)
        invoice, customer_name, dc_number = row
        lines = await self._get_lines(invoice.id)
        return invoice, customer_name, dc_number, lines

    # --- create: direct ----------------------------------------------------

    async def _build_direct_lines(
        self,
        *,
        tenant_id: uuid.UUID,
        invoice_id: uuid.UUID,
        line_inputs: list[SalesLineInput],
        gst_treatment: str,
    ) -> tuple[list[SalesInvoiceLine], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        lines: list[SalesInvoiceLine] = []
        calculated_lines = []

        for index, line_input in enumerate(line_inputs, start=1):
            validated_product = await validate_product_for_sale(
                self._session, tenant_id=tenant_id, product_id=uuid.UUID(line_input.product_id)
            )
            uom = await self._get_uom_or_raise(tenant_id, uuid.UUID(line_input.uom_id))
            product = validated_product.product

            result = calculate_line(
                quantity=line_input.quantity,
                unit_price=line_input.unit_price,
                discount_percent=line_input.discount_percent,
                discount_amount=line_input.discount_amount,
                gst_rate=product.gst_rate or Decimal("0"),
                gst_treatment=gst_treatment,
            )
            calculated_lines.append(result)

            lines.append(
                SalesInvoiceLine(
                    tenant_id=tenant_id,
                    invoice_id=invoice_id,
                    line_no=index,
                    product_id=product.id,
                    description=product.name,
                    hsn_code=product.hsn_code,
                    quantity=line_input.quantity,
                    uom_id=uom.id,
                    unit_price=line_input.unit_price,
                    discount_amount=result.discount_amount,
                    taxable_amount=result.taxable_amount,
                    gst_rate=product.gst_rate or Decimal("0"),
                    cgst_amount=result.cgst_amount,
                    sgst_amount=result.sgst_amount,
                    igst_amount=result.igst_amount,
                    line_total=result.line_total,
                    source_delivery_challan_line_id=None,
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

    async def create_direct_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        invoice_date: date | None,
        shipping_address: str | None,
        notes: str | None,
        line_inputs: list[SalesLineInput],
        ip_address: str | None,
    ) -> tuple[SalesInvoice, str, str | None, list[tuple[SalesInvoiceLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        validated_customer = await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=customer_id)
        customer = validated_customer.customer

        gst_treatment = determine_gst_treatment(
            supplier_state_code=tenant.state_code, customer_state_code=customer.state_code
        )
        doc_date = invoice_date or date.today()

        numbering = DocumentNumberingService(self._session)
        invoice_number = await numbering.next_number(tenant=tenant, document_type=SALES_INVOICE, prefix="INV")

        invoice = SalesInvoice(
            tenant_id=tenant_id,
            invoice_number=invoice_number,
            invoice_date=doc_date,
            invoice_type=DIRECT_SALES_INVOICE,
            customer_id=customer.id,
            customer_gstin=customer.gstin,
            customer_type=B2B if validated_customer.is_b2b else B2C,
            billing_address=customer.address,
            shipping_address=shipping_address or customer.address,
            place_of_supply_state_code=customer.state_code,
            source_delivery_challan_id=None,
            source_sales_order_id=None,
            status=DRAFT,
            notes=notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(invoice)
        await self._session.flush()

        lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
            await self._build_direct_lines(
                tenant_id=tenant_id, invoice_id=invoice.id, line_inputs=line_inputs, gst_treatment=gst_treatment
            )
        )
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        invoice.subtotal = subtotal
        invoice.discount_total = discount_total
        invoice.taxable_total = taxable_total
        invoice.cgst_total = cgst_total
        invoice.sgst_total = sgst_total
        invoice.igst_total = igst_total
        invoice.tax_total = cgst_total + sgst_total + igst_total
        invoice.grand_total = grand_total
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_INVOICE_CREATED",
            entity_type="sales_invoice",
            entity_id=invoice.id,
            after=self._snapshot(invoice),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(invoice.id)
        return invoice, customer.name, None, lines_with_uom

    # --- create: from Delivery Challan --------------------------------------

    async def create_invoice_from_challan(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        challan_id: uuid.UUID,
        invoice_date: date | None,
        notes: str | None,
        line_inputs: list[InvoiceFromChallanLineInput],
        ip_address: str | None,
    ) -> tuple[SalesInvoice, str, str | None, list[tuple[SalesInvoiceLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        challan, _customer_name, _so_number, eligibility_lines = await self.get_invoice_eligibility(
            tenant_id=tenant_id, challan_id=challan_id
        )
        eligibility_by_id = {dc_line.id: (dc_line, uom, so_line) for dc_line, uom, so_line in eligibility_lines}

        validated_customer = await validate_customer_for_sale(
            self._session, tenant_id=tenant_id, customer_id=challan.customer_id
        )
        customer = validated_customer.customer

        gst_treatment = determine_gst_treatment(
            supplier_state_code=tenant.state_code,
            customer_state_code=challan.place_of_supply_state_code or customer.state_code,
        )
        doc_date = invoice_date or date.today()

        numbering = DocumentNumberingService(self._session)
        invoice_number = await numbering.next_number(tenant=tenant, document_type=SALES_INVOICE, prefix="INV")

        invoice = SalesInvoice(
            tenant_id=tenant_id,
            invoice_number=invoice_number,
            invoice_date=doc_date,
            invoice_type=DELIVERY_CHALLAN_SALES_INVOICE,
            customer_id=customer.id,
            # DeliveryChallan itself carries no GSTIN snapshot (PROMPT-014
            # has no pricing/tax fields at all) — read it from Customer
            # Master directly, same as a direct invoice would.
            customer_gstin=customer.gstin,
            customer_type=B2B if validated_customer.is_b2b else B2C,
            billing_address=challan.billing_address,
            shipping_address=challan.shipping_address,
            place_of_supply_state_code=challan.place_of_supply_state_code,
            source_delivery_challan_id=challan.id,
            source_sales_order_id=challan.source_sales_order_id,
            status=DRAFT,
            notes=notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(invoice)
        await self._session.flush()

        lines: list[SalesInvoiceLine] = []
        calculated_lines = []

        for index, line_input in enumerate(line_inputs, start=1):
            dc_line_id = uuid.UUID(line_input.source_delivery_challan_line_id)
            match = eligibility_by_id.get(dc_line_id)
            if match is None:
                raise ValidationAppError(
                    "The selected delivery challan line does not belong to this delivery challan.",
                    code=SI_EXCEEDS_INVOICEABLE,
                )
            dc_line, uom, so_line = match

            invoiceable = dc_line.current_delivery_quantity - dc_line.invoiced_quantity
            if line_input.quantity > invoiceable:
                raise ValidationAppError(
                    f"Invoice quantity {line_input.quantity} exceeds invoiceable quantity {invoiceable}.",
                    code=SI_EXCEEDS_INVOICEABLE,
                )

            gross_ordered = so_line.quantity * so_line.unit_price
            effective_discount_percent = (
                (so_line.discount_amount / gross_ordered * Decimal("100")) if gross_ordered > 0 else Decimal("0")
            )

            result = calculate_line(
                quantity=line_input.quantity,
                unit_price=so_line.unit_price,
                discount_percent=effective_discount_percent,
                discount_amount=None,
                gst_rate=so_line.gst_rate,
                gst_treatment=gst_treatment,
            )
            calculated_lines.append(result)

            lines.append(
                SalesInvoiceLine(
                    tenant_id=tenant_id,
                    invoice_id=invoice.id,
                    line_no=index,
                    product_id=dc_line.product_id,
                    description=dc_line.description,
                    hsn_code=dc_line.hsn_code,
                    quantity=line_input.quantity,
                    uom_id=dc_line.uom_id,
                    unit_price=so_line.unit_price,
                    discount_amount=result.discount_amount,
                    taxable_amount=result.taxable_amount,
                    gst_rate=so_line.gst_rate,
                    cgst_amount=result.cgst_amount,
                    sgst_amount=result.sgst_amount,
                    igst_amount=result.igst_amount,
                    line_total=result.line_total,
                    source_delivery_challan_line_id=dc_line.id,
                )
            )

        totals = calculate_document_totals(calculated_lines)
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        invoice.subtotal = totals.subtotal
        invoice.discount_total = totals.total_discount
        invoice.taxable_total = totals.total_taxable
        invoice.cgst_total = totals.total_cgst
        invoice.sgst_total = totals.total_sgst
        invoice.igst_total = totals.total_igst
        invoice.tax_total = totals.total_cgst + totals.total_sgst + totals.total_igst
        invoice.grand_total = totals.grand_total
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_INVOICE_CREATED",
            entity_type="sales_invoice",
            entity_id=invoice.id,
            after=self._snapshot(invoice),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(invoice.id)
        return invoice, customer.name, challan.challan_number, lines_with_uom

    # --- update (DRAFT only) ------------------------------------------------

    async def update_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        invoice_id: uuid.UUID,
        expected_row_version: int,
        invoice_date: date | None,
        shipping_address: str | None,
        notes: str | None,
        line_inputs: list[SalesLineInput] | None,
        ip_address: str | None,
    ) -> tuple[SalesInvoice, str, str | None, list[tuple[SalesInvoiceLine, UnitOfMeasure]]]:
        invoice = await self._get_invoice_locked(tenant_id, invoice_id)
        check_row_version(invoice, expected_row_version)

        if invoice.status != DRAFT:
            raise ValidationAppError(
                "This invoice has already been posted and cannot be edited.", code=SI_INVALID_STATUS
            )
        if line_inputs is not None and invoice.invoice_type == DELIVERY_CHALLAN_SALES_INVOICE:
            raise ValidationAppError(
                "Line quantities on a delivery-challan-based invoice cannot be edited — cancel and "
                "recreate it instead.",
                code=SI_INVALID_STATUS,
            )

        before = self._snapshot(invoice)
        tenant = await self._get_tenant(tenant_id)

        customer_result = await self._session.execute(select(Customer).where(Customer.id == invoice.customer_id))
        customer = customer_result.scalar_one()

        if invoice_date is not None:
            invoice.invoice_date = invoice_date
        if shipping_address is not None:
            invoice.shipping_address = shipping_address
        if notes is not None:
            invoice.notes = notes

        if line_inputs is not None:
            gst_treatment = determine_gst_treatment(
                supplier_state_code=tenant.state_code, customer_state_code=customer.state_code
            )
            existing_lines = await self._get_lines(invoice.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
                await self._build_direct_lines(
                    tenant_id=tenant_id, invoice_id=invoice.id, line_inputs=line_inputs, gst_treatment=gst_treatment
                )
            )
            for line in lines:
                line.created_by = actor_user_id
                line.updated_by = actor_user_id
                self._session.add(line)

            invoice.subtotal = subtotal
            invoice.discount_total = discount_total
            invoice.taxable_total = taxable_total
            invoice.cgst_total = cgst_total
            invoice.sgst_total = sgst_total
            invoice.igst_total = igst_total
            invoice.tax_total = cgst_total + sgst_total + igst_total
            invoice.grand_total = grand_total

        invoice.updated_by = actor_user_id
        invoice.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_INVOICE_UPDATED",
            entity_type="sales_invoice",
            entity_id=invoice.id,
            before=before,
            after=self._snapshot(invoice),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(invoice.id)
        dc_number = None
        if invoice.source_delivery_challan_id:
            dc_result = await self._session.execute(
                select(DeliveryChallan.challan_number).where(DeliveryChallan.id == invoice.source_delivery_challan_id)
            )
            dc_number = dc_result.scalar_one_or_none()
        return invoice, customer.name, dc_number, lines_with_uom

    # --- post (§20: the atomic stock/accounting/GST core) -------------------

    async def post_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        invoice_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> tuple[SalesInvoice, str, str | None, list[tuple[SalesInvoiceLine, UnitOfMeasure]]]:
        invoice = await self._get_invoice_locked(tenant_id, invoice_id)
        check_row_version(invoice, expected_row_version)

        if invoice.status != DRAFT:
            raise ValidationAppError(f"Cannot post an invoice in {invoice.status} status.", code=SI_INVALID_STATUS)

        await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=invoice.customer_id)
        lines = await self._get_lines(invoice.id)

        dc_number: str | None = None

        if invoice.invoice_type == DIRECT_SALES_INVOICE:
            # §2 Scenario A: this invoice OWNS the stock-out.
            inventory = InventoryService(self._session)
            location = await inventory.ensure_default_location(tenant_id)
            for line, uom in lines:
                if line.product_id is not None:
                    await validate_product_for_sale(self._session, tenant_id=tenant_id, product_id=line.product_id)
                    product = await inventory.get_active_product_locked(tenant_id, line.product_id)
                    await inventory.post_movement(
                        tenant_id=tenant_id,
                        actor_user_id=actor_user_id,
                        product=product,
                        location=location,
                        movement_type=STOCK_OUT,
                        quantity=line.quantity,
                        uom=uom,
                        source_type=SALES_INVOICE,
                        source_id=line.id,
                        audit_action="STOCK_OUT_CREATED",
                        audit_extra={
                            "sales_invoice_id": str(invoice.id),
                            "sales_invoice_number": invoice.invoice_number,
                        },
                        ip_address=ip_address,
                    )
        else:
            # §2 Scenario B / §15/§16: NO stock movement — the source
            # Delivery Challan already moved stock. Locking it here is
            # what serializes concurrent invoice postings against the
            # SAME challan (§38), the same pattern
            # `DeliveryChallanService.confirm_challan` uses for its own
            # concurrency guarantee against Sales Order.
            dc_service = DeliveryChallanService(self._session)
            challan = await dc_service.get_challan_locked(tenant_id, invoice.source_delivery_challan_id)
            if challan.status != DC_CONFIRMED:
                raise ValidationAppError(
                    f"The source delivery challan is in {challan.status} status and can no longer be invoiced.",
                    code=SI_SOURCE_DC_NOT_CONFIRMED,
                )
            dc_number = challan.challan_number

            dc_lines = await dc_service.get_lines(challan.id)
            dc_lines_by_id = {dc_line.id: dc_line for dc_line, _uom in dc_lines}

            for line, _uom in lines:
                dc_line = dc_lines_by_id.get(line.source_delivery_challan_line_id)
                if dc_line is None:
                    raise ValidationAppError(
                        "The source delivery challan line no longer exists.", code=SI_EXCEEDS_INVOICEABLE
                    )
                live_invoiceable = dc_line.current_delivery_quantity - dc_line.invoiced_quantity
                if line.quantity > live_invoiceable:
                    raise ValidationAppError(
                        f"Invoice quantity {line.quantity} exceeds invoiceable quantity {live_invoiceable}.",
                        code=SI_EXCEEDS_INVOICEABLE,
                    )
                dc_line.invoiced_quantity += line.quantity
                dc_line.updated_by = actor_user_id
                if line.product_id is not None:
                    await validate_product_for_sale(self._session, tenant_id=tenant_id, product_id=line.product_id)

        accounting_reference = await AccountingPostingService(self._session).post_sales_invoice(
            tenant_id=tenant_id, actor_user_id=actor_user_id, invoice=invoice, ip_address=ip_address
        )
        gst_reference = await GstReportingService(self._session).record_invoice_transaction(
            tenant_id=tenant_id, actor_user_id=actor_user_id, invoice=invoice, ip_address=ip_address
        )

        previous_status = invoice.status
        invoice.status = POSTED
        invoice.accounting_posting_reference = accounting_reference
        invoice.gst_transaction_reference = gst_reference
        invoice.updated_by = actor_user_id
        invoice.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_INVOICE_POSTED",
            entity_type="sales_invoice",
            entity_id=invoice.id,
            before={"status": previous_status},
            after={"status": POSTED, "accounting_posting_reference": accounting_reference, "gst_transaction_reference": gst_reference},
            ip_address=ip_address,
        )

        customer_result = await self._session.execute(select(Customer.name).where(Customer.id == invoice.customer_id))
        customer_name = customer_result.scalar_one()
        lines_with_uom = await self._get_lines(invoice.id)
        return invoice, customer_name, dc_number, lines_with_uom

    # --- cancel (DRAFT only — see model docstring for why) ------------------

    async def cancel_invoice(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        invoice_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> SalesInvoice:
        invoice = await self._get_invoice_locked(tenant_id, invoice_id)
        check_row_version(invoice, expected_row_version)

        if invoice.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(
                "Only a draft invoice can be cancelled — a posted invoice has already affected stock/"
                "accounting/GST and cancellation-with-reversal is not yet supported.",
                code=SI_INVALID_STATUS,
            )

        previous_status = invoice.status
        invoice.status = CANCELLED
        invoice.updated_by = actor_user_id
        invoice.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_INVOICE_CANCELLED",
            entity_type="sales_invoice",
            entity_id=invoice.id,
            before={"status": previous_status},
            after={"status": CANCELLED},
            ip_address=ip_address,
        )
        return invoice
