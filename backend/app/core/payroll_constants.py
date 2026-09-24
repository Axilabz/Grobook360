"""Payroll shared constants (PROMPT-029). Mirrors `accounting_constants.
py`'s own "default, tenant-editable seed" pattern for `salary_component`
(§9/§10, §56 OD-010/OD-011) — a documented STARTING catalogue, not an
approved final one."""

from app.models.salary_component import DEDUCTION, EARNING, FIXED_AMOUNT, PERCENTAGE

BASIC = "BASIC"
HRA = "HRA"
ALLOWANCE = "ALLOWANCE"
OTHER_DEDUCTION = "OTHER_DEDUCTION"

# code -> (name, component_type, default_calculation_type)
DEFAULT_SALARY_COMPONENT_SEED: dict[str, tuple[str, str, str]] = {
    BASIC: ("Basic Salary", EARNING, FIXED_AMOUNT),
    HRA: ("House Rent Allowance", EARNING, PERCENTAGE),
    ALLOWANCE: ("Other Allowance", EARNING, FIXED_AMOUNT),
    OTHER_DEDUCTION: ("Other Deduction", DEDUCTION, FIXED_AMOUNT),
}
