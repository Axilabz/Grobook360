"""E-Way Bill orchestration service (PROMPT-018).

Mirrors `einvoice_service.py`'s structure and safety guarantees exactly
(idempotency/concurrency via row-lock, §24 unknown-result reconciliation
reusing the prior idempotency key, atomic provider-result application) —
see that module's docstring for the full rationale, not repeated here.

The one structural difference: E-Way Bill generation accepts caller-
supplied transport details (§19 — vehicle/transporter/mode), which are
NOT derived from the Sales Invoice itself (a Sales Invoice has no
transport fields) and are validated before submission.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.error_codes import (
    EWB_ALREADY_GENERATED,
    EWB_AUTH_FAILED,
    EWB_CONCURRENT_OPERATION,
    EWB_INVALID_STATUS,
    EWB_INVOICE_NOT_FOUND,
    EWB_NOT_APPLICABLE,
    EWB_NOT_ELIGIBLE_FOR_CANCEL,
    EWB_NOT_FOUND,
    EWB_PROVIDER_UNAVAILABLE,
    EWB_RATE_LIMITED,
    EWB_STATUS_UNKNOWN,
    EWB_TIMEOUT,
    EWB_VALIDATION_FAILED,
)
from app.core.exceptions import ConflictError, ExternalServiceError, NotFoundError, ValidationAppError
from app.models.eway_bill import (
    CANCEL_REQUESTED,
    CANCELLABLE_STATUSES,
    CANCELLED,
    EwayBill,
    FAILED,
    GENERATED,
    LOCKED_STATUSES,
    NOT_APPLICABLE,
    PROCESSING,
    READY,
    STATUS_UNKNOWN,
)
from app.models.integration_configuration import IntegrationConfiguration
from app.models.integration_operation import CANCEL as OP_CANCEL
from app.models.integration_operation import EWAY_BILL
from app.models.integration_operation import FAILED as OP_FAILED
from app.models.integration_operation import GENERATE as OP_GENERATE
from app.models.integration_operation import STATUS_CHECK as OP_STATUS_CHECK
from app.models.integration_operation import SUCCEEDED as OP_SUCCEEDED
from app.models.integration_operation import UNKNOWN as OP_UNKNOWN
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.tenant import Tenant
from app.services.audit.audit_service import AuditService
from app.services.gst_integration.applicability_service import evaluate_eway_bill_applicability
from app.services.gst_integration.integration_operation_service import IntegrationOperationService
from app.services.gst_integration.provider import (
    AUTH_FAILED,
    RATE_LIMITED,
    TIMEOUT,
    UNAVAILABLE,
    ProviderResult,
    get_eway_bill_provider,
    new_idempotency_key,
)
from app.services.gst_integration.validation_service import validate_eway_bill_data

_OUTCOME_TO_ERROR_CODE = {
    AUTH_FAILED: EWB_AUTH_FAILED,
    TIMEOUT: EWB_TIMEOUT,
    UNAVAILABLE: EWB_PROVIDER_UNAVAILABLE,
    RATE_LIMITED: EWB_RATE_LIMITED,
}

_OUTCOME_TO_MESSAGE = {
    AUTH_FAILED: "E-Way Bill authentication with the integration provider failed. Please check the integration "
    "configuration and try again.",
    TIMEOUT: "The E-Way Bill request timed out. It was NOT confirmed as generated — status will be reconciled "
    "before any retry.",
    UNAVAILABLE: "E-Way Bill service is temporarily unavailable. Please retry shortly.",
    RATE_LIMITED: "The E-Way Bill provider is rate-limiting requests. Please retry after a short delay.",
}


class EWayBillService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared helpers -----------------------------------------------

    async def _get_invoice(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> SalesInvoice:
        result = await self._session.execute(
            select(SalesInvoice).where(SalesInvoice.id == invoice_id, SalesInvoice.tenant_id == tenant_id)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Sales invoice not found", code=EWB_INVOICE_NOT_FOUND)
        return invoice

    async def _get_lines(self, invoice_id: uuid.UUID) -> list[SalesInvoiceLine]:
        result = await self._session.execute(
            select(SalesInvoiceLine).where(SalesInvoiceLine.invoice_id == invoice_id).order_by(SalesInvoiceLine.line_no)
        )
        return list(result.scalars().all())

    async def _get_config(self, tenant_id: uuid.UUID) -> IntegrationConfiguration:
        """Lazily provisions a default SANDBOX configuration — see
        `EInvoiceService._get_config`'s identical rationale."""
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

    async def _get_by_invoice(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> EwayBill | None:
        result = await self._session.execute(
            select(EwayBill).where(EwayBill.tenant_id == tenant_id, EwayBill.sales_invoice_id == invoice_id)
        )
        return result.scalar_one_or_none()

    async def _get_locked(self, tenant_id: uuid.UUID, eway_bill_id: uuid.UUID) -> EwayBill:
        result = await self._session.execute(
            select(EwayBill).where(EwayBill.id == eway_bill_id, EwayBill.tenant_id == tenant_id).with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError("E-way bill not found", code=EWB_NOT_FOUND)
        return record

    async def _get_or_create_locked(self, tenant_id: uuid.UUID, invoice_id: uuid.UUID, actor_user_id: uuid.UUID) -> EwayBill:
        result = await self._session.execute(
            select(EwayBill).where(EwayBill.tenant_id == tenant_id, EwayBill.sales_invoice_id == invoice_id).with_for_update()
        )
        record = result.scalar_one_or_none()
        if record is not None:
            return record

        record = EwayBill(
            tenant_id=tenant_id, sales_invoice_id=invoice_id, status=READY,
            created_by=actor_user_id, updated_by=actor_user_id,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            result = await self._session.execute(
                select(EwayBill).where(EwayBill.tenant_id == tenant_id, EwayBill.sales_invoice_id == invoice_id).with_for_update()
            )
            record = result.scalar_one_or_none()
            if record is None:
                raise
        return record

    def _build_payload(
        self, *, tenant: Tenant, invoice: SalesInvoice, lines: list[SalesInvoiceLine],
        transport_mode: str | None, vehicle_number: str | None, transporter_id: str | None,
        transporter_name: str | None, distance_km: Decimal | None,
    ) -> dict:
        return {
            "seller_gstin": tenant.gstin,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date.isoformat(),
            "place_of_supply_state_code": invoice.place_of_supply_state_code,
            "grand_total": str(invoice.grand_total),
            "transport_mode": transport_mode,
            "vehicle_number": vehicle_number,
            "transporter_id": transporter_id,
            "transporter_name": transporter_name,
            "distance_km": str(distance_km) if distance_km is not None else None,
            "lines": [{"hsn_code": line.hsn_code, "quantity": str(line.quantity)} for line in lines],
        }

    async def _apply_provider_result(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, record: EwayBill,
        operation_service: IntegrationOperationService, operation, result: ProviderResult, operation_type: str,
        ip_address: str | None,
    ) -> None:
        if result.is_success:
            if operation_type == OP_GENERATE:
                record.status = GENERATED
                record.eway_bill_number = result.eway_bill_number
                record.valid_from = result.valid_from
                record.valid_until = result.valid_until
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
            audit_action = "EWAY_BILL_GENERATED" if operation_type == OP_GENERATE else "EWAY_BILL_CANCELLED"
        elif result.is_unknown:
            record.status = STATUS_UNKNOWN
            record.provider_response_message = result.response_message
            await operation_service.mark_result(
                operation=operation, status=OP_UNKNOWN, provider_reference=result.provider_reference,
                response_code=result.response_code, error_code=EWB_TIMEOUT, error_message=result.response_message,
            )
            audit_action = "EWAY_BILL_GENERATION_FAILED" if operation_type == OP_GENERATE else "EWAY_BILL_CANCELLATION_FAILED"
        else:
            record.status = FAILED if operation_type == OP_GENERATE else GENERATED
            record.provider_response_code = result.response_code
            record.provider_response_message = result.response_message
            error_code = _OUTCOME_TO_ERROR_CODE.get(result.outcome, EWB_VALIDATION_FAILED)
            await operation_service.mark_result(
                operation=operation, status=OP_FAILED, provider_reference=result.provider_reference,
                response_code=result.response_code, error_code=error_code, error_message=result.response_message,
            )
            audit_action = "EWAY_BILL_GENERATION_FAILED" if operation_type == OP_GENERATE else "EWAY_BILL_CANCELLATION_FAILED"

        record.last_operation_id = operation.id
        record.updated_by = actor_user_id
        record.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action=audit_action, entity_type="eway_bill",
            entity_id=record.id, after={"status": record.status, "eway_bill_number": record.eway_bill_number, "outcome": result.outcome},
            ip_address=ip_address,
        )

    # --- queries ---------------------------------------------------------

    async def get_status_by_invoice(self, *, tenant_id: uuid.UUID, invoice_id: uuid.UUID) -> tuple[SalesInvoice, EwayBill | None]:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        record = await self._get_by_invoice(tenant_id, invoice_id)
        return invoice, record

    async def get(self, *, tenant_id: uuid.UUID, eway_bill_id: uuid.UUID) -> EwayBill:
        result = await self._session.execute(
            select(EwayBill).where(EwayBill.id == eway_bill_id, EwayBill.tenant_id == tenant_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFoundError("E-way bill not found", code=EWB_NOT_FOUND)
        return record

    # --- generate (§20/§24) ----------------------------------------------

    async def generate(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID,
        transport_mode: str | None, vehicle_number: str | None, transporter_id: str | None,
        transporter_name: str | None, distance_km: Decimal | None, ip_address: str | None,
    ) -> EwayBill:
        invoice = await self._get_invoice(tenant_id, invoice_id)
        tenant = await self._get_tenant(tenant_id)
        config = await self._get_config(tenant_id)
        record = await self._get_or_create_locked(tenant_id, invoice_id, actor_user_id)

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="EWAY_BILL_GENERATION_REQUESTED",
            entity_type="eway_bill", entity_id=record.id, ip_address=ip_address,
        )

        if record.status == GENERATED:
            raise ValidationAppError("An e-way bill has already been generated for this invoice.", code=EWB_ALREADY_GENERATED)
        if record.status == CANCELLED:
            raise ValidationAppError("This invoice's e-way bill was cancelled and cannot be regenerated.", code=EWB_INVALID_STATUS)
        if record.status in LOCKED_STATUSES:
            raise ConflictError("An E-Way Bill operation is already in progress for this invoice.", code=EWB_CONCURRENT_OPERATION)

        applicability = evaluate_eway_bill_applicability(invoice, config)
        record.applicability_result = applicability.to_json()
        if not applicability.applicable:
            record.status = NOT_APPLICABLE
            record.updated_by = actor_user_id
            record.row_version += 1
            await self._session.flush()
            raise ValidationAppError(applicability.reason, code=EWB_NOT_APPLICABLE)

        lines = await self._get_lines(invoice.id)
        validation_errors = validate_eway_bill_data(
            tenant=tenant, invoice=invoice, lines=lines, transport_mode=transport_mode,
            vehicle_number=vehicle_number, transporter_id=transporter_id,
        )
        if validation_errors:
            record.status = FAILED
            record.provider_response_message = "; ".join(validation_errors)
            record.updated_by = actor_user_id
            record.row_version += 1
            await self._session.flush()
            raise ValidationAppError(validation_errors[0], details=[{"message": m} for m in validation_errors], code=EWB_VALIDATION_FAILED)

        record.transport_mode = transport_mode
        record.vehicle_number = vehicle_number
        record.transporter_id = transporter_id
        record.transporter_name = transporter_name
        record.distance_km = distance_km

        operation_service = IntegrationOperationService(self._session)
        provider = get_eway_bill_provider(is_production=False)
        idempotency_key = new_idempotency_key()

        if record.status == STATUS_UNKNOWN:
            prior_ops = await operation_service.list_for_entity(tenant_id=tenant_id, entity_type=EWAY_BILL, entity_id=record.id)
            prior_unknown = next((op for op in prior_ops if op.operation_type == OP_GENERATE and op.status == OP_UNKNOWN), None)
            reconcile_result = await provider.get_eway_bill_status(
                eway_bill_number=record.eway_bill_number,
                provider_reference=(prior_unknown.provider_reference if prior_unknown else None),
            )
            if reconcile_result.is_success and reconcile_result.eway_bill_number:
                record.eway_bill_number = reconcile_result.eway_bill_number
                record.status = GENERATED
                record.generated_at = datetime.now(timezone.utc)
                record.provider_reference = reconcile_result.provider_reference or record.provider_reference
                record.updated_by = actor_user_id
                record.row_version += 1
                await self._session.flush()
                await AuditService(self._session).record(
                    tenant_id=tenant_id, actor_user_id=actor_user_id, action="EWAY_BILL_STATUS_RECONCILED",
                    entity_type="eway_bill", entity_id=record.id,
                    after={"status": GENERATED, "eway_bill_number": record.eway_bill_number}, ip_address=ip_address,
                )
                return record
            if reconcile_result.is_unknown:
                raise ExternalServiceError(
                    "E-Way Bill status is still unknown after checking with the provider. This requires manual "
                    "review before retrying.", code=EWB_STATUS_UNKNOWN,
                )
            if prior_unknown and prior_unknown.idempotency_key:
                idempotency_key = prior_unknown.idempotency_key

        record.status = PROCESSING
        record.updated_by = actor_user_id
        await self._session.flush()

        operation = await operation_service.create(
            tenant_id=tenant_id, actor_user_id=actor_user_id, entity_type=EWAY_BILL, entity_id=record.id,
            operation_type=OP_GENERATE, idempotency_key=idempotency_key, provider=type(provider).__name__,
        )

        payload = self._build_payload(
            tenant=tenant, invoice=invoice, lines=lines, transport_mode=transport_mode, vehicle_number=vehicle_number,
            transporter_id=transporter_id, transporter_name=transporter_name, distance_km=distance_km,
        )
        try:
            await provider.authenticate()
            result = await provider.generate_eway_bill(idempotency_key=idempotency_key, payload=payload)
        except Exception as exc:  # noqa: BLE001
            result = ProviderResult(outcome=UNAVAILABLE, response_message=str(exc))

        await self._apply_provider_result(
            tenant_id=tenant_id, actor_user_id=actor_user_id, record=record, operation_service=operation_service,
            operation=operation, result=result, operation_type=OP_GENERATE, ip_address=ip_address,
        )

        if not result.is_success:
            message = _OUTCOME_TO_MESSAGE.get(result.outcome, result.response_message or "E-Way Bill generation failed.")
            code = _OUTCOME_TO_ERROR_CODE.get(result.outcome, EWB_VALIDATION_FAILED)
            if result.outcome in (UNAVAILABLE, RATE_LIMITED, TIMEOUT, AUTH_FAILED):
                raise ExternalServiceError(message, code=code)
            raise ValidationAppError(message, code=code)

        return record

    # --- refresh status ----------------------------------------------------

    async def refresh_status(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, eway_bill_id: uuid.UUID, ip_address: str | None) -> EwayBill:
        record = await self._get_locked(tenant_id, eway_bill_id)
        provider = get_eway_bill_provider(is_production=False)
        provider_result = await provider.get_eway_bill_status(
            eway_bill_number=record.eway_bill_number, provider_reference=record.provider_reference
        )

        operation_service = IntegrationOperationService(self._session)
        operation = await operation_service.create(
            tenant_id=tenant_id, actor_user_id=actor_user_id, entity_type=EWAY_BILL, entity_id=record.id,
            operation_type=OP_STATUS_CHECK, idempotency_key=None, provider=type(provider).__name__,
        )

        if provider_result.is_success and provider_result.eway_bill_number:
            record.status = GENERATED
        elif provider_result.is_unknown:
            record.status = STATUS_UNKNOWN

        await operation_service.mark_result(
            operation=operation,
            status=OP_SUCCEEDED if provider_result.is_success else (OP_UNKNOWN if provider_result.is_unknown else OP_FAILED),
            provider_reference=provider_result.provider_reference, response_code=provider_result.response_code,
            error_code=None, error_message=provider_result.response_message,
        )
        record.updated_by = actor_user_id
        record.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="EWAY_BILL_STATUS_RECONCILED",
            entity_type="eway_bill", entity_id=record.id, after={"status": record.status}, ip_address=ip_address,
        )
        return record

    # --- cancel (§22) ------------------------------------------------------

    async def cancel(self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, eway_bill_id: uuid.UUID, reason: str, ip_address: str | None) -> EwayBill:
        record = await self._get_locked(tenant_id, eway_bill_id)

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="EWAY_BILL_CANCELLATION_REQUESTED",
            entity_type="eway_bill", entity_id=record.id, ip_address=ip_address,
        )

        if record.status in LOCKED_STATUSES:
            raise ConflictError("An E-Way Bill operation is already in progress for this record.", code=EWB_CONCURRENT_OPERATION)
        if record.status not in CANCELLABLE_STATUSES:
            raise ValidationAppError(f"An e-way bill in {record.status} status cannot be cancelled.", code=EWB_NOT_ELIGIBLE_FOR_CANCEL)

        record.status = CANCEL_REQUESTED
        record.cancellation_reason = reason
        await self._session.flush()

        operation_service = IntegrationOperationService(self._session)
        provider = get_eway_bill_provider(is_production=False)
        idempotency_key = new_idempotency_key()
        operation = await operation_service.create(
            tenant_id=tenant_id, actor_user_id=actor_user_id, entity_type=EWAY_BILL, entity_id=record.id,
            operation_type=OP_CANCEL, idempotency_key=idempotency_key, provider=type(provider).__name__,
        )

        try:
            provider_result = await provider.cancel_eway_bill(eway_bill_number=record.eway_bill_number, reason=reason)
        except Exception as exc:  # noqa: BLE001
            provider_result = ProviderResult(outcome=UNAVAILABLE, response_message=str(exc))

        await self._apply_provider_result(
            tenant_id=tenant_id, actor_user_id=actor_user_id, record=record, operation_service=operation_service,
            operation=operation, result=provider_result, operation_type=OP_CANCEL, ip_address=ip_address,
        )

        if not provider_result.is_success:
            message = _OUTCOME_TO_MESSAGE.get(provider_result.outcome, provider_result.response_message or "E-Way Bill cancellation failed.")
            code = _OUTCOME_TO_ERROR_CODE.get(provider_result.outcome, EWB_VALIDATION_FAILED)
            raise ExternalServiceError(message, code=code)

        return record
