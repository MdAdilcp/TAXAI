"""
Deduction rules: amount + explanation + legal reference.
80C, 80D, standard deduction, NPS 80CCD(1B), home loan interest 24(b), 80TTA.
"""
from decimal import Decimal
from dataclasses import dataclass
from typing import Any

from tax_engine.slabs import load_slabs, get_section_limits


@dataclass
class DeductionResult:
    section: str
    amount: Decimal
    explanation: str
    legal_reference: str
    eligible_limit: Decimal | None = None
    suggestion: str | None = None


def _d(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v)) if v is not None else Decimal("0")


def _limits() -> dict[str, Decimal]:
    return get_section_limits()


def deduction_80c(amount_claimed: Decimal) -> DeductionResult:
    """Section 80C — max ₹1.5 Lakh."""
    limit = _limits().get("section_80c_limit", Decimal("150000"))
    claimed = _d(amount_claimed)
    allowed = min(claimed, limit)
    shortfall = limit - allowed if allowed < limit else Decimal("0")
    suggestion = f"Invest ₹{shortfall} more to maximize 80C benefit." if shortfall > 0 else None
    return DeductionResult(
        section="80C",
        amount=allowed,
        explanation=f"80C deduction: claimed ₹{claimed}, limit ₹{limit}. Allowed = ₹{allowed}.",
        legal_reference="Income Tax Act 1961, Section 80C; Finance Act 2021.",
        eligible_limit=limit,
        suggestion=suggestion,
    )


def deduction_80d(
    self_premium: Decimal,
    parents_premium: Decimal = Decimal("0"),
    self_senior: bool = False,
    parents_senior: bool = False,
) -> DeductionResult:
    """Section 80D — health insurance. Self 25k/50k (senior), Parents 25k/50k (senior)."""
    limits = _limits()
    self_lim = limits.get("section_80d_senior_self" if self_senior else "section_80d_self", Decimal("25000"))
    par_lim = limits.get("section_80d_parents_senior" if parents_senior else "section_80d_parents", Decimal("25000"))
    s = min(_d(self_premium), self_lim)
    p = min(_d(parents_premium), par_lim)
    total = s + p
    return DeductionResult(
        section="80D",
        amount=total,
        explanation=f"80D: self ₹{s} (limit ₹{self_lim}), parents ₹{p} (limit ₹{par_lim}). Total = ₹{total}.",
        legal_reference="Income Tax Act 1961, Section 80D; Finance Act 2021.",
        eligible_limit=self_lim + par_lim,
        suggestion=None,
    )


def deduction_standard(regime: str) -> DeductionResult:
    """Standard deduction for salary — both regimes."""
    from tax_engine.slabs import get_standard_deduction
    amt = get_standard_deduction(regime)
    return DeductionResult(
        section="standard_deduction",
        amount=amt,
        explanation=f"Standard deduction (salary) ₹{amt} per annum for {regime} regime.",
        legal_reference="Finance Act 2023; applicable AY 2024-25.",
        eligible_limit=amt,
    )


def deduction_nps_80ccd_1b(amount_claimed: Decimal) -> DeductionResult:
    """Additional NPS 80CCD(1B) — max ₹50,000."""
    limit = _limits().get("section_80ccd_1b", Decimal("50000"))
    claimed = _d(amount_claimed)
    allowed = min(claimed, limit)
    shortfall = limit - allowed if allowed < limit else Decimal("0")
    suggestion = f"Contribute ₹{shortfall} more to NPS for additional deduction." if shortfall > 0 else None
    return DeductionResult(
        section="80CCD(1B)",
        amount=allowed,
        explanation=f"NPS additional deduction: claimed ₹{claimed}, limit ₹{limit}. Allowed = ₹{allowed}.",
        legal_reference="Income Tax Act 1961, Section 80CCD(1B); Finance Act 2021.",
        eligible_limit=limit,
        suggestion=suggestion,
    )


def deduction_home_loan_interest(interest_paid: Decimal) -> DeductionResult:
    """Section 24(b) — interest on home loan (self-occupied) — max ₹2 Lakh."""
    limit = _limits().get("section_24b_interest_home_loan", Decimal("200000"))
    claimed = _d(interest_paid)
    allowed = min(claimed, limit)
    return DeductionResult(
        section="24(b)",
        amount=allowed,
        explanation=f"Home loan interest deduction: claimed ₹{claimed}, limit ₹{limit}. Allowed = ₹{allowed}.",
        legal_reference="Income Tax Act 1961, Section 24(b).",
        eligible_limit=limit,
        suggestion=None,
    )


def deduction_80tta(savings_interest: Decimal) -> DeductionResult:
    """Section 80TTA — savings account interest — max ₹10,000 (non-senior)."""
    limit = _limits().get("section_80tta", Decimal("10000"))
    claimed = _d(savings_interest)
    allowed = min(claimed, limit)
    return DeductionResult(
        section="80TTA",
        amount=allowed,
        explanation=f"Savings interest deduction: ₹{claimed}, limit ₹{limit}. Allowed = ₹{allowed}.",
        legal_reference="Income Tax Act 1961, Section 80TTA.",
        eligible_limit=limit,
    )


