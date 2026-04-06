"""Unit tests for OCR financial document extraction heuristics."""

from types import SimpleNamespace

from app.models.schemas import DocType
from app.services import ocr_service
from app.services.document_classifier import classify_document_text
from app.services.ocr_service import normalize_ocr_to_structured, assess_ocr_quality
from app.services.universal_extractor import universal_extract_to_dict


def test_extract_payslip_fields_from_text() -> None:
    text = """
    ACME PRIVATE LIMITED
    Employee Name: Rahul Sharma
    Pay Period: Mar 2025
    Basic Salary: 50,000
    HRA: 20,000
    Special Allowance: 10,000
    Professional Tax: 200
    Gross Salary: 80,000
    Net Salary: 76,500
    Annual CTC: 9,60,000
    """

    structured = normalize_ocr_to_structured(text, DocType.payslip)

    assert structured["employee_name"] == "Rahul Sharma"
    assert structured["basic_salary"] == 50000.0
    assert structured["hra"] == 20000.0
    assert structured["gross_salary"] == 80000.0
    assert structured["net_salary"] == 76500.0
    assert structured["ctc_annual"] == 960000.0
    assert structured["year"] == 2025


def test_extract_investment_aliases_for_prefill() -> None:
    text = """
    LIC Premium Receipt
    Policy Name: Jeevan Anand
    Section: 80C
    Premium Amount: Rs 1,50,000
    Receipt Date: 12/03/2025
    """

    structured = normalize_ocr_to_structured(text, DocType.investment)

    assert structured["section"] == "80C"
    assert structured["amount"] == 150000.0
    assert structured["amount_80c"] == 150000.0
    assert structured["total_80c"] == 150000.0


def test_extract_rent_receipt_monthly_rent() -> None:
    text = """
    RENT RECEIPT
    Received from: Amit Verma
    Landlord Name: Suresh Kumar
    Address: Flat 12, MG Road, Bengaluru
    Monthly Rent: ₹24,000
    For April 2024
    PAN: ABCDE1234F
    """

    structured = normalize_ocr_to_structured(text, DocType.rent_receipt)

    assert structured["landlord_name"] == "Suresh Kumar"
    assert structured["rent_amount"] == 24000.0
    assert structured["monthly_rent"] == 24000.0
    assert structured["pan_landlord"] == "ABCDE1234F"


def test_extract_income_tax_statement_generic_fields() -> None:
    text = """
    FORM 16 - PART B
    PAN: ABCDE1234F
    TAN: BLRA12345K
    Assessment Year: 2025-26
    Gross Total Income: 12,40,000
    Total Deductions: 1,85,000
    Taxable Income: 10,55,000
    Total Tax Liability: 1,12,500
    TDS: 1,05,000
    """

    structured = normalize_ocr_to_structured(text, DocType.other)

    assert structured["pan"] == "ABCDE1234F"
    assert structured["tan"] == "BLRA12345K"
    assert structured["assessment_year"] == "2025-26"
    assert structured["gross_total_income"] == 1240000.0
    assert structured["total_deductions"] == 185000.0
    assert structured["taxable_income"] == 1055000.0
    assert structured["total_tax"] == 112500.0
    assert structured["tds"] == 105000.0


def test_assess_quality_not_unclear_when_fields_present() -> None:
    text = "FORM 16 PART B\nGross Total Income: 1240000\nTaxable Income: 1055000\nTDS: 105000"
    structured = {
        "gross_total_income": 1240000.0,
        "taxable_income": 1055000.0,
        "tds": 105000.0,
    }

    quality = assess_ocr_quality(text, confidence=0.35, structured=structured, doc_type=DocType.other)

    assert quality["ocr_clarity"] in {"readable", "clear"}
    assert quality["ocr_status"] in {"verified", "needs_review"}


def test_form16_quality_not_low_when_core_fields_present() -> None:
    text = """
    FORM 16 PART B
    PAN: ABCDE1234F
    Assessment Year: 2025-26
    Gross Total Income: 1240000
    Taxable Income: 1055000
    Total Tax Liability: 112500
    TDS: 105000
    """
    structured = normalize_ocr_to_structured(text, DocType.other)
    quality = assess_ocr_quality(text, confidence=0.34, structured=structured, doc_type=DocType.other)

    assert quality["ocr_accuracy"] in {"medium", "high"}


