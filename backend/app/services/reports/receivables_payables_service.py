"""Receivables & Payables reports (PROMPT-027 §26-§29).

Outstanding is always `grand_total - paid_amount` computed directly on
POSTED `sales_invoice`/`purchase_invoice` rows — NOT `customer.balance`/
`supplier.balance` (those are separate reconciliation caches maintained
elsewhere; using the invoice-level source avoids a second, potentially
drifted number for the same concept — §2's own principle applied one
level down).

**Due date (§26/§56 OD-006, partially resolved)**: `purchase_invoice.
due_date` already exists as a stored column (used directly when
present). `sales_invoice` has NO due_date column of its own — where a
value is needed, it is opportunistically derived from `customer.
payment_terms_days` (`invoice_date + payment_terms_days`), an existing
field with no other consumer yet. Where neither is available, due_date
is `None` — no overdue/ageing calculation is performed on top of this
(§27/§29's own explicit instruction; OD-007/OD-008/OD-009 stay open).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.purchase_invoice import POSTED as PINV_POSTED
from app.models.purchase_invoice import PurchaseInvoice
from app.models.sales_invoice import POSTED as SINV_POSTED
from app.models.sales_invoice import SalesInvoice
from app.models.supplier import Supplier

_ZERO = Decimal("0")
UNPAID, PARTIALLY_PAID, PAID = "UNPAID", "PARTIALLY_PAID", "PAID"


class ReceivablesPayablesService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Receivables (§26/§27) --------------------------------------------

    async def get_receivables(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, customer_id: uuid.UUID | None,
    ) -> tuple[list[dict], int, dict]:
        conditions = [SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED, SalesInvoice.payment_status != PAID]
        if customer_id is not None:
            conditions.append(SalesInvoice.customer_id == customer_id)

        base = select(SalesInvoice, Customer.name, Customer.payment_terms_days).join(Customer, Customer.id == SalesInvoice.customer_id).where(*conditions)
        count_stmt = select(func.count()).select_from(select(SalesInvoice.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(SalesInvoice.invoice_date).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        items = []
        for invoice, customer_name, terms_days in rows:
            due_date = invoice.invoice_date + timedelta(days=terms_days) if terms_days else None
            items.append({
                "customer_id": str(invoice.customer_id), "customer_name": customer_name, "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number, "invoice_date": invoice.invoice_date.isoformat(),
                "due_date": due_date.isoformat() if due_date else None, "invoice_amount": invoice.grand_total,
                "paid_amount": invoice.paid_amount, "outstanding": invoice.grand_total - invoice.paid_amount,
                "payment_status": invoice.payment_status,
            })

        summary_conditions = [SalesInvoice.tenant_id == tenant_id, SalesInvoice.status == SINV_POSTED]
        summary_rows = (
            await self._session.execute(
                select(SalesInvoice.payment_status, func.count(SalesInvoice.id), func.coalesce(func.sum(SalesInvoice.grand_total - SalesInvoice.paid_amount), _ZERO))
                .where(*summary_conditions).group_by(SalesInvoice.payment_status)
            )
        ).all()
        summary = {"total_receivables": _ZERO, "fully_paid_count": 0, "partially_paid_count": 0, "unpaid_count": 0}
        for status, count, outstanding in summary_rows:
            if status == PAID:
                summary["fully_paid_count"] = count
            elif status == PARTIALLY_PAID:
                summary["partially_paid_count"] = count
                summary["total_receivables"] += outstanding
            elif status == UNPAID:
                summary["unpaid_count"] = count
                summary["total_receivables"] += outstanding

        return items, total_items, summary

    # --- Payables (§28/§29) --------------------------------------------------

    async def get_payables(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, supplier_id: uuid.UUID | None,
    ) -> tuple[list[dict], int, dict]:
        conditions = [PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.status == PINV_POSTED, PurchaseInvoice.payment_status != PAID]
        if supplier_id is not None:
            conditions.append(PurchaseInvoice.supplier_id == supplier_id)

        base = select(PurchaseInvoice, Supplier.name, Supplier.credit_terms_days).join(Supplier, Supplier.id == PurchaseInvoice.supplier_id).where(*conditions)
        count_stmt = select(func.count()).select_from(select(PurchaseInvoice.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(PurchaseInvoice.document_date).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()

        items = []
        for invoice, supplier_name, terms_days in rows:
            due_date = invoice.due_date or (invoice.document_date + timedelta(days=terms_days) if terms_days else None)
            items.append({
                "supplier_id": str(invoice.supplier_id), "supplier_name": supplier_name, "invoice_id": str(invoice.id),
                "invoice_number": invoice.purchase_invoice_number, "invoice_date": invoice.document_date.isoformat(),
                "due_date": due_date.isoformat() if due_date else None, "invoice_amount": invoice.grand_total,
                "paid_amount": invoice.paid_amount, "outstanding": invoice.grand_total - invoice.paid_amount,
                "payment_status": invoice.payment_status,
            })

        summary_conditions = [PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.status == PINV_POSTED]
        summary_rows = (
            await self._session.execute(
                select(PurchaseInvoice.payment_status, func.count(PurchaseInvoice.id), func.coalesce(func.sum(PurchaseInvoice.grand_total - PurchaseInvoice.paid_amount), _ZERO))
                .where(*summary_conditions).group_by(PurchaseInvoice.payment_status)
            )
        ).all()
        summary = {"total_payables": _ZERO, "fully_paid_count": 0, "partially_paid_count": 0, "unpaid_count": 0}
        for status, count, outstanding in summary_rows:
            if status == PAID:
                summary["fully_paid_count"] = count
            elif status == PARTIALLY_PAID:
                summary["partially_paid_count"] = count
                summary["total_payables"] += outstanding
            elif status == UNPAID:
                summary["unpaid_count"] = count
                summary["total_payables"] += outstanding

        return items, total_items, summary
