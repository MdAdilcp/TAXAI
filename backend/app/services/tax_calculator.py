"""Tax under old and new regime; rebate 87A; cess; suggested investments."""
from decimal import Decimal

from app.models.schemas import SalaryBreakup, DeductionItem, TaxRow, SuggestedInvestment

# FY 2025-26 aligned slab set.
NEW_REGIME_SLABS = [
    (Decimal("0"), Decimal("400000"), Decimal("0")),
    (Decimal("400000"), Decimal("800000"), Decimal("0.05")),
    (Decimal("800000"), Decimal("1200000"), Decimal("0.10")),
    (Decimal("1200000"), Decimal("1600000"), Decimal("0.15")),
    (Decimal("1600000"), Decimal("2000000"), Decimal("0.20")),
    (Decimal("2000000"), Decimal("2400000"), Decimal("0.25")),
    (Decimal("2400000"), Decimal("1e9"), Decimal("0.30")),
]
OLD_REGIME_SLABS = [
    (Decimal("0"), Decimal("250000"), Decimal("0")),
    (Decimal("250000"), Decimal("500000"), Decimal("0.05")),
    (Decimal("500000"), Decimal("1000000"), Decimal("0.20")),
    (Decimal("1000000"), Decimal("1e9"), Decimal("0.30")),
]
REBATE_87A_NEW = Decimal("60000")   # FY 2025-26: taxable income <= 12 lakh
REBATE_87A_NEW_LIMIT = Decimal("1200000")
REBATE_87A_OLD = Decimal("12500")   # taxable income <= 5 lakh
CESS_PCT = Decimal("0.04")
STANDARD_DEDUCTION_NEW = Decimal("75000")
STANDARD_DEDUCTION_OLD = Decimal("50000")


def _qty(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v)) if v is not None else Decimal("0")


def _tax_from_slabs(income: Decimal, slabs: list) -> Decimal:
    tax = Decimal("0")
    for low, high, rate in slabs:
        if income <= low:
            break
        bracket = min(income, high) - low
        if bracket > 0:
            tax += bracket * rate
    return tax


def _total_deductions(deductions: list[DeductionItem], regime: str) -> Decimal:
    standard_code = "standard_deduction"
    standard_default = STANDARD_DEDUCTION_NEW if regime == "new" else STANDARD_DEDUCTION_OLD
    if regime == "new":
        # New regime largely disallows Chapter VI-A deductions in this legacy calculator path.
        allowed_codes = {"80CCD(2)", "employer_nps_80ccd2"}
        non_standard_total = sum(
            d.amount_claimed or Decimal("0")
            for d in deductions
            if d.code in allowed_codes
        )
    else:
        non_standard_total = sum(
            d.amount_claimed or Decimal("0") for d in deductions if d.code != standard_code
        )
    provided_standard = next(
        (d.amount_claimed for d in deductions if d.code == standard_code and (d.amount_claimed or Decimal("0")) > 0),
        None,
    )
    # Guardrail: never allow a higher-than-permitted standard deduction for a regime.
    standard_allowed = min((provided_standard or standard_default), standard_default)
    return non_standard_total + standard_allowed


def _gross_from_salary(s: SalaryBreakup | None) -> Decimal:
    if not s:
        return Decimal("0")
    return _qty(s.gross_salary) * 12 if _qty(s.gross_salary) else _qty(s.ctc)


def calculate_tax(
    salary_breakup: SalaryBreakup | None,
    other_income: Decimal,
    deductions: list[DeductionItem],
    regime: str,  # "old" | "new"
) -> TaxRow:
    gross = _gross_from_salary(salary_breakup) + _qty(other_income)
    total_ded = _total_deductions(deductions, regime)
    taxable = max(Decimal("0"), gross - total_ded)
    slabs = NEW_REGIME_SLABS if regime == "new" else OLD_REGIME_SLABS
    tax_before = _tax_from_slabs(taxable, slabs)
    rebate = Decimal("0")
    if regime == "new" and taxable <= REBATE_87A_NEW_LIMIT:
        rebate = min(tax_before, REBATE_87A_NEW)
    elif regime == "old" and taxable <= Decimal("500000"):
        rebate = min(tax_before, REBATE_87A_OLD)
    tax_after = max(Decimal("0"), tax_before - rebate)
    cess = tax_after * CESS_PCT
    total_tax = tax_after + cess
    effective = (total_tax / taxable * 100) if taxable > 0 else 0
    return TaxRow(
        regime=regime,
        taxable_income=taxable,
        tax_before_rebate=tax_before,
        rebate_87a=rebate,
        tax_after_rebate=tax_after,
        cess=cess,
        total_tax=total_tax,
        effective_rate_pct=round(float(effective), 2),
    )


def suggest_investments(
    salary_breakup: SalaryBreakup | None,
    other_income: Decimal,
    deductions: list[DeductionItem],
) -> list[SuggestedInvestment]:
    """Suggest 80C/80D etc. to optimize tax under old regime."""
    suggestions = []
    gross = _gross_from_salary(salary_breakup) + _qty(other_income)
    current_80c = sum(float(d.amount_claimed or 0) for d in deductions if d.code == "80C")
    current_80d = sum(float(d.amount_claimed or 0) for d in deductions if d.code == "80D")
    if current_80c < 150000 and gross > 500000:
        suggestions.append(SuggestedInvestment(
            section="80C",
            description="Invest in ELSS/PPF/LIC to save tax up to ₹1.5 Lakh",
            suggested_amount=Decimal("150000") - Decimal(str(current_80c)),
            max_deduction=Decimal("150000"),
            current_claim=Decimal(str(current_80c)),
        ))
    if current_80d < 25000 and gross > 500000:
        suggestions.append(SuggestedInvestment(
            section="80D",
            description="Health insurance premium up to ₹25,000",
            suggested_amount=Decimal("25000") - Decimal(str(current_80d)),
            max_deduction=Decimal("25000"),
            current_claim=Decimal(str(current_80d)),
        ))
    return suggestions
