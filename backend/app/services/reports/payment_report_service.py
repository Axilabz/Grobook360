"""Payment reports — Payment Register, Payment Method Summary, Cheque
Report (PROMPT-027 §30-§32).

Built on POSTED `payment` rows only (§44) — a DRAFT payment has zero
financial effect by construction (PROMPT-024's own rule, unchanged) and
never appears here. Date basis: `payment_date`.

Unlike `PaymentService.list_payments` (which is scoped to ONE
`party_type` at a time, matching its own Customer-Receipts/Supplier-
Payments-specific callers), this report's Payment Register covers BOTH
directions in one paginated result set (§30's own explicit "support
both" instruction) — party names are resolved with two batched
name-lookup queries rather than joining Customer/Supplier directly,
since `payment.customer_id`/`.supplier_id` are mutually-exclusive
nullable FKs that can't both be joined against the same row cleanly.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.customer import Customer
from app.models.payment import CUSTOMER, POSTED, Payment
from app.models.supplier import Supplier
from app.models.user import User

_ZERO = Decimal("0")


def _date_filters(column, date_from: date | None, date_to: date | None) -> list:
    conditions = []
    if date_from is not None:
        conditions.append(column >= date_from)
    if date_to is not None:
        conditions.append(column <= date_to)
    return conditions


class PaymentReportService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- Payment Register (§30) ------------------------------------------

    async def list_payments(
        self, *, tenant_id: uuid.UUID, page: int, page_size: int, date_from: date | None, date_to: date | None,
        party_type: str | None, payment_method: str | None,
    ) -> tuple[list[dict], int]:
        conditions = [Payment.tenant_id == tenant_id, Payment.status == POSTED, *_date_filters(Payment.payment_date, date_from, date_to)]
        if party_type:
            conditions.append(Payment.party_type == party_type)
        if payment_method:
            conditions.append(Payment.payment_method == payment_method)

        count_stmt = select(func.count()).select_from(select(Payment.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = select(Payment).where(*conditions).order_by(Payment.payment_date.desc(), Payment.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        payments = (await self._session.execute(paged)).scalars().all()

        customer_ids = {p.customer_id for p in payments if p.customer_id}
        supplier_ids = {p.supplier_id for p in payments if p.supplier_id}
        customer_names = dict((await self._session.execute(select(Customer.id, Customer.name).where(Customer.id.in_(customer_ids)))).all()) if customer_ids else {}
        supplier_names = dict((await self._session.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids)))).all()) if supplier_ids else {}

        items = []
        for p in payments:
            party_name = customer_names.get(p.customer_id) if p.party_type == CUSTOMER else supplier_names.get(p.supplier_id)
            items.append({
                "payment_id": str(p.id), "payment_number": p.payment_number, "payment_date": p.payment_date.isoformat(),
                "party_type": p.party_type, "party_name": party_name, "payment_method": p.payment_method, "amount": p.amount,
                "allocated_amount": p.allocated_amount, "unallocated_amount": p.unallocated_amount, "status": p.status,
                "reference_number": p.reference_number,
            })
        return items, total_items

    # --- Payment Method Summary (§31) ---------------------------------------

    async def get_payment_method_summary(self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None) -> list[dict]:
        conditions = [Payment.tenant_id == tenant_id, Payment.status == POSTED, *_date_filters(Payment.payment_date, date_from, date_to)]
        rows = (
            await self._session.execute(
                select(Payment.payment_method, func.count(Payment.id), func.coalesce(func.sum(Payment.amount), _ZERO))
                .where(*conditions).group_by(Payment.payment_method)
            )
        ).all()
        return [{"payment_method": method, "transaction_count": count, "amount": amount} for method, count, amount in rows]

    # --- Daily Collection Report (new) ------------------------------------
    # Customer-side collections only (money IN) — "collection" is
    # distinct from a Supplier Payment (money OUT), so this is always
    # party_type == CUSTOMER, grouped by payment_date, with the
    # collecting user resolved via the same created_by -> user.name
    # pattern used elsewhere in this codebase (e.g.
    # delivery_challan_service.get_challan).

    async def daily_collection_report(self, *, tenant_id: uuid.UUID, date_from: date | None, date_to: date | None) -> list[dict]:
        creator = aliased(User)
        conditions = [
            Payment.tenant_id == tenant_id, Payment.status == POSTED, Payment.party_type == CUSTOMER,
            *_date_filters(Payment.payment_date, date_from, date_to),
        ]
        rows = (
            await self._session.execute(
                select(Payment, Customer.name, creator.name)
                .join(Customer, Customer.id == Payment.customer_id)
                .outerjoin(creator, creator.id == Payment.created_by)
                .where(*conditions)
                .order_by(Payment.payment_date.asc(), Payment.created_at.asc())
            )
        ).all()

        days: dict[str, dict] = {}
        for payment, customer_name, collected_by_name in rows:
            day_key = payment.payment_date.isoformat()
            day = days.setdefault(day_key, {"date": payment.payment_date, "total_amount": _ZERO, "entry_count": 0, "entries": []})
            day["total_amount"] += payment.amount
            day["entry_count"] += 1
            day["entries"].append({
                "payment_id": str(payment.id), "payment_number": payment.payment_number, "customer_name": customer_name,
                "payment_method": payment.payment_method, "amount": payment.amount, "collected_by_name": collected_by_name,
            })
        return sorted(days.values(), key=lambda d: d["date"], reverse=True)

    # --- Cheque Report (§32) --------------------------------------------------

    async def list_cheques(self, *, tenant_id: uuid.UUID, page: int, page_size: int, cheque_status: str | None) -> tuple[list[dict], int]:
        from app.models.payment import CHEQUE

        conditions = [Payment.tenant_id == tenant_id, Payment.payment_method == CHEQUE, Payment.status == POSTED]
        if cheque_status:
            conditions.append(Payment.cheque_status == cheque_status)

        count_stmt = select(func.count()).select_from(select(Payment.id).where(*conditions).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = select(Payment).where(*conditions).order_by(Payment.cheque_date.desc().nullslast()).offset((page - 1) * page_size).limit(page_size)
        payments = (await self._session.execute(paged)).scalars().all()

        customer_ids = {p.customer_id for p in payments if p.customer_id}
        supplier_ids = {p.supplier_id for p in payments if p.supplier_id}
        customer_names = dict((await self._session.execute(select(Customer.id, Customer.name).where(Customer.id.in_(customer_ids)))).all()) if customer_ids else {}
        supplier_names = dict((await self._session.execute(select(Supplier.id, Supplier.name).where(Supplier.id.in_(supplier_ids)))).all()) if supplier_ids else {}

        items = []
        for p in payments:
            party_name = customer_names.get(p.customer_id) if p.party_type == CUSTOMER else supplier_names.get(p.supplier_id)
            items.append({
                "cheque_number": p.cheque_number, "payment_number": p.payment_number, "party_name": party_name, "amount": p.amount,
                "cheque_date": p.cheque_date.isoformat() if p.cheque_date else None, "bank": p.cheque_bank_name,
                "cheque_status": p.cheque_status, "cleared_date": p.cleared_date.isoformat() if p.cleared_date else None,
            })
        return items, total_items
