import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AuditColumnsMixin, Base, RowVersionMixin, UUIDPKMixin

# §4: every payment belongs to exactly ONE party type — never both.
CUSTOMER = "CUSTOMER"
SUPPLIER = "SUPPLIER"
PARTY_TYPES = frozenset({CUSTOMER, SUPPLIER})

# §5: the four MVP payment methods — no gateway/card/wallet/POS integration.
CASH = "CASH"
UPI = "UPI"
BANK_TRANSFER = "BANK_TRANSFER"
CHEQUE = "CHEQUE"
PAYMENT_METHODS = frozenset({CASH, UPI, BANK_TRANSFER, CHEQUE})

# §7/§17: payment transaction status is distinct from cheque status.
DRAFT = "DRAFT"
POSTED = "POSTED"
REVERSED = "REVERSED"
PAYMENT_STATUSES = frozenset({DRAFT, POSTED, REVERSED})
CANCELLABLE_STATUSES = frozenset({DRAFT})
REVERSIBLE_STATUSES = frozenset({POSTED})

# §6/§7: cheque lifecycle — separate from payment status. Only meaningful
# when payment_method == CHEQUE.
PENDING = "PENDING"
CLEARED = "CLEARED"
BOUNCED = "BOUNCED"
CHEQUE_STATUSES = frozenset({PENDING, CLEARED, BOUNCED})


class Payment(UUIDPKMixin, Base, AuditColumnsMixin, RowVersionMixin):
    """Payment header (PROMPT-024) — a financial transaction representing
    money received from a customer (`party_type=CUSTOMER`) or paid to a
    supplier (`party_type=SUPPLIER`). §2's central rule: a Payment is
    NEVER the same record as its allocation — see `PaymentAllocation`.

    `customer_id`/`supplier_id` are mutually exclusive per `party_type`
    (§4, enforced by a DB CHECK constraint in migration 0025 AND
    re-validated in `PaymentService`, never trusted from the client
    alone).

    `allocated_amount`/`unallocated_amount` are reconciliation CACHE
    columns (same discipline as `product.stock_qty_cache`) — always
    recomputed from `payment_allocation` under the payment's own row
    lock at POST/REVERSE time, never edited directly.

    `client_transaction_id` (optional, unique per tenant when set) is a
    domain-level idempotency guard layered ON TOP OF the HTTP
    `Idempotency-Key` mechanism (mirrors PROMPT-018's own two-layer
    idempotency precedent) — a retried create with the same
    `client_transaction_id` returns the existing payment rather than
    erroring or creating a duplicate.

    Cheque fields (`cheque_number`/`cheque_date`/`cheque_bank_name`/
    `cheque_status`/`cleared_date`) are only meaningful when
    `payment_method == CHEQUE`; NULL otherwise. §19: a BOUNCED cheque
    forces the payment itself to `REVERSED` (reuses the reversal
    mechanism rather than inventing a parallel "exclude from outstanding"
    path) — see `PaymentService.mark_cheque_status`.

    `accounting_posting_reference`: opaque integration-boundary reference
    (§32), identical stub discipline to every prior document type's own
    column — not a foreign key, no real ledger table exists yet
    (PROMPT-025's own scope).
    """

    __tablename__ = "payment"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=False, index=True
    )
    payment_number: Mapped[str] = mapped_column(String(50), nullable=False)
    party_type: Mapped[str] = mapped_column(String(20), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("customer.id"), nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("supplier.id"), nullable=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=DRAFT)
    client_transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    cheque_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cheque_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cheque_bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cheque_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cleared_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    unallocated_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)

    accounting_posting_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
