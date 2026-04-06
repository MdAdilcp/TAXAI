"""
Compare old vs new regime; recommend best regime; suggest additional investment to reduce tax.
"""
from decimal import Decimal
from dataclasses import dataclass
from typing import Any

from tax_engine.calculator import compute_tax, TaxResult
from tax_engine.deductions import deduction_80c, deduction_80d, deduction_nps_80ccd_1b
from tax_engine.slabs import get_section_limits


@dataclass
class OptimizationResult:
    recommended_regime: str
    tax_old: Decimal
    tax_new: Decimal
    savings_if_switch: Decimal
    result_old: TaxResult
    result_new: TaxResult
    suggested_investments: list[dict[str, Any]]


def optimize_tax(
    salary: dict[str, Any],
    investments: dict[str, Any],
    rent_paid: Decimal = Decimal("0"),
    lta_exempt: Decimal = Decimal("0"),
    other_section10_exemptions: Decimal = Decimal("0"),
    home_loan_interest: Decimal = Decimal("0"),
    savings_interest: Decimal = Decimal("0"),
    house_property_income: Decimal = Decimal("0"),
    business_income: Decimal = Decimal("0"),
    other_sources_income: Decimal = Decimal("0"),
    dividend_income: Decimal = Decimal("0"),
    capital_gains_stcg: Decimal = Decimal("0"),
    capital_gains_stcg_pre_23_jul_2024: Decimal = Decimal("0"),
    capital_gains_stcg_post_23_jul_2024: Decimal = Decimal("0"),
    capital_gains_ltcg: Decimal = Decimal("0"),
    equity_stcg: Decimal | None = None,
    equity_ltcg: Decimal | None = None,
    employer_nps_80ccd2: Decimal = Decimal("0"),
    education_loan_interest_80e: Decimal = Decimal("0"),
    electric_vehicle_loan_interest_80eeb: Decimal = Decimal("0"),
    donation_80g_50: Decimal = Decimal("0"),
    donation_80g_100: Decimal = Decimal("0"),
    rent_paid_80gg: Decimal = Decimal("0"),
    claim_80gg: bool = False,
    self_is_senior: bool = False,
    parents_are_senior: bool = False,
    professional_tax_paid: Decimal = Decimal("0"),
    metro: bool = True,
    financial_year: str | None = None,
) -> OptimizationResult:
    """
    Compute tax under both regimes; recommend regime; suggest additional 80C/80D/NPS if beneficial under old.
    """
    compute_kwargs = dict(
        salary=salary,
        investments=investments,
        rent_paid=rent_paid,
        lta_exempt=lta_exempt,
        other_section10_exemptions=other_section10_exemptions,
        home_loan_interest=home_loan_interest,
        savings_interest=savings_interest,
        house_property_income=house_property_income,
        business_income=business_income,
        other_sources_income=other_sources_income,
        dividend_income=dividend_income,
        capital_gains_stcg=capital_gains_stcg,
        capital_gains_stcg_pre_23_jul_2024=capital_gains_stcg_pre_23_jul_2024,
        capital_gains_stcg_post_23_jul_2024=capital_gains_stcg_post_23_jul_2024,
        capital_gains_ltcg=capital_gains_ltcg,
        equity_stcg=equity_stcg,
        equity_ltcg=equity_ltcg,
        employer_nps_80ccd2=employer_nps_80ccd2,
        education_loan_interest_80e=education_loan_interest_80e,
        electric_vehicle_loan_interest_80eeb=electric_vehicle_loan_interest_80eeb,
        donation_80g_50=donation_80g_50,
        donation_80g_100=donation_80g_100,
        rent_paid_80gg=rent_paid_80gg,
        claim_80gg=claim_80gg,
        self_is_senior=self_is_senior,
        parents_are_senior=parents_are_senior,
        professional_tax_paid=professional_tax_paid,
        metro=metro,
        financial_year=financial_year,
    )
    result_old = compute_tax(**compute_kwargs, regime="old")
    result_new = compute_tax(**compute_kwargs, regime="new")
    tax_old = result_old.total_tax
    tax_new = result_new.total_tax
    recommended = "new" if tax_new <= tax_old else "old"
    savings_if_switch = abs(tax_old - tax_new)

    suggested: list[dict[str, Any]] = []
    limits = get_section_limits()
    inv_80c = investments.get("80C") or []
    total_80c = sum(Decimal(str(x)) for x in (inv_80c if isinstance(inv_80c, list) else [inv_80c]))
    limit_80c = limits.get("section_80c_limit", Decimal("150000"))
    if total_80c < limit_80c and result_old.taxable_income > 0:
        shortfall_80c = limit_80c - total_80c
        suggested.append({
            "section": "80C",
            "current_claim": float(total_80c),
            "max_deduction": float(limit_80c),
            "suggested_additional": float(shortfall_80c),
            "message": f"Invest ₹{shortfall_80c} more in 80C (ELSS/PPF/LIC) to maximize deduction.",
        })
    self_80d = Decimal(str(investments.get("80D_self", 0)))
    limit_80d = limits.get("section_80d_self", Decimal("25000"))
    if self_80d < limit_80d:
        suggested.append({
            "section": "80D",
            "current_claim": float(self_80d),
            "max_deduction": float(limit_80d),
            "suggested_additional": float(limit_80d - self_80d),
            "message": f"Consider health insurance premium up to ₹{limit_80d - self_80d} more for 80D.",
        })
    nps = Decimal(str(investments.get("nps", 0)))
    limit_nps = limits.get("section_80ccd_1b", Decimal("50000"))
    if nps < limit_nps:
        suggested.append({
            "section": "80CCD(1B)",
            "current_claim": float(nps),
            "max_deduction": float(limit_nps),
            "suggested_additional": float(limit_nps - nps),
            "message": f"NPS additional contribution up to ₹{limit_nps - nps} for extra deduction.",
        })

    return OptimizationResult(
        recommended_regime=recommended,
        tax_old=tax_old,
        tax_new=tax_new,
        savings_if_switch=savings_if_switch,
        result_old=result_old,
        result_new=result_new,
        suggested_investments=suggested,
    )
