"""Permission catalogue (PROMPT-006).

Scope note: only permissions for capabilities that ACTUALLY EXIST in this
codebase are defined here — the users.* surface built in PROMPT-005, plus the
roles.*/permissions.* surface this prompt itself builds. Customer/product/
sales/etc. permission codes from the API Contract's "representative" (S15,
explicitly non-final) examples are deliberately NOT created — those modules
don't exist yet and are out of scope for this prompt; inventing their
permissions now would be exactly the "fill the matrix with assumptions" this
prompt forbids. See PROMPT-006-NOTES.md.

Format: <module>.<action> (PROMPT-006 S6).
"""

# --- Users module (PROMPT-005 surface) ---
USERS_VIEW = "users.view"
USERS_CREATE = "users.create"
USERS_UPDATE = "users.update"
USERS_ACTIVATE = "users.activate"
USERS_DEACTIVATE = "users.deactivate"

# --- Roles/Permissions module (this prompt's own read-only surface) ---
ROLES_VIEW = "roles.view"
PERMISSIONS_VIEW = "permissions.view"

# --- Customers module (PROMPT-007 surface) ---
CUSTOMERS_VIEW = "customers.view"
CUSTOMERS_CREATE = "customers.create"
CUSTOMERS_UPDATE = "customers.update"
CUSTOMERS_ACTIVATE = "customers.activate"
CUSTOMERS_DEACTIVATE = "customers.deactivate"

# --- Suppliers module (PROMPT-008 surface) ---
SUPPLIERS_VIEW = "suppliers.view"
SUPPLIERS_CREATE = "suppliers.create"
SUPPLIERS_UPDATE = "suppliers.update"
SUPPLIERS_ACTIVATE = "suppliers.activate"
SUPPLIERS_DEACTIVATE = "suppliers.deactivate"

# --- Products module (PROMPT-009 surface) ---
# Unit of Measure and Product Unit Conversion are sub-resources of Product
# Master (a UOM is meaningless without a product to attach it to, and no
# approved Role & Entitlement Matrix row exists for a standalone "Units"
# module) — they are gated by these same products.* codes rather than a new
# permission family invented for them. See PROMPT-009-NOTES.md.
PRODUCTS_VIEW = "products.view"
PRODUCTS_CREATE = "products.create"
PRODUCTS_UPDATE = "products.update"
PRODUCTS_ACTIVATE = "products.activate"
PRODUCTS_DEACTIVATE = "products.deactivate"

# --- Inventory module (PROMPT-010 surface) ---
# FR-STK-04 (Confirmed): "Owner/Manager may record manual stock movements;
# Salesperson may only cause stock movement through permitted sales
# workflows" — split into granular codes for style-consistency with every
# other module's catalogue, not because the FRD itself names them
# separately.
INVENTORY_VIEW = "inventory.view"
INVENTORY_OPENING_STOCK = "inventory.opening_stock"
INVENTORY_ADJUST = "inventory.adjust"
INVENTORY_STOCK_IN = "inventory.stock_in"
INVENTORY_STOCK_OUT = "inventory.stock_out"

# --- Sales Estimate module (PROMPT-012 surface) ---
SALES_ESTIMATE_VIEW = "sales_estimate.view"
SALES_ESTIMATE_CREATE = "sales_estimate.create"
SALES_ESTIMATE_EDIT = "sales_estimate.edit"
SALES_ESTIMATE_SEND = "sales_estimate.send"
SALES_ESTIMATE_ACCEPT = "sales_estimate.accept"
SALES_ESTIMATE_REJECT = "sales_estimate.reject"
SALES_ESTIMATE_CANCEL = "sales_estimate.cancel"
SALES_ESTIMATE_CONVERT = "sales_estimate.convert"

# --- Sales Order module (PROMPT-013 surface) ---
# No separate "convert_from_estimate" permission code: the prompt's own
# §31 list suggests one, but the actual conversion action is exposed via
# the EXISTING POST /sales/estimates/{id}/convert-to-sales-order endpoint
# (PROMPT-012), which already requires sales_estimate.convert. Adding a
# second, always-must-match-in-lockstep permission for the same one gate
# would be exactly the "invent a permission the codebase doesn't actually
# check independently" mistake this catalogue's own discipline forbids —
# see PROMPT-013-NOTES.md.
SALES_ORDER_VIEW = "sales_order.view"
SALES_ORDER_CREATE = "sales_order.create"
SALES_ORDER_EDIT = "sales_order.edit"
SALES_ORDER_CONFIRM = "sales_order.confirm"
SALES_ORDER_CANCEL = "sales_order.cancel"

# --- Delivery Challan module (PROMPT-014 surface) ---
DELIVERY_CHALLAN_VIEW = "delivery_challan.view"
DELIVERY_CHALLAN_CREATE = "delivery_challan.create"
DELIVERY_CHALLAN_EDIT = "delivery_challan.edit"
DELIVERY_CHALLAN_CONFIRM = "delivery_challan.confirm"
DELIVERY_CHALLAN_CANCEL = "delivery_challan.cancel"

