"""Goods Receipt service (PROMPT-019).

The FIRST Purchase document type that actually moves stock. §11 is a
MANDATORY business rule, mirroring `delivery_challan_service.py`'s
identical role in the Sales chain: DRAFT never touches inventory;
CONFIRMED creates exactly one Stock IN movement per line, atomically
with the status change and the source Purchase Order's receipt update.

Traceability chain (§37): GoodsReceipt -> GoodsReceiptLine ->
StockLedgerEntry (via `source_type='GOODS_RECEIPT'`,
`source_id=<goods_receipt_line.id>`) -> Product; and separately
GoodsReceipt.source_purchase_order_id -> PurchaseOrder ->
PurchaseOrderLine.received_quantity.

`source_id` is the LINE's id, not the header's — same duplicate-
movement-protection reasoning as every Sales document that moves stock
(the existing `uq_stock_ledger_entry_source` constraint needs a
per-movement-unique key for a multi-line document).
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
    GR_EXCEEDS_REMAINING,
    GR_HAS_DOWNSTREAM_INVOICE,
    GR_INVALID_QUANTITY,
    GR_INVALID_STATUS,
    GR_NOT_FOUND,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.purchase_constants import GOODS_RECEIPT, GOODS_RECEIPT_REVERSAL
from app.models.audit_log import AuditLog
from app.models.goods_receipt import CANCELLABLE_STATUSES, CANCELLED, CONFIRMED, DRAFT, GoodsReceipt
from app.models.goods_receipt_line import GoodsReceiptLine
from app.models.purchase_invoice import PurchaseInvoice
from app.models.purchase_order import RECEIPT_ELIGIBLE_STATUSES, PurchaseOrder
from app.models.purchase_order_line import PurchaseOrderLine
from app.models.stock_ledger_entry import STOCK_IN, STOCK_OUT, StockLedgerEntry
from app.models.supplier import Supplier
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.models.user import User
from app.schemas.purchase import ReceiptLineInput
from app.services.audit.audit_service import AuditService
from app.services.inventory.inventory_service import InventoryService
from app.services.purchase.purchase_order_service import PurchaseOrderService
from app.services.purchase.purchase_validation_service import validate_product_for_purchase
from app.services.sales.document_numbering_service import DocumentNumberingService


@dataclass(frozen=True)
class GoodsReceiptPage:
    items: list[tuple[GoodsReceipt, str, str, str | None, str | None]]  # (receipt, supplier_name, po_number, created_by_name, updated_by_name)
    total_items: int


@dataclass(frozen=True)
class ReceiptEligibilityLine:
    purchase_order_line: PurchaseOrderLine
    uom: UnitOfMeasure
    received_quantity: Decimal
    remaining_quantity: Decimal


class GoodsReceiptService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared helpers -----------------------------------------------

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _get_receipt_locked(self, tenant_id: uuid.UUID, receipt_id: uuid.UUID) -> GoodsReceipt:
        result = await self._session.execute(
            select(GoodsReceipt).where(GoodsReceipt.id == receipt_id, GoodsReceipt.tenant_id == tenant_id).with_for_update()
        )
        receipt = result.scalar_one_or_none()
        if receipt is None:
            raise NotFoundError("Goods receipt not found", code=GR_NOT_FOUND)
        return receipt

    async def _get_lines(self, receipt_id: uuid.UUID) -> list[tuple[GoodsReceiptLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(GoodsReceiptLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == GoodsReceiptLine.uom_id)
            .where(GoodsReceiptLine.goods_receipt_id == receipt_id)
            .order_by(GoodsReceiptLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    # --- public entrypoints for PurchaseInvoiceService ---------------------

    async def get_receipt_locked(self, tenant_id: uuid.UUID, receipt_id: uuid.UUID) -> GoodsReceipt:
        return await self._get_receipt_locked(tenant_id, receipt_id)

    async def get_lines(self, receipt_id: uuid.UUID) -> list[tuple[GoodsReceiptLine, UnitOfMeasure]]:
        return await self._get_lines(receipt_id)

    def _snapshot(self, receipt: GoodsReceipt) -> dict:
        return {
            "source_purchase_order_id": str(receipt.source_purchase_order_id) if receipt.source_purchase_order_id else None,
            "supplier_id": str(receipt.supplier_id),
            "document_date": receipt.document_date.isoformat(),
            "supplier_delivery_note": receipt.supplier_delivery_note,
            "status": receipt.status,
            "total_quantity": str(receipt.total_quantity),
        }

    async def stock_movement_info_for_lines(
        self, tenant_id: uuid.UUID, line_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[uuid.UUID | None, bool]]:
        """§42 Stock Impact Visibility: for each Goods Receipt line, the
        `stock_ledger_entry.id` its STOCK_IN posted as (source_type=
        GOODS_RECEIPT, source_id=<line.id>), plus whether a compensating
        STOCK_OUT reversal (source_type=GOODS_RECEIPT_REVERSAL, same
        source_id) has since been posted against it. Both are read-only
        lookups into the immutable stock ledger — never write paths."""
        if not line_ids:
            return {}
        result = await self._session.execute(
            select(StockLedgerEntry.source_id, StockLedgerEntry.source_type, StockLedgerEntry.id)
            .where(
                StockLedgerEntry.tenant_id == tenant_id,
                StockLedgerEntry.source_type.in_([GOODS_RECEIPT, GOODS_RECEIPT_REVERSAL]),
                StockLedgerEntry.source_id.in_(line_ids),
            )
        )
        info: dict[uuid.UUID, tuple[uuid.UUID | None, bool]] = {}
        for source_id, source_type, entry_id in result.all():
            movement_id, reversed_flag = info.get(source_id, (None, False))
            if source_type == GOODS_RECEIPT:
                movement_id = entry_id
            else:
                reversed_flag = True
            info[source_id] = (movement_id, reversed_flag)
        return info

    # --- receipt eligibility (§8/§9) -----------------------------------

    async def get_receipt_eligibility(
        self, *, tenant_id: uuid.UUID, purchase_order_id: uuid.UUID
    ) -> tuple[PurchaseOrder, str, list[ReceiptEligibilityLine]]:
        po_service = PurchaseOrderService(self._session)
        order, supplier_name, lines, _totals = await po_service.get_order(tenant_id=tenant_id, order_id=purchase_order_id)

        if order.status not in RECEIPT_ELIGIBLE_STATUSES:
            raise ValidationAppError(
                f"A purchase order in {order.status} status is not eligible for receiving.", code=GR_INVALID_STATUS
            )

        eligibility_lines = [
            ReceiptEligibilityLine(
                purchase_order_line=line, uom=uom, received_quantity=line.received_quantity,
                remaining_quantity=line.quantity - line.received_quantity,
            )
            for line, uom in lines
        ]
        return order, supplier_name, eligibility_lines

    # --- queries ---------------------------------------------------------

    async def list_receipts(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, search: str | None, status_filter: str | None,
        supplier_id: uuid.UUID | None, purchase_order_id: uuid.UUID | None, date_from: date | None, date_to: date | None,
    ) -> GoodsReceiptPage:
        creator = aliased(User)
        updater = aliased(User)
        base = (
            select(GoodsReceipt, Supplier.name, PurchaseOrder.po_number, creator.name, updater.name)
            .join(Supplier, Supplier.id == GoodsReceipt.supplier_id)
            .outerjoin(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.source_purchase_order_id)
            .outerjoin(creator, creator.id == GoodsReceipt.created_by)
            .outerjoin(updater, updater.id == GoodsReceipt.updated_by)
            .where(GoodsReceipt.tenant_id == tenant_id)
        )
        if search:
            like = f"%{search}%"
            base = base.where(or_(GoodsReceipt.grn_number.ilike(like), PurchaseOrder.po_number.ilike(like), Supplier.name.ilike(like)))
        if status_filter:
            base = base.where(GoodsReceipt.status == status_filter)
        if supplier_id:
            base = base.where(GoodsReceipt.supplier_id == supplier_id)
        if purchase_order_id:
            base = base.where(GoodsReceipt.source_purchase_order_id == purchase_order_id)
        if date_from:
            base = base.where(GoodsReceipt.document_date >= date_from)
        if date_to:
            base = base.where(GoodsReceipt.document_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(GoodsReceipt.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(GoodsReceipt.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        return GoodsReceiptPage(items=[(row[0], row[1], row[2], row[3], row[4]) for row in rows], total_items=total_items)

    async def get_creator_names(self, receipt: GoodsReceipt) -> tuple[str | None, str | None]:
        """Narrow, additive lookup — mirrors PurchaseOrderService's own
        `get_creator_names`; kept separate from `get_receipt`'s tuple shape
        since that method is also called from PurchaseInvoiceService."""
        user_ids = [uid for uid in {receipt.created_by, receipt.updated_by} if uid is not None]
        if not user_ids:
            return None, None
        result = await self._session.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        names = dict(result.all())
        return names.get(receipt.created_by), names.get(receipt.updated_by)

    async def get_receipt(
        self, *, tenant_id: uuid.UUID, receipt_id: uuid.UUID
    ) -> tuple[
        GoodsReceipt, str, str | None, list[tuple[GoodsReceiptLine, UnitOfMeasure]],
        dict[uuid.UUID, tuple[uuid.UUID | None, bool]],
    ]:
        result = await self._session.execute(
            select(GoodsReceipt, Supplier.name, PurchaseOrder.po_number)
            .join(Supplier, Supplier.id == GoodsReceipt.supplier_id)
            .outerjoin(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.source_purchase_order_id)
            .where(GoodsReceipt.id == receipt_id, GoodsReceipt.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Goods receipt not found", code=GR_NOT_FOUND)
        receipt, supplier_name, po_number = row
        lines = await self._get_lines(receipt.id)
        stock_info = await self.stock_movement_info_for_lines(tenant_id, [line.id for line, _uom in lines])
        return receipt, supplier_name, po_number, lines, stock_info

    # --- line building (shared by create/update) ----------------------------

    async def _build_lines(
        self, *, tenant_id: uuid.UUID, receipt_id: uuid.UUID, order: PurchaseOrder, line_inputs: list[ReceiptLineInput],
    ) -> tuple[list[GoodsReceiptLine], Decimal]:
        po_service = PurchaseOrderService(self._session)
        po_lines = await po_service.get_lines(order.id)
        po_lines_by_id = {line.id: (line, uom) for line, uom in po_lines}

        lines: list[GoodsReceiptLine] = []
        total_quantity = Decimal("0")

        for index, line_input in enumerate(line_inputs, start=1):
            po_line_id = uuid.UUID(line_input.purchase_order_line_id)
            match = po_lines_by_id.get(po_line_id)
            if match is None:
                raise ValidationAppError("The selected purchase order line does not belong to this purchase order.", code=GR_INVALID_QUANTITY)
            po_line, uom = match

            if po_line.product_id is not None:
                validated_product = await validate_product_for_purchase(self._session, tenant_id=tenant_id, product_id=po_line.product_id)
                product = validated_product.product
            else:
                product = None

            remaining = po_line.quantity - po_line.received_quantity
            if line_input.quantity > remaining:
                raise ValidationAppError(
                    f"Receipt quantity {line_input.quantity} exceeds remaining quantity {remaining}.", code=GR_EXCEEDS_REMAINING
                )

            total_quantity += line_input.quantity
            lines.append(
                GoodsReceiptLine(
                    tenant_id=tenant_id, goods_receipt_id=receipt_id, line_no=index,
                    source_purchase_order_line_id=po_line.id, product_id=po_line.product_id,
                    description=po_line.description, hsn_code=po_line.hsn_code, uom_id=uom.id,
                    ordered_quantity=po_line.quantity, previously_received_quantity=po_line.received_quantity,
                    quantity=line_input.quantity, remaining_quantity=remaining - line_input.quantity,
                    unit_price=po_line.unit_price, discount_amount=Decimal("0"),
                    taxable_amount=po_line.unit_price * line_input.quantity, gst_rate=po_line.gst_rate,
                    line_total=po_line.unit_price * line_input.quantity,
                )
            )

        return lines, total_quantity

    # --- create / update (DRAFT only) ---------------------------------------

    async def create_receipt(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_order_id: uuid.UUID, document_date: date | None,
        supplier_delivery_note: str | None = None,
        notes: str | None, line_inputs: list[ReceiptLineInput], ip_address: str | None,
    ) -> tuple[GoodsReceipt, str, str | None, list[tuple[GoodsReceiptLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        po_service = PurchaseOrderService(self._session)
        order, _supplier_name, _lines, _totals = await po_service.get_order(tenant_id=tenant_id, order_id=purchase_order_id)

        if order.status not in RECEIPT_ELIGIBLE_STATUSES:
            raise ValidationAppError(f"A purchase order in {order.status} status is not eligible for receiving.", code=GR_INVALID_STATUS)

        validated_supplier_result = await self._session.execute(select(Supplier).where(Supplier.id == order.supplier_id))
        supplier = validated_supplier_result.scalar_one()

        doc_date = document_date or date.today()
        numbering = DocumentNumberingService(self._session)
        grn_number = await numbering.next_number(tenant=tenant, document_type=GOODS_RECEIPT, prefix="GRN")

        receipt = GoodsReceipt(
            tenant_id=tenant_id, grn_number=grn_number, supplier_id=supplier.id, supplier_gstin=supplier.gstin,
            place_of_supply_state_code=order.place_of_supply_state_code, source_purchase_order_id=order.id,
            document_date=doc_date, supplier_delivery_note=supplier_delivery_note,
            status=DRAFT, notes=notes, created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(receipt)
        await self._session.flush()

        lines, total_quantity = await self._build_lines(tenant_id=tenant_id, receipt_id=receipt.id, order=order, line_inputs=line_inputs)
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        receipt.total_quantity = total_quantity
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="GOODS_RECEIPT_CREATED",
            entity_type="goods_receipt", entity_id=receipt.id, after=self._snapshot(receipt), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(receipt.id)
        return receipt, supplier.name, order.po_number, lines_with_uom

    async def update_receipt(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, receipt_id: uuid.UUID, expected_row_version: int,
        document_date: date | None, supplier_delivery_note: str | None = None,
        notes: str | None, line_inputs: list[ReceiptLineInput] | None, ip_address: str | None,
    ) -> tuple[GoodsReceipt, str, str | None, list[tuple[GoodsReceiptLine, UnitOfMeasure]]]:
        receipt = await self._get_receipt_locked(tenant_id, receipt_id)
        check_row_version(receipt, expected_row_version)

        if receipt.status != DRAFT:
            raise ValidationAppError("This goods receipt has already been confirmed and cannot be edited.", code=GR_INVALID_STATUS)

        before = self._snapshot(receipt)

        if document_date is not None:
            receipt.document_date = document_date
        if supplier_delivery_note is not None:
            receipt.supplier_delivery_note = supplier_delivery_note
        if notes is not None:
            receipt.notes = notes

        po_service = PurchaseOrderService(self._session)
        order, supplier_name, _lines, _totals = await po_service.get_order(tenant_id=tenant_id, order_id=receipt.source_purchase_order_id)

        if line_inputs is not None:
            existing_lines = await self._get_lines(receipt.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, total_quantity = await self._build_lines(tenant_id=tenant_id, receipt_id=receipt.id, order=order, line_inputs=line_inputs)
            for line in lines:
                line.created_by = actor_user_id
                line.updated_by = actor_user_id
                self._session.add(line)
            receipt.total_quantity = total_quantity

        receipt.updated_by = actor_user_id
        receipt.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="GOODS_RECEIPT_UPDATED",
            entity_type="goods_receipt", entity_id=receipt.id, before=before, after=self._snapshot(receipt), ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(receipt.id)
        return receipt, supplier_name, order.po_number, lines_with_uom

    # --- confirm (§11/§28: the atomic stock-in + receipt core) --------------

    async def confirm_receipt(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, receipt_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> tuple[GoodsReceipt, str, str | None, list[tuple[GoodsReceiptLine, UnitOfMeasure]]]:
        receipt = await self._get_receipt_locked(tenant_id, receipt_id)
        check_row_version(receipt, expected_row_version)

        if receipt.status != DRAFT:
            raise ValidationAppError(f"Cannot confirm a goods receipt in {receipt.status} status.", code=GR_INVALID_STATUS)

        po_service = PurchaseOrderService(self._session)
        order = await po_service.get_order_locked(tenant_id, receipt.source_purchase_order_id)
        if order.status not in RECEIPT_ELIGIBLE_STATUSES:
            raise ValidationAppError(
                f"The source purchase order is in {order.status} status and can no longer be received against.", code=GR_INVALID_STATUS
            )

        po_lines = await po_service.get_lines(order.id)
        po_lines_by_id = {line.id: (line, uom) for line, uom in po_lines}

        receipt_lines = await self._get_lines(receipt.id)
        inventory = InventoryService(self._session)
        location = await inventory.ensure_default_location(tenant_id)
        line_receipts: dict[uuid.UUID, Decimal] = {}

        for gr_line, gr_uom in receipt_lines:
            match = po_lines_by_id.get(gr_line.source_purchase_order_line_id)
            if match is None:
                raise ValidationAppError("The source purchase order line no longer exists.", code=GR_INVALID_QUANTITY)
            po_line, _po_uom = match

            live_remaining = po_line.quantity - po_line.received_quantity
            if gr_line.quantity > live_remaining:
                raise ValidationAppError(
                    f"Receipt quantity {gr_line.quantity} exceeds remaining quantity {live_remaining}.", code=GR_EXCEEDS_REMAINING
                )

            gr_line.previously_received_quantity = po_line.received_quantity
            gr_line.remaining_quantity = live_remaining - gr_line.quantity

            if gr_line.product_id is not None:
                await validate_product_for_purchase(self._session, tenant_id=tenant_id, product_id=gr_line.product_id)
                product = await inventory.get_active_product_locked(tenant_id, gr_line.product_id)

                await inventory.post_movement(
                    tenant_id=tenant_id, actor_user_id=actor_user_id, product=product, location=location,
                    movement_type=STOCK_IN, quantity=gr_line.quantity, uom=gr_uom,
                    source_type=GOODS_RECEIPT, source_id=gr_line.id, audit_action="STOCK_IN_CREATED",
                    audit_extra={"goods_receipt_id": str(receipt.id), "grn_number": receipt.grn_number, "source_purchase_order_id": str(order.id)},
                    ip_address=ip_address,
                )

            line_receipts[po_line.id] = gr_line.quantity

        await po_service.apply_receipt(tenant_id=tenant_id, actor_user_id=actor_user_id, order=order, line_receipts=line_receipts, ip_address=ip_address)

        previous_status = receipt.status
        receipt.status = CONFIRMED
        receipt.updated_by = actor_user_id
        receipt.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="GOODS_RECEIPT_CONFIRMED",
            entity_type="goods_receipt", entity_id=receipt.id, before={"status": previous_status},
            after={"status": CONFIRMED}, ip_address=ip_address,
        )

        supplier_result = await self._session.execute(select(Supplier.name).where(Supplier.id == receipt.supplier_id))
        supplier_name = supplier_result.scalar_one()
        lines_with_uom = await self._get_lines(receipt.id)
        return receipt, supplier_name, order.po_number, lines_with_uom

    # --- cancel (DRAFT: no stock impact; CONFIRMED: compensating reversal) --

    async def cancel_receipt(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, receipt_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> GoodsReceipt:
        """§23-25: cancelling a DRAFT GR is a pure status change (no stock
        ever moved for it). Cancelling a CONFIRMED GR is a controlled
        REVERSAL, not a deletion — gated by (a) no downstream Purchase
        Invoice against any line of this GR, and (b) the InventoryService's
        own negative-stock guard (if the received stock was already
        consumed elsewhere, the compensating STOCK_OUT is rejected). The
        original STOCK_IN ledger entries are NEVER edited or deleted
        (INVARIANT 7) — only compensated via a NEW `GOODS_RECEIPT_REVERSAL`
        entry per line (INVARIANT 8)."""
        receipt = await self._get_receipt_locked(tenant_id, receipt_id)
        check_row_version(receipt, expected_row_version)

        if receipt.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(f"Cannot cancel a goods receipt in {receipt.status} status.", code=GR_INVALID_STATUS)

        previous_status = receipt.status

        if previous_status == DRAFT:
            receipt.status = CANCELLED
            receipt.updated_by = actor_user_id
            receipt.row_version += 1
            await self._session.flush()

            await AuditService(self._session).record(
                tenant_id=tenant_id, actor_user_id=actor_user_id, action="GOODS_RECEIPT_CANCELLED",
                entity_type="goods_receipt", entity_id=receipt.id, before={"status": previous_status},
                after={"status": CANCELLED}, ip_address=ip_address,
            )
            return receipt

        # previous_status == CONFIRMED: this is a reversal, not a simple cancel.
        receipt_lines = await self._get_lines(receipt.id)

        if any(gr_line.invoiced_quantity > 0 for gr_line, _uom in receipt_lines):
            raise ValidationAppError(
                "Goods Receipt cannot be cancelled because a Purchase Invoice has already been created against this receipt.",
                code=GR_HAS_DOWNSTREAM_INVOICE,
            )

        po_service = PurchaseOrderService(self._session)
        order = await po_service.get_order_locked(tenant_id, receipt.source_purchase_order_id)

        inventory = InventoryService(self._session)
        location = await inventory.ensure_default_location(tenant_id)
        line_reversals: dict[uuid.UUID, Decimal] = {}

        for gr_line, gr_uom in receipt_lines:
            if gr_line.product_id is not None:
                product = await inventory.get_active_product_locked(tenant_id, gr_line.product_id)

                # If the received stock has already been consumed elsewhere
                # (e.g. a Sales dispatch), this raises ConflictError — the
                # reversal is rejected rather than forced through negative
                # stock (§60 #5, negative-stock policy unchanged from
                # PROMPT-010).
                await inventory.post_movement(
                    tenant_id=tenant_id, actor_user_id=actor_user_id, product=product, location=location,
                    movement_type=STOCK_OUT, quantity=gr_line.quantity, uom=gr_uom,
                    source_type=GOODS_RECEIPT_REVERSAL, source_id=gr_line.id, audit_action="STOCK_IN_REVERSED",
                    audit_extra={"goods_receipt_id": str(receipt.id), "grn_number": receipt.grn_number, "reason": "GOODS_RECEIPT_CANCELLED"},
                    ip_address=ip_address,
                )

            if gr_line.source_purchase_order_line_id is not None:
                line_reversals[gr_line.source_purchase_order_line_id] = gr_line.quantity

        await po_service.apply_reversal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, order=order, line_reversals=line_reversals, ip_address=ip_address,
        )

        receipt.status = CANCELLED
        receipt.updated_by = actor_user_id
        receipt.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="GOODS_RECEIPT_CANCELLED",
            entity_type="goods_receipt", entity_id=receipt.id, before={"status": previous_status},
            after={"status": CANCELLED, "stock_reversed": True}, ip_address=ip_address,
        )
        return receipt

    # --- related documents / audit history (PROMPT-021) ---------------------

    async def get_related_documents(
        self, *, tenant_id: uuid.UUID, receipt_id: uuid.UUID
    ) -> tuple[GoodsReceipt, PurchaseOrder | None, list[PurchaseInvoice]]:
        """§18/§34/§41: the source Purchase Order plus every Purchase
        Invoice created against this Goods Receipt."""
        result = await self._session.execute(
            select(GoodsReceipt).where(GoodsReceipt.id == receipt_id, GoodsReceipt.tenant_id == tenant_id)
        )
        receipt = result.scalar_one_or_none()
        if receipt is None:
            raise NotFoundError("Goods receipt not found", code=GR_NOT_FOUND)

        order: PurchaseOrder | None = None
        if receipt.source_purchase_order_id is not None:
            order_result = await self._session.execute(
                select(PurchaseOrder).where(PurchaseOrder.id == receipt.source_purchase_order_id, PurchaseOrder.tenant_id == tenant_id)
            )
            order = order_result.scalar_one_or_none()

        inv_result = await self._session.execute(
            select(PurchaseInvoice)
            .where(PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.source_goods_receipt_id == receipt_id)
            .order_by(PurchaseInvoice.created_at.asc())
        )
        invoices = list(inv_result.scalars().all())

        return receipt, order, invoices

    async def get_audit_history(self, *, tenant_id: uuid.UUID, receipt_id: uuid.UUID) -> list[AuditLog]:
        """§46: the audit trail shown on the GR detail screen — mirrors
        `PurchaseOrderService.get_audit_history`'s exact discipline
        (narrow, entity-scoped, tenant-ownership-checked first)."""
        exists_result = await self._session.execute(
            select(GoodsReceipt.id).where(GoodsReceipt.id == receipt_id, GoodsReceipt.tenant_id == tenant_id)
        )
        if exists_result.scalar_one_or_none() is None:
            raise NotFoundError("Goods receipt not found", code=GR_NOT_FOUND)

        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.entity_type == "goods_receipt", AuditLog.entity_id == receipt_id)
            .order_by(AuditLog.occurred_at.asc())
        )
        return list(result.scalars().all())
