"""Purchase reports (PROMPT-027 §16-§21).

Mirrors `sales_report_service.py`'s exact discipline one level down the
Purchase chain — built on POSTED `purchase_invoice`/CONFIRMED
`purchase_return` rows only (§44 draft exclusion). Unlike Sales, a
Purchase Invoice/Return CAN be cancelled AFTER posting (PROMPT-022/023's
own reversal support) — a CANCELLED row is excluded from every
aggregate here exactly like DRAFT, since its accounting/GST/stock impact
was already reversed via a separate REVERSAL journal/gst_transaction/
stock-ledger entry (§43); the Purchase Invoice Register still shows
CANCELLED rows (with their status column) for traceability, matching
§18's own column list which includes no such exclusion.

Date basis: `document_date` (Purchase's own equivalent of `invoice_date`
— see `app/models/purchase_invoice.py`'s own field naming).

**Net Purchase formula (§17/§56 OD-011, resolved for M1)**: no
Purchase-side Credit/Debit Note exists in this codebase (confirmed by
PROMPT-017's own explicit scope), so:
Net Purchase = Taxable Purchase (posted invoices) - Purchase Returns (confirmed)
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.models.purchase_invoice import CANCELLED as PINV_CANCELLED
from app.models.purchase_invoice import POSTED as PINV_POSTED
from app.models.purchase_invoice import PurchaseInvoice
from app.models.purchase_invoice_line import PurchaseInvoiceLine
from app.models.purchase_return import CONFIRMED as PRET_CONFIRMED
from app.models.purchase_return import PurchaseReturn
from app.models.purchase_return_line import PurchaseReturnLine
from app.models.supplier import Supplier

_ZERO = Decimal("0")


def _date_filters(column, date_from: date | None, date_to: date | None) -> list:
    conditions = []
    if date_from is not None:
        conditions.append(column >= date_from)
    if date_to is not None:
        conditions.append(column <= date_to)
    return conditions


class PurchaseReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Purchase Summary (§17) --------------------------------------------

    async def get_purchase_summary(self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None) -> dict:
        inv_conditions = [PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.status == PINV_POSTED, *_date_filters(PurchaseInvoice.document_date, date_from, date_to)]
        inv_row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(PurchaseInvoice.subtotal), _ZERO), func.coalesce(func.sum(PurchaseInvoice.discount_total), _ZERO),
                    func.coalesce(func.sum(PurchaseInvoice.taxable_total), _ZERO), func.coalesce(func.sum(PurchaseInvoice.cgst_total), _ZERO),
                    func.coalesce(func.sum(PurchaseInvoice.sgst_total), _ZERO), func.coalesce(func.sum(PurchaseInvoice.igst_total), _ZERO),
                    func.count(PurchaseInvoice.id),
                ).where(*inv_conditions)
            )
        ).one()
        gross_purchase, discount, taxable_purchase, cgst, sgst, igst, invoice_count = inv_row

        ret_conditions = [PurchaseReturn.tenant_id == tenant_id, PurchaseReturn.status == PRET_CONFIRMED, *_date_filters(PurchaseReturn.document_date, date_from, date_to)]
        ret_row = (
            await self._session.execute(select(func.coalesce(func.sum(PurchaseReturn.taxable_total), _ZERO)).where(*ret_conditions))
        ).scalar_one()

        total_input_gst = cgst + sgst + igst
        net_purchase = taxable_purchase - ret_row

        return {
            "gross_purchase": gross_purchase, "discount": discount, "taxable_purchase": taxable_purchase,
            "input_cgst": cgst, "input_sgst": sgst, "input_igst": igst, "total_input_gst": total_input_gst,
            "invoice_count": invoice_count, "purchase_returns": ret_row, "net_purchase": net_purchase,
        }

    # --- Purchase Invoice Register (§18) ------------------------------------

    async def list_purchase_invoices(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, date_from: date | None, date_to: date | None,
        supplier_id: uuid.UUID | None, payment_status: str | None,
    ) -> tuple[list[tuple[PurchaseInvoice, str]], int]:
        conditions = [PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.status.in_([PINV_POSTED, PINV_CANCELLED]), *_date_filters(PurchaseInvoice.document_date, date_from, date_to)]
        if supplier_id is not None:
            conditions.append(PurchaseInvoice.supplier_id == supplier_id)
        if payment_status:
            conditions.append(PurchaseInvoice.payment_status == payment_status)

        base = select(PurchaseInvoice, Supplier.name).join(Supplier, Supplier.id == PurchaseInvoice.supplier_id).where(*conditions)
        count_stmt = select(func.count()).select_from(select(PurchaseInvoice.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(PurchaseInvoice.document_date.desc(), PurchaseInvoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        return [(r[0], r[1]) for r in rows], total_items

    # --- Supplier-wise Purchase (§19) ---------------------------------------

    async def get_supplier_wise_purchase(
        self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None, page: int, page_size: int,
    ) -> tuple[list[dict], int]:
        conditions = [PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.status == PINV_POSTED, *_date_filters(PurchaseInvoice.document_date, date_from, date_to)]
        base = (
            select(
                PurchaseInvoice.supplier_id, Supplier.name, func.count(PurchaseInvoice.id), func.coalesce(func.sum(PurchaseInvoice.subtotal), _ZERO),
                func.coalesce(func.sum(PurchaseInvoice.discount_total), _ZERO), func.coalesce(func.sum(PurchaseInvoice.taxable_total), _ZERO),
                func.coalesce(func.sum(PurchaseInvoice.cgst_total + PurchaseInvoice.sgst_total + PurchaseInvoice.igst_total), _ZERO),
                func.coalesce(func.sum(PurchaseInvoice.grand_total), _ZERO), func.coalesce(func.sum(PurchaseInvoice.paid_amount), _ZERO),
            )
            .join(Supplier, Supplier.id == PurchaseInvoice.supplier_id)
            .where(*conditions)
            .group_by(PurchaseInvoice.supplier_id, Supplier.name)
        )
        count_stmt = select(func.count()).select_from(base.with_only_columns(PurchaseInvoice.supplier_id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(func.sum(PurchaseInvoice.grand_total).desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        ret_conditions = [PurchaseReturn.tenant_id == tenant_id, PurchaseReturn.status == PRET_CONFIRMED, *_date_filters(PurchaseReturn.document_date, date_from, date_to)]
        returns_by_supplier = dict(
            (await self._session.execute(
                select(PurchaseReturn.supplier_id, func.coalesce(func.sum(PurchaseReturn.taxable_total), _ZERO)).where(*ret_conditions).group_by(PurchaseReturn.supplier_id)
            )).all()
        )

        items = []
        for supplier_id, name, invoice_count, gross, discount, taxable, gst, grand_total, paid in rows:
            returns = returns_by_supplier.get(supplier_id, _ZERO)
            items.append({
                "supplier_id": str(supplier_id), "supplier_name": name, "invoice_count": invoice_count, "gross_purchase": gross,
                "discount": discount, "taxable_purchase": taxable, "gst": gst, "returns": returns, "net_purchase": taxable - returns,
                "outstanding": grand_total - paid,
            })
        return items, total_items

    # --- Product-wise Purchase (§20) -----------------------------------------

    async def get_product_wise_purchase(
        self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None, page: int, page_size: int,
    ) -> tuple[list[dict], int]:
        conditions = [
            PurchaseInvoiceLine.tenant_id == tenant_id, PurchaseInvoice.status == PINV_POSTED, PurchaseInvoiceLine.product_id.is_not(None),
            *_date_filters(PurchaseInvoice.document_date, date_from, date_to),
        ]
        base = (
            select(
                PurchaseInvoiceLine.product_id, Product.sku, Product.name, func.coalesce(func.sum(PurchaseInvoiceLine.quantity), _ZERO),
                func.coalesce(func.sum(PurchaseInvoiceLine.quantity * PurchaseInvoiceLine.unit_price), _ZERO), func.coalesce(func.sum(PurchaseInvoiceLine.discount_amount), _ZERO),
                func.coalesce(func.sum(PurchaseInvoiceLine.taxable_amount), _ZERO),
                func.coalesce(func.sum(PurchaseInvoiceLine.cgst_amount + PurchaseInvoiceLine.sgst_amount + PurchaseInvoiceLine.igst_amount), _ZERO),
            )
            .select_from(PurchaseInvoiceLine)
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseInvoiceLine.purchase_invoice_id)
            .join(Product, Product.id == PurchaseInvoiceLine.product_id)
            .where(*conditions)
            .group_by(PurchaseInvoiceLine.product_id, Product.sku, Product.name)
        )
        count_stmt = select(func.count()).select_from(base.with_only_columns(PurchaseInvoiceLine.product_id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(func.sum(PurchaseInvoiceLine.taxable_amount).desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        ret_conditions = [
            PurchaseReturnLine.tenant_id == tenant_id, PurchaseReturn.status == PRET_CONFIRMED, PurchaseReturnLine.product_id.is_not(None),
            *_date_filters(PurchaseReturn.document_date, date_from, date_to),
        ]
        returns_by_product = dict(
            (await self._session.execute(
                select(PurchaseReturnLine.product_id, func.coalesce(func.sum(PurchaseReturnLine.taxable_amount), _ZERO))
                .select_from(PurchaseReturnLine).join(PurchaseReturn, PurchaseReturn.id == PurchaseReturnLine.purchase_return_id)
                .where(*ret_conditions).group_by(PurchaseReturnLine.product_id)
            )).all()
        )

        items = []
        for product_id, sku, name, qty, gross, discount, taxable, gst in rows:
            returns = returns_by_product.get(product_id, _ZERO)
            items.append({
                "product_id": str(product_id), "sku": sku, "product_name": name, "quantity_purchased": qty, "purchase_value": gross,
                "discount": discount, "taxable_value": taxable, "gst": gst, "returns": returns, "net_purchase": taxable - returns,
            })
        return items, total_items

    # --- Purchase Return Report (§21) -----------------------------------------

    async def list_purchase_returns(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, date_from: date | None, date_to: date | None, supplier_id: uuid.UUID | None,
    ) -> tuple[list[tuple[PurchaseReturn, str, str]], int]:
        conditions = [PurchaseReturn.tenant_id == tenant_id, PurchaseReturn.status == PRET_CONFIRMED, *_date_filters(PurchaseReturn.document_date, date_from, date_to)]
        if supplier_id is not None:
            conditions.append(PurchaseReturn.supplier_id == supplier_id)

        base = (
            select(PurchaseReturn, Supplier.name, PurchaseInvoice.purchase_invoice_number)
            .join(Supplier, Supplier.id == PurchaseReturn.supplier_id)
            .join(PurchaseInvoice, PurchaseInvoice.id == PurchaseReturn.source_purchase_invoice_id)
            .where(*conditions)
        )
        count_stmt = select(func.count()).select_from(select(PurchaseReturn.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(PurchaseReturn.document_date.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        return [(r[0], r[1], r[2]) for r in rows], total_items
