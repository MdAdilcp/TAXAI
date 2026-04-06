"""TaxAI API routes."""
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.core.config import get_settings
from app.core.audit import audit_log
from app.models.schemas import (
    DocType,
    UploadDocResponse,
    ParseSalaryRequest,
    ParseSalaryResponse,
    SalaryBreakup,
    RecommendDeductionsRequest,
    RecommendDeductionsResponse,
    CalculateTaxRequest,
    CalculateTaxResponse,
    ConversationRequest,
    ConversationResponse,
    TaxDocReviewRequest,
    TaxDocReviewResponse,
    ITR1MapRequest,
)
from app.services.document_classifier import classify_document_text
from app.services.ocr_service import run_ocr_bytes_detailed, normalize_ocr_to_structured, assess_ocr_quality
from app.services.universal_extractor import universal_extract_to_dict
from app.services.deduction_engine import rule_based_deductions, rank_deductions_by_impact
from app.services.tax_calculator import calculate_tax, suggest_investments
from app.services.conversation_service import converse
from app.services.tts_service import text_to_speech
from app.services.itr1_mapper import build_itr1_payload

router = APIRouter(prefix="/api", tags=["api"])

# In-memory doc store for MVP
_docs: dict[str, dict[str, Any]] = {}
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def _is_present(value: Any) -> bool:
    return value not in (None, "", 0, 0.0, [], {})


