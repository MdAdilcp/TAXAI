"""Lightweight Python document classifier for OCR text."""

from dataclasses import dataclass
import re
from typing import Iterable

from app.models.schemas import DocType
from app.services.ocr_schema import DOC_TYPE_HINTS

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ClassificationResult:
    doc_type: DocType
    confidence: float
    scores: dict[str, float]


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _contains_phrase(text_lower: str, phrase: str) -> bool:
    pattern = rf"\b{re.escape(phrase.lower())}\b"
    return bool(re.search(pattern, text_lower))


def _score_doc_type(text: str, doc_type: str, keywords: Iterable[str]) -> float:
    text_lower = (text or "").lower()
    tokens = _tokenize(text)

    score = 0.0
    for keyword in keywords:
        kw = keyword.lower().strip()
        if not kw:
            continue
        if " " in kw:
            if _contains_phrase(text_lower, kw):
                score += 2.0
        elif kw in tokens:
            score += 1.5

    # Add a few high-precision anchors per document type.
    if doc_type == DocType.form16.value and any(k in text_lower for k in ["form 16", "part a", "part b"]):
        score += 4.0
    if doc_type == DocType.ais.value and "annual information statement" in text_lower:
        score += 4.0
    if doc_type == DocType.form26as.value and any(k in text_lower for k in ["form 26as", "tax credit statement"]):
        score += 4.0
    if doc_type == DocType.payslip.value and any(k in text_lower for k in ["payslip", "gross pay", "net pay"]):
        score += 3.0
    if doc_type == DocType.rent_receipt.value and any(k in text_lower for k in ["rent receipt", "landlord", "tenant"]):
        score += 3.0

    return score


def classify_document_text(text: str) -> ClassificationResult:
    """Classify OCR text into a TaxAI document type using a pure-Python scorer."""
    scores: dict[str, float] = {}
    for raw_type, keywords in DOC_TYPE_HINTS.items():
        scores[raw_type] = _score_doc_type(text, raw_type, keywords)

    if not scores:
        return ClassificationResult(doc_type=DocType.other, confidence=0.0, scores={})

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_type, best_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0.0

    if best_score <= 0:
        return ClassificationResult(doc_type=DocType.other, confidence=0.0, scores=scores)

    # Confidence reflects both absolute score and margin from next candidate.
    confidence = min(0.99, (best_score / 10.0) * 0.55 + max(0.0, (best_score - runner_up)) * 0.08)
    return ClassificationResult(doc_type=DocType(best_type), confidence=round(confidence, 3), scores=scores)
