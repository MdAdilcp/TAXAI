"""Explainable layer: return section-wise explanation with claimed, limit, suggestion."""
from decimal import Decimal
from typing import Any

from tax_engine.deductions import (
    deduction_80c,
    deduction_80d,
    deduction_standard,
    deduction_nps_80ccd_1b,
    deduction_home_loan_interest,
    deduction_80tta,
    professional_tax,
)
from tax_engine.hra import compute_hra_exemption


def _d(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v)) if v is not None else Decimal("0")


def explain_section(
    section: str,
    context: dict[str, Any],
    regime: str = "old",
) -> dict[str, Any]:
    """
    Return explainable output for a section: section, claimed, eligible_limit,
    explanation, suggestion, legal_reference.
    context keys depend on section: e.g. 80C → amount_claimed; 80D → self_premium, parents_premium; HRA → basic, hra_received, rent_paid, metro.
    """
    section = section.strip().upper().replace(" ", "")
    result: dict[str, Any] = {}

    if section == "80C":
        r = deduction_80c(_d(context.get("amount_claimed", 0)))
        result = {
            "section": r.section,
            "claimed": float(r.amount),
            "eligible_limit": float(r.eligible_limit) if r.eligible_limit else None,
            "explanation": r.explanation,
            "suggestion": r.suggestion,
            "legal_reference": r.legal_reference,
        }
    elif section == "80D":
        r = deduction_80d(
            _d(context.get("self_premium", 0)),
            _d(context.get("parents_premium", 0)),
            context.get("self_senior", False),
            context.get("parents_senior", False),
        )
        result = {
            "section": r.section,
            "claimed": float(r.amount),
            "eligible_limit": float(r.eligible_limit) if r.eligible_limit else None,
            "explanation": r.explanation,
            "suggestion": r.suggestion,
            "legal_reference": r.legal_reference,
        }
    elif section in ("STANDARD_DEDUCTION", "STANDARDDEDUCTION"):
        r = deduction_standard(regime)
        result = {
            "section": "standard_deduction",
            "claimed": float(r.amount),
            "eligible_limit": float(r.eligible_limit) if r.eligible_limit else None,
            "explanation": r.explanation,
            "suggestion": r.suggestion,
            "legal_reference": r.legal_reference,
        }
    elif section in ("80CCD(1B)", "80CCD1B", "NPS"):
        r = deduction_nps_80ccd_1b(_d(context.get("amount_claimed", 0)))
        result = {
            "section": r.section,
            "claimed": float(r.amount),
            "eligible_limit": float(r.eligible_limit) if r.eligible_limit else None,
            "explanation": r.explanation,
            "suggestion": r.suggestion,
            "legal_reference": r.legal_reference,
        }
    elif section in ("24(B)", "24B", "HOME_LOAN_INTEREST"):
        r = deduction_home_loan_interest(_d(context.get("interest_paid", 0)))
        result = {
            "section": r.section,
            "claimed": float(r.amount),
            "eligible_limit": float(r.eligible_limit) if r.eligible_limit else None,
            "explanation": r.explanation,
            "suggestion": r.suggestion,
            "legal_reference": r.legal_reference,
        }
    elif section == "80TTA":
        r = deduction_80tta(_d(context.get("savings_interest", 0)))
        result = {
            "section": r.section,
            "claimed": float(r.amount),
            "eligible_limit": float(r.eligible_limit) if r.eligible_limit else None,
            "explanation": r.explanation,
            "suggestion": r.suggestion,
            "legal_reference": r.legal_reference,
        }
    elif section == "PROFESSIONAL_TAX":
        r = professional_tax(_d(context.get("amount_paid", 0)))
        result = {
            "section": r.section,
            "claimed": float(r.amount),
            "eligible_limit": None,
            "explanation": r.explanation,
            "suggestion": r.suggestion,
            "legal_reference": r.legal_reference,
        }
    elif section == "HRA":
        basic = _d(context.get("basic", 0)) * 12
        hra = _d(context.get("hra_received", 0)) * 12
        rent = _d(context.get("rent_paid", 0)) * 12
        metro = context.get("metro", True)
        r = compute_hra_exemption(basic, hra, rent, metro)
        result = {
            "section": "HRA",
            "claimed": float(r.amount),
            "eligible_limit": float(hra),
            "explanation": r.explanation,
            "suggestion": None,
            "legal_reference": r.legal_reference,
        }
    else:
        result = {
            "section": section,
            "claimed": 0,
            "eligible_limit": None,
            "explanation": f"No rule implemented for section '{section}'.",
            "suggestion": "Check section code (80C, 80D, HRA, 80CCD(1B), 24(b), 80TTA, standard_deduction).",
            "legal_reference": "",
        }
    return result