def _merge_for_schema_mapping(schema_first: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Prefer schema-first extractor fields and backfill with enriched OCR output."""
    merged = dict(fallback or {})
    for key, value in (schema_first or {}).items():
        if _is_present(value):
            merged[key] = value
    return merged


@router.post("/upload-doc", response_model=UploadDocResponse)
async def upload_doc(
    file: UploadFile = File(...),
    doc_type: str | None = Form(None),
) -> UploadDocResponse:
    """Saves document, runs OCR, returns structured data."""
    content = await file.read()
    doc_id = str(uuid.uuid4())
    ext = (file.filename or "").split(".")[-1].lower()
    filename_lower = (file.filename or "").lower()
    requested = DocType(doc_type) if doc_type and doc_type in [e.value for e in DocType] else None
    if "form26as" in filename_lower or "26as" in filename_lower:
        requested = DocType.form26as
    elif "form16" in filename_lower:
        requested = DocType.form16
    elif "ais" in filename_lower:
        requested = DocType.ais
    if ext == "pdf":
        mime = "application/pdf"
    elif ext in {"jpg", "jpeg"}:
        mime = "image/jpeg"
    elif ext in {"png"}:
        mime = "image/png"
    elif ext in {"tif", "tiff"}:
        mime = "image/tiff"
    else:
        mime = (file.content_type or "").strip() or "application/octet-stream"

    try:
        detailed = run_ocr_bytes_detailed(content, mime)
        text = detailed.get("text") or ""
        confidence = float(detailed.get("confidence") or 0.0)
        classification = classify_document_text(text)
        detected = classification.doc_type
        dtype = requested or detected
        text_lower = (text or "").lower()
        if requested in {DocType.payslip, DocType.other} and any(k in text_lower for k in ["form 16", "part a", "part b", "salary u/s 17"]):
            dtype = DocType.form16
        if requested in {DocType.payslip, DocType.other} and detected in {DocType.form16, DocType.ais, DocType.form26as}:
            dtype = detected
        schema_dict = universal_extract_to_dict(text, dtype)
        enriched = normalize_ocr_to_structured(text, dtype)
        structured = _merge_for_schema_mapping(schema_dict, enriched)
        structured.setdefault(
            "_classification",
            {
                "doc_type": classification.doc_type.value,
                "confidence": classification.confidence,
            },
        )
        calculator_json = _build_tax_calculator_json(structured, dtype)
        if detailed.get("pdf_type"):
            structured.setdefault("pdf_type", detailed.get("pdf_type"))
        if detailed.get("unreadable_pages"):
            structured.setdefault("unreadable_pages", detailed.get("unreadable_pages"))
        quality = assess_ocr_quality(text, confidence, structured, dtype)
        if quality.get("extracted_fields", 0) > 0 and confidence <= 0:
            confidence = min(0.85, 0.35 + 0.08 * float(quality.get("extracted_fields", 0)))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to process {file.filename or 'uploaded file'}: {exc}") from exc

    save_path = UPLOAD_DIR / f"{doc_id}.{ext}"
    save_path.write_bytes(content)
    _docs[doc_id] = {
        "doc_type": dtype.value,
        "structured_data": structured,
        "tax_calculator_json": calculator_json,
        "raw_text": text[:1000],
        "ocr_quality": quality,
    }
    audit_log("upload_doc", details={"doc_id": doc_id, "doc_type": dtype.value})
    return UploadDocResponse(
        doc_id=doc_id,
        doc_type=dtype,
        structured_data=structured,
        tax_calculator_json=calculator_json,
        raw_text_preview=text[:500] if text else None,
        confidence=confidence,
        classification_confidence=classification.confidence,
        ocr_status=quality["ocr_status"],
        ocr_clarity=quality["ocr_clarity"],
        ocr_accuracy=quality["ocr_accuracy"],
        ocr_issues=quality["ocr_issues"],
        extracted_fields=quality["extracted_fields"],
        expected_fields=quality["expected_fields"],
    )


def _sum_amount(rows: list[dict[str, Any]], key: str) -> float:
    total = 0.0
    for row in rows or []:
        try:
            total += float(row.get(key) or 0)
        except Exception:
            pass
    return total


def _to_num(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _first_num(data: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = _to_num(data.get(key))
        if value > 0:
            return value
    return 0.0


def _looks_monthly_salary(structured: dict[str, Any], ctc_annual: float, gross: float) -> bool:
    if ctc_annual > 0:
        return False
    if 0 < gross <= 250000:
        return True
    month = structured.get("month")
    return bool(month and gross > 0)


def _sanitize_professional_tax(value: float, gross_annual: float = 0.0) -> float:
    pt = max(0.0, value)
    if pt <= 0:
        return 0.0
    # Typical annual professional tax is low; suppress clear OCR outliers.
    hard_cap = 10000.0
    soft_cap = gross_annual * 0.02 if gross_annual > 0 else hard_cap
    return pt if pt <= min(hard_cap, soft_cap) else 0.0


def _sanitize_form16_component(value: float, *, gross_annual: float, min_amount: float) -> float:
    amt = max(0.0, value)
    if amt <= 0:
        return 0.0
    if amt < min_amount:
        return 0.0
    if gross_annual > 0 and amt > gross_annual * 1.2:
        return 0.0
    return amt


def _build_tax_calculator_json(structured: dict[str, Any], dtype: DocType) -> dict[str, Any]:
    """Convert OCR structured output into calculator-ready JSON payloads."""
    salary = {
        "basic": 0.0,
        "hra_received": 0.0,
        "special_allowance": 0.0,
        "other_income": 0.0,
    }
    investments = {
        "80C": [],
        "80D": {"self_family": 0.0, "parents": 0.0},
        "nps": 0.0,
    }
    payload: dict[str, Any] = {
        "salary": salary,
        "investments": investments,
        "rent_paid": 0.0,
        "lta_exempt": 0.0,
        "other_section10_exemptions": 0.0,
        "home_loan_interest": 0.0,
        "savings_interest": 0.0,
        "house_property_income": 0.0,
        "business_income": 0.0,
        "other_sources_income": 0.0,
        "capital_gains_stcg": 0.0,
        "capital_gains_ltcg": 0.0,
        "employer_nps_80ccd2": 0.0,
        "education_loan_interest_80e": 0.0,
        "donation_80g_50": 0.0,
        "donation_80g_100": 0.0,
        "rent_paid_80gg": 0.0,
        "claim_80gg": False,
        "self_is_senior": False,
        "parents_are_senior": False,
        "professional_tax_paid": 0.0,
        "metro": False,
        "regime": "new",
    }

    prefill: dict[str, float] = {
        "basic": 0.0,
        "hra_received": 0.0,
        "special_allowance": 0.0,
        "other_income": 0.0,
        "ltaExempt": 0.0,
        "section80C": 0.0,
        "medicalSelf": 0.0,
        "medicalFamily": 0.0,
        "nps": 0.0,
        "rentPaid": 0.0,
        "homeLoanInterest": 0.0,
        "savingsInterest": 0.0,
        "professionalTax": 0.0,
        "otherSection10Exemptions": 0.0,
    }

    if dtype == DocType.form16:
        has_pan = bool(structured.get("pan") or structured.get("employee_pan"))
        has_ay = bool(structured.get("assessment_year"))

        gti = _first_num(structured, "gross_total_income", "gross_salary", "ctc_annual")
        taxable = _first_num(structured, "taxable_income", "net_taxable_salary")
        total_tax = _first_num(structured, "total_tax", "total_tax_payable", "tax_on_income")
        tds = _first_num(structured, "tds", "tds_deducted", "total_tds_deposited", "income_tax_tds")

        numeric_core = 0
        if gti >= 50000:
            numeric_core += 1
        if taxable >= 50000:
            numeric_core += 1
        if total_tax >= 100:
            numeric_core += 1
        if tds >= 100:
            numeric_core += 1

        has_tax_computation_signal = total_tax >= 100 or (tds >= 1000 and taxable >= 500000)

        strong_part_b_signal = (
            numeric_core >= 3
            and total_tax >= 100
            and _first_num(structured, "salary_u_s_17_1", "gross_salary") >= 10000
            and _first_num(structured, "standard_deduction", "total_deductions") >= 10000
        )

        # Require identity anchors and strong numeric evidence before auto-prefill from Form16 OCR.
        if not ((has_pan and has_ay and numeric_core >= 2 and has_tax_computation_signal) or strong_part_b_signal):
            # Keep upload response deterministic but avoid pushing low-quality values into calculator.
            return {
                "doc_type": dtype.value,
                "compute_tax_payload": payload,
                "prefill": {},
            }

        gross_annual = _first_num(structured, "gross_total_income", "gross_salary", "ctc_annual")

        basic_candidate = _first_num(structured, "salary_u_s_17_1", "basic_salary", "basic")
        basic = _sanitize_form16_component(basic_candidate, gross_annual=gross_annual, min_amount=10000)
        if basic <= 0 and gross_annual > 0:
            basic = gross_annual * 0.4

        hra_candidate = _first_num(structured, "hra_exemption_u_s_10_13a", "hra")
        hra = _sanitize_form16_component(hra_candidate, gross_annual=gross_annual, min_amount=500)

        perquisites = _sanitize_form16_component(
            _first_num(structured, "perquisites_u_s_17_2", "perquisites"),
            gross_annual=gross_annual,
            min_amount=100,
        )
        profits_in_lieu = _sanitize_form16_component(
            _first_num(structured, "profits_in_lieu_u_s_17_3", "profits_in_lieu"),
            gross_annual=gross_annual,
            min_amount=100,
        )

        special = max(0.0, gross_annual - basic - hra - perquisites - profits_in_lieu) if gross_annual > 0 else 0.0

        salary["basic"] = basic
        salary["hra_received"] = hra
        salary["perquisites"] = perquisites
        salary["profits_in_lieu"] = profits_in_lieu
        salary["special_allowance"] = special
        salary["other_income"] = _first_num(structured, "other_income", "other_sources_income")

        payload["lta_exempt"] = _sanitize_form16_component(
            _first_num(structured, "lta_exemption_u_s_10_5", "lta", "lta_exempt"),
            gross_annual=gross_annual,
            min_amount=500,
        )
        payload["professional_tax_paid"] = _sanitize_professional_tax(
            _sanitize_form16_component(
                _first_num(structured, "professional_tax", "pt"),
                gross_annual=gross_annual,
                min_amount=100,
            ),
            gross_annual,
        )
        amount_80c = _sanitize_form16_component(
            _first_num(structured, "deduction_80c", "amount_80c", "total_80c"),
            gross_annual=gross_annual,
            min_amount=1000,
        )
        if amount_80c > 0:
            payload["investments"]["80C"] = [{"amount": amount_80c}]
        payload["investments"]["80D"]["self_family"] = _first_num(structured, "deduction_80d", "amount_80d", "medical_premium", "health_insurance")
        payload["investments"]["nps"] = _first_num(structured, "deduction_80ccd_1b", "amount_80ccd_1b", "nps")
        payload["donation_80g_50"] = _first_num(structured, "deduction_80g")
        payload["home_loan_interest"] = _first_num(structured, "deduction_24b", "home_loan_interest")
        payload["savings_interest"] = _sanitize_form16_component(
            _first_num(structured, "deduction_80tta", "amount_80tta", "savings_interest"),
            gross_annual=gross_annual,
            min_amount=100,
        )

        prefill["basic"] = basic
        prefill["hra_received"] = hra
        prefill["perquisites"] = perquisites
        prefill["profits_in_lieu"] = profits_in_lieu
        prefill["special_allowance"] = special
        prefill["other_income"] = salary["other_income"]
        prefill["ltaExempt"] = payload["lta_exempt"]
        prefill["section80C"] = amount_80c
        prefill["medicalSelf"] = payload["investments"]["80D"]["self_family"]
        prefill["nps"] = payload["investments"]["nps"]
        prefill["homeLoanInterest"] = payload["home_loan_interest"]
        prefill["savingsInterest"] = payload["savings_interest"]
        prefill["professionalTax"] = payload["professional_tax_paid"]
        prefill["otherSection10Exemptions"] = hra

    elif dtype == DocType.payslip:
        ctc_annual = _first_num(structured, "ctc_annual", "gross_total_income")
        gross_hint = _first_num(structured, "gross_salary", "net_salary", "basic_salary")
        multiplier = 12.0 if _looks_monthly_salary(structured, ctc_annual, gross_hint) else 1.0
        gross_for_cap = ctc_annual if ctc_annual > 0 else (gross_hint * multiplier)

        basic = _first_num(structured, "basic_salary", "basic") * multiplier
        hra = _first_num(structured, "hra") * multiplier
        special = _first_num(structured, "special_allowance") * multiplier
        other_allowances = _first_num(structured, "other_allowances") * multiplier
        salary["basic"] = basic
        salary["hra_received"] = hra
        salary["special_allowance"] = special + other_allowances
        salary["other_income"] = _first_num(structured, "other_income", "other_sources_income")
        payload["professional_tax_paid"] = _sanitize_professional_tax(
            _first_num(structured, "professional_tax", "pt") * multiplier,
            gross_for_cap,
        )

        prefill["basic"] = salary["basic"]
        prefill["hra_received"] = salary["hra_received"]
        prefill["special_allowance"] = salary["special_allowance"]
        prefill["other_income"] = salary["other_income"]
        prefill["professionalTax"] = payload["professional_tax_paid"]

    elif dtype == DocType.investment:
        section = str(structured.get("section") or "").upper().replace(" ", "")
        policy_name = str(structured.get("policy_or_fund_name") or "").upper()
        generic_amount = _first_num(structured, "amount", "investment_amount", "premium")

        amt_80c = _first_num(structured, "amount_80c", "total_80c")
        nps = _first_num(structured, "nps_amount", "nps")
        med = _first_num(structured, "health_insurance", "medical_premium")

        if generic_amount > 0:
            if section.startswith("80C") and amt_80c <= 0:
                amt_80c = generic_amount
            if (section.startswith("80CCD") or "NPS" in policy_name) and nps <= 0:
                nps = generic_amount
            if section.startswith("80D") and med <= 0:
                med = generic_amount

        if amt_80c > 0:
            payload["investments"]["80C"] = [{"amount": amt_80c}]
        payload["investments"]["nps"] = nps
        payload["investments"]["80D"]["self_family"] = med
        prefill["section80C"] = amt_80c
        prefill["nps"] = nps
        prefill["medicalSelf"] = med

    elif dtype == DocType.rent_receipt:
        annual_rent = _to_num(structured.get("annual_rent") or structured.get("rent_paid"))
        monthly_rent = _to_num(structured.get("monthly_rent") or structured.get("rent_amount"))
        payload["rent_paid"] = annual_rent if annual_rent > 0 else (monthly_rent * 12 if monthly_rent > 0 else 0.0)
        prefill["rentPaid"] = payload["rent_paid"]

    elif dtype == DocType.medical_bill:
        med = _to_num(structured.get("amount") or structured.get("total"))
        payload["investments"]["80D"]["self_family"] = med
        prefill["medicalSelf"] = med

    elif dtype == DocType.ais:
        interest_total = _sum_amount(structured.get("interest_entries") or [], "amount")
        dividend_total = _sum_amount(structured.get("dividend_entries") or [], "amount")
        cap_stcg = _sum_amount([r for r in (structured.get("capital_gains_securities") or []) if (r.get("type") or "").lower() == "stcg"], "amount") + _sum_amount([r for r in (structured.get("capital_gains_other") or []) if (r.get("type") or "").lower() == "stcg"], "amount")
        cap_ltcg = _sum_amount([r for r in (structured.get("capital_gains_securities") or []) if (r.get("type") or "").lower() == "ltcg"], "amount") + _sum_amount([r for r in (structured.get("capital_gains_other") or []) if (r.get("type") or "").lower() == "ltcg"], "amount")
        payload["other_sources_income"] = interest_total + dividend_total
        payload["capital_gains_stcg"] = cap_stcg
        payload["capital_gains_ltcg"] = cap_ltcg
        prefill["other_income"] = payload["other_sources_income"] + cap_stcg + cap_ltcg

    # Generic compatibility mapping: fill missing prefill fields for non-Form16 docs.
    # Form16 has dedicated parsing/safety gates and should not be backfilled by loose aliases.
    if dtype != DocType.form16:
        prefill["section80C"] = prefill["section80C"] or _first_num(structured, "amount_80c", "total_80c", "deduction_80c")
        prefill["medicalSelf"] = prefill["medicalSelf"] or _first_num(structured, "amount_80d", "deduction_80d", "medical_premium", "health_insurance")
        prefill["nps"] = prefill["nps"] or _first_num(structured, "amount_80ccd_1b", "deduction_80ccd_1b", "nps", "nps_amount")
        prefill["homeLoanInterest"] = prefill["homeLoanInterest"] or _first_num(structured, "deduction_24b", "home_loan_interest")
        prefill["savingsInterest"] = prefill["savingsInterest"] or _first_num(structured, "amount_80tta", "deduction_80tta", "savings_interest")
        prefill["professionalTax"] = prefill["professionalTax"] or _sanitize_professional_tax(
            _first_num(structured, "professional_tax", "pt"),
            _first_num(structured, "gross_total_income", "gross_salary", "ctc_annual"),
        )
        prefill["other_income"] = prefill["other_income"] or _first_num(structured, "other_income", "other_sources_income")

    filtered_prefill = {k: v for k, v in prefill.items() if _to_num(v) > 0}
    return {
        "doc_type": dtype.value,
        "compute_tax_payload": payload,
        "prefill": filtered_prefill,
    }


def _finding(status: str, field: str, detail: str) -> dict[str, Any]:
    symbol = "✅" if status == "match" else ("⚠️" if status == "mismatch" else "❌")
    return {"status": status, "symbol": symbol, "field": field, "detail": detail}


def _build_filing_json(extracted: dict[str, Any], regime: str | None = None) -> dict[str, Any]:
    form16 = extracted.get("form16") or {}
    ais = extracted.get("ais") or {}
    form26as = extracted.get("form26as") or {}

    gross_salary = form16.get("gross_salary") or form16.get("gross_total_income")
    standard_deduction = form16.get("standard_deduction")
    net_taxable_salary = form16.get("net_taxable_salary") or form16.get("taxable_income")

    interest_total = _sum_amount(ais.get("interest_entries") or [], "amount")
    dividend_total = _sum_amount(ais.get("dividend_entries") or [], "amount")

    stcg_total = _sum_amount([r for r in (ais.get("capital_gains_securities") or []) if (r.get("type") or "").lower() == "stcg"], "amount")
    ltcg_total = _sum_amount([r for r in (ais.get("capital_gains_securities") or []) if (r.get("type") or "").lower() == "ltcg"], "amount")
    other_stcg = _sum_amount([r for r in (ais.get("capital_gains_other") or []) if (r.get("type") or "").lower() == "stcg"], "amount")
    other_ltcg = _sum_amount([r for r in (ais.get("capital_gains_other") or []) if (r.get("type") or "").lower() == "ltcg"], "amount")

    tds_credits = (ais.get("tds_credits") or form26as.get("tds_credits") or [])
    total_tds = _sum_amount(tds_credits, "amount_deducted")

    taxes_paid = ais.get("taxes_paid") or []
    advance_tax = _sum_amount([r for r in taxes_paid if (r.get("type") or "") == "advance"], "amount")
    self_assessment = _sum_amount([r for r in taxes_paid if (r.get("type") or "") == "self_assessment"], "amount")

    total_tax_payable = form16.get("total_tax_payable") or form16.get("total_tax")
    rebate_87a = form16.get("rebate_87a")
    cess = form16.get("health_education_cess") or form16.get("cess")

    balance = None
    try:
        if total_tax_payable is not None:
            balance = float(total_tax_payable) - float(total_tds or 0) - float(advance_tax or 0) - float(self_assessment or 0)
    except Exception:
        balance = None

    return {
        "assessment_year": form16.get("assessment_year") or extracted.get("assessment_year"),
        "personal": {
            "name": form16.get("employee_name"),
            "pan": form16.get("employee_pan") or form16.get("pan") or extracted.get("pan"),
            "regime": (regime if regime in {"old", "new"} else None),
        },
        "income": {
            "salary": {
                "gross": gross_salary,
                "exempt_allowances": form16.get("other_exempt_allowances"),
                "standard_deduction": standard_deduction,
                "net_taxable": net_taxable_salary,
            },
            "interest": {
                "savings": None,
                "fd": None,
                "other": interest_total if interest_total > 0 else None,
            },
            "dividend": dividend_total if dividend_total > 0 else None,
            "capital_gains": {
                "stcg_111a": stcg_total if stcg_total > 0 else None,
                "ltcg_112a": ltcg_total if ltcg_total > 0 else None,
                "other_stcg": other_stcg if other_stcg > 0 else None,
                "other_ltcg": other_ltcg if other_ltcg > 0 else None,
            },
            "other_sources": None,
        },
        "deductions": {
            "80C": form16.get("deduction_80c") or form16.get("amount_80c"),
            "80D": form16.get("deduction_80d") or form16.get("amount_80d"),
            "80CCD1B": form16.get("deduction_80ccd_1b") or form16.get("amount_80ccd_1b"),
            "80G": form16.get("deduction_80g"),
            "80TTA": form16.get("deduction_80tta") or form16.get("amount_80tta"),
            "other": form16.get("other_deductions"),
        },
        "tds_credits": [
            {
                "section": row.get("section"),
                "deductor": row.get("deductor_name"),
                "tan": row.get("tan"),
                "amount": row.get("amount_deducted"),
            }
            for row in tds_credits
        ],
        "taxes_paid": {
            "advance_tax": advance_tax if advance_tax > 0 else None,
            "self_assessment_tax": self_assessment if self_assessment > 0 else None,
        },
        "tax_computed": {
            "gross_tax": form16.get("tax_on_income"),
            "rebate_87a": rebate_87a,
            "cess": cess,
            "total_tax_payable": total_tax_payable,
            "tds_deducted": total_tds if total_tds > 0 else None,
            "balance_payable_or_refund": balance,
        },
    }


@router.post("/review-tax-docs", response_model=TaxDocReviewResponse)
async def review_tax_docs(req: TaxDocReviewRequest) -> TaxDocReviewResponse:
    extracted: dict[str, Any] = {}
    document_types: list[str] = []
    findings: list[dict[str, Any]] = []

    for doc_id in req.doc_ids:
        rec = _docs.get(doc_id)
        if not rec:
            continue
        dtype = rec.get("doc_type") or "other"
        document_types.append(dtype)
        extracted[dtype] = rec.get("structured_data") or {}

    if not extracted:
        return TaxDocReviewResponse(
            document_types=[],
            extracted={},
            findings=[_finding("missing", "documents", "No uploaded documents found for the provided IDs")],
            needs_confirmation=True,
            message="Please upload Form 16/AIS/26AS documents first.",
            filing_json=None,
        )

    form16 = extracted.get("form16") or extracted.get("payslip") or {}
    ais = extracted.get("ais") or {}
    form26as = extracted.get("form26as") or {}

    form16_tds = float(form16.get("total_tds_deposited") or form16.get("tds_deducted") or form16.get("tds") or 0)
    ais_tds = _sum_amount(ais.get("tds_credits") or [], "amount_deducted")
    as26_tds = _sum_amount(form26as.get("tds_credits") or [], "amount_deducted")
    compared_tds = ais_tds or as26_tds
    if form16_tds and compared_tds:
        if abs(form16_tds - compared_tds) <= 1:
            findings.append(_finding("match", "TDS", f"Form16={form16_tds} matches AIS/26AS={compared_tds}"))
        else:
            findings.append(_finding("mismatch", "TDS", f"Form16={form16_tds} vs AIS/26AS={compared_tds}"))
    else:
        findings.append(_finding("missing", "TDS", "TDS not available in one of the documents"))

    form16_salary = float(form16.get("gross_salary") or form16.get("gross_total_income") or 0)
    ais_salary = _sum_amount(ais.get("salary_entries") or [], "amount")
    if form16_salary and ais_salary:
        if abs(form16_salary - ais_salary) <= max(1.0, form16_salary * 0.03):
            findings.append(_finding("match", "Salary", f"Form16={form16_salary} aligns with AIS={ais_salary}"))
        else:
            findings.append(_finding("mismatch", "Salary", f"Form16={form16_salary} vs AIS={ais_salary}"))
    else:
        findings.append(_finding("missing", "Salary", "Salary data missing in Form16 or AIS"))

    extra_income = []
    if _sum_amount(ais.get("interest_entries") or [], "amount") > 0:
        extra_income.append("interest")
    if _sum_amount(ais.get("dividend_entries") or [], "amount") > 0:
        extra_income.append("dividend")
    if _sum_amount(ais.get("capital_gains_securities") or [], "amount") + _sum_amount(ais.get("capital_gains_other") or [], "amount") > 0:
        extra_income.append("capital gains")
    if extra_income:
        findings.append(_finding("mismatch", "AIS extra income", f"AIS contains additional categories: {', '.join(extra_income)}"))
    else:
        findings.append(_finding("match", "AIS extra income", "No additional AIS income categories detected"))

    if ais.get("unconfirmed_entries"):
        findings.append(_finding("mismatch", "AIS status", f"Unconfirmed entries detected: {len(ais.get('unconfirmed_entries') or [])}"))
    else:
        findings.append(_finding("match", "AIS status", "No unconfirmed/disputed AIS entries detected"))

    pans = [
        form16.get("employee_pan") or form16.get("pan"),
        ais.get("pan"),
        form26as.get("pan"),
    ]
    pans = [p for p in pans if p]
    if len(set(pans)) > 1:
        findings.append(_finding("mismatch", "PAN", f"PAN mismatch across documents: {', '.join(sorted(set(pans)))}"))
    elif pans:
        findings.append(_finding("match", "PAN", f"PAN matches across documents: {pans[0]}"))
    else:
        findings.append(_finding("missing", "PAN", "PAN not found in documents"))

    filing_json = None
    needs_confirmation = not req.confirm
    message = "Please review the above. Should I correct anything before I proceed to file your return?"
    if req.confirm:
        filing_json = _build_filing_json(extracted, req.regime)
        needs_confirmation = False
        message = "Confirmed. Filing JSON generated."

    return TaxDocReviewResponse(
        document_types=document_types,
        extracted=extracted,
        findings=findings,
        needs_confirmation=needs_confirmation,
        message=message,
        filing_json=filing_json,
    )


@router.post("/itr1-map")
async def itr1_map(req: ITR1MapRequest) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for doc_id in req.doc_ids:
        rec = _docs.get(doc_id)
        if not rec:
            continue
        dtype = rec.get("doc_type") or "other"
        extracted[dtype] = rec.get("structured_data") or {}

    output = build_itr1_payload(extracted)
    if not extracted:
        output["validation"]["errors"].append("No uploaded documents found for the provided IDs")
    return output


@router.post("/parse-salary", response_model=ParseSalaryResponse)
async def parse_salary(req: ParseSalaryRequest) -> ParseSalaryResponse:
    """Returns salary breakup (CTC, basic, HRA, allowances)."""
    if req.structured_data:
        data = req.structured_data
    elif req.doc_id and req.doc_id in _docs:
        data = _docs[req.doc_id].get("structured_data", {})
    else:
        data = {}
    def _num(v):
        return Decimal(str(v)) if v is not None else Decimal("0")
    basic = _num(data.get("basic_salary") or data.get("basic") or data.get("salary_u_s_17_1"))
    hra = _num(data.get("hra"))
    sa = _num(data.get("special_allowance"))
    oa = _num(data.get("other_allowances"))
    gross = (
        _num(data.get("gross_salary"))
        or _num(data.get("gross_total_income"))
        or _num(data.get("net_taxable_salary"))
        or _num(data.get("taxable_income"))
        or (basic + hra + sa + oa)
    )
    pt = _num(data.get("professional_tax"))
    net = _num(data.get("net_salary")) or _num(data.get("net_taxable_salary")) or (gross - pt)
    ctc = _num(data.get("ctc_annual")) or _num(data.get("gross_total_income"))

    # If gross appears annual (common in Form16), convert to monthly for SalaryBreakup and keep annual CTC.
    converted_annual_to_monthly = False
    if ctc <= 0 and gross > Decimal("300000"):
        ctc = gross
        gross = (gross / Decimal("12")) if gross > 0 else gross
        converted_annual_to_monthly = True

    if ctc <= 0:
        ctc = gross * 12

    if converted_annual_to_monthly:
        if net > gross * 2:
            net = net / Decimal("12")
        if pt > Decimal("5000"):
            pt = pt / Decimal("12")
    breakup = SalaryBreakup(
        ctc=ctc,
        basic=basic,
        hra=hra,
        special_allowance=sa,
        other_allowances=oa,
        professional_tax=pt,
        pt_monthly=pt,
        gross_salary=gross,
        deductions_total=max(Decimal("0"), gross - net),
        net_salary=net,
        month=data.get("month"),
        year=int(data["year"]) if data.get("year") else None,
    )
    return ParseSalaryResponse(breakup=breakup, source="ocr", confidence=0.9)


@router.post("/recommend-deductions", response_model=RecommendDeductionsResponse)
async def recommend_deductions(req: RecommendDeductionsRequest) -> RecommendDeductionsResponse:
    """Returns ranked deduction list with confidence and legal citation."""
    deductions = rule_based_deductions(req.salary_breakup, req.parsed_docs, req.user_profile)
    ranked = rank_deductions_by_impact(deductions, req.user_profile, req.parsed_docs)
    audit_log("recommend_deductions", details={"count": len(ranked)})
    return RecommendDeductionsResponse(
        deductions=ranked,
        regime_suggestion="new" if (req.user_profile.get("prefer_simple") or not ranked) else "old",
    )


@router.post("/calculate-tax", response_model=CalculateTaxResponse)
async def calculate_tax_endpoint(req: CalculateTaxRequest) -> CalculateTaxResponse:
    """Returns tax table under old & new regimes and suggested investments."""
    regime = req.regime or "new"
    row_old = calculate_tax(req.salary_breakup, req.other_income, req.deductions, "old")
    row_new = calculate_tax(req.salary_breakup, req.other_income, req.deductions, "new")
    suggested = suggest_investments(req.salary_breakup, req.other_income, req.deductions)
    recommended = "new" if row_new.total_tax <= row_old.total_tax else "old"
    audit_log("calculate_tax", details={"regime_old_tax": str(row_old.total_tax), "regime_new_tax": str(row_new.total_tax)})
    return CalculateTaxResponse(
        tax_table=[row_old, row_new],
        suggested_investments=suggested,
        recommended_regime=recommended,
    )


@router.post("/conversation", response_model=ConversationResponse)
async def conversation(req: ConversationRequest) -> ConversationResponse:
    """Chat: NLU + RAG + multilingual response; includes TTS/avatar JSON spec."""
    out = await converse(
        message=req.message,
        session_id=req.session_id,
        language_hint=req.language_hint,
        intent_override=req.intent,
        parsed_docs=req.parsed_docs,
        conversation_history=req.conversation_history,
        user_profile=req.user_profile,
        enable_voice=req.enable_voice,
    )
    
    # Keep chat response fast: TTS is fetched separately by frontend from /api/tts
    return ConversationResponse(**out)


@router.get("/tts")
async def tts(text: str, lang: str = "en") -> Response:
    """Generate TTS audio for text. Returns MP3 audio bytes."""
    if not text or len(text.strip()) == 0:
        raise HTTPException(status_code=400, detail="Text is required")
    
    audio_data = await text_to_speech(text, lang)
    if not audio_data:
        raise HTTPException(status_code=503, detail="TTS service not available")
    
    # If data URL, extract base64 content
    if audio_data.startswith("data:audio/mp3;base64,"):
        import base64
        audio_bytes = base64.b64decode(audio_data.replace("data:audio/mp3;base64,", ""))
        return Response(content=audio_bytes, media_type="audio/mpeg")
    
    raise HTTPException(status_code=500, detail="Invalid audio data")


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...), language: str = Form("en")) -> dict[str, Any]:
    """Convert speech to text. Returns transcribed text."""
    try:
        from google.cloud import speech_v1
    except ImportError:
        raise HTTPException(status_code=503, detail="Speech-to-text not available")
    
    try:
        content = await file.read()
        client = speech_v1.SpeechClient()
        audio = speech_v1.RecognitionAudio(content=content)
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            language_code=f"{language}-IN",
            sample_rate_hertz=16000,
        )
        response = client.recognize(config=config, audio=audio)
        
        transcript = ""
        for result in response.results:
            for alternative in result.alternatives:
                transcript += alternative.transcript + " "
        
        return {
            "text": transcript.strip(),
            "language": language,
            "confidence": response.results[0].alternatives[0].confidence if response.results else 0,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"STT Error: {str(e)}")
