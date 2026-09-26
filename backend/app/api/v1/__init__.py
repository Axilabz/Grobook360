from fastapi import APIRouter

from app.api.v1.accounting import router as accounting_router
from app.api.v1.auth import router as auth_router
from app.api.v1.configuration import router as configuration_router
from app.api.v1.parties import router as parties_router
from app.api.v1.credit_debit_notes import router as credit_debit_notes_router
from app.api.v1.customer_receipts import router as customer_receipts_router
from app.api.v1.customers import router as customers_router
from app.api.v1.delivery_challans import router as delivery_challans_router
from app.api.v1.einvoice import router as einvoice_router
from app.api.v1.eway_bills import invoice_router as eway_bills_invoice_router
from app.api.v1.gst import router as gst_router
from app.api.v1.payroll import router as payroll_router
from app.api.v1.reports import router as reports_router
from app.api.v1.eway_bills import router as eway_bills_router
from app.api.v1.exports import router as exports_router
from app.api.v1.goods_receipts import router as goods_receipts_router
from app.api.v1.integration_operations import router as integration_operations_router
from app.api.v1.inventory import router as inventory_router
from app.api.v1.password_reset import router as password_reset_router
from app.api.v1.products import router as products_router
from app.api.v1.purchase_invoices import router as purchase_invoices_router
from app.api.v1.purchase_orders import router as purchase_orders_router
from app.api.v1.purchase_returns import router as purchase_returns_router
from app.api.v1.roles import router as roles_router
from app.api.v1.sales_estimates import router as sales_estimates_router
from app.api.v1.sales_invoices import router as sales_invoices_router
from app.api.v1.sales_orders import router as sales_orders_router
from app.api.v1.sales_returns import router as sales_returns_router
from app.api.v1.supplier_payments import router as supplier_payments_router
from app.api.v1.suppliers import router as suppliers_router
from app.api.v1.system import router as system_router
from app.api.v1.units import router as units_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(auth_router)
api_router.include_router(password_reset_router)
api_router.include_router(users_router)
api_router.include_router(roles_router)
api_router.include_router(customers_router)
api_router.include_router(suppliers_router)
api_router.include_router(products_router)
api_router.include_router(units_router)
api_router.include_router(inventory_router)
api_router.include_router(sales_estimates_router)
api_router.include_router(sales_orders_router)
api_router.include_router(delivery_challans_router)
api_router.include_router(sales_invoices_router)
api_router.include_router(sales_returns_router)
api_router.include_router(credit_debit_notes_router)
api_router.include_router(einvoice_router)
api_router.include_router(eway_bills_invoice_router)
api_router.include_router(eway_bills_router)
api_router.include_router(integration_operations_router)
api_router.include_router(purchase_orders_router)
api_router.include_router(goods_receipts_router)
api_router.include_router(purchase_invoices_router)
api_router.include_router(purchase_returns_router)
api_router.include_router(customer_receipts_router)
api_router.include_router(supplier_payments_router)
api_router.include_router(accounting_router)
api_router.include_router(gst_router)
api_router.include_router(reports_router)
api_router.include_router(payroll_router)
api_router.include_router(exports_router)
api_router.include_router(configuration_router)
api_router.include_router(parties_router)
