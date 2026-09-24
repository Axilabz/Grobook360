"""GST Rule Engine & GST Reporting endpoints (PROMPT-026 §40).

Deliberately no `POST /gst/calculate`/`POST /gst/validate` endpoint that
lets an arbitrary client submit numbers for the server to "validate" or
"calculate" against — §40's own explicit instruction ("prefer internal
service invocation from Sales/Purchase rather than allowing arbitrary
clients to create tax records"). GST calculation happens exclusively
inside `gst_calculation_service.py`, called internally by each document
service's own posting flow; this router only ever exposes READ access to
what was already calculated and snapshotted (`gst_transaction`), plus
return-preparation aggregation/validation/reconciliation views built on
top of it.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.correlation import get_correlation_id
from app.core.deps import AuthenticatedContext, require_permission
from app.core.error_codes import GST_RETURN_PERIOD_INVALID, GST_TRANSACTION_NOT_FOUND
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationAppError
from app.core.permissions import GST_EXPORT, GST_PREPARE_RETURNS, GST_VIEW
from app.db.session import get_db_session
from app.models.gst_transaction import GstTransaction
from app.models.gst_transaction_line import GstTransactionLine
from app.schemas.envelopes import Pagination
from app.schemas.gst import (
    GstTransactionDetail,
    GstTransactionLineItem,
    GstTransactionListItem,
    ValidationIssueItem,
    ValidationResult,
)
from app.services.gst.gstr_service import GstrService, GstTotals

router = APIRouter(prefix="/gst", tags=["gst"])


def _meta() -> dict:
    return {"correlation_id": str(get_correlation_id()), "timestamp": datetime.now(timezone.utc).isoformat()}


def _require_tenant(context: AuthenticatedContext) -> uuid.UUID:
    if context.tenant_id is None:
        raise AuthorizationError("This operation requires a tenant context.")
    return context.tenant_id


def _validate_period(return_period: str) -> None:
    parts = return_period.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValidationAppError("return_period must be in YYYY-MM format.", code=GST_RETURN_PERIOD_INVALID)


def _totals_dict(totals: GstTotals) -> dict:
    return {
        "taxable_value": str(totals.taxable_value), "cgst": str(totals.cgst), "sgst": str(totals.sgst),
        "igst": str(totals.igst), "cess": str(totals.cess), "total_gst": str(totals.total_gst),
    }


def _to_list_item(transaction: GstTransaction) -> GstTransactionListItem:
    return GstTransactionListItem(
        id=str(transaction.id), source_type=transaction.source_type, source_id=str(transaction.source_id),
        source_number=transaction.source_number, event_type=transaction.event_type, direction=transaction.direction,
        classification=transaction.classification, party_name=transaction.party_name, party_gstin=transaction.party_gstin,
        place_of_supply_state_code=transaction.place_of_supply_state_code, document_date=transaction.document_date.isoformat(),
        financial_year_label=transaction.financial_year_label, return_period=transaction.return_period,
        taxable_value=str(transaction.taxable_value), cgst_amount=str(transaction.cgst_amount), sgst_amount=str(transaction.sgst_amount),
        igst_amount=str(transaction.igst_amount), cess_amount=str(transaction.cess_amount), total_gst=str(transaction.total_gst),
        total_amount=str(transaction.total_amount),
    )


def _to_line_item(line: GstTransactionLine) -> GstTransactionLineItem:
    return GstTransactionLineItem(
        line_no=line.line_no, hsn_code=line.hsn_code, quantity=str(line.quantity), unit_price=str(line.unit_price),
        gst_rate=str(line.gst_rate), taxable_value=str(line.taxable_value), cgst_amount=str(line.cgst_amount),
        sgst_amount=str(line.sgst_amount), igst_amount=str(line.igst_amount), cess_amount=str(line.cess_amount),
        line_total=str(line.line_total),
    )


def _bucket_dict(bucket: dict) -> dict:
    return {
        "count": bucket["count"], "totals": _totals_dict(bucket["totals"]),
        "transactions": [_to_list_item(t).model_dump() for t in bucket["transactions"]],
    }


def _hsn_summary_dict(entries: list[dict]) -> list[dict]:
    return [
        {
            "hsn_code": e["hsn_code"], "taxable_value": str(e["taxable_value"]), "cgst": str(e["cgst"]), "sgst": str(e["sgst"]),
            "igst": str(e["igst"]), "cess": str(e["cess"]), "quantity": str(e["quantity"]),
        }
        for e in entries
    ]


@router.get("/transactions")
async def list_transactions(
    page: int = 1, page_size: int = 25, return_period: str | None = None, source_type: str | None = None,
    classification: str | None = None, party_gstin: str | None = None, direction: str | None = None,
    context: AuthenticatedContext = Depends(require_permission(GST_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    page_size = min(max(page_size, 1), 100)
    page = max(page, 1)
    service = GstrService(session)
    transactions, total_items = await service.list_transactions(
        tenant_id=tenant_id, page=page, page_size=page_size, return_period=return_period, source_type=source_type,
        classification=classification, party_gstin=party_gstin, direction=direction,
    )
    total_pages = (total_items + page_size - 1) // page_size if total_items else 0
    return {
        "data": [_to_list_item(t).model_dump() for t in transactions],
        "pagination": Pagination(page=page, page_size=page_size, total_items=total_items, total_pages=total_pages).model_dump(),
        "meta": _meta(),
    }


@router.get("/transactions/{transaction_id}")
async def get_transaction(
    transaction_id: uuid.UUID, context: AuthenticatedContext = Depends(require_permission(GST_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    service = GstrService(session)
    transaction, lines = await service.get_transaction(tenant_id=tenant_id, transaction_id=transaction_id)
    if transaction is None:
        raise NotFoundError("GST transaction not found", code=GST_TRANSACTION_NOT_FOUND)
    detail = GstTransactionDetail(**_to_list_item(transaction).model_dump(), lines=[_to_line_item(line) for line in lines])
    return {"data": detail.model_dump(), "meta": _meta()}


@router.get("/dashboard")
async def dashboard(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(GST_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_period(return_period)
    result = await GstrService(session).dashboard(tenant_id=tenant_id, return_period=return_period)
    data = {
        "return_period": result["return_period"], "output_gst": str(result["output_gst"]), "input_gst": str(result["input_gst"]),
        "net_gst_position": str(result["net_gst_position"]), "b2b_sales": str(result["b2b_sales"]), "b2c_sales": str(result["b2c_sales"]),
        "credit_notes": str(result["credit_notes"]), "debit_notes": str(result["debit_notes"]),
        "validation_error_count": result["validation_error_count"],
    }
    return {"data": data, "meta": _meta()}


@router.get("/returns/gstr1")
async def get_gstr1(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(GST_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_period(return_period)
    dataset = await GstrService(session).gstr1_dataset(tenant_id=tenant_id, return_period=return_period)
    data = {
        "return_period": dataset["return_period"], "b2b": _bucket_dict(dataset["b2b"]), "b2c": _bucket_dict(dataset["b2c"]),
        "credit_notes": _bucket_dict(dataset["credit_notes"]), "debit_notes": _bucket_dict(dataset["debit_notes"]),
        "hsn_summary": _hsn_summary_dict(dataset["hsn_summary"]),
    }
    return {"data": data, "meta": _meta()}


@router.post("/returns/gstr1/validate")
async def validate_gstr1(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(GST_PREPARE_RETURNS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_period(return_period)
    issues = await GstrService(session).validate_gstr1(tenant_id=tenant_id, return_period=return_period)
    result = ValidationResult(
        return_period=return_period, is_valid=not any(i.severity == "ERROR" for i in issues),
        error_count=len([i for i in issues if i.severity == "ERROR"]), warning_count=len([i for i in issues if i.severity == "WARNING"]),
        issues=[ValidationIssueItem(**vars(i)) for i in issues],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/returns/gstr3b")
async def get_gstr3b(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(GST_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_period(return_period)
    dataset = await GstrService(session).gstr3b_dataset(tenant_id=tenant_id, return_period=return_period)
    data = {
        "return_period": dataset["return_period"],
        "outward_taxable_supplies": _totals_dict(dataset["outward_taxable_supplies"]),
        "output_cgst": str(dataset["output_cgst"]), "output_sgst": str(dataset["output_sgst"]), "output_igst": str(dataset["output_igst"]),
        "inward_supplies": _totals_dict(dataset["inward_supplies"]),
        "input_tax_credit_cgst": str(dataset["input_tax_credit_cgst"]), "input_tax_credit_sgst": str(dataset["input_tax_credit_sgst"]),
        "input_tax_credit_igst": str(dataset["input_tax_credit_igst"]), "net_gst_payable": str(dataset["net_gst_payable"]),
    }
    return {"data": data, "meta": _meta()}


@router.post("/returns/gstr3b/validate")
async def validate_gstr3b(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(GST_PREPARE_RETURNS)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_period(return_period)
    issues = await GstrService(session).validate_gstr3b(tenant_id=tenant_id, return_period=return_period)
    result = ValidationResult(
        return_period=return_period, is_valid=not any(i.severity == "ERROR" for i in issues),
        error_count=len([i for i in issues if i.severity == "ERROR"]), warning_count=len([i for i in issues if i.severity == "WARNING"]),
        issues=[ValidationIssueItem(**vars(i)) for i in issues],
    )
    return {"data": result.model_dump(), "meta": _meta()}


@router.get("/reconciliation")
async def reconciliation(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(GST_VIEW)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_period(return_period)
    result = await GstrService(session).reconciliation(tenant_id=tenant_id, return_period=return_period)
    data = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in result.items()}
    return {"data": data, "meta": _meta()}


@router.get("/returns/gstr1/export")
async def export_gstr1(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(GST_EXPORT)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    """§39: JSON export only in this MVP — no CSV/Excel writer and no
    statutory-schema-conformant file exists yet (§39/OD-008/OD-009: the
    exact GSTR-1 statutory schema/version is not finalized). This is
    explicitly NOT claimed to be portal-ready."""
    tenant_id = _require_tenant(context)
    _validate_period(return_period)
    dataset = await GstrService(session).gstr1_dataset(tenant_id=tenant_id, return_period=return_period)
    data = {
        "return_period": dataset["return_period"], "b2b": _bucket_dict(dataset["b2b"]), "b2c": _bucket_dict(dataset["b2c"]),
        "credit_notes": _bucket_dict(dataset["credit_notes"]), "debit_notes": _bucket_dict(dataset["debit_notes"]),
        "hsn_summary": _hsn_summary_dict(dataset["hsn_summary"]),
    }
    return {"data": data, "meta": _meta()}


@router.get("/returns/gstr3b/export")
async def export_gstr3b(
    return_period: str, context: AuthenticatedContext = Depends(require_permission(GST_EXPORT)), session: AsyncSession = Depends(get_db_session),
) -> dict:
    tenant_id = _require_tenant(context)
    _validate_period(return_period)
    dataset = await GstrService(session).gstr3b_dataset(tenant_id=tenant_id, return_period=return_period)
    data = {
        "return_period": dataset["return_period"],
        "outward_taxable_supplies": _totals_dict(dataset["outward_taxable_supplies"]),
        "output_cgst": str(dataset["output_cgst"]), "output_sgst": str(dataset["output_sgst"]), "output_igst": str(dataset["output_igst"]),
        "inward_supplies": _totals_dict(dataset["inward_supplies"]),
        "input_tax_credit_cgst": str(dataset["input_tax_credit_cgst"]), "input_tax_credit_sgst": str(dataset["input_tax_credit_sgst"]),
        "input_tax_credit_igst": str(dataset["input_tax_credit_igst"]), "net_gst_payable": str(dataset["net_gst_payable"]),
    }
    return {"data": data, "meta": _meta()}
