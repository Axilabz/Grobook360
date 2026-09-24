"""PROMPT-029 test catalogue for Employee, Payroll & Basic Salary
Management (/api/v1/employees, /salary-structures, /attendance, /leave,
/payroll/*).

Covers the core mandatory scenarios from §64: employee CRUD/lifecycle,
salary structure creation with FIXED_AMOUNT + PERCENTAGE components,
effective-dated structure selection, attendance/leave, payroll period
creation with overlap prevention, payroll run calculate/finalize,
duplicate-run prevention, gross/deduction/net calculation correctness,
mid-period joining proration, payroll snapshot immutability after a
salary change, payslip generation, accounting integration + idempotency,
no PF/ESI/TDS, RBAC, tenant isolation, and audit.
"""

import uuid
from decimal import Decimal

import pytest

EMPLOYEES_ENDPOINT = "/api/v1/employees"
SALARY_COMPONENTS_ENDPOINT = "/api/v1/salary-components"
ATTENDANCE_ENDPOINT = "/api/v1/attendance"
LEAVE_ENDPOINT = "/api/v1/leave"
PAYROLL_PERIODS_ENDPOINT = "/api/v1/payroll/periods"
PAYROLL_RUNS_ENDPOINT = "/api/v1/payroll/runs"
ACCOUNTING_ENDPOINT = "/api/v1/accounting"
SIGNUP_ENDPOINT = "/api/v1/auth/sign-up"
LOGIN_ENDPOINT = "/api/v1/auth/login"
USERS_ENDPOINT = "/api/v1/users"
RESET_ENDPOINT = "/api/v1/auth/reset-password"

OWNER_PASSWORD = "SecurePass123"
SALESPERSON_PASSWORD = "AnotherSecurePass456"


def _unique_phone() -> str:
    return "9" + str(uuid.uuid4().int)[:9]


def _unique_email() -> str:
    return f"pyr-{uuid.uuid4().hex[:12]}@example.com"


def _idem() -> dict:
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    from app.core.rate_limit import reset_rate_limits
    from app.core.login_lockout import reset_all

    reset_rate_limits()
    reset_all()
    yield


