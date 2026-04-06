"""Universal field extractor that returns schema-friendly dictionaries."""

import re
from typing import Any

from app.models.schemas import DocType
from app.services.ocr_schema import (
    INVESTMENT_FIELDS,
    MEDICAL_BILL_FIELDS,
    PAYSLIP_FIELDS,
    RENT_RECEIPT_FIELDS,
    normalize_number,
    normalize_structured,
)

_DOC_FIELDS: dict[DocType, list[str]] = {
    DocType.payslip: PAYSLIP_FIELDS,
    DocType.investment: INVESTMENT_FIELDS,
    DocType.medical_bill: MEDICAL_BILL_FIELDS,
    DocType.rent_receipt: RENT_RECEIPT_FIELDS,
    DocType.form16: [
        "employee_name",
        "employee_pan",
        "assessment_year",
        "gross_salary",
        "taxable_income",
        "total_tax_payable",
        "tds_deducted",
    ],
    DocType.ais: ["pan", "assessment_year", "total_tds_deposited"],
    DocType.form26as: ["pan", "assessment_year", "total_tds_deposited"],
}

_FIELD_ALIASES: dict[str, list[str]] = {
    "employee_name": ["employee name", "name of employee"],
    "employer_name": ["employer", "company name"],
    "month": ["month", "pay period"],
    "year": ["year", "fy", "assessment year"],
    "basic_salary": ["basic salary", "basic pay", "basic"],
    "hra": ["hra", "house rent allowance"],
    "special_allowance": ["special allowance"],
    "other_allowances": ["other allowance", "allowances"],
    "gross_salary": ["gross salary", "gross earnings", "gross total income"],
    "professional_tax": ["professional tax"],
    "income_tax_tds": ["income tax", "tds", "tax deducted"],
    "other_deductions": ["other deductions", "deductions"],
    "net_salary": ["net salary", "net pay"],
    "ctc_annual": ["ctc", "annual ctc"],
    "provider_name": ["provider", "insurer", "institution"],
    "policy_or_fund_name": ["policy name", "fund name", "plan"],
    "section": ["section", "u/s", "under section"],
    "amount": ["amount", "premium", "deposit", "investment amount"],
    "financial_year": ["financial year", "fy"],
    "receipt_date": ["receipt date", "payment date", "date"],
    "hospital_or_provider": ["hospital", "provider", "clinic"],
    "patient_name": ["patient name", "insured name"],
    "date": ["date", "invoice date"],
    "description": ["description", "treatment", "service"],
    "landlord_name": ["landlord name", "owner name"],
    "tenant_name": ["tenant name", "received from"],
    "address": ["address", "property address"],
    "rent_amount": ["rent amount", "monthly rent", "rent paid"],
    "pan_landlord": ["landlord pan", "owner pan", "pan"],
    "employee_pan": ["employee pan", "pan of employee"],
    "assessment_year": ["assessment year", "ay"],
    "taxable_income": ["taxable income", "net taxable salary"],
    "total_tax_payable": ["total tax payable", "total tax liability"],
    "tds_deducted": ["tds deducted", "tax deducted at source", "tds"],
    "pan": ["pan"],
    "total_tds_deposited": ["total tds deposited", "amount deducted"],
}

_NUMERIC_FIELDS = {
    "basic_salary",
    "hra",
    "special_allowance",
    "other_allowances",
    "gross_salary",
    "professional_tax",
    "income_tax_tds",
    "other_deductions",
    "net_salary",
    "ctc_annual",
    "amount",
    "rent_amount",
    "taxable_income",
    "total_tax_payable",
    "tds_deducted",
    "total_tds_deposited",
}

_KEY_VALUE_LINE_RE = re.compile(r"^\s*[^:]{2,80}\s*[:\-–—]\s*.+$")
_MONEY_RE = re.compile(r"(?:rs\.?|inr|₹)?\s*([-+]?\d[\d,]*(?:\.\d{1,2})?)", re.I)


def _compile_alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(rf"\b{escaped}\b", re.I)


_FIELD_ALIAS_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    field: [_compile_alias_pattern(a) for a in aliases]
    for field, aliases in _FIELD_ALIASES.items()
}


