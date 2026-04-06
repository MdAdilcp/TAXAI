"""Unit tests for deduction engine — core deductions for synthetic profiles."""
import pytest
from decimal import Decimal

from app.models.schemas import SalaryBreakup, DeductionItem
from app.services.deduction_engine import rule_based_deductions, rank_deductions_by_impact


def test_standard_deduction_and_pt():
    salary = SalaryBreakup(
        gross_salary=Decimal("80000"),
        professional_tax=Decimal("200"),
        basic=Decimal("40000"),
        hra=Decimal("0"),
    )
    deductions = rule_based_deductions(salary, [], {"metro": True})
    codes = [d.code for d in deductions]
    assert "standard_deduction" in codes
    assert "professional_tax" in codes


def test_80c_from_parsed_docs():
    salary = SalaryBreakup(gross_salary=Decimal("100000"), basic=Decimal("50000"), hra=Decimal("0"))
    docs = [{"section": "80C", "amount": 100000}, {"section": "80C", "amount": 50000}]
    deductions = rule_based_deductions(salary, docs, {})
    eighty_c = [d for d in deductions if d.code == "80C"]
    assert len(eighty_c) == 1
    assert eighty_c[0].amount_claimed == Decimal("150000")
    assert eighty_c[0].max_allowed == Decimal("150000")


def test_hra_exemption():
    salary = SalaryBreakup(
        basic=Decimal("50000"),
        hra=Decimal("20000"),
        gross_salary=Decimal("88000"),
    )
    docs = [{"rent_amount": 25000}]
    deductions = rule_based_deductions(salary, docs, {"metro": True})
    hra = [d for d in deductions if d.code == "HRA"]
    assert len(hra) == 1
    assert hra[0].amount_claimed > 0


def test_ranking_orders_by_impact():
    items = [
        DeductionItem(code="80C", name="80C", amount_claimed=Decimal("150000"), confidence=0.9),
        DeductionItem(code="80D", name="80D", amount_claimed=Decimal("25000"), confidence=0.95),
    ]
    ranked = rank_deductions_by_impact(items, {"annual_income": 1000000}, [])
    assert len(ranked) == 2
    assert ranked[0].code == "80C"
