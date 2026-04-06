"""
Tax computation core for FY 2025-26 / AY 2026-27.
Implements separated slab income and special-rate capital gains logic,
standard deduction, regime-specific deductions, rebate u/s 87A, cess,
and summary metrics.
"""
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Any

from tax_engine.slabs import (
    get_new_regime_slabs,
    get_old_regime_slabs,
    get_cess_rate,
    get_standard_deduction,
)
from tax_engine.hra import compute_hra_exemption
from tax_engine.deductions import (
    deduction_80c,
    deduction_80d,
    deduction_nps_80ccd_1b,
    deduction_employer_nps_80ccd_2,
    deduction_home_loan_interest,
    deduction_80tta,
    deduction_80ttb,
    deduction_80e,
    deduction_80eeb,
    deduction_80g,
    deduction_80gg,
    professional_tax,
    lta_exemption,
    DeductionResult,
)


def _d(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v)) if v is not None else Decimal("0")


def _tax_from_slabs(income: Decimal, slabs: list[tuple[Decimal, Decimal, Decimal]]) -> Decimal:
    tax = Decimal("0")
    for low, high, rate in slabs:
        if income <= low:
            break
        bracket = min(income, high) - low
        if bracket > 0:
            tax += bracket * rate
    return tax


def _last_slab_rate(income: Decimal, slabs: list[tuple[Decimal, Decimal, Decimal]]) -> Decimal:
    rate = Decimal("0")
    for low, _high, slab_rate in slabs:
        if income > low:
            rate = slab_rate
        else:
            break
    return rate


@dataclass
class TaxResult:
    regime: str
    slab_income: Decimal
    net_salary: Decimal
    gross_total_income: Decimal
    gross_income: Decimal
    total_deductions: Decimal
    taxable_income: Decimal
    slab_tax_before_rebate: Decimal
    tax_before_rebate: Decimal
    stcg_tax: Decimal
    ltcg_tax: Decimal
    surcharge: Decimal
    surcharge_rate_pct: float
    marginal_relief: Decimal
    rebate_87a: Decimal
    slab_tax_after_rebate: Decimal
    total_tax_before_cess: Decimal
    tax_after_rebate: Decimal
    cess: Decimal
    total_tax: Decimal
    effective_rate_pct: float
    marginal_rate_pct: float
    surcharge_applies: bool
    rebate_applies: bool
    deduction_breakup: list[DeductionResult] = field(default_factory=list)
    slab_breakup: list[dict[str, Any]] = field(default_factory=list)


def _compute_slab_breakup(income: Decimal, slabs: list[tuple[Decimal, Decimal, Decimal]]) -> list[dict[str, Any]]:
    breakdown: list[dict[str, Any]] = []
    safe_income = max(Decimal("0"), income)
    for low, high, rate in slabs:
        if safe_income <= low:
            break
        taxable_at_rate = min(safe_income, high) - low
        if taxable_at_rate <= 0:
            continue
        tax_amount = taxable_at_rate * rate
        breakdown.append({
            "lower": low,
            "upper": high,
            "rate": rate,
            "taxable_at_rate": taxable_at_rate,
            "tax_amount": tax_amount,
        })
    return breakdown


def _compute_salary_exemptions_old(
    salary: dict[str, Any],
    rent_paid: Decimal,
    lta_exempt: Decimal,
    other_section10_exemptions: Decimal,
    metro: bool,
) -> tuple[Decimal, list[DeductionResult]]:
    results: list[DeductionResult] = []
    basic = _d(salary.get("basic", 0))
    hra_received = _d(salary.get("hra_received", 0))

    if hra_received > 0 and rent_paid > 0 and basic > 0:
        hra_res = compute_hra_exemption(basic, hra_received, rent_paid, metro)
        results.append(DeductionResult(
            section="HRA",
            amount=hra_res.amount,
            explanation=hra_res.explanation,
            legal_reference=hra_res.legal_reference,
            eligible_limit=hra_received,
        ))

    if lta_exempt > 0:
        results.append(lta_exemption(lta_exempt))

    if other_section10_exemptions > 0:
        results.append(DeductionResult(
            section="Other Section 10 exemptions",
            amount=other_section10_exemptions,
            explanation=f"Other Section 10 salary exemptions claimed: ₹{other_section10_exemptions}.",
            legal_reference="Income Tax Act 1961, Section 10.",
            eligible_limit=None,
        ))

    return sum(r.amount for r in results), results


