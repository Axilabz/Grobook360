"""Purchase Order service (PROMPT-019).

The first concrete Purchase document type, mirroring `sales_order_
service.py`'s exact shape and discipline:
- GST amounts come from `gst_calculation_service` (never invented here).
- Supplier/product validation comes from `purchase_validation_service`.
- Document numbers come from the shared `DocumentNumberingService`.
- Purchase Orders NEVER touch inventory — §10 is a MANDATORY business
  rule: creation, editing, confirmation, and cancellation must never
  create a stock ledger entry. No `InventoryService` import exists
  anywhere in this file — the same structural guarantee `sales_order_
  service.py` uses for the identical rule.

Server-side calculation is authoritative (§15): every financial value in
`PurchaseOrderLineInput` the client submits is input only — gross/
discount/taxable/GST/totals are always recomputed here.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.concurrency import check_row_version
from app.core.error_codes import PO_INVALID_STATUS, PO_NOT_FOUND
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.purchase_constants import PURCHASE_ORDER
from app.models.audit_log import AuditLog
from app.models.goods_receipt import GoodsReceipt
from app.models.purchase_invoice import PurchaseInvoice
from app.models.purchase_order import (
    CANCELLABLE_STATUSES,
    CANCELLED,
    CONFIRMED,
    DRAFT,
    FULLY_RECEIVED,
    PARTIALLY_RECEIVED,
    PurchaseOrder,
)
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.supplier import Supplier
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.models.user import User
from app.schemas.purchase import PurchaseOrderLineInput
from app.services.audit.audit_service import AuditService
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
class PurchaseOrderPage:
    # (order, supplier_name, ordered, received, remaining, created_by_name, updated_by_name)
    items: list[tuple[PurchaseOrder, str, Decimal, Decimal, Decimal, str | None, str | None]]
    total_items: int


@dataclass(frozen=True)
class QuantityTotals:
    ordered: Decimal
    received: Decimal
    remaining: Decimal


class PurchaseOrderService:
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
            raise ValidationAppError("Select a valid unit.", code=PO_NOT_FOUND)
        return unit

    async def _get_order_locked(self, tenant_id: uuid.UUID, order_id: uuid.UUID) -> PurchaseOrder:
        result = await self._session.execute(
            select(PurchaseOrder).where(PurchaseOrder.id == order_id, PurchaseOrder.tenant_id == tenant_id).with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise NotFoundError("Purchase order not found", code=PO_NOT_FOUND)
        return order

    async def _get_lines(self, order_id: uuid.UUID) -> list[tuple[PurchaseOrderLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(PurchaseOrderLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == PurchaseOrderLine.uom_id)
            .where(PurchaseOrderLine.purchase_order_id == order_id)
            .order_by(PurchaseOrderLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def _quantity_totals_for_orders(self, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, QuantityTotals]:
        """§21/§45: ordered/received/remaining, aggregated per order, in
        ONE query for a whole page (never N+1) — remaining is always
        derived server-side, never accepted from a client (§19)."""
        if not order_ids:
            return {}
        result = await self._session.execute(
            select(
                PurchaseOrderLine.purchase_order_id,
                func.coalesce(func.sum(PurchaseOrderLine.quantity), 0),
                func.coalesce(func.sum(PurchaseOrderLine.received_quantity), 0),
            )
            .where(PurchaseOrderLine.purchase_order_id.in_(order_ids))
            .group_by(PurchaseOrderLine.purchase_order_id)
        )
        totals: dict[uuid.UUID, QuantityTotals] = {}
        for order_id, ordered, received in result.all():
            ordered_dec = Decimal(ordered)
            received_dec = Decimal(received)
            totals[order_id] = QuantityTotals(ordered=ordered_dec, received=received_dec, remaining=ordered_dec - received_dec)
        return totals

    # --- public entrypoints for GoodsReceiptService ------------------------

    async def get_order_locked(self, tenant_id: uuid.UUID, order_id: uuid.UUID) -> PurchaseOrder:
        """Locks the Purchase Order row so two concurrent Goods Receipt
        confirmations against the same order serialize instead of racing
        (§27) — mirrors `SalesOrderService.get_order_locked` exactly."""
        return await self._get_order_locked(tenant_id, order_id)

    async def get_lines(self, order_id: uuid.UUID) -> list[tuple[PurchaseOrderLine, UnitOfMeasure]]:
        return await self._get_lines(order_id)

    async def apply_receipt(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        order: PurchaseOrder,
        line_receipts: dict[uuid.UUID, Decimal],
        ip_address: str | None,
    ) -> None:
        """The ONE place `purchase_order_line.received_quantity` and
        `purchase_order.status` are ever updated for receipt — called by
        `GoodsReceiptService.confirm_receipt` inside that same
        transaction, after the order row is already locked and the Stock
        IN movement(s) for this Goods Receipt have already posted
        successfully. Mirrors `SalesOrderService.apply_delivery` exactly."""
        all_lines = await self._get_lines(order.id)
        for line, _uom in all_lines:
            increment = line_receipts.get(line.id)
            if increment is not None:
                line.received_quantity += increment
                line.updated_by = actor_user_id

        previous_status = order.status
        if all(line.received_quantity >= line.quantity for line, _uom in all_lines):
            order.status = FULLY_RECEIVED
        else:
            order.status = PARTIALLY_RECEIVED
        order.updated_by = actor_user_id
        order.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="PURCHASE_ORDER_RECEIPT_UPDATED",
            entity_type="purchase_order",
            entity_id=order.id,
            before={"status": previous_status},
            after={"status": order.status, "line_receipts": {str(k): str(v) for k, v in line_receipts.items()}},
            ip_address=ip_address,
        )

    async def apply_reversal(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        order: PurchaseOrder,
        line_reversals: dict[uuid.UUID, Decimal],
        ip_address: str | None,
    ) -> None:
        """PROMPT-021 §23/§25: the mirror image of `apply_receipt` —
        called by `GoodsReceiptService.cancel_receipt` when reversing a
        CONFIRMED Goods Receipt, inside the same transaction as the
        compensating Stock OUT movement(s), after the order row is
        already locked. Never called for a DRAFT-GR cancellation (which
        has no stock/PO impact at all)."""
        all_lines = await self._get_lines(order.id)
        for line, _uom in all_lines:
            decrement = line_reversals.get(line.id)
            if decrement is not None:
                line.received_quantity = max(Decimal("0"), line.received_quantity - decrement)
                line.updated_by = actor_user_id

        previous_status = order.status
        # A CANCELLED order's status is terminal — a reversal changes its
        # received-quantity bookkeeping but must not resurrect it into an
        # active receiving state.
        if order.status != CANCELLED:
            totals = self.totals_from_lines(all_lines)
            if totals.received <= 0:
                order.status = CONFIRMED
            elif totals.received >= totals.ordered:
                order.status = FULLY_RECEIVED
            else:
                order.status = PARTIALLY_RECEIVED
        order.updated_by = actor_user_id
        order.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="PURCHASE_ORDER_RECEIPT_REVERSED",
            entity_type="purchase_order",
            entity_id=order.id,
            before={"status": previous_status},
            after={"status": order.status, "line_reversals": {str(k): str(v) for k, v in line_reversals.items()}},
            ip_address=ip_address,
        )

    async def _build_lines_from_input(
        self,
        *,
        tenant_id: uuid.UUID,
        order_id: uuid.UUID,
        line_inputs: list[PurchaseOrderLineInput],
        gst_treatment: str,
    ) -> tuple[list[PurchaseOrderLine], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        lines: list[PurchaseOrderLine] = []
        calculated_lines = []

        for index, line_input in enumerate(line_inputs, start=1):
            validated_product = await validate_product_for_purchase(
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
                PurchaseOrderLine(
                    tenant_id=tenant_id,
                    purchase_order_id=order_id,
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
                )
            )

        totals = calculate_document_totals(calculated_lines)
        return (
            lines, totals.subtotal, totals.total_discount, totals.total_taxable,
            totals.total_cgst, totals.total_sgst, totals.total_igst, totals.grand_total,
        )

    def _snapshot(self, order: PurchaseOrder) -> dict:
        return {
            "supplier_id": str(order.supplier_id),
            "document_date": order.document_date.isoformat(),
            "supplier_reference": order.supplier_reference,
            "expected_delivery_date": order.expected_delivery_date.isoformat() if order.expected_delivery_date else None,
            "payment_terms": order.payment_terms,
            "delivery_terms": order.delivery_terms,
            "status": order.status,
            "grand_total": str(order.grand_total),
        }

    # --- queries ---------------------------------------------------------

    async def list_orders(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, search: str | None, status_filter: str | None,
        supplier_id: uuid.UUID | None, date_from: date | None, date_to: date | None,
    ) -> PurchaseOrderPage:
        creator = aliased(User)
        updater = aliased(User)
        base = (
            select(PurchaseOrder, Supplier.name, creator.name, updater.name)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .outerjoin(creator, creator.id == PurchaseOrder.created_by)
            .outerjoin(updater, updater.id == PurchaseOrder.updated_by)
            .where(PurchaseOrder.tenant_id == tenant_id)
        )
        if search:
            like = f"%{search}%"
            base = base.where(or_(PurchaseOrder.po_number.ilike(like), Supplier.name.ilike(like), Supplier.supplier_code.ilike(like)))
        if status_filter:
            base = base.where(PurchaseOrder.status == status_filter)
        if supplier_id:
            base = base.where(PurchaseOrder.supplier_id == supplier_id)
        if date_from:
            base = base.where(PurchaseOrder.document_date >= date_from)
        if date_to:
            base = base.where(PurchaseOrder.document_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(PurchaseOrder.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(PurchaseOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        order_ids = [row[0].id for row in rows]
        totals_by_order = await self._quantity_totals_for_orders(order_ids)
        zero = QuantityTotals(ordered=Decimal("0"), received=Decimal("0"), remaining=Decimal("0"))
        items = [
            (row[0], row[1], totals_by_order.get(row[0].id, zero).ordered,
             totals_by_order.get(row[0].id, zero).received, totals_by_order.get(row[0].id, zero).remaining,
             row[2], row[3])
            for row in rows
        ]
        return PurchaseOrderPage(items=items, total_items=total_items)

    @staticmethod
    def totals_from_lines(lines: list[tuple[PurchaseOrderLine, UnitOfMeasure]]) -> QuantityTotals:
        """Pure helper — ordered/received/remaining computed directly from
        an already-fetched line list (no extra query), used by every
        entrypoint that already has the lines in hand (create/update/get/
        receiving-summary). `list_orders` is the one exception: it uses
        `_quantity_totals_for_orders` instead, to aggregate a whole page
        in a single query rather than N+1 round trips."""
        ordered = sum((line.quantity for line, _uom in lines), Decimal("0"))
        received = sum((line.received_quantity for line, _uom in lines), Decimal("0"))
        return QuantityTotals(ordered=ordered, received=received, remaining=ordered - received)

    async def get_order(
        self, *, tenant_id: uuid.UUID, order_id: uuid.UUID
    ) -> tuple[PurchaseOrder, str, list[tuple[PurchaseOrderLine, UnitOfMeasure]], QuantityTotals]:
        order, supplier_name, lines = await self._order_and_lines(tenant_id, order_id)
        return order, supplier_name, lines, self.totals_from_lines(lines)

    async def get_creator_names(self, order: PurchaseOrder) -> tuple[str | None, str | None]:
        """Resolves `created_by`/`updated_by` display names for a single
        already-fetched order — kept separate from `get_order`'s own tuple
        shape since that method is shared by GoodsReceiptService/
        PurchaseInvoiceService and widening it would ripple through every
        caller; this is a narrow, additive lookup used only by this
        router's own list/detail responses."""
        user_ids = [uid for uid in {order.created_by, order.updated_by} if uid is not None]
        if not user_ids:
            return None, None
        result = await self._session.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        names = dict(result.all())
        return names.get(order.created_by), names.get(order.updated_by)

    # --- related documents / receiving summary / audit history (PROMPT-020) ---

    async def get_related_documents(
        self, *, tenant_id: uuid.UUID, order_id: uuid.UUID
    ) -> tuple[PurchaseOrder, list[GoodsReceipt], list[PurchaseInvoice]]:
        """§17/§24/§34: every Goods Receipt sourced from this PO, plus
        every Purchase Invoice sourced from one of those Goods Receipts
        (a Purchase Invoice has no direct PO reference of its own — see
        PROMPT-019 Open Decision #2 — so it is only reachable transitively
        through its source Goods Receipt)."""
        result = await self._session.execute(
            select(PurchaseOrder, Supplier.name)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .where(PurchaseOrder.id == order_id, PurchaseOrder.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Purchase order not found", code=PO_NOT_FOUND)
        order = row[0]

        gr_result = await self._session.execute(
            select(GoodsReceipt)
            .where(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.source_purchase_order_id == order_id)
            .order_by(GoodsReceipt.created_at.asc())
        )
        goods_receipts = list(gr_result.scalars().all())

        gr_ids = [gr.id for gr in goods_receipts]
        invoices: list[PurchaseInvoice] = []
        if gr_ids:
            inv_result = await self._session.execute(
                select(PurchaseInvoice)
                .where(PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.source_goods_receipt_id.in_(gr_ids))
                .order_by(PurchaseInvoice.created_at.asc())
            )
            invoices = list(inv_result.scalars().all())

        return order, goods_receipts, invoices

    async def get_receiving_summary(
        self, *, tenant_id: uuid.UUID, order_id: uuid.UUID
    ) -> tuple[PurchaseOrder, list[tuple[PurchaseOrderLine, UnitOfMeasure]], QuantityTotals]:
        """§18/§19/§21: the authoritative ordered/received/remaining view,
        exposed as its own endpoint per §30's explicit "GET Purchase
        Order receiving summary" requirement — distinct from the
        eligibility endpoint `GoodsReceiptService.get_receipt_eligibility`
        exposes (that one is scoped to "how much CAN I receive right
        now," this one is scoped to "what IS the current state")."""
        order, _supplier_name, lines = await self._order_and_lines(tenant_id, order_id)
        return order, lines, self.totals_from_lines(lines)

    async def _order_and_lines(
        self, tenant_id: uuid.UUID, order_id: uuid.UUID
    ) -> tuple[PurchaseOrder, str, list[tuple[PurchaseOrderLine, UnitOfMeasure]]]:
        result = await self._session.execute(
            select(PurchaseOrder, Supplier.name)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
            .where(PurchaseOrder.id == order_id, PurchaseOrder.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Purchase order not found", code=PO_NOT_FOUND)
        order, supplier_name = row
        lines = await self._get_lines(order.id)
        return order, supplier_name, lines

    async def get_audit_history(self, *, tenant_id: uuid.UUID, order_id: uuid.UUID) -> list[AuditLog]:
        """§34/§38: the audit trail shown on the PO detail screen. No
        generic audit-read API exists anywhere in this codebase yet
        (audit_log has been write-only through every prior prompt) — this
        is a narrow, PO-scoped read, not a general audit-log endpoint."""
        # Confirm the order exists and belongs to this tenant first, so a
        # cross-tenant/nonexistent id returns the same 404 as everywhere
        # else rather than an empty (ambiguous) list.
        exists_result = await self._session.execute(
            select(PurchaseOrder.id).where(PurchaseOrder.id == order_id, PurchaseOrder.tenant_id == tenant_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Purchase order not found", code=PO_NOT_FOUND)

        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "purchase_order", AuditLog.entity_id == order_id)
            .order_by(AuditLog.occurred_at.asc())
        )
        return list(result.scalars().all())

    # --- create / update ----------------------------------------------------

    async def create_order(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, supplier_id: uuid.UUID, document_date: date | None,
        supplier_reference: str | None = None, expected_delivery_date: date | None = None,
        payment_terms: str | None = None, delivery_terms: str | None = None,
        shipping_address: str | None, notes: str | None, line_inputs: list[PurchaseOrderLineInput], ip_address: str | None,
    ) -> tuple[PurchaseOrder, str, list[tuple[PurchaseOrderLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        validated_supplier = await validate_supplier_for_purchase(self._session, tenant_id=tenant_id, supplier_id=supplier_id)
        supplier = validated_supplier.supplier

        gst_treatment = determine_gst_treatment(supplier_state_code=tenant.state_code, customer_state_code=supplier.state_code)
        doc_date = document_date or date.today()

        numbering = DocumentNumberingService(self._session)
        po_number = await numbering.next_number(tenant=tenant, document_type=PURCHASE_ORDER, prefix="PO")

        order = PurchaseOrder(
            tenant_id=tenant_id, po_number=po_number, supplier_id=supplier.id, supplier_gstin=supplier.gstin,
            # Purchase Order's "billing address" is the BUYER's (this
            # tenant's own business) address, unlike a Sales document's
            # billing_address (the customer's) — the tenant is who the
            # supplier bills.
            billing_address=tenant.address_line1,
            shipping_address=shipping_address or supplier.address,
            place_of_supply_state_code=supplier.state_code, document_date=doc_date,
            supplier_reference=supplier_reference, expected_delivery_date=expected_delivery_date,
            payment_terms=payment_terms, delivery_terms=delivery_terms,
            status=DRAFT, notes=notes,
            created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(order)
        await self._session.flush()

        lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
            await self._build_lines_from_input(tenant_id=tenant_id, order_id=order.id, line_inputs=line_inputs, gst_treatment=gst_treatment)
        )
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        order.subtotal = subtotal
        order.discount_total = discount_total
        order.taxable_total = taxable_total
        order.cgst_total = cgst_total
        order.sgst_total = sgst_total
        order.igst_total = igst_total
        order.tax_total = cgst_total + sgst_total + igst_total
        order.grand_total = grand_total
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_ORDER_CREATED",
            entity_type="purchase_order", entity_id=order.id, after=self._snapshot(order), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(order.id)
        return order, supplier.name, lines_with_uom

    async def update_order(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, order_id: uuid.UUID, expected_row_version: int,
        document_date: date | None, supplier_reference: str | None = None, expected_delivery_date: date | None = None,
        payment_terms: str | None = None, delivery_terms: str | None = None,
        shipping_address: str | None, notes: str | None,
        line_inputs: list[PurchaseOrderLineInput] | None, ip_address: str | None,
    ) -> tuple[PurchaseOrder, str, list[tuple[PurchaseOrderLine, UnitOfMeasure]]]:
        order = await self._get_order_locked(tenant_id, order_id)
        check_row_version(order, expected_row_version)

        if order.status != DRAFT:
            raise ValidationAppError("This purchase order has already been confirmed and cannot be edited.", code=PO_INVALID_STATUS)

        before = self._snapshot(order)
        tenant = await self._get_tenant(tenant_id)

        supplier_result = await self._session.execute(select(Supplier).where(Supplier.id == order.supplier_id))
        supplier = supplier_result.scalar_one()

        if document_date is not None:
            order.document_date = document_date
        if supplier_reference is not None:
            order.supplier_reference = supplier_reference
        if expected_delivery_date is not None:
            order.expected_delivery_date = expected_delivery_date
        if payment_terms is not None:
            order.payment_terms = payment_terms
        if delivery_terms is not None:
            order.delivery_terms = delivery_terms
        if shipping_address is not None:
            order.shipping_address = shipping_address
        if notes is not None:
            order.notes = notes

        if line_inputs is not None:
            gst_treatment = determine_gst_treatment(supplier_state_code=tenant.state_code, customer_state_code=supplier.state_code)
            existing_lines = await self._get_lines(order.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
                await self._build_lines_from_input(tenant_id=tenant_id, order_id=order.id, line_inputs=line_inputs, gst_treatment=gst_treatment)
            )
            for line in lines:
                line.created_by = actor_user_id
                line.updated_by = actor_user_id
                self._session.add(line)

            order.subtotal = subtotal
            order.discount_total = discount_total
            order.taxable_total = taxable_total
            order.cgst_total = cgst_total
            order.sgst_total = sgst_total
            order.igst_total = igst_total
            order.tax_total = cgst_total + sgst_total + igst_total
            order.grand_total = grand_total

        order.updated_by = actor_user_id
        order.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_ORDER_UPDATED",
            entity_type="purchase_order", entity_id=order.id, before=before, after=self._snapshot(order), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(order.id)
        return order, supplier.name, lines_with_uom

    # --- status transitions ------------------------------------------------

    async def confirm_order(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, order_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> PurchaseOrder:
        """§10 mandatory rule restated: confirmation NEVER touches
        inventory — no InventoryService import exists in this file."""
        order = await self._get_order_locked(tenant_id, order_id)
        check_row_version(order, expected_row_version)

        if order.status != DRAFT:
            raise ValidationAppError(f"Cannot confirm a purchase order in {order.status} status.", code=PO_INVALID_STATUS)

        await validate_supplier_for_purchase(self._session, tenant_id=tenant_id, supplier_id=order.supplier_id)
        lines = await self._get_lines(order.id)
        for line, _uom in lines:
            if line.product_id is not None:
                await validate_product_for_purchase(self._session, tenant_id=tenant_id, product_id=line.product_id)

        previous_status = order.status
        order.status = CONFIRMED
        order.updated_by = actor_user_id
        order.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_ORDER_CONFIRMED",
            entity_type="purchase_order", entity_id=order.id, before={"status": previous_status},
            after={"status": CONFIRMED}, ip_address=ip_address,
        )
        return order

    async def cancel_order(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, order_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> PurchaseOrder:
        order = await self._get_order_locked(tenant_id, order_id)
        check_row_version(order, expected_row_version)

        if order.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(f"Cannot cancel a purchase order in {order.status} status.", code=PO_INVALID_STATUS)

        previous_status = order.status
        order.status = CANCELLED
        order.updated_by = actor_user_id
        order.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PURCHASE_ORDER_CANCELLED",
            entity_type="purchase_order", entity_id=order.id, before={"status": previous_status},
            after={"status": CANCELLED}, ip_address=ip_address,
        )
        return order
