"""
Unit tests for tax_engine: slabs, deductions, HRA, calculator, optimizer.
Scenarios: 5L no deductions, 10L max 80C, HRA exemption, home loan + NPS, old vs new regime.
"""
import pytest
from decimal import Decimal

from tax_engine.slabs import load_slabs, get_new_regime_slabs, get_old_regime_slabs
from tax_engine.hra import compute_hra_exemption
from tax_engine.deductions import deduction_80c, deduction_80d, deduction_standard, deduction_nps_80ccd_1b, deduction_home_loan_interest
from tax_engine.calculator import compute_tax
from tax_engine.optimizer import optimize_tax
from tax_engine.itr_generator import generate_itr


class TestSlabs:
    def test_load_slabs(self):
        cfg = load_slabs()
        assert "new_regime" in cfg
        assert "old_regime" in cfg
        assert float(cfg["cess_rate"]) == 0.04

    def test_new_regime_slabs(self):
        slabs = get_new_regime_slabs()
        assert len(slabs) >= 7
        assert slabs[0][2] == 0  # first bracket 0%
        assert slabs[0][1] == Decimal("400000")
        assert slabs[1][0] == Decimal("400000")
        assert slabs[1][2] == Decimal("0.05")
        assert slabs[3][0] == Decimal("1200000")
        assert slabs[3][1] == Decimal("1600000")
        assert slabs[3][2] == Decimal("0.15")
        assert slabs[4][0] == Decimal("1600000")
        assert slabs[4][1] == Decimal("2000000")
        assert slabs[4][2] == Decimal("0.20")
        assert slabs[5][0] == Decimal("2000000")
        assert slabs[5][1] == Decimal("2400000")
        assert slabs[5][2] == Decimal("0.25")
        assert slabs[-1][2] == Decimal("0.30")

    def test_old_regime_slabs(self):
        slabs = get_old_regime_slabs()
        assert len(slabs) >= 4


class TestDeductions:
    def test_80c_below_limit(self):
        r = deduction_80c(Decimal("100000"))
        assert r.amount == Decimal("100000")
        assert r.eligible_limit == Decimal("150000")
        assert r.suggestion is not None

    def test_80c_at_limit(self):
        r = deduction_80c(Decimal("150000"))
        assert r.amount == Decimal("150000")
        assert r.suggestion is None

    def test_80c_above_limit(self):
        r = deduction_80c(Decimal("200000"))
        assert r.amount == Decimal("150000")

    def test_standard_deduction(self):
        r = deduction_standard("new")
        assert r.amount == Decimal("75000")

    def test_standard_deduction_old_regime(self):
        r = deduction_standard("old")
        assert r.amount == Decimal("50000")


class TestHRA:
    def test_hra_exemption_metro(self):
        # basic 50k/m = 6L, hra 20k/m = 2.4L, rent 25k/m = 3L
        r = compute_hra_exemption(
            Decimal("600000"), Decimal("240000"), Decimal("300000"), metro=True
        )
        # min(2.4L, 3L, 3L - 0.6L=2.4L) = 2.4L
        assert r.amount == Decimal("240000")

    def test_hra_exemption_no_rent(self):
        r = compute_hra_exemption(Decimal("600000"), Decimal("240000"), Decimal("0"), True)
        assert r.amount == Decimal("0")


