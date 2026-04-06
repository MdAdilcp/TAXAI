"""Generate ITR-ready JSON output from computation result."""
from decimal import Decimal
from typing import Any

from tax_engine.calculator import compute_tax, TaxResult
from tax_engine.optimizer import optimize_tax


def _serialize_decimal(d: Decimal) -> float:
    return float(d)


def generate_itr(
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
    regime_override: str | None = None,
) -> dict[str, Any]:
    """
    Returns ITR-ready structure with total_income, gross_income, total_deductions,
    taxable_income, tax_payable, regime_selected, and deduction_breakup.
    """
    opt = optimize_tax(
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
    regime = regime_override or opt.recommended_regime
    result = opt.result_old if regime == "old" else opt.result_new

    deduction_breakup = [
        {
            "section": r.section,
            "amount": _serialize_decimal(r.amount),
            "explanation": r.explanation,
            "legal_reference": r.legal_reference,
        }
        for r in result.deduction_breakup
    ]

    return {
        "total_income": _serialize_decimal(result.gross_income),
        "net_salary": _serialize_decimal(result.net_salary),
        "gross_total_income": _serialize_decimal(result.gross_total_income),
        "gross_income": _serialize_decimal(result.gross_income),
        "total_deductions": _serialize_decimal(result.total_deductions),
        "taxable_income": _serialize_decimal(result.taxable_income),
        "tax_before_rebate": _serialize_decimal(result.tax_before_rebate),
        "surcharge": _serialize_decimal(result.surcharge),
        "surcharge_rate_pct": result.surcharge_rate_pct,
        "marginal_relief": _serialize_decimal(result.marginal_relief),
        "rebate_87a": _serialize_decimal(result.rebate_87a),
        "tax_after_rebate": _serialize_decimal(result.tax_after_rebate),
        "cess": _serialize_decimal(result.cess),
        "tax_payable": _serialize_decimal(result.total_tax),
        "effective_rate_pct": result.effective_rate_pct,
        "marginal_rate_pct": result.marginal_rate_pct,
        "surcharge_applies": result.surcharge_applies,
        "rebate_applies": result.rebate_applies,
        "regime_selected": regime,
        "recommended_regime": opt.recommended_regime,
        "deduction_breakup": deduction_breakup,
        "comparison": {
            "tax_under_old_regime": _serialize_decimal(opt.tax_old),
            "tax_under_new_regime": _serialize_decimal(opt.tax_new),
        },
    }