def _compute_deductions(
    regime: str,
    net_salary: Decimal,
    investments: dict[str, Any],
    home_loan_interest: Decimal,
    savings_interest: Decimal,
    professional_tax_paid: Decimal,
    employer_nps_80ccd2: Decimal,
    education_loan_interest_80e: Decimal,
    electric_vehicle_loan_interest_80eeb: Decimal,
    donation_80g_50: Decimal,
    donation_80g_100: Decimal,
    rent_paid_80gg: Decimal,
    claim_80gg: bool,
    gross_total_income_before_chapter_via: Decimal,
    self_is_senior: bool,
    parents_are_senior: bool,
) -> tuple[Decimal, list[DeductionResult]]:
    results: list[DeductionResult] = []

    standard_limit = get_standard_deduction(regime)
    standard_amt = min(standard_limit, max(Decimal("0"), net_salary))
    results.append(DeductionResult(
        section="standard_deduction",
        amount=standard_amt,
        explanation=f"Standard deduction (salary) ₹{standard_amt} per annum for {regime} regime.",
        legal_reference="Finance Act 2024; applicable from FY 2024-25 onwards.",
        eligible_limit=standard_limit,
    ))

    if regime == "old":
        if professional_tax_paid > 0:
            results.append(professional_tax(professional_tax_paid))

        inv_80c = investments.get("80C") or []
        total_80c = sum(_d(x) for x in (inv_80c if isinstance(inv_80c, list) else [inv_80c]))
        if total_80c > 0:
            results.append(deduction_80c(total_80c))

        self_80d = _d(investments.get("80D_self", 0))
        parents_80d = _d(investments.get("80D_parents", 0))
        if self_80d > 0 or parents_80d > 0:
            results.append(deduction_80d(self_80d, parents_80d, self_is_senior, parents_are_senior))

        nps = _d(investments.get("nps", 0))
        if nps > 0:
            results.append(deduction_nps_80ccd_1b(nps))

        if home_loan_interest > 0:
            results.append(deduction_home_loan_interest(home_loan_interest))

        if education_loan_interest_80e > 0:
            results.append(deduction_80e(education_loan_interest_80e))

        if electric_vehicle_loan_interest_80eeb > 0:
            results.append(deduction_80eeb(electric_vehicle_loan_interest_80eeb))

        if donation_80g_50 > 0:
            results.append(deduction_80g(donation_80g_50, Decimal("0.5")))
        if donation_80g_100 > 0:
            results.append(deduction_80g(donation_80g_100, Decimal("1.0")))

        if claim_80gg and rent_paid_80gg > 0:
            adjusted_income = max(Decimal("0"), gross_total_income_before_chapter_via - standard_amt)
            results.append(deduction_80gg(rent_paid_80gg, adjusted_income))

        if self_is_senior:
            if savings_interest > 0:
                results.append(deduction_80ttb(savings_interest))
        else:
            if savings_interest > 0:
                results.append(deduction_80tta(savings_interest))

    if employer_nps_80ccd2 > 0:
        results.append(deduction_employer_nps_80ccd_2(employer_nps_80ccd2, net_salary, regime))

    return sum(r.amount for r in results), results


def _compute_special_rate_tax(capital_gains_stcg: Decimal, capital_gains_ltcg: Decimal) -> tuple[Decimal, Decimal]:
    stcg_tax = max(Decimal("0"), capital_gains_stcg) * Decimal("0.15")
    ltcg_taxable = max(Decimal("0"), capital_gains_ltcg - Decimal("100000"))
    ltcg_tax = ltcg_taxable * Decimal("0.10")
    highest_rate = Decimal("0")
    if capital_gains_stcg > 0:
        highest_rate = max(highest_rate, Decimal("0.15"))
    if capital_gains_ltcg > 0:
        highest_rate = max(highest_rate, Decimal("0.10"))
    return stcg_tax + ltcg_tax, highest_rate


def calculate_slab_tax(slab_income: Decimal, regime: str) -> tuple[Decimal, list[dict[str, Any]], list[tuple[Decimal, Decimal, Decimal]]]:
    """Calculate slab tax only on normal income, excluding capital gains."""
    slabs = get_new_regime_slabs() if regime == "new" else get_old_regime_slabs()
    safe_income = max(Decimal("0"), slab_income)
    slab_breakup = _compute_slab_breakup(safe_income, slabs)
    slab_tax = _tax_from_slabs(safe_income, slabs)
    return slab_tax, slab_breakup, slabs