def test_form16_maps_to_calculator_fields() -> None:
    text = """
    FORM 16 PART B
    PAN: ABCDE1234F
    Assessment Year: 2025-26
    Gross Total Income: 12,40,000
    Total Deductions: 1,85,000
    Taxable Income: 10,55,000
    Tax Deducted at Source: 1,05,000
    80C: 1,50,000
    80D: 25,000
    """

    structured = normalize_ocr_to_structured(text, DocType.payslip)

    assert structured["ctc_annual"] == 1240000.0
    assert structured["gross_salary"] == 103333.33
    assert structured["income_tax_tds"] == 105000.0
    assert structured["total_80c"] == 150000.0
    assert structured["health_insurance"] == 25000.0
    assert structured["year"] == 2024


def test_detect_form16_type_and_extract_core_fields() -> None:
    text = """
    FORM 16
    PART A
    Employer Name: ACME PRIVATE LIMITED
    Employee Name: Rahul Sharma
    Employer TAN: BLRA12345K
    Employee PAN: ABCDE1234F
    Assessment Year: 2025-26
    Total TDS Deposited: 105000

    PART B
    Gross Salary: 1240000
    Standard Deduction: 50000
    Taxable Income: 1055000
    Tax on Income: 112500
    """

    structured = normalize_ocr_to_structured(text, DocType.form16)

    assert structured["doc_subtype"] == "form16"
    assert structured["employee_pan"] == "ABCDE1234F"
    assert structured["assessment_year"] == "2025-26"
    assert structured["gross_salary"] == 1240000.0
    assert structured["taxable_income"] == 1055000.0


def test_form16_tiny_section_artifacts_are_dropped() -> None:
    text = """
    FORM 16 PART B
    Employee PAN: ABCDE1234F
    Assessment Year: 2025-26
    Gross Total Income: 9,20,000
    Taxable Income: 8,05,000
    Total Tax Payable: 86,000
    TDS Deducted: 83,000
    Salary u/s 17(1): 17
    HRA exemption u/s 10(13A): 13
    LTA exemption u/s 10(5): 10
    """

    structured = normalize_ocr_to_structured(text, DocType.form16)

    assert "salary_u_s_17_1" not in structured
    assert "hra_exemption_u_s_10_13a" not in structured
    assert "lta_exemption_u_s_10_5" not in structured


def test_form16_tax_rows_parse_without_section_192_tds_contamination() -> None:
    text = """
    Certificate under Section 203 of the Income-tax Act, 1961 for tax deducted at source on salary paid to an employee under section 192
    PART B
    (a) Salary as per provisions contained in section 17(1) 2557983.00
    (a) Standard deduction under section 16(ia) 50000.00
    6. Income chargeable under the head "Salaries" [(3+1(e)-5] 2325433.00
    (d) Total deduction under section 80C, 80CCC and 80CCD(1) 150000.00 150000.00
    13. Tax on total income 465132.00
    16. Health and education cess 18605.00
    19. Net tax payable (17-18) 483737.00
    """

    structured = normalize_ocr_to_structured(text, DocType.form16)

    assert structured.get("salary_u_s_17_1") == 2557983.0
    assert structured.get("deduction_80c") == 150000.0
    assert structured.get("tax_on_income") == 465132.0
    assert structured.get("health_education_cess") == 18605.0
    assert structured.get("total_tax_payable") == 483737.0
    assert structured.get("tds_deducted") in (None, 0, 0.0)


def test_form16_extracts_professional_tax_from_section_16iii_row() -> None:
    text = """
    FORM 16 PART B
    (c) Tax on employment under section 16(iii) 2400.00
    (a) Salary as per provisions contained in section 17(1) 900000.00
    13. Tax on total income 55000.00
    """

    structured = normalize_ocr_to_structured(text, DocType.form16)
    assert structured.get("professional_tax") == 2400.0


def test_form16_pan_is_corrected_for_common_ocr_confusions() -> None:
    text = """
    FORM 16 PART B
    PAN: ABCDEI234F
    Assessment Year: 2025-26
    Gross Total Income: 12,40,000
    Taxable Income: 10,55,000
    TDS: 1,05,000
    """

    structured = normalize_ocr_to_structured(text, DocType.form16)
    assert structured.get("employee_pan") == "ABCDE1234F" or structured.get("pan") == "ABCDE1234F"


def test_universal_extractor_corrects_grouped_pan_with_ocr_noise() -> None:
    text = """
    FORM 16
    PAN: ABCDE I23O F
    Assessment Year: 2025-26
    Gross Salary: 12,40,000
    """

    extracted = universal_extract_to_dict(text, DocType.form16)
    assert extracted.get("employee_pan") == "ABCDE1230F"


