"""Sales reports (PROMPT-027 §10-§15).

Built entirely on top of POSTED `sales_invoice`/CONFIRMED `sales_return`/
POSTED `credit_debit_note` rows — DRAFT documents never appear (§44),
and a CANCELLED Sales Invoice is excluded from every aggregate the same
way (§43 — cancellation-after-posting doesn't exist yet for Sales
Invoice per the existing open decisions, so CANCELLED here only ever
means a DRAFT that was cancelled before posting, which already carries
zero financial values by construction).

Date basis: `invoice_date`/`return_date`/`note_date` — the document's
own date (§4 "Sales Report: Document / posting date according to
approved reporting policy" — this codebase has no separate posting_date
column on these tables distinct from the document's own date; POST
happens synchronously at that date, so the two concepts coincide here).

**Net Sales formula (§11/§56 OD-010, resolved for M1)**:
Net Sales = Taxable Sales (posted invoices) - Sales Returns (confirmed)
          - Credit Notes (posted) + Debit Notes (posted)
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit_debit_note import CREDIT_NOTE, DEBIT_NOTE
from app.models.credit_debit_note import POSTED as NOTE_POSTED
from app.models.credit_debit_note import CreditDebitNote
from app.models.customer import Customer
from app.models.product import Product
from app.models.sales_invoice import POSTED as INVOICE_POSTED
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.sales_return import CONFIRMED as RETURN_CONFIRMED
from app.models.sales_return import SalesReturn
from app.models.sales_return_line import SalesReturnLine

_ZERO = Decimal("0")


def _date_filters(column, date_from: date | None, date_to: date | None) -> list:
    conditions = []
    if date_from is not None:
        conditions.append(column >= date_from)
    if date_to is not None:
        conditions.append(column <= date_to)
    return conditions


class SalesReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Sales Summary (§11) --------------------------------------------

    async def get_sales_summary(self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None) -> dict:
        inv_conditions = [SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == INVOICE_POSTED, *_date_filters(SalesInvoice.invoice_date, date_from, date_to)]
        inv_row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(SalesInvoice.subtotal), _ZERO), func.coalesce(func.sum(SalesInvoice.discount_total), _ZERO),
                    func.coalesce(func.sum(SalesInvoice.taxable_total), _ZERO), func.coalesce(func.sum(SalesInvoice.cgst_total), _ZERO),
                    func.coalesce(func.sum(SalesInvoice.sgst_total), _ZERO), func.coalesce(func.sum(SalesInvoice.igst_total), _ZERO),
                    func.coalesce(func.sum(SalesInvoice.grand_total), _ZERO), func.count(SalesInvoice.id),
                ).where(*inv_conditions)
            )
        ).one()
        gross_sales, discount, taxable_sales, cgst, sgst, igst, gross_invoice_total, invoice_count = inv_row

        ret_conditions = [SalesReturn.tenant_id == tenant_id, SalesReturn.status == RETURN_CONFIRMED, *_date_filters(SalesReturn.return_date, date_from, date_to)]
        ret_row = (
            await self._session.execute(select(func.coalesce(func.sum(SalesReturn.taxable_total), _ZERO), func.coalesce(func.sum(SalesReturn.grand_total), _ZERO)).where(*ret_conditions))
        ).one()
        sales_returns_taxable, sales_returns_total = ret_row

        note_base = [CreditDebitNote.tenant_id == tenant_id, CreditDebitNote.status == NOTE_POSTED, *_date_filters(CreditDebitNote.note_date, date_from, date_to)]
        credit_row = (
            await self._session.execute(select(func.coalesce(func.sum(CreditDebitNote.taxable_total), _ZERO)).where(*note_base, CreditDebitNote.note_type == CREDIT_NOTE))
        ).scalar_one()
        debit_row = (
            await self._session.execute(select(func.coalesce(func.sum(CreditDebitNote.taxable_total), _ZERO)).where(*note_base, CreditDebitNote.note_type == DEBIT_NOTE))
        ).scalar_one()

        total_gst = cgst + sgst + igst
        net_sales = taxable_sales - sales_returns_taxable - credit_row + debit_row

        return {
            "gross_sales": gross_sales, "discount": discount, "taxable_sales": taxable_sales,
            "cgst": cgst, "sgst": sgst, "igst": igst, "total_gst": total_gst,
            "invoice_total": gross_invoice_total, "invoice_count": invoice_count,
            "sales_returns": sales_returns_taxable, "sales_returns_total": sales_returns_total,
            "credit_notes": credit_row, "debit_notes": debit_row, "net_sales": net_sales,
        }

    # --- Sales Invoice Register (§12) ------------------------------------

    async def list_sales_invoices(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, date_from: date | None, date_to: date | None,
        customer_id: uuid.UUID | None, payment_status: str | None, amount_min: Decimal | None, amount_max: Decimal | None,
    ) -> tuple[list[tuple[SalesInvoice, str]], int]:
        conditions = [SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == INVOICE_POSTED, *_date_filters(SalesInvoice.invoice_date, date_from, date_to)]
        if customer_id is not None:
            conditions.append(SalesInvoice.customer_id == customer_id)
        if payment_status:
            conditions.append(SalesInvoice.payment_status == payment_status)
        if amount_min is not None:
            conditions.append(SalesInvoice.grand_total >= amount_min)
        if amount_max is not None:
            conditions.append(SalesInvoice.grand_total <= amount_max)

        base = select(SalesInvoice, Customer.name).join(Customer, Customer.id == SalesInvoice.customer_id).where(*conditions)
        count_stmt = select(func.count()).select_from(select(SalesInvoice.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(SalesInvoice.invoice_date.desc(), SalesInvoice.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        return [(r[0], r[1]) for r in rows], total_items

    # --- Customer-wise Sales (§13) -----------------------------------------

    async def get_customer_wise_sales(
        self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None, page: int, page_size: int,
    ) -> tuple[list[dict], int]:
        conditions = [SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == INVOICE_POSTED, *_date_filters(SalesInvoice.invoice_date, date_from, date_to)]
        base = (
            select(
                SalesInvoice.customer_id, Customer.name, func.count(SalesInvoice.id), func.coalesce(func.sum(SalesInvoice.subtotal), _ZERO),
                func.coalesce(func.sum(SalesInvoice.discount_total), _ZERO), func.coalesce(func.sum(SalesInvoice.taxable_total), _ZERO),
                func.coalesce(func.sum(SalesInvoice.cgst_total + SalesInvoice.sgst_total + SalesInvoice.igst_total), _ZERO),
                func.coalesce(func.sum(SalesInvoice.grand_total), _ZERO), func.coalesce(func.sum(SalesInvoice.paid_amount), _ZERO),
            )
            .join(Customer, Customer.id == SalesInvoice.customer_id)
            .where(*conditions)
            .group_by(SalesInvoice.customer_id, Customer.name)
        )
        count_stmt = select(func.count()).select_from(base.with_only_columns(SalesInvoice.customer_id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(func.sum(SalesInvoice.grand_total).desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        # Sales Returns per customer, same period, folded in for "Net Sales".
        ret_conditions = [SalesReturn.tenant_id == tenant_id, SalesReturn.status == RETURN_CONFIRMED, *_date_filters(SalesReturn.return_date, date_from, date_to)]
        returns_by_customer = dict(
            (await self._session.execute(
                select(SalesReturn.customer_id, func.coalesce(func.sum(SalesReturn.taxable_total), _ZERO)).where(*ret_conditions).group_by(SalesReturn.customer_id)
            )).all()
        )

        items = []
        for customer_id, name, invoice_count, gross, discount, taxable, gst, grand_total, paid in rows:
            returns = returns_by_customer.get(customer_id, _ZERO)
            items.append({
                "customer_id": str(customer_id), "customer_name": name, "invoice_count": invoice_count, "gross_sales": gross,
                "discount": discount, "taxable_sales": taxable, "gst": gst, "returns": returns, "net_sales": taxable - returns,
                "outstanding": grand_total - paid,
            })
        return items, total_items

    # --- Product-wise Sales (§14) -------------------------------------------

    async def get_product_wise_sales(
        self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None, page: int, page_size: int,
    ) -> tuple[list[dict], int]:
        conditions = [
            SalesInvoiceLine.tenant_id == tenant_id, SalesInvoice.status == INVOICE_POSTED, SalesInvoiceLine.product_id.is_not(None),
            *_date_filters(SalesInvoice.invoice_date, date_from, date_to),
        ]
        base = (
            select(
                SalesInvoiceLine.product_id, Product.sku, Product.name, func.coalesce(func.sum(SalesInvoiceLine.quantity), _ZERO),
                func.coalesce(func.sum(SalesInvoiceLine.quantity * SalesInvoiceLine.unit_price), _ZERO), func.coalesce(func.sum(SalesInvoiceLine.discount_amount), _ZERO),
                func.coalesce(func.sum(SalesInvoiceLine.taxable_amount), _ZERO),
                func.coalesce(func.sum(SalesInvoiceLine.cgst_amount + SalesInvoiceLine.sgst_amount + SalesInvoiceLine.igst_amount), _ZERO),
            )
            .select_from(SalesInvoiceLine)
            .join(SalesInvoice, SalesInvoice.id == SalesInvoiceLine.invoice_id)
            .join(Product, Product.id == SalesInvoiceLine.product_id)
            .where(*conditions)
            .group_by(SalesInvoiceLine.product_id, Product.sku, Product.name)
        )
        count_stmt = select(func.count()).select_from(base.with_only_columns(SalesInvoiceLine.product_id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(func.sum(SalesInvoiceLine.taxable_amount).desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        ret_conditions = [
            SalesReturnLine.tenant_id == tenant_id, SalesReturn.status == RETURN_CONFIRMED, SalesReturnLine.product_id.is_not(None),
            *_date_filters(SalesReturn.return_date, date_from, date_to),
        ]
        returns_by_product = dict(
            (await self._session.execute(
                select(SalesReturnLine.product_id, func.coalesce(func.sum(SalesReturnLine.taxable_amount), _ZERO))
                .select_from(SalesReturnLine).join(SalesReturn, SalesReturn.id == SalesReturnLine.sales_return_id)
                .where(*ret_conditions).group_by(SalesReturnLine.product_id)
            )).all()
        )

        items = []
        for product_id, sku, name, qty, gross, discount, taxable, gst in rows:
            returns = returns_by_product.get(product_id, _ZERO)
            items.append({
                "product_id": str(product_id), "sku": sku, "product_name": name, "quantity_sold": qty, "gross_sales": gross,
                "discount": discount, "taxable_sales": taxable, "gst": gst, "returns": returns, "net_sales": taxable - returns,
            })
        return items, total_items

    # --- Sales Return Report (§15) -------------------------------------------

    async def list_sales_returns(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, date_from: date | None, date_to: date | None, customer_id: uuid.UUID | None,
    ) -> tuple[list[tuple[SalesReturn, str, str]], int]:
        conditions = [SalesReturn.tenant_id == tenant_id, SalesReturn.status == RETURN_CONFIRMED, *_date_filters(SalesReturn.return_date, date_from, date_to)]
        if customer_id is not None:
            conditions.append(SalesReturn.customer_id == customer_id)

        base = (
            select(SalesReturn, Customer.name, SalesInvoice.invoice_number)
            .join(Customer, Customer.id == SalesReturn.customer_id)
            .join(SalesInvoice, SalesInvoice.id == SalesReturn.source_invoice_id)
            .where(*conditions)
        )
        count_stmt = select(func.count()).select_from(select(SalesReturn.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(SalesReturn.return_date.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        return [(r[0], r[1], r[2]) for r in rows], total_items