def calculate_capital_gains_tax(
    equity_stcg: Decimal = Decimal("0"),
    equity_ltcg: Decimal = Decimal("0"),
) -> tuple[Decimal, Decimal, Decimal]:
    """Calculate special-rate tax for equity STCG u/s 111A and LTCG u/s 112A."""
    stcg_tax = max(Decimal("0"), equity_stcg) * Decimal("0.15")
    ltcg_tax = max(Decimal("0"), equity_ltcg - Decimal("100000")) * Decimal("0.10")
    return stcg_tax, ltcg_tax, stcg_tax + ltcg_tax


def apply_rebate(
    slab_income: Decimal,
    slab_tax: Decimal,
    regime: str,
    financial_year: str | None,
) -> Decimal:
    """Apply 87A rebate only against slab tax, never against capital gains tax."""
    _ = financial_year  # Rebate eligibility here is intentionally based on fixed slab-income thresholds.
    limit_87a = Decimal("700000") if regime == "new" else Decimal("500000")
    rebate_amt = Decimal("25000") if regime == "new" else Decimal("12500")
    taxable_slab_income = max(Decimal("0"), slab_income)
    normal_tax = max(Decimal("0"), slab_tax)
    if normal_tax <= 0:
        return Decimal("0")

    if taxable_slab_income <= limit_87a:
        rebate = min(normal_tax, rebate_amt)
    else:
        rebate = Decimal("0")

    return min(normal_tax, rebate)


def compute_total_tax(slab_tax_after_rebate: Decimal, stcg_tax: Decimal, ltcg_tax: Decimal, cess_rate: Decimal | None = None) -> tuple[Decimal, Decimal, Decimal]:
    """Compute tax + cess in the required order with non-negative guards."""
    cess_rate = get_cess_rate() if cess_rate is None else cess_rate
    taxable_before_cess = max(Decimal("0"), slab_tax_after_rebate) + max(Decimal("0"), stcg_tax) + max(Decimal("0"), ltcg_tax)
    cess = max(Decimal("0"), taxable_before_cess * cess_rate)
    total_tax = max(Decimal("0"), taxable_before_cess + cess)
    return taxable_before_cess, cess, total_tax


def calculate_tax(
    normal_taxable_income: Decimal,
    capital_gains_stcg: Decimal,
    capital_gains_ltcg: Decimal,
    regime: str,
) -> tuple[Decimal, list[dict[str, Any]], list[tuple[Decimal, Decimal, Decimal]], Decimal, Decimal, Decimal]:
    """Compatibility wrapper returning slab tax and capital gains tax separately."""
    slab_tax, slab_breakup, slabs = calculate_slab_tax(normal_taxable_income, regime)
    stcg_tax, ltcg_tax, special_tax = calculate_capital_gains_tax(capital_gains_stcg, capital_gains_ltcg)
    return slab_tax, slab_breakup, slabs, stcg_tax, ltcg_tax, special_tax