def _clean_lines(text: str) -> list[str]:
    lines = []
    for raw in (text or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip(" :-\t")
        if line:
            lines.append(line)
    return lines


def _extract_inline_tail(line: str, alias_match: re.Match[str]) -> str | None:
    tail = line[alias_match.end() :].strip(" :-\t")
    return tail or None


def _extract_labeled_text(lines: list[str], alias_patterns: list[re.Pattern[str]]) -> str | None:
    for idx, line in enumerate(lines):
        for alias_pattern in alias_patterns:
            match = alias_pattern.search(line)
            if not match:
                continue

            inline = _extract_inline_tail(line, match)
            if inline:
                return inline

            if idx + 1 < len(lines):
                next_line = lines[idx + 1].strip()
                if next_line and len(next_line) <= 120 and not _KEY_VALUE_LINE_RE.match(next_line):
                    return next_line
    return None


def _extract_labeled_number(lines: list[str], alias_patterns: list[re.Pattern[str]]) -> float | None:
    for idx, line in enumerate(lines):
        for alias_pattern in alias_patterns:
            match = alias_pattern.search(line)
            if not match:
                continue

            # Prefer numbers that appear after the matched alias.
            tail = line[match.end() :]
            number_match = _MONEY_RE.search(tail)
            if number_match:
                return normalize_number(number_match.group(1))

            # Some OCRs place the value in the next line.
            if idx + 1 < len(lines):
                next_number = _MONEY_RE.search(lines[idx + 1])
                if next_number:
                    return normalize_number(next_number.group(1))

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


def _extract_assessment_year(text: str) -> str | None:
    match = re.search(r"\b(20\d{2}\s*[-/]\s*\d{2,4})\b", text or "")
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1)).replace("/", "-")


def _normalize_assessment_year(value: Any) -> str | None:
    match = re.search(r"\b(20\d{2}\s*[-/]\s*\d{2,4})\b", str(value or ""))
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1)).replace("/", "-")


def _extract_month_year(text: str) -> tuple[str | None, int | None]:
    month_match = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December)\b",
        text or "",
        re.I,
    )
    year_match = re.search(r"\b(20\d{2})\b", text or "")
    month = month_match.group(1).title() if month_match else None
    year = int(year_match.group(1)) if year_match else None
    return month, year


def universal_extract_to_dict(text: str, doc_type: DocType) -> dict[str, Any]:
    """Extract fields into a normalized dictionary for schema-based mapping."""
    lines = _clean_lines(text)
    schema_fields = _DOC_FIELDS.get(doc_type, [])

    extracted: dict[str, Any] = {}
    for field in schema_fields:
        alias_patterns = _FIELD_ALIAS_PATTERNS.get(field)
        if not alias_patterns:
            alias_patterns = [_compile_alias_pattern(field.replace("_", " "))]

        if field in _NUMERIC_FIELDS:
            number = _extract_labeled_number(lines, alias_patterns)
            if number is None:
                continue
            extracted[field] = number
            continue

        value = _extract_labeled_text(lines, alias_patterns)
        if value:
            extracted[field] = value

    # Generic enrichments that help schema mapping even when labels are noisy.
    if "pan" in schema_fields and not extracted.get("pan"):
        pan = _extract_pan(text)
        if pan:
            extracted["pan"] = pan
    if "employee_pan" in schema_fields and not extracted.get("employee_pan"):
        pan = _extract_pan(text)
        if pan:
            extracted["employee_pan"] = pan
    if "pan_landlord" in schema_fields and not extracted.get("pan_landlord"):
        pan = _extract_pan(text)
        if pan:
            extracted["pan_landlord"] = pan

    if "assessment_year" in schema_fields and not extracted.get("assessment_year"):
        ay = _extract_assessment_year(text)
        if ay:
            extracted["assessment_year"] = ay
    elif "assessment_year" in schema_fields and extracted.get("assessment_year"):
        normalized_ay = _normalize_assessment_year(extracted.get("assessment_year"))
        if normalized_ay:
            extracted["assessment_year"] = normalized_ay

    if doc_type in {DocType.payslip, DocType.rent_receipt}:
        month, year = _extract_month_year(text)
        if month and "month" in schema_fields and not extracted.get("month"):
            extracted["month"] = month
        if year and "year" in schema_fields and not extracted.get("year"):
            extracted["year"] = year

    if "rent_amount" in schema_fields and not extracted.get("rent_amount"):
        rent_match = re.search(r"\b(?:monthly\s+rent|rent\s+amount|rent\s+paid|rent)\b[^\d]{0,20}" + _MONEY_RE.pattern, text or "", re.I)
        if rent_match:
            extracted["rent_amount"] = normalize_number(rent_match.group(1))

    return normalize_structured(extracted, doc_type.value)