class TestCalculator:
    def test_5l_salary_no_deductions(self):
        salary = {"basic": 420000, "hra_received": 180000, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result_old = compute_tax(salary, investments, regime="old")
        result_new = compute_tax(salary, investments, regime="new")
        # Gross = 6L. Old/New: 6L - 75k std = 5.25L taxable.
        assert result_old.taxable_income > 0
        assert result_new.taxable_income > 0
        assert result_old.total_tax >= 0
        assert result_new.total_tax >= 0

    def test_new_regime_standard_deduction_applied(self):
        salary = {"basic": 800000, "hra_received": 0, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result_new = compute_tax(salary, investments, regime="new")
        assert result_new.taxable_income == Decimal("725000")

    def test_new_regime_87a_full_rebate_upto_7l(self):
        # Gross 7.75L -> after std deduction 75k => taxable exactly 7L
        salary = {"basic": 775000, "hra_received": 0, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result_new = compute_tax(salary, investments, regime="new", financial_year="2024-25")

        assert result_new.taxable_income == Decimal("700000")
        assert result_new.rebate_87a == result_new.tax_before_rebate
        assert result_new.tax_after_rebate == Decimal("0")
        assert result_new.total_tax == Decimal("0")

    def test_new_regime_87a_not_allowed_above_7l(self):
        salary = {"basic": 1275000, "hra_received": 0, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result_new = compute_tax(salary, investments, regime="new", financial_year="2025-26")

        assert result_new.taxable_income == Decimal("1200000")
        assert result_new.rebate_87a == Decimal("0")
        assert result_new.total_tax > Decimal("0")

    def test_new_regime_no_rebate_when_slab_income_exceeds_7l_with_capital_gains(self):
        salary = {"basic": 750000, "hra_received": 0, "special_allowance": 0, "other_income": 50000}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result_new = compute_tax(
            salary,
            investments,
            equity_ltcg=Decimal("120000"),
            equity_stcg=Decimal("40000"),
            regime="new",
        )

        assert result_new.slab_income == Decimal("725000")
        assert result_new.rebate_87a == Decimal("0")
        assert result_new.slab_tax_after_rebate == result_new.slab_tax_before_rebate
        assert result_new.ltcg_tax == Decimal("2000")
        assert result_new.stcg_tax == Decimal("6000")
        assert result_new.total_tax_before_cess == Decimal("24250")
        assert result_new.total_tax == Decimal("25220")

    def test_new_regime_rebate_not_applied_to_special_rate_income(self):
        salary = {"basic": 700000, "hra_received": 0, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result_new = compute_tax(
            salary,
            investments,
            capital_gains_stcg=Decimal("100000"),
            regime="new",
            financial_year="2025-26",
        )

        assert result_new.rebate_87a > Decimal("0")
        assert result_new.total_tax > Decimal("0")

    def test_ltcg_tax_rate_is_ten_percent_above_exemption(self):
        salary = {"basic": 0, "hra_received": 0, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result = compute_tax(
            salary,
            investments,
            capital_gains_ltcg=Decimal("200000"),
            regime="new",
            financial_year="2025-26",
        )

        # 2,00,000 LTCG - 1,00,000 exemption = 1,00,000 taxable at 10% => 10,000 tax before cess.
        assert result.tax_before_rebate == Decimal("10000")
        assert result.total_tax == Decimal("10400")

    def test_10l_salary_max_80c(self):
        salary = {"basic": 600000, "hra_received": 240000, "special_allowance": 160000, "other_income": 0}
        # gross ~10L
        investments = {"80C": [150000], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result = compute_tax(salary, investments, regime="old")
        total_ded = result.total_deductions
        assert total_ded >= Decimal("150000")  # 80C + standard deduction
        assert result.taxable_income < result.gross_income

    def test_hra_exemption_case(self):
        salary = {"basic": 480000, "hra_received": 192000, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "nps": 0}
        rent_paid = Decimal("240000")  # annual
        result = compute_tax(salary, investments, rent_paid=rent_paid, metro=True, regime="old")
        # Should have HRA in deduction breakup
        sections = [r.section for r in result.deduction_breakup]
        assert "HRA" in sections

    def test_home_loan_and_nps(self):
        salary = {"basic": 720000, "hra_received": 288000, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [100000], "80D_self": 15000, "nps": 50000}
        result = compute_tax(
            salary, investments,
            home_loan_interest=Decimal("180000"),
            regime="old",
        )
        sections = [r.section for r in result.deduction_breakup]
        assert "24(b)" in sections or "24b" in str(sections).lower()
        nps_ded = [r for r in result.deduction_breakup if "80CCD" in r.section or "NPS" in r.section]
        assert len(nps_ded) >= 1

    def test_compare_old_vs_new_regime(self):
        salary = {"basic": 840000, "hra_received": 336000, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [150000], "80D_self": 25000, "nps": 0}
        opt = optimize_tax(salary, investments)
        assert opt.tax_old >= 0
        assert opt.tax_new >= 0
        assert opt.recommended_regime in ("old", "new")
        assert opt.savings_if_switch == abs(opt.tax_old - opt.tax_new)

    def test_new_regime_slab_breakup_for_1795000_taxable_income(self):
        salary = {"basic": 1870000, "hra_received": 0, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result = compute_tax(salary, investments, regime="new")

        assert result.taxable_income == Decimal("1795000")
        assert [b["tax_amount"] for b in result.slab_breakup] == [
            Decimal("0"),
            Decimal("20000"),
            Decimal("40000"),
            Decimal("60000"),
            Decimal("39000"),
        ]
        assert result.tax_before_rebate == Decimal("159000")
        assert result.total_tax == Decimal("165360")

    def test_lta_exemption_applies_in_old_regime(self):
        salary = {"basic": 600000, "hra_received": 240000, "special_allowance": 120000, "other_income": 0}
        investments = {"80C": [], "80D_self": 0, "80D_parents": 0, "nps": 0}
        without_lta = compute_tax(salary, investments, lta_exempt=Decimal("0"), regime="old")
        with_lta = compute_tax(salary, investments, lta_exempt=Decimal("30000"), regime="old")

        assert with_lta.taxable_income < without_lta.taxable_income
        assert any(r.section == "10(5) LTA" for r in with_lta.deduction_breakup)

    def test_80d_parents_is_included_in_total_deductions(self):
        salary = {"basic": 600000, "hra_received": 0, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [], "80D_self": 15000, "80D_parents": 10000, "nps": 0}
        result = compute_tax(salary, investments, regime="old")

        assert result.total_deductions == Decimal("75000")
        assert any(r.section == "80D" and r.amount == Decimal("25000") for r in result.deduction_breakup)

    def test_old_regime_other_income_is_added_before_deductions(self):
        salary = {"basic": 631000, "hra_received": 0, "special_allowance": 0, "other_income": 20000}
        investments = {"80C": [100000], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result = compute_tax(salary, investments, regime="old")

        assert result.gross_income == Decimal("651000")
        assert result.total_deductions == Decimal("150000")
        assert result.taxable_income == Decimal("501000")

    def test_old_regime_80c_counted_exactly_once(self):
        salary = {"basic": 631000, "hra_received": 0, "special_allowance": 0, "other_income": 20000}
        investments = {"80C": [100000], "80D_self": 0, "80D_parents": 0, "nps": 0}
        result = compute_tax(salary, investments, regime="old")

        deduction_80c_rows = [r for r in result.deduction_breakup if r.section == "80C"]
        assert len(deduction_80c_rows) == 1
        assert deduction_80c_rows[0].amount == Decimal("100000")
        assert result.total_deductions == Decimal("150000")


class TestITRGenerator:
    def test_generate_itr_structure(self):
        salary = {"basic": 600000, "hra_received": 240000, "special_allowance": 0, "other_income": 0}
        investments = {"80C": [100000], "80D_self": 10000, "nps": 0}
        itr = generate_itr(salary, investments)
        assert "total_income" in itr
        assert "gross_income" in itr
        assert "total_deductions" in itr
        assert "taxable_income" in itr
        assert "tax_payable" in itr
        assert "regime_selected" in itr
        assert "deduction_breakup" in itr
        assert itr["regime_selected"] in ("old", "new")