# --- Sales Invoice module (PROMPT-015 surface) ---
# Both direct-invoice creation and invoice-from-Delivery-Challan creation
# are gated by the single sales_invoice.create code — the endpoint that
# accepts a source Delivery Challan id is a REST convenience nested under
# /sales/delivery-challans/{id}/create-invoice, not a signal that a
# different permission model applies (unlike Estimate->Sales Order
# conversion, which reuses sales_estimate.convert because THAT endpoint
# lives under the source Estimate's own URL and mutates the Estimate
# itself — here, the source Delivery Challan is only read, never mutated
# by this action, so the capability being exercised is purely "create a
# sales invoice").
SALES_INVOICE_VIEW = "sales_invoice.view"
SALES_INVOICE_CREATE = "sales_invoice.create"
SALES_INVOICE_EDIT = "sales_invoice.edit"
SALES_INVOICE_POST = "sales_invoice.post"
SALES_INVOICE_CANCEL = "sales_invoice.cancel"

# --- Sales Return module (PROMPT-016 surface) ---
# The return-eligibility read (GET /sales/invoices/{id}/return-eligibility)
# is gated by sales_return.create — same convention as PROMPT-015's own
# invoice-eligibility endpoint (gated by sales_invoice.create): it is a
# preparatory read for creating a Sales Return, not a mutation of the
# source Sales Invoice.
SALES_RETURN_VIEW = "sales_return.view"
SALES_RETURN_CREATE = "sales_return.create"
SALES_RETURN_EDIT = "sales_return.edit"
SALES_RETURN_CONFIRM = "sales_return.confirm"
SALES_RETURN_CANCEL = "sales_return.cancel"

# --- Credit Note / Debit Note module (PROMPT-017 surface) ---
# The adjustment-eligibility read (GET /sales/invoices/{id}/adjustment-
# eligibility) is gated by EITHER credit_note.create OR debit_note.create
# (checked directly in that endpoint, not via require_permission, since
# it serves both note types) — same preparatory-read convention as
# PROMPT-015/016's own eligibility endpoints.
CREDIT_NOTE_VIEW = "credit_note.view"
CREDIT_NOTE_CREATE = "credit_note.create"
CREDIT_NOTE_EDIT = "credit_note.edit"
CREDIT_NOTE_POST = "credit_note.post"
CREDIT_NOTE_CANCEL = "credit_note.cancel"

DEBIT_NOTE_VIEW = "debit_note.view"
DEBIT_NOTE_CREATE = "debit_note.create"
DEBIT_NOTE_EDIT = "debit_note.edit"
DEBIT_NOTE_POST = "debit_note.post"
DEBIT_NOTE_CANCEL = "debit_note.cancel"

# --- E-Invoice / E-Way Bill module (PROMPT-018 surface) ---
EINVOICE_VIEW = "einvoice.view"
EINVOICE_GENERATE = "einvoice.generate"
EINVOICE_CANCEL = "einvoice.cancel"

EWAY_BILL_VIEW = "eway_bill.view"
EWAY_BILL_GENERATE = "eway_bill.generate"
EWAY_BILL_CANCEL = "eway_bill.cancel"

# --- Purchase module (PROMPT-019 surface) ---
# FRD's own Table 7 (Role & Screen matrix) lists Purchase Orders/Goods
# Receipt/Purchase Invoice as "Owner, Manager" with NO Salesperson entry
# at all — unlike every Sales module row, which always names Salesperson
# too. Resolved per that explicit signal in ROLE_DEFAULT_PERMISSIONS
# below: Salesperson gets none of these codes.
PURCHASE_ORDER_VIEW = "purchase_order.view"
PURCHASE_ORDER_CREATE = "purchase_order.create"
PURCHASE_ORDER_EDIT = "purchase_order.edit"
PURCHASE_ORDER_CONFIRM = "purchase_order.confirm"
PURCHASE_ORDER_CANCEL = "purchase_order.cancel"

GOODS_RECEIPT_VIEW = "goods_receipt.view"
GOODS_RECEIPT_CREATE = "goods_receipt.create"
GOODS_RECEIPT_EDIT = "goods_receipt.edit"
GOODS_RECEIPT_CONFIRM = "goods_receipt.confirm"
GOODS_RECEIPT_CANCEL = "goods_receipt.cancel"

PURCHASE_INVOICE_VIEW = "purchase_invoice.view"
PURCHASE_INVOICE_CREATE = "purchase_invoice.create"
PURCHASE_INVOICE_EDIT = "purchase_invoice.edit"
PURCHASE_INVOICE_POST = "purchase_invoice.post"
PURCHASE_INVOICE_CANCEL = "purchase_invoice.cancel"

PURCHASE_RETURN_VIEW = "purchase_return.view"
PURCHASE_RETURN_CREATE = "purchase_return.create"
PURCHASE_RETURN_EDIT = "purchase_return.edit"
PURCHASE_RETURN_CONFIRM = "purchase_return.confirm"
PURCHASE_RETURN_CANCEL = "purchase_return.cancel"

CUSTOMER_RECEIPT_VIEW = "customer_receipt.view"
CUSTOMER_RECEIPT_CREATE = "customer_receipt.create"
CUSTOMER_RECEIPT_EDIT = "customer_receipt.edit"
CUSTOMER_RECEIPT_POST = "customer_receipt.post"
CUSTOMER_RECEIPT_REVERSE = "customer_receipt.reverse"

SUPPLIER_PAYMENT_VIEW = "supplier_payment.view"
SUPPLIER_PAYMENT_CREATE = "supplier_payment.create"
SUPPLIER_PAYMENT_EDIT = "supplier_payment.edit"
SUPPLIER_PAYMENT_POST = "supplier_payment.post"
SUPPLIER_PAYMENT_REVERSE = "supplier_payment.reverse"

