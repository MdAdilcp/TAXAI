"""Advanced OCR pipeline for financial documents.

Uses Google Vision for raw OCR, image preprocessing for noisy scans, financial-field
heuristics, and optional LLM-based post-processing to normalize extracted values.
"""
import io
import json
import re
import base64
import os
from pathlib import Path
from typing import Any

import httpx
import numpy as np

try:
    from dotenv import dotenv_values
except Exception:  # pragma: no cover - optional runtime dependency
    dotenv_values = None

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
except Exception:  # pragma: no cover - optional runtime dependency
    Image = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None

try:
    import pdfplumber
except Exception:  # pragma: no cover - optional runtime dependency
    pdfplumber = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional runtime dependency
    PdfReader = None

try:
    import pypdfium2 as pdfium
except Exception:  # pragma: no cover - optional runtime dependency
    pdfium = None

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover - optional runtime dependency
    RapidOCR = None

from app.core.config import get_settings
from app.models.schemas import DocType
from app.services.document_classifier import classify_document_text
from app.services.ocr_schema import (
    INVESTMENT_FIELDS,
    MEDICAL_BILL_FIELDS,
    PAYSLIP_FIELDS,
    RENT_RECEIPT_FIELDS,
    normalize_number,
    normalize_structured,
)
from app.services.universal_extractor import universal_extract_to_dict

_RAPID_OCR_ENGINE: Any | None = None

MONTH_MAP = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "may": "May", "jun": "June", "jul": "July", "aug": "August",
    "sep": "September", "sept": "September", "oct": "October",
    "nov": "November", "dec": "December",
}

FIELD_ALIASES: dict[str, dict[str, list[str]]] = {
    "payslip": {
        "employee_name": ["employee name", "name of employee", "associate name"],
        "employer_name": ["employer", "company", "company name", "organization"],
        "basic_salary": ["basic salary", "basic pay", "basic"],
        "hra": ["hra", "house rent allowance"],
        "special_allowance": ["special allowance"],
        "other_allowances": ["other allowance", "allowances", "conveyance allowance"],
        "gross_salary": ["gross salary", "gross earnings", "gross pay"],
        "professional_tax": ["professional tax"],
        "income_tax_tds": ["income tax", "tds", "tax deducted"],
        "other_deductions": ["other deductions", "deductions"],
        "net_salary": ["net salary", "net pay", "take home"],
        "ctc_annual": ["ctc", "annual ctc", "cost to company"],
    },
    "investment": {
        "provider_name": ["provider", "insurer", "fund house", "institution"],
        "policy_or_fund_name": ["policy name", "fund name", "scheme", "plan"],
        "section": ["section", "deduction section", "u/s", "under section"],
        "amount": ["amount", "invested amount", "premium", "deposit", "investment amount"],
        "financial_year": ["financial year", "fy", "assessment year"],
        "receipt_date": ["receipt date", "date", "payment date"],
    },
    "medical_bill": {
        "hospital_or_provider": ["hospital", "provider", "clinic", "insurance company"],
        "patient_name": ["patient name", "insured name", "member name"],
        "amount": ["amount", "bill amount", "total", "premium"],
        "date": ["date", "invoice date", "receipt date"],
        "description": ["description", "treatment", "service", "plan"],
    },
    "rent_receipt": {
        "landlord_name": ["landlord name", "owner name"],
        "tenant_name": ["tenant name", "employee name", "paid by", "received from"],
        "address": ["address", "premises", "property address"],
        "rent_amount": ["rent amount", "monthly rent", "rent paid", "received a sum of"],
        "pan_landlord": ["pan", "landlord pan", "owner pan"],
    },
}

FORM16_EXPECTED_FIELDS = [
    "pan",
    "assessment_year",
    "gross_total_income",
    "taxable_income",
    "total_tax",
    "tds",
]

FORM16_PART_A_FIELDS = [
    "employer_name", "employer_tan", "employer_pan", "employee_name", "employee_pan",
    "assessment_year", "tds_q1", "tds_q2", "tds_q3", "tds_q4", "total_tds_deposited",
]

FORM16_PART_B_FIELDS = [
    "gross_salary", "salary_u_s_17_1", "perquisites_u_s_17_2", "profits_u_s_17_3",
    "hra_exemption_u_s_10_13a", "lta_exemption_u_s_10_5", "other_exempt_allowances",
    "standard_deduction", "professional_tax", "net_taxable_salary", "deduction_80c",
    "deduction_80d", "deduction_80ccd_1b", "deduction_80g", "deduction_80tta",
    "other_deductions", "total_deductions", "taxable_income", "tax_on_income",
    "rebate_87a", "surcharge", "health_education_cess", "total_tax_payable", "tds_deducted",
]


def _clean_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip(" :-\t") for line in (text or "").splitlines() if line.strip()]


def _split_table_cells(line: str) -> list[str]:
    if not line:
        return []
    if "|" in line:
        parts = [p.strip() for p in re.split(r"\|", line) if p.strip()]
    else:
        parts = [p.strip() for p in re.split(r"\t+|\s{2,}", line) if p.strip()]
    if len(parts) <= 1:
        return []
    return parts