def test_extract_ais_core_categories() -> None:
    text = """
    Annual Information Statement
    PAN: ABCDE1234F
    Salary income from employer amount 900000 confirmed
    Interest from bank FD amount 25000
    Dividend income amount 12000
    TDS deducted by deductor TAN BLRA12345K amount 15000
    """

    structured = normalize_ocr_to_structured(text, DocType.ais)

    assert structured["doc_subtype"] == "ais"
    assert structured["pan"] == "ABCDE1234F"
    assert len(structured.get("salary_entries") or []) >= 1
    assert len(structured.get("interest_entries") or []) >= 1
    assert len(structured.get("tds_credits") or []) >= 1


def test_extract_ais_from_column_rows() -> None:
    text = """
    Annual Information Statement
    Source    Type    Amount    TDS
    HDFC Bank    FD    25,000    2,500
    ICICI Bank    Savings    8,000    0

    Section    Deductor Name    TAN    Amount Deducted
    194A    HDFC BANK LTD    BLRA12345K    2,500
    """

    structured = normalize_ocr_to_structured(text, DocType.ais)

    interest = structured.get("interest_entries") or []
    tds = structured.get("tds_credits") or []
    assert len(interest) >= 2
    assert any((row.get("type") or "") == "fd" for row in interest)
    assert len(tds) >= 1
    assert tds[0].get("tan") == "BLRA12345K"


def test_extract_form26as_from_column_rows() -> None:
    text = """
    Form 26AS
    Section    Deductor Name    TAN    Amount Paid/Credited    Amount Deducted
    192    ACME PRIVATE LIMITED    BLRA12345K    12,40,000    1,05,000
    """

    structured = normalize_ocr_to_structured(text, DocType.form26as)
    tds_rows = structured.get("tds_credits") or []

    assert len(tds_rows) >= 1
    assert tds_rows[0].get("section") == "192"
    assert tds_rows[0].get("tan") == "BLRA12345K"


def test_extract_statement_style_label_next_line_amounts() -> None:
    text = """
    INCOME TAX FINAL STATEMENT FOR THE FINANCIAL YEAR 2025-26 (AY 2026-27)
    PAN: BZOPS1918M
    1 a
    Gross Salary/Pension (Basic Pay, DA, HRA, CCA, Other Allowance, Etc.)
    1303412
    d Total Income (a+b-c)
    1306412
    2 DEDUCTIONS
    i Less standard deduction (Maximum 75000)
    75000
    3 Taxable Income (1-2) [rounded off to nearest multiple of ten rupees]
    1231412
    8 Educational cess@4% (6+7)
    1256
    9 Total Tax Payable (6+7+8)
    32668
    12 Income tax deducted from salary, Advance tax paid
    30000
    """

    structured = normalize_ocr_to_structured(text, DocType.other)

    assert structured["gross_total_income"] == 1306412.0
    assert structured["standard_deduction"] == 75000.0
    assert structured["taxable_income"] == 1231412.0
    assert structured["cess"] == 1256.0
    assert structured["total_tax"] == 32668.0
    assert structured["tds"] == 30000.0


def test_run_provider_ocr_fast_accept_skips_fallbacks(monkeypatch) -> None:
    calls = {"openrouter": 0, "vision": 0, "gemini": 0}

    settings = SimpleNamespace(
        ocr_provider="openrouter",
        google_application_credentials="dummy-creds",
        google_cloud_project="dummy-project",
        gemini_api_key="dummy-gemini",
        openrouter_api_key="sk-or-test",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_model="google/gemini-2.0-flash-001",
        openrouter_fallback_model="openai/gpt-4o-mini",
        ocr_max_pdf_ocr_pages=1,
        ocr_max_image_variants=1,
        ocr_target_chars=120,
        ocr_fast_accept_score=80.0,
        ocr_preprocess_scans=True,
    )

    monkeypatch.setattr(ocr_service, "get_settings", lambda: settings)
    monkeypatch.setattr(ocr_service, "_resolve_openrouter_key", lambda _s: "sk-or-test")
    monkeypatch.setattr(ocr_service, "_extract_pdf_images", lambda _c, max_pages=6: [b"img"])
    monkeypatch.setattr(ocr_service, "_preprocess_image_variants", lambda c: [c])

    def fake_openrouter(_content: bytes, _mime_type: str) -> tuple[str, float]:
        calls["openrouter"] += 1
        return "PAN ABCDE1234F\nGross Total Income 1240000\nTDS 105000", 0.9

    def fake_vision(_content: bytes) -> tuple[str, float]:
        calls["vision"] += 1
        return "", 0.0

    def fake_gemini(_content: bytes, _mime_type: str) -> tuple[str, float]:
        calls["gemini"] += 1
        return "", 0.0

    monkeypatch.setattr(ocr_service, "_ocr_with_openrouter", fake_openrouter)
    monkeypatch.setattr(ocr_service, "_ocr_with_google_vision", fake_vision)
    monkeypatch.setattr(ocr_service, "_ocr_with_gemini", fake_gemini)

    text, conf = ocr_service._run_provider_ocr(b"fake-pdf", "application/pdf")

    assert text
    assert conf > 0
    assert calls["openrouter"] == 1
    assert calls["vision"] == 0
    assert calls["gemini"] >= 1


