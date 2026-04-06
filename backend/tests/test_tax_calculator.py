"""Tax calculator: old vs new regime, rebate, suggested investments."""
import pytest
from decimal import Decimal

from app.models.schemas import SalaryBreakup, DeductionItem
from app.services.tax_calculator import calculate_tax, suggest_investments


def test_new_regime_lower_slab():
    salary = SalaryBreakup(gross_salary=Decimal("50000"), ctc=Decimal("600000"))
    deductions = [
        DeductionItem(code="standard_deduction", name="Standard", amount_claimed=Decimal("75000")),
    ]
    row = calculate_tax(salary, Decimal("0"), deductions, "new")
    assert row.regime == "new"
    assert row.taxable_income == Decimal("525000")  # 6L - 75k
    assert row.total_tax >= 0


def test_old_regime_with_80c():
    salary = SalaryBreakup(gross_salary=Decimal("100000"), ctc=Decimal("1200000"))
    deductions = [
        DeductionItem(code="standard_deduction", name="Standard", amount_claimed=Decimal("75000")),
        DeductionItem(code="80C", name="80C", amount_claimed=Decimal("150000")),
        DeductionItem(code="80D", name="80D", amount_claimed=Decimal("25000")),
    ]
    row = calculate_tax(salary, Decimal("0"), deductions, "old")
    assert row.regime == "old"
    assert row.taxable_income == Decimal("975000")  # old std deduction capped at 50k


def test_reported_case_new_zero_old_39000():
    salary = SalaryBreakup(gross_salary=Decimal("0"), ctc=Decimal("800000"))
    deductions = [
        DeductionItem(code="standard_deduction", name="Standard", amount_claimed=Decimal("75000")),
        DeductionItem(code="80C", name="80C", amount_claimed=Decimal("150000")),
        DeductionItem(code="80D", name="80D", amount_claimed=Decimal("25000")),
    ]

    row_new = calculate_tax(salary, Decimal("50000"), deductions, "new")
    row_old = calculate_tax(salary, Decimal("50000"), deductions, "old")

    assert row_new.total_tax == Decimal("0")
    assert row_old.total_tax == Decimal("39000")


def test_suggested_investments():
    salary = SalaryBreakup(gross_salary=Decimal("100000"), ctc=Decimal("1200000"))
    deductions = [DeductionItem(code="80C", name="80C", amount_claimed=Decimal("50000"))]
    suggestions = suggest_investments(salary, Decimal("0"), deductions)
    assert any(s.section == "80C" for s in suggestions)
    assert suggestions[0].suggested_amount == Decimal("100000")