def _norm_header(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _is_numeric_cell(cell: str) -> bool:
    return bool(re.fullmatch(r"(?:₹|rs\.?|inr)?\s*[0-9][0-9,]*(?:\.\d+)?", (cell or "").strip(), re.I))


def _looks_like_header(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False
    numeric = sum(1 for c in cells if _is_numeric_cell(c))
    if numeric >= len(cells) - 1:
        return False
    header_words = [
        "amount", "tds", "deductor", "tan", "section", "status", "salary", "interest",
        "dividend", "capital", "date", "buy", "sell", "challan", "bsr", "remarks",
        "quarter", "q1", "q2", "q3", "q4", "field", "value",
    ]
    joined = " ".join(_norm_header(c) for c in cells)
    return any(w in joined for w in header_words)


def _extract_numbers(text: str) -> list[float]:
    vals = []
    for match in re.finditer(r"(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.\d+)?)", text, re.I):
        num = normalize_number(match.group(1))
        if num > 0:
            vals.append(num)
    return vals


def _extract_first_number(text: str) -> float:
    nums = _extract_numbers(text)
    return nums[0] if nums else 0.0


def _extract_max_number(text: str) -> float:
    nums = _extract_numbers(text)
    return max(nums) if nums else 0.0


def _clean_name(value: str | None) -> str | None:
    if not value:
        return None
    name = re.sub(r"[^A-Za-z.& ]+", " ", value)
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() if len(name) >= 3 else None


def _find_labeled_value(lines: list[str], aliases: list[str]) -> str | None:
    for idx, line in enumerate(lines):
        for alias in aliases:
            pattern = rf"\b{re.escape(alias)}\b\s*(?:[:\-–—]|is)?\s*(.+)$"
            match = re.search(pattern, line, re.I)
            if match:
                value = match.group(1).strip(" :-")
                if value:
                    return value
            if re.search(rf"\b{re.escape(alias)}\b\s*[:\-–—]?\s*$", line, re.I) and idx + 1 < len(lines):
                next_line = lines[idx + 1].strip()
                if next_line and len(next_line) <= 120:
                    return next_line
    return None


def _extract_pan(text: str) -> str | None:
    def _normalize_pan_candidate(raw: str) -> str | None:
        token = re.sub(r"[^A-Z0-9]", "", (raw or "").upper())
        if len(token) != 10:
            return None

        chars = list(token)
        digit_to_alpha = {
            "0": "O",
            "1": "I",
            "2": "Z",
            "4": "A",
            "5": "S",
            "6": "G",
            "7": "T",
            "8": "B",
            "9": "P",
        }
        alpha_to_digit = {
            "O": "0",
            "Q": "0",
            "D": "0",
            "I": "1",
            "L": "1",
            "Z": "2",
            "A": "4",
            "S": "5",
            "G": "6",
            "T": "7",
            "B": "8",
        }

        for idx in (0, 1, 2, 3, 4, 9):
            if chars[idx].isdigit():
                chars[idx] = digit_to_alpha.get(chars[idx], chars[idx])

        for idx in (5, 6, 7, 8):
            if chars[idx].isalpha():
                chars[idx] = alpha_to_digit.get(chars[idx], chars[idx])

        normalized = "".join(chars)
        if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", normalized):
            return normalized
        return None

    upper = (text or "").upper()
    strict = re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", upper)
    if strict:
        return strict.group(0)

    # OCR-correction mode is intentionally limited to PAN-labeled regions
    # to avoid mistaking TAN or section codes as PAN.
    for labeled in re.finditer(
        r"(?:\bPAN\b|PERMANENT\s+ACCOUNT\s+NUMBER)[^A-Z0-9]{0,8}([A-Z0-9\s\-/]{8,20})",
        upper,
    ):
        candidate_raw = labeled.group(1)
        grouped = re.search(r"\b([A-Z0-9]{5})\s*[-/]?\s*([A-Z0-9]{4})\s*[-/]?\s*([A-Z0-9])\b", candidate_raw)
        if grouped:
            fixed = _normalize_pan_candidate("".join(grouped.groups()))
            if fixed:
                return fixed
        for token in re.findall(r"\b[A-Z0-9]{10}\b", candidate_raw):
            fixed = _normalize_pan_candidate(token)
            if fixed:
                return fixed
    return None


def _extract_section(text: str) -> str | None:
    match = re.search(r"\b(80(?:C|CCC|CCD(?:\(?1B\)?)?|D|E|G|TTA|TTB)|24\(b\)|10\(13A\))\b", text or "", re.I)
    if not match:
        return None
    return match.group(1).upper().replace(" ", "")


def _extract_date(text: str) -> str | None:
    match = re.search(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}|[A-Za-z]{3,9}\s+\d{4})\b", text or "")
    return match.group(1) if match else None


def _extract_financial_year(text: str) -> str | None:
    match = re.search(r"\b(?:FY|Financial Year|AY|Assessment Year)\s*[:\-]?\s*(\d{4}\s*[-/]\s*\d{2,4})\b", text or "", re.I)
    if match:
        return re.sub(r"\s+", "", match.group(1))
    return None


def _extract_month_year(text: str) -> tuple[str | None, int | None]:
    match = re.search(r"\b([A-Za-z]{3,9})\s+(\d{4})\b", text or "")
    if match:
        month = MONTH_MAP.get(match.group(1).lower()[:4].rstrip('.'), MONTH_MAP.get(match.group(1).lower()[:3]))
        if month:
            return month, int(match.group(2))
    match = re.search(r"\b(\d{1,2})[/-](\d{4})\b", text or "")
    if match:
        month_num = int(match.group(1))
        if 1 <= month_num <= 12:
            month = list(MONTH_MAP.values())[month_num - 1]
            return month, int(match.group(2))
    return None, None


def _extract_best_amount(lines: list[str], aliases: list[str]) -> float:
    labeled = _find_labeled_value(lines, aliases)
    if labeled:
        amount = _extract_max_number(labeled)
        # Ignore tiny serial/reference numbers often present in heading text.
        if amount > 20:
            return amount

    for idx, line in enumerate(lines):
        lower = line.lower()
        has_alias = any(re.search(rf"\b{re.escape(alias.lower())}\b", lower) for alias in aliases)
        if has_alias:
            # Avoid false positives from legal headings like "Income-tax Act, 1961".
            if "income-tax act" in lower or "income tax act" in lower:
                continue

            # Statement-style PDFs often keep amount in the next line after label text.
            if idx + 1 < len(lines):
                next_line = lines[idx + 1]
                next_amount = _extract_max_number(next_line)
                looks_like_date = bool(re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", next_line))
                if next_amount > 0 and not looks_like_date:
                    return next_amount

            amount = _extract_max_number(line)
            if amount > 20:
                return amount

    # Fallback: return best positive amount on matching lines even if small.
    for line in lines:
        if any(alias in line.lower() for alias in aliases):
            amount = _extract_max_number(line)
            if amount > 0:
                return amount
    return 0.0


def _extract_payslip_from_text(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    data: dict[str, Any] = {}
    aliases = FIELD_ALIASES["payslip"]

    data["employee_name"] = _clean_name(_find_labeled_value(lines, aliases["employee_name"]))
    data["employer_name"] = _clean_name(_find_labeled_value(lines, aliases["employer_name"]))
    data["basic_salary"] = _extract_best_amount(lines, aliases["basic_salary"])
    data["hra"] = _extract_best_amount(lines, aliases["hra"])
    data["special_allowance"] = _extract_best_amount(lines, aliases["special_allowance"])
    data["other_allowances"] = _extract_best_amount(lines, aliases["other_allowances"])
    data["gross_salary"] = _extract_best_amount(lines, aliases["gross_salary"])
    data["professional_tax"] = _extract_best_amount(lines, aliases["professional_tax"])
    data["income_tax_tds"] = _extract_best_amount(lines, aliases["income_tax_tds"])
    data["other_deductions"] = _extract_best_amount(lines, aliases["other_deductions"])
    data["net_salary"] = _extract_best_amount(lines, aliases["net_salary"])
    data["ctc_annual"] = _extract_best_amount(lines, aliases["ctc_annual"])
    data["month"], data["year"] = _extract_month_year(text)

    if not data["gross_salary"]:
        subtotal = sum(float(data.get(k) or 0) for k in ["basic_salary", "hra", "special_allowance", "other_allowances"])
        if subtotal > 0:
            data["gross_salary"] = subtotal
    return normalize_structured({k: v for k, v in data.items() if v not in (None, "", 0, 0.0)}, "payslip")


def _extract_investment_from_text(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    data: dict[str, Any] = {}
    aliases = FIELD_ALIASES["investment"]
    section = _extract_section(text) or _find_labeled_value(lines, aliases["section"])
    amount = _extract_best_amount(lines, aliases["amount"])

    data["provider_name"] = _clean_name(_find_labeled_value(lines, aliases["provider_name"]))
    policy = _find_labeled_value(lines, aliases["policy_or_fund_name"])
    data["policy_or_fund_name"] = policy.strip() if policy else None
    data["section"] = section.upper() if isinstance(section, str) else None
    if amount > 0:
        data["amount"] = amount
    data["financial_year"] = _extract_financial_year(text)
    data["receipt_date"] = _extract_date(text)
    return normalize_structured({k: v for k, v in data.items() if v not in (None, "", 0, 0.0)}, "investment")


def _extract_medical_from_text(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    aliases = FIELD_ALIASES["medical_bill"]
    data: dict[str, Any] = {
        "hospital_or_provider": _clean_name(_find_labeled_value(lines, aliases["hospital_or_provider"])),
        "patient_name": _clean_name(_find_labeled_value(lines, aliases["patient_name"])),
        "date": _extract_date(text),
    }
    amount = _extract_best_amount(lines, aliases["amount"])
    if amount > 0:
        data["amount"] = amount
    description = _find_labeled_value(lines, aliases["description"])
    if description:
        data["description"] = description
    return normalize_structured({k: v for k, v in data.items() if v not in (None, "", 0, 0.0)}, "medical_bill")


def _extract_rent_from_text(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    aliases = FIELD_ALIASES["rent_receipt"]
    data: dict[str, Any] = {
        "landlord_name": _clean_name(_find_labeled_value(lines, aliases["landlord_name"])),
        "tenant_name": _clean_name(_find_labeled_value(lines, aliases["tenant_name"])),
        "address": _find_labeled_value(lines, aliases["address"]),
        "pan_landlord": _extract_pan(_find_labeled_value(lines, aliases["pan_landlord"]) or text),
    }
    amount = _extract_best_amount(lines, aliases["rent_amount"])
    if amount > 0:
        data["rent_amount"] = amount
    data["month"], data["year"] = _extract_month_year(text)
    return normalize_structured({k: v for k, v in data.items() if v not in (None, "", 0, 0.0)}, "rent_receipt")


def _extract_form16_from_text(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    raw_lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

    def amount_for(aliases: list[str]) -> float:
        return _extract_best_amount(lines, aliases)

    def meaningful_form16_amount(key: str, value: float) -> float:
        thresholds = {
            "gross_salary": 50000,
            "salary_u_s_17_1": 10000,
            "perquisites_u_s_17_2": 100,
            "profits_u_s_17_3": 100,
            "standard_deduction": 10000,
            "taxable_income": 50000,
            "tax_on_income": 100,
            "total_tax_payable": 100,
            "tds_deducted": 100,
            "deduction_80c": 1000,
            "deduction_80d": 1000,
            "deduction_80ccd_1b": 1000,
            "deduction_80g": 100,
            "deduction_80tta": 100,
            "total_deductions": 1000,
            "health_education_cess": 10,
            "professional_tax": 100,
            "net_taxable_salary": 10000,
            "total_tds_deposited": 100,
        }
        if key in thresholds and 0 < value < thresholds[key]:
            return 0.0
        return value

    def _extract_amount_from_patterns(patterns: list[str]) -> float:
        best = 0.0
        blob = text or ""
        for pattern in patterns:
            for m in re.finditer(pattern, blob, re.I):
                captures = [g for g in m.groups() if g is not None]
                if not captures:
                    continue
                vals = [normalize_number(c) for c in captures if normalize_number(c) > 0]
                if vals:
                    best = max(best, max(vals))
        return best

    part_a: dict[str, Any] = {}
    part_b: dict[str, Any] = {}

    part_a["employer_name"] = _clean_name(_find_labeled_value(lines, ["employer name", "name and address of employer", "deductor name"]))
    part_a["employee_name"] = _clean_name(_find_labeled_value(lines, ["employee name", "name of employee", "assessee name"]))
    part_a["employer_tan"] = None
    tan_label = _find_labeled_value(lines, ["tan of deductor", "deductor tan", "employer tan", "tan"])
    if tan_label:
        tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", tan_label.upper())
        if tan_match:
            part_a["employer_tan"] = tan_match.group(0)
    if not part_a["employer_tan"]:
        tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", (text or "").upper())
        if tan_match:
            part_a["employer_tan"] = tan_match.group(0)

    part_a["employee_pan"] = _extract_pan(_find_labeled_value(lines, ["employee pan", "pan of employee", "assessee pan"]) or text)
    part_a["employer_pan"] = _extract_pan(_find_labeled_value(lines, ["employer pan", "deductor pan", "pan of deductor"]) or "")
    part_a["assessment_year"] = _extract_financial_year(text)

    for quarter in [1, 2, 3, 4]:
        val = meaningful_form16_amount(
            "total_tds_deposited",
            amount_for([
                f"q{quarter}", f"quarter {quarter}", f"tds q{quarter}", f"tds quarter {quarter}",
                f"quarter {quarter} amount", f"q{quarter} tax deposited",
            ]),
        )
        if val > 0:
            part_a[f"tds_q{quarter}"] = val

    # Column-based quarterly table parsing (Q1..Q4 rows)
    for line in lines:
        qm = re.search(r"\bq\s*([1-4])\b[^0-9₹]*(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.\d+)?)", line, re.I)
        if qm:
            q = int(qm.group(1))
            amt = meaningful_form16_amount("total_tds_deposited", normalize_number(qm.group(2)))
            if amt > 0:
                part_a[f"tds_q{q}"] = amt

    # Some OCR layouts print quarter marker and amount on separate lines.
    for idx, line in enumerate(raw_lines):
        qm = re.fullmatch(r"\s*Q\s*([1-4])\s*", line, re.I)
        if not qm:
            continue
        q = int(qm.group(1))
        window = " ".join(raw_lines[max(0, idx - 3): min(len(raw_lines), idx + 4)])
        candidates = [n for n in _extract_numbers(window) if n >= 100]
        if candidates and f"tds_q{q}" not in part_a:
            # In Form16 quarterly summary rows, the smaller value is usually TDS deposited.
            part_a[f"tds_q{q}"] = min(candidates)

    total_tds = meaningful_form16_amount(
        "total_tds_deposited",
        amount_for(["total tds deposited", "total tax deposited", "total tds"]),
    )
    if total_tds > 0:
        part_a["total_tds_deposited"] = total_tds

    q_sum = sum(float(part_a.get(f"tds_q{q}") or 0) for q in [1, 2, 3, 4])
    if q_sum > 0:
        current_total_tds = float(part_a.get("total_tds_deposited") or 0)
        # Replace obvious year-artifact values like 1961 with quarter sum when available.
        if current_total_tds <= 0 or abs(current_total_tds - 1961.0) < 1 or current_total_tds < q_sum * 0.5:
            part_a["total_tds_deposited"] = q_sum

    amount_map = {
        "gross_total_income": ["gross total income", "gross income"],
        "gross_salary": ["gross salary", "salary as per provisions", "salary u/s 17"],
        "salary_u_s_17_1": ["salary u/s 17(1)", "salary under section 17(1)", "section 17(1)"],
        "perquisites_u_s_17_2": ["perquisites u/s 17(2)", "value of perquisites", "section 17(2)"],
        "profits_u_s_17_3": ["profits in lieu u/s 17(3)", "profits in lieu", "section 17(3)"],
        "hra_exemption_u_s_10_13a": ["hra exemption", "10(13a)", "house rent allowance exempt"],
        "lta_exemption_u_s_10_5": ["lta exemption", "10(5)", "leave travel allowance", "travel concession or assistance"],
        "other_exempt_allowances": ["other exempt allowances", "allowances exempt", "exempt allowances", "allowance to the extent exempt"],
        "standard_deduction": ["standard deduction", "u/s 16(ia)", "section 16(ia)"],
        "professional_tax": ["professional tax", "tax on employment", "16(iii)", "pt"],
        "net_taxable_salary": ["net taxable salary", "income chargeable under the head salaries", "income chargeable under salaries"],
        "deduction_80c": ["80c", "u/s 80c"],
        "deduction_80d": ["80d", "u/s 80d"],
        "deduction_80ccd_1b": ["80ccd(1b)", "80ccd 1b"],
        "deduction_80g": ["80g", "u/s 80g"],
        "deduction_80tta": ["80tta", "u/s 80tta"],
        "other_deductions": ["other deductions", "chapter vi-a other deductions"],
        "total_deductions": ["total deductions", "aggregate of deductible amount", "chapter vi-a total"],
        "taxable_income": ["taxable income", "total taxable income"],
        "tax_on_income": ["tax on total income", "tax on income", "total tax liability"],
        "rebate_87a": ["rebate u/s 87a", "rebate under section 87a"],
        "surcharge": ["surcharge"],
        "health_education_cess": ["health and education cess", "education cess", "cess"],
        "total_tax_payable": ["total tax payable", "net tax payable", "tax payable"],
        "tds_deducted": ["tds deducted", "tax deducted at source on salary", "tax deducted"],
    }
    for key, aliases in amount_map.items():
        val = meaningful_form16_amount(key, amount_for(aliases))
        if val > 0:
            part_b[key] = val

    # Column-based key/value parsing for Part B tables
    for line in raw_lines:
        cells = _split_table_cells(line)
        if len(cells) < 2:
            continue
        label = _norm_header(cells[0])
        value = _extract_max_number(" ".join(cells[1:]))
        if value <= 0:
            continue
        for key, aliases in amount_map.items():
            if key in part_b:
                continue
            if any(_norm_header(alias) in label for alias in aliases):
                value = meaningful_form16_amount(key, value)
                if value > 0:
                    part_b[key] = value
                break

    regex_overrides: dict[str, list[str]] = {
        "tax_on_income": [
            r"tax\s+on\s+total\s+income[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
            r"tax\s+on\s+income[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
        ],
        "total_tax_payable": [
            r"net\s+tax\s+payable[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
            r"total\s+tax\s+payable[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
        ],
        "health_education_cess": [
            r"health\s+and\s+education\s+cess[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
        ],
        "net_taxable_salary": [
            r"income\s+chargeable\s+under\s+the\s+head\s+\"?salaries\"?[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
        ],
        "deduction_80c": [
            r"total\s+deduction\s+under\s+section\s+80c[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)\s+(?:[0-9][0-9,]*(?:\.\d+)?)",
            r"total\s+deduction\s+under\s+section\s+80c[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
        ],
        "lta_exemption_u_s_10_5": [
            r"travel\s+concession\s+or\s+assistance\s+under\s+section\s+10\s*\(\s*5\s*\)[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
            r"lta\s+exemption[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
        ],
        "professional_tax": [
            r"tax\s+on\s+employment\s+under\s+section\s+16\s*\(\s*iii\s*\)[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
            r"professional\s+tax[^\n\r]*?([0-9][0-9,]*(?:\.\d+)?)",
        ],
    }

    for key, patterns in regex_overrides.items():
        current = normalize_number(part_b.get(key))
        if current <= 0:
            val = meaningful_form16_amount(key, _extract_amount_from_patterns(patterns))
            if val > 0:
                part_b[key] = val

    # Drop common section-code artifacts from TDS-like fields.
    tds_val = normalize_number(part_b.get("tds_deducted"))
    if 0 < tds_val < 500:
        part_b.pop("tds_deducted", None)

    total_tds_val = normalize_number(part_a.get("total_tds_deposited"))
    gross_salary_val = normalize_number(part_b.get("gross_salary"))
    total_tax_payable_val = normalize_number(part_b.get("total_tax_payable"))
    if total_tds_val > 0 and gross_salary_val > 0 and total_tax_payable_val > 0:
        if total_tds_val > gross_salary_val * 0.9 and total_tds_val > total_tax_payable_val * 2.0:
            part_a.pop("total_tds_deposited", None)

    merged = {
        "doc_subtype": "form16",
        "part_a": {k: v for k, v in part_a.items() if v not in (None, "", 0, 0.0)},
        "part_b": {k: v for k, v in part_b.items() if v not in (None, "", 0, 0.0)},
    }
    merged.update(merged["part_a"])
    merged.update(merged["part_b"])
    return normalize_structured(merged, "other")


def _extract_ais_from_text(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    raw_lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    data: dict[str, Any] = {
        "doc_subtype": "ais",
        "salary_entries": [],
        "interest_entries": [],
        "dividend_entries": [],
        "capital_gains_securities": [],
        "capital_gains_other": [],
        "tds_credits": [],
        "taxes_paid": [],
        "high_value_transactions": [],
        "unconfirmed_entries": [],
    }

    pan = _extract_pan(text)
    if pan:
        data["pan"] = pan

    current_header: list[str] = []
    current_mode: str | None = None

    def _set_mode(header_cells: list[str]) -> str | None:
        header = " ".join(_norm_header(c) for c in header_cells)
        if any(x in header for x in ["salary", "employer", "status"]):
            return "salary"
        if all(x in header for x in ["source", "type", "amount"]) and "section" not in header:
            return "interest"
        if any(x in header for x in ["interest", "bank", "nbfc"]):
            return "interest"
        if any(x in header for x in ["dividend", "company"]):
            return "dividend"
        if any(x in header for x in ["capital", "gain", "scrip", "buy", "sell"]):
            return "capital"
        if any(x in header for x in ["tds", "deductor", "tan", "section"]):
            return "tds"
        if any(x in header for x in ["advance", "self assessment", "challan", "bsr"]):
            return "taxes"
        if any(x in header for x in ["high value", "transaction", "remarks"]):
            return "hvt"
        return None

    for line in raw_lines:
        lower = line.lower()
        amount = _extract_max_number(line)
        status = "unconfirmed" if "unconfirmed" in lower or "pending" in lower else "confirmed"

        cells = _split_table_cells(line)
        if cells and _looks_like_header(cells):
            current_header = cells
            current_mode = _set_mode(cells)
            continue
        if cells and current_mode and len(cells) >= 2:
            if current_mode == "salary":
                row_amount = _extract_max_number(" ".join(cells))
                if row_amount > 0:
                    data["salary_entries"].append({
                        "employer": cells[0],
                        "amount": row_amount,
                        "tds": _extract_max_number(cells[-1]) if len(cells) >= 3 else None,
                        "status": "unconfirmed" if "unconfirmed" in " ".join(c.lower() for c in cells) else "confirmed",
                    })
                    continue
            elif current_mode == "interest":
                row_amount = _extract_max_number(" ".join(cells))
                if row_amount > 0:
                    joined = " ".join(cells).lower()
                    data["interest_entries"].append({
                        "source": cells[0],
                        "type": "fd" if "fd" in joined else "rd" if "rd" in joined else "savings" if "saving" in joined else None,
                        "amount": row_amount,
                        "tds": _extract_max_number(cells[-1]) if len(cells) >= 3 else None,
                    })
                    continue
            elif current_mode == "dividend":
                row_amount = _extract_max_number(" ".join(cells))
                if row_amount > 0:
                    data["dividend_entries"].append({"company": cells[0], "amount": row_amount, "tds": _extract_max_number(cells[-1]) if len(cells) >= 3 else None})
                    continue
            elif current_mode == "tds":
                row_amount = _extract_max_number(" ".join(cells))
                if row_amount > 0:
                    tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", " ".join(cells).upper())
                    data["tds_credits"].append({
                        "section": cells[0] if re.search(r"\b\d{3}[A-Z]*\b", cells[0], re.I) else None,
                        "deductor_name": cells[0] if not re.search(r"\b\d{3}[A-Z]*\b", cells[0], re.I) else (cells[1] if len(cells) > 1 else None),
                        "tan": tan_match.group(0) if tan_match else None,
                        "amount_deducted": row_amount,
                    })
                    continue
            elif current_mode == "taxes":
                row_amount = _extract_max_number(" ".join(cells))
                if row_amount > 0:
                    joined = " ".join(cells).lower()
                    data["taxes_paid"].append({
                        "type": "advance" if "advance" in joined else "self_assessment" if "self" in joined else None,
                        "bsr_code": next((c for c in cells if re.fullmatch(r"\d{7}", c)), None),
                        "date": next((c for c in cells if _extract_date(c)), None),
                        "amount": row_amount,
                        "challan_no": next((c for c in cells if re.fullmatch(r"\d{5,}", c)), None),
                    })
                    continue
            elif current_mode == "hvt":
                row_amount = _extract_max_number(" ".join(cells))
                if row_amount > 0:
                    data["high_value_transactions"].append({"type": cells[0], "amount": row_amount, "remarks": " ".join(cells[1:])})
                    continue

        if "salary" in lower and amount > 0:
            entry = {"employer": None, "amount": amount, "tds": None, "status": status}
            tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", line.upper())
            if tan_match:
                entry["tan"] = tan_match.group(0)
            data["salary_entries"].append(entry)
        elif "interest" in lower and amount > 0:
            data["interest_entries"].append({
                "source": "bank" if "bank" in lower else "nbfc" if "nbfc" in lower else None,
                "type": "fd" if "fd" in lower else "rd" if "rd" in lower else "savings" if "savings" in lower else None,
                "amount": amount,
                "tds": None,
            })
        elif "dividend" in lower and amount > 0:
            data["dividend_entries"].append({"company": None, "amount": amount, "tds": None})
        elif any(x in lower for x in ["capital gain", "stcg", "ltcg"]) and amount > 0:
            entry = {"description": line, "amount": amount, "type": "stcg" if "stcg" in lower else "ltcg" if "ltcg" in lower else None}
            if any(x in lower for x in ["equity", "security", "mf", "mutual fund", "scrip"]):
                data["capital_gains_securities"].append(entry)
            else:
                data["capital_gains_other"].append(entry)
        elif any(x in lower for x in ["tds", "tax deducted"]) and amount > 0:
            tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", line.upper())
            data["tds_credits"].append({
                "section": None,
                "deductor_name": None,
                "tan": tan_match.group(0) if tan_match else None,
                "amount_deducted": amount,
            })
        elif any(x in lower for x in ["advance tax", "self assessment", "challan"]) and amount > 0:
            data["taxes_paid"].append({
                "type": "advance" if "advance" in lower else "self_assessment" if "self" in lower else None,
                "bsr_code": None,
                "date": _extract_date(line),
                "amount": amount,
                "challan_no": None,
            })
        elif any(x in lower for x in ["high value", "sft", "transaction"]) and amount > 0:
            data["high_value_transactions"].append({"type": None, "amount": amount, "remarks": line})

        if status == "unconfirmed":
            data["unconfirmed_entries"].append({"line": line})

    return normalize_structured(data, "other")


def _extract_form26as_from_text(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    raw_lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    data: dict[str, Any] = {"doc_subtype": "form26as", "tds_credits": []}
    pan = _extract_pan(text)
    if pan:
        data["pan"] = pan

    # Fast path: parse markdown-style table rows directly when present.
    table_rows: list[dict[str, Any]] = []
    row_re = re.compile(
        r"\|\s*\d+\s*\|\s*([0-9]{3}[A-Z()]{0,6})\s*\|\s*[^|]*\|\s*([0-9][0-9,]*(?:\.\d+)?)\s*\|\s*([0-9][0-9,]*(?:\.\d+)?)\s*\|",
        re.I,
    )
    for m in row_re.finditer(text or ""):
        section = (m.group(1) or "").upper().strip()
        amount_deducted = normalize_number(m.group(3))
        if amount_deducted >= 10 and re.search(r"\b\d{3}[A-Z()]*\b", section, re.I):
            table_rows.append({
                "section": section,
                "deductor_name": None,
                "tan": None,
                "amount_deducted": amount_deducted,
            })

    if table_rows:
        data["tds_credits"] = table_rows
        data["total_tds_deposited"] = sum(normalize_number(r.get("amount_deducted")) for r in table_rows)
        return normalize_structured(data, "other")

    total_tds = 0.0
    current_header: list[str] = []

    def _header_index(headers: list[str], aliases: list[str]) -> int:
        normalized = [_norm_header(h) for h in headers]
        for i, h in enumerate(normalized):
            if any(a in h for a in aliases):
                return i
        return -1

    for line in raw_lines:
        lower = line.lower()
        cells = _split_table_cells(line)
        if cells and _looks_like_header(cells):
            current_header = cells
            continue

        if cells and current_header and len(cells) >= 2:
            sec_idx = _header_index(current_header, ["section code", "section"])
            ded_idx = _header_index(current_header, ["deductor name", "name of deductor", "deductor"])
            tan_idx = _header_index(current_header, ["tan"])
            tax_idx = _header_index(current_header, ["tax deducted", "amount deducted", "tax collected", "amount collected"])

            # Parse row entries only for headers that include a tax amount column.
            if tax_idx < 0:
                continue

            section = cells[sec_idx] if 0 <= sec_idx < len(cells) else None
            if section and not re.search(r"\b\d{3}[A-Z()]*\b", section, re.I):
                section = None

            deductor_name = cells[ded_idx] if 0 <= ded_idx < len(cells) else None
            tan_cell = cells[tan_idx] if 0 <= tan_idx < len(cells) else ""
            tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", (tan_cell or "").upper())
            if not tan_match:
                tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", " ".join(cells).upper())

            row_amount = 0.0
            if 0 <= tax_idx < len(cells):
                row_amount = _extract_max_number(cells[tax_idx])
            if row_amount <= 0 and len(cells) >= 3:
                # Conservative fallback for malformed headers: often tax amount is one of the last numeric columns.
                row_amount = max(_extract_max_number(cells[-1]), _extract_max_number(cells[-2]))

            if row_amount >= 10:
                data["tds_credits"].append({
                    "section": section,
                    "deductor_name": deductor_name,
                    "tan": tan_match.group(0) if tan_match else None,
                    "amount_deducted": row_amount,
                })
                total_tds += row_amount
                continue

        if any(x in lower for x in ["tax deducted", "amount deducted", "tax collected", "amount collected"]):
            amount = _extract_max_number(line)
            has_tan = bool(re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", line.upper()))
            has_section = bool(re.search(r"\b\d{3}[A-Z()]*\b", line, re.I))
            if amount >= 10 and (has_tan or has_section):
                tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", line.upper())
                data["tds_credits"].append({
                    "section": None,
                    "deductor_name": None,
                    "tan": tan_match.group(0) if tan_match else None,
                    "amount_deducted": amount,
                })
                total_tds += amount

        # Plain-text fallback for OCR outputs that lose table structure.
        if not cells and any(x in lower for x in ["tds", "deduct", "tax credit", "credit statement", "section"]):
            amount = _extract_max_number(line)
            if amount >= 10:
                sec_match = re.search(r"\b(\d{3}[A-Z()]{0,6})\b", line, re.I)
                tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", line.upper())
                deductor_name = None
                if tan_match:
                    prefix = line[:tan_match.start()].strip(" :-\t,")
                    deductor_name = prefix if len(prefix) >= 3 else None
                elif sec_match:
                    prefix = line[:sec_match.start()].strip(" :-\t,")
                    deductor_name = prefix if len(prefix) >= 3 else None
                else:
                    prefix = re.sub(r"(?:tds|tax credit|credit statement|amount deducted|amount collected|tax deducted)\b.*$", "", line, flags=re.I).strip(" :-\t,")
                    if prefix and not re.fullmatch(r"[0-9,./\- ]+", prefix):
                        deductor_name = prefix
                data["tds_credits"].append({
                    "section": sec_match.group(1).upper() if sec_match else None,
                    "deductor_name": deductor_name,
                    "tan": tan_match.group(0) if tan_match else None,
                    "amount_deducted": amount,
                })
                total_tds += amount
    if total_tds > 0:
        data["total_tds_deposited"] = total_tds
    return normalize_structured(data, "other")


def _extract_pdf_text_layer(content: bytes, max_pages: int | None = None) -> tuple[str, str, list[int]]:
    if pdfplumber is None and PdfReader is None:
        return "", "scanned", []

    # Fast fallback path with pypdf
    if pdfplumber is None and PdfReader is not None:
        try:
            reader = PdfReader(io.BytesIO(content))
            pages_text: list[str] = []
            unreadable_pages: list[int] = []
            pages = reader.pages[:max_pages] if max_pages and max_pages > 0 else reader.pages
            for idx, page in enumerate(pages, start=1):
                text = (page.extract_text() or "").strip()
                pages_text.append(text)
                if len(text) < 20:
                    unreadable_pages.append(idx)

            if not pages_text:
                return "", "scanned", []
            if len(unreadable_pages) == 0:
                return "\n\n".join(pages_text).strip(), "text-based", []
            if len(unreadable_pages) == len(pages_text):
                return "", "scanned", unreadable_pages
            merged = "\n\n".join(p for p in pages_text if p).strip()
            return merged, "hybrid", unreadable_pages
        except Exception:
            return "", "scanned", []

    try:
        pages_text: list[str] = []
        unreadable_pages: list[int] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages = pdf.pages[:max_pages] if max_pages and max_pages > 0 else pdf.pages
            for idx, page in enumerate(pages, start=1):
                page_text = (page.extract_text() or "").strip()
                pages_text.append(page_text)
                if len(page_text) < 20:
                    unreadable_pages.append(idx)

        if not pages_text:
            return "", "scanned", []
        if len(unreadable_pages) == 0:
            return "\n\n".join(pages_text).strip(), "text-based", []
        if len(unreadable_pages) == len(pages_text):
            return "", "scanned", unreadable_pages
        merged = "\n\n".join(p for p in pages_text if p).strip()
        return merged, "hybrid", unreadable_pages
    except Exception:
        return "", "scanned", []


def _extract_pdf_images(content: bytes, max_pages: int = 6) -> list[bytes]:
    """Extract embedded page images from scanned PDFs using pypdf."""
    if PdfReader is None:
        return []

    def _to_png_bytes(raw: bytes) -> bytes | None:
        if not raw:
            return None
        if Image is None:
            return bytes(raw)
        try:
            with Image.open(io.BytesIO(raw)) as img:
                out = io.BytesIO()
                img.convert("RGB").save(out, format="PNG")
                return out.getvalue()
        except Exception:
            return None

    def _pil_to_png_bytes(pil_img: Any) -> bytes | None:
        if pil_img is None:
            return None
        try:
            out = io.BytesIO()
            pil_img.convert("RGB").save(out, format="PNG")
            return out.getvalue()
        except Exception:
            return None

    def _collect_images_from_xobject(xobj: Any, out: list[bytes], depth: int = 0) -> None:
        if depth > 6 or xobj is None:
            return
        try:
            values = xobj.values() if hasattr(xobj, "values") else []
            for obj in values:
                try:
                    resolved = obj.get_object() if hasattr(obj, "get_object") else obj
                    subtype = str(resolved.get("/Subtype", "")) if hasattr(resolved, "get") else ""
                    if subtype == "/Image":
                        data = None
                        if hasattr(resolved, "get_data"):
                            data = resolved.get_data()
                        elif hasattr(obj, "data"):
                            data = obj.data
                        if data and isinstance(data, (bytes, bytearray)):
                            png = _to_png_bytes(bytes(data))
                            if png:
                                out.append(png)
                    elif subtype == "/Form":
                        nested = resolved.get("/Resources", {}).get("/XObject") if hasattr(resolved, "get") else None
                        _collect_images_from_xobject(nested, out, depth + 1)
                except Exception:
                    continue
        except Exception:
            return

    images: list[bytes] = []
    try:
        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages[:max_pages]:
            try:
                page_images = getattr(page, "images", []) or []
                for img in page_images:
                    pil_img = getattr(img, "image", None)
                    png_from_pil = _pil_to_png_bytes(pil_img)
                    if png_from_pil:
                        images.append(png_from_pil)
                        continue

                    data = getattr(img, "data", None)
                    if data and isinstance(data, (bytes, bytearray)):
                        png = _to_png_bytes(bytes(data))
                        if png:
                            images.append(png)

                # Fallback for PDFs where images are nested under form XObjects.
                if not page_images:
                    resources = page.get("/Resources", {}) if hasattr(page, "get") else {}
                    xobj = resources.get("/XObject") if hasattr(resources, "get") else None
                    _collect_images_from_xobject(xobj, images)
            except Exception:
                continue
    except Exception:
        images = []

    # Fallback for scanned PDFs with no directly extractable embedded images:
    # render pages to PNG via pypdfium2 and OCR those images.
    if not images and pdfium is not None and Image is not None:
        try:
            pdf = pdfium.PdfDocument(content)
            page_count = min(len(pdf), max_pages)
            for page_index in range(page_count):
                page = pdf[page_index]
                bitmap = page.render(scale=2.0)
                pil_image = bitmap.to_pil()
                out = io.BytesIO()
                pil_image.convert("RGB").save(out, format="PNG")
                images.append(out.getvalue())
        except Exception:
            pass

    return images


def _get_rapidocr_engine() -> Any | None:
    global _RAPID_OCR_ENGINE
    if RapidOCR is None:
        return None
    if _RAPID_OCR_ENGINE is None:
        try:
            _RAPID_OCR_ENGINE = RapidOCR()
        except Exception:
            _RAPID_OCR_ENGINE = None
    return _RAPID_OCR_ENGINE


def _ocr_with_rapidocr_image(content: bytes) -> tuple[str, float]:
    engine = _get_rapidocr_engine()
    if engine is None or Image is None:
        return "", 0.0

    try:
        with Image.open(io.BytesIO(content)) as img:
            arr = np.array(img.convert("RGB"))
    except Exception:
        return "", 0.0

    try:
        result, elapsed = engine(arr)
    except Exception:
        return "", 0.0

    if not result:
        return "", 0.0

    texts: list[str] = []
    confidences: list[float] = []
    for row in result:
        if not row or len(row) < 3:
            continue
        text = str(row[1] or "").strip()
        if text:
            texts.append(text)
        try:
            confidences.append(float(row[2]))
        except Exception:
            pass

    if not texts:
        return "", 0.0

    merged = "\n".join(texts).strip()
    confidence = sum(confidences) / len(confidences) if confidences else (0.72 if len(merged) > 40 else 0.5)
    if elapsed and confidence < 0.3:
        confidence = 0.3
    return merged, confidence


def _extract_generic_tax_statement_fields(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    data: dict[str, Any] = {}

    pan = _extract_pan(text)
    if pan:
        data["pan"] = pan

    tan_match = re.search(r"\b[A-Z]{4}[0-9]{5}[A-Z]\b", (text or "").upper())
    if tan_match:
        data["tan"] = tan_match.group(0)

    ay_match = re.search(r"\b(?:AY|Assessment Year)\s*[:\-]?\s*(\d{4}\s*[-/]\s*\d{2,4})\b", text or "", re.I)
    if ay_match:
        data["assessment_year"] = re.sub(r"\s+", "", ay_match.group(1))

    fy = _extract_financial_year(text)
    if fy:
        data["financial_year"] = fy

    amount_aliases = {
        "gross_total_income": ["gross total income", "gross income", "total income"],
        "total_deductions": ["total deductions", "chapter vi-a deductions", "deductions"],
        "taxable_income": ["taxable income", "total taxable income", "income chargeable"],
        "tax_before_cess": ["tax before cess", "income tax on total income", "tax payable before cess"],
        "cess": ["health and education cess", "education cess", "cess"],
        "total_tax": ["total tax", "total tax liability", "tax payable"],
        "tds": ["tds", "tax deducted at source", "tax deducted"],
        "refund": ["refund", "refund due", "tax refund"],
        "rebate_87a": ["rebate under section 87a", "rebate u/s 87a", "rebate 87a"],
        "standard_deduction": ["standard deduction"],
    }

    for key, aliases in amount_aliases.items():
        amount = _extract_best_amount(lines, aliases)
        if amount > 0:
            data[key] = amount

    tax_before = normalize_number(data.get("tax_before_cess"))
    cess = normalize_number(data.get("cess"))
    total_tax = normalize_number(data.get("total_tax"))
    if tax_before <= 0 and total_tax > 0 and cess > 0 and total_tax >= cess:
        data["tax_before_cess"] = total_tax - cess
    if total_tax <= 0 and tax_before > 0 and cess > 0:
        data["total_tax"] = tax_before + cess

    # Section-wise deduction extraction commonly present in AIS/Form 16 statements
    section_patterns = [
        ("amount_80c", r"\b80C\b[^\n\r:]*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.\d+)?)"),
        ("amount_80d", r"\b80D\b[^\n\r:]*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.\d+)?)"),
        ("amount_80ccd_1b", r"\b80CCD\s*\(?1B\)?\b[^\n\r:]*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.\d+)?)"),
        ("amount_80tta", r"\b80TTA\b[^\n\r:]*[:\-]?\s*(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.\d+)?)"),
    ]
    for field, pattern in section_patterns:
        m = re.search(pattern, text or "", re.I)
        if m:
            val = normalize_number(m.group(1))
            if val > 0:
                data[field] = val

    return normalize_structured(data, "other")


def _map_tax_statement_to_calc_fields(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)

    # Canonicalize key statement fields so quality checks and downstream payloads
    # are consistent across Form16/statement layouts.
    if not out.get("pan"):
        out["pan"] = out.get("employee_pan") or out.get("employeePan")
    if not out.get("assessment_year"):
        out["assessment_year"] = out.get("ay") or out.get("assessmentYear")

    total_tax = normalize_number(out.get("total_tax"))
    if total_tax <= 0:
        total_tax_candidate = normalize_number(out.get("total_tax_payable") or out.get("tax_payable"))
        if total_tax_candidate > 0:
            out["total_tax"] = total_tax_candidate

    tds_val = normalize_number(out.get("tds"))
    if tds_val <= 0:
        tds_candidate = normalize_number(out.get("tds_deducted") or out.get("total_tds_deposited") or out.get("income_tax_tds"))
        if tds_candidate > 0:
            out["tds"] = tds_candidate

    gti = normalize_number(out.get("gross_total_income"))
    if gti <= 0:
        gross_salary = normalize_number(out.get("gross_salary"))
        # Treat gross salary as annual if it is clearly not monthly.
        if gross_salary > 300000:
            out["gross_total_income"] = gross_salary
        elif gross_salary > 0 and normalize_number(out.get("ctc_annual")) > 0:
            out["gross_total_income"] = normalize_number(out.get("ctc_annual"))

    if normalize_number(out.get("taxable_income")) <= 0:
        taxable = normalize_number(out.get("net_taxable_salary"))
        if taxable > 0:
            out["taxable_income"] = taxable

    gross_total_income = normalize_number(out.get("gross_total_income"))
    taxable_income = normalize_number(out.get("taxable_income"))
    total_deductions = normalize_number(out.get("total_deductions"))

    if gross_total_income > 0:
        out.setdefault("ctc_annual", gross_total_income)
        gross_salary = normalize_number(out.get("gross_salary"))
        doc_subtype = str(out.get("doc_subtype") or "").lower()
        # Gross total income is annual. If gross_salary looks annual/noisy, convert to monthly.
        if doc_subtype != "form16" and (gross_salary <= 0 or gross_salary >= gross_total_income * 0.9 or gross_salary > 300000):
            out["gross_salary"] = round(gross_total_income / 12.0, 2)
    if taxable_income > 0 and gross_total_income > 0 and total_deductions <= 0:
        inferred = max(0.0, gross_total_income - taxable_income)
        if inferred > 0:
            out.setdefault("total_deductions", inferred)
    if total_deductions > 0:
        out.setdefault("other_deductions", total_deductions)

    if normalize_number(out.get("tds")) > 0:
        out.setdefault("income_tax_tds", normalize_number(out.get("tds")))
    if normalize_number(out.get("amount_80c")) > 0:
        out.setdefault("total_80c", normalize_number(out.get("amount_80c")))
    if normalize_number(out.get("amount_80d")) > 0:
        out.setdefault("health_insurance", normalize_number(out.get("amount_80d")))

    assessment_year = str(out.get("assessment_year") or "")
    ay_match = re.search(r"(\d{4})\s*[-/]\s*(\d{2,4})", assessment_year)
    if ay_match:
        start_year = int(ay_match.group(1))
        year_value = out.get("year")
        year_int = None
        try:
            year_int = int(year_value)
        except Exception:
            year_int = None
        if year_int is None or year_int < 1900 or year_int > 2100:
            out["year"] = max(1900, start_year - 1)

    return out


def _to_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _canonicalize_structured_output(data: dict[str, Any], doc_type: DocType) -> dict[str, Any]:
    out = dict(data or {})

    # Normalize list-like sections for statement documents.
    if doc_type in {DocType.ais, DocType.form26as}:
        tds_rows = _to_list_of_dicts(out.get("tds_credits"))
        norm_rows: list[dict[str, Any]] = []
        seen: set[tuple[str | None, str | None, float]] = set()
        for row in tds_rows:
            amt = normalize_number(row.get("amount_deducted") or row.get("amount") or 0)
            section = row.get("section")
            deductor_name = row.get("deductor_name") or row.get("deductor") or row.get("source")
            tan = row.get("tan")

            # Drop obvious OCR noise rows.
            if amt <= 0:
                continue
            if doc_type == DocType.form26as:
                if amt < 100:
                    continue
                if section and not re.search(r"\b\d{3}[A-Z()]*\b", str(section), re.I):
                    section = None
                if not section and not tan and not deductor_name:
                    continue

            key = (str(section).upper() if section else None, str(tan).upper() if tan else None, float(amt))
            if key in seen:
                continue
            seen.add(key)

            norm_rows.append({
                "section": section,
                "deductor_name": deductor_name,
                "tan": tan,
                "amount_deducted": amt,
            })
        out["tds_credits"] = norm_rows
        row_total = sum(normalize_number(r.get("amount_deducted")) for r in norm_rows)
        reported_total = normalize_number(out.get("total_tds_deposited"))
        if norm_rows and (
            reported_total <= 0
            or reported_total < (row_total * 0.5)
            or reported_total > (row_total * 2.0)
        ):
            out["total_tds_deposited"] = row_total
        elif doc_type == DocType.form26as and norm_rows:
            # For Form26AS, prefer clean recomputed total over noisy OCR aggregate.
            out["total_tds_deposited"] = row_total

    # Form16/statement cleanup: avoid passing obvious OCR outliers as professional tax.
    if doc_type in {DocType.form16, DocType.payslip, DocType.other}:
        pt = normalize_number(out.get("professional_tax"))
        gross = max(
            normalize_number(out.get("gross_total_income")),
            normalize_number(out.get("ctc_annual")),
            normalize_number(out.get("gross_salary")),
        )
        hard_cap = 10000.0
        soft_cap = gross * 0.02 if gross > 0 else hard_cap
        if pt > min(hard_cap, soft_cap):
            out.pop("professional_tax", None)

    form16_like = doc_type == DocType.form16 or str(out.get("doc_subtype") or "").lower() == "form16"
    if form16_like:
        # Suppress section-code leakage like 17(1)/10(13A) being interpreted as amounts.
        for key, min_val in [
            ("salary_u_s_17_1", 10000),
            ("perquisites_u_s_17_2", 100),
            ("profits_u_s_17_3", 100),
            ("hra_exemption_u_s_10_13a", 500),
            ("lta_exemption_u_s_10_5", 500),
            ("other_exempt_allowances", 500),
            ("gross_salary", 10000),
            ("standard_deduction", 10000),
            ("net_taxable_salary", 10000),
            ("professional_tax", 100),
            ("deduction_80c", 1000),
            ("deduction_80d", 1000),
            ("deduction_80ccd_1b", 1000),
            ("deduction_80tta", 100),
            ("total_deductions", 1000),
            ("tds_deducted", 500),
            ("total_tds_deposited", 500),
        ]:
            val = normalize_number(out.get(key))
            if 0 < val < min_val:
                out.pop(key, None)

        # Guard against tiny OCR artifacts (e.g., 14 from section 17(1)).
        for key, min_val in [
            ("gross_total_income", 50000),
            ("taxable_income", 50000),
            ("total_tax", 100),
            ("tds", 500),
        ]:
            val = normalize_number(out.get(key))
            if 0 < val < min_val:
                out.pop(key, None)

        ay = str(out.get("assessment_year") or "").strip()
        if ay and not re.fullmatch(r"\d{4}\s*[-/]\s*\d{2,4}", ay):
            out.pop("assessment_year", None)

    return out


def _flatten_nested_ocr_fields(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)

    employee = out.get("employee")
    if isinstance(employee, dict):
        if employee.get("employee_name") and not out.get("employee_name"):
            out["employee_name"] = employee.get("employee_name")
        if employee.get("employee_pan") and not out.get("employee_pan"):
            out["employee_pan"] = employee.get("employee_pan")

    employer = out.get("employer")
    if isinstance(employer, dict):
        if employer.get("employer_name") and not out.get("employer_name"):
            out["employer_name"] = employer.get("employer_name")
        if employer.get("employer_tan") and not out.get("employer_tan"):
            out["employer_tan"] = employer.get("employer_tan")

    tds_obj = out.get("tds")
    if isinstance(tds_obj, dict):
        if tds_obj.get("income_tax_tds") and not out.get("income_tax_tds"):
            out["income_tax_tds"] = tds_obj.get("income_tax_tds")
        if tds_obj.get("total_tds_deposited") and not out.get("total_tds_deposited"):
            out["total_tds_deposited"] = tds_obj.get("total_tds_deposited")

    # Guard against false extraction of "1961" from "Income-tax Act, 1961"
    tds_val = normalize_number(out.get("income_tax_tds") or out.get("tds") or 0)
    if 0 < tds_val <= 5000:
        larger_candidates = [
            normalize_number(out.get("tds_deducted") or 0),
            normalize_number(out.get("total_tds_deposited") or 0),
            normalize_number(out.get("total_tax_payable") or 0),
        ]
        better = max(larger_candidates) if larger_candidates else 0.0
        if better > tds_val:
            out["income_tax_tds"] = better
            out["tds"] = better

    return out


def _is_income_tax_statement(text: str, structured: dict[str, Any] | None = None) -> bool:
    t = (text or "").lower()
    structured = structured or {}
    keyword_hit = any(
        key in t
        for key in [
            "form 16",
            "income tax statement",
            "annual tax statement",
            "part b",
            "assessment year",
            "tax deducted at source",
            "tds",
        ]
    )
    structured_hit = sum(
        1
        for key in ["pan", "assessment_year", "gross_total_income", "taxable_income", "total_tax", "tds"]
        if structured.get(key) not in (None, "", 0, 0.0, [], {})
    )
    return keyword_hit or structured_hit >= 2


def _allowed_fields_for(doc_type: DocType) -> list[str]:
    if doc_type == DocType.payslip:
        return PAYSLIP_FIELDS
    if doc_type == DocType.investment:
        return INVESTMENT_FIELDS
    if doc_type == DocType.medical_bill:
        return MEDICAL_BILL_FIELDS
    if doc_type == DocType.rent_receipt:
        return RENT_RECEIPT_FIELDS
    if doc_type == DocType.form16:
        return FORM16_PART_A_FIELDS + FORM16_PART_B_FIELDS
    if doc_type == DocType.ais:
        return [
            "salary_entries", "interest_entries", "dividend_entries", "capital_gains_securities",
            "capital_gains_other", "tds_credits", "taxes_paid", "high_value_transactions",
            "unconfirmed_entries", "pan",
        ]
    if doc_type == DocType.form26as:
        return ["tds_credits", "total_tds_deposited", "pan"]
    return ["raw_preview"]


def _resolve_openrouter_key(settings: Any) -> str:
    # Primary: settings-loaded values.
    explicit = (getattr(settings, "openrouter_api_key", None) or "").strip()
    if explicit:
        return explicit

    openai_like = (getattr(settings, "openai_api_key", None) or "").strip()
    if openai_like.startswith("sk-or-"):
        return openai_like

    # Secondary: process environment variables.
    env_openrouter = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if env_openrouter:
        return env_openrouter
    env_openai = (os.getenv("OPENAI_API_KEY") or "").strip()
    if env_openai.startswith("sk-or-"):
        return env_openai

    # Last resort: read backend/.env directly, independent of process cwd.
    if dotenv_values is not None:
        try:
            env_path = Path(__file__).resolve().parents[2] / ".env"
            values = dotenv_values(str(env_path))
            file_openrouter = (values.get("OPENROUTER_API_KEY") or "").strip()
            if file_openrouter:
                return file_openrouter
            file_openai = (values.get("OPENAI_API_KEY") or "").strip()
            if file_openai.startswith("sk-or-"):
                return file_openai
        except Exception:
            pass
    return ""


def _llm_extract_structured(full_text: str, doc_type: DocType) -> dict[str, Any]:
    settings = get_settings()
    if not settings.ocr_enable_llm_refine or not full_text.strip():
        return {}

    provider = (settings.ocr_llm_provider or "auto").lower().strip()

    def _has_real_openai_key() -> bool:
        key = (settings.openai_api_key or "").strip()
        if not key:
            return False
        if key in {"sk-...", "your-openai-key", "your-openai-api-key"}:
            return False
        if "..." in key:
            return False
        return key.startswith("sk-") and len(key) > 20

    openrouter_key = _resolve_openrouter_key(settings)
    if provider == "auto":
        provider = (
            "openrouter" if openrouter_key
            else ("gemini" if settings.gemini_api_key else ("openai" if _has_real_openai_key() else "none"))
        )

    if provider == "gemini":
        return _llm_extract_structured_gemini(full_text, doc_type)
    if provider == "openrouter":
        return _llm_extract_structured_openrouter(full_text, doc_type)
    if provider != "openai" or not _has_real_openai_key():
        return {}

    try:
        from openai import OpenAI

        fields = ", ".join(_allowed_fields_for(doc_type))
        client = OpenAI(api_key=settings.openai_api_key, timeout=8.0)
        response = client.chat.completions.create(
            model=settings.ocr_llm_model or settings.llm_model,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=260,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract structured fields from OCR text of Indian financial documents. "
                        "Return JSON only. Do not invent values. Use only these fields: "
                        f"{fields}. Keep section codes uppercase. Numeric values must be plain numbers."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Document type: {doc_type.value}\n\nOCR text:\n{full_text[:6000]}",
                },
            ],
        )
        content = (response.choices[0].message.content or "{}").strip()
        data = json.loads(content)
        return normalize_structured(data if isinstance(data, dict) else {}, doc_type.value)
    except Exception:
        return {}


def _llm_extract_structured_openrouter(full_text: str, doc_type: DocType) -> dict[str, Any]:
    settings = get_settings()
    openrouter_key = _resolve_openrouter_key(settings)
    if not openrouter_key:
        return {}

    try:
        from openai import OpenAI

        fields = ", ".join(_allowed_fields_for(doc_type))
        client = OpenAI(
            api_key=openrouter_key,
            base_url=settings.openrouter_base_url,
            timeout=8.0,
        )

        model_candidates: list[str] = []
        for m in [settings.ocr_llm_model, settings.openrouter_model, settings.openrouter_fallback_model, settings.llm_model]:
            model = (m or "").strip()
            if model and model not in model_candidates:
                model_candidates.append(model)

        for model in model_candidates:
            for _ in range(2):
                try:
                    response = client.chat.completions.create(
                        model=model,
                        temperature=0,
                        max_tokens=260,
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "Extract structured fields from OCR text of Indian financial documents. "
                                    "Return JSON only. Do not invent values. Use only these fields: "
                                    f"{fields}. Keep section codes uppercase. Numeric values must be plain numbers."
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"Document type: {doc_type.value}\n\nOCR text:\n{full_text[:6000]}",
                            },
                        ],
                    )
                    raw = (response.choices[0].message.content or "{}").strip()
                    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", raw, re.I)
                    if fenced:
                        raw = fenced.group(1)
                    else:
                        brace = re.search(r"(\{[\s\S]*\})", raw)
                        if brace:
                            raw = brace.group(1)
                    data = json.loads(raw)
                    normalized = normalize_structured(data if isinstance(data, dict) else {}, doc_type.value)
                    if normalized:
                        return normalized
                except Exception:
                    continue
        return {}
    except Exception:
        return {}


def _llm_extract_structured_gemini(full_text: str, doc_type: DocType) -> dict[str, Any]:
    settings = get_settings()
    if not settings.gemini_api_key:
        return {}

    fields = ", ".join(_allowed_fields_for(doc_type))
    prompt = (
        "Extract structured fields from OCR text of Indian financial documents. "
        "Return strictly valid JSON object only. Do not invent values. "
        f"Use only these fields: {fields}. "
        "Keep section codes uppercase. Numeric values must be plain numbers.\n\n"
        f"Document type: {doc_type.value}\n\nOCR text:\n{full_text[:6000]}"
    )
    model = settings.gemini_ocr_model or "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.gemini_api_key}"
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 320},
    }

    try:
        with httpx.Client(timeout=8.0) as client:
            resp = client.post(url, json=body)
            if resp.status_code >= 400:
                return {}
            payload = resp.json()

        candidates = payload.get("candidates") or []
        if not candidates:
            return {}
        parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
        raw = "\n".join((p or {}).get("text", "") for p in parts).strip()
        if not raw:
            return {}

        cleaned = raw.strip()
        fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", cleaned, re.I)
        if fenced:
            cleaned = fenced.group(1)
        else:
            brace = re.search(r"(\{[\s\S]*\})", cleaned)
            if brace:
                cleaned = brace.group(1)

        data = json.loads(cleaned)
        return normalize_structured(data if isinstance(data, dict) else {}, doc_type.value)
    except Exception:
        return {}


def _merge_structured(base: dict[str, Any], refined: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in refined.items():
        if value in (None, "", 0, 0.0, [], {}):
            continue
        merged[key] = value
    return merged


def _merge_missing(base: dict[str, Any], supplement: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in supplement.items():
        if value in (None, "", 0, 0.0, [], {}):
            continue
        if merged.get(key) in (None, "", 0, 0.0, [], {}):
            merged[key] = value
    return merged


def _filled_field_count(data: dict[str, Any], keys: list[str]) -> int:
    return sum(1 for k in keys if data.get(k) not in (None, "", 0, 0.0, [], {}))


def _should_skip_llm_refine(full_text: str, doc_type: DocType, structured: dict[str, Any]) -> bool:
    text = (full_text or "").strip()
    if len(text) < 120:
        return False

    if doc_type == DocType.form16:
        core_hits = 0
        if structured.get("pan") or structured.get("employee_pan"):
            core_hits += 1
        if structured.get("assessment_year"):
            core_hits += 1
        if normalize_number(structured.get("gross_total_income") or structured.get("gross_salary") or structured.get("ctc_annual")) > 0:
            core_hits += 1
        if normalize_number(structured.get("taxable_income") or structured.get("net_taxable_salary")) > 0:
            core_hits += 1
        if normalize_number(structured.get("total_tax") or structured.get("total_tax_payable") or structured.get("tax_on_income")) > 0:
            core_hits += 1
        if normalize_number(structured.get("tds") or structured.get("tds_deducted") or structured.get("total_tds_deposited") or structured.get("income_tax_tds")) > 0:
            core_hits += 1
        if core_hits >= 4:
            return True
        return False

    if doc_type == DocType.payslip:
        core = ["basic_salary", "gross_salary", "net_salary", "ctc_annual"]
        if _filled_field_count(structured, core) >= 3:
            return True

    if doc_type == DocType.investment:
        core = ["section", "amount", "receipt_date"]
        if _filled_field_count(structured, core) >= 2:
            return True

    if doc_type == DocType.rent_receipt:
        core = ["landlord_name", "rent_amount", "pan_landlord"]
        if _filled_field_count(structured, core) >= 2:
            return True

    if doc_type in {DocType.ais, DocType.form26as}:
        core = ["tds_credits", "pan"]
        if _filled_field_count(structured, core) >= 1:
            return True
        return False

    signal_fields = sum(
        1 for k, v in (structured or {}).items()
        if k != "raw_preview" and v not in (None, "", 0, 0.0, [], {})
    )
    return signal_fields >= 6


def _apply_compatibility_aliases(data: dict[str, Any], doc_type: DocType, full_text: str) -> dict[str, Any]:
    out = dict(data)
    text_lower = (full_text or "").lower()

    if doc_type == DocType.investment:
        amount = normalize_number(out.get("amount"))
        section = str(out.get("section") or "").upper()
        policy = str(out.get("policy_or_fund_name") or "").lower()
        if amount > 0 and (section.startswith("80C") or any(x in text_lower or x in policy for x in ["ppf", "elss", "lic", "ulip"])):
            out.setdefault("amount_80c", amount)
            out.setdefault("total_80c", amount)
        if amount > 0 and (section.startswith("80CCD") or "nps" in text_lower or "nps" in policy):
            out.setdefault("nps_amount", amount)
            out.setdefault("nps", amount)
        if amount > 0 and (section == "80D" or any(x in text_lower or x in policy for x in ["health", "medical", "mediclaim", "insurance"])):
            out.setdefault("health_insurance", amount)
            out.setdefault("medical_premium", amount)

    if doc_type == DocType.rent_receipt:
        amount = normalize_number(out.get("rent_amount"))
        if amount > 0:
            if any(x in text_lower for x in ["annual", "yearly", "12 months"]):
                out.setdefault("annual_rent", amount)
                out.setdefault("rent_paid", amount)
            else:
                out.setdefault("monthly_rent", amount)

    if doc_type == DocType.medical_bill:
        amount = normalize_number(out.get("amount"))
        if amount > 0:
            out.setdefault("total", amount)
            if any(x in text_lower for x in ["insurance", "premium", "mediclaim"]):
                out.setdefault("health_insurance", amount)
                out.setdefault("medical_premium", amount)

    return out


def _extract_average_confidence(annotation: Any, text: str) -> float:
    confidences: list[float] = []
    for page in getattr(annotation, "pages", []) or []:
        for block in getattr(page, "blocks", []) or []:
            conf = getattr(block, "confidence", None)
            if conf is not None:
                confidences.append(float(conf))
    if confidences:
        return sum(confidences) / len(confidences)
    if len(text) > 350:
        return 0.9
    if len(text) > 120:
        return 0.78
    if len(text) > 40:
        return 0.58
    return 0.0


def _preprocess_image_variants(content: bytes) -> list[bytes]:
    settings = get_settings()
    if not settings.ocr_preprocess_scans or Image is None or ImageOps is None or ImageEnhance is None or ImageFilter is None:
        return [content]
    try:
        image = Image.open(io.BytesIO(content))
        image = ImageOps.exif_transpose(image).convert("L")
        if max(image.size) < 1400:
            scale = 1400 / max(image.size)
            image = image.resize((int(image.width * scale), int(image.height * scale)))

        base = ImageOps.autocontrast(image)
        enhanced = ImageEnhance.Contrast(base).enhance(1.4)
        denoised = enhanced.filter(ImageFilter.MedianFilter(size=3))
        sharpened = denoised.filter(ImageFilter.SHARPEN)
        thresholded_soft = sharpened.point(lambda p: 255 if p > 155 else 0)
        thresholded_hard = sharpened.point(lambda p: 255 if p > 175 else 0)

        variants = [content]
        for candidate in (enhanced, denoised, sharpened, thresholded_soft, thresholded_hard):
            buf = io.BytesIO()
            candidate.save(buf, format="PNG")
            variants.append(buf.getvalue())
        return variants
    except Exception:
        return [content]


def _ocr_with_google_vision(content: bytes) -> tuple[str, float]:
    try:
        from google.cloud import vision

        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=content)
        response = client.document_text_detection(image=image)
        if response.error.message:
            return "", 0.0
        annotation = response.full_text_annotation
        text = (annotation.text if annotation else "") or ""
        return text, _extract_average_confidence(annotation, text)
    except Exception:
        return "", 0.0


def _ocr_with_gemini(content: bytes, mime_type: str) -> tuple[str, float]:
    settings = get_settings()
    if not settings.gemini_api_key:
        return "", 0.0

    model = settings.gemini_ocr_model or "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.gemini_api_key}"
    prompt = (
        "Perform OCR on this document and return only the transcribed text. "
        "Preserve important line breaks and numbers. Do not add commentary."
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(content).decode("utf-8"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1800},
    }

    try:
        with httpx.Client(timeout=18.0) as client:
            resp = client.post(url, json=body)
            if resp.status_code >= 400:
                return "", 0.0
            payload = resp.json()

        candidates = payload.get("candidates") or []
        if not candidates:
            return "", 0.0
        parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
        text = "\n".join((p or {}).get("text", "") for p in parts).strip()
        if not text:
            return "", 0.0
        confidence = 0.88 if len(text) > 350 else (0.76 if len(text) > 120 else 0.58)
        return text, confidence
    except Exception:
        return "", 0.0


def _ocr_with_openrouter(content: bytes, mime_type: str) -> tuple[str, float]:
    settings = get_settings()
    openrouter_key = _resolve_openrouter_key(settings)
    if not openrouter_key:
        return "", 0.0

    if not (mime_type or "").startswith("image/"):
        return "", 0.0

    timeout_sec = float(getattr(settings, "ocr_openrouter_timeout_sec", 12.0) or 12.0)
    max_retries = max(1, int(getattr(settings, "ocr_openrouter_retries", 1) or 1))
    max_models = max(1, int(getattr(settings, "ocr_openrouter_max_models", 1) or 1))

    try:
        from openai import OpenAI

        client = OpenAI(api_key=openrouter_key, base_url=settings.openrouter_base_url, timeout=timeout_sec)
        data_uri = f"data:{mime_type};base64,{base64.b64encode(content).decode('utf-8')}"
        prompt = (
            "Perform OCR on this tax document image and return only transcribed text. "
            "Preserve line breaks, numbers, TAN, PAN, section codes, and table rows. "
            "Do not summarize."
        )

        model_candidates: list[str] = []
        for m in [settings.openrouter_model, settings.openrouter_fallback_model, "google/gemini-2.0-flash-001"]:
            model = (m or "").strip()
            if model and model not in model_candidates:
                model_candidates.append(model)

        for model in model_candidates[:max_models]:
            for _ in range(max_retries):
                try:
                    response = client.chat.completions.create(
                        model=model,
                        temperature=0,
                        max_tokens=2200,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": data_uri}},
                                ],
                            }
                        ],
                    )
                    text = (response.choices[0].message.content or "").strip()
                    if not text:
                        continue
                    confidence = 0.87 if len(text) > 350 else (0.74 if len(text) > 120 else 0.56)
                    return text, confidence
                except Exception:
                    continue
        return "", 0.0
    except Exception:
        return "", 0.0


def _text_layer_is_reliable(text_layer: str) -> bool:
    """Heuristic guard: use embedded PDF text only if it is reasonably clean."""
    if len(text_layer or "") < 40:
        return False
    score = _ocr_text_signal(text_layer)
    bad_char_ratio = sum(1 for ch in (text_layer or "") if ch in {"\ufffd", "?"}) / max(1, len(text_layer or ""))
    return score >= 14 and bad_char_ratio < 0.12


def _ocr_text_signal(text: str) -> float:
    t = text or ""
    lines = _clean_lines(t)
    line_count = len(lines)
    digit_chars = sum(ch.isdigit() for ch in t)
    alpha_chars = sum(ch.isalpha() for ch in t)
    doc_signals = sum(1 for kw in ["pan", "tds", "assessment year", "gross", "net", "section", "form 16"] if kw in t.lower())
    ratio = (digit_chars / max(1, alpha_chars + digit_chars))
    return min(line_count, 160) * 0.35 + min(digit_chars, 800) * 0.03 + min(doc_signals, 8) * 2.5 + (ratio * 10)


def _financial_amount_signal(text: str) -> int:
    # Count meaningful monetary values to avoid accepting OCR output that has headings but misses key numbers.
    vals = _extract_numbers(text or "")
    return sum(1 for v in vals if v >= 100)


def _ocr_score(text: str, confidence: float) -> float:
    return (confidence * 100.0) + min(len(text or ""), 3000) / 60.0 + _ocr_text_signal(text)


def _limited_image_variants(content: bytes) -> list[bytes]:
    settings = get_settings()
    max_variants = max(1, int(getattr(settings, "ocr_max_image_variants", 2) or 2))
    variants = _preprocess_image_variants(content)
    return variants[:max_variants] if variants else [content]


def _detect_doc_type(text: str) -> DocType:
    return classify_document_text(text).doc_type


def _run_provider_ocr(content: bytes, mime_type: str = "application/pdf") -> tuple[str, float]:
    settings = get_settings()
    provider = (settings.ocr_provider or "auto").lower().strip()
    has_vision = bool(settings.google_application_credentials and settings.google_cloud_project)
    has_gemini = bool(settings.gemini_api_key)
    has_openrouter = bool(_resolve_openrouter_key(settings))

    if provider == "auto":
        provider = "gemini" if has_gemini else ("vision" if has_vision else ("openrouter" if has_openrouter else "none"))

    if provider not in {"vision", "gemini", "openrouter"}:
        return "", 0.0

    candidates: list[tuple[str, float]] = []
    fast_accept_score = float(getattr(settings, "ocr_fast_accept_score", 108.0) or 108.0)

    def _is_fast_accept(text: str, conf: float) -> bool:
        return bool((text or "").strip()) and _ocr_score(text, conf) >= fast_accept_score

    if provider == "openrouter":
        if has_openrouter:
            if mime_type == "application/pdf" and has_gemini:
                max_pdf_pages = max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3))
                page_images = _extract_pdf_images(content, max_pages=max_pdf_pages)
                gemini_texts: list[str] = []
                gemini_confs: list[float] = []
                if page_images:
                    for page_img in page_images:
                        text, conf = _ocr_with_gemini(page_img, "image/png")
                        if text.strip():
                            gemini_texts.append(text.strip())
                            gemini_confs.append(conf)
                    if gemini_texts:
                        gemini_text = "\n\n".join(gemini_texts)
                        gemini_conf = (sum(gemini_confs) / len(gemini_confs)) if gemini_confs else 0.0
                    else:
                        gemini_text, gemini_conf = _ocr_with_gemini(content, mime_type)
                else:
                    gemini_text, gemini_conf = _ocr_with_gemini(content, mime_type)

                if _is_fast_accept(gemini_text, gemini_conf):
                    return gemini_text, gemini_conf
                if gemini_text.strip():
                    candidates.append((gemini_text, gemini_conf))
            if mime_type == "application/pdf":
                max_pdf_pages = max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3))
                target_chars = max(600, int(getattr(settings, "ocr_target_chars", 1800) or 1800))
                page_images = _extract_pdf_images(content, max_pages=max_pdf_pages)
                if page_images:
                    texts: list[str] = []
                    confs: list[float] = []
                    total_chars = 0
                    min_pages_before_early_stop = min(len(page_images), 4)
                    for page_img in page_images:
                        for candidate in _limited_image_variants(page_img):
                            text, conf = _ocr_with_openrouter(candidate, "image/png")
                            if text.strip():
                                texts.append(text.strip())
                                confs.append(conf)
                                total_chars += len(text)
                                break
                        merged_so_far = "\n\n".join(texts)
                        if (
                            len(texts) >= min_pages_before_early_stop
                            and total_chars >= target_chars
                            and _financial_amount_signal(merged_so_far) >= 10
                        ):
                            break
                    if texts:
                        merged = "\n\n".join(texts)
                        avg_conf = (sum(confs) / len(confs)) if confs else 0.0
                        if _is_fast_accept(merged, avg_conf):
                            return merged, avg_conf
                        candidates.append((merged, avg_conf))
            else:
                for candidate in _limited_image_variants(content):
                    text, conf = _ocr_with_openrouter(candidate, "image/png")
                    if _is_fast_accept(text, conf):
                        return text, conf
                    candidates.append((text, conf))
        if has_vision:
            if mime_type == "application/pdf":
                max_pdf_pages = max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3))
                page_images = _extract_pdf_images(content, max_pages=max_pdf_pages)
                if page_images:
                    for page_img in page_images:
                        candidates.append(_ocr_with_google_vision(page_img))
                else:
                    candidates.append(_ocr_with_google_vision(content))
            else:
                for candidate in _limited_image_variants(content):
                    candidates.append(_ocr_with_google_vision(candidate))
        if has_gemini and mime_type != "application/pdf":
            candidates.append(_ocr_with_gemini(content, mime_type))
    elif provider == "gemini":
        if has_gemini:
            if mime_type == "application/pdf":
                max_pdf_pages = max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3))
                page_images = _extract_pdf_images(content, max_pages=max_pdf_pages)
                texts: list[str] = []
                confs: list[float] = []
                if page_images:
                    for page_img in page_images:
                        text, conf = _ocr_with_gemini(page_img, "image/png")
                        if text.strip():
                            texts.append(text.strip())
                            confs.append(conf)
                    if texts:
                        merged = "\n\n".join(texts)
                        avg_conf = (sum(confs) / len(confs)) if confs else 0.0
                        if _is_fast_accept(merged, avg_conf):
                            return merged, avg_conf
                        candidates.append((merged, avg_conf))
                    else:
                        text, conf = _ocr_with_gemini(content, mime_type)
                        if _is_fast_accept(text, conf):
                            return text, conf
                        candidates.append((text, conf))
                else:
                    text, conf = _ocr_with_gemini(content, mime_type)
                    if _is_fast_accept(text, conf):
                        return text, conf
                    candidates.append((text, conf))
            else:
                text, conf = _ocr_with_gemini(content, mime_type)
                if _is_fast_accept(text, conf):
                    return text, conf
                candidates.append((text, conf))
        if has_openrouter:
            if mime_type == "application/pdf":
                max_pdf_pages = max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3))
                page_images = _extract_pdf_images(content, max_pages=max_pdf_pages)
                if page_images:
                    for candidate in page_images:
                        candidates.append(_ocr_with_openrouter(candidate, "image/png"))
            else:
                for candidate in _limited_image_variants(content):
                    candidates.append(_ocr_with_openrouter(candidate, "image/png"))
        if has_vision:
            if mime_type == "application/pdf":
                max_pdf_pages = max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3))
                page_images = _extract_pdf_images(content, max_pages=max_pdf_pages)
                if page_images:
                    for candidate in page_images:
                        candidates.append(_ocr_with_google_vision(candidate))
                else:
                    candidates.append(_ocr_with_google_vision(content))
            else:
                for candidate in _limited_image_variants(content):
                    candidates.append(_ocr_with_google_vision(candidate))
    else:
        if has_vision:
            if mime_type == "application/pdf":
                max_pdf_pages = max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3))
                page_images = _extract_pdf_images(content, max_pages=max_pdf_pages)
                if page_images:
                    for candidate in page_images:
                        candidates.append(_ocr_with_google_vision(candidate))
                else:
                    text, conf = _ocr_with_google_vision(content)
                    if _is_fast_accept(text, conf):
                        return text, conf
                    candidates.append((text, conf))
            else:
                for candidate in _limited_image_variants(content):
                    candidates.append(_ocr_with_google_vision(candidate))
        if has_openrouter and mime_type != "application/pdf":
            for candidate in _limited_image_variants(content):
                candidates.append(_ocr_with_openrouter(candidate, "image/png"))
        if has_gemini:
            if mime_type == "application/pdf":
                max_pdf_pages = max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3))
                page_images = _extract_pdf_images(content, max_pages=max_pdf_pages)
                if page_images:
                    for page_img in page_images:
                        candidates.append(_ocr_with_gemini(page_img, "image/png"))
                else:
                    candidates.append(_ocr_with_gemini(content, mime_type))
            else:
                candidates.append(_ocr_with_gemini(content, mime_type))

    best_text = ""
    best_conf = 0.0
    for text, conf in candidates:
        if _ocr_score(text, conf) > _ocr_score(best_text, best_conf):
            best_text, best_conf = text, conf

    # Final offline fallback: local OCR on rendered/scanned PDF pages or images.
    if not (best_text or "").strip():
        if mime_type == "application/pdf":
            page_images = _extract_pdf_images(content, max_pages=max(1, int(getattr(settings, "ocr_max_pdf_ocr_pages", 3) or 3)))
            local_texts: list[str] = []
            local_confs: list[float] = []
            for page_img in page_images:
                text, conf = _ocr_with_rapidocr_image(page_img)
                if text.strip():
                    local_texts.append(text.strip())
                    local_confs.append(conf)
            if local_texts:
                best_text = "\n\n".join(local_texts)
                best_conf = sum(local_confs) / len(local_confs) if local_confs else 0.58
        else:
            best_text, best_conf = _ocr_with_rapidocr_image(content)

    return best_text, best_conf