def test_run_provider_ocr_uses_local_rapidocr_fallback_for_pdf(monkeypatch) -> None:
    settings = SimpleNamespace(
        ocr_provider="auto",
        google_application_credentials=None,
        google_cloud_project=None,
        gemini_api_key=None,
        openrouter_api_key=None,
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_model="google/gemini-2.0-flash-001",
        openrouter_fallback_model="openai/gpt-4o-mini",
        ocr_max_pdf_ocr_pages=2,
        ocr_max_image_variants=1,
        ocr_target_chars=120,
        ocr_fast_accept_score=80.0,
        ocr_preprocess_scans=True,
    )

    monkeypatch.setattr(ocr_service, "get_settings", lambda: settings)
    monkeypatch.setattr(ocr_service, "_extract_pdf_images", lambda _content, max_pages=6: [b"page-1", b"page-2"])
    monkeypatch.setattr(ocr_service, "_ocr_with_rapidocr_image", lambda content: ("FORM 26AS\nPAN ABCDE1234F\nTax Deducted at Source 1,05,000", 0.91))

    text, conf = ocr_service._run_provider_ocr(b"fake-pdf", "application/pdf")

    assert "FORM 26AS" in text
    assert "ABCDE1234F" in text
    assert conf > 0.8


def test_normalize_form16_skips_llm_refine_when_core_fields_present(monkeypatch) -> None:
    text = """
    FORM 16 PART B
    PAN: ABCDE1234F
    Assessment Year: 2025-26
    Gross Total Income: 12,40,000
    Taxable Income: 10,55,000
    Total Tax Liability: 1,12,500
    TDS: 1,05,000
    """

    def fail_if_called(_full_text, _doc_type):
        raise AssertionError("LLM refine should be skipped for dense Form16 extraction")

    monkeypatch.setattr(ocr_service, "_llm_extract_structured", fail_if_called)

    structured = normalize_ocr_to_structured(text, DocType.form16)
    assert structured.get("assessment_year") == "2025-26"
    assert structured.get("gross_total_income") == 1240000.0


def test_statement_aliases_map_to_canonical_core_fields() -> None:
    text = """
    FORM 16 PART B
    Employee PAN: ABCDE1234F
    Assessment Year: 2025-26
    Gross Salary: 1240000
    Net Taxable Salary: 1055000
    Total Tax Payable: 112500
    TDS Deducted: 105000
    """

    structured = normalize_ocr_to_structured(text, DocType.form16)

    assert structured.get("pan") == "ABCDE1234F"
    assert structured.get("assessment_year") == "2025-26"
    assert structured.get("gross_total_income") == 1240000.0
    assert structured.get("taxable_income") == 1055000.0
    assert structured.get("total_tax") == 112500.0
    assert structured.get("tds") == 105000.0


def test_form16_does_not_false_match_professional_tax_from_pt_substring() -> None:
    text = """
    FORM 16 PART B
    PAN: ABCDE1234F
    Assessment Year: 2025-26
    Gross Total Income: 1240000
    Rebate u/s 87A: 33300
    Total Tax Payable: 32668
    TDS Deducted: 30000
    """

    structured = normalize_ocr_to_structured(text, DocType.form16)
    # PT is not present in text; parser should not infer it from unrelated words.
    assert (structured.get("professional_tax") or 0) == 0


def test_form16_professional_tax_outlier_removed_from_structured_output() -> None:
    text = """
    FORM 16 PART B
    PAN: ABCDE1234F
    Assessment Year: 2025-26
    Gross Total Income: 1240000
    Professional Tax: 60000
    Taxable Income: 1055000
    TDS Deducted: 105000
    """

    structured = normalize_ocr_to_structured(text, DocType.form16)
    assert "professional_tax" not in structured