ACCOUNTING_VIEW_JOURNALS = "accounting.view_journals"
ACCOUNTING_VIEW_CHART_OF_ACCOUNTS = "accounting.view_chart_of_accounts"
ACCOUNTING_MANAGE_ACCOUNT_MAPPINGS = "accounting.manage_account_mappings"
ACCOUNTING_REVERSE_JOURNAL = "accounting.reverse_journal"

GST_VIEW = "gst.view"
GST_PREPARE_RETURNS = "gst.prepare_returns"
GST_EXPORT = "gst.export"

REPORTS_VIEW_DASHBOARD = "reports.view_dashboard"
REPORTS_VIEW_SALES = "reports.view_sales"
REPORTS_VIEW_PURCHASE = "reports.view_purchase"
REPORTS_VIEW_INVENTORY = "reports.view_inventory"
REPORTS_VIEW_RECEIVABLES = "reports.view_receivables"
REPORTS_VIEW_PAYABLES = "reports.view_payables"
REPORTS_VIEW_PAYMENTS = "reports.view_payments"
REPORTS_VIEW_GENERAL_LEDGER = "reports.view_general_ledger"
REPORTS_VIEW_TRIAL_BALANCE = "reports.view_trial_balance"
REPORTS_VIEW_PROFIT_LOSS = "reports.view_profit_loss"
REPORTS_VIEW_BALANCE_SHEET = "reports.view_balance_sheet"
REPORTS_VIEW_GST = "reports.view_gst"
REPORTS_EXPORT = "reports.export"

EMPLOYEES_VIEW = "employees.view"
EMPLOYEES_CREATE = "employees.create"
EMPLOYEES_EDIT = "employees.edit"
EMPLOYEES_DEACTIVATE = "employees.deactivate"
SALARY_VIEW = "salary.view"
SALARY_MANAGE = "salary.manage"
ATTENDANCE_VIEW = "attendance.view"
ATTENDANCE_MANAGE = "attendance.manage"
LEAVE_VIEW = "leave.view"
LEAVE_MANAGE = "leave.manage"
LEAVE_APPROVE = "leave.approve"
PAYROLL_RUN = "payroll.run"
PAYROLL_FINALIZE = "payroll.finalize"
PAYROLL_VIEW = "payroll.view"
PAYROLL_VIEW_PAYSLIP = "payroll.view_payslip"
PAYROLL_EXPORT = "payroll.export"