def run_ocr_bytes_detailed(content: bytes, mime_type: str = "application/pdf") -> dict[str, Any]:
    """Run OCR and return text + confidence + PDF type metadata."""
    out: dict[str, Any] = {
        "text": "",
        "confidence": 0.0,
        "pdf_type": "unknown",
        "unreadable_pages": [],
    }

    if mime_type == "application/pdf":
        settings = get_settings()
        max_text_pages = max(1, int(getattr(settings, "ocr_max_pdf_text_pages", 8) or 8))
        text_layer, pdf_type, unreadable_pages = _extract_pdf_text_layer(content, max_pages=max_text_pages)
        out["pdf_type"] = pdf_type
        out["unreadable_pages"] = unreadable_pages

        if pdf_type == "text-based" and _text_layer_is_reliable(text_layer):
            out["text"] = text_layer
            out["confidence"] = 0.96
            return out

        ocr_text, ocr_conf = _run_provider_ocr(content, mime_type)
        if pdf_type == "hybrid" and text_layer:
            merged = (text_layer + "\n\n" + ocr_text).strip()
            out["text"] = merged
            out["confidence"] = max(ocr_conf, 0.84)
            return out

        # Last-resort fallback: if provider OCR fails but a minimal text layer exists,
        # return it to avoid completely empty extraction for partially-readable PDFs.
        if not ocr_text.strip() and text_layer.strip():
            out["text"] = text_layer.strip()
            out["confidence"] = 0.35
            return out

        out["text"] = ocr_text
        out["confidence"] = ocr_conf
        return out

    text, confidence = _run_provider_ocr(content, mime_type)
    out["text"] = text
    out["confidence"] = confidence
    return out