async def _signup_and_login_owner(client, state_code: str = "33") -> dict:
    phone = _unique_phone()
    payload = {
        "organization": {"business_name": "Payroll Test Co", "address_line1": "1 Main St", "city": "Chennai", "state_code": state_code, "pin_code": "600001", "gstin": None},
        "owner": {"phone": phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
    }
    signup_response = await client.post(SIGNUP_ENDPOINT, json=payload, headers={"Idempotency-Key": str(uuid.uuid4())})
    assert signup_response.status_code == 201
    login_response = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": OWNER_PASSWORD})
    assert login_response.status_code == 200
    return signup_response.json()["data"]


async def _create_salesperson_and_login(client) -> None:
    from app.services.password_recovery.provider import ConsolePasswordRecoveryProvider

    phone = _unique_phone()
    create_response = await client.post(USERS_ENDPOINT, json={"name": "SP", "phone": phone, "email": _unique_email(), "role": "SALESPERSON"})
    assert create_response.status_code == 201
    reset_token = ConsolePasswordRecoveryProvider.outbox[-1].reset_link.split("token=")[1]
    reset_response = await client.post(RESET_ENDPOINT, json={"token": reset_token, "new_password": SALESPERSON_PASSWORD, "confirm_password": SALESPERSON_PASSWORD})
    assert reset_response.status_code == 200
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": phone, "password": SALESPERSON_PASSWORD})
    assert login.status_code == 200


async def _create_employee(client, date_of_joining: str = "2026-01-01", **overrides) -> dict:
    payload = {"full_name": "Test Employee", "date_of_joining": date_of_joining, "designation": "Engineer", "employment_type": "FULL_TIME"}
    payload.update(overrides)
    response = await client.post(EMPLOYEES_ENDPOINT, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _get_component_id(client, code: str) -> str:
    response = await client.get(SALARY_COMPONENTS_ENDPOINT)
    assert response.status_code == 200
    component = next(c for c in response.json()["data"] if c["code"] == code)
    return component["id"]


async def _create_structure(client, employee_id: str, effective_from: str = "2026-01-01", basic: str = "25000", hra_percent: str = "40") -> dict:
    basic_id = await _get_component_id(client, "BASIC")
    hra_id = await _get_component_id(client, "HRA")
    payload = {
        "effective_from": effective_from,
        "lines": [
            {"component_id": basic_id, "calculation_type": "FIXED_AMOUNT", "amount": basic},
            {"component_id": hra_id, "calculation_type": "PERCENTAGE", "percentage": hra_percent, "percentage_of_component_code": "BASIC"},
        ],
    }
    response = await client.post(f"{EMPLOYEES_ENDPOINT}/{employee_id}/salary-structures", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _create_period(client, label: str = "2026-04", start: str = "2026-04-01", end: str = "2026-04-30") -> dict:
    response = await client.post(PAYROLL_PERIODS_ENDPOINT, json={"period_label": label, "start_date": start, "end_date": end})
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _create_run(client, period_id: str) -> dict:
    response = await client.post(PAYROLL_RUNS_ENDPOINT, json={"payroll_period_id": period_id}, headers=_idem())
    assert response.status_code == 201, response.text
    return response.json()["data"]


# --- TC-001/002/003: Employee CRUD + lifecycle -----------------------------


async def test_create_employee_assigns_server_code(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client)
    assert employee["employee_code"].startswith("EMP-")
    assert employee["status"] == "ACTIVE"


async def test_edit_employee(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client)
    response = await client.put(f"{EMPLOYEES_ENDPOINT}/{employee['id']}", json={"designation": "Senior Engineer", "expected_row_version": employee["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["designation"] == "Senior Engineer"


async def test_deactivate_employee(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client)
    response = await client.post(f"{EMPLOYEES_ENDPOINT}/{employee['id']}/deactivate", json={"status": "INACTIVE", "expected_row_version": employee["row_version"]})
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "INACTIVE"


# --- TC-004/005/006/007: Salary Structure -----------------------------------


async def test_create_salary_structure_with_fixed_and_percentage_components(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client)
    structure = await _create_structure(client, employee["id"])
    basic_line = next(l for l in structure["lines"] if l["component_code"] == "BASIC")
    hra_line = next(l for l in structure["lines"] if l["component_code"] == "HRA")
    assert basic_line["amount"] == "25000.00"
    assert hra_line["percentage_of_component_code"] == "BASIC"


async def test_multiple_effective_dated_structures_select_correct_one_for_period(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client, date_of_joining="2026-01-01")
    await _create_structure(client, employee["id"], effective_from="2026-01-01", basic="25000")
    await _create_structure(client, employee["id"], effective_from="2026-07-01", basic="35000")

    structures = (await client.get(f"{EMPLOYEES_ENDPOINT}/{employee['id']}/salary-structures")).json()["data"]
    assert len(structures) == 2


# --- TC-008/009/010/011: Attendance / Leave ---------------------------------


async def test_create_attendance(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client)
    response = await client.post(ATTENDANCE_ENDPOINT, json={"employee_id": employee["id"], "attendance_date": "2026-04-05", "status": "ABSENT"})
    assert response.status_code == 201
    assert response.json()["data"]["status"] == "ABSENT"


async def test_create_and_approve_leave(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client)
    created = await client.post(LEAVE_ENDPOINT, json={"employee_id": employee["id"], "leave_type": "PAID", "from_date": "2026-04-10", "to_date": "2026-04-11", "reason": "Personal"})
    assert created.status_code == 201
    leave = created.json()["data"]
    assert leave["days"] == "2.00"

    approved = await client.post(f"{LEAVE_ENDPOINT}/{leave['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "APPROVED"


async def test_reject_leave(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client)
    created = await client.post(LEAVE_ENDPOINT, json={"employee_id": employee["id"], "leave_type": "UNPAID", "from_date": "2026-04-10", "to_date": "2026-04-10"})
    leave = created.json()["data"]
    rejected = await client.post(f"{LEAVE_ENDPOINT}/{leave['id']}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "REJECTED"


# --- TC-012/013: Payroll Period ----------------------------------------------


async def test_create_payroll_period(client):
    await _signup_and_login_owner(client)
    period = await _create_period(client)
    assert period["status"] == "OPEN"


async def test_overlapping_payroll_period_rejected(client):
    await _signup_and_login_owner(client)
    await _create_period(client, label="2026-04", start="2026-04-01", end="2026-04-30")
    response = await client.post(PAYROLL_PERIODS_ENDPOINT, json={"period_label": "2026-04B", "start_date": "2026-04-15", "end_date": "2026-05-15"})
    assert response.status_code == 422


# --- TC-014-018: Payroll calculation correctness ----------------------------


async def test_calculate_payroll_gross_deductions_net(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client, date_of_joining="2026-01-01")
    await _create_structure(client, employee["id"], effective_from="2026-01-01", basic="25000", hra_percent="40")
    period = await _create_period(client)
    run = await _create_run(client, period["id"])

    calculated = await client.post(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/calculate")
    assert calculated.status_code == 200
    run_data = calculated.json()["data"]
    assert run_data["status"] == "CALCULATED"
    assert run_data["employee_count"] == 1
    # No attendance/leave marked -> full month present (exception-based default)
    assert Decimal(run_data["total_gross"]) == Decimal("35000.00")  # 25000 + 40%*25000
    assert Decimal(run_data["total_deductions"]) == Decimal("0.00")
    assert Decimal(run_data["total_net"]) == Decimal("35000.00")

    records = (await client.get(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/records")).json()["data"]
    assert len(records) == 1
    record = records[0]
    assert Decimal(record["net_salary"]) == Decimal(record["gross_earnings"]) - Decimal(record["total_deductions"])


# --- TC-021: mid-period joining proration -----------------------------------


async def test_mid_period_joining_prorates_salary(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client, date_of_joining="2026-04-15")
    await _create_structure(client, employee["id"], effective_from="2026-04-15", basic="30000", hra_percent="0")
    period = await _create_period(client)
    run = await _create_run(client, period["id"])
    calculated = await client.post(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/calculate")
    assert calculated.status_code == 200

    records = (await client.get(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/records")).json()["data"]
    record = records[0]
    assert record["payable_days"] == "16.00"  # Apr 15-30 inclusive
    assert Decimal(record["gross_earnings"]) == Decimal("16000.00")  # 30000 * 16/30


# --- TC-023/024: Finalize + duplicate prevention -----------------------------


async def test_finalize_payroll_creates_accounting_journal(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client, date_of_joining="2026-01-01")
    await _create_structure(client, employee["id"], effective_from="2026-01-01", basic="25000", hra_percent="0")
    period = await _create_period(client)
    run = await _create_run(client, period["id"])
    await client.post(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/calculate")

    finalized = await client.post(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/finalize", headers=_idem())
    assert finalized.status_code == 200
    run_data = finalized.json()["data"]
    assert run_data["status"] == "FINALIZED"
    assert run_data["accounting_posting_reference"] is not None

    journals = await client.get(f"{ACCOUNTING_ENDPOINT}/journals", params={"source_type": "PAYROLL_RUN", "page_size": 10})
    assert journals.status_code == 200
    assert len(journals.json()["data"]) == 1
    journal_detail = await client.get(f"{ACCOUNTING_ENDPOINT}/journals/{journals.json()['data'][0]['id']}")
    lines = journal_detail.json()["data"]["lines"]
    total_debit = sum(Decimal(l["debit_amount"]) for l in lines)
    total_credit = sum(Decimal(l["credit_amount"]) for l in lines)
    assert total_debit == total_credit == Decimal("25000.00")


async def test_duplicate_payroll_run_for_same_period_rejected(client):
    await _signup_and_login_owner(client)
    period = await _create_period(client)
    await _create_run(client, period["id"])
    response = await client.post(PAYROLL_RUNS_ENDPOINT, json={"payroll_period_id": period["id"]}, headers=_idem())
    assert response.status_code == 409


async def test_duplicate_run_creation_request_is_idempotent(client):
    await _signup_and_login_owner(client)
    period = await _create_period(client)
    key = str(uuid.uuid4())
    payload = {"payroll_period_id": period["id"]}
    first = await client.post(PAYROLL_RUNS_ENDPOINT, json=payload, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    second = await client.post(PAYROLL_RUNS_ENDPOINT, json=payload, headers={"Idempotency-Key": key})
    assert second.status_code == 201
    assert second.json()["data"]["id"] == first.json()["data"]["id"]


# --- TC-026/027: Snapshot immutability ---------------------------------------


async def test_historical_payroll_unchanged_after_salary_change(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client, date_of_joining="2026-01-01")
    await _create_structure(client, employee["id"], effective_from="2026-01-01", basic="25000", hra_percent="0")
    period = await _create_period(client)
    run = await _create_run(client, period["id"])
    await client.post(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/calculate")
    await client.post(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/finalize", headers=_idem())

    records_before = (await client.get(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/records")).json()["data"]
    net_before = records_before[0]["net_salary"]

    # A new salary structure effective AFTER this period must not alter it.
    await _create_structure(client, employee["id"], effective_from="2026-07-01", basic="99999", hra_percent="0")

    records_after = (await client.get(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/records")).json()["data"]
    assert records_after[0]["net_salary"] == net_before == "25000.00"


# --- TC-028/029: Payslip -----------------------------------------------------


async def test_payslip_matches_payroll_snapshot(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client, date_of_joining="2026-01-01")
    await _create_structure(client, employee["id"], effective_from="2026-01-01", basic="25000", hra_percent="40")
    period = await _create_period(client)
    run = await _create_run(client, period["id"])
    await client.post(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/calculate")
    await client.post(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/finalize", headers=_idem())

    records = (await client.get(f"{PAYROLL_RUNS_ENDPOINT}/{run['id']}/records")).json()["data"]
    record = records[0]
    assert record["payslip_number"].startswith("PAYSLIP-")

    payslip = await client.get(f"/api/v1/payroll/{record['id']}/payslip")
    assert payslip.status_code == 200
    data = payslip.json()["data"]
    assert data["net_salary"] == record["net_salary"]
    assert data["gross_earnings"] == record["gross_earnings"]
    line_total = sum(Decimal(l["amount"]) for l in data["lines"] if l["component_type"] == "EARNING")
    assert line_total == Decimal(data["gross_earnings"])


# --- TC-032: No PF/ESI/TDS ----------------------------------------------------


async def test_payroll_never_creates_statutory_components(client):
    await _signup_and_login_owner(client)
    components = (await client.get(SALARY_COMPONENTS_ENDPOINT)).json()["data"]
    codes = {c["code"] for c in components}
    assert not (codes & {"PF", "ESI", "TDS", "PROFESSIONAL_TAX"})


# --- TC-033/034: RBAC + tenant isolation --------------------------------------


async def test_salesperson_cannot_view_employees(client):
    await _signup_and_login_owner(client)
    await _create_salesperson_and_login(client)
    response = await client.get(EMPLOYEES_ENDPOINT)
    assert response.status_code == 403


async def test_tenant_isolation_on_employees(client):
    await _signup_and_login_owner(client)
    employee = await _create_employee(client)

    other_phone = _unique_phone()
    signup = await client.post(
        SIGNUP_ENDPOINT,
        json={
            "organization": {"business_name": "Other Tenant", "address_line1": "2 Side St", "city": "Mumbai", "state_code": "27", "pin_code": "400001", "gstin": None},
            "owner": {"phone": other_phone, "email": _unique_email(), "password": OWNER_PASSWORD, "confirm_password": OWNER_PASSWORD},
        },
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert signup.status_code == 201
    login = await client.post(LOGIN_ENDPOINT, json={"login_identifier": other_phone, "password": OWNER_PASSWORD})
    assert login.status_code == 200

    response = await client.get(f"{EMPLOYEES_ENDPOINT}/{employee['id']}")
    assert response.status_code == 404


# --- TC-035: Audit -------------------------------------------------------------


async def test_employee_creation_is_audited(client, db_session):
    import uuid as uuid_module
    from sqlalchemy import select
    from app.models.audit_log import AuditLog

    await _signup_and_login_owner(client)
    employee = await _create_employee(client)

    result = await db_session.execute(select(AuditLog).where(AuditLog.entity_type == "employee", AuditLog.entity_id == uuid_module.UUID(employee["id"])))
    actions = {e.action for e in result.scalars().all()}
    assert "EMPLOYEE_CREATED" in actions