ALL_PERMISSIONS: dict[str, str] = {
    USERS_VIEW: "View tenant users",
    USERS_CREATE: "Create tenant users",
    USERS_UPDATE: "Edit tenant user details and role",
    USERS_ACTIVATE: "Reactivate a deactivated user",
    USERS_DEACTIVATE: "Deactivate a user",
    ROLES_VIEW: "View the tenant's roles and their permissions",
    PERMISSIONS_VIEW: "View the global permission catalogue",
    CUSTOMERS_VIEW: "View tenant customers",
    CUSTOMERS_CREATE: "Create tenant customers",
    CUSTOMERS_UPDATE: "Edit tenant customer details",
    CUSTOMERS_ACTIVATE: "Reactivate a deactivated customer",
    CUSTOMERS_DEACTIVATE: "Deactivate a customer",
    SUPPLIERS_VIEW: "View tenant suppliers",
    SUPPLIERS_CREATE: "Create tenant suppliers",
    SUPPLIERS_UPDATE: "Edit tenant supplier details",
    SUPPLIERS_ACTIVATE: "Reactivate a deactivated supplier",
    SUPPLIERS_DEACTIVATE: "Deactivate a supplier",
    PRODUCTS_VIEW: "View tenant products",
    PRODUCTS_CREATE: "Create tenant products",
    PRODUCTS_UPDATE: "Edit tenant product details",
    PRODUCTS_ACTIVATE: "Reactivate a deactivated product",
    PRODUCTS_DEACTIVATE: "Deactivate a product",
    INVENTORY_VIEW: "View tenant inventory and stock movement history",
    INVENTORY_OPENING_STOCK: "Record opening stock for a product",
    INVENTORY_ADJUST: "Record a manual stock adjustment",
    INVENTORY_STOCK_IN: "Record a manual stock-in movement",
    INVENTORY_STOCK_OUT: "Record a manual stock-out movement",
    SALES_ESTIMATE_VIEW: "View tenant sales estimates",
    SALES_ESTIMATE_CREATE: "Create a sales estimate",
    SALES_ESTIMATE_EDIT: "Edit a draft sales estimate",
    SALES_ESTIMATE_SEND: "Mark an estimate as sent to the customer",
    SALES_ESTIMATE_ACCEPT: "Record customer acceptance of an estimate",
    SALES_ESTIMATE_REJECT: "Record customer rejection of an estimate",
    SALES_ESTIMATE_CANCEL: "Cancel a draft/sent estimate",
    SALES_ESTIMATE_CONVERT: "Convert an eligible estimate to a Sales Order",
    SALES_ORDER_VIEW: "View tenant sales orders",
    SALES_ORDER_CREATE: "Create a sales order",
    SALES_ORDER_EDIT: "Edit a draft sales order",
    SALES_ORDER_CONFIRM: "Confirm a sales order for fulfillment",
    SALES_ORDER_CANCEL: "Cancel a sales order",
    DELIVERY_CHALLAN_VIEW: "View tenant delivery challans",
    DELIVERY_CHALLAN_CREATE: "Create a delivery challan against a sales order",
    DELIVERY_CHALLAN_EDIT: "Edit a draft delivery challan",
    DELIVERY_CHALLAN_CONFIRM: "Confirm a delivery challan and dispatch stock",
    DELIVERY_CHALLAN_CANCEL: "Cancel a draft delivery challan",
    SALES_INVOICE_VIEW: "View tenant sales invoices",
    SALES_INVOICE_CREATE: "Create a sales invoice (direct or from a delivery challan)",
    SALES_INVOICE_EDIT: "Edit a draft sales invoice",
    SALES_INVOICE_POST: "Post a sales invoice (stock/accounting/GST impact)",
    SALES_INVOICE_CANCEL: "Cancel a draft sales invoice",
    SALES_RETURN_VIEW: "View tenant sales returns",
    SALES_RETURN_CREATE: "Create a sales return against a posted sales invoice",
    SALES_RETURN_EDIT: "Edit a draft sales return",
    SALES_RETURN_CONFIRM: "Confirm a sales return (stock IN impact)",
    SALES_RETURN_CANCEL: "Cancel a draft sales return",
    CREDIT_NOTE_VIEW: "View tenant credit notes",
    CREDIT_NOTE_CREATE: "Create a credit note against a posted sales invoice",
    CREDIT_NOTE_EDIT: "Edit a draft credit note",
    CREDIT_NOTE_POST: "Post a credit note (accounting/GST impact)",
    CREDIT_NOTE_CANCEL: "Cancel a draft credit note",
    DEBIT_NOTE_VIEW: "View tenant debit notes",
    DEBIT_NOTE_CREATE: "Create a debit note against a posted sales invoice",
    DEBIT_NOTE_EDIT: "Edit a draft debit note",
    DEBIT_NOTE_POST: "Post a debit note (accounting/GST impact)",
    DEBIT_NOTE_CANCEL: "Cancel a draft debit note",
    EINVOICE_VIEW: "View tenant e-invoice status and details",
    EINVOICE_GENERATE: "Generate an e-invoice (IRN) for a posted sales invoice",
    EINVOICE_CANCEL: "Cancel a generated e-invoice (IRN)",
    EWAY_BILL_VIEW: "View tenant e-way bill status and details",
    EWAY_BILL_GENERATE: "Generate an e-way bill for a posted sales invoice",
    EWAY_BILL_CANCEL: "Cancel a generated e-way bill",
    PURCHASE_ORDER_VIEW: "View tenant purchase orders",
    PURCHASE_ORDER_CREATE: "Create a purchase order",
    PURCHASE_ORDER_EDIT: "Edit a draft purchase order",
    PURCHASE_ORDER_CONFIRM: "Confirm a purchase order for receiving",
    PURCHASE_ORDER_CANCEL: "Cancel a purchase order",
    GOODS_RECEIPT_VIEW: "View tenant goods receipts",
    GOODS_RECEIPT_CREATE: "Create a goods receipt against a purchase order",
    GOODS_RECEIPT_EDIT: "Edit a draft goods receipt",
    GOODS_RECEIPT_CONFIRM: "Confirm a goods receipt and receive stock",
    GOODS_RECEIPT_CANCEL: "Cancel a draft goods receipt",
    PURCHASE_INVOICE_VIEW: "View tenant purchase invoices",
    PURCHASE_INVOICE_CREATE: "Create a purchase invoice (direct or from a goods receipt)",
    PURCHASE_INVOICE_EDIT: "Edit a draft purchase invoice",
    PURCHASE_INVOICE_POST: "Post a purchase invoice (stock/payable impact)",
    PURCHASE_INVOICE_CANCEL: "Cancel a draft purchase invoice",
    PURCHASE_RETURN_VIEW: "View tenant purchase returns",
    PURCHASE_RETURN_CREATE: "Create a purchase return against a posted purchase invoice",
    PURCHASE_RETURN_EDIT: "Edit a draft purchase return",
    PURCHASE_RETURN_CONFIRM: "Confirm a purchase return (stock OUT impact)",
    PURCHASE_RETURN_CANCEL: "Cancel a draft purchase return",
    CUSTOMER_RECEIPT_VIEW: "View tenant customer receipts",
    CUSTOMER_RECEIPT_CREATE: "Create a customer receipt",
    CUSTOMER_RECEIPT_EDIT: "Edit a draft customer receipt",
    CUSTOMER_RECEIPT_POST: "Post a customer receipt (invoice outstanding impact)",
    CUSTOMER_RECEIPT_REVERSE: "Reverse a posted customer receipt",
    SUPPLIER_PAYMENT_VIEW: "View tenant supplier payments",
    SUPPLIER_PAYMENT_CREATE: "Create a supplier payment",
    SUPPLIER_PAYMENT_EDIT: "Edit a draft supplier payment",
    SUPPLIER_PAYMENT_POST: "Post a supplier payment (invoice outstanding impact)",
    SUPPLIER_PAYMENT_REVERSE: "Reverse a posted supplier payment",
    ACCOUNTING_VIEW_JOURNALS: "View tenant accounting journals",
    ACCOUNTING_VIEW_CHART_OF_ACCOUNTS: "View the tenant's Chart of Accounts",
    ACCOUNTING_MANAGE_ACCOUNT_MAPPINGS: "View/manage posting-rule account mappings",
    ACCOUNTING_REVERSE_JOURNAL: "Reverse a posted accounting journal",
    GST_VIEW: "View GST transactions, dashboard and reconciliation",
    GST_PREPARE_RETURNS: "Calculate/refresh and validate GSTR-1 and GSTR-3B",
    GST_EXPORT: "Export prepared GST return data",
    REPORTS_VIEW_DASHBOARD: "View the management dashboard",
    REPORTS_VIEW_SALES: "View Sales reports",
    REPORTS_VIEW_PURCHASE: "View Purchase reports",
    REPORTS_VIEW_INVENTORY: "View Inventory/Stock reports",
    REPORTS_VIEW_RECEIVABLES: "View the Receivables (Customer Outstanding) report",
    REPORTS_VIEW_PAYABLES: "View the Payables (Supplier Outstanding) report",
    REPORTS_VIEW_PAYMENTS: "View Payment reports",
    REPORTS_VIEW_GENERAL_LEDGER: "View the General Ledger",
    REPORTS_VIEW_TRIAL_BALANCE: "View the Trial Balance",
    REPORTS_VIEW_PROFIT_LOSS: "View the Profit & Loss statement",
    REPORTS_VIEW_BALANCE_SHEET: "View the Balance Sheet",
    REPORTS_VIEW_GST: "View GST reporting views",
    REPORTS_EXPORT: "Export report data",
    EMPLOYEES_VIEW: "View tenant employees",
    EMPLOYEES_CREATE: "Create a new employee",
    EMPLOYEES_EDIT: "Edit employee details",
    EMPLOYEES_DEACTIVATE: "Deactivate/reactivate an employee",
    SALARY_VIEW: "View employee salary structures",
    SALARY_MANAGE: "Create/edit employee salary structures",
    ATTENDANCE_VIEW: "View attendance records",
    ATTENDANCE_MANAGE: "Record/edit attendance",
    LEAVE_VIEW: "View leave requests",
    LEAVE_MANAGE: "Create/edit leave requests",
    LEAVE_APPROVE: "Approve or reject leave requests",
    PAYROLL_RUN: "Create and calculate a payroll run",
    PAYROLL_FINALIZE: "Finalize a payroll run",
    PAYROLL_VIEW: "View payroll runs and records",
    PAYROLL_VIEW_PAYSLIP: "View an individual payslip",
    PAYROLL_EXPORT: "Export payroll register/reports",
}

