from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import app
from app.models.schemas import DocType


def test_upload_doc_uses_classifier_then_universal_extractor(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        routes,
        "run_ocr_bytes_detailed",
        lambda content, mime: {
            "text": "FORM 16 PAN ABCDE1234F Assessment Year 2025-26 Gross Salary 1240000",
            "confidence": 0.91,
        },
    )

    def _fake_classify(text: str) -> SimpleNamespace:
        calls["classified_text"] = text
        return SimpleNamespace(doc_type=DocType.form16, confidence=0.87)

    monkeypatch.setattr(routes, "classify_document_text", _fake_classify)

    def _fake_universal(text: str, dtype: DocType) -> dict[str, object]:
        calls["universal_dtype"] = dtype
        return {
            "gross_salary": 1240000,
            "employee_pan": "ABCDE1234F",
            "assessment_year": "2025-26",
        }

    monkeypatch.setattr(routes, "universal_extract_to_dict", _fake_universal)

    def _fake_normalize(text: str, dtype: DocType) -> dict[str, object]:
        calls["normalized_dtype"] = dtype
        return {
            "gross_salary": 999999,
            "taxable_income": 1055000,
            "total_tax_payable": 112500,
            "tds_deducted": 105000,
        }

    monkeypatch.setattr(routes, "normalize_ocr_to_structured", _fake_normalize)
    monkeypatch.setattr(
        routes,
        "assess_ocr_quality",
        lambda text, confidence, structured, dtype: {
            "ocr_status": "verified",
            "ocr_clarity": "clear",
            "ocr_accuracy": "high",
            "ocr_issues": [],
            "extracted_fields": 4,
            "expected_fields": 6,
        },
    )
    monkeypatch.setattr(routes, "audit_log", lambda *args, **kwargs: None)

    client = TestClient(app)
    response = client.post(
        "/api/upload-doc",
        files={"file": ("sample.pdf", b"fake-pdf", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()

    assert body["doc_type"] == "form16"
    assert body["classification_confidence"] == 0.87
    assert body["structured_data"]["gross_salary"] == 1240000
    assert body["structured_data"]["taxable_income"] == 1055000
    assert body["structured_data"]["_classification"]["doc_type"] == "form16"
    assert body["structured_data"]["_classification"]["confidence"] == 0.87

    assert calls["universal_dtype"] == DocType.form16
    assert calls["normalized_dtype"] == DocType.form16
    assert "FORM 16" in str(calls["classified_text"])


def test_upload_doc_infers_form26as_from_filename(monkeypatch) -> None:
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        routes,
        "run_ocr_bytes_detailed",
        lambda content, mime: {
            "text": "Form 26AS\nSection 192\nTDS Deducted 1,05,000",
            "confidence": 0.91,
        },
    )

    def _fake_classify(text: str) -> SimpleNamespace:
        calls["classified_text"] = text
        return SimpleNamespace(doc_type=DocType.other, confidence=0.12)

    monkeypatch.setattr(routes, "classify_document_text", _fake_classify)

    def _fake_universal(text: str, dtype: DocType) -> dict[str, object]:
        calls["universal_dtype"] = dtype
        return {
            "tds_credits": [{"section": "192", "amount_deducted": 105000}],
            "total_tds_deposited": 105000,
        }

    monkeypatch.setattr(routes, "universal_extract_to_dict", _fake_universal)
    monkeypatch.setattr(routes, "normalize_ocr_to_structured", lambda text, dtype: {"tds_credits": [{"section": "192", "amount_deducted": 105000}], "total_tds_deposited": 105000})
    monkeypatch.setattr(
        routes,
        "assess_ocr_quality",
        lambda text, confidence, structured, dtype: {
            "ocr_status": "verified",
            "ocr_clarity": "clear",
            "ocr_accuracy": "high",
            "ocr_issues": [],
            "extracted_fields": 2,
            "expected_fields": 2,
        },
    )
    monkeypatch.setattr(routes, "audit_log", lambda *args, **kwargs: None)

    client = TestClient(app)
    response = client.post(
        "/api/upload-doc",
        files={"file": ("form26as.pdf", b"fake-pdf", "application/pdf")},
        data={"doc_type": "payslip"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["doc_type"] == "form26as"
    assert body["structured_data"]["total_tds_deposited"] == 105000
    assert calls["universal_dtype"] == DocType.form26as
