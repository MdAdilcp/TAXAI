from app.api.routes import _build_tax_calculator_json
from app.models.schemas import DocType


def test_unrealistic_professional_tax_is_not_mapped_to_prefill() -> None:
    structured = {
        "gross_total_income": 1240000,
        "professional_tax": 60000,
        "taxable_income": 1055000,
        "total_tax": 112500,
        "tds": 105000,
    }

    out = _build_tax_calculator_json(structured, DocType.form16)
    prefill = out.get("prefill") or {}

    assert prefill.get("professionalTax", 0) == 0
