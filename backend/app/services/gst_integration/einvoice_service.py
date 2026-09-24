"""E-Invoice orchestration service (PROMPT-018).

The application-facing entry point for E-Invoice generation/status/
cancellation — `app/api/v1/einvoice.py` calls this, never the provider
directly. §10's canonical flow is implemented verbatim: validate ->
evaluate applicability -> build payload -> generate idempotency key ->
submit -> process response -> persist -> update status -> audit.

§11/§38 (idempotency/concurrency) — the core guarantee: `generate()` locks
the `einvoice` row (`SELECT ... FOR UPDATE`, the exact same pattern every
prior Sales document's confirm/post action uses) before inspecting or
changing its status. Two concurrent requests for the SAME invoice
serialize on that lock; the second one sees the first's terminal state
(GENERATED/FAILED) or in-flight state (PROCESSING, rejected with
EINV_CONCURRENT_OPERATION) once it acquires the lock — it can never
observe the pre-lock READY state and proceed to also call the provider.

§24 (unknown-result handling) — the single most safety-critical piece:
if the row's status is STATUS_UNKNOWN (a previous attempt's provider
response was never received), `generate()` does NOT immediately submit a
new request. It first calls `get_irn_status` to reconcile; only if that
confirms "not processed" does it proceed, and it REUSES the prior
attempt's idempotency key rather than minting a new one (§23's explicit
"retries must use the same logical integration operation/idempotency
identity").
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import (
    EINV_ALREADY_GENERATED,
    EINV_AUTH_FAILED,
    EINV_CONCURRENT_OPERATION,
    EINV_INVALID_STATUS,
    EINV_INVOICE_NOT_FOUND,
    EINV_NOT_APPLICABLE,
    EINV_NOT_ELIGIBLE_FOR_CANCEL,
    EINV_NOT_FOUND,
    EINV_PROVIDER_UNAVAILABLE,
    EINV_RATE_LIMITED,
    EINV_STATUS_UNKNOWN,
    EINV_TIMEOUT,
    EINV_VALIDATION_FAILED,
)
from app.core.exceptions import ConflictError, ExternalServiceError, NotFoundError, ValidationAppError
from app.models.einvoice import (
    CANCEL_REQUESTED,
    CANCELLABLE_STATUSES,
    CANCELLED,
    FAILED,
    GENERATED,
    LOCKED_STATUSES,
    NOT_APPLICABLE,
    PROCESSING,
    READY,
    STATUS_UNKNOWN,
    Einvoice,
)
from app.models.integration_configuration import IntegrationConfiguration
from app.models.integration_operation import EINVOICE
from app.models.integration_operation import GENERATE as OP_GENERATE
from app.models.integration_operation import CANCEL as OP_CANCEL
from app.models.integration_operation import STATUS_CHECK as OP_STATUS_CHECK
from app.models.integration_operation import FAILED as OP_FAILED
from app.models.integration_operation import SUCCEEDED as OP_SUCCEEDED
from app.models.integration_operation import UNKNOWN as OP_UNKNOWN
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.tenant import Tenant
from app.services.audit.audit_service import AuditService
from app.services.gst_integration.applicability_service import evaluate_einvoice_applicability
from app.services.gst_integration.integration_operation_service import IntegrationOperationService
from app.services.gst_integration.provider import (
    AUTH_FAILED,
    RATE_LIMITED,
    TIMEOUT,
    UNAVAILABLE,
    ProviderResult,
    get_einvoice_provider,
    new_idempotency_key,
)
from app.services.gst_integration.validation_service import validate_einvoice_data

_OUTCOME_TO_ERROR_CODE = {
    AUTH_FAILED: EINV_AUTH_FAILED,
    TIMEOUT: EINV_TIMEOUT,
    UNAVAILABLE: EINV_PROVIDER_UNAVAILABLE,
    RATE_LIMITED: EINV_RATE_LIMITED,
}

_OUTCOME_TO_MESSAGE = {
    AUTH_FAILED: "E-Invoice authentication with the integration provider failed. Please check the integration "
    "configuration and try again.",
    TIMEOUT: "The E-Invoice request timed out. The invoice was NOT confirmed as generated — status will be "
    "reconciled before any retry.",
    UNAVAILABLE: "E-Invoice service is temporarily unavailable. The invoice was not marked as successfully "
    "generated. Please retry shortly.",
    RATE_LIMITED: "The E-Invoice provider is rate-limiting requests. Please retry after a short delay.",
}


class EInvoiceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared helpers -----------------------------------------------

    async def _get_invoice(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> SalesInvoice:
        result = await self._session.execute(
            select(SalesInvoice).where(SalesInvoice.id == invoice_id, SalesInvoice.tenant_id == tenant_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Sales invoice not found", code=EINV_INVOICE_NOT_FOUND)
        return invoice

    async def _get_lines(self, invoice_id: uuid.UUID) -> list[SalesInvoiceLine]:
        result = await self._session.execute(
            select(SalesInvoiceLine).where(SalesInvoiceLine.invoice_id == invoice_id).order_by(SalesInvoiceLine.line_no)
        )
        return list(result.scalars().all())

    async def _get_config(self, tenant_id: uuid.UUID) -> IntegrationConfiguration:
        """Lazily provisions a default SANDBOX configuration (E-Invoice/
        E-Way Bill both enabled) the first time a tenant's invoice is
        evaluated — mirrors `InventoryService.ensure_default_location()`'s
        identical "no setup screen exists, so get-or-create" pattern. No
        configuration-management API/UI is in this prompt's scope (§27's
        suggested endpoint list has none) — an operator adjusts these
        columns directly until a future prompt builds one."""
        result = await self._session.execute(
            select(IntegrationConfiguration).where(IntegrationConfiguration.tenant_id == tenant_id)
        )
        config = result.scalar_one_or_none()
        if config is None:
            config = IntegrationConfiguration(tenant_id=tenant_id)
            try:
                async with self._session.begin_nested():
                    self._session.add(config)
                    await self._session.flush()
            except IntegrityError:
                result = await self._session.execute(
                    select(IntegrationConfiguration).where(IntegrationConfiguration.tenant_id == tenant_id)
                )
                config = result.scalar_one()
        return config

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _get_or_create_locked(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID, actor_user_id: uuid.UUID) -> Einvoice:
        result = await self._session.execute(
            select(Einvoice)
            .where(Einvoice.tenant_id == tenant_id, Einvoice.sales_invoice_id == invoice_id)
            .with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is not None:
            return record

        record = Einvoice(
            tenant_id=tenant_id,
            sales_invoice_id=invoice_id,
            status=READY,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            # Concurrent creator won the race on the unique constraint —
            # re-fetch and lock theirs instead.
            result = await self._session.execute(
                select(Einvoice)
                .where(Einvoice.tenant_id == tenant_id, Einvoice.sales_invoice_id == invoice_id)
                .with_for_update()
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise
        return record

    def _build_payload(self, *, tenant: Tenant, invoice: SalesInvoice, lines: list[SalesInvoiceLine]) -> dict:
        """§10: a canonical, provider-agnostic internal request model —
        deliberately NOT shaped like any specific provider's schema field
        names, so a real adapter translates FROM this shape rather than
        the rest of the application depending on one provider's naming."""
        return {
            "seller_gstin": tenant.gstin,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date.isoformat(),
            "place_of_supply_state_code": invoice.place_of_supply_state_code,
            "customer_gstin": invoice.customer_gstin,
            "customer_type": invoice.customer_type,
            "billing_address": invoice.billing_address,
            "taxable_total": str(invoice.taxable_total),
            "cgst_total": str(invoice.cgst_total),
            "sgst_total": str(invoice.sgst_total),
            "igst_total": str(invoice.igst_total),
            "grand_total": str(invoice.grand_total),
            "lines": [
                {
                    "hsn_code": line.hsn_code,
                    "quantity": str(line.quantity),
                    "unit_price": str(line.unit_price),
                    "taxable_amount": str(line.taxable_amount),
                    "gst_rate": str(line.gst_rate),
                }
                for line in lines
            ],
        }

    def _sync_invoice_snapshot(self, invoice: SalesInvoice, record: Einvoice) -> None:
        """Keeps `sales_invoice`'s own reserved denormalized columns
        (migration 0017) in sync with the authoritative `einvoice` row —
        see `einvoice.py`'s model docstring."""
        invoice.irn = record.irn
        invoice.ack_number = record.ack_number
        invoice.ack_date = record.ack_date
        invoice.einvoice_status = record.status
        invoice.qr_code_data = record.signed_qr_data

    async def _apply_provider_result(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        invoice: SalesInvoice,
        record: Einvoice,
        operation_service: IntegrationOperationService,
        operation,
        result: ProviderResult,
        operation_type: str,
        ip_address: str | None,
    ) -> None:
        if result.is_success:
            if operation_type == OP_GENERATE:
                record.status = GENERATED
                record.irn = result.irn
                record.ack_number = result.ack_number
                record.ack_date = result.ack_date
                record.signed_invoice_data = result.signed_invoice_data
                record.signed_qr_data = result.signed_qr_data
                record.generated_at = datetime.now(timezone.utc)
            elif operation_type == OP_CANCEL:
                record.status = CANCELLED
                record.cancelled_at = datetime.now(timezone.utc)
            record.provider_reference = result.provider_reference or record.provider_reference
            record.provider_response_code = result.response_code
            record.provider_response_message = result.response_message
            await operation_service.mark_result(
                operation=operation, status=OP_SUCCEEDED, provider_reference=result.provider_reference,
                response_code=result.response_code, error_code=None, error_message=None,
            )
            audit_action = "EINVOICE_GENERATED" if operation_type == OP_GENERATE else "EINVOICE_CANCELLED"
        elif result.is_unknown:
            record.status = STATUS_UNKNOWN
            record.provider_response_message = result.response_message
            await operation_service.mark_result(
                operation=operation, status=OP_UNKNOWN, provider_reference=result.provider_reference,
                response_code=result.response_code, error_code=EINV_TIMEOUT, error_message=result.response_message,
            )
            audit_action = "EINVOICE_GENERATION_FAILED" if operation_type == OP_GENERATE else "EINVOICE_CANCELLATION_FAILED"
        else:
            record.status = FAILED if operation_type == OP_GENERATE else GENERATED  # cancel-fail reverts to GENERATED
            record.provider_response_code = result.response_code
            record.provider_response_message = result.response_message
            error_code = _OUTCOME_TO_ERROR_CODE.get(result.outcome, EINV_VALIDATION_FAILED)
            await operation_service.mark_result(
                operation=operation, status=OP_FAILED, provider_reference=result.provider_reference,
                response_code=result.response_code, error_code=error_code, error_message=result.response_message,
            )
            audit_action = "EINVOICE_GENERATION_FAILED" if operation_type == OP_GENERATE else "EINVOICE_CANCELLATION_FAILED"

        record.last_operation_id = operation.id
        record.updated_by = actor_user_id
        record.row_version += 1
        self._sync_invoice_snapshot(invoice, record)
        invoice.updated_by = actor_user_id
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=audit_action,
            entity_type="einvoice",
            entity_id=record.id,
            after={"status": record.status, "irn": record.irn, "outcome": result.outcome},
            ip_address=ip_address,
        )

    # --- queries ---------------------------------------------------------

    async def get_status(self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> tuple[SalesInvoice, Einvoice | None]:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        result = await self._session.execute(
            select(Einvoice).where(Einvoice.tenant_id == tenant_id, Einvoice.sales_invoice_id == invoice_id)
        )
        return invoice, result.scalar_one_or_none()

    # --- generate (§10/§12/§24) ----------------------------------------

    async def generate(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID, ip_address: str | None
    ) -> Einvoice:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        tenant = await self._get_tenant(tenant_id)
        config = await self._get_config(tenant_id)
        record = await self._get_or_create_locked(tenant_id, invoice_id, actor_user_id)

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="EINVOICE_GENERATION_REQUESTED",
            entity_type="einvoice", entity_id=record.id, ip_address=ip_address,
        )

        if record.status == GENERATED:
            raise ValidationAppError("An e-invoice (IRN) has already been generated for this invoice.", code=EINV_ALREADY_GENERATED)
        if record.status == CANCELLED:
            raise ValidationAppError(
                "This invoice's e-invoice was cancelled and cannot be regenerated — use a new invoice.",
                code=EINV_INVALID_STATUS,
            )
        if record.status in LOCKED_STATUSES:
            raise ConflictError(
                "An E-Invoice operation is already in progress for this invoice.", code=EINV_CONCURRENT_OPERATION
            )

        applicability = evaluate_einvoice_applicability(invoice, config)
        record.applicability_result = applicability.to_json()
        if not applicability.applicable:
            record.status = NOT_APPLICABLE
            record.updated_by = actor_user_id
            record.row_version += 1
            self._sync_invoice_snapshot(invoice, record)
            await self._session.flush()
            raise ValidationAppError(applicability.reason, code=EINV_NOT_APPLICABLE)

        lines = await self._get_lines(invoice.id)
        validation_errors = validate_einvoice_data(tenant=tenant, invoice=invoice, lines=lines)
        if validation_errors:
            record.status = FAILED
            record.provider_response_message = "; ".join(validation_errors)
            record.updated_by = actor_user_id
            record.row_version += 1
            self._sync_invoice_snapshot(invoice, record)
            await self._session.flush()
            raise ValidationAppError(validation_errors[0], details=[{"message": m} for m in validation_errors], code=EINV_VALIDATION_FAILED)

        operation_service = IntegrationOperationService(self._session)
        provider = get_einvoice_provider(is_production=False)

        # §24: STATUS_UNKNOWN means a prior attempt's response was lost —
        # reconcile before ever submitting a fresh request, and reuse
        # that attempt's idempotency key rather than minting a new one.
        idempotency_key = new_idempotency_key()
        if record.status == STATUS_UNKNOWN:
            prior_ops = await operation_service.list_for_entity(
                tenant_id=tenant_id, entity_type=EINVOICE, entity_id=record.id
            )
            prior_unknown = next((op for op in prior_ops if op.operation_type == OP_GENERATE and op.status == OP_UNKNOWN), None)
            reconcile_result = await provider.get_irn_status(
                irn=record.irn, provider_reference=(prior_unknown.provider_reference if prior_unknown else None)
            )
            if reconcile_result.is_success and reconcile_result.irn:
                # Confirmed: the provider DID process the earlier request.
                record.irn = reconcile_result.irn
                record.status = GENERATED
                record.generated_at = datetime.now(timezone.utc)
                record.provider_reference = reconcile_result.provider_reference or record.provider_reference
                record.updated_by = actor_user_id
                record.row_version += 1
                self._sync_invoice_snapshot(invoice, record)
                await self._session.flush()
                await AuditService(self._session).record(
                    tenant_id=tenant_id, actor_user_id=actor_user_id, action="EINVOICE_STATUS_RECONCILED",
                    entity_type="einvoice", entity_id=record.id, after={"status": GENERATED, "irn": record.irn},
                    ip_address=ip_address,
                )
                return record
            if reconcile_result.is_unknown:
                raise ExternalServiceError(
                    "E-Invoice status is still unknown after checking with the provider. This requires manual "
                    "review before retrying — please check status again shortly or contact support.",
                    code=EINV_STATUS_UNKNOWN,
                )
            # Confirmed NOT processed — safe to retry, reusing the SAME
            # idempotency key as the lost attempt (§23).
            if prior_unknown and prior_unknown.idempotency_key:
                idempotency_key = prior_unknown.idempotency_key

        record.status = PROCESSING
        record.updated_by = actor_user_id
        await self._session.flush()

        operation = await operation_service.create(
            tenant_id=tenant_id, actor_user_id=actor_user_id, entity_type=EINVOICE, entity_id=record.id,
            operation_type=OP_GENERATE, idempotency_key=idempotency_key, provider=type(provider).__name__,
        )

        payload = self._build_payload(tenant=tenant, invoice=invoice, lines=lines)
        try:
            await provider.authenticate()
            result = await provider.generate_irn(idempotency_key=idempotency_key, payload=payload)
        except Exception as exc:  # noqa: BLE001 — provider call boundary, normalized below
            result = ProviderResult(outcome=UNAVAILABLE, response_message=str(exc))

        await self._apply_provider_result(
            tenant_id=tenant_id, actor_user_id=actor_user_id, invoice=invoice, record=record,
            operation_service=operation_service, operation=operation, result=result, operation_type=OP_GENERATE,
            ip_address=ip_address,
        )

        if not result.is_success:
            message = _OUTCOME_TO_MESSAGE.get(result.outcome, result.response_message or "E-Invoice generation failed.")
            code = _OUTCOME_TO_ERROR_CODE.get(result.outcome, EINV_VALIDATION_FAILED)
            if result.outcome in (UNAVAILABLE, RATE_LIMITED, TIMEOUT, AUTH_FAILED):
                raise ExternalServiceError(message, code=code)
            raise ValidationAppError(message, code=code)

        return record

    # --- refresh status (§18/§39 reconciliation) ----------------------

    async def refresh_status(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID, ip_address: str | None
    ) -> Einvoice:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        result = await self._session.execute(
            select(Einvoice).where(Einvoice.tenant_id == tenant_id, Einvoice.sales_invoice_id == invoice_id).with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError("No e-invoice record exists for this invoice yet.", code=EINV_NOT_FOUND)

        provider = get_einvoice_provider(is_production=False)
        provider_result = await provider.get_irn_status(irn=record.irn, provider_reference=record.provider_reference)

        operation_service = IntegrationOperationService(self._session)
        operation = await operation_service.create(
            tenant_id=tenant_id, actor_user_id=actor_user_id, entity_type=EINVOICE, entity_id=record.id,
            operation_type=OP_STATUS_CHECK, idempotency_key=None, provider=type(provider).__name__,
        )

        if provider_result.is_success and provider_result.irn:
            record.status = GENERATED
        elif provider_result.is_unknown:
            record.status = STATUS_UNKNOWN
        # else: leave status as-is (e.g. a NOT_FOUND reconciliation of an
        # already-FAILED record isn't itself a new failure).

        await operation_service.mark_result(
            operation=operation,
            status=OP_SUCCEEDED if provider_result.is_success else (OP_UNKNOWN if provider_result.is_unknown else OP_FAILED),
            provider_reference=provider_result.provider_reference, response_code=provider_result.response_code,
            error_code=None, error_message=provider_result.response_message,
        )
        record.updated_by = actor_user_id
        record.row_version += 1
        self._sync_invoice_snapshot(invoice, record)
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="EINVOICE_STATUS_RECONCILED",
            entity_type="einvoice", entity_id=record.id, after={"status": record.status}, ip_address=ip_address,
        )
        return record

    # --- cancel (§16) ----------------------------------------------------

    async def cancel(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID, reason: str, ip_address: str | None
    ) -> Einvoice:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        result = await self._session.execute(
            select(Einvoice).where(Einvoice.tenant_id == tenant_id, Einvoice.sales_invoice_id == invoice_id).with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError("No e-invoice record exists for this invoice yet.", code=EINV_NOT_FOUND)

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="EINVOICE_CANCELLATION_REQUESTED",
            entity_type="einvoice", entity_id=record.id, ip_address=ip_address,
        )

        if record.status in LOCKED_STATUSES:
            raise ConflictError("An E-Invoice operation is already in progress for this invoice.", code=EINV_CONCURRENT_OPERATION)
        if record.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(
                f"An e-invoice in {record.status} status cannot be cancelled.", code=EINV_NOT_ELIGIBLE_FOR_CANCEL
            )

        record.status = CANCEL_REQUESTED
        record.cancellation_reason = reason
        await self._session.flush()

        operation_service = IntegrationOperationService(self._session)
        provider = get_einvoice_provider(is_production=False)
        idempotency_key = new_idempotency_key()
        operation = await operation_service.create(
            tenant_id=tenant_id, actor_user_id=actor_user_id, entity_type=EINVOICE, entity_id=record.id,
            operation_type=OP_CANCEL, idempotency_key=idempotency_key, provider=type(provider).__name__,
        )

        try:
            provider_result = await provider.cancel_irn(irn=record.irn, reason=reason)
        except Exception as exc:  # noqa: BLE001
            provider_result = ProviderResult(outcome=UNAVAILABLE, response_message=str(exc))

        await self._apply_provider_result(
            tenant_id=tenant_id, actor_user_id=actor_user_id, invoice=invoice, record=record,
            operation_service=operation_service, operation=operation, result=provider_result, operation_type=OP_CANCEL,
            ip_address=ip_address,
        )

        if not provider_result.is_success:
            message = _OUTCOME_TO_MESSAGE.get(provider_result.outcome, provider_result.response_message or "E-Invoice cancellation failed.")
            code = _OUTCOME_TO_ERROR_CODE.get(provider_result.outcome, EINV_VALIDATION_FAILED)
            raise ExternalServiceError(message, code=code)

        return record
