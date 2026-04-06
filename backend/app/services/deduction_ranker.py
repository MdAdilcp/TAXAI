"""
ML ranking for deductions: likelihood + tax-savings impact.
Initial model: gradient boosting on synthesized features (or logistic regression).
"""
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.models.schemas import DeductionItem

MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "ml"
MODEL_PATH = MODEL_DIR / "deduction_ranker.joblib"


def _feature_vector(d: DeductionItem, user_profile: dict[str, Any], parsed_docs: list[dict[str, Any]]) -> list[float]:
    """Simple features for ranking."""
    amt = float(d.amount_claimed or 0)
    conf = d.confidence
    has_proof = 1.0 if amt > 0 else 0.0
    income = float(user_profile.get("annual_income") or user_profile.get("gross_salary", 0) or 0)
    impact_ratio = (amt / income) if income > 0 else 0
    return [conf, amt / 100000.0, has_proof, impact_ratio, len(parsed_docs) / 20.0]


def rank_deductions(
    deductions: list[DeductionItem],
    user_profile: dict[str, Any],
    parsed_docs: list[dict[str, Any]],
) -> list[DeductionItem]:
    """Rank by predicted score (likelihood * impact). Uses sklearn model if present."""
    if not deductions:
        return []
    try:
        import joblib
        import numpy as np
        if MODEL_PATH.exists():
            model = joblib.load(MODEL_PATH)
            X = np.array([_feature_vector(d, user_profile, parsed_docs) for d in deductions])
            if hasattr(model, "predict_proba") and X.shape[1] == getattr(model, "n_features_in_", X.shape[1]):
                scores = model.predict_proba(X)[:, 1]
            elif hasattr(model, "predict"):
                scores = model.predict(X)
            else:
                scores = [d.confidence for d in deductions]
        else:
            scores = [d.confidence * (1 + float(d.amount_claimed or 0) / 200000.0) for d in deductions]
        out = []
        for d, sc in zip(deductions, scores):
            impact = (d.amount_claimed or Decimal("0")) * Decimal("0.30")
            data = d.model_dump()
            data["tax_savings_impact"] = impact
            out.append(DeductionItem(**data))
        pairs = list(zip(out, scores))
        pairs.sort(key=lambda x: -x[1])
        return [p[0] for p in pairs]
    except Exception:
        # No model or error: sort by amount then confidence
        return sorted(
            deductions,
            key=lambda d: (-float(d.amount_claimed or 0), -d.confidence),
        )