def compute_tax(
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
    regime: str = "old",
    financial_year: str | None = None,
) -> TaxResult:
    basic = _d(salary.get("basic", 0))
    hra_received = _d(salary.get("hra_received", 0))
    special_allowance = _d(salary.get("special_allowance", 0))
    other_allowance = _d(salary.get("other_allowance", 0)) or _d(salary.get("other_allowances", 0))
    perquisites = _d(salary.get("perquisites", 0)) or _d(salary.get("perquisites_u_s_17_2", 0))
    profits_in_lieu = _d(salary.get("profits_in_lieu", 0)) or _d(salary.get("profits_in_lieu_u_s_17_3", 0))
    salary_other_income = _d(salary.get("other_income", 0))

    gross_salary = basic + hra_received + special_allowance + other_allowance + perquisites + profits_in_lieu
    if gross_salary <= 0 and salary.get("gross_annual"):
        gross_salary = _d(salary.get("gross_annual", 0))

    if regime == "old":
        salary_exemptions_total, exemption_breakup = _compute_salary_exemptions_old(
            salary, _d(rent_paid), _d(lta_exempt), _d(other_section10_exemptions), metro,
        )
    else:
        salary_exemptions_total, exemption_breakup = Decimal("0"), []

    net_salary = max(Decimal("0"), gross_salary - salary_exemptions_total)
    normal_other_heads = _d(house_property_income) + _d(business_income) + _d(other_sources_income) + _d(dividend_income) + salary_other_income
    legacy_stcg = _d(capital_gains_stcg) + _d(capital_gains_stcg_pre_23_jul_2024) + _d(capital_gains_stcg_post_23_jul_2024)
    legacy_ltcg = _d(capital_gains_ltcg)
    equity_stcg_val = _d(equity_stcg) if equity_stcg is not None else Decimal("0")
    equity_ltcg_val = _d(equity_ltcg) if equity_ltcg is not None else Decimal("0")
    special_stcg = equity_stcg_val if equity_stcg_val > 0 or legacy_stcg <= 0 else legacy_stcg
    special_ltcg = equity_ltcg_val if equity_ltcg_val > 0 or legacy_ltcg <= 0 else legacy_ltcg
    special_heads_total = special_stcg + special_ltcg
    gross_total_income = net_salary + normal_other_heads + special_heads_total
    gross_income = gross_salary + normal_other_heads + special_heads_total

    chapter_via_total, deduction_breakup = _compute_deductions(
        regime=regime,
        net_salary=net_salary,
        investments=investments,
        home_loan_interest=_d(home_loan_interest),
        savings_interest=_d(savings_interest),
        professional_tax_paid=_d(professional_tax_paid),
        employer_nps_80ccd2=_d(employer_nps_80ccd2),
        education_loan_interest_80e=_d(education_loan_interest_80e),
        donation_80g_50=_d(donation_80g_50),
        donation_80g_100=_d(donation_80g_100),
        rent_paid_80gg=_d(rent_paid_80gg),
        claim_80gg=claim_80gg,
        gross_total_income_before_chapter_via=max(Decimal("0"), net_salary + normal_other_heads),
        self_is_senior=self_is_senior,
        parents_are_senior=parents_are_senior,
        electric_vehicle_loan_interest_80eeb=_d(electric_vehicle_loan_interest_80eeb),
    )

    normal_taxable_income = max(Decimal("0"), net_salary + normal_other_heads - chapter_via_total)
    total_taxable_income = normal_taxable_income + special_heads_total

    slab_tax, slab_breakup, slabs, stcg_tax, ltcg_tax, special_tax = calculate_tax(
        normal_taxable_income,
        special_stcg,
        special_ltcg,
        regime,
    )
    tax_before_rebate = slab_tax + special_tax

    rebate = apply_rebate(
        slab_income=normal_taxable_income,
        slab_tax=slab_tax,
        regime=regime,
        financial_year=financial_year,
    )
    slab_tax_after_rebate = max(Decimal("0"), slab_tax - rebate)
    total_tax_before_cess, cess, total_tax = compute_total_tax(
        slab_tax_after_rebate=slab_tax_after_rebate,
        stcg_tax=stcg_tax,
        ltcg_tax=ltcg_tax,
        cess_rate=get_cess_rate(),
    )
    tax_after_rebate = total_tax_before_cess

    marginal_rate = max(
        _last_slab_rate(normal_taxable_income, slabs),
        Decimal("0.10") if special_ltcg > 0 else Decimal("0.15") if special_stcg > 0 else Decimal("0"),
    )
    effective = (total_tax / gross_income * 100) if gross_income > 0 else Decimal("0")

    return TaxResult(
        regime=regime,
        slab_income=normal_taxable_income,
        net_salary=net_salary,
        gross_total_income=gross_total_income,
        gross_income=gross_income,
        total_deductions=salary_exemptions_total + chapter_via_total,
        taxable_income=total_taxable_income,
        slab_tax_before_rebate=slab_tax,
        tax_before_rebate=tax_before_rebate,
        stcg_tax=stcg_tax,
        ltcg_tax=ltcg_tax,
        surcharge=Decimal("0"),
        surcharge_rate_pct=0.0,
        marginal_relief=Decimal("0"),
        rebate_87a=rebate,
        slab_tax_after_rebate=slab_tax_after_rebate,
        total_tax_before_cess=total_tax_before_cess,
        tax_after_rebate=tax_after_rebate,
        cess=cess,
        total_tax=total_tax,
        effective_rate_pct=round(float(effective), 2),
        marginal_rate_pct=round(float(marginal_rate * 100), 2),
        surcharge_applies=False,
        rebate_applies=rebate > 0,
        deduction_breakup=exemption_breakup + deduction_breakup,
        slab_breakup=slab_breakup,
    )
