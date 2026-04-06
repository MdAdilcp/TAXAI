"""
Train a simple GradientBoosting classifier for deduction ranking.
Synthesized labels: preferred = 1 if deduction is 80C/80D or amount_claimed > 50k else 0.
Saves model to ml/deduction_ranker.joblib.
"""
import numpy as np
from pathlib import Path
from sklearn.ensemble import GradientBoostingClassifier

# Synthetic features + labels: [conf, amt_norm, has_proof, impact_ratio, n_docs]
X = np.array([
    [0.9, 1.5, 1, 0.15, 0.2],
    [0.85, 0.25, 1, 0.025, 0.2],
    [0.95, 0.0, 0, 0, 0.1],
    [0.8, 0.5, 1, 0.05, 0.3],
    [0.9, 1.0, 1, 0.10, 0.25],
    [0.7, 0.2, 1, 0.02, 0.15],
] * 20)
y = np.array([1, 1, 0, 1, 1, 0] * 20)  # prefer 80C/80D and high impact

model = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)
model.fit(X, y)

out = Path(__file__).resolve().parent / "deduction_ranker.joblib"
import joblib
joblib.dump(model, out)
print(f"Saved to {out}")