# Default role -> permission-code set, applied when a tenant's Role row is
# first created (sign-up for OWNER; first assignment for MANAGER/SALESPERSON)
# and backfilled for pre-existing roles by migration 0007. Mirrors exactly the
# access pattern PROMPT-005 already enforced via require_role() — this is a
# formalization, not a new business decision. PLATFORM_ADMINISTRATOR is
# deliberately absent: no platform module exists yet to define its
# permissions against (open decision, see PROMPT-006-NOTES.md).
ROLE_DEFAULT_PERMISSIONS: dict[str, frozenset[str]] = {
    "OWNER": frozenset(
        {
            USERS_VIEW, USERS_CREATE, USERS_UPDATE, USERS_ACTIVATE, USERS_DEACTIVATE,
            ROLES_VIEW, PERMISSIONS_VIEW,
            CUSTOMERS_VIEW, CUSTOMERS_CREATE, CUSTOMERS_UPDATE, CUSTOMERS_ACTIVATE, CUSTOMERS_DEACTIVATE,
            SUPPLIERS_VIEW, SUPPLIERS_CREATE, SUPPLIERS_UPDATE, SUPPLIERS_ACTIVATE, SUPPLIERS_DEACTIVATE,
            PRODUCTS_VIEW, PRODUCTS_CREATE, PRODUCTS_UPDATE, PRODUCTS_ACTIVATE, PRODUCTS_DEACTIVATE,
            INVENTORY_VIEW, INVENTORY_OPENING_STOCK, INVENTORY_ADJUST, INVENTORY_STOCK_IN, INVENTORY_STOCK_OUT,
            SALES_ESTIMATE_VIEW, SALES_ESTIMATE_CREATE, SALES_ESTIMATE_EDIT, SALES_ESTIMATE_SEND,
            SALES_ESTIMATE_ACCEPT, SALES_ESTIMATE_REJECT, SALES_ESTIMATE_CANCEL, SALES_ESTIMATE_CONVERT,
            SALES_ORDER_VIEW, SALES_ORDER_CREATE, SALES_ORDER_EDIT, SALES_ORDER_CONFIRM, SALES_ORDER_CANCEL,
            DELIVERY_CHALLAN_VIEW, DELIVERY_CHALLAN_CREATE, DELIVERY_CHALLAN_EDIT,
            DELIVERY_CHALLAN_CONFIRM, DELIVERY_CHALLAN_CANCEL,
            SALES_INVOICE_VIEW, SALES_INVOICE_CREATE, SALES_INVOICE_EDIT,
            SALES_INVOICE_POST, SALES_INVOICE_CANCEL,
            SALES_RETURN_VIEW, SALES_RETURN_CREATE, SALES_RETURN_EDIT,
            SALES_RETURN_CONFIRM, SALES_RETURN_CANCEL,
            CREDIT_NOTE_VIEW, CREDIT_NOTE_CREATE, CREDIT_NOTE_EDIT, CREDIT_NOTE_POST, CREDIT_NOTE_CANCEL,
            DEBIT_NOTE_VIEW, DEBIT_NOTE_CREATE, DEBIT_NOTE_EDIT, DEBIT_NOTE_POST, DEBIT_NOTE_CANCEL,
            EINVOICE_VIEW, EINVOICE_GENERATE, EINVOICE_CANCEL,
            EWAY_BILL_VIEW, EWAY_BILL_GENERATE, EWAY_BILL_CANCEL,
            PURCHASE_ORDER_VIEW, PURCHASE_ORDER_CREATE, PURCHASE_ORDER_EDIT, PURCHASE_ORDER_CONFIRM, PURCHASE_ORDER_CANCEL,
            GOODS_RECEIPT_VIEW, GOODS_RECEIPT_CREATE, GOODS_RECEIPT_EDIT, GOODS_RECEIPT_CONFIRM, GOODS_RECEIPT_CANCEL,
            PURCHASE_INVOICE_VIEW, PURCHASE_INVOICE_CREATE, PURCHASE_INVOICE_EDIT, PURCHASE_INVOICE_POST, PURCHASE_INVOICE_CANCEL,
            PURCHASE_RETURN_VIEW, PURCHASE_RETURN_CREATE, PURCHASE_RETURN_EDIT, PURCHASE_RETURN_CONFIRM, PURCHASE_RETURN_CANCEL,
            CUSTOMER_RECEIPT_VIEW, CUSTOMER_RECEIPT_CREATE, CUSTOMER_RECEIPT_EDIT, CUSTOMER_RECEIPT_POST, CUSTOMER_RECEIPT_REVERSE,
            SUPPLIER_PAYMENT_VIEW, SUPPLIER_PAYMENT_CREATE, SUPPLIER_PAYMENT_EDIT, SUPPLIER_PAYMENT_POST, SUPPLIER_PAYMENT_REVERSE,
            ACCOUNTING_VIEW_JOURNALS, ACCOUNTING_VIEW_CHART_OF_ACCOUNTS, ACCOUNTING_MANAGE_ACCOUNT_MAPPINGS, ACCOUNTING_REVERSE_JOURNAL,
            GST_VIEW, GST_PREPARE_RETURNS, GST_EXPORT,
            REPORTS_VIEW_DASHBOARD, REPORTS_VIEW_SALES, REPORTS_VIEW_PURCHASE, REPORTS_VIEW_INVENTORY,
            REPORTS_VIEW_RECEIVABLES, REPORTS_VIEW_PAYABLES, REPORTS_VIEW_PAYMENTS, REPORTS_VIEW_GENERAL_LEDGER,
            REPORTS_VIEW_TRIAL_BALANCE, REPORTS_VIEW_PROFIT_LOSS, REPORTS_VIEW_BALANCE_SHEET, REPORTS_VIEW_GST,
            REPORTS_EXPORT,
            EMPLOYEES_VIEW, EMPLOYEES_CREATE, EMPLOYEES_EDIT, EMPLOYEES_DEACTIVATE,
            SALARY_VIEW, SALARY_MANAGE, ATTENDANCE_VIEW, ATTENDANCE_MANAGE,
            LEAVE_VIEW, LEAVE_MANAGE, LEAVE_APPROVE,
            PAYROLL_RUN, PAYROLL_FINALIZE, PAYROLL_VIEW, PAYROLL_VIEW_PAYSLIP, PAYROLL_EXPORT,
        }
    ),
    "MANAGER": frozenset(
        {
            USERS_VIEW, ROLES_VIEW, PERMISSIONS_VIEW,
            CUSTOMERS_VIEW, CUSTOMERS_CREATE, CUSTOMERS_UPDATE, CUSTOMERS_ACTIVATE, CUSTOMERS_DEACTIVATE,
            SUPPLIERS_VIEW, SUPPLIERS_CREATE, SUPPLIERS_UPDATE, SUPPLIERS_ACTIVATE, SUPPLIERS_DEACTIVATE,
            PRODUCTS_VIEW, PRODUCTS_CREATE, PRODUCTS_UPDATE, PRODUCTS_ACTIVATE, PRODUCTS_DEACTIVATE,
            INVENTORY_VIEW, INVENTORY_OPENING_STOCK, INVENTORY_ADJUST, INVENTORY_STOCK_IN, INVENTORY_STOCK_OUT,
            SALES_ESTIMATE_VIEW, SALES_ESTIMATE_CREATE, SALES_ESTIMATE_EDIT, SALES_ESTIMATE_SEND,
            SALES_ESTIMATE_ACCEPT, SALES_ESTIMATE_REJECT, SALES_ESTIMATE_CANCEL, SALES_ESTIMATE_CONVERT,
            SALES_ORDER_VIEW, SALES_ORDER_CREATE, SALES_ORDER_EDIT, SALES_ORDER_CONFIRM, SALES_ORDER_CANCEL,
            DELIVERY_CHALLAN_VIEW, DELIVERY_CHALLAN_CREATE, DELIVERY_CHALLAN_EDIT,
            DELIVERY_CHALLAN_CONFIRM, DELIVERY_CHALLAN_CANCEL,
            SALES_INVOICE_VIEW, SALES_INVOICE_CREATE, SALES_INVOICE_EDIT,
            SALES_INVOICE_POST, SALES_INVOICE_CANCEL,
            SALES_RETURN_VIEW, SALES_RETURN_CREATE, SALES_RETURN_EDIT,
            SALES_RETURN_CONFIRM, SALES_RETURN_CANCEL,
            CREDIT_NOTE_VIEW, CREDIT_NOTE_CREATE, CREDIT_NOTE_EDIT, CREDIT_NOTE_POST, CREDIT_NOTE_CANCEL,
            DEBIT_NOTE_VIEW, DEBIT_NOTE_CREATE, DEBIT_NOTE_EDIT, DEBIT_NOTE_POST, DEBIT_NOTE_CANCEL,
            EINVOICE_VIEW, EINVOICE_GENERATE, EINVOICE_CANCEL,
            EWAY_BILL_VIEW, EWAY_BILL_GENERATE, EWAY_BILL_CANCEL,
            PURCHASE_ORDER_VIEW, PURCHASE_ORDER_CREATE, PURCHASE_ORDER_EDIT, PURCHASE_ORDER_CONFIRM, PURCHASE_ORDER_CANCEL,
            GOODS_RECEIPT_VIEW, GOODS_RECEIPT_CREATE, GOODS_RECEIPT_EDIT, GOODS_RECEIPT_CONFIRM, GOODS_RECEIPT_CANCEL,
            PURCHASE_INVOICE_VIEW, PURCHASE_INVOICE_CREATE, PURCHASE_INVOICE_EDIT, PURCHASE_INVOICE_POST, PURCHASE_INVOICE_CANCEL,
            PURCHASE_RETURN_VIEW, PURCHASE_RETURN_CREATE, PURCHASE_RETURN_EDIT, PURCHASE_RETURN_CONFIRM, PURCHASE_RETURN_CANCEL,
            CUSTOMER_RECEIPT_VIEW, CUSTOMER_RECEIPT_CREATE, CUSTOMER_RECEIPT_EDIT, CUSTOMER_RECEIPT_POST, CUSTOMER_RECEIPT_REVERSE,
            SUPPLIER_PAYMENT_VIEW, SUPPLIER_PAYMENT_CREATE, SUPPLIER_PAYMENT_EDIT, SUPPLIER_PAYMENT_POST, SUPPLIER_PAYMENT_REVERSE,
            ACCOUNTING_VIEW_JOURNALS, ACCOUNTING_VIEW_CHART_OF_ACCOUNTS, ACCOUNTING_MANAGE_ACCOUNT_MAPPINGS, ACCOUNTING_REVERSE_JOURNAL,
            GST_VIEW, GST_PREPARE_RETURNS, GST_EXPORT,
            REPORTS_VIEW_DASHBOARD, REPORTS_VIEW_SALES, REPORTS_VIEW_PURCHASE, REPORTS_VIEW_INVENTORY,
            REPORTS_VIEW_RECEIVABLES, REPORTS_VIEW_PAYABLES, REPORTS_VIEW_PAYMENTS, REPORTS_VIEW_GENERAL_LEDGER,
            REPORTS_VIEW_TRIAL_BALANCE, REPORTS_VIEW_PROFIT_LOSS, REPORTS_VIEW_BALANCE_SHEET, REPORTS_VIEW_GST,
            REPORTS_EXPORT,
            EMPLOYEES_VIEW, EMPLOYEES_CREATE, EMPLOYEES_EDIT, EMPLOYEES_DEACTIVATE,
            SALARY_VIEW, SALARY_MANAGE, ATTENDANCE_VIEW, ATTENDANCE_MANAGE,
            LEAVE_VIEW, LEAVE_MANAGE, LEAVE_APPROVE,
            PAYROLL_RUN, PAYROLL_FINALIZE, PAYROLL_VIEW, PAYROLL_VIEW_PAYSLIP, PAYROLL_EXPORT,
        }
    ),
    # FR-CUST-07 / FR-SUPP-05 (both Confirmed): Salesperson may create/edit
    # customers and suppliers but not deactivate/reactivate either. Table 7
    # independently confirms "Limited" (not "No") access to both for
    # Salesperson.
    #
    # FR-PROD-04 (Confirmed) is stricter for Products: "Owner and Manager
    # may create/edit/deactivate; Salesperson has read-only visibility."
    # Table 7 confirms "View" (not "Limited") for Salesperson on Products —
    # unlike Customer/Supplier, Salesperson gets products.view ONLY.
    # FR-STK-04 (Confirmed): Salesperson "may only cause stock movement
    # through permitted sales workflows" — no manual movement rights at all
    # here (no Sales module exists yet to grant that indirect path).
    # No approved source defines exact per-role Estimate permissions
    # (PROMPT-012 §29/§44 Q16 — open decision, documented in
    # PROMPT-012-NOTES.md). Resolved by mirroring the established
    # Customer/Supplier shape: Salesperson gets the full day-to-day
    # lifecycle except the higher-commitment "convert to Sales Order"
    # action, which is Owner/Manager only.
    #
    # Sales Order (PROMPT-013 §31/§44 Q4 — also an open decision): unlike
    # Estimate, the excluded higher-commitment action here is CONFIRM —
    # User Story 3 explicitly names "Manager/Owner" (not Salesperson) as
    # confirming a Sales Order for fulfillment, a stronger signal than
    # anything the Estimate module had. Salesperson keeps view/create/
    # edit/cancel on Sales Order but not confirm. Converting an Estimate
    # into a Sales Order remains gated by sales_estimate.convert (already
    # Owner/Manager-only since PROMPT-012) — Salesperson cannot trigger it
    # either, unchanged from before this prompt.
    #
    # Delivery Challan (PROMPT-014 §35/§45 Q5 — same open decision shape):
    # CONFIRM is the stock-reducing action (§3/User Story 3 again names
    # Owner/Manager), excluded for Salesperson; create/edit/cancel (DRAFT
    # only — see delivery_challan.py's CANCELLABLE_STATUSES) remain
    # available.
    #
    # Sales Invoice (PROMPT-015 §41/§52 Q2/Q3 — same open decision shape
    # again): POST is the financial/stock/accounting/GST-impacting action
    # (User Story 3 once more names "Owner/Manager" as the actor for whom
    # posted invoices become immutable), excluded for Salesperson;
    # create/edit/cancel (DRAFT only) remain available — this is now the
    # third consecutive Sales document type resolved with this exact
    # shape, not a new judgment call each time.
    #
    # Sales Return (PROMPT-016 §36/§47 open decision #18 — explicitly
    # flagged unresolved in the prompt itself, unlike prior prompts: User
    # Stories 1/2/4 here say "as an authorized user", not "as Owner/
    # Manager", a weaker signal than Sales Order/Delivery Challan/Sales
    # Invoice's own explicit User Story 3 wording). Resolved by mirroring
    # the established shape anyway for consistency across the Sales
    # document chain — CONFIRM (the stock-IN-impacting action) excluded
    # for Salesperson; create/edit/cancel (DRAFT only) remain available.
    # Still documented as an open decision, not a settled business rule,
    # since the textual signal this time is weaker.
    # Credit/Debit Note (PROMPT-017 §42/§53 open decision #24 — explicitly
    # flagged unresolved, same weaker-signal shape as Sales Return's own
    # open decision #18). Resolved by mirroring the established pattern
    # anyway for consistency — POST (the accounting/GST-impacting action)
    # excluded for Salesperson; create/edit/cancel (DRAFT only) remain
    # available for both note types.
    #
    # Purchase (PROMPT-019 — NOT ambiguous, unlike every module above):
    # FRD Table 7 lists Purchase Orders/Goods Receipt/Purchase Invoice as
    # "Owner, Manager" with NO Salesperson entry at all. Salesperson gets
    # ZERO purchase.*/goods_receipt.*/purchase_invoice.*/purchase_return.*
    # permissions — a direct reading of the approved matrix, not a
    # judgment call.
    "SALESPERSON": frozenset(
        {
            CUSTOMERS_VIEW, CUSTOMERS_CREATE, CUSTOMERS_UPDATE,
            SUPPLIERS_VIEW, SUPPLIERS_CREATE, SUPPLIERS_UPDATE,
            PRODUCTS_VIEW,
            INVENTORY_VIEW,
            SALES_ESTIMATE_VIEW, SALES_ESTIMATE_CREATE, SALES_ESTIMATE_EDIT, SALES_ESTIMATE_SEND,
            SALES_ESTIMATE_ACCEPT, SALES_ESTIMATE_REJECT, SALES_ESTIMATE_CANCEL,
            SALES_ORDER_VIEW, SALES_ORDER_CREATE, SALES_ORDER_EDIT, SALES_ORDER_CANCEL,
            DELIVERY_CHALLAN_VIEW, DELIVERY_CHALLAN_CREATE, DELIVERY_CHALLAN_EDIT, DELIVERY_CHALLAN_CANCEL,
            SALES_INVOICE_VIEW, SALES_INVOICE_CREATE, SALES_INVOICE_EDIT, SALES_INVOICE_CANCEL,
            SALES_RETURN_VIEW, SALES_RETURN_CREATE, SALES_RETURN_EDIT, SALES_RETURN_CANCEL,
            CREDIT_NOTE_VIEW, CREDIT_NOTE_CREATE, CREDIT_NOTE_EDIT, CREDIT_NOTE_CANCEL,
            DEBIT_NOTE_VIEW, DEBIT_NOTE_CREATE, DEBIT_NOTE_EDIT, DEBIT_NOTE_CANCEL,
            # E-Invoice/E-Way Bill (PROMPT-018 §4/§43 open decision — no
            # approved source defines exact Salesperson access here).
            # Resolved MORE conservatively than every prior module:
            # VIEW ONLY, no generate/cancel — submitting to or cancelling
            # against a government system is judged a higher-commitment
            # action than any prior Sales-document post/confirm. Flagged
            # as a judgment call, not a settled rule.
            EINVOICE_VIEW, EWAY_BILL_VIEW,
            # Payments & Collections (PROMPT-024 §36/§50 open decision
            # OD-012, no approved source defines exact per-role access).
            # Resolved by mirroring the established "Salesperson drafts,
            # Owner/Manager posts" shape used identically across every
            # Sales document type: view/create/edit only, no post/reverse.
            # Supplier Payment gets ZERO Salesperson access — same
            # direct-FRD-Table-7 reasoning as Purchase's own "Owner,
            # Manager" only rule (a supplier payment is a Purchase-side
            # financial action).
            CUSTOMER_RECEIPT_VIEW, CUSTOMER_RECEIPT_CREATE, CUSTOMER_RECEIPT_EDIT,
            # Reporting (PROMPT-027 §51/§62 OD-022/OD-023 — no approved
            # source defines exact per-role reporting access). Resolved
            # conservatively, mirroring precedent set by every prior
            # financial module: Salesperson gets the operational reports
            # matching modules they already have view access to
            # (Dashboard, Sales, Inventory) but NONE of the
            # Receivables/Payables/Payment/General Ledger/Trial Balance/
            # P&L/Balance Sheet/GST reports — those expose cross-customer
            # outstanding balances and full financial statements, judged
            # equivalent to Accounting's own Owner/Manager-only precedent
            # (OD-023/OD-024 explicitly flagged, not silently resolved).
            REPORTS_VIEW_DASHBOARD, REPORTS_VIEW_SALES, REPORTS_VIEW_INVENTORY,
        }
    ),
}
