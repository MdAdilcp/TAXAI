"""Rule-based deduction coverage + ML ranking; edge cases return requires_human_review."""
import json
from pathlib import Path
from decimal import Decimal
from typing import Any

from app.models.schemas import DeductionItem, SalaryBreakup

# Load KB
KB_PATH = Path(__file__).resolve().parent.parent.parent / "kb" / "deduction_rules.json"
try:
    with open(KB_PATH) as f:
        DEDUCTION_KB = json.load(f)
except Exception:
    DEDUCTION_KB = {}


def _qty(val: Any) -> Decimal:
    if isinstance(val, Decimal):
        return val
    if isinstance(val, (int, float)):
        return Decimal(str(val))
    return Decimal("0")


def _hra_exemption(basic: Decimal, hra_received: Decimal, rent_paid: Decimal, metro: bool) -> Decimal:
    """HRA exemption = min(actual HRA, 50% basic (metro) or 40%, rent - 10% basic)."""
    if basic <= 0 or hra_received <= 0:
        return Decimal("0")
    pct = Decimal("0.5") if metro else Decimal("0.4")
    limit1 = basic * pct
    limit2 = rent_paid - (basic * Decimal("0.1"))
    return min(hra_received, limit1, limit2) if limit2 > 0 else min(hra_received, limit1)


def rule_based_deductions(
    salary_breakup: SalaryBreakup | None,
    parsed_docs: list[dict[str, Any]],
    user_profile: dict[str, Any],
) -> list[DeductionItem]:
    items: list[DeductionItem] = []
    basic = _qty(salary_breakup.basic) if salary_breakup else Decimal("0")
    hra_received = _qty(salary_breakup.hra) if salary_breakup else Decimal("0")
    pt = _qty(salary_breakup.professional_tax) if salary_breakup else Decimal("0")
    gross = _qty(salary_breakup.gross_salary) if salary_breakup else Decimal("0")

    # Standard deduction (old regime; salary)
    if gross > 0 and DEDUCTION_KB.get("standard_deduction"):
        sd = DEDUCTION_KB["standard_deduction"].get("amount", 75000)
        items.append(DeductionItem(
            code="standard_deduction",
            name=DEDUCTION_KB["standard_deduction"]["name"],
            amount_claimed=Decimal(str(sd)),
            max_allowed=Decimal(str(sd)),
            confidence=1.0,
            legal_citation=DEDUCTION_KB["standard_deduction"].get("citation"),
        ))

    # Professional tax
    if pt > 0:
        items.append(DeductionItem(
            code="professional_tax",
            name="Professional tax",
            amount_claimed=pt,
            max_allowed=None,
            confidence=1.0,
            legal_citation="State-specific; deductible from salary",
        ))

    # HRA (if rent from docs)
    rent_paid = Decimal("0")
    for doc in parsed_docs:
        r = doc.get("rent_amount") or doc.get("rent")
        if r is not None:
            rent_paid = _qty(r)
            break
    if hra_received > 0 and rent_paid > 0:
        metro = user_profile.get("metro", True)
        hra_exempt = _hra_exemption(basic, hra_received, rent_paid, metro)
        items.append(DeductionItem(
            code="HRA",
            name="HRA exemption",
            amount_claimed=hra_exempt,
            max_allowed=hra_received,
            confidence=0.95,
            legal_citation=DEDUCTION_KB.get("HRA", {}).get("citation"),
        ))

    # 80C from parsed docs
    limit_80c = Decimal(str(DEDUCTION_KB.get("80C", {}).get("max_amount", 150000)))
    total_80c = Decimal("0")
    for doc in parsed_docs:
        sec = (doc.get("section") or "").upper()
        amt = _qty(doc.get("amount") or doc.get("premium") or 0)
        if "80C" in sec or sec in ("80C", "80CCC", "ELSS", "PPF", "LIC"):
            total_80c += amt
    if total_80c > 0:
        claim = min(total_80c, limit_80c)
        items.append(DeductionItem(
            code="80C",
            name=DEDUCTION_KB.get("80C", {}).get("name", "80C"),
            amount_claimed=claim,
            max_allowed=limit_80c,
            confidence=0.9,
            legal_citation=DEDUCTION_KB.get("80C", {}).get("citation"),
            requires_human_review=total_80c > limit_80c,
        ))

    # 80D from docs
    limit_80d = Decimal(str(DEDUCTION_KB.get("80D", {}).get("max_amount_self", 25000)))
    for doc in parsed_docs:
        sec = (doc.get("section") or "").upper()
        amt = _qty(doc.get("amount") or doc.get("premium") or 0)
        if "80D" in sec or doc.get("doc_type") == "medical_bill":
            items.append(DeductionItem(
                code="80D",
                name=DEDUCTION_KB.get("80D", {}).get("name", "80D"),
                amount_claimed=min(amt, limit_80d),
                max_allowed=limit_80d,
                confidence=0.85,
                legal_citation=DEDUCTION_KB.get("80D", {}).get("citation"),
            ))
            break

    # 80TTA
    savings_interest = _qty(user_profile.get("savings_interest", 0))
    if savings_interest > 0:
        limit_80tta = Decimal(str(DEDUCTION_KB.get("80TTA", {}).get("max_amount", 10000)))
        items.append(DeductionItem(
            code="80TTA",
            name=DEDUCTION_KB.get("80TTA", {}).get("name", "80TTA"),
            amount_claimed=min(savings_interest, limit_80tta),
            max_allowed=limit_80tta,
            confidence=0.85,
            legal_citation=DEDUCTION_KB.get("80TTA", {}).get("citation"),
        ))

    # NPS additional 80CCD(1B)
    nps_extra = _qty(user_profile.get("nps_extra", 0))
    if nps_extra > 0:
        limit_nps = Decimal("50000")
        items.append(DeductionItem(
            code="80CCD_1B",
            name="Additional NPS",
            amount_claimed=min(nps_extra, limit_nps),
            max_allowed=limit_nps,
            confidence=0.9,
            legal_citation=DEDUCTION_KB.get("80CCD_1B", {}).get("citation"),
        ))

    return items


def rank_deductions_by_impact(
    deductions: list[DeductionItem],
    user_profile: dict[str, Any],
    parsed_docs: list[dict[str, Any]],
) -> list[DeductionItem]:
    """
    ML ranking: score by likelihood and tax-savings impact.
    Initial model: simple logistic/weighted score on synthesized features.
    """
    try:
        from app.services.deduction_ranker import rank_deductions
        return rank_deductions(deductions, user_profile, parsed_docs)
    except Exception:
        # Fallback: sort by amount_claimed desc then confidence
        def key(d: DeductionItem) -> tuple:
            return (-(d.amount_claimed or Decimal("0")), -d.confidence)
        return sorted(deductions, key=key)
