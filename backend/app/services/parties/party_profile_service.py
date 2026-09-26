"""Party 360 Profile — a single reusable service for BOTH Customer and
Supplier (per the source prompt's own §32/§47 "one architecture, not two
parallel builds" mandate), branching only on `party_type` to pick the
correct model/terminology on each side. Every number here is read
directly from already-authoritative tables (sales_invoice,
purchase_invoice, payment, sales_order, purchase_order, delivery_challan,
goods_receipt, sales_return, purchase_return) — nothing is recalculated
independently of those tables' own posted/confirmed state.

Deliberately bounded against the much larger source prompt: ONE combined
endpoint or "GET /parties/{party_type}/{party_id}" is far more than a
30/34/44 style Progressive-Loading builder wants) rather than 10
separate report-service methods each returning a small slice
(§43's own "load progressively" instruction) — this is a documented
scope reduction, not a silent shortcut; see PartyProfileService's own
call sites in api/v1/parties.py.
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.customer import Customer
from app.models.delivery_challan import DeliveryChallan
from app.models.goods_receipt import GoodsReceipt
from app.models.payment import CUSTOMER as PAYMENT_CUSTOMER
from app.models.payment import SUPPLIER as PAYMENT_SUPPLIER
from app.models.payment import POSTED as PAYMENT_POSTED
from app.models.payment import Payment
from app.models.product import Product
from app.models.purchase_invoice import POSTED as PINV_POSTED
from app.models.purchase_invoice import PurchaseInvoice
from app.models.purchase_invoice_line import PurchaseInvoiceLine
from app.models.purchase_order import CANCELLED as PO_CANCELLED
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_return import PurchaseReturn
from app.models.sales_invoice import POSTED as SINV_POSTED
from app.models.sales_invoice import SalesInvoice
from app.models.sales_invoice_line import SalesInvoiceLine
from app.models.sales_order import CANCELLED as SO_CANCELLED
from app.models.sales_order import SalesOrder
from app.models.sales_return import SalesReturn
from app.models.supplier import Supplier

_ZERO = Decimal("0")
_TOP_N = 5
_RECENT_LIMIT = 10

CUSTOMER = "customer"
SUPPLIER = "supplier"
PARTY_TYPES = frozenset({CUSTOMER, SUPPLIER})

_AGING_BUCKETS = ("current", "days_1_30", "days_31_60", "days_61_90", "days_90_plus", "no_due_date")


class PartyProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_profile(self, *, tenant_id: uuid.UUID, party_type: str, party_id: uuid.UUID) -> dict:
        if party_type not in PARTY_TYPES:
            raise ValidationAppError(f"Unknown party type '{party_type}'.")
        if party_type == CUSTOMER:
            return await self._customer_profile(tenant_id, party_id)
        return await self._supplier_profile(tenant_id, party_id)

    # --- CUSTOMER side ---------------------------------------------------

    async def _customer_profile(self, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> dict:
        customer = (
            await self._session.execute(
                select(Customer).where(Customer.tenant_id == tenant_id, Customer.id == customer_id)
            )
        ).scalar_one_or_none()
        if customer is None:
            raise NotFoundError("Customer not found.")

        header = {
            "party_type": CUSTOMER, "id": str(customer.id), "code": customer.customer_code, "name": customer.name,
            "status": customer.status, "gstin": customer.gstin, "phone": customer.phone, "email": customer.email,
            "address": customer.address, "city": customer.city, "state_code": customer.state_code, "pincode": customer.pincode,
            "credit_limit": customer.credit_limit, "payment_terms_days": customer.payment_terms_days,
        }

        inv_row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(SalesInvoice.grand_total), _ZERO),
                    func.coalesce(func.sum(SalesInvoice.grand_total - SalesInvoice.paid_amount), _ZERO),
                    func.count(SalesInvoice.id), func.max(SalesInvoice.invoice_date),
                ).where(SalesInvoice.tenant_id == tenant_id, SalesInvoice.customer_id == customer_id, SalesInvoice.status == SINV_POSTED)
            )
        ).one()
        total_sales, outstanding, invoice_count, last_invoice_date = inv_row

        collected = (
            await self._session.execute(
                select(func.coalesce(func.sum(Payment.amount), _ZERO)).where(
                    Payment.tenant_id == tenant_id, Payment.customer_id == customer_id,
                    Payment.party_type == PAYMENT_CUSTOMER, Payment.status == PAYMENT_POSTED,
                )
            )
        ).scalar_one()

        order_count = (
            await self._session.execute(
                select(func.count()).select_from(SalesOrder).where(
                    SalesOrder.tenant_id == tenant_id, SalesOrder.customer_id == customer_id, SalesOrder.status != SO_CANCELLED,
                )
            )
        ).scalar_one()

        kpis = {
            "total_sales": total_sales, "outstanding": outstanding, "collected": collected,
            "invoice_count": invoice_count, "order_count": order_count,
            "last_transaction_date": last_invoice_date.isoformat() if last_invoice_date else None,
        }

        aging = await self._aging(tenant_id=tenant_id, invoice_model=SalesInvoice, party_field=SalesInvoice.customer_id, party_id=customer_id, posted_status=SINV_POSTED, payment_terms_days=customer.payment_terms_days)

        top_products = await self._top_products(
            tenant_id=tenant_id, line_model=SalesInvoiceLine, invoice_model=SalesInvoice, invoice_fk=SalesInvoiceLine.invoice_id,
            party_field=SalesInvoice.customer_id, party_id=customer_id, posted_status=SINV_POSTED, date_field=SalesInvoice.invoice_date,
        )

        payment_history = await self._payment_history(tenant_id=tenant_id, party_type=PAYMENT_CUSTOMER, party_field=Payment.customer_id, party_id=customer_id)

        recent = await self._customer_recent_transactions(tenant_id, customer_id)

        return {"header": header, "kpis": kpis, "outstanding_aging": aging, "top_products": top_products, "payment_history": payment_history, "recent_transactions": recent}

    async def _customer_recent_transactions(self, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> list[dict]:
        items: list[dict] = []

        rows = (await self._session.execute(
            select(SalesInvoice.invoice_number, SalesInvoice.invoice_date, SalesInvoice.grand_total, SalesInvoice.status, SalesInvoice.created_at)
            .where(SalesInvoice.tenant_id == tenant_id, SalesInvoice.customer_id == customer_id)
            .order_by(SalesInvoice.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, amount, status, created_at in rows:
            items.append({"type": "SALES_INVOICE", "reference": number, "date": doc_date.isoformat(), "amount": amount, "status": status, "sort_key": created_at})

        rows = (await self._session.execute(
            select(SalesOrder.order_number, SalesOrder.order_date, SalesOrder.grand_total, SalesOrder.status, SalesOrder.created_at)
            .where(SalesOrder.tenant_id == tenant_id, SalesOrder.customer_id == customer_id)
            .order_by(SalesOrder.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, amount, status, created_at in rows:
            items.append({"type": "SALES_ORDER", "reference": number, "date": doc_date.isoformat(), "amount": amount, "status": status, "sort_key": created_at})

        rows = (await self._session.execute(
            select(DeliveryChallan.challan_number, DeliveryChallan.challan_date, DeliveryChallan.status, DeliveryChallan.created_at)
            .where(DeliveryChallan.tenant_id == tenant_id, DeliveryChallan.customer_id == customer_id)
            .order_by(DeliveryChallan.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, status, created_at in rows:
            items.append({"type": "DELIVERY_CHALLAN", "reference": number, "date": doc_date.isoformat(), "amount": None, "status": status, "sort_key": created_at})

        rows = (await self._session.execute(
            select(SalesReturn.return_number, SalesReturn.return_date, SalesReturn.grand_total, SalesReturn.status, SalesReturn.created_at)
            .where(SalesReturn.tenant_id == tenant_id, SalesReturn.customer_id == customer_id)
            .order_by(SalesReturn.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, amount, status, created_at in rows:
            items.append({"type": "SALES_RETURN", "reference": number, "date": doc_date.isoformat(), "amount": amount, "status": status, "sort_key": created_at})

        rows = (await self._session.execute(
            select(Payment.payment_number, Payment.payment_date, Payment.amount, Payment.status, Payment.created_at)
            .where(Payment.tenant_id == tenant_id, Payment.customer_id == customer_id, Payment.party_type == PAYMENT_CUSTOMER)
            .order_by(Payment.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, amount, status, created_at in rows:
            items.append({"type": "CUSTOMER_RECEIPT", "reference": number, "date": doc_date.isoformat(), "amount": amount, "status": status, "sort_key": created_at})

        items.sort(key=lambda i: i["sort_key"], reverse=True)
        for item in items:
            del item["sort_key"]
        return items[:_RECENT_LIMIT]

    # --- SUPPLIER side -----------------------------------------------------

    async def _supplier_profile(self, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> dict:
        supplier = (
            await self._session.execute(
                select(Supplier).where(Supplier.tenant_id == tenant_id, Supplier.id == supplier_id)
            )
        ).scalar_one_or_none()
        if supplier is None:
            raise NotFoundError("Supplier not found.")

        header = {
            "party_type": SUPPLIER, "id": str(supplier.id), "code": supplier.supplier_code, "name": supplier.name,
            "status": supplier.status, "gstin": supplier.gstin, "phone": supplier.phone, "email": supplier.email,
            "address": supplier.address, "city": supplier.city, "state_code": supplier.state_code, "pincode": supplier.pincode,
            "credit_limit": None, "payment_terms_days": supplier.credit_terms_days,
        }

        inv_row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(PurchaseInvoice.grand_total), _ZERO),
                    func.coalesce(func.sum(PurchaseInvoice.grand_total - PurchaseInvoice.paid_amount), _ZERO),
                    func.count(PurchaseInvoice.id), func.max(PurchaseInvoice.document_date),
                ).where(PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.supplier_id == supplier_id, PurchaseInvoice.status == PINV_POSTED)
            )
        ).one()
        total_purchases, outstanding, invoice_count, last_invoice_date = inv_row

        paid = (
            await self._session.execute(
                select(func.coalesce(func.sum(Payment.amount), _ZERO)).where(
                    Payment.tenant_id == tenant_id, Payment.supplier_id == supplier_id,
                    Payment.party_type == PAYMENT_SUPPLIER, Payment.status == PAYMENT_POSTED,
                )
            )
        ).scalar_one()

        order_count = (
            await self._session.execute(
                select(func.count()).select_from(PurchaseOrder).where(
                    PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.supplier_id == supplier_id, PurchaseOrder.status != PO_CANCELLED,
                )
            )
        ).scalar_one()

        kpis = {
            "total_purchases": total_purchases, "outstanding": outstanding, "paid": paid,
            "invoice_count": invoice_count, "order_count": order_count,
            "last_transaction_date": last_invoice_date.isoformat() if last_invoice_date else None,
        }

        aging = await self._aging(tenant_id=tenant_id, invoice_model=PurchaseInvoice, party_field=PurchaseInvoice.supplier_id, party_id=supplier_id, posted_status=PINV_POSTED, payment_terms_days=None, due_date_field=PurchaseInvoice.due_date)

        top_products = await self._top_products(
            tenant_id=tenant_id, line_model=PurchaseInvoiceLine, invoice_model=PurchaseInvoice, invoice_fk=PurchaseInvoiceLine.purchase_invoice_id,
            party_field=PurchaseInvoice.supplier_id, party_id=supplier_id, posted_status=PINV_POSTED, date_field=PurchaseInvoice.document_date,
        )

        payment_history = await self._payment_history(tenant_id=tenant_id, party_type=PAYMENT_SUPPLIER, party_field=Payment.supplier_id, party_id=supplier_id)

        recent = await self._supplier_recent_transactions(tenant_id, supplier_id)

        return {"header": header, "kpis": kpis, "outstanding_aging": aging, "top_products": top_products, "payment_history": payment_history, "recent_transactions": recent}

    async def _supplier_recent_transactions(self, tenant_id: uuid.UUID, supplier_id: uuid.UUID) -> list[dict]:
        items: list[dict] = []

        rows = (await self._session.execute(
            select(PurchaseInvoice.purchase_invoice_number, PurchaseInvoice.document_date, PurchaseInvoice.grand_total, PurchaseInvoice.status, PurchaseInvoice.created_at)
            .where(PurchaseInvoice.tenant_id == tenant_id, PurchaseInvoice.supplier_id == supplier_id)
            .order_by(PurchaseInvoice.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, amount, status, created_at in rows:
            items.append({"type": "PURCHASE_INVOICE", "reference": number, "date": doc_date.isoformat(), "amount": amount, "status": status, "sort_key": created_at})

        rows = (await self._session.execute(
            select(PurchaseOrder.po_number, PurchaseOrder.document_date, PurchaseOrder.grand_total, PurchaseOrder.status, PurchaseOrder.created_at)
            .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.supplier_id == supplier_id)
            .order_by(PurchaseOrder.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, amount, status, created_at in rows:
            items.append({"type": "PURCHASE_ORDER", "reference": number, "date": doc_date.isoformat(), "amount": amount, "status": status, "sort_key": created_at})

        rows = (await self._session.execute(
            select(GoodsReceipt.grn_number, GoodsReceipt.document_date, GoodsReceipt.status, GoodsReceipt.created_at)
            .where(GoodsReceipt.tenant_id == tenant_id, GoodsReceipt.supplier_id == supplier_id)
            .order_by(GoodsReceipt.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, status, created_at in rows:
            items.append({"type": "GOODS_RECEIPT", "reference": number, "date": doc_date.isoformat(), "amount": None, "status": status, "sort_key": created_at})

        rows = (await self._session.execute(
            select(PurchaseReturn.purchase_return_number, PurchaseReturn.document_date, PurchaseReturn.grand_total, PurchaseReturn.status, PurchaseReturn.created_at)
            .where(PurchaseReturn.tenant_id == tenant_id, PurchaseReturn.supplier_id == supplier_id)
            .order_by(PurchaseReturn.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, amount, status, created_at in rows:
            items.append({"type": "PURCHASE_RETURN", "reference": number, "date": doc_date.isoformat(), "amount": amount, "status": status, "sort_key": created_at})

        rows = (await self._session.execute(
            select(Payment.payment_number, Payment.payment_date, Payment.amount, Payment.status, Payment.created_at)
            .where(Payment.tenant_id == tenant_id, Payment.supplier_id == supplier_id, Payment.party_type == PAYMENT_SUPPLIER)
            .order_by(Payment.created_at.desc()).limit(_RECENT_LIMIT)
        )).all()
        for number, doc_date, amount, status, created_at in rows:
            items.append({"type": "SUPPLIER_PAYMENT", "reference": number, "date": doc_date.isoformat(), "amount": amount, "status": status, "sort_key": created_at})

        items.sort(key=lambda i: i["sort_key"], reverse=True)
        for item in items:
            del item["sort_key"]
        return items[:_RECENT_LIMIT]

    # --- Shared helpers ---------------------------------------------------

    async def _aging(
        self, *, tenant_id: uuid.UUID, invoice_model, party_field, party_id: uuid.UUID, posted_status: str,
        payment_terms_days: int | None = None, due_date_field=None,
    ) -> dict:
        """Best-effort aging bucket, mirroring dashboard_service.py's own
        identical technique (and identical documented limitation: no
        approved overdue policy exists — see that module's docstring)."""
        conditions = [invoice_model.tenant_id == tenant_id, party_field == party_id, invoice_model.status == posted_status, invoice_model.payment_status != "PAID"]
        if due_date_field is not None:
            rows = (await self._session.execute(
                select(invoice_model.invoice_date if hasattr(invoice_model, "invoice_date") else invoice_model.document_date, due_date_field, invoice_model.grand_total - invoice_model.paid_amount).where(*conditions)
            )).all()
        else:
            rows = (await self._session.execute(
                select(invoice_model.invoice_date, invoice_model.grand_total - invoice_model.paid_amount).where(*conditions)
            )).all()

        today = date.today()
        aging = {bucket: _ZERO for bucket in _AGING_BUCKETS}
        for row in rows:
            if due_date_field is not None:
                doc_date, due_date, outstanding = row
                effective_due = due_date
            else:
                doc_date, outstanding = row
                effective_due = doc_date + timedelta(days=payment_terms_days) if payment_terms_days else None

            if effective_due:
                days_past_due = (today - effective_due).days
                if days_past_due <= 0:
                    aging["current"] += outstanding
                elif days_past_due <= 30:
                    aging["days_1_30"] += outstanding
                elif days_past_due <= 60:
                    aging["days_31_60"] += outstanding
                elif days_past_due <= 90:
                    aging["days_61_90"] += outstanding
                else:
                    aging["days_90_plus"] += outstanding
            else:
                aging["no_due_date"] += outstanding
        return aging

    async def _top_products(
        self, *, tenant_id: uuid.UUID, line_model, invoice_model, invoice_fk, party_field, party_id: uuid.UUID,
        posted_status: str, date_field,
    ) -> list[dict]:
        rows = (
            await self._session.execute(
                select(
                    line_model.product_id, Product.sku, Product.name,
                    func.coalesce(func.sum(line_model.quantity), _ZERO), func.coalesce(func.sum(line_model.taxable_amount), _ZERO),
                    func.max(date_field),
                )
                .select_from(line_model)
                .join(invoice_model, invoice_fk == invoice_model.id)
                .join(Product, Product.id == line_model.product_id)
                .where(invoice_model.tenant_id == tenant_id, party_field == party_id, invoice_model.status == posted_status, line_model.product_id.is_not(None))
                .group_by(line_model.product_id, Product.sku, Product.name)
                .order_by(func.sum(line_model.taxable_amount).desc())
                .limit(_TOP_N)
            )
        ).all()
        return [
            {"product_id": str(pid), "sku": sku, "product_name": name, "quantity": qty, "value": value, "last_transaction_date": last_date.isoformat() if last_date else None}
            for pid, sku, name, qty, value, last_date in rows
        ]

    async def _payment_history(self, *, tenant_id: uuid.UUID, party_type: str, party_field, party_id: uuid.UUID) -> list[dict]:
        rows = (
            await self._session.execute(
                select(Payment.payment_number, Payment.payment_date, Payment.amount, Payment.payment_method, Payment.allocated_amount, Payment.unallocated_amount, Payment.status)
                .where(Payment.tenant_id == tenant_id, party_field == party_id, Payment.party_type == party_type)
                .order_by(Payment.payment_date.desc()).limit(_RECENT_LIMIT)
            )
        ).all()
        return [
            {"reference": number, "date": pdate.isoformat(), "amount": amount, "method": method, "allocated_amount": allocated, "unallocated_amount": unallocated, "status": status}
            for number, pdate, amount, method, allocated, unallocated, status in rows
        ]
