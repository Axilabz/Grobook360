"""Purchase Invoice service (PROMPT-019).

Mirrors `sales_invoice_service.py`'s central rule, inverted for
Purchase: §12 is THE critical business rule this file is organized
around —
- DIRECT_PURCHASE_INVOICE posting calls `InventoryService.post_movement`
  itself (like `GoodsReceiptService.confirm_receipt` does).
- GOODS_RECEIPT_PURCHASE_INVOICE posting NEVER calls it — the source
  Goods Receipt already increased stock at ITS OWN confirm time. Instead,
  posting increments `goods_receipt_line.invoiced_quantity`.

Pricing for a GOODS_RECEIPT_PURCHASE_INVOICE line: a Goods Receipt line
DOES carry price/GST (unlike a Delivery Challan line, which carries
none) — copied verbatim from the PO line at GR-build time. So unlike
Sales Invoice's DC-based proration, a GR-based Purchase Invoice line
reuses the GR line's own price/GST directly, scaled only by the
(possibly smaller, for partial invoicing) quantity actually being
billed now — no discount-to-percentage conversion is needed since
`goods_receipt_line.discount_amount` is always 0 in this foundation (no
receipt-time discount input exists — §16 discount is captured at PO/
direct-invoice line entry only, a documented scope simplification, see
PROMPT-019-NOTES.md).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    PINV_EXCEEDS_INVOICEABLE,
    PINV_HAS_DOWNSTREAM_RETURN,
    PINV_INVALID_STATUS,
    PINV_NOT_FOUND,
    PINV_SOURCE_GR_NOT_CONFIRMED,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.purchase_constants import PURCHASE_INVOICE, PURCHASE_INVOICE_REVERSAL
from app.models.audit_log import AuditLog
from app.models.goods_receipt import CONFIRMED as GR_CONFIRMED
from app.models.goods_receipt import GoodsReceipt
from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.purchase_invoice import (
    CANCELLABLE_STATUSES,
    CANCELLED,
    DIRECT_PURCHASE_INVOICE,
    DRAFT,
    GOODS_RECEIPT_PURCHASE_INVOICE,
    NO_STOCK_IMPACT_INVOICE_TYPES,
    POSTED,
    PURCHASE_ORDER_PURCHASE_INVOICE,
    PurchaseInvoice,
)
from app.models.purchase_invoice_line import PurchaseInvoiceLine
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.purchase_return import PurchaseReturn
from app.models.stock_ledger_entry import STOCK_IN, STOCK_OUT, StockLedgerEntry
from app.models.supplier import Supplier
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.purchase import (
    DirectPurchaseInvoiceLineInput,
    InvoiceFromPurchaseOrderLineInput,
    InvoiceFromReceiptLineInput,
)
from app.services.accounting.accounting_posting_service import AccountingPostingService
from app.services.audit.audit_service import AuditService
from app.services.sales.gst_reporting_service import GstReportingService
from app.services.inventory.inventory_service import InventoryService
from app.services.purchase.goods_receipt_service import GoodsReceiptService
from app.services.purchase.purchase_order_service import PurchaseOrderService
from app.services.purchase.purchase_validation_service import (
    validate_product_for_purchase,
    validate_supplier_for_purchase,
)
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.services.sales.gst_calculation_service import (
    calculate_document_totals,
    calculate_line,
    determine_gst_treatment,
)


@dataclass(frozen=True)
class PurchaseInvoicePage:
    items: list[tuple[PurchaseInvoice, str, str | None, str | None]]  # (invoice, supplier_name, source_grn_number, source_po_number)
    total_items: int


@dataclass(frozen=True)
class POInvoiceEligibilityLine:
    purchase_order_line: PurchaseOrderLine
    uom: UnitOfMeasure
    invoiced_quantity: Decimal
    invoiceable_quantity: Decimal


class PurchaseInvoiceService:
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
            raise ValidationAppError("Select a valid unit.", code=PINV_NOT_FOUND)
        return unit

    async def _get_invoice_locked(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> PurchaseInvoice:
        result = await self._session.execute(
            select(PurchaseInvoice).where(PurchaseInvoice.id == invoice_id, PurchaseInvoice.tenant_id == tenant_id).with_for_update()
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Purchase invoice not found", code=PINV_NOT_FOUND)
        return invoice

    async def _get_lines(self, invoice_id: uuid.UUID) -> list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(PurchaseInvoiceLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == PurchaseInvoiceLine.uom_id)
            .where(PurchaseInvoiceLine.purchase_invoice_id == invoice_id)
            .order_by(PurchaseInvoiceLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    # --- public entrypoints for PurchaseReturnService -----------------------

    async def get_invoice_locked(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> PurchaseInvoice:
        return await self._get_invoice_locked(tenant_id, invoice_id)

    async def get_lines(self, invoice_id: uuid.UUID) -> list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]:
        return await self._get_lines(invoice_id)

    def _snapshot(self, invoice: PurchaseInvoice) -> dict:
        return {
            "supplier_id": str(invoice.supplier_id),
            "document_date": invoice.document_date.isoformat(),
            "invoice_type": invoice.invoice_type,
            "status": invoice.status,
            "grand_total": str(invoice.grand_total),
            "source_goods_receipt_id": str(invoice.source_goods_receipt_id) if invoice.source_goods_receipt_id else None,
            "source_purchase_order_id": str(invoice.source_purchase_order_id) if invoice.source_purchase_order_id else None,
            "supplier_invoice_number": invoice.supplier_invoice_number,
        }

    async def check_duplicate_supplier_invoice(
        self, *, tenant_id: uuid.UUID, supplier_id: uuid.UUID, supplier_invoice_number: str | None,
        exclude_invoice_id: uuid.UUID | None = None,
    ) -> bool:
        """§7: non-blocking duplicate-supplier-invoice-number DETECTION —
        the final uniqueness policy (tenant+supplier+supplier_invoice_
        number) is an explicit Open Decision, not enforced at the
        database level. Callers surface this as a warning, never a
        rejection."""
        if not supplier_invoice_number:
            return False
        query = select(PurchaseInvoice.id).where(
            PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.supplier_id == supplier_id,
            PurchaseInvoice.supplier_invoice_number == supplier_invoice_number, PurchaseInvoice.status != CANCELLED,
        )
        if exclude_invoice_id is not None:
            query = query.where(PurchaseInvoice.id != exclude_invoice_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none() is not None

    async def stock_movement_info_for_lines(
        self, tenant_id: uuid.UUID, line_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID | None, bool]]:
        """§46/§42-style Stock Impact Visibility, mirrors
        `GoodsReceiptService.stock_movement_info_for_lines` exactly —
        for each Purchase Invoice line, the `stock_ledger_entry.id` its
        STOCK_IN posted as (only ever populated for a DIRECT invoice's
        lines), plus whether a compensating `PURCHASE_INVOICE_REVERSAL`
        has since been posted against it."""
        if not line_ids:
            return {}
        result = await self._session.execute(
            select(StockLedgerEntry.source_id, StockLedgerEntry.source_type, StockLedgerEntry.id)
            .where(
                StockLedgerEntry.tenant_id == tenant_id,
                StockLedgerEntry.source_type.in_([PURCHASE_INVOICE, PURCHASE_INVOICE_REVERSAL]),
                StockLedgerEntry.source_id.in_(line_ids),
            )
        )
        info: dict[uuid.UUID, tuple[uuid.UUID | None, bool]] = {}
        for source_id, source_type, entry_id in result.all():
            movement_id, reversed_flag = info.get(source_id, (None, False))
            if source_type == PURCHASE_INVOICE:
                movement_id = entry_id
            else:
                reversed_flag = True
            info[source_id] = (movement_id, reversed_flag)
        return info

    async def _invoiced_quantity_by_po_line(self, po_line_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        """Aggregates `goods_receipt_line.invoiced_quantity` across ALL
        of a PO line's contributing GR lines — the authoritative
        "previously invoiced" figure for §10/§26's PO-level invoiceable-
        quantity formula, regardless of whether each unit was billed via
        a single-GR invoice or a PO-consolidated one (both increment the
        SAME counter — INVARIANT 5)."""
        if not po_line_ids:
            return {}
        result = await self._session.execute(
            select(GoodsReceiptLine.source_purchase_order_line_id, func.coalesce(func.sum(GoodsReceiptLine.invoiced_quantity), 0))
            .where(GoodsReceiptLine.source_purchase_order_line_id.in_(po_line_ids))
            .group_by(GoodsReceiptLine.source_purchase_order_line_id)
        )
        return {row[0]: Decimal(row[1]) for row in result.all()}

    async def _confirmed_gr_lines_for_po_line(
        self, tenant_id: uuid.UUID, po_line_id: uuid.UUID
    ) -> list[tuple[GoodsReceiptLine, UnitOfMeasure]]:
        """Every CONFIRMED Goods Receipt line that contributes physical
        receipt toward this PO line, oldest first — the fan-out source
        for `create_invoice_from_purchase_order`."""
        result = await self._session.execute(
            select(GoodsReceiptLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == GoodsReceiptLine.uom_id)
            .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptLine.goods_receipt_id)
            .where(
                GoodsReceiptLine.tenant_id == tenant_id, GoodsReceiptLine.source_purchase_order_line_id == po_line_id,
                GoodsReceipt.status == GR_CONFIRMED,
            )
            .order_by(GoodsReceipt.document_date.asc(), GoodsReceipt.created_at.asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    # --- invoice eligibility (from GR) --------------------------------------

    async def get_invoice_eligibility(
        self, *, tenant_id: uuid.UUID, receipt_id: uuid.UUID
    ) -> tuple[GoodsReceipt, str, list[tuple[GoodsReceiptLine, UnitOfMeasure]]]:
        gr_service = GoodsReceiptService(self._session)
        receipt, supplier_name, _po_number, gr_lines, _stock_info = await gr_service.get_receipt(tenant_id=tenant_id, receipt_id=receipt_id)

        if receipt.status != GR_CONFIRMED:
            raise ValidationAppError(
                f"A goods receipt in {receipt.status} status is not eligible for invoicing.", code=PINV_SOURCE_GR_NOT_CONFIRMED
            )
        return receipt, supplier_name, gr_lines

    # --- invoice eligibility (from PO, "Supported Flow 2") ------------------

    async def get_po_invoice_eligibility(
        self, *, tenant_id: uuid.UUID, purchase_order_id: uuid.UUID
    ) -> tuple[PurchaseOrder, str, list[POInvoiceEligibilityLine]]:
        """§8/§10/§26: for each PO line, ordered/received/previously-
        invoiced/invoiceable — "previously invoiced" is aggregated across
        ALL of that line's contributing GR lines (§18 "multiple GR
        linkage"), never accepted from the client."""
        po_service = PurchaseOrderService(self._session)
        order, supplier_name, po_lines, _totals = await po_service.get_order(tenant_id=tenant_id, order_id=purchase_order_id)

        po_line_ids = [line.id for line, _uom in po_lines]
        invoiced_by_po_line = await self._invoiced_quantity_by_po_line(po_line_ids)

        eligibility_lines = [
            POInvoiceEligibilityLine(
                purchase_order_line=line, uom=uom, invoiced_quantity=invoiced_by_po_line.get(line.id, Decimal("0")),
                invoiceable_quantity=line.received_quantity - invoiced_by_po_line.get(line.id, Decimal("0")),
            )
            for line, uom in po_lines
        ]
        return order, supplier_name, eligibility_lines

    # --- queries ---------------------------------------------------------

    async def list_invoices(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, search: str | None, status_filter: str | None,
        invoice_type_filter: str | None, supplier_id: uuid.UUID | None, date_from: date | None, date_to: date | None,
    ) -> PurchaseInvoicePage:
        base = (
            select(PurchaseInvoice, Supplier.name, GoodsReceipt.grn_number, PurchaseOrder.po_number)
            .join(Supplier, Supplier.id == PurchaseInvoice.supplier_id)
            .outerjoin(GoodsReceipt, GoodsReceipt.id == PurchaseInvoice.source_goods_receipt_id)
            .outerjoin(PurchaseOrder, PurchaseOrder.id == PurchaseInvoice.source_purchase_order_id)
            .where(PurchaseInvoice.tenant_id == tenant_id)
        )
        if search:
            like = f"%{search}%"
            base = base.where(
                or_(
                    PurchaseInvoice.purchase_invoice_number.ilike(like),
                    PurchaseInvoice.supplier_invoice_number.ilike(like),
                    GoodsReceipt.grn_number.ilike(like),
                    PurchaseOrder.po_number.ilike(like),
                    Supplier.name.ilike(like),
                )
            )
        if status_filter:
            base = base.where(PurchaseInvoice.status == status_filter)
        if invoice_type_filter:
            base = base.where(PurchaseInvoice.invoice_type == invoice_type_filter)
        if supplier_id:
            base = base.where(PurchaseInvoice.supplier_id == supplier_id)
        if date_from:
            base = base.where(PurchaseInvoice.document_date >= date_from)
        if date_to:
            base = base.where(PurchaseInvoice.document_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(PurchaseInvoice.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(PurchaseInvoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        return PurchaseInvoicePage(items=[(row[0], row[1], row[2], row[3]) for row in rows], total_items=total_items)

    async def get_invoice(
        self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> tuple[PurchaseInvoice, str, str | None, str | None, list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]]:
        result = await self._session.execute(
            select(PurchaseInvoice, Supplier.name, GoodsReceipt.grn_number, PurchaseOrder.po_number)
            .join(Supplier, Supplier.id == PurchaseInvoice.supplier_id)
            .outerjoin(GoodsReceipt, GoodsReceipt.id == PurchaseInvoice.source_goods_receipt_id)
            .outerjoin(PurchaseOrder, PurchaseOrder.id == PurchaseInvoice.source_purchase_order_id)
            .where(PurchaseInvoice.id == invoice_id, PurchaseInvoice.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Purchase invoice not found", code=PINV_NOT_FOUND)
        invoice, supplier_name, grn_number, po_number = row
        lines = await self._get_lines(invoice.id)
        return invoice, supplier_name, grn_number, po_number, lines

    # --- create: direct ----------------------------------------------------

    async def _build_direct_lines(
        self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID, line_inputs: list[DirectPurchaseInvoiceLineInput], gst_treatment: str,
    ) -> tuple[list[PurchaseInvoiceLine], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        lines: list[PurchaseInvoiceLine] = []
        calculated_lines = []

        for index, line_input in enumerate(line_inputs, start=1):
            validated_product = await validate_product_for_purchase(self._session, tenant_id=tenant_id, product_id=uuid.UUID(line_input.product_id))
            uom = await self._get_uom_or_raise(tenant_id, uuid.UUID(line_input.uom_id))
            product = validated_product.product

            result = calculate_line(
                quantity=line_input.quantity, unit_price=line_input.unit_price,
                discount_percent=line_input.discount_percent, discount_amount=line_input.discount_amount,
                gst_rate=product.gst_rate or Decimal("0"), gst_treatment=gst_treatment,
            )
            calculated_lines.append(result)

            lines.append(
                PurchaseInvoiceLine(
                    tenant_id=tenant_id, purchase_invoice_id=invoice_id, line_no=index, product_id=product.id,
                    description=product.name, hsn_code=product.hsn_code, quantity=line_input.quantity, uom_id=uom.id,
                    unit_price=line_input.unit_price, discount_amount=result.discount_amount,
                    taxable_amount=result.taxable_amount, gst_rate=product.gst_rate or Decimal("0"),
                    cgst_amount=result.cgst_amount, sgst_amount=result.sgst_amount, igst_amount=result.igst_amount,
                    line_total=result.line_total, source_goods_receipt_line_id=None,
                )
            )

        totals = calculate_document_totals(calculated_lines)
        return (lines, totals.subtotal, totals.total_discount, totals.total_taxable, totals.total_cgst, totals.total_sgst, totals.total_igst, totals.grand_total)

    async def create_direct_invoice(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, supplier_id: uuid.UUID, document_date: date | None,
        supplier_invoice_number: str | None, supplier_invoice_date: date | None = None, due_date: date | None = None,
        notes: str | None, line_inputs: list[DirectPurchaseInvoiceLineInput], ip_address: str | None,
    ) -> tuple[PurchaseInvoice, str, str | None, list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        validated_supplier = await validate_supplier_for_purchase(self._session, tenant_id=tenant_id, supplier_id=supplier_id)
        supplier = validated_supplier.supplier

        gst_treatment = determine_gst_treatment(supplier_state_code=tenant.state_code, customer_state_code=supplier.state_code)
        doc_date = document_date or date.today()

        numbering = DocumentNumberingService(self._session)
        invoice_number = await numbering.next_number(tenant=tenant, document_type=PURCHASE_INVOICE, prefix="PINV")

        invoice = PurchaseInvoice(
            tenant_id=tenant_id, purchase_invoice_number=invoice_number, supplier_invoice_number=supplier_invoice_number,
            invoice_type=DIRECT_PURCHASE_INVOICE, supplier_id=supplier.id, supplier_gstin=supplier.gstin,
            place_of_supply_state_code=supplier.state_code, source_goods_receipt_id=None, document_date=doc_date,
            supplier_invoice_date=supplier_invoice_date, due_date=due_date,
            status=DRAFT, notes=notes, created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(invoice)
        await self._session.flush()

        lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
            await self._build_direct_lines(tenant_id=tenant_id, invoice_id=invoice.id, line_inputs=line_inputs, gst_treatment=gst_treatment)
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
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_INVOICE_CREATED",
            entity_type="purchase_invoice", entity_id=invoice.id, after=self._snapshot(invoice), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(invoice.id)
        return invoice, supplier.name, None, lines_with_uom

    # --- create: from Goods Receipt ------------------------------------

    async def create_invoice_from_receipt(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, receipt_id: uuid.UUID, document_date: date | None,
        supplier_invoice_number: str | None, supplier_invoice_date: date | None = None, due_date: date | None = None,
        notes: str | None, line_inputs: list[InvoiceFromReceiptLineInput], ip_address: str | None,
    ) -> tuple[PurchaseInvoice, str, str | None, list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        receipt, _supplier_name, gr_lines = await self.get_invoice_eligibility(tenant_id=tenant_id, receipt_id=receipt_id)
        gr_lines_by_id = {gr_line.id: (gr_line, uom) for gr_line, uom in gr_lines}

        validated_supplier = await validate_supplier_for_purchase(self._session, tenant_id=tenant_id, supplier_id=receipt.supplier_id)
        supplier = validated_supplier.supplier

        gst_treatment = determine_gst_treatment(
            supplier_state_code=tenant.state_code, customer_state_code=receipt.place_of_supply_state_code or supplier.state_code
        )
        doc_date = document_date or date.today()

        numbering = DocumentNumberingService(self._session)
        invoice_number = await numbering.next_number(tenant=tenant, document_type=PURCHASE_INVOICE, prefix="PINV")

        invoice = PurchaseInvoice(
            tenant_id=tenant_id, purchase_invoice_number=invoice_number, supplier_invoice_number=supplier_invoice_number,
            invoice_type=GOODS_RECEIPT_PURCHASE_INVOICE, supplier_id=supplier.id, supplier_gstin=supplier.gstin,
            place_of_supply_state_code=receipt.place_of_supply_state_code, source_goods_receipt_id=receipt.id,
            document_date=doc_date, supplier_invoice_date=supplier_invoice_date, due_date=due_date,
            status=DRAFT, notes=notes, created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(invoice)
        await self._session.flush()

        lines: list[PurchaseInvoiceLine] = []
        calculated_lines = []

        for index, line_input in enumerate(line_inputs, start=1):
            gr_line_id = uuid.UUID(line_input.source_goods_receipt_line_id)
            match = gr_lines_by_id.get(gr_line_id)
            if match is None:
                raise ValidationAppError("The selected goods receipt line does not belong to this goods receipt.", code=PINV_EXCEEDS_INVOICEABLE)
            gr_line, uom = match

            invoiceable = gr_line.quantity - gr_line.invoiced_quantity
            if line_input.quantity > invoiceable:
                raise ValidationAppError(f"Invoice quantity {line_input.quantity} exceeds invoiceable quantity {invoiceable}.", code=PINV_EXCEEDS_INVOICEABLE)

            result = calculate_line(
                quantity=line_input.quantity, unit_price=gr_line.unit_price, discount_percent=None,
                discount_amount=Decimal("0"), gst_rate=gr_line.gst_rate, gst_treatment=gst_treatment,
            )
            calculated_lines.append(result)

            lines.append(
                PurchaseInvoiceLine(
                    tenant_id=tenant_id, purchase_invoice_id=invoice.id, line_no=index, product_id=gr_line.product_id,
                    description=gr_line.description, hsn_code=gr_line.hsn_code, quantity=line_input.quantity, uom_id=gr_line.uom_id,
                    unit_price=gr_line.unit_price, discount_amount=result.discount_amount, taxable_amount=result.taxable_amount,
                    gst_rate=gr_line.gst_rate, cgst_amount=result.cgst_amount, sgst_amount=result.sgst_amount,
                    igst_amount=result.igst_amount, line_total=result.line_total, source_goods_receipt_line_id=gr_line.id,
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
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_INVOICE_CREATED",
            entity_type="purchase_invoice", entity_id=invoice.id, after=self._snapshot(invoice), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(invoice.id)
        return invoice, supplier.name, receipt.grn_number, lines_with_uom

    # --- create: from Purchase Order, "Supported Flow 2" ---------------------

    async def create_invoice_from_purchase_order(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_order_id: uuid.UUID, document_date: date | None,
        supplier_invoice_number: str | None, supplier_invoice_date: date | None, due_date: date | None,
        notes: str | None, line_inputs: list[InvoiceFromPurchaseOrderLineInput], ip_address: str | None,
    ) -> tuple[PurchaseInvoice, str, str | None, list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]]:
        """§8/§9/§18: consolidates eligible quantity across potentially
        MULTIPLE confirmed Goods Receipts under one Purchase Order, in a
        single invoice. Every unit still traces to a specific `goods_
        receipt_line` — a requested PO-line quantity is fanned out across
        that PO line's own contributing GR lines (oldest first),
        consuming each one's OWN remaining invoiceable quantity, so ONE
        requested `InvoiceFromPurchaseOrderLineInput` can produce SEVERAL
        `PurchaseInvoiceLine` rows (one per contributing GR line) —
        invoice-before-receipt is never possible via this path either."""
        tenant = await self._get_tenant(tenant_id)
        order, _supplier_name, eligibility_lines = await self.get_po_invoice_eligibility(tenant_id=tenant_id, purchase_order_id=purchase_order_id)
        eligibility_by_po_line = {el.purchase_order_line.id: el for el in eligibility_lines}

        validated_supplier = await validate_supplier_for_purchase(self._session, tenant_id=tenant_id, supplier_id=order.supplier_id)
        supplier = validated_supplier.supplier

        gst_treatment = determine_gst_treatment(
            supplier_state_code=tenant.state_code, customer_state_code=order.place_of_supply_state_code or supplier.state_code
        )
        doc_date = document_date or date.today()

        numbering = DocumentNumberingService(self._session)
        invoice_number = await numbering.next_number(tenant=tenant, document_type=PURCHASE_INVOICE, prefix="PINV")

        invoice = PurchaseInvoice(
            tenant_id=tenant_id, purchase_invoice_number=invoice_number, supplier_invoice_number=supplier_invoice_number,
            invoice_type=PURCHASE_ORDER_PURCHASE_INVOICE, supplier_id=supplier.id, supplier_gstin=supplier.gstin,
            place_of_supply_state_code=order.place_of_supply_state_code, source_goods_receipt_id=None,
            source_purchase_order_id=order.id, document_date=doc_date, supplier_invoice_date=supplier_invoice_date,
            due_date=due_date, status=DRAFT, notes=notes, created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(invoice)
        await self._session.flush()

        lines: list[PurchaseInvoiceLine] = []
        calculated_lines = []
        line_no = 1

        for line_input in line_inputs:
            po_line_id = uuid.UUID(line_input.purchase_order_line_id)
            eligibility = eligibility_by_po_line.get(po_line_id)
            if eligibility is None:
                raise ValidationAppError("The selected purchase order line does not belong to this purchase order.", code=PINV_EXCEEDS_INVOICEABLE)
            if line_input.quantity > eligibility.invoiceable_quantity:
                raise ValidationAppError(
                    f"Invoice quantity {line_input.quantity} exceeds invoiceable quantity {eligibility.invoiceable_quantity}.",
                    code=PINV_EXCEEDS_INVOICEABLE,
                )

            remaining_to_allocate = line_input.quantity
            for gr_line, gr_uom in await self._confirmed_gr_lines_for_po_line(tenant_id, po_line_id):
                if remaining_to_allocate <= 0:
                    break
                gr_invoiceable = gr_line.quantity - gr_line.invoiced_quantity
                if gr_invoiceable <= 0:
                    continue
                take = min(remaining_to_allocate, gr_invoiceable)

                result = calculate_line(
                    quantity=take, unit_price=gr_line.unit_price, discount_percent=None,
                    discount_amount=Decimal("0"), gst_rate=gr_line.gst_rate, gst_treatment=gst_treatment,
                )
                calculated_lines.append(result)
                lines.append(
                    PurchaseInvoiceLine(
                        tenant_id=tenant_id, purchase_invoice_id=invoice.id, line_no=line_no, product_id=gr_line.product_id,
                        description=gr_line.description, hsn_code=gr_line.hsn_code, quantity=take, uom_id=gr_line.uom_id,
                        unit_price=gr_line.unit_price, discount_amount=result.discount_amount, taxable_amount=result.taxable_amount,
                        gst_rate=gr_line.gst_rate, cgst_amount=result.cgst_amount, sgst_amount=result.sgst_amount,
                        igst_amount=result.igst_amount, line_total=result.line_total,
                        source_goods_receipt_line_id=gr_line.id, source_purchase_order_line_id=po_line_id,
                    )
                )
                line_no += 1
                remaining_to_allocate -= take

            if remaining_to_allocate > 0:
                # Guards a race between the eligibility read above and this
                # fan-out (e.g. a concurrent invoice consumed the same GR
                # line's remaining quantity in between) — never partially
                # apply an under-sourced request.
                raise ValidationAppError(
                    f"Unable to source {line_input.quantity} units for this line from confirmed goods receipts "
                    f"— {remaining_to_allocate} units could not be allocated. Please refresh and try again.",
                    code=PINV_EXCEEDS_INVOICEABLE,
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
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_INVOICE_CREATED",
            entity_type="purchase_invoice", entity_id=invoice.id, after=self._snapshot(invoice), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(invoice.id)
        return invoice, supplier.name, order.po_number, lines_with_uom

    # --- update (DRAFT only, direct invoices only) --------------------------

    async def update_invoice(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID, expected_row_version: int,
        document_date: date | None, supplier_invoice_number: str | None, supplier_invoice_date: date | None = None,
        due_date: date | None = None, notes: str | None,
        line_inputs: list[DirectPurchaseInvoiceLineInput] | None, ip_address: str | None,
    ) -> tuple[PurchaseInvoice, str, str | None, list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]]:
        invoice = await self._get_invoice_locked(tenant_id, invoice_id)
        check_row_version(invoice, expected_row_version)

        if invoice.status != DRAFT:
            raise ValidationAppError("This invoice has already been posted and cannot be edited.", code=PINV_INVALID_STATUS)
        if line_inputs is not None and invoice.invoice_type in NO_STOCK_IMPACT_INVOICE_TYPES:
            raise ValidationAppError(
                "Line quantities on a goods-receipt-sourced or purchase-order-sourced invoice cannot be edited — cancel and recreate it instead.",
                code=PINV_INVALID_STATUS,
            )

        before = self._snapshot(invoice)
        tenant = await self._get_tenant(tenant_id)
        supplier_result = await self._session.execute(select(Supplier).where(Supplier.id == invoice.supplier_id))
        supplier = supplier_result.scalar_one()

        if document_date is not None:
            invoice.document_date = document_date
        if supplier_invoice_number is not None:
            invoice.supplier_invoice_number = supplier_invoice_number
        if supplier_invoice_date is not None:
            invoice.supplier_invoice_date = supplier_invoice_date
        if due_date is not None:
            invoice.due_date = due_date
        if notes is not None:
            invoice.notes = notes

        if line_inputs is not None:
            gst_treatment = determine_gst_treatment(supplier_state_code=tenant.state_code, customer_state_code=supplier.state_code)
            existing_lines = await self._get_lines(invoice.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
                await self._build_direct_lines(tenant_id=tenant_id, invoice_id=invoice.id, line_inputs=line_inputs, gst_treatment=gst_treatment)
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
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_INVOICE_UPDATED",
            entity_type="purchase_invoice", entity_id=invoice.id, before=before, after=self._snapshot(invoice), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(invoice.id)
        grn_number = None
        if invoice.source_goods_receipt_id:
            gr_result = await self._session.execute(select(GoodsReceipt.grn_number).where(GoodsReceipt.id == invoice.source_goods_receipt_id))
            grn_number = gr_result.scalar_one_or_none()
        return invoice, supplier.name, grn_number, lines_with_uom

    # --- post (§12/§28: the atomic stock core) -----------------------------

    async def post_invoice(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> tuple[PurchaseInvoice, str, str | None, list[tuple[PurchaseInvoiceLine, UnitOfMeasure]]]:
        invoice = await self._get_invoice_locked(tenant_id, invoice_id)
        check_row_version(invoice, expected_row_version)

        if invoice.status != DRAFT:
            raise ValidationAppError(f"Cannot post an invoice in {invoice.status} status.", code=PINV_INVALID_STATUS)

        await validate_supplier_for_purchase(self._session, tenant_id=tenant_id, supplier_id=invoice.supplier_id)
        lines = await self._get_lines(invoice.id)

        grn_number: str | None = None

        if invoice.invoice_type == DIRECT_PURCHASE_INVOICE:
            # §12 Scenario A: this invoice OWNS the stock-in.
            inventory = InventoryService(self._session)
            location = await inventory.ensure_default_location(tenant_id)
            for line, uom in lines:
                if line.product_id is not None:
                    await validate_product_for_purchase(self._session, tenant_id=tenant_id, product_id=line.product_id)
                    product = await inventory.get_active_product_locked(tenant_id, line.product_id)
                    await inventory.post_movement(
                        tenant_id=tenant_id, actor_user_id=actor_user_id, product=product, location=location,
                        movement_type=STOCK_IN, quantity=line.quantity, uom=uom, source_type=PURCHASE_INVOICE,
                        source_id=line.id, audit_action="STOCK_IN_CREATED",
                        audit_extra={"purchase_invoice_id": str(invoice.id), "purchase_invoice_number": invoice.purchase_invoice_number},
                        ip_address=ip_address,
                    )
        else:
            # §12 Scenario B / NO_STOCK_IMPACT_INVOICE_TYPES: NO stock
            # movement — the source Goods Receipt(s) already increased
            # stock. A single-GR invoice locks exactly one receipt; a
            # PO-consolidated invoice may reference SEVERAL (§18) — every
            # DISTINCT one referenced by this invoice's own lines is
            # locked (in a consistent, sorted order, to avoid a lock-
            # ordering deadlock against a concurrently-posting invoice
            # that references the same receipts in a different order),
            # which is what serializes concurrent invoice postings
            # against any of them.
            gr_service = GoodsReceiptService(self._session)
            gr_line_ids = [line.source_goods_receipt_line_id for line, _uom in lines]
            if any(gr_line_id is None for gr_line_id in gr_line_ids):
                raise ValidationAppError("The source goods receipt line no longer exists.", code=PINV_EXCEEDS_INVOICEABLE)

            gr_id_lookup = await self._session.execute(
                select(GoodsReceiptLine.id, GoodsReceiptLine.goods_receipt_id).where(GoodsReceiptLine.id.in_(gr_line_ids))
            )
            gr_id_by_line_id = {row[0]: row[1] for row in gr_id_lookup.all()}
            distinct_gr_ids = sorted({str(gr_id) for gr_id in gr_id_by_line_id.values()})

            receipts_by_id: dict[str, object] = {}
            for gr_id_str in distinct_gr_ids:
                receipt = await gr_service.get_receipt_locked(tenant_id, uuid.UUID(gr_id_str))
                if receipt.status != GR_CONFIRMED:
                    raise ValidationAppError(
                        f"The source goods receipt is in {receipt.status} status and can no longer be invoiced.", code=PINV_SOURCE_GR_NOT_CONFIRMED
                    )
                receipts_by_id[gr_id_str] = receipt

            if invoice.source_goods_receipt_id is not None:
                grn_number = receipts_by_id[str(invoice.source_goods_receipt_id)].grn_number

            gr_lines_result = await self._session.execute(select(GoodsReceiptLine).where(GoodsReceiptLine.id.in_(gr_line_ids)))
            gr_lines_by_id = {gl.id: gl for gl in gr_lines_result.scalars().all()}

            for line, _uom in lines:
                gr_line = gr_lines_by_id.get(line.source_goods_receipt_line_id)
                if gr_line is None:
                    raise ValidationAppError("The source goods receipt line no longer exists.", code=PINV_EXCEEDS_INVOICEABLE)
                live_invoiceable = gr_line.quantity - gr_line.invoiced_quantity
                if line.quantity > live_invoiceable:
                    raise ValidationAppError(
                        f"Invoice quantity {line.quantity} exceeds invoiceable quantity {live_invoiceable}.", code=PINV_EXCEEDS_INVOICEABLE
                    )
                gr_line.invoiced_quantity += line.quantity
                gr_line.updated_by = actor_user_id
                if line.product_id is not None:
                    await validate_product_for_purchase(self._session, tenant_id=tenant_id, product_id=line.product_id)

        previous_status = invoice.status
        invoice.status = POSTED
        invoice.updated_by = actor_user_id
        invoice.row_version += 1
        await self._session.flush()

        # PROMPT-025 closes the accounting boundary PROMPT-019 §14
        # explicitly deferred ("Do not implement accounting posting in
        # this prompt") — DR Purchase Expense + Input GST, CR Accounts
        # Payable, using this invoice's own already-calculated totals.
        accounting_reference = await AccountingPostingService(self._session).post_purchase_invoice(
            tenant_id=tenant_id, actor_user_id=actor_user_id, invoice=invoice, ip_address=ip_address,
        )
        invoice.accounting_posting_reference = accounting_reference
        await self._session.flush()

        # PROMPT-026: closes the Purchase-side GST reporting gap — the
        # invoice's own already-calculated GST totals (never
        # recalculated) are snapshotted as an Input GST transaction.
        gst_reference = await GstReportingService(self._session).record_purchase_invoice_transaction(
            tenant_id=tenant_id, actor_user_id=actor_user_id, invoice=invoice, ip_address=ip_address,
        )
        invoice.gst_transaction_reference = gst_reference
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_INVOICE_POSTED",
            entity_type="purchase_invoice", entity_id=invoice.id, before={"status": previous_status},
            after={
                "status": POSTED, "accounting_posting_reference": accounting_reference,
                "gst_transaction_reference": gst_reference,
            },
            ip_address=ip_address,
        )

        supplier_result = await self._session.execute(select(Supplier.name).where(Supplier.id == invoice.supplier_id))
        supplier_name = supplier_result.scalar_one()
        lines_with_uom = await self._get_lines(invoice.id)
        return invoice, supplier_name, grn_number, lines_with_uom

    # --- cancel (DRAFT: no stock impact; POSTED: reversal) ------------------

    async def cancel_invoice(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> PurchaseInvoice:
        """§33-35: cancelling a DRAFT invoice is a pure status change (no
        stock/quantity-tracking impact ever occurred). Cancelling a
        POSTED invoice is a controlled REVERSAL, not a deletion — gated
        by no downstream Purchase Return against any line
        (`purchase_invoice_line.returned_quantity == 0` for every line).
        A DIRECT invoice's cancellation posts a compensating STOCK_OUT
        per line (mirrors `GoodsReceiptService.cancel_receipt`'s own
        reversal design exactly — INVARIANT 7: the original STOCK_IN is
        never edited/deleted). A GR/PO-sourced invoice's cancellation
        NEVER touches stock (§35 — the source GR remains the physical
        receipt) — it only releases its own bookkeeping claim on each
        line's source `goods_receipt_line.invoiced_quantity`."""
        invoice = await self._get_invoice_locked(tenant_id, invoice_id)
        check_row_version(invoice, expected_row_version)

        if invoice.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(f"Cannot cancel an invoice in {invoice.status} status.", code=PINV_INVALID_STATUS)

        previous_status = invoice.status

        if previous_status == DRAFT:
            invoice.status = CANCELLED
            invoice.updated_by = actor_user_id
            invoice.row_version += 1
            await self._session.flush()

            await AuditService(self._session).record(
                tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_INVOICE_CANCELLED",
                entity_type="purchase_invoice", entity_id=invoice.id, before={"status": previous_status},
                after={"status": CANCELLED}, ip_address=ip_address,
            )
            return invoice

        # previous_status == POSTED: reversal, not a simple cancel.
        lines = await self._get_lines(invoice.id)

        if any(line.returned_quantity > 0 for line, _uom in lines):
            raise ValidationAppError(
                "Purchase Invoice cannot be cancelled because a Purchase Return has already been created against this invoice.",
                code=PINV_HAS_DOWNSTREAM_RETURN,
            )

        if invoice.invoice_type == DIRECT_PURCHASE_INVOICE:
            inventory = InventoryService(self._session)
            location = await inventory.ensure_default_location(tenant_id)
            for line, uom in lines:
                if line.product_id is not None:
                    product = await inventory.get_active_product_locked(tenant_id, line.product_id)
                    # If the received stock has already been consumed
                    # elsewhere, this raises ConflictError — the reversal
                    # is rejected rather than forced through negative
                    # stock (same policy as Goods Receipt's own reversal,
                    # PROMPT-021).
                    await inventory.post_movement(
                        tenant_id=tenant_id, actor_user_id=actor_user_id, product=product, location=location,
                        movement_type=STOCK_OUT, quantity=line.quantity, uom=uom, source_type=PURCHASE_INVOICE_REVERSAL,
                        source_id=line.id, audit_action="STOCK_IN_REVERSED",
                        audit_extra={"purchase_invoice_id": str(invoice.id), "purchase_invoice_number": invoice.purchase_invoice_number, "reason": "PURCHASE_INVOICE_CANCELLED"},
                        ip_address=ip_address,
                    )
        else:
            gr_line_ids = [line.source_goods_receipt_line_id for line, _uom in lines if line.source_goods_receipt_line_id]
            if gr_line_ids:
                gr_lines_result = await self._session.execute(select(GoodsReceiptLine).where(GoodsReceiptLine.id.in_(gr_line_ids)))
                gr_lines_by_id = {gl.id: gl for gl in gr_lines_result.scalars().all()}
                for line, _uom in lines:
                    gr_line = gr_lines_by_id.get(line.source_goods_receipt_line_id)
                    if gr_line is not None:
                        gr_line.invoiced_quantity = max(Decimal("0"), gr_line.invoiced_quantity - line.quantity)
                        gr_line.updated_by = actor_user_id

        invoice.status = CANCELLED
        invoice.updated_by = actor_user_id
        invoice.row_version += 1
        await self._session.flush()

        # PROMPT-025 §33/§34: reverses the ORIGINAL purchase invoice
        # journal via a new REVERSAL journal — never edits it.
        accounting_reference = await AccountingPostingService(self._session).reverse_purchase_invoice(
            tenant_id=tenant_id, actor_user_id=actor_user_id, invoice_id=invoice.id, ip_address=ip_address,
        )

        # PROMPT-026 §21/§33: reverses the ORIGINAL GST snapshot via a new
        # REVERSAL row — never edits it.
        gst_reversal_reference = await GstReportingService(self._session).reverse_purchase_invoice_transaction(
            tenant_id=tenant_id, actor_user_id=actor_user_id, invoice_id=invoice.id, ip_address=ip_address,
        )

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_INVOICE_CANCELLED",
            entity_type="purchase_invoice", entity_id=invoice.id, before={"status": previous_status},
            after={
                "status": CANCELLED, "stock_reversed": invoice.invoice_type == DIRECT_PURCHASE_INVOICE,
                "accounting_reversal_reference": accounting_reference,
                "gst_reversal_reference": gst_reversal_reference,
            },
            ip_address=ip_address,
        )
        return invoice

    # --- related documents / audit history (PROMPT-022) ---------------------

    async def get_related_documents(
        self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> tuple[PurchaseInvoice, PurchaseOrder | None, list[GoodsReceipt], list[PurchaseReturn]]:
        """§36/§47: source Purchase Order (if any), every contributing
        Goods Receipt (derived from the invoice's own lines — works for
        both a single-GR invoice and a PO-consolidated one), and every
        Purchase Return created against this invoice."""
        result = await self._session.execute(
            select(PurchaseInvoice).where(PurchaseInvoice.id == invoice_id, PurchaseInvoice.tenant_id == tenant_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Purchase invoice not found", code=PINV_NOT_FOUND)

        order: PurchaseOrder | None = None
        if invoice.source_purchase_order_id is not None:
            order_result = await self._session.execute(
                select(PurchaseOrder).where(PurchaseOrder.id == invoice.source_purchase_order_id, PurchaseOrder.tenant_id == tenant_id)
            )
            order = order_result.scalar_one_or_none()

        lines = await self._get_lines(invoice.id)
        gr_line_ids = [line.source_goods_receipt_line_id for line, _uom in lines if line.source_goods_receipt_line_id]
        goods_receipts: list[GoodsReceipt] = []
        if gr_line_ids:
            gr_result = await self._session.execute(
                select(GoodsReceipt)
                .join(GoodsReceiptLine, GoodsReceiptLine.goods_receipt_id == GoodsReceipt.id)
                .where(GoodsReceiptLine.id.in_(gr_line_ids))
                .distinct()
            )
            goods_receipts = list(gr_result.scalars().all())

        returns_result = await self._session.execute(
            select(PurchaseReturn)
            .where(PurchaseReturn.tenant_id == tenant_id, PurchaseReturn.source_purchase_invoice_id == invoice_id)
            .order_by(PurchaseReturn.created_at.asc())
        )
        purchase_returns = list(returns_result.scalars().all())

        return invoice, order, goods_receipts, purchase_returns

    async def get_audit_history(self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> list[AuditLog]:
        """§51: the audit trail shown on the invoice detail screen —
        mirrors `PurchaseOrderService.get_audit_history`/
        `GoodsReceiptService.get_audit_history`'s exact discipline
        (narrow, entity-scoped, tenant-ownership-checked first)."""
        exists_result = await self._session.execute(
            select(PurchaseInvoice.id).where(PurchaseInvoice.id == invoice_id, PurchaseInvoice.tenant_id == tenant_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Purchase invoice not found", code=PINV_NOT_FOUND)

        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "purchase_invoice", AuditLog.entity_id == invoice_id)
            .order_by(AuditLog.occurred_at.asc())
        )
        return list(result.scalars().all())
