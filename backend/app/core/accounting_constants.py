"""Accounting Posting Matrix & Journal Engine shared constants (PROMPT-025).

Mirrors `app.core.sales_constants`/`app.core.purchase_constants`'s exact
role: pure vocabulary every accounting-aware service imports, rather
than each inventing its own strings. The default Chart of Accounts and
account-mapping seed data live here too — explicitly a DEFAULT, EDITABLE
starting set (§56 OD-001/OD-002), not an approved final Chart of
Accounts. No account code is ever hard-coded into posting logic itself;
posting logic only ever asks for a `posting_rule_code` and gets back
whatever account the tenant's own `account_mapping` row resolves to.
"""

# --- Account types (§9) ---
ASSET = "ASSET"
LIABILITY = "LIABILITY"
EQUITY = "EQUITY"
REVENUE = "REVENUE"
EXPENSE = "EXPENSE"
COGS = "COGS"

ACCOUNT_TYPES = frozenset({ASSET, LIABILITY, EQUITY, REVENUE, EXPENSE, COGS})

# --- Posting rule codes (§10) — the ONLY vocabulary posting logic uses
# to resolve an account; never a literal account id. ---
ACCOUNTS_RECEIVABLE = "ACCOUNTS_RECEIVABLE"
SALES_REVENUE = "SALES_REVENUE"
OUTPUT_CGST = "OUTPUT_CGST"
OUTPUT_SGST = "OUTPUT_SGST"
OUTPUT_IGST = "OUTPUT_IGST"
SALES_RETURN_ADJUSTMENT = "SALES_RETURN_ADJUSTMENT"
ACCOUNTS_PAYABLE = "ACCOUNTS_PAYABLE"
PURCHASE_EXPENSE = "PURCHASE_EXPENSE"
INPUT_CGST = "INPUT_CGST"
INPUT_SGST = "INPUT_SGST"
INPUT_IGST = "INPUT_IGST"
PURCHASE_RETURN_ADJUSTMENT = "PURCHASE_RETURN_ADJUSTMENT"
CASH_ACCOUNT = "CASH_ACCOUNT"
BANK_ACCOUNT = "BANK_ACCOUNT"
UPI_ACCOUNT = "UPI_ACCOUNT"
CHEQUE_ACCOUNT = "CHEQUE_ACCOUNT"
# PROMPT-029 §32/§59: basic-payroll-only posting rules — no PF/ESI/TDS
# liability account exists (M1 explicitly excludes statutory payroll).
SALARY_EXPENSE = "SALARY_EXPENSE"
SALARY_PAYABLE = "SALARY_PAYABLE"
SALARY_DEDUCTIONS_PAYABLE = "SALARY_DEDUCTIONS_PAYABLE"

POSTING_RULE_CODES = frozenset(
    {
        ACCOUNTS_RECEIVABLE, SALES_REVENUE, OUTPUT_CGST, OUTPUT_SGST, OUTPUT_IGST, SALES_RETURN_ADJUSTMENT,
        ACCOUNTS_PAYABLE, PURCHASE_EXPENSE, INPUT_CGST, INPUT_SGST, INPUT_IGST, PURCHASE_RETURN_ADJUSTMENT,
        CASH_ACCOUNT, BANK_ACCOUNT, UPI_ACCOUNT, CHEQUE_ACCOUNT,
        SALARY_EXPENSE, SALARY_PAYABLE, SALARY_DEDUCTIONS_PAYABLE,
    }
)

# posting_rule_code -> (default account code, default account name, account_type)
# §56 OD-001/OD-002/OD-003/OD-004/OD-011/OD-012/OD-013: a documented
# DEFAULT starting Chart of Accounts, editable per tenant, NOT an
# approved final COA — the FMCG-oriented set the prompt's own §9/§10
# names, given stable short codes for referencing.
DEFAULT_ACCOUNT_SEED: dict[str, tuple[str, str, str]] = {
    ACCOUNTS_RECEIVABLE: ("1010", "Accounts Receivable", ASSET),
    CASH_ACCOUNT: ("1020", "Cash-in-Hand", ASSET),
    BANK_ACCOUNT: ("1030", "Bank Account", ASSET),
    UPI_ACCOUNT: ("1040", "UPI Clearing Account", ASSET),
    CHEQUE_ACCOUNT: ("1050", "Cheque Clearing Account", ASSET),
    INPUT_CGST: ("1060", "Input CGST Receivable", ASSET),
    INPUT_SGST: ("1070", "Input SGST Receivable", ASSET),
    INPUT_IGST: ("1080", "Input IGST Receivable", ASSET),
    ACCOUNTS_PAYABLE: ("2010", "Accounts Payable", LIABILITY),
    OUTPUT_CGST: ("2020", "Output CGST Payable", LIABILITY),
    OUTPUT_SGST: ("2030", "Output SGST Payable", LIABILITY),
    OUTPUT_IGST: ("2040", "Output IGST Payable", LIABILITY),
    SALES_REVENUE: ("4010", "Sales Revenue", REVENUE),
    SALES_RETURN_ADJUSTMENT: ("4020", "Sales Return / Revenue Adjustment", REVENUE),
    PURCHASE_EXPENSE: ("5010", "Purchase Expense", EXPENSE),
    PURCHASE_RETURN_ADJUSTMENT: ("5020", "Purchase Return / Inventory Adjustment", EXPENSE),
    SALARY_PAYABLE: ("2050", "Salary Payable", LIABILITY),
    SALARY_DEDUCTIONS_PAYABLE: ("2060", "Salary Deductions Payable", LIABILITY),
    SALARY_EXPENSE: ("5030", "Salary Expense", EXPENSE),
}

# --- Journal document type (for DocumentNumberingService) ---
JOURNAL = "JOURNAL"

# --- Journal status (§5) ---
JNL_DRAFT = "DRAFT"
JNL_POSTED = "POSTED"
JNL_REVERSED = "REVERSED"
JOURNAL_STATUSES = frozenset({JNL_DRAFT, JNL_POSTED, JNL_REVERSED})

# --- posting_event_type (§31/§32 idempotency key component) — what KIND
# of journal this is for a given source document; a source can have at
# most one journal per event type (enforced by a unique DB constraint).
EVT_ORIGINAL = "ORIGINAL"
EVT_REVERSAL = "REVERSAL"

# --- Source types (§6 journal_entry.source_type) ---
SRC_SALES_INVOICE = "SALES_INVOICE"
SRC_PURCHASE_INVOICE = "PURCHASE_INVOICE"
SRC_CUSTOMER_RECEIPT = "CUSTOMER_RECEIPT"
SRC_SUPPLIER_PAYMENT = "SUPPLIER_PAYMENT"
SRC_SALES_RETURN = "SALES_RETURN"
SRC_PURCHASE_RETURN = "PURCHASE_RETURN"
SRC_CREDIT_NOTE = "CREDIT_NOTE"
SRC_DEBIT_NOTE = "DEBIT_NOTE"
SRC_PAYROLL_RUN = "PAYROLL_RUN"
