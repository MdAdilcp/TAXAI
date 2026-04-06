"""Normalized OCR output schema — same structure regardless of provider (Vision/Textract/Form Recognizer)."""
from typing import Any

# Field names we expect from OCR after normalization (for payslips, investments, bills, rent)
PAYSLIP_FIELDS = [
    "employee_name",
    "employer_name",
    "month",
    "year",
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
]

INVESTMENT_FIELDS = [
    "provider_name",
    "policy_or_fund_name",
    "section",  # 80C, 80D, etc.
    "amount",
    "financial_year",
    "receipt_date",
]

MEDICAL_BILL_FIELDS = [
    "hospital_or_provider",
    "patient_name",
    "amount",
    "date",
    "description",
]

RENT_RECEIPT_FIELDS = [
    "landlord_name",
    "tenant_name",
    "address",
    "month",
    "year",
    "rent_amount",
    "pan_landlord",
]

# Regex/keyword hints for auto-classifying doc type from raw text
DOC_TYPE_HINTS = {
    "payslip": [
        "payslip", "salary", "basic", "hra", "gross", "net salary", "employee", "ctc",
        "form 16", "part b", "annual tax statement", "income tax statement", "tax deducted", "tds",
    ],
    "investment": ["80c", "80d", "lic", "ppf", "elss", "nps", "ulip", "premium", "investment"],
    "medical_bill": ["hospital", "medical", "doctor", "medicine", "bill", "patient", "80d"],
    "rent_receipt": ["rent", "landlord", "tenant", "house rent", "hra"],
    "form16": ["form 16", "part a", "part b", "employer tan", "salary u/s 17", "tds"],
    "ais": ["annual information statement", "ais", "income tax department", "information category"],
    "form26as": ["form 26as", "tax credit statement", "deductor", "amount paid/credited", "tds deposited"],
}


def normalize_number(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace(" ", "")
    # Remove currency symbols
    for c in ["₹", "Rs", "INR", "$"]:
        s = s.replace(c, "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def normalize_structured(data: dict[str, Any], doc_type: str) -> dict[str, Any]:
    """Ensure numeric fields are numbers and keys match our schema."""
    out = {}
    for k, v in data.items():
        key = k.lower().replace(" ", "_").replace("-", "_")
        if isinstance(v, str) and key in (
            "basic_salary", "hra", "gross_salary", "net_salary", "amount", "rent_amount",
            "professional_tax", "ctc_annual", "special_allowance", "other_allowances",
        ):
            out[key] = normalize_number(v)
        else:
            out[key] = v
    return out
