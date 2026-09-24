"""E-Invoice / E-Way Bill request/response schemas (PROMPT-018).

`EinvoiceDetail`/`EwayBillDetail` deliberately expose `has_signed_qr`/
`has_signed_invoice_data` booleans rather than the raw payloads inline —
the actual signed data is large and belongs to the print/preview layer's
own dedicated fetch, not every status-check response (§14/§35).
"""

from decimal import Decimal

from pydantic import BaseModel, Field


class EinvoiceDetail(BaseModel):
    id: str | None
    sales_invoice_id: str
    status: str
    applicable: bool | None
    applicability_reason: str | None
    irn: str | None
    ack_number: str | None
    ack_date: str | None
    has_signed_qr: bool
    provider_reference: str | None
    provider_response_message: str | None
    generated_at: str | None
    cancelled_at: str | None
    cancellation_reason: str | None
    row_version: int | None
    updated_at: str | None


class EwayBillDetail(BaseModel):
    id: str | None
    sales_invoice_id: str
    status: str
    applicable: bool | None
    applicability_reason: str | None
    eway_bill_number: str | None
    valid_from: str | None
    valid_until: str | None
    transport_mode: str | None
    vehicle_number: str | None
    transporter_id: str | None
    transporter_name: str | None
    distance_km: str | None
    provider_reference: str | None
    provider_response_message: str | None
    generated_at: str | None
    cancelled_at: str | None
    cancellation_reason: str | None
    row_version: int | None
    updated_at: str | None


class GenerateEwayBillRequest(BaseModel):
    invoice_id: str
    transport_mode: str | None = Field(default=None, max_length=20)
    vehicle_number: str | None = Field(default=None, max_length=20)
    transporter_id: str | None = Field(default=None, max_length=20)
    transporter_name: str | None = Field(default=None, max_length=200)
    distance_km: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class EinvoiceCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class EwayBillCancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class IntegrationOperationDetail(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    operation_type: str
    status: str
    attempt_count: int
    provider: str | None
    provider_reference: str | None
    response_code: str | None
    error_code: str | None
    error_message: str | None
    correlation_id: str | None
    requested_at: str | None
    responded_at: str | None
    created_at: str
