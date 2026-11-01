"""Payments & Collections service (PROMPT-024).

One service backs BOTH directions (Customer Receipt / Supplier Payment)
— §2's central rule (a Payment is never the same record as its
allocation) drives the whole design: `Payment`/`PaymentAllocation` are
two separate tables, and `sales_invoice.paid_amount`/`purchase_invoice.
paid_amount` are reconciliation CACHE columns, never a manually-editable
API field.

Mirrors the established "DRAFT is a soft/non-authoritative preview,
POST is the authoritative, row-locked recalculation" discipline used by
every prior document type in this codebase (Sales Invoice, Purchase
Invoice, Credit/Debit Note, Purchase Return, ...): `create_payment`
performs a convenience check against the invoice's CURRENTLY-cached
outstanding; `post_payment` re-validates against a FRESH aggregate
query under a row lock on every touched invoice (locked in sorted id
order — PROMPT-022's own deadlock-avoidance generalization), which is
what actually protects the mandatory concurrency invariant (§29/TC-020):
total allocation across concurrent payments can never exceed an
invoice's live outstanding.

Reversal (§17) is a status flip (POSTED -> REVERSED) on the SAME
Payment row — the amount/method/date/allocation fields are NEVER
edited, only `status` changes (mirrors every other document type's own
header-level cancel-with-reversal pattern; Payment does not yet have an
append-only ledger of its own to write a compensating entry against —
that arrives with PROMPT-025's Accounting Posting Matrix). Allocation
rows are never deleted on reversal — `_recalculate_invoice_payment_state`
only ever aggregates allocations whose PARENT payment is currently
POSTED, so a REVERSED payment's allocations simply stop counting.

A BOUNCED cheque (§19) reuses this exact reversal mechanism rather than
inventing a parallel "exclude from outstanding" path — see
`mark_cheque_status`.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.concurrency import check_row_version
from app.core.error_codes import (
    PAY_ALLOCATION_EXCEEDS_OUTSTANDING,
    PAY_ALLOCATION_EXCEEDS_PAYMENT,
    PAY_ALREADY_REVERSED,
    PAY_CHEQUE_ALREADY_BOUNCED,
    PAY_CHEQUE_DATA_INVALID,
    PAY_INVALID_STATUS,
    PAY_INVOICE_MISMATCH,
    PAY_NOT_CHEQUE_METHOD,
    PAY_NOT_FOUND,
    PAY_NOT_REVERSIBLE,
    PAY_VALIDATION,
)
from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.customer import Customer
from app.models.payment import (
    BOUNCED,
    CANCELLABLE_STATUSES,
    CHEQUE,
    CHEQUE_STATUSES,
    CLEARED,
    CUSTOMER,
    DRAFT,
    PARTY_TYPES,
    PAYMENT_METHODS,
    PENDING,
    POSTED,
    REVERSED,
    REVERSIBLE_STATUSES,
    SUPPLIER,
    Payment,
)
from app.models.payment_allocation import PaymentAllocation
from app.models.purchase_invoice import POSTED as PINV_POSTED
from app.models.purchase_invoice import PurchaseInvoice
from app.models.sales_invoice import POSTED as SI_POSTED
from app.models.sales_invoice import SalesInvoice
from app.models.supplier import Supplier
from app.models.user import User
from app.models.tenant import Tenant
from app.schemas.payments import AllocationLineInput
from app.services.accounting.accounting_posting_service import AccountingPostingService
from app.services.audit.audit_service import AuditService
from app.services.customers.customer_service import CustomerService
from app.services.sales.document_numbering_service import DocumentNumberingService
from app.services.suppliers.supplier_service import SupplierService

UNPAID = "UNPAID"
PARTIALLY_PAID = "PARTIALLY_PAID"
PAID = "PAID"

_NUMBERING = {
    CUSTOMER: ("CUSTOMER_RECEIPT", "REC"),
    SUPPLIER: ("SUPPLIER_PAYMENT", "PAY"),
}


@dataclass(frozen=True)
class PaymentPage:
    items: list[tuple[Payment, str, str | None, str | None]]  # (payment, party_name, created_by_name, updated_by_name)
    total_items: int


@dataclass(frozen=True)
class OutstandingInvoice:
    invoice_id: uuid.UUID
    invoice_number: str
    invoice_date: date
    invoice_total: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    payment_status: str


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- shared helpers -----------------------------------------------

    async def _get_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        result = await self._session.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one()

    async def _get_payment_locked(self, tenant_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
        result = await self._session.execute(
            select(Payment).where(Payment.id == payment_id, Payment.tenant_id == tenant_id).with_for_update()
        )
        payment = result.scalar_one_or_none()
        if payment is None:
            raise NotFoundError("Payment not found", code=PAY_NOT_FOUND)
        return payment

    async def _get_allocations(self, payment_id: uuid.UUID) -> list[PaymentAllocation]:
        result = await self._session.execute(
            select(PaymentAllocation).where(PaymentAllocation.payment_id == payment_id).order_by(PaymentAllocation.created_at)
        )
        return list(result.scalars().all())

    async def _party_name(self, payment: Payment) -> str:
        if payment.party_type == CUSTOMER:
            result = await self._session.execute(select(Customer.name).where(Customer.id == payment.customer_id))
        else:
            result = await self._session.execute(select(Supplier.name).where(Supplier.id == payment.supplier_id))
        return result.scalar_one()

    def _snapshot(self, payment: Payment) -> dict:
        return {
            "party_type": payment.party_type,
            "customer_id": str(payment.customer_id) if payment.customer_id else None,
            "supplier_id": str(payment.supplier_id) if payment.supplier_id else None,
            "payment_date": payment.payment_date.isoformat(),
            "payment_method": payment.payment_method,
            "amount": str(payment.amount),
            "status": payment.status,
            "cheque_status": payment.cheque_status,
        }

    @staticmethod
    def _validate_method(payment_method: str) -> None:
        if payment_method not in PAYMENT_METHODS:
            raise ValidationAppError(f"'{payment_method}' is not a recognized payment method.", code=PAY_VALIDATION)

    # --- outstanding-invoice lookups (§25) ------------------------------

    async def get_outstanding_invoices(
        self, *, tenant_id: uuid.UUID, party_type: str, party_id: uuid.UUID
    ) -> tuple[str, list[OutstandingInvoice]]:
        if party_type == CUSTOMER:
            customer = await CustomerService(self._session).get_customer(tenant_id=tenant_id, customer_id=party_id)
            result = await self._session.execute(
                select(SalesInvoice)
                .where(
                    SalesInvoice.tenant_id == tenant_id,
                    SalesInvoice.customer_id == party_id,
                    SalesInvoice.status == SI_POSTED,
                    SalesInvoice.payment_status != PAID,
                )
                .order_by(SalesInvoice.invoice_date.asc())
            )
            invoices = result.scalars().all()
            party_name = customer.name
        else:
            supplier = await SupplierService(self._session).get_supplier(tenant_id=tenant_id, supplier_id=party_id)
            result = await self._session.execute(
                select(PurchaseInvoice)
                .where(
                    PurchaseInvoice.tenant_id == tenant_id,
                    PurchaseInvoice.supplier_id == party_id,
                    PurchaseInvoice.status == PINV_POSTED,
                    PurchaseInvoice.payment_status != PAID,
                )
                .order_by(PurchaseInvoice.document_date.asc())
            )
            invoices = result.scalars().all()
            party_name = supplier.name

        items = [
            OutstandingInvoice(
                invoice_id=inv.id,
                invoice_number=inv.invoice_number if party_type == CUSTOMER else inv.purchase_invoice_number,
                invoice_date=inv.invoice_date if party_type == CUSTOMER else inv.document_date,
                invoice_total=inv.grand_total,
                paid_amount=inv.paid_amount,
                outstanding_amount=inv.grand_total - inv.paid_amount,
                payment_status=inv.payment_status,
            )
            for inv in invoices
        ]
        return party_name, items

    # --- per-invoice payment history (narrow, document-scoped read — same
    # convention as PROMPT-020/021/022/023's own related-documents/audit-
    # history endpoints: gated by the SOURCE document's own .view
    # permission, not a general payment-browsing API) ---------------------

    async def list_receipts_for_invoice(
        self, *, tenant_id: uuid.UUID, sales_invoice_id: uuid.UUID
    ) -> list[dict]:
        creator = aliased(User)
        rows = (
            await self._session.execute(
                select(Payment, PaymentAllocation.allocated_amount, creator.name)
                .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
                .outerjoin(creator, creator.id == Payment.created_by)
                .where(
                    Payment.tenant_id == tenant_id,
                    PaymentAllocation.sales_invoice_id == sales_invoice_id,
                )
                .order_by(Payment.payment_date.desc(), Payment.created_at.desc())
            )
        ).all()
        return [
            {
                "payment_id": str(payment.id),
                "payment_number": payment.payment_number,
                "payment_date": payment.payment_date.isoformat(),
                "amount": allocated_amount,
                "payment_method": payment.payment_method,
                "status": payment.status,
                "collected_by_name": creator_name,
            }
            for payment, allocated_amount, creator_name in rows
        ]

    # --- queries ---------------------------------------------------------

    async def list_payments(
        self, *, tenant_id: uuid.UUID, party_type: str, page: int, page_size: int, search: str | None,
        status_filter: str | None, party_id: uuid.UUID | None, payment_method_filter: str | None,
        date_from: date | None, date_to: date | None,
    ) -> PaymentPage:
        creator = aliased(User)
        updater = aliased(User)
        if party_type == CUSTOMER:
            base = (
                select(Payment, Customer.name, creator.name, updater.name)
                .join(Customer, Customer.id == Payment.customer_id)
                .outerjoin(creator, creator.id == Payment.created_by)
                .outerjoin(updater, updater.id == Payment.updated_by)
                .where(Payment.tenant_id == tenant_id, Payment.party_type == CUSTOMER)
            )
            if search:
                like = f"%{search}%"
                base = base.where(or_(Payment.payment_number.ilike(like), Payment.reference_number.ilike(like), Customer.name.ilike(like)))
        else:
            base = (
                select(Payment, Supplier.name, creator.name, updater.name)
                .join(Supplier, Supplier.id == Payment.supplier_id)
                .outerjoin(creator, creator.id == Payment.created_by)
                .outerjoin(updater, updater.id == Payment.updated_by)
                .where(Payment.tenant_id == tenant_id, Payment.party_type == SUPPLIER)
            )
            if search:
                like = f"%{search}%"
                base = base.where(or_(Payment.payment_number.ilike(like), Payment.reference_number.ilike(like), Supplier.name.ilike(like)))

        if status_filter:
            base = base.where(Payment.status == status_filter)
        if party_id:
            base = base.where(Payment.customer_id == party_id if party_type == CUSTOMER else Payment.supplier_id == party_id)
        if payment_method_filter:
            base = base.where(Payment.payment_method == payment_method_filter)
        if date_from:
            base = base.where(Payment.payment_date >= date_from)
        if date_to:
            base = base.where(Payment.payment_date <= date_to)

        count_stmt = select(func.count()).select_from(base.with_only_columns(Payment.id).subquery())
        total_items = (await self._session.execute(count_stmt)).scalar_one()

        paged = base.order_by(Payment.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        rows = (await self._session.execute(paged)).all()
        return PaymentPage(items=[(row[0], row[1], row[2], row[3]) for row in rows], total_items=total_items)

    async def get_payment(
        self, *, tenant_id: uuid.UUID, payment_id: uuid.UUID
    ) -> tuple[Payment, str, str | None, str | None, list[PaymentAllocation]]:
        result = await self._session.execute(select(Payment).where(Payment.id == payment_id, Payment.tenant_id == tenant_id))
        payment = result.scalar_one_or_none()
        if payment is None:
            raise NotFoundError("Payment not found", code=PAY_NOT_FOUND)
        party_name = await self._party_name(payment)
        allocations = await self._get_allocations(payment.id)
        created_by_name, updated_by_name = await self.get_creator_names(payment)
        return payment, party_name, created_by_name, updated_by_name, allocations

    async def get_creator_names(self, payment: Payment) -> tuple[str | None, str | None]:
        user_ids = [uid for uid in {payment.created_by, payment.updated_by} if uid is not None]
        if not user_ids:
            return None, None
        result = await self._session.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        names = dict(result.all())
        return names.get(payment.created_by), names.get(payment.updated_by)

    async def get_payment_by_client_transaction_id(
        self, *, tenant_id: uuid.UUID, client_transaction_id: str
    ) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.tenant_id == tenant_id, Payment.client_transaction_id == client_transaction_id)
        )
        return result.scalar_one_or_none()

    # --- allocation validation helpers -----------------------------------

    async def _validate_allocation_target(
        self, *, tenant_id: uuid.UUID, party_type: str, invoice_id: uuid.UUID
    ) -> tuple[SalesInvoice | PurchaseInvoice, bool]:
        """§4/§12: a Customer Receipt may only allocate a Sales Invoice
        belonging to THIS payment's own customer; a Supplier Payment may
        only allocate a Purchase Invoice belonging to THIS payment's own
        supplier. Returns (invoice, is_sales)."""
        if party_type == CUSTOMER:
            result = await self._session.execute(
                select(SalesInvoice).where(SalesInvoice.id == invoice_id, SalesInvoice.tenant_id == tenant_id)
            )
            invoice = result.scalar_one_or_none()
            if invoice is None:
                raise NotFoundError("Sales invoice not found", code=PAY_NOT_FOUND)
            if invoice.status != SI_POSTED:
                raise ValidationAppError(f"An invoice in {invoice.status} status is not eligible for payment allocation.", code=PAY_INVOICE_MISMATCH)
            return invoice, True
        else:
            result = await self._session.execute(
                select(PurchaseInvoice).where(PurchaseInvoice.id == invoice_id, PurchaseInvoice.tenant_id == tenant_id)
            )
            invoice = result.scalar_one_or_none()
            if invoice is None:
                raise NotFoundError("Purchase invoice not found", code=PAY_NOT_FOUND)
            if invoice.status != PINV_POSTED:
                raise ValidationAppError(f"An invoice in {invoice.status} status is not eligible for payment allocation.", code=PAY_INVOICE_MISMATCH)
            return invoice, False

    def _validate_cheque_inputs(
        self, *, payment_method: str, cheque_number: str | None, cheque_date: date | None
    ) -> None:
        if payment_method == CHEQUE and (not cheque_number or not cheque_date):
            raise ValidationAppError("Cheque number and cheque date are required for a CHEQUE payment.", code=PAY_CHEQUE_DATA_INVALID)

    # --- create (DRAFT only) ------------------------------------------------

    async def create_payment(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, party_type: str, customer_id: uuid.UUID | None,
        supplier_id: uuid.UUID | None, payment_date: date | None, payment_method: str, amount: Decimal,
        reference_number: str | None, notes: str | None, client_transaction_id: str | None,
        cheque_number: str | None, cheque_date: date | None, cheque_bank_name: str | None,
        allocation_inputs: list[AllocationLineInput], ip_address: str | None,
    ) -> tuple[Payment, str, list[PaymentAllocation]]:
        if party_type not in PARTY_TYPES:
            raise ValidationAppError(f"'{party_type}' is not a recognized party type.", code=PAY_VALIDATION)
        self._validate_method(payment_method)
        self._validate_cheque_inputs(payment_method=payment_method, cheque_number=cheque_number, cheque_date=cheque_date)

        # §30 domain-level idempotency layer: a retried create with the
        # same client_transaction_id returns the EXISTING payment.
        if client_transaction_id:
            existing = await self.get_payment_by_client_transaction_id(tenant_id=tenant_id, client_transaction_id=client_transaction_id)
            if existing is not None:
                party_name = await self._party_name(existing)
                allocations = await self._get_allocations(existing.id)
                return existing, party_name, allocations

        if party_type == CUSTOMER:
            customer = await CustomerService(self._session).get_customer(tenant_id=tenant_id, customer_id=customer_id)
            party_name = customer.name
        else:
            supplier = await SupplierService(self._session).get_supplier(tenant_id=tenant_id, supplier_id=supplier_id)
            party_name = supplier.name

        tenant = await self._get_tenant(tenant_id)
        doc_date = payment_date or date.today()

        document_type, prefix = _NUMBERING[party_type]
        numbering = DocumentNumberingService(self._session)
        payment_number = await numbering.next_number(tenant=tenant, document_type=document_type, prefix=prefix)

        payment = Payment(
            tenant_id=tenant_id, payment_number=payment_number, party_type=party_type,
            customer_id=customer_id if party_type == CUSTOMER else None,
            supplier_id=supplier_id if party_type == SUPPLIER else None,
            payment_date=doc_date, payment_method=payment_method, amount=amount,
            reference_number=reference_number, notes=notes, status=DRAFT,
            client_transaction_id=client_transaction_id,
            cheque_number=cheque_number if payment_method == CHEQUE else None,
            cheque_date=cheque_date if payment_method == CHEQUE else None,
            cheque_bank_name=cheque_bank_name if payment_method == CHEQUE else None,
            cheque_status=PENDING if payment_method == CHEQUE else None,
            allocated_amount=Decimal("0"), unallocated_amount=amount,
            created_by=actor_user_id, updated_by=actor_user_id,
        )
        self._session.add(payment)
        await self._session.flush()

        allocations = await self._build_allocations(
            tenant_id=tenant_id, actor_user_id=actor_user_id, payment=payment, allocation_inputs=allocation_inputs,
        )

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PAYMENT_CREATED",
            entity_type="payment", entity_id=payment.id, after=self._snapshot(payment), ip_address=ip_address,
        )

        return payment, party_name, allocations

    async def _build_allocations(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payment: Payment, allocation_inputs: list[AllocationLineInput],
    ) -> list[PaymentAllocation]:
        """§12/§27 soft, DRAFT-time convenience validation only — the
        authoritative, race-proof re-validation happens again in
        `post_payment` under a lock on every touched invoice."""
        total_allocated = Decimal("0")
        allocations: list[PaymentAllocation] = []

        for line in allocation_inputs:
            invoice_id = uuid.UUID(line.invoice_id)
            invoice, is_sales = await self._validate_allocation_target(tenant_id=tenant_id, party_type=payment.party_type, invoice_id=invoice_id)

            outstanding = invoice.grand_total - invoice.paid_amount
            if line.allocated_amount > outstanding:
                raise ValidationAppError(
                    f"Allocation amount {line.allocated_amount} exceeds invoice outstanding amount {outstanding}.",
                    code=PAY_ALLOCATION_EXCEEDS_OUTSTANDING,
                )
            total_allocated += line.allocated_amount

            allocations.append(
                PaymentAllocation(
                    tenant_id=tenant_id, payment_id=payment.id,
                    sales_invoice_id=invoice.id if is_sales else None,
                    purchase_invoice_id=None if is_sales else invoice.id,
                    allocated_amount=line.allocated_amount,
                    created_by=actor_user_id, updated_by=actor_user_id,
                )
            )

        if total_allocated > payment.amount:
            raise ValidationAppError(
                f"Total allocation {total_allocated} exceeds payment amount {payment.amount}.",
                code=PAY_ALLOCATION_EXCEEDS_PAYMENT,
            )

        for allocation in allocations:
            self._session.add(allocation)

        payment.allocated_amount = total_allocated
        payment.unallocated_amount = payment.amount - total_allocated
        await self._session.flush()
        return allocations

    # --- update (DRAFT only) ------------------------------------------------

    async def update_payment(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payment_id: uuid.UUID, expected_row_version: int,
        payment_date: date | None, payment_method: str | None, amount: Decimal | None, reference_number: str | None,
        notes: str | None, cheque_number: str | None, cheque_date: date | None, cheque_bank_name: str | None,
        allocation_inputs: list[AllocationLineInput] | None, ip_address: str | None,
    ) -> tuple[Payment, str, list[PaymentAllocation]]:
        payment = await self._get_payment_locked(tenant_id, payment_id)
        check_row_version(payment, expected_row_version)

        if payment.status != DRAFT:
            raise ValidationAppError("This payment has already been posted and cannot be edited.", code=PAY_INVALID_STATUS)

        before = self._snapshot(payment)

        effective_method = payment_method or payment.payment_method
        if payment_method is not None:
            self._validate_method(payment_method)
            payment.payment_method = payment_method
        if amount is not None:
            payment.amount = amount
        if payment_date is not None:
            payment.payment_date = payment_date
        if reference_number is not None:
            payment.reference_number = reference_number
        if notes is not None:
            payment.notes = notes

        if effective_method == CHEQUE:
            effective_cheque_number = cheque_number if cheque_number is not None else payment.cheque_number
            effective_cheque_date = cheque_date if cheque_date is not None else payment.cheque_date
            self._validate_cheque_inputs(payment_method=CHEQUE, cheque_number=effective_cheque_number, cheque_date=effective_cheque_date)
            payment.cheque_number = effective_cheque_number
            payment.cheque_date = effective_cheque_date
            if cheque_bank_name is not None:
                payment.cheque_bank_name = cheque_bank_name
            if payment.cheque_status is None:
                payment.cheque_status = PENDING
        else:
            payment.cheque_number = None
            payment.cheque_date = None
            payment.cheque_bank_name = None
            payment.cheque_status = None

        if allocation_inputs is not None:
            existing = await self._get_allocations(payment.id)
            for allocation in existing:
                await self._session.delete(allocation)
            await self._session.flush()
            await self._build_allocations(tenant_id=tenant_id, actor_user_id=actor_user_id, payment=payment, allocation_inputs=allocation_inputs)
        elif amount is not None:
            # Amount changed but allocations weren't resubmitted — keep
            # the existing allocation total, just recompute unallocated.
            if payment.allocated_amount > payment.amount:
                raise ValidationAppError(
                    f"Total allocation {payment.allocated_amount} exceeds payment amount {payment.amount}.",
                    code=PAY_ALLOCATION_EXCEEDS_PAYMENT,
                )
            payment.unallocated_amount = payment.amount - payment.allocated_amount

        payment.updated_by = actor_user_id
        payment.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PAYMENT_UPDATED",
            entity_type="payment", entity_id=payment.id, before=before, after=self._snapshot(payment), ip_address=ip_address,
        )

        party_name = await self._party_name(payment)
        allocations = await self._get_allocations(payment.id)
        return payment, party_name, allocations

    # --- recalculation (shared by post/reverse) -----------------------------

    async def _recalculate_invoice_payment_state(self, *, invoice: SalesInvoice | PurchaseInvoice, is_sales: bool, actor_user_id: uuid.UUID) -> None:
        """§15/§16: recomputes `paid_amount`/`payment_status` from the
        AUTHORITATIVE source — SUM(payment_allocation.allocated_amount)
        across every currently-POSTED Payment — never trusting the cache
        alone. Must be called while the invoice row is already locked."""
        column = PaymentAllocation.sales_invoice_id if is_sales else PaymentAllocation.purchase_invoice_id
        result = await self._session.execute(
            select(func.coalesce(func.sum(PaymentAllocation.allocated_amount), 0))
            .select_from(PaymentAllocation)
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(column == invoice.id, Payment.status == POSTED)
        )
        paid_amount = result.scalar_one()

        invoice.paid_amount = paid_amount
        if paid_amount <= 0:
            invoice.payment_status = UNPAID
        elif paid_amount >= invoice.grand_total:
            invoice.payment_status = PAID
        else:
            invoice.payment_status = PARTIALLY_PAID
        invoice.updated_by = actor_user_id

    # --- post (§28: the atomic allocation + outstanding-update core) -------

    async def post_payment(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payment_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
    ) -> tuple[Payment, str, list[PaymentAllocation]]:
        payment = await self._get_payment_locked(tenant_id, payment_id)
        check_row_version(payment, expected_row_version)

        if payment.status != DRAFT:
            raise ValidationAppError(f"Cannot post a payment in {payment.status} status.", code=PAY_INVALID_STATUS)

        allocations = await self._get_allocations(payment.id)

        # §29: lock every DISTINCT invoice this payment's allocations
        # reference, in SORTED order, to avoid a lock-ordering deadlock
        # against a concurrently-posting payment referencing an
        # overlapping set of invoices in a different order (PROMPT-022's
        # own generalization of this exact pattern).
        sales_ids = sorted({str(a.sales_invoice_id) for a in allocations if a.sales_invoice_id})
        purchase_ids = sorted({str(a.purchase_invoice_id) for a in allocations if a.purchase_invoice_id})

        locked_sales: dict[uuid.UUID, SalesInvoice] = {}
        for sid in sales_ids:
            result = await self._session.execute(select(SalesInvoice).where(SalesInvoice.id == uuid.UUID(sid)).with_for_update())
            invoice = result.scalar_one()
            locked_sales[invoice.id] = invoice

        locked_purchase: dict[uuid.UUID, PurchaseInvoice] = {}
        for pid in purchase_ids:
            result = await self._session.execute(select(PurchaseInvoice).where(PurchaseInvoice.id == uuid.UUID(pid)).with_for_update())
            invoice = result.scalar_one()
            locked_purchase[invoice.id] = invoice

        total_allocated = Decimal("0")
        for allocation in allocations:
            if allocation.sales_invoice_id:
                invoice = locked_sales[allocation.sales_invoice_id]
            else:
                invoice = locked_purchase[allocation.purchase_invoice_id]

            live_outstanding = invoice.grand_total - invoice.paid_amount
            if allocation.allocated_amount > live_outstanding:
                raise ValidationAppError(
                    f"Allocation amount {allocation.allocated_amount} exceeds invoice outstanding amount {live_outstanding}.",
                    code=PAY_ALLOCATION_EXCEEDS_OUTSTANDING,
                )
            total_allocated += allocation.allocated_amount

        if total_allocated > payment.amount:
            raise ValidationAppError(
                f"Total allocation {total_allocated} exceeds payment amount {payment.amount}.",
                code=PAY_ALLOCATION_EXCEEDS_PAYMENT,
            )

        previous_status = payment.status
        payment.status = POSTED
        payment.allocated_amount = total_allocated
        payment.unallocated_amount = payment.amount - total_allocated
        await self._session.flush()

        for invoice in locked_sales.values():
            await self._recalculate_invoice_payment_state(invoice=invoice, is_sales=True, actor_user_id=actor_user_id)
        for invoice in locked_purchase.values():
            await self._recalculate_invoice_payment_state(invoice=invoice, is_sales=False, actor_user_id=actor_user_id)

        accounting_reference = await AccountingPostingService(self._session).post_payment(
            tenant_id=tenant_id, actor_user_id=actor_user_id, payment=payment, ip_address=ip_address,
        )
        payment.accounting_posting_reference = accounting_reference
        payment.updated_by = actor_user_id
        payment.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PAYMENT_POSTED",
            entity_type="payment", entity_id=payment.id, before={"status": previous_status},
            after={"status": POSTED, "allocated_amount": str(total_allocated), "accounting_posting_reference": accounting_reference},
            ip_address=ip_address,
        )

        party_name = await self._party_name(payment)
        return payment, party_name, allocations

    # --- reverse (§17: status flip, original row immutable otherwise) ------

    async def reverse_payment(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payment_id: uuid.UUID, expected_row_version: int, ip_address: str | None,
        audit_action: str = "PAYMENT_REVERSED",
    ) -> tuple[Payment, str, list[PaymentAllocation]]:
        payment = await self._get_payment_locked(tenant_id, payment_id)
        check_row_version(payment, expected_row_version)

        if payment.status not in REVERSIBLE_STATUSES:
            if payment.status == REVERSED:
                raise ValidationAppError("This payment has already been reversed.", code=PAY_ALREADY_REVERSED)
            raise ValidationAppError(f"Cannot reverse a payment in {payment.status} status.", code=PAY_NOT_REVERSIBLE)

        allocations = await self._get_allocations(payment.id)
        sales_ids = sorted({str(a.sales_invoice_id) for a in allocations if a.sales_invoice_id})
        purchase_ids = sorted({str(a.purchase_invoice_id) for a in allocations if a.purchase_invoice_id})

        previous_status = payment.status
        payment.status = REVERSED
        payment.updated_by = actor_user_id
        payment.row_version += 1
        await self._session.flush()

        for sid in sales_ids:
            result = await self._session.execute(select(SalesInvoice).where(SalesInvoice.id == uuid.UUID(sid)).with_for_update())
            await self._recalculate_invoice_payment_state(invoice=result.scalar_one(), is_sales=True, actor_user_id=actor_user_id)
        for pid in purchase_ids:
            result = await self._session.execute(select(PurchaseInvoice).where(PurchaseInvoice.id == uuid.UUID(pid)).with_for_update())
            await self._recalculate_invoice_payment_state(invoice=result.scalar_one(), is_sales=False, actor_user_id=actor_user_id)

        # PROMPT-025 §33/§34: reverses the ORIGINAL payment's own journal
        # via a new REVERSAL journal — never edits it. Returns None (a
        # safe no-op) if no journal exists for this payment, which should
        # not happen in practice but must never block the payment's own
        # reversal from proceeding.
        accounting_reference = await AccountingPostingService(self._session).reverse_payment(
            tenant_id=tenant_id, actor_user_id=actor_user_id, payment=payment, ip_address=ip_address,
        )

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action=audit_action,
            entity_type="payment", entity_id=payment.id, before={"status": previous_status},
            after={"status": REVERSED, "accounting_reversal_reference": accounting_reference}, ip_address=ip_address,
        )

        party_name = await self._party_name(payment)
        return payment, party_name, allocations

    # --- cheque lifecycle (§6/§7/§19) ---------------------------------------

    async def mark_cheque_status(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payment_id: uuid.UUID, expected_row_version: int,
        cheque_status: str, cleared_date: date | None, ip_address: str | None,
    ) -> tuple[Payment, str, list[PaymentAllocation]]:
        if cheque_status not in CHEQUE_STATUSES:
            raise ValidationAppError(f"'{cheque_status}' is not a recognized cheque status.", code=PAY_CHEQUE_DATA_INVALID)

        payment = await self._get_payment_locked(tenant_id, payment_id)
        check_row_version(payment, expected_row_version)

        if payment.payment_method != CHEQUE:
            raise ValidationAppError("This payment is not a cheque payment.", code=PAY_NOT_CHEQUE_METHOD)
        if payment.cheque_status == BOUNCED:
            raise ValidationAppError("This cheque has already bounced.", code=PAY_CHEQUE_ALREADY_BOUNCED)

        if cheque_status == BOUNCED:
            # §19: a bounced cheque must not continue to reduce
            # outstanding as if settled — reuse the reversal mechanism
            # rather than a parallel exclusion path.
            payment.cheque_status = BOUNCED
            await self._session.flush()
            return await self.reverse_payment(
                tenant_id=tenant_id, actor_user_id=actor_user_id, payment_id=payment_id,
                expected_row_version=payment.row_version, ip_address=ip_address, audit_action="PAYMENT_CHEQUE_BOUNCED",
            )

        before = self._snapshot(payment)
        payment.cheque_status = cheque_status
        if cheque_status == CLEARED:
            payment.cleared_date = cleared_date or date.today()
        payment.updated_by = actor_user_id
        payment.row_version += 1
        await self._session.flush()

        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="PAYMENT_CHEQUE_STATUS_CHANGED",
            entity_type="payment", entity_id=payment.id, before=before, after=self._snapshot(payment), ip_address=ip_address,
        )

        party_name = await self._party_name(payment)
        allocations = await self._get_allocations(payment.id)
        return payment, party_name, allocations