def run_ocr_bytes(content: bytes, mime_type: str = "application/pdf") -> tuple[str, float]:
    detailed = run_ocr_bytes_detailed(content, mime_type)
    return str(detailed.get("text") or ""), float(detailed.get("confidence") or 0.0)


def run_ocr_file(path: str) -> tuple[str, float]:
    with open(path, "rb") as f:
        return run_ocr_bytes(f.read())


def normalize_ocr_to_structured(full_text: str, doc_type: DocType | None = None) -> dict[str, Any]:
    if not doc_type:
        doc_type = _detect_doc_type(full_text)

    if doc_type == DocType.payslip:
        structured = _extract_payslip_from_text(full_text)
    elif doc_type == DocType.form16:
        structured = _extract_form16_from_text(full_text)
    elif doc_type == DocType.ais:
        structured = _extract_ais_from_text(full_text)
    elif doc_type == DocType.form26as:
        structured = _extract_form26as_from_text(full_text)
    elif doc_type == DocType.investment:
        structured = _extract_investment_from_text(full_text)
    elif doc_type == DocType.medical_bill:
        structured = _extract_medical_from_text(full_text)
    elif doc_type == DocType.rent_receipt:
        structured = _extract_rent_from_text(full_text)
    else:
        if _is_income_tax_statement(full_text):
            structured = _extract_generic_tax_statement_fields(full_text)
            structured = _merge_missing(structured, _extract_payslip_from_text(full_text))
        else:
            structured = {"raw_preview": full_text[:500] if full_text else ""}

    refined = {} if _should_skip_llm_refine(full_text, doc_type, structured) else _llm_extract_structured(full_text, doc_type)
    merged = _merge_structured(structured, refined)
    merged = _flatten_nested_ocr_fields(merged)
    merged = _merge_missing(merged, _extract_generic_tax_statement_fields(full_text))
    # Universal extractor ensures we always have a flat schema dictionary even for noisy OCR.
    merged = _merge_missing(merged, universal_extract_to_dict(full_text, doc_type))
    merged = _map_tax_statement_to_calc_fields(merged)
    merged = _canonicalize_structured_output(merged, doc_type)
    merged = _apply_compatibility_aliases(merged, doc_type, full_text)
    return merged if merged else {"raw_preview": full_text[:500] if full_text else ""}


