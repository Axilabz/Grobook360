"""Accounting Posting Matrix (PROMPT-025) — the CONCRETE posting rules
for every supported business transaction, built on top of
`JournalService`'s generic double-entry engine.

Every method here does exactly two things: (1) build the list of
`JournalLineInput`s from the source document's OWN already-calculated
authoritative totals (never recomputing GST — §12/§41), and (2) hand
them to `JournalService.post_journal`/`reverse_journal_for_source`. No
account id is ever hard-coded — every line names a `posting_rule_code`
(see `app.core.accounting_constants`), resolved dynamically per tenant
by `ChartOfAccountsService` (§10).

This file used to be a stub (PROMPT-015 through PROMPT-024) that only
wrote a JSON "conceptual entries" blob to the audit log. It now creates
REAL, balanced `journal_entry`/`journal_line` rows — but every existing
call site (`sales_invoice_service.py`, `sales_return_service.py`,
`credit_debit_note_service.py`, `payment_service.py`) is unchanged: same
method names, same parameters, same `-> str` return (now the real
`journal_number` instead of an opaque `ACCPOST-<id>` string).

No COGS/Inventory leg is ever posted for the Sales/Purchase document
chains (§56 OD-005/OD-006/OD-007/OD-024 — that policy stays unapproved;
"Purchase Expense" is still a deliberately generic placeholder for the
purchase-side debit, not "Inventory" — OD-004/OD-010 stay open). No
Goods Receipt journal exists (OD-008/OD-009/OD-025 — GR/IR clearing
policy not approved).

**Manual Stock Movements ARE posted** (Opening Stock / Stock In / Stock
Out / Adjustment, via `InventoryService`'s 4 public entry points) — a
narrower, separate decision: those 4 actions value stock at Weighted
Average Cost (`Product.cost_price`, maintained by `InventoryService`
itself, never recomputed here) and post to the new `INVENTORY`/
`OPENING_BALANCE_EQUITY`/`STOCK_ADJUSTMENT` accounts. This does NOT
reopen OD-004/OD-005/OD-006/OD-007/OD-010 above — Sales/Purchase
document posting is completely untouched; only genuinely manual
quantity-and-cost entries get a journal, and only when a cost is
actually known (never a fabricated/zero-value journal — see the
`amount <= 0: return None` guard on each of the 3 methods below).
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.accounting_constants import (
    ACCOUNTS_PAYABLE,
    ACCOUNTS_RECEIVABLE,
    BANK_ACCOUNT,
    CASH_ACCOUNT,
    CHEQUE_ACCOUNT,
    INPUT_CGST,
    INPUT_IGST,
    INPUT_SGST,
    INVENTORY,
    OPENING_BALANCE_EQUITY,
    OUTPUT_CGST,
    OUTPUT_IGST,
    OUTPUT_SGST,
    PURCHASE_EXPENSE,
    PURCHASE_RETURN_ADJUSTMENT,
    SALARY_DEDUCTIONS_PAYABLE,
    SALARY_EXPENSE,
    SALARY_PAYABLE,
    SALES_RETURN_ADJUSTMENT,
    SALES_REVENUE,
    SRC_CREDIT_NOTE,
    SRC_CUSTOMER_RECEIPT,
    SRC_DEBIT_NOTE,
    SRC_MANUAL_STOCK_IN,
    SRC_MANUAL_STOCK_OUT,
    SRC_OPENING_STOCK,
    SRC_PAYROLL_RUN,
    SRC_PURCHASE_INVOICE,
    SRC_PURCHASE_RETURN,
    SRC_SALES_INVOICE,
    SRC_SALES_RETURN,
    SRC_STOCK_ADJUSTMENT,
    SRC_SUPPLIER_PAYMENT,
    STOCK_ADJUSTMENT,
    UPI_ACCOUNT,
)
from app.models.credit_debit_note import CREDIT_NOTE, CreditDebitNote
from app.models.payment import BANK_TRANSFER, CASH, CHEQUE, CUSTOMER, UPI, Payment
from app.models.purchase_invoice import PurchaseInvoice
from app.models.purchase_return import PurchaseReturn
from app.models.sales_invoice import SalesInvoice
from app.models.sales_return import SalesReturn
from app.services.accounting.journal_service import JournalLineInput, JournalService
from app.services.audit.audit_service import AuditService

_PAYMENT_METHOD_ACCOUNT = {
    CASH: CASH_ACCOUNT,
    BANK_TRANSFER: BANK_ACCOUNT,
    UPI: UPI_ACCOUNT,
    CHEQUE: CHEQUE_ACCOUNT,
}

# §49/AC-025 traceability: JournalService's own audit entry is scoped to the
# journal_entry itself (entity_type="journal_entry"), which is correct for the
# ledger's own audit trail but is NOT what every source document's own
# audit-history view (GET .../audit-history, PROMPT-020 precedent) reads —
# those are scoped to the SOURCE entity's own id. This mirrors the pre-
# PROMPT-025 stub's behavior (which wrote "ACCOUNTING_POSTED" directly under
# the source entity) so that trail isn't lost now that real posting exists.
_SOURCE_ENTITY_TYPE = {
    SRC_SALES_INVOICE: "sales_invoice",
    SRC_SALES_RETURN: "sales_return",
    SRC_CREDIT_NOTE: "credit_debit_note",
    SRC_DEBIT_NOTE: "credit_debit_note",
    SRC_PURCHASE_INVOICE: "purchase_invoice",
    SRC_PURCHASE_RETURN: "purchase_return",
    SRC_CUSTOMER_RECEIPT: "payment",
    SRC_SUPPLIER_PAYMENT: "payment",
    SRC_PAYROLL_RUN: "payroll_run",
    SRC_OPENING_STOCK: "stock_ledger_entry",
    SRC_MANUAL_STOCK_IN: "stock_ledger_entry",
    SRC_MANUAL_STOCK_OUT: "stock_ledger_entry",
    SRC_STOCK_ADJUSTMENT: "stock_ledger_entry",
}


def _gst_lines(*, cgst: Decimal, sgst: Decimal, igst: Decimal, output: bool) -> list[JournalLineInput]:
    """§12/§15: builds the CGST/SGST/IGST leg(s) for either the
    output-GST (sales-side, credit) or input-GST (purchase-side, debit)
    direction — only the components the source document actually
    carries (an intra-state document has no igst_total; an inter-state
    one has no cgst/sgst_total, per the existing GST calculation
    service's own mutually-exclusive design)."""
    cgst_code, sgst_code, igst_code = (OUTPUT_CGST, OUTPUT_SGST, OUTPUT_IGST) if output else (INPUT_CGST, INPUT_SGST, INPUT_IGST)
    lines: list[JournalLineInput] = []
    if cgst:
        lines.append(JournalLineInput(posting_rule_code=cgst_code, credit=cgst if output else Decimal("0"), debit=cgst if not output else Decimal("0")))
    if sgst:
        lines.append(JournalLineInput(posting_rule_code=sgst_code, credit=sgst if output else Decimal("0"), debit=sgst if not output else Decimal("0")))
    if igst:
        lines.append(JournalLineInput(posting_rule_code=igst_code, credit=igst if output else Decimal("0"), debit=igst if not output else Decimal("0")))
    return lines


class AccountingPostingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._journals = JournalService(session)

    async def _record_posted_audit(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_type: str, source_id: uuid.UUID,
        journal_number: str, ip_address: str | None,
    ) -> None:
        await AuditService(self._session).record(
            tenant_id=tenant_id, actor_user_id=actor_user_id, action="ACCOUNTING_POSTED",
            entity_type=_SOURCE_ENTITY_TYPE[source_type], entity_id=source_id,
            after={"journal_number": journal_number, "source_type": source_type},
            ip_address=ip_address,
        )

    # --- Sales Invoice (PROMPT-015 §21) -------------------------------------

    async def post_sales_invoice(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice: SalesInvoice, ip_address: str | None,
    ) -> str:
        """§11/§12: DR Accounts Receivable (grand_total) / CR Sales
        Revenue (taxable_total) + Output CGST/SGST/IGST. The invoice's
        own authoritative totals are used verbatim — never recalculated."""
        lines = [
            JournalLineInput(posting_rule_code=ACCOUNTS_RECEIVABLE, debit=invoice.grand_total),
            JournalLineInput(posting_rule_code=SALES_REVENUE, credit=invoice.taxable_total),
            *_gst_lines(cgst=invoice.cgst_total, sgst=invoice.sgst_total, igst=invoice.igst_total, output=True),
        ]
        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_SALES_INVOICE, source_id=invoice.id,
            source_number=invoice.invoice_number, journal_date=invoice.invoice_date,
            description=f"Sales Invoice {invoice.invoice_number}", lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_SALES_INVOICE, source_id=invoice.id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    # --- Sales Return (PROMPT-016 §21) --------------------------------------

    async def post_sales_return(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, sales_return: SalesReturn, ip_address: str | None,
    ) -> str:
        """§18: mirror image of the Sales Invoice entry — DR Sales
        Return/Revenue Adjustment + Output GST reversal (debiting the
        SAME output-GST accounts the original invoice credited), CR
        Accounts Receivable. This is NOT a Credit Note (§20 explicit
        boundary)."""
        gst_debit_lines = []
        if sales_return.cgst_total:
            gst_debit_lines.append(JournalLineInput(posting_rule_code=OUTPUT_CGST, debit=sales_return.cgst_total))
        if sales_return.sgst_total:
            gst_debit_lines.append(JournalLineInput(posting_rule_code=OUTPUT_SGST, debit=sales_return.sgst_total))
        if sales_return.igst_total:
            gst_debit_lines.append(JournalLineInput(posting_rule_code=OUTPUT_IGST, debit=sales_return.igst_total))
        lines = [
            JournalLineInput(posting_rule_code=SALES_RETURN_ADJUSTMENT, debit=sales_return.taxable_total),
            *gst_debit_lines,
            JournalLineInput(posting_rule_code=ACCOUNTS_RECEIVABLE, credit=sales_return.grand_total),
        ]
        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_SALES_RETURN, source_id=sales_return.id,
            source_number=sales_return.return_number, journal_date=sales_return.return_date,
            description=f"Sales Return {sales_return.return_number}", lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_SALES_RETURN, source_id=sales_return.id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    # --- Purchase Invoice (PROMPT-025, closes PROMPT-019 §14's boundary) ---

    async def post_purchase_invoice(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice: PurchaseInvoice, ip_address: str | None,
    ) -> str:
        """§14/§15: DR Purchase Expense (taxable_total) + Input CGST/
        SGST/IGST, CR Accounts Payable (grand_total). "Purchase Expense"
        is a deliberate placeholder, not "Inventory" — perpetual vs
        periodic inventory accounting is unapproved (OD-004/OD-005/
        OD-010)."""
        lines = [
            JournalLineInput(posting_rule_code=PURCHASE_EXPENSE, debit=invoice.taxable_total),
            *_gst_lines(cgst=invoice.cgst_total, sgst=invoice.sgst_total, igst=invoice.igst_total, output=False),
            JournalLineInput(posting_rule_code=ACCOUNTS_PAYABLE, credit=invoice.grand_total),
        ]
        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PURCHASE_INVOICE, source_id=invoice.id,
            source_number=invoice.purchase_invoice_number, journal_date=invoice.document_date,
            description=f"Purchase Invoice {invoice.purchase_invoice_number}", lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PURCHASE_INVOICE, source_id=invoice.id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    async def reverse_purchase_invoice(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, invoice_id: uuid.UUID, ip_address: str | None,
    ) -> str | None:
        journal = await self._journals.reverse_journal_for_source(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PURCHASE_INVOICE, source_id=invoice_id, ip_address=ip_address,
        )
        return journal.journal_number if journal else None

    # --- Purchase Return (PROMPT-025) ---------------------------------------

    async def post_purchase_return(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, purchase_return: PurchaseReturn, ip_address: str | None,
    ) -> str:
        """§19: DR Accounts Payable (grand_total), CR Purchase Return/
        Inventory Adjustment (taxable_total) + Input CGST/SGST/IGST
        reversal."""
        gst_credit_lines = []
        if purchase_return.cgst_total:
            gst_credit_lines.append(JournalLineInput(posting_rule_code=INPUT_CGST, credit=purchase_return.cgst_total))
        if purchase_return.sgst_total:
            gst_credit_lines.append(JournalLineInput(posting_rule_code=INPUT_SGST, credit=purchase_return.sgst_total))
        if purchase_return.igst_total:
            gst_credit_lines.append(JournalLineInput(posting_rule_code=INPUT_IGST, credit=purchase_return.igst_total))
        lines = [
            JournalLineInput(posting_rule_code=ACCOUNTS_PAYABLE, debit=purchase_return.grand_total),
            JournalLineInput(posting_rule_code=PURCHASE_RETURN_ADJUSTMENT, credit=purchase_return.taxable_total),
            *gst_credit_lines,
        ]
        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PURCHASE_RETURN, source_id=purchase_return.id,
            source_number=purchase_return.purchase_return_number, journal_date=purchase_return.document_date,
            description=f"Purchase Return {purchase_return.purchase_return_number}", lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PURCHASE_RETURN, source_id=purchase_return.id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    async def reverse_purchase_return(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, return_id: uuid.UUID, ip_address: str | None,
    ) -> str | None:
        journal = await self._journals.reverse_journal_for_source(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PURCHASE_RETURN, source_id=return_id, ip_address=ip_address,
        )
        return journal.journal_number if journal else None

    # --- Payments & Collections (PROMPT-024 §32) ----------------------------

    async def post_payment(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payment: Payment, ip_address: str | None,
    ) -> str:
        """§16/§17: Customer Receipt: DR Cash/Bank/UPI/Cheque (by
        `payment_method`), CR Accounts Receivable. Supplier Payment is
        the mirror image. The debit/credit-side account is resolved
        dynamically per `payment_method` — never a single hard-coded
        "Cash/Bank" placeholder (§16's own explicit instruction)."""
        cash_bank_rule = _PAYMENT_METHOD_ACCOUNT[payment.payment_method]
        source_type = SRC_CUSTOMER_RECEIPT if payment.party_type == CUSTOMER else SRC_SUPPLIER_PAYMENT

        if payment.party_type == CUSTOMER:
            lines = [
                JournalLineInput(posting_rule_code=cash_bank_rule, debit=payment.amount),
                JournalLineInput(posting_rule_code=ACCOUNTS_RECEIVABLE, credit=payment.amount),
            ]
        else:
            lines = [
                JournalLineInput(posting_rule_code=ACCOUNTS_PAYABLE, debit=payment.amount),
                JournalLineInput(posting_rule_code=cash_bank_rule, credit=payment.amount),
            ]

        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=source_type, source_id=payment.id,
            source_number=payment.payment_number, journal_date=payment.payment_date,
            description=f"{source_type.replace('_', ' ').title()} {payment.payment_number}", lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=source_type, source_id=payment.id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    async def reverse_payment(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payment: Payment, ip_address: str | None,
    ) -> str | None:
        source_type = SRC_CUSTOMER_RECEIPT if payment.party_type == CUSTOMER else SRC_SUPPLIER_PAYMENT
        journal = await self._journals.reverse_journal_for_source(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=source_type, source_id=payment.id, ip_address=ip_address,
        )
        return journal.journal_number if journal else None

    # --- Credit Note / Debit Note (PROMPT-017 §20) --------------------------

    async def post_credit_debit_note(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, note: CreditDebitNote, ip_address: str | None,
    ) -> str:
        """§20/§21: CREDIT_NOTE mirrors Sales Return's own resolution
        (DR Sales Return/Revenue Adjustment + Output GST, CR Accounts
        Receivable). DEBIT_NOTE direction (§56 OD-016, still a
        documented judgment call, unchanged from the pre-PROMPT-025
        stub's own resolution — no approved source confirms it): the
        mirror-opposite (DR Accounts Receivable, CR Sales Revenue/
        Adjustment + Output GST)."""
        is_credit = note.note_type == CREDIT_NOTE
        gst_side_debit = is_credit

        gst_lines = []
        for total, code in ((note.cgst_total, OUTPUT_CGST), (note.sgst_total, OUTPUT_SGST), (note.igst_total, OUTPUT_IGST)):
            if total:
                gst_lines.append(JournalLineInput(posting_rule_code=code, debit=total if gst_side_debit else Decimal("0"), credit=total if not gst_side_debit else Decimal("0")))

        if is_credit:
            lines = [
                JournalLineInput(posting_rule_code=SALES_RETURN_ADJUSTMENT, debit=note.taxable_total),
                *gst_lines,
                JournalLineInput(posting_rule_code=ACCOUNTS_RECEIVABLE, credit=note.grand_total),
            ]
        else:
            lines = [
                JournalLineInput(posting_rule_code=ACCOUNTS_RECEIVABLE, debit=note.grand_total),
                JournalLineInput(posting_rule_code=SALES_REVENUE, credit=note.taxable_total),
                *gst_lines,
            ]

        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id,
            source_type=SRC_CREDIT_NOTE if is_credit else SRC_DEBIT_NOTE, source_id=note.id,
            source_number=note.note_number, journal_date=note.note_date,
            description=f"{note.note_type.replace('_', ' ').title()} {note.note_number}", lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id,
            source_type=SRC_CREDIT_NOTE if is_credit else SRC_DEBIT_NOTE, source_id=note.id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    # --- Payroll (PROMPT-029 §32/§33/§59) -----------------------------------

    async def post_payroll_run(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payroll_run_id: uuid.UUID, run_date, total_gross: Decimal,
        total_deductions: Decimal, total_net: Decimal, run_label: str, ip_address: str | None,
    ) -> str:
        """§32: DR Salary Expense (gross) / CR Salary Payable (net) +
        CR Salary Deductions Payable (deductions, only when > 0) — this
        is the ENTIRE payroll journal (§33: PROMPT-029 owns calculation
        and the snapshot; this service owns journal creation/balancing,
        exactly like every other document type). No PF/ESI/TDS liability
        line exists — M1 is basic payroll only (§3/§20 AC)."""
        lines = [JournalLineInput(posting_rule_code=SALARY_EXPENSE, debit=total_gross)]
        if total_deductions > 0:
            lines.append(JournalLineInput(posting_rule_code=SALARY_DEDUCTIONS_PAYABLE, credit=total_deductions))
        lines.append(JournalLineInput(posting_rule_code=SALARY_PAYABLE, credit=total_net))

        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PAYROLL_RUN, source_id=payroll_run_id,
            source_number=run_label, journal_date=run_date, description=f"Payroll {run_label}", lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PAYROLL_RUN, source_id=payroll_run_id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    async def reverse_payroll_run(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, payroll_run_id: uuid.UUID, ip_address: str | None,
    ) -> str | None:
        journal = await self._journals.reverse_journal_for_source(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_PAYROLL_RUN, source_id=payroll_run_id, ip_address=ip_address,
        )
        return journal.journal_number if journal else None

    # --- Manual Stock Movements (Weighted Average Cost) ---------------------
    # Called by InventoryService's 4 public entry points after post_movement
    # has already written the stock_ledger_entry/stock_qty_cache update —
    # these 3 methods are purely about the VALUE of that movement, using
    # whatever cost InventoryService resolved (entered unit_cost, or the
    # product's current weighted-average cost_price). `source_id` is the
    # StockLedgerEntry's own id, guaranteeing one journal per movement.
    # Never posts a zero/fabricated-value journal: `amount <= 0` (no known
    # cost) returns None and InventoryService's caller just has a stock
    # movement with no accounting entry, same as before this feature existed.

    async def post_opening_stock(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_id: uuid.UUID, movement_date: date,
        amount: Decimal, description: str, ip_address: str | None,
    ) -> str | None:
        """DR Inventory / CR Opening Balance Equity — the one-time
        starting value of a product's stock."""
        if amount <= 0:
            return None
        lines = [
            JournalLineInput(posting_rule_code=INVENTORY, debit=amount),
            JournalLineInput(posting_rule_code=OPENING_BALANCE_EQUITY, credit=amount),
        ]
        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_OPENING_STOCK, source_id=source_id,
            source_number=None, journal_date=movement_date, description=description, lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=SRC_OPENING_STOCK, source_id=source_id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    async def post_stock_increase(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_type: str, source_id: uuid.UUID,
        movement_date: date, amount: Decimal, description: str, ip_address: str | None,
    ) -> str | None:
        """DR Inventory / CR Stock Adjustment — manual Stock In or an
        Adjustment in the IN direction (quantity found/corrected upward).
        `source_type` is SRC_MANUAL_STOCK_IN or SRC_STOCK_ADJUSTMENT."""
        if amount <= 0:
            return None
        lines = [
            JournalLineInput(posting_rule_code=INVENTORY, debit=amount),
            JournalLineInput(posting_rule_code=STOCK_ADJUSTMENT, credit=amount),
        ]
        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=source_type, source_id=source_id,
            source_number=None, journal_date=movement_date, description=description, lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=source_type, source_id=source_id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number

    async def post_stock_decrease(
        self, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, source_type: str, source_id: uuid.UUID,
        movement_date: date, amount: Decimal, description: str, ip_address: str | None,
    ) -> str | None:
        """DR Stock Adjustment / CR Inventory — manual Stock Out or an
        Adjustment in the OUT direction (damage/shrinkage/correction
        downward), valued at the product's current weighted-average cost.
        `source_type` is SRC_MANUAL_STOCK_OUT or SRC_STOCK_ADJUSTMENT."""
        if amount <= 0:
            return None
        lines = [
            JournalLineInput(posting_rule_code=STOCK_ADJUSTMENT, debit=amount),
            JournalLineInput(posting_rule_code=INVENTORY, credit=amount),
        ]
        journal = await self._journals.post_journal(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=source_type, source_id=source_id,
            source_number=None, journal_date=movement_date, description=description, lines=lines, ip_address=ip_address,
        )
        await self._record_posted_audit(
            tenant_id=tenant_id, actor_user_id=actor_user_id, source_type=source_type, source_id=source_id,
            journal_number=journal.journal_number, ip_address=ip_address,
        )
        return journal.journal_number
