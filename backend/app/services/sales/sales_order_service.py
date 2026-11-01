"""Sales Order service (PROMPT-013).

The second concrete Sales document type, built directly on PROMPT-011's
foundation exactly like `estimate_service.py`:
- GST amounts come from `gst_calculation_service` (never invented here).
- Customer/product validation comes from `sales_validation_service`.
- Document numbers come from `document_numbering_service`.
- Sales Orders NEVER touch inventory — no call to InventoryService
  anywhere in this file. §4 is a MANDATORY business rule: creation,
  editing, confirmation, and cancellation must never create a stock
  ledger entry. A Sales Order is a commercial commitment, not a stock
  movement — that happens later via Delivery Challan / Sales Invoice
  (neither of which exists yet).

Server-side calculation is authoritative (§33): every financial value in
`SalesLineInput` the client submits is used as *input* for a manual
create/edit, but gross/discount/taxable/GST/totals are always recomputed
here — never trusted as a pre-computed client value. Converting FROM an
Estimate is the one exception: that path deliberately reuses the
Estimate's own already-server-calculated snapshot (see
`create_from_estimate`'s docstring) rather than re-pricing what the
customer already agreed to.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.concurrency import check_row_version
from app.core.error_codes import SO_INVALID_STATUS, SO_NOT_FOUND
from app.core.exceptions import NotFoundError, ValidationAppError
from app.core.sales_constants import SALES_ORDER
from app.models.customer import Customer
from app.models.user import User
from app.models.sales_order import (
    CANCELLABLE_STATUSES,
    CANCELLED,
    CONFIRMED,
    DRAFT,
    FULFILLED,
    PARTIALLY_FULFILLED,
    SalesOrder,
)
from app.models.sales_order_line import SalesOrderLine
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.sales_common import SalesLineInput
from app.services.audit.audit_service import AuditService
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.models.sales_estimate import SalesEstimate
from app.services.sales.estimate_service import EstimateService
from app.services.sales.gst_calculation_service import (
    calculate_document_totals,
    calculate_line,
    determine_gst_treatment,
)
from app.services.sales.sales_validation_service import (
    validate_customer_for_sale,
    validate_product_for_sale,
)


@dataclass(frozen=True)
class SalesOrderPage:
    items: list[tuple[SalesOrder, str, str | None, str | None]]  # (order, customer_name, created_by_name, updated_by_name)
    total_items: int


class SalesOrderService:
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
            raise ValidationAppError("Select a valid unit.", code=SO_NOT_FOUND)
        return unit

    async def _get_order_locked(self, tenant_id: uuid.UUID, order_id: uuid.UUID) -> SalesOrder:
        result = await self._session.execute(
            select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id).with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise NotFoundError("Sales order not found", code=SO_NOT_FOUND)
        return order

    async def _get_lines(self, order_id: uuid.UUID) -> list[tuple[SalesOrderLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(SalesOrderLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == SalesOrderLine.uom_id)
            .where(SalesOrderLine.order_id == order_id)
            .order_by(SalesOrderLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    # --- public entrypoints for PROMPT-014's DeliveryChallanService ---------

    async def get_order_locked(self, tenant_id: uuid.UUID, order_id: uuid.UUID) -> SalesOrder:
        """Locks the Sales Order row (`SELECT ... FOR UPDATE`) so two
        concurrent Delivery Challan confirmations against the same order
        serialize instead of racing (§19/§20 of PROMPT-014) — the second
        transaction blocks here until the first commits, then every
        subsequent read in this same transaction (READ COMMITTED) sees the
        first transaction's already-applied `delivered_quantity` changes."""
        return await self._get_order_locked(tenant_id, order_id)

    async def get_lines(self, order_id: uuid.UUID) -> list[tuple[SalesOrderLine, UnitOfMeasure]]:
        return await self._get_lines(order_id)

    async def apply_delivery(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        order: SalesOrder,
        line_deliveries: dict[uuid.UUID, Decimal],
        ip_address: str | None,
    ) -> None:
        """§23 of PROMPT-014: the ONE place `sales_order_line.delivered_quantity`
        and `sales_order.status` are ever updated for fulfillment — called
        by `DeliveryChallanService.confirm_challan` inside that same
        transaction, after the order row is already locked
        (`get_order_locked`) and the Stock OUT movement(s) for this
        Delivery Challan have already posted successfully. `line_deliveries`
        maps `sales_order_line.id` -> quantity just confirmed for that line.

        Recomputes the order's overall status from ALL of its lines (not
        just the ones in this delivery), so a Delivery Challan covering
        only some products still correctly leaves the order
        PARTIALLY_FULFILLED rather than jumping straight to FULFILLED."""
        all_lines = await self._get_lines(order.id)
        for line, _uom in all_lines:
            increment = line_deliveries.get(line.id)
            if increment is not None:
                line.delivered_quantity += increment
                line.updated_by = actor_user_id

        previous_status = order.status
        if all(line.delivered_quantity >= line.quantity for line, _uom in all_lines):
            order.status = FULFILLED
        else:
            order.status = PARTIALLY_FULFILLED
        order.updated_by = actor_user_id
        order.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_ORDER_FULFILLMENT_UPDATED",
            entity_type="sales_order",
            entity_id=order.id,
            before={"status": previous_status},
            after={
                "status": order.status,
                "line_deliveries": {str(k): str(v) for k, v in line_deliveries.items()},
            },
            ip_address=ip_address,
        )

    async def _build_lines_from_input(
        self,
        *,
        tenant_id: uuid.UUID,
        order_id: uuid.UUID,
        line_inputs: list[SalesLineInput],
        gst_treatment: str,
    ) -> tuple[list[SalesOrderLine], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        """Manual create/edit path (§33): validates every line's
        product/unit and recomputes all financial values server-side —
        never trusting any client-submitted amount."""
        lines: list[SalesOrderLine] = []
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
                SalesOrderLine(
                    tenant_id=tenant_id,
                    order_id=order_id,
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
            lines,
            totals.subtotal,
            totals.total_discount,
            totals.total_taxable,
            totals.total_cgst,
            totals.total_sgst,
            totals.total_igst,
            totals.grand_total,
        )

    def _snapshot(self, order: SalesOrder) -> dict:
        return {
            "customer_id": str(order.customer_id),
            "order_date": order.order_date.isoformat(),
            "status": order.status,
            "grand_total": str(order.grand_total),
            "source_estimate_id": str(order.source_estimate_id) if order.source_estimate_id else None,
        }

    # --- queries ---------------------------------------------------------

    async def list_orders(
        self,
        *,
        tenant_id: uuid.UUID,
        page: int,
        page_size: int,
        search: str | None,
        status_filter: str | None,
        customer_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
        from_estimate_only: bool | None,
    ) -> SalesOrderPage:
        creator = aliased(User)
        updater = aliased(User)
        base = (
            select(SalesOrder, Customer.name, creator.name, updater.name)
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .outerjoin(creator, creator.id == SalesOrder.created_by)
            .outerjoin(updater, updater.id == SalesOrder.updated_by)
            .where(SalesOrder.tenant_id == tenant_id)
        )

        if search:
            like = f"%{search}%"
            base = base.where(
                or_(SalesOrder.order_number.ilike(like), Customer.name.ilike(like), Customer.customer_code.ilike(like))
            )
        if status_filter:
            base = base.where(SalesOrder.status == status_filter)
        if customer_id:
            base = base.where(SalesOrder.customer_id == customer_id)
        if date_from:
            base = base.where(SalesOrder.order_date >= date_from)
        if date_to:
            base = base.where(SalesOrder.order_date <= date_to)
        if from_estimate_only is True:
            base = base.where(SalesOrder.source_estimate_id.isnot(None))
        elif from_estimate_only is False:
            base = base.where(SalesOrder.source_estimate_id.is_(None))

        count_stmt = select(func.count()).select_from(base.with_only_columns(SalesOrder.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(SalesOrder.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return SalesOrderPage(items=[(row[0], row[1], row[2], row[3]) for row in rows], total_items=total_items)

    async def get_order(
        self, *, tenant_id: uuid.UUID, order_id: uuid.UUID
    ) -> tuple[SalesOrder, str, str | None, str | None, list[tuple[SalesOrderLine, UnitOfMeasure]]]:
        creator = aliased(User)
        updater = aliased(User)
        result = await self._session.execute(
            select(SalesOrder, Customer.name, creator.name, updater.name)
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .outerjoin(creator, creator.id == SalesOrder.created_by)
            .outerjoin(updater, updater.id == SalesOrder.updated_by)
            .where(SalesOrder.id == order_id, SalesOrder.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Sales order not found", code=SO_NOT_FOUND)
        order, customer_name, created_by_name, updated_by_name = row
        lines = await self._get_lines(order.id)
        return order, customer_name, created_by_name, updated_by_name, lines

    # --- create / update (manual) -------------------------------------------

    async def create_order(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        order_date: date | None,
        shipping_address: str | None,
        notes: str | None,
        line_inputs: list[SalesLineInput],
        ip_address: str | None,
    ) -> tuple[SalesOrder, str, list[tuple[SalesOrderLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        validated_customer = await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=customer_id)
        customer = validated_customer.customer

        gst_treatment = determine_gst_treatment(
            supplier_state_code=tenant.state_code, customer_state_code=customer.state_code
        )

        doc_date = order_date or date.today()

        numbering = DocumentNumberingService(self._session)
        order_number = await numbering.next_number(tenant=tenant, document_type=SALES_ORDER, prefix="SO")

        order = SalesOrder(
            tenant_id=tenant_id,
            order_number=order_number,
            customer_id=customer.id,
            order_date=doc_date,
            status=DRAFT,
            customer_gstin=customer.gstin,
            billing_address=customer.address,
            # §8/proposed addition: defaults to billing address at creation
            # time; a caller may override it per order (no separate
            # shipping-address source exists in Customer Master).
            shipping_address=shipping_address or customer.address,
            place_of_supply_state_code=customer.state_code,
            notes=notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(order)
        await self._session.flush()

        lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
            await self._build_lines_from_input(
                tenant_id=tenant_id, order_id=order.id, line_inputs=line_inputs, gst_treatment=gst_treatment
            )
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
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_ORDER_CREATED",
            entity_type="sales_order",
            entity_id=order.id,
            after=self._snapshot(order),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(order.id)
        return order, customer.name, lines_with_uom

    async def update_order(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
        expected_row_version: int,
        customer_id: uuid.UUID | None,
        order_date: date | None,
        shipping_address: str | None,
        notes: str | None,
        line_inputs: list[SalesLineInput] | None,
        ip_address: str | None,
    ) -> tuple[SalesOrder, str, list[tuple[SalesOrderLine, UnitOfMeasure]]]:
        order = await self._get_order_locked(tenant_id, order_id)
        check_row_version(order, expected_row_version)

        # §19: only DRAFT is editable — once CONFIRMED, no unrestricted
        # editing (and CANCELLED is terminal).
        if order.status != DRAFT:
            raise ValidationAppError(
                "This sales order has already been confirmed and cannot be edited in this status.",
                code=SO_INVALID_STATUS,
            )

        before = self._snapshot(order)
        tenant = await self._get_tenant(tenant_id)

        customer = None
        if customer_id is not None:
            validated_customer = await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=customer_id)
            customer = validated_customer.customer
            order.customer_id = customer.id
            order.customer_gstin = customer.gstin
            order.billing_address = customer.address
            order.place_of_supply_state_code = customer.state_code
        else:
            customer_result = await self._session.execute(select(Customer).where(Customer.id == order.customer_id))
            customer = customer_result.scalar_one()

        if order_date is not None:
            order.order_date = order_date
        if shipping_address is not None:
            order.shipping_address = shipping_address
        if notes is not None:
            order.notes = notes

        if line_inputs is not None:
            gst_treatment = determine_gst_treatment(
                supplier_state_code=tenant.state_code, customer_state_code=customer.state_code
            )
            # Replace lines wholesale — simplest correct approach for a
            # DRAFT-only edit, matching EstimateService.update_estimate.
            existing_lines = await self._get_lines(order.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
                await self._build_lines_from_input(
                    tenant_id=tenant_id, order_id=order.id, line_inputs=line_inputs, gst_treatment=gst_treatment
                )
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
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_ORDER_UPDATED",
            entity_type="sales_order",
            entity_id=order.id,
            before=before,
            after=self._snapshot(order),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(order.id)
        return order, customer.name, lines_with_uom

    # --- status transitions ------------------------------------------------

    async def confirm_order(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> SalesOrder:
        """§20: recalculates nothing new (totals are already server-
        authoritative from create/edit), re-validates customer/product
        state, flips DRAFT -> CONFIRMED. MUST NOT touch inventory, create
        an invoice, or post accounting — none of those services are even
        imported into this file."""
        order = await self._get_order_locked(tenant_id, order_id)
        check_row_version(order, expected_row_version)

        if order.status != DRAFT:
            raise ValidationAppError(f"Cannot confirm a sales order in {order.status} status.", code=SO_INVALID_STATUS)

        # Re-validate customer/products are still usable at confirmation
        # time (§20 step 3) — a manual DRAFT could sit unconfirmed for a
        # while, during which a customer/product might be deactivated.
        await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=order.customer_id)
        lines = await self._get_lines(order.id)
        for line, _uom in lines:
            if line.product_id is not None:
                await validate_product_for_sale(self._session, tenant_id=tenant_id, product_id=line.product_id)

        previous_status = order.status
        order.status = CONFIRMED
        order.updated_by = actor_user_id
        order.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_ORDER_CONFIRMED",
            entity_type="sales_order",
            entity_id=order.id,
            before={"status": previous_status},
            after={"status": CONFIRMED},
            ip_address=ip_address,
        )
        return order

    async def cancel_order(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        order_id: uuid.UUID,
        expected_row_version: int,
        cancellation_reason: str,
        ip_address: str | None,
    ) -> SalesOrder:
        """§21: cancellation is status-controlled and creates NO stock
        reversal — a Sales Order itself never moved stock in the first
        place (§4). Preserves all historical data; only `status` (and the
        new `cancellation_reason`) changes."""
        order = await self._get_order_locked(tenant_id, order_id)
        check_row_version(order, expected_row_version)

        if order.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(f"Cannot cancel a sales order in {order.status} status.", code=SO_INVALID_STATUS)

        previous_status = order.status
        order.status = CANCELLED
        order.cancellation_reason = cancellation_reason
        order.updated_by = actor_user_id
        order.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_ORDER_CANCELLED",
            entity_type="sales_order",
            entity_id=order.id,
            before={"status": previous_status},
            after={"status": CANCELLED, "cancellation_reason": cancellation_reason},
            ip_address=ip_address,
        )
        return order

    # --- conversion from Estimate (§15-18) -----------------------------------

    async def create_from_estimate(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        estimate_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> tuple[SalesOrder, str, list[tuple[SalesOrderLine, UnitOfMeasure]], SalesEstimate]:
        """§15: validates the Estimate, marks it CONVERTED (delegated to
        `EstimateService.convert_to_sales_order`, which owns that entity's
        own eligibility rules and locking), then builds a real Sales Order
        from the Estimate's own frozen line snapshot in the SAME session —
        so a failure anywhere in this method rolls back the Estimate's
        status change too (§15: "If any step fails: rollback transaction,
        Estimate remains unchanged, no partial Sales Order"). §16's
        `uq_sales_order_source_estimate` DB constraint is the final
        backstop against a duplicate Sales Order even if application logic
        had a gap.

        Design decision (documented, not silently chosen — see
        PROMPT-013-NOTES.md): the new Sales Order's lines/totals are
        copied verbatim from the Estimate's own already-server-calculated
        snapshot rather than re-priced from the CURRENT Product Master.
        The Estimate is the quote the customer already accepted; silently
        re-pricing it at conversion time would contradict that. Products
        are still re-validated as existing/active (§15 step 6) — an
        inactive product blocks conversion, it just doesn't get re-priced.
        """
        estimate_service = EstimateService(self._session)
        estimate = await estimate_service.convert_to_sales_order(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            estimate_id=estimate_id,
            expected_row_version=expected_row_version,
            ip_address=ip_address,
        )

        # §15 steps 5-6: verify customer/products still exist/usable.
        validated_customer = await validate_customer_for_sale(
            self._session, tenant_id=tenant_id, customer_id=estimate.customer_id
        )
        customer = validated_customer.customer

        estimate_lines = await estimate_service.get_lines(estimate.id)
        for est_line, _uom in estimate_lines:
            if est_line.product_id is not None:
                await validate_product_for_sale(self._session, tenant_id=tenant_id, product_id=est_line.product_id)

        tenant = await self._get_tenant(tenant_id)
        numbering = DocumentNumberingService(self._session)
        order_number = await numbering.next_number(tenant=tenant, document_type=SALES_ORDER, prefix="SO")

        order = SalesOrder(
            tenant_id=tenant_id,
            order_number=order_number,
            customer_id=customer.id,
            order_date=date.today(),
            status=DRAFT,
            customer_gstin=estimate.customer_gstin,
            billing_address=estimate.billing_address,
            shipping_address=estimate.billing_address,
            place_of_supply_state_code=estimate.place_of_supply_state_code,
            source_estimate_id=estimate.id,
            subtotal=estimate.subtotal,
            discount_total=estimate.discount_total,
            taxable_total=estimate.taxable_total,
            cgst_total=estimate.cgst_total,
            sgst_total=estimate.sgst_total,
            igst_total=estimate.igst_total,
            tax_total=estimate.tax_total,
            grand_total=estimate.grand_total,
            notes=estimate.notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(order)
        await self._session.flush()

        for index, (est_line, _uom) in enumerate(estimate_lines, start=1):
            order_line = SalesOrderLine(
                tenant_id=tenant_id,
                order_id=order.id,
                line_no=index,
                product_id=est_line.product_id,
                description=est_line.description,
                hsn_code=est_line.hsn_code,
                quantity=est_line.quantity,
                uom_id=est_line.uom_id,
                unit_price=est_line.unit_price,
                discount_amount=est_line.discount_amount,
                taxable_amount=est_line.taxable_amount,
                gst_rate=est_line.gst_rate,
                cgst_amount=est_line.cgst_amount,
                sgst_amount=est_line.sgst_amount,
                igst_amount=est_line.igst_amount,
                line_total=est_line.line_total,
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            self._session.add(order_line)
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="SALES_ORDER_CREATED_FROM_ESTIMATE",
            entity_type="sales_order",
            entity_id=order.id,
            after=self._snapshot(order),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(order.id)
        return order, customer.name, lines_with_uom, estimate
