"""Sales Estimate service (PROMPT-012).

The first concrete Sales document type built on PROMPT-011's foundation:
- GST amounts come from `gst_calculation_service` (never invented here).
- Customer/product validation comes from `sales_validation_service`.
- Document numbers come from `document_numbering_service`.
- Estimates NEVER touch inventory — no call to InventoryService anywhere
  in this file (§10 is absolute: no stock movement on create, edit, or
  conversion).

Server-side calculation is authoritative (§26): every financial value in
`SalesLineInput` the client submits (quantity, unit_price, discount) is
used as *input*, but gross/discount/taxable/GST/totals are always
recomputed here from that input plus the product's snapshotted GST rate —
never trusted as a pre-computed client value.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    EST_ALREADY_CONVERTED,
    EST_EXPIRED,
    EST_INVALID_STATUS,
    EST_NOT_FOUND,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.core.sales_constants import ESTIMATE
from app.models.customer import Customer
from app.models.sales_estimate import (
    ACCEPTED,
    CANCELLED,
    CONVERTED,
    CONVERTIBLE_STATUSES,
    DRAFT,
    EXPIRED,
    REJECTED,
    SENT,
    SalesEstimate,
)
from app.models.sales_estimate_line import SalesEstimateLine
from app.models.tenant import Tenant
from app.models.unit_of_measure import UnitOfMeasure
from app.schemas.sales_common import SalesLineInput
from app.services.audit.audit_service import AuditService
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.services.sales.gst_calculation_service import (
    calculate_document_totals,
    calculate_line,
    determine_gst_treatment,
)
from app.services.sales.sales_validation_service import (
    validate_customer_for_sale,
    validate_product_for_sale,
)

# §12: which prior status each action may be applied from. Anything not
# listed for an action (including all of TERMINAL_STATUSES) is rejected
# with EST_INVALID_STATUS. Documented here as the single source of the
# state machine rather than scattered checks (§12's own instruction).
_ACTION_ALLOWED_FROM = {
    "send": {DRAFT},
    "accept": {SENT},
    "reject": {SENT, ACCEPTED},
    "cancel": {DRAFT, SENT, ACCEPTED},
}


def apply_estimate_expiry_if_needed(estimate: SalesEstimate) -> bool:
    """§13 approach C: status is lazily transitioned to EXPIRED the next
    time the record is read or acted upon, rather than running a scheduled
    job this architecture doesn't otherwise need. Public/module-level (not
    a private method) so PROMPT-013's SalesOrderService can apply the same
    check when locking an Estimate for conversion, without duplicating the
    business rule."""
    if (
        estimate.valid_until_date is not None
        and estimate.valid_until_date < date.today()
        and estimate.status in (DRAFT, SENT, ACCEPTED)
    ):
        estimate.status = EXPIRED
        return True
    return False


@dataclass(frozen=True)
class EstimatePage:
    items: list[tuple[SalesEstimate, str]]  # (estimate, customer_name)
    total_items: int


class EstimateService:
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
            raise ValidationAppError("Select a valid unit.", code=EST_NOT_FOUND)
        return unit

    def _apply_expiry_if_needed(self, estimate: SalesEstimate) -> bool:
        return apply_estimate_expiry_if_needed(estimate)

    async def _get_estimate_locked(self, tenant_id: uuid.UUID, estimate_id: uuid.UUID) -> SalesEstimate:
        result = await self._session.execute(
            select(SalesEstimate)
            .where(SalesEstimate.id == estimate_id, SalesEstimate.tenant_id == tenant_id)
            .with_for_update()
        )
        estimate = result.scalar_one_or_none()
        if estimate is None:
            raise NotFoundError("Estimate not found", code=EST_NOT_FOUND)
        return estimate

    async def _get_lines(self, estimate_id: uuid.UUID) -> list[tuple[SalesEstimateLine, UnitOfMeasure]]:
        result = await self._session.execute(
            select(SalesEstimateLine, UnitOfMeasure)
            .join(UnitOfMeasure, UnitOfMeasure.id == SalesEstimateLine.uom_id)
            .where(SalesEstimateLine.estimate_id == estimate_id)
            .order_by(SalesEstimateLine.line_no)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def _build_lines(
        self,
        *,
        tenant_id: uuid.UUID,
        estimate_id: uuid.UUID,
        line_inputs: list[SalesLineInput],
        gst_treatment: str,
    ) -> tuple[list[SalesEstimateLine], Decimal, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
        """Validates every line's product/unit and returns the persisted
        line rows plus document-level totals — all recomputed server-side
        (§26), never trusting any client-submitted amount."""
        lines: list[SalesEstimateLine] = []
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
                SalesEstimateLine(
                    tenant_id=tenant_id,
                    estimate_id=estimate_id,
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

    def _snapshot(self, estimate: SalesEstimate) -> dict:
        return {
            "customer_id": str(estimate.customer_id),
            "document_date": estimate.document_date.isoformat(),
            "valid_until_date": estimate.valid_until_date.isoformat() if estimate.valid_until_date else None,
            "status": estimate.status,
            "grand_total": str(estimate.grand_total),
        }

    # --- queries ---------------------------------------------------------

    async def list_estimates(
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
    ) -> EstimatePage:
        base = (
            select(SalesEstimate, Customer.name)
            .join(Customer, Customer.id == SalesEstimate.customer_id)
            .where(SalesEstimate.tenant_id == tenant_id)
        )

        if search:
            like = f"%{search}%"
            base = base.where(or_(SalesEstimate.estimate_number.ilike(like), Customer.name.ilike(like), Customer.customer_code.ilike(like)))
        if status_filter:
            base = base.where(SalesEstimate.status == status_filter)
        if customer_id:
            base = base.where(SalesEstimate.customer_id == customer_id)
        if date_from:
            base = base.where(SalesEstimate.document_date >= date_from)
        if date_to:
            base = base.where(SalesEstimate.document_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(SalesEstimate.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(SalesEstimate.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        return EstimatePage(items=[(row[0], row[1]) for row in rows], total_items=total_items)

    async def get_estimate(
        self, *, tenant_id: uuid.UUID, estimate_id: uuid.UUID
    ) -> tuple[SalesEstimate, str, list[tuple[SalesEstimateLine, UnitOfMeasure]]]:
        result = await self._session.execute(
            select(SalesEstimate, Customer.name)
            .join(Customer, Customer.id == SalesEstimate.customer_id)
            .where(SalesEstimate.id == estimate_id, SalesEstimate.tenant_id == tenant_id)
        )
        row = result.first()
        if row is None:
            raise NotFoundError("Estimate not found", code=EST_NOT_FOUND)
        estimate, customer_name = row

        if self._apply_expiry_if_needed(estimate):
            await self._session.flush()

        lines = await self._get_lines(estimate.id)
        return estimate, customer_name, lines

    # --- create / update ---------------------------------------------------

    async def create_estimate(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        customer_id: uuid.UUID,
        document_date: date | None,
        valid_until_date: date | None,
        notes: str | None,
        line_inputs: list[SalesLineInput],
        ip_address: str | None,
    ) -> tuple[SalesEstimate, str, list[tuple[SalesEstimateLine, UnitOfMeasure]]]:
        tenant = await self._get_tenant(tenant_id)
        validated_customer = await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=customer_id)
        customer = validated_customer.customer

        gst_treatment = determine_gst_treatment(
            supplier_state_code=tenant.state_code, customer_state_code=customer.state_code
        )

        doc_date = document_date or date.today()

        numbering = DocumentNumberingService(self._session)
        estimate_number = await numbering.next_number(tenant=tenant, document_type=ESTIMATE, prefix="EST")

        estimate = SalesEstimate(
            tenant_id=tenant_id,
            estimate_number=estimate_number,
            customer_id=customer.id,
            document_date=doc_date,
            valid_until_date=valid_until_date,
            status=DRAFT,
            customer_gstin=customer.gstin,
            billing_address=customer.address,
            place_of_supply_state_code=customer.state_code,
            notes=notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        self._session.add(estimate)
        await self._session.flush()

        lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
            await self._build_lines(
                tenant_id=tenant_id, estimate_id=estimate.id, line_inputs=line_inputs, gst_treatment=gst_treatment
            )
        )
        for line in lines:
            line.created_by = actor_user_id
            line.updated_by = actor_user_id
            self._session.add(line)

        estimate.subtotal = subtotal
        estimate.discount_total = discount_total
        estimate.taxable_total = taxable_total
        estimate.cgst_total = cgst_total
        estimate.sgst_total = sgst_total
        estimate.igst_total = igst_total
        estimate.tax_total = cgst_total + sgst_total + igst_total
        estimate.grand_total = grand_total
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="ESTIMATE_CREATED",
            entity_type="sales_estimate",
            entity_id=estimate.id,
            after=self._snapshot(estimate),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(estimate.id)
        return estimate, customer.name, lines_with_uom

    async def update_estimate(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        estimate_id: uuid.UUID,
        expected_row_version: int,
        customer_id: uuid.UUID | None,
        document_date: date | None,
        valid_until_date: date | None,
        notes: str | None,
        line_inputs: list[SalesLineInput] | None,
        ip_address: str | None,
    ) -> tuple[SalesEstimate, str, list[tuple[SalesEstimateLine, UnitOfMeasure]]]:
        estimate = await self._get_estimate_locked(tenant_id, estimate_id)
        if self._apply_expiry_if_needed(estimate):
            await self._session.flush()
        check_row_version(estimate, expected_row_version)

        # §16: only DRAFT is editable.
        if estimate.status != DRAFT:
            raise ValidationAppError(
                "This estimate has already been sent and cannot be edited in this status.", code=EST_INVALID_STATUS
            )

        before = self._snapshot(estimate)
        tenant = await self._get_tenant(tenant_id)

        customer = None
        if customer_id is not None:
            validated_customer = await validate_customer_for_sale(self._session, tenant_id=tenant_id, customer_id=customer_id)
            customer = validated_customer.customer
            estimate.customer_id = customer.id
            estimate.customer_gstin = customer.gstin
            estimate.billing_address = customer.address
            estimate.place_of_supply_state_code = customer.state_code
        else:
            customer_result = await self._session.execute(select(Customer).where(Customer.id == estimate.customer_id))
            customer = customer_result.scalar_one()

        if document_date is not None:
            estimate.document_date = document_date
        if valid_until_date is not None:
            estimate.valid_until_date = valid_until_date
        if notes is not None:
            estimate.notes = notes

        if line_inputs is not None:
            gst_treatment = determine_gst_treatment(
                supplier_state_code=tenant.state_code, customer_state_code=customer.state_code
            )
            # Replace lines wholesale — simplest correct approach for a
            # DRAFT-only edit; posted/sent estimates never reach this path.
            existing_lines = await self._get_lines(estimate.id)
            for line, _ in existing_lines:
                await self._session.delete(line)
            await self._session.flush()

            lines, subtotal, discount_total, taxable_total, cgst_total, sgst_total, igst_total, grand_total = (
                await self._build_lines(
                    tenant_id=tenant_id, estimate_id=estimate.id, line_inputs=line_inputs, gst_treatment=gst_treatment
                )
            )
            for line in lines:
                line.created_by = actor_user_id
                line.updated_by = actor_user_id
                self._session.add(line)

            estimate.subtotal = subtotal
            estimate.discount_total = discount_total
            estimate.taxable_total = taxable_total
            estimate.cgst_total = cgst_total
            estimate.sgst_total = sgst_total
            estimate.igst_total = igst_total
            estimate.tax_total = cgst_total + sgst_total + igst_total
            estimate.grand_total = grand_total

        estimate.updated_by = actor_user_id
        estimate.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="ESTIMATE_UPDATED",
            entity_type="sales_estimate",
            entity_id=estimate.id,
            before=before,
            after=self._snapshot(estimate),
            ip_address=ip_address,
        )

        lines_with_uom = await self._get_lines(estimate.id)
        return estimate, customer.name, lines_with_uom

    # --- status transitions ------------------------------------------------

    async def _transition(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        estimate_id: uuid.UUID,
        expected_row_version: int,
        action: str,
        new_status: str,
        audit_action: str,
        ip_address: str | None,
    ) -> SalesEstimate:
        estimate = await self._get_estimate_locked(tenant_id, estimate_id)
        if self._apply_expiry_if_needed(estimate):
            await self._session.flush()
        check_row_version(estimate, expected_row_version)

        if estimate.status == EXPIRED:
            raise ValidationAppError("This estimate has expired and can no longer be actioned.", code=EST_EXPIRED)

        allowed_from = _ACTION_ALLOWED_FROM[action]
        if estimate.status not in allowed_from:
            raise ValidationAppError(
                f"Cannot {action} an estimate in {estimate.status} status.", code=EST_INVALID_STATUS
            )

        previous_status = estimate.status
        estimate.status = new_status
        estimate.updated_by = actor_user_id
        estimate.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=audit_action,
            entity_type="sales_estimate",
            entity_id=estimate.id,
            before={"status": previous_status},
            after={"status": new_status},
            ip_address=ip_address,
        )
        return estimate

    async def send_estimate(self, **kwargs) -> SalesEstimate:
        return await self._transition(action="send", new_status=SENT, audit_action="ESTIMATE_SENT", **kwargs)

    async def accept_estimate(self, **kwargs) -> SalesEstimate:
        return await self._transition(action="accept", new_status=ACCEPTED, audit_action="ESTIMATE_ACCEPTED", **kwargs)

    async def reject_estimate(self, **kwargs) -> SalesEstimate:
        return await self._transition(action="reject", new_status=REJECTED, audit_action="ESTIMATE_REJECTED", **kwargs)

    async def cancel_estimate(self, **kwargs) -> SalesEstimate:
        return await self._transition(action="cancel", new_status=CANCELLED, audit_action="ESTIMATE_CANCELLED", **kwargs)

    async def get_lines(self, estimate_id: uuid.UUID) -> list[tuple[SalesEstimateLine, UnitOfMeasure]]:
        """Public entrypoint for PROMPT-013's SalesOrderService to read an
        estimate's frozen lines when building a Sales Order from them."""
        return await self._get_lines(estimate_id)

    # --- conversion boundary (§21 PROMPT-012 / §15-18 PROMPT-013) -----------

    async def convert_to_sales_order(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        estimate_id: uuid.UUID,
        expected_row_version: int,
        ip_address: str | None,
    ) -> SalesEstimate:
        """Validates conversion eligibility and atomically marks the
        estimate CONVERTED with a `converted_at` timestamp. This is the
        Estimate-side half of PROMPT-013's conversion flow — locking here
        (SELECT ... FOR UPDATE) is what makes concurrent conversion
        attempts serialize instead of racing (§18). The caller
        (`SalesOrderService.create_from_estimate`) is responsible for
        actually building the Sales Order row/lines in the same
        transaction/session, and for re-validating that the customer and
        products are still usable (§15 steps 5-6) — this method only
        answers "is this estimate itself eligible to be converted right
        now." No inventory effect either way (§10 PROMPT-013 is absolute).
        """
        estimate = await self._get_estimate_locked(tenant_id, estimate_id)
        if self._apply_expiry_if_needed(estimate):
            await self._session.flush()
        check_row_version(estimate, expected_row_version)

        if estimate.status == CONVERTED:
            # 409 Conflict — matches the established "duplicate/already-done
            # state" pattern (CUST-002/SUPP-002/PROD-002/INV-004), not a 422
            # validation error.
            raise ConflictError("This estimate has already been converted.", code=EST_ALREADY_CONVERTED)
        if estimate.status == EXPIRED:
            raise ValidationAppError("This estimate has expired and cannot be converted.", code=EST_EXPIRED)
        if estimate.status not in CONVERTIBLE_STATUSES:
            raise ValidationAppError(
                f"An estimate in {estimate.status} status cannot be converted.", code=EST_INVALID_STATUS
            )

        previous_status = estimate.status
        estimate.status = CONVERTED
        estimate.converted_at = datetime.now(timezone.utc)
        estimate.updated_by = actor_user_id
        estimate.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action="ESTIMATE_CONVERTED",
            entity_type="sales_estimate",
            entity_id=estimate.id,
            before={"status": previous_status},
            after={"status": CONVERTED, "converted_at": estimate.converted_at.isoformat()},
            ip_address=ip_address,
        )
        return estimate
