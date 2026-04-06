"""HRA exemption — Section 10(13A), Rule 2A."""
from decimal import Decimal
from dataclasses import dataclass


@dataclass
class HRAResult:
    amount: Decimal
    explanation: str
    legal_reference: str


def _d(v: any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v)) if v is not None else Decimal("0")


def compute_hra_exemption(
    basic_salary_annual: Decimal,
    hra_received_annual: Decimal,
    rent_paid_annual: Decimal,
    metro: bool = True,
) -> HRAResult:
    """
    HRA exemption = min of:
    1. Actual HRA received
    2. 50% of salary (metro) / 40% (non-metro)
    3. Rent paid - 10% of salary
    """
    basic = _d(basic_salary_annual)
    hra = _d(hra_received_annual)
    rent = _d(rent_paid_annual)
    if basic <= 0 or hra <= 0:
        return HRAResult(
            amount=Decimal("0"),
            explanation="No HRA exemption as basic or HRA received is zero.",
            legal_reference="Income Tax Act 1961, Section 10(13A), Rule 2A.",
        )
    pct = Decimal("0.5") if metro else Decimal("0.4")
    limit1 = basic * pct
    limit2 = rent - (basic * Decimal("0.1"))
    # Exemption = least of (HRA, limit1, limit2); if limit2 < 0 then least is negative → 0
    exempt = min(hra, limit1, limit2)
    exempt = max(Decimal("0"), exempt)
    metro_str = "50%" if metro else "40%"
    explanation = (
        f"HRA exemption is minimum of: (1) HRA received ₹{hra}, "
        f"(2) {metro_str} of basic ₹{limit1}, (3) Rent − 10% basic ₹{limit2}. "
        f"Allowed exemption = ₹{exempt}."
    )
    return HRAResult(
        amount=exempt,
        explanation=explanation,
        legal_reference="Income Tax Act 1961, Section 10(13A), Rule 2A.",
    )
