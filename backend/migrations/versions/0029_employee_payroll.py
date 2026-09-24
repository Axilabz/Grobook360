"""Employee, Payroll & Basic Salary Management (PROMPT-029): Employee
Master, Salary Structure/Component, Attendance, Leave, Payroll Period/
Run/Record(+Lines), and the employee/salary/attendance/leave/payroll.*
permission catalogue.

Revision ID: 0029_employee_payroll
Revises: 0028_reports
Create Date: 2026-10-16

Basic payroll ONLY (§3/§67 — no PF/ESI/TDS/Professional Tax/statutory
filing anywhere in this schema). `salary_component` mirrors `chart_of_
account`'s own lazily-seeded, per-tenant-editable pattern (PROMPT-025).
`payroll_record` IS the payslip (no separate `payslip` table — a
payslip has no independent lifecycle, it's always this snapshot
rendered for display). Employee Code / Payslip Number both use
`DocumentNumberingService` (`next_number_no_fy` for the former, which
must never reset annually unlike every GST/financial document number).

Like migration 0021/0025/0026/0027/(0028 permission-only), this
migration enables Row-Level Security on every new table and backfills
the new permission codes onto every EXISTING tenant's OWNER/MANAGER
roles (Salesperson gets none — HR/payroll data has no plausible
Salesperson use case in this MVP, a direct reading, not a judgment
call, mirroring Purchase's own "not ambiguous" FRD-Table-7-style
resolution).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0029_employee_payroll"
down_revision = "0028_reports"
branch_labels = None
depends_on = None

_PAYROLL_PERMISSIONS = {
    "employees.view": "View tenant employees",
    "employees.create": "Create a new employee",
    "employees.edit": "Edit employee details",
    "employees.deactivate": "Deactivate/reactivate an employee",
    "salary.view": "View employee salary structures",
    "salary.manage": "Create/edit employee salary structures",
    "attendance.view": "View attendance records",
    "attendance.manage": "Record/edit attendance",
    "leave.view": "View leave requests",
    "leave.manage": "Create/edit leave requests",
    "leave.approve": "Approve or reject leave requests",
    "payroll.run": "Create and calculate a payroll run",
    "payroll.finalize": "Finalize a payroll run",
    "payroll.view": "View payroll runs and records",
    "payroll.view_payslip": "View an individual payslip",
    "payroll.export": "Export payroll register/reports",
}

_ALL_CODES = list(_PAYROLL_PERMISSIONS.keys())

_ROLE_DEFAULT_PERMISSIONS = {
    "OWNER": _ALL_CODES,
    "MANAGER": _ALL_CODES,
    "SALESPERSON": [],
}


def upgrade() -> None:
    op.create_table(
        "employee",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("employee_code", sa.String(20), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("mobile", sa.String(15), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("date_of_joining", sa.Date, nullable=False),
        sa.Column("exit_date", sa.Date, nullable=True),
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("designation", sa.String(100), nullable=True),
        sa.Column("employment_type", sa.String(20), nullable=False, server_default="FULL_TIME"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("reporting_manager_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("bank_account_number", sa.String(30), nullable=True),
        sa.Column("bank_ifsc", sa.CHAR(11), nullable=True),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["reporting_manager_id"], ["employee.id"]),
        sa.UniqueConstraint("tenant_id", "employee_code", name="uq_employee_code"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE','ON_NOTICE','EXITED')", name="ck_employee_status"),
        sa.CheckConstraint("employment_type IN ('FULL_TIME','PART_TIME','CONTRACT')", name="ck_employee_employment_type"),
    )
    op.create_index("idx_employee_tenant", "employee", ["tenant_id"])
    op.create_index("idx_employee_status", "employee", ["tenant_id", "status"])

    op.create_table(
        "salary_component",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("component_type", sa.String(20), nullable=False),
        sa.Column("default_calculation_type", sa.String(20), nullable=False, server_default="FIXED_AMOUNT"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_salary_component_code"),
        sa.CheckConstraint("component_type IN ('EARNING','DEDUCTION')", name="ck_salary_component_type"),
        sa.CheckConstraint("default_calculation_type IN ('FIXED_AMOUNT','PERCENTAGE')", name="ck_salary_component_calc_type"),
    )
    op.create_index("idx_salary_component_tenant", "salary_component", ["tenant_id"])

    op.create_table(
        "salary_structure",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id"), nullable=False),
        sa.Column("effective_from", sa.Date, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "employee_id", "effective_from", name="uq_salary_structure_effective"),
    )
    op.create_index("idx_salary_structure_tenant", "salary_structure", ["tenant_id"])
    op.create_index("idx_salary_structure_employee", "salary_structure", ["tenant_id", "employee_id"])

    op.create_table(
        "salary_structure_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("salary_structure_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("salary_structure.id"), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("salary_component.id"), nullable=False),
        sa.Column("calculation_type", sa.String(20), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("percentage", sa.Numeric(5, 2), nullable=True),
        sa.Column("percentage_of_component_code", sa.String(30), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint("calculation_type IN ('FIXED_AMOUNT','PERCENTAGE')", name="ck_salary_structure_line_calc_type"),
        sa.CheckConstraint("amount >= 0", name="ck_salary_structure_line_amount_nonneg"),
    )
    op.create_index("idx_salary_structure_line_tenant", "salary_structure_line", ["tenant_id"])
    op.create_index("idx_salary_structure_line_structure", "salary_structure_line", ["salary_structure_id"])

    op.create_table(
        "attendance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id"), nullable=False),
        sa.Column("attendance_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "employee_id", "attendance_date", name="uq_attendance_employee_date"),
        sa.CheckConstraint("status IN ('PRESENT','ABSENT','HALF_DAY','LEAVE','HOLIDAY','WEEK_OFF')", name="ck_attendance_status"),
    )
    op.create_index("idx_attendance_tenant", "attendance", ["tenant_id"])
    op.create_index("idx_attendance_employee_date", "attendance", ["tenant_id", "employee_id", "attendance_date"])

    op.create_table(
        "leave_request",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id"), nullable=False),
        sa.Column("leave_type", sa.String(10), nullable=False),
        sa.Column("from_date", sa.Date, nullable=False),
        sa.Column("to_date", sa.Date, nullable=False),
        sa.Column("days", sa.Numeric(6, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint("leave_type IN ('PAID','UNPAID')", name="ck_leave_type"),
        sa.CheckConstraint("status IN ('PENDING','APPROVED','REJECTED')", name="ck_leave_status"),
        sa.CheckConstraint("to_date >= from_date", name="ck_leave_date_range"),
        sa.CheckConstraint("days > 0", name="ck_leave_days_positive"),
    )
    op.create_index("idx_leave_request_tenant", "leave_request", ["tenant_id"])
    op.create_index("idx_leave_request_employee", "leave_request", ["tenant_id", "employee_id"])

    op.create_table(
        "payroll_period",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("period_label", sa.String(10), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "period_label", name="uq_payroll_period_label"),
        sa.CheckConstraint("status IN ('OPEN','PROCESSING','PROCESSED','FINALIZED','CLOSED')", name="ck_payroll_period_status"),
        sa.CheckConstraint("end_date >= start_date", name="ck_payroll_period_date_range"),
    )
    op.create_index("idx_payroll_period_tenant", "payroll_period", ["tenant_id"])

    op.create_table(
        "payroll_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("payroll_period_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_period.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("employee_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_gross", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_deductions", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_net", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accounting_posting_reference", sa.String(100), nullable=True),
        sa.Column("reversal_of_payroll_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["reversal_of_payroll_run_id"], ["payroll_run.id"]),
        sa.CheckConstraint("status IN ('DRAFT','CALCULATED','FINALIZED','REVERSED')", name="ck_payroll_run_status"),
    )
    op.create_index("idx_payroll_run_tenant", "payroll_run", ["tenant_id"])
    op.create_index("idx_payroll_run_period", "payroll_run", ["tenant_id", "payroll_period_id"])

    op.create_table(
        "payroll_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("payroll_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_run.id"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id"), nullable=False),
        sa.Column("employee_code_snapshot", sa.String(20), nullable=False),
        sa.Column("employee_name_snapshot", sa.String(200), nullable=False),
        sa.Column("designation_snapshot", sa.String(100), nullable=True),
        sa.Column("salary_structure_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("salary_structure.id"), nullable=True),
        sa.Column("calendar_days", sa.Integer, nullable=False, server_default="0"),
        sa.Column("working_days", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("present_days", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("paid_leave_days", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("unpaid_leave_days", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("payable_days", sa.Numeric(6, 2), nullable=False, server_default="0"),
        sa.Column("gross_earnings", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_deductions", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("net_salary", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("payslip_number", sa.String(30), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("reversal_of_payroll_record_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["reversal_of_payroll_record_id"], ["payroll_record.id"]),
        sa.UniqueConstraint("tenant_id", "payroll_run_id", "employee_id", name="uq_payroll_record_run_employee"),
    )
    op.create_index("idx_payroll_record_tenant", "payroll_record", ["tenant_id"])
    op.create_index("idx_payroll_record_run", "payroll_record", ["payroll_run_id"])
    op.create_index("idx_payroll_record_employee", "payroll_record", ["tenant_id", "employee_id"])

    op.create_table(
        "payroll_record_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("payroll_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payroll_record.id"), nullable=False),
        sa.Column("component_type", sa.String(20), nullable=False),
        sa.Column("component_code", sa.String(30), nullable=False),
        sa.Column("component_name", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("row_version", sa.BigInteger, nullable=False, server_default="1"),
        sa.CheckConstraint("component_type IN ('EARNING','DEDUCTION')", name="ck_payroll_record_line_type"),
    )
    op.create_index("idx_payroll_record_line_tenant", "payroll_record_line", ["tenant_id"])
    op.create_index("idx_payroll_record_line_record", "payroll_record_line", ["payroll_record_id"])

    for table in (
        "employee", "salary_component", "salary_structure", "salary_structure_line", "attendance", "leave_request",
        "payroll_period", "payroll_run", "payroll_record", "payroll_record_line",
    ):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tenant_isolation_{table} ON "{table}" '
            f"USING (tenant_id::text = current_setting('app.tenant_id', true))"
        )

    connection = op.get_bind()

    permission_ids: dict[str, str] = {}
    for code, description in _PAYROLL_PERMISSIONS.items():
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
    for table in (
        "payroll_record_line", "payroll_record", "payroll_run", "payroll_period", "leave_request", "attendance",
        "salary_structure_line", "salary_structure", "salary_component", "employee",
    ):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation_{table} ON "{table}"')
        op.drop_table(table)
    # Permission/role_permission seed rows left in place, matching precedent.