def deduction_80ttb(interest_income: Decimal) -> DeductionResult:
    """Section 80TTB — interest deduction for senior citizens — max ₹50,000."""
    limit = _limits().get("section_80ttb", Decimal("50000"))
    claimed = _d(interest_income)
    allowed = min(claimed, limit)
    return DeductionResult(
        section="80TTB",
        amount=allowed,
        explanation=f"Senior citizen interest deduction: ₹{claimed}, limit ₹{limit}. Allowed = ₹{allowed}.",
        legal_reference="Income Tax Act 1961, Section 80TTB.",
        eligible_limit=limit,
    )


def deduction_80e(interest_paid: Decimal) -> DeductionResult:
    """Section 80E — education loan interest, no monetary cap (within statutory period)."""
    claimed = max(Decimal("0"), _d(interest_paid))
    return DeductionResult(
        section="80E",
        amount=claimed,
        explanation=f"Education loan interest deduction claimed: ₹{claimed}.",
        legal_reference="Income Tax Act 1961, Section 80E.",
        eligible_limit=None,
    )


def deduction_80eeb(interest_paid: Decimal) -> DeductionResult:
    """Section 80EEB — EV loan interest, capped at ₹1.5 lakh."""
    limit = _limits().get("section_80eeb", Decimal("150000"))
    claimed = max(Decimal("0"), _d(interest_paid))
    allowed = min(claimed, limit)
    return DeductionResult(
        section="80EEB",
        amount=allowed,
        explanation=f"Electric vehicle loan interest deduction: claimed ₹{claimed}, limit ₹{limit}. Allowed = ₹{allowed}.",
        legal_reference="Income Tax Act 1961, Section 80EEB.",
        eligible_limit=limit,
    )


def deduction_80g(amount_claimed: Decimal, rate: Decimal) -> DeductionResult:
    """Section 80G — donation deduction at 50% or 100% of donation amount."""
    claimed = max(Decimal("0"), _d(amount_claimed))
    allowed = claimed * rate
    rate_label = int(rate * 100)
    return DeductionResult(
        section=f"80G ({rate_label}%)",
        amount=allowed,
        explanation=f"80G donation deduction at {rate_label}%: donated ₹{claimed}, allowed ₹{allowed}.",
        legal_reference="Income Tax Act 1961, Section 80G.",
        eligible_limit=None,
    )


def deduction_80gg(rent_paid: Decimal, adjusted_total_income: Decimal) -> DeductionResult:
    """Section 80GG — no-HRA rent deduction."""
    limits = _limits()
    monthly_limit = limits.get("section_80gg_monthly_limit", Decimal("5000"))
    annual_limit = monthly_limit * Decimal("12")
    ati = max(Decimal("0"), _d(adjusted_total_income))
    rent = max(Decimal("0"), _d(rent_paid))
    rent_minus_ten_pct = max(Decimal("0"), rent - (ati * Decimal("0.10")))
    quarter_income = ati * Decimal("0.25")
    allowed = min(annual_limit, quarter_income, rent_minus_ten_pct)
    return DeductionResult(
        section="80GG",
        amount=allowed,
        explanation=(
            f"80GG deduction is minimum of annual cap ₹{annual_limit}, 25% of adjusted total income ₹{quarter_income}, "
            f"and rent minus 10% of adjusted total income ₹{rent_minus_ten_pct}. Allowed = ₹{allowed}."
        ),
        legal_reference="Income Tax Act 1961, Section 80GG.",
        eligible_limit=annual_limit,
    )


def deduction_employer_nps_80ccd_2(amount_claimed: Decimal, salary_income: Decimal, regime: str) -> DeductionResult:
    """Employer NPS contribution under Section 80CCD(2), allowed in new regime too."""
    limits = _limits()
    limit_rate = limits.get("section_80ccd_2_new_rate", Decimal("0.14")) if regime == "new" else Decimal("0.10")
    claimed = max(Decimal("0"), _d(amount_claimed))
    salary_amt = max(Decimal("0"), _d(salary_income))
    eligible_limit = salary_amt * limit_rate
    allowed = min(claimed, eligible_limit)
    return DeductionResult(
        section="80CCD(2)",
        amount=allowed,
        explanation=f"Employer NPS contribution: claimed ₹{claimed}, cap {limit_rate * 100}% of salary = ₹{eligible_limit}. Allowed = ₹{allowed}.",
        legal_reference="Income Tax Act 1961, Section 80CCD(2).",
        eligible_limit=eligible_limit,
    )


def professional_tax(amount_paid: Decimal) -> DeductionResult:
    """Professional tax — no upper limit, state-specific."""
    amt = _d(amount_paid)
    return DeductionResult(
        section="professional_tax",
        amount=amt,
        explanation=f"Professional tax paid (deductible from salary): ₹{amt}.",
        legal_reference="State-specific; deductible from salary income.",
        eligible_limit=None,
    )


def lta_exemption(amount_exempt: Decimal) -> DeductionResult:
    """Section 10(5) — Leave Travel Allowance exemption (as declared/eligible amount)."""
    amt = max(Decimal("0"), _d(amount_exempt))
    return DeductionResult(
        section="10(5) LTA",
        amount=amt,
        explanation=f"LTA exemption claimed under Section 10(5): ₹{amt}.",
        legal_reference="Income Tax Act 1961, Section 10(5) read with Rule 2B.",
        eligible_limit=None,
    )
