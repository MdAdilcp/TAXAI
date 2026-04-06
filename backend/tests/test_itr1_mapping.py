from fastapi.testclient import TestClient

import app.api.routes as routes
from app.main import app


def test_itr1_map_returns_requested_structure(monkeypatch) -> None:
    doc_form16 = "doc-form16"
    doc_26as = "doc-26as"

    routes._docs[doc_form16] = {
        "doc_type": "form16",
        "structured_data": {
            "employee_name": "Rahul Sharma",
            "employee_pan": "ABCDE1234F",
            "assessment_year": "2025-26",
            "gross_salary": 1240000,
            "standard_deduction": 50000,
            "professional_tax": 2400,
            "taxable_income": 1055000,
            "tax_on_income": 108173,
            "surcharge": 0,
            "health_education_cess": 4327,
            "total_tax_payable": 112500,
            "relief_u89": 0,
            "net_tax_payable": 112500,
            "deduction_80c": 150000,
            "deduction_80d": 25000,
            "deduction_80ccd_1b": 50000,
            "total_deductions": 225000,
            "tds_deducted": 105000,
        },
    }
    routes._docs[doc_26as] = {
        "doc_type": "form26as",
        "structured_data": {
            "tds_credits": [
                {
                    "section": "192",
                    "deductor_name": "ACME LTD",
                    "tan": "BLRA12345K",
                    "amount_paid_credited": 1240000,
                    "amount_deducted": 105000,
                    "tax_deposited": 105000,
                }
            ]
        },
    }

    client = TestClient(app)
    res = client.post("/api/itr1-map", json={"doc_ids": [doc_form16, doc_26as]})
    assert res.status_code == 200
    body = res.json()

    assert set(body.keys()) == {"extraction", "itr_mapped", "validation"}
    assert body["itr_mapped"]["PersonalInfo"]["PAN"] == "ABCDE1234F"
    assert body["itr_mapped"]["ScheduleS"]["Salaries"] == 1240000
    assert body["itr_mapped"]["PartBTTI"]["TaxPayableOnTI"] == 112500
    assert body["validation"]["refund_or_demand"]["type"] == "TAX_DUE"


def test_itr1_map_applies_statutory_caps() -> None:
    doc_form16 = "doc-form16-cap"

    routes._docs[doc_form16] = {
        "doc_type": "form16",
        "structured_data": {
            "employee_pan": "ABCDE1234F",
            "assessment_year": "2025-26",
            "standard_deduction": 75000,
            "deduction_80c": 200000,
            "deduction_80ccd_1b": 70000,
            "tax_on_income": 100000,
            "surcharge": 0,
            "health_education_cess": 4000,
            "total_tax_payable": 104000,
            "relief_u89": 0,
            "net_tax_payable": 104000,
        },
    }

    client = TestClient(app)
    res = client.post("/api/itr1-map", json={"doc_ids": [doc_form16]})
    assert res.status_code == 200
    body = res.json()

    form16 = body["extraction"]["form16"]
    assert form16["standard_deduction"] == 50000
    assert form16["deduction_80c"] == 150000
    assert form16["deduction_80ccd1b"] == 50000
    assert "80C exceeds limit" in body["validation"]["errors"]
    assert "80CCD(1B) exceeds limit" in body["validation"]["errors"]


def test_itr1_map_returns_explicit_nulls_when_missing() -> None:
    client = TestClient(app)
    res = client.post("/api/itr1-map", json={"doc_ids": ["missing-doc-id"]})
    assert res.status_code == 200
    body = res.json()

    form16 = body["extraction"]["form16"]
    form26as = body["extraction"]["form26as"]
    partb = body["itr_mapped"]["PartBTTI"]

    assert "employee_pan" in form16 and form16["employee_pan"] is None
    assert "assessment_year" in form16 and form16["assessment_year"] is None
    assert "total_tax_payable" in form16 and form16["total_tax_payable"] is None
    assert "advance_tax_total" in form26as and form26as["advance_tax_total"] is None
    assert "self_assessment_tax_total" in form26as and form26as["self_assessment_tax_total"] is None
    assert partb["TaxPayableOnTI"] is None
    assert partb["TaxDue"] is None
    assert partb["Refund"]["RefundDue"] is None
