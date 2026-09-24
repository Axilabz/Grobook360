"""Global Table/Grid Export Framework: <resource>.export permission codes.

Revision ID: 0031_export_permissions
Revises: 0030_product_supplier
Create Date: 2026-09-25

Adds a new `<module>.export` permission per resource this pass of the
export framework covers (Customers, Suppliers, Products, Sales Invoices,
Purchase Invoices, Customer Receipts, Supplier Payments) — VIEW and
EXPORT are deliberately separate permissions (a user may see a grid
on-screen without being authorized to extract it as a file), mirroring
the ALREADY-EXISTING gst.export/reports.export/payroll.export precedent
this codebase established in PROMPT-026/027/029.

No new tables: exports are synchronous for M1 (no background-job
infrastructure exists anywhere in this codebase — the same confirmed
absence every prior integration-heavy prompt in this session has
independently found) and are audited via the EXISTING audit_log table
via AuditService, not a new export_job table — see
app/services/export/export_service.py's own module docstring for the
full rationale.

Like migration 0021/0024/0025/0026/0027/0029, this migration backfills
the new permission codes onto every EXISTING tenant's OWNER/MANAGER
roles (Salesperson gets none — matches how every one of these 7
resources' own VIEW-adjacent write permissions already treat
Salesperson: full or partial access to the underlying data, but never
the most privileged bulk-extraction action for financial/purchase
resources; and for Customer/Supplier/Product, export is judged a more
sensitive, higher-blast-radius action than ordinary view/create,
consistent with this codebase's own repeated "a narrower permission for
a more sensitive action" pattern, e.g. salary.view vs salary.manage).
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0031_export_permissions"
down_revision = "0030_product_supplier"
branch_labels = None
depends_on = None

_EXPORT_PERMISSIONS = {
    "customers.export": "Export the customer list to Excel/PDF",
    "suppliers.export": "Export the supplier list to Excel/PDF",
    "products.export": "Export the product list to Excel/PDF",
    "sales_invoice.export": "Export the sales invoice list to Excel/PDF",
    "purchase_invoice.export": "Export the purchase invoice list to Excel/PDF",
    "customer_receipt.export": "Export the customer receipt list to Excel/PDF",
    "supplier_payment.export": "Export the supplier payment list to Excel/PDF",
}

_ALL_CODES = list(_EXPORT_PERMISSIONS.keys())

_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": _ALL_CODES,
    "MANAGER": _ALL_CODES,
    "SALESPERSON": [],
}


def upgrade() -> None:
    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _EXPORT_PERMISSIONS.items():
        row = connection.execute(sa.text("SELECT id FROM permission WHERE code = :code"), {"code": code}).fetchone()
        if row is None:
            new_id = connection.execute(
                sa.text(
                    "INSERT INTO permission (id, code, description, created_at, updated_at, row_version) "
                    "VALUES (gen_random_uuid(), :code, :description, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1) "
                    "RETURNING id"
                ),
                {"code": code, "description": description},
            ).fetchone()
            permission_ids[code] = str(new_id[0])
        else:
            permission_ids[code] = str(row[0])

    roles = connection.execute(sa.text("SELECT id, tenant_id, name FROM role")).fetchall()
    for role_id, tenant_id, role_name in roles:
        for code in _ROLE_DEFAULT_PERMISSIONS.get(role_name, []):
            permission_id = permission_ids[code]
            existing = connection.execute(
                sa.text("SELECT 1 FROM role_permission WHERE role_id = :role_id AND permission_id = :permission_id"),
                {"role_id": str(role_id), "permission_id": permission_id},
            ).fetchone()
            if existing is None:
                connection.execute(
                    sa.text(
                        "INSERT INTO role_permission (id, tenant_id, role_id, permission_id, created_at, updated_at, row_version) "
                        "VALUES (gen_random_uuid(), :tenant_id, :role_id, :permission_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                    ),
                    {"tenant_id": str(tenant_id), "role_id": str(role_id), "permission_id": permission_id},
                )


def downgrade() -> None:
    # Permission/role_permission seed rows left in place, matching precedent
    # (0029 and earlier permission-adding migrations do the same).
    pass