def assess_ocr_quality(
    full_text: str,
    confidence: float,
    structured: dict[str, Any],
    doc_type: DocType,
) -> dict[str, Any]:
    text = (full_text or "").strip()
    text_len = len(text)

    expected_map = {
        DocType.payslip: ["basic_salary", "hra", "gross_salary", "net_salary"],
        DocType.form16: FORM16_EXPECTED_FIELDS,
        DocType.ais: ["salary_entries", "tds_credits"],
        DocType.form26as: ["tds_credits", "total_tds_deposited"],
        DocType.investment: ["section", "amount"],
        DocType.medical_bill: ["amount", "date"],
        DocType.rent_receipt: ["rent_amount", "month"],
        DocType.other: ["raw_preview"],
    }
    expected_fields = expected_map.get(doc_type, ["raw_preview"])
    if _is_income_tax_statement(text, structured) and doc_type in (DocType.other, DocType.payslip):
        expected_fields = FORM16_EXPECTED_FIELDS
    extracted_fields = sum(1 for k in expected_fields if structured.get(k) not in (None, "", 0, 0.0, [], {}))
    expected_count = max(1, len(expected_fields))
    structured_density = extracted_fields / expected_count
    extracted_signal_fields = sum(
        1 for k, v in (structured or {}).items()
        if k != "raw_preview" and v not in (None, "", 0, 0.0, [], {})
    )

    issues: list[str] = []

    if confidence >= 0.72 and (text_len >= 60 or structured_density >= 0.5):
        ocr_clarity = "clear"
    elif confidence >= 0.4 and (text_len >= 25 or extracted_fields >= 1):
        ocr_clarity = "readable"
        issues.append("Document is readable but clarity is moderate. A clearer scan can improve accuracy.")
    elif doc_type == DocType.other and extracted_signal_fields >= 2 and text_len >= 40:
        ocr_clarity = "readable"
        issues.append("Document text is partially noisy, but useful statement fields were extracted.")
    elif text_len >= 140 and extracted_fields >= 1:
        ocr_clarity = "readable"
        issues.append("OCR confidence is moderate, but key fields were detected. Please verify extracted values.")
    else:
        ocr_clarity = "unclear"
        issues.append("Document appears unclear or text is too faint/short for reliable OCR.")

    if _is_income_tax_statement(text, structured) and doc_type in (DocType.other, DocType.payslip):
        if extracted_fields >= 4 or extracted_signal_fields >= 6:
            ocr_accuracy = "high"
        elif extracted_fields >= 2 or extracted_signal_fields >= 3:
            ocr_accuracy = "medium"
            issues.append("Only partial fields were extracted. Please verify values before applying.")
        else:
            ocr_accuracy = "low"
            issues.append("Could not extract required fields from this document.")
    elif extracted_fields >= max(1, len(expected_fields) - 1):
        ocr_accuracy = "high"
    elif extracted_fields >= 1 or structured_density >= 0.4:
        ocr_accuracy = "medium"
        issues.append("Only partial fields were extracted. Please verify values before applying.")
    else:
        ocr_accuracy = "low"
        issues.append("Could not extract required fields from this document.")

    if not text:
        issues.append("No OCR text detected. Try better lighting, higher resolution, or a non-blurry scan.")

    ocr_status = "verified" if ocr_clarity == "clear" and ocr_accuracy in ("high", "medium") else "needs_review"

    return {
        "ocr_status": ocr_status,
        "ocr_clarity": ocr_clarity,
        "ocr_accuracy": ocr_accuracy,
        "ocr_issues": issues,
        "extracted_fields": extracted_fields,
        "expected_fields": expected_count,
    }