def test_ais_tds_credits_normalized_to_list_and_total() -> None:
    text = """
    Annual Information Statement
    Section    Deductor Name    TAN    Amount Deducted
    194A    HDFC BANK LTD    BLRA12345K    15,000
    """

    structured = normalize_ocr_to_structured(text, DocType.ais)
    tds_rows = structured.get("tds_credits") or []

    assert isinstance(tds_rows, list)
    assert len(tds_rows) >= 1
    assert structured.get("total_tds_deposited", 0) >= 15000


def test_form26as_parses_tax_deducted_column_not_amount_paid() -> None:
    text = """
    Form 26AS
    Section    Deductor Name    TAN    Amount Paid/Credited    Amount Deducted
    192    ACME PRIVATE LIMITED    BLRA12345K    12,40,000    1,05,000
    194A    HDFC BANK LTD    BLRA12345K    50,000    5,000
    """

    structured = normalize_ocr_to_structured(text, DocType.form26as)
    rows = structured.get("tds_credits") or []

    assert len(rows) >= 2
    assert rows[0].get("amount_deducted") == 105000.0
    assert rows[1].get("amount_deducted") == 5000.0
    assert structured.get("total_tds_deposited") == 110000.0


def test_form26as_fallback_parses_plain_text_row() -> None:
    text = """
    FORM 26AS
    Tax Deducted at Source
    Section 192 ACME PRIVATE LIMITED BLRA12345K 1,05,000
    """

    structured = normalize_ocr_to_structured(text, DocType.form26as)
    rows = structured.get("tds_credits") or []

    assert len(rows) >= 1
    assert rows[0].get("amount_deducted") == 105000.0
    assert structured.get("total_tds_deposited") == 105000.0


def test_form26as_keeps_plain_text_rows_without_tan() -> None:
    text = """
    Form 26AS
    Tax Deducted
    ACME PRIVATE LIMITED Section 192 1,05,000
    HDFC BANK LTD Section 194A 5,000
    """

    from app.services.ocr_service import _extract_form26as_from_text

    structured = _extract_form26as_from_text(text)
    rows = structured.get("tds_credits") or []

    assert len(rows) >= 2
    assert rows[0].get("deductor_name")
    assert rows[0].get("amount_deducted") == 105000.0
    assert structured.get("total_tds_deposited") == 110000.0


def test_python_classifier_detects_form16_text() -> None:
    text = """
    FORM 16
    PART A
    Employer TAN: BLRA12345K
    Employee PAN: ABCDE1234F
    PART B
    Taxable Income: 10,55,000
    """

    result = classify_document_text(text)
    assert result.doc_type == DocType.form16
    assert result.confidence > 0


def test_universal_extractor_outputs_schema_dictionary() -> None:
    text = """
    RENT RECEIPT
    Landlord Name: Suresh Kumar
    Tenant Name: Amit Verma
    Monthly Rent: Rs 24,000
    PAN: ABCDE1234F
    For Apr 2024
    """

    data = universal_extract_to_dict(text, DocType.rent_receipt)
    assert isinstance(data, dict)
    assert data.get("landlord_name") == "Suresh Kumar"
    assert data.get("rent_amount") == 24000.0
    assert data.get("pan_landlord") == "ABCDE1234F"


def test_universal_extractor_form16_handles_value_on_next_line() -> None:
    text = """
    FORM 16 PART B
    Employee PAN:
    ABCDE1234F
    Gross Salary:
    12,40,000
    Taxable Income:
    10,55,000
    TDS Deducted:
    1,05,000
    """

    data = universal_extract_to_dict(text, DocType.form16)

    assert data.get("employee_pan") == "ABCDE1234F"
    assert data.get("gross_salary") == 1240000.0
    assert data.get("taxable_income") == 1055000.0
    assert data.get("tds_deducted") == 105000.0


def test_universal_extractor_normalizes_assessment_year_slash_format() -> None:
    text = """
    Form 26AS
    PAN: ABCDE1234F
    Assessment Year 2025 / 26
    Total TDS Deposited: 1,10,000
    """

    data = universal_extract_to_dict(text, DocType.form26as)

    assert data.get("pan") == "ABCDE1234F"
    assert data.get("assessment_year") == "2025-26"
    assert data.get("total_tds_deposited") == 110000.0


def test_universal_extractor_parses_currency_prefixed_numbers() -> None:
    text = """
    RENT RECEIPT
    Landlord Name: Suresh Kumar
    Rent Amount: INR 24,500
    PAN: ABCDE1234F
    """

    data = universal_extract_to_dict(text, DocType.rent_receipt)

    assert data.get("rent_amount") == 24500.0
    assert data.get("pan_landlord") == "ABCDE1234F"
