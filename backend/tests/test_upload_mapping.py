from app.api.routes import _build_tax_calculator_json
from app.models.schemas import DocType


def test_payslip_monthly_values_are_annualized_for_prefill() -> None:
    structured = {
        "basic_salary": 50000,
        "hra": 20000,
        "special_allowance": 10000,
        "professional_tax": 200,
        "gross_salary": 80000,
        "month": "March",
    }

    out = _build_tax_calculator_json(structured, DocType.payslip)
    prefill = out.get("prefill") or {}

    assert prefill.get("basic") == 600000
    assert prefill.get("hra_received") == 240000
    assert prefill.get("special_allowance") == 120000
    assert prefill.get("professionalTax") == 2400


def test_form16_aliases_map_to_prefill_fields() -> None:
    structured = {
        "employee_pan": "ABCDE1234F",
        "assessment_year": "2025-26",
        "gross_salary": 1240000,
        "net_taxable_salary": 1055000,
        "total_tax_payable": 112500,
        "tds_deducted": 105000,
        "amount_80c": 150000,
        "amount_80d": 25000,
        "amount_80ccd_1b": 50000,
        "amount_80tta": 9000,
        "professional_tax": 2400,
    }

    out = _build_tax_calculator_json(structured, DocType.form16)
    prefill = out.get("prefill") or {}

    assert prefill.get("section80C") == 150000
    assert prefill.get("medicalSelf") == 25000
    assert prefill.get("nps") == 50000
    assert prefill.get("savingsInterest") == 9000
    assert prefill.get("professionalTax") == 2400


def test_form16_section_number_artifacts_are_not_used_for_salary_prefill() -> None:
    structured = {
        "employee_pan": "ABCDE1234F",
        "assessment_year": "2025-26",
        "gross_total_income": 920000,
        "taxable_income": 805000,
        "total_tax_payable": 86000,
        "tds_deducted": 83000,
        # Common OCR artifacts from labels: section 17(1) and 10(13A).
        "salary_u_s_17_1": 17,
        "hra_exemption_u_s_10_13a": 13,
        "lta_exemption_u_s_10_5": 10,
    }

    out = _build_tax_calculator_json(structured, DocType.form16)
    prefill = out.get("prefill") or {}

    assert prefill.get("basic") == 368000
    assert prefill.get("hra_received") is None
    assert prefill.get("ltaExempt") is None


def test_form16_low_signal_does_not_autoprefill() -> None:
    structured = {
        "assessment_year": "2020-21",
        "taxable_income": 240000,
        # Missing most core fields; avoid mapping noisy OCR values.
    }

    out = _build_tax_calculator_json(structured, DocType.form16)
    prefill = out.get("prefill") or {}

    assert prefill == {}


def test_form16_strong_part_b_prefills_even_if_identity_is_noisy() -> None:
    structured = {
        "employee_pan": "ATxOxPxxMxx4x0x17E",
        "assessment_year": None,
        "salary_u_s_17_1": 2557983,
        "gross_salary": 2557983,
        "gross_total_income": 2325433,
        "taxable_income": 2175433,
        "standard_deduction": 50000,
        "tax_on_income": 465132,
        "total_tax_payable": 483737,
        "deduction_80c": 150000,
        "professional_tax": 2400,
    }

    out = _build_tax_calculator_json(structured, DocType.form16)
    prefill = out.get("prefill") or {}

    assert prefill.get("section80C") == 150000
    assert prefill.get("professionalTax") == 2400


def test_form16_does_not_backfill_tiny_alias_artifacts() -> None:
    structured = {
        "employee_pan": "ABCDE1234F",
        "assessment_year": "2025-26",
        "gross_total_income": 900000,
        "gross_salary": 900000,
        "taxable_income": 780000,
        "tax_on_income": 82000,
        "total_tax_payable": 86000,
        # Valid Form16 keys are missing, but noisy aliases exist.
        "amount_80c": 80,
        "amount_80tta": 80,
        "pt": 84,
    }

    out = _build_tax_calculator_json(structured, DocType.form16)
    prefill = out.get("prefill") or {}

    assert prefill.get("section80C") is None
    assert prefill.get("savingsInterest") is None
    assert prefill.get("professionalTax") is None


def test_investment_section_uses_generic_amount_for_mapping() -> None:
    structured = {
        "section": "80D",
        "amount": 24000,
        "policy_or_fund_name": "Health Protect Plan",
    }

    out = _build_tax_calculator_json(structured, DocType.investment)
    prefill = out.get("prefill") or {}

    assert prefill.get("medicalSelf") == 24000
