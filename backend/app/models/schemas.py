"""API request/response schemas."""
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DocType(str, Enum):
    payslip = "payslip"
    investment = "investment"
    medical_bill = "medical_bill"
    rent_receipt = "rent_receipt"
    form16 = "form16"
    ais = "ais"
    form26as = "form26as"
    other = "other"


# --- Upload / OCR ---
class UploadDocResponse(BaseModel):
    doc_id: str
    doc_type: DocType
    structured_data: dict[str, Any]
    tax_calculator_json: dict[str, Any] | None = None
    raw_text_preview: str | None = None
    confidence: float = 0.0
    classification_confidence: float = 0.0
    ocr_status: str = "needs_review"  # verified | needs_review
    ocr_clarity: str = "unclear"  # clear | readable | unclear
    ocr_accuracy: str = "low"  # high | medium | low
    ocr_issues: list[str] = Field(default_factory=list)
    extracted_fields: int = 0
    expected_fields: int = 0


# --- Salary ---
class ParseSalaryRequest(BaseModel):
    doc_id: str | None = None
    raw_text: str | None = None
    structured_data: dict[str, Any] | None = None


class SalaryBreakup(BaseModel):
    ctc: Decimal = Decimal("0")
    basic: Decimal = Decimal("0")
    hra: Decimal = Decimal("0")
    special_allowance: Decimal = Decimal("0")
    other_allowances: Decimal = Decimal("0")
    professional_tax: Decimal = Decimal("0")
    pt_monthly: Decimal = Decimal("0")
    gross_salary: Decimal = Decimal("0")
    deductions_total: Decimal = Decimal("0")
    net_salary: Decimal = Decimal("0")
    currency: str = "INR"
    month: str | None = None
    year: int | None = None


class ParseSalaryResponse(BaseModel):
    breakup: SalaryBreakup
    source: str = "ocr"
    confidence: float = 0.0


# --- Deductions ---
class DeductionItem(BaseModel):
    code: str  # e.g. 80C, 80D, HRA
    name: str
    amount_claimed: Decimal = Decimal("0")
    max_allowed: Decimal | None = None
    confidence: float = 0.0
    legal_citation: str | None = None
    requires_human_review: bool = False
    tax_savings_impact: Decimal | None = None


class RecommendDeductionsRequest(BaseModel):
    user_profile: dict[str, Any] = Field(default_factory=dict)  # age, income, employment, etc.
    parsed_docs: list[dict[str, Any]] = Field(default_factory=list)
    salary_breakup: SalaryBreakup | None = None


class RecommendDeductionsResponse(BaseModel):
    deductions: list[DeductionItem]
    regime_suggestion: str | None = None  # old | new


# --- Tax calculation ---
class TaxRow(BaseModel):
    regime: str  # old | new
    taxable_income: Decimal
    tax_before_rebate: Decimal
    rebate_87a: Decimal = Decimal("0")
    tax_after_rebate: Decimal
    cess: Decimal = Decimal("0")
    total_tax: Decimal
    effective_rate_pct: float = 0.0


class SuggestedInvestment(BaseModel):
    section: str
    description: str
    suggested_amount: Decimal
    max_deduction: Decimal
    current_claim: Decimal = Decimal("0")


class CalculateTaxRequest(BaseModel):
    salary_breakup: SalaryBreakup | None = None
    other_income: Decimal = Decimal("0")
    deductions: list[DeductionItem] = Field(default_factory=list)
    regime: str | None = None  # optional override


class CalculateTaxResponse(BaseModel):
    tax_table: list[TaxRow]
    suggested_investments: list[SuggestedInvestment] = Field(default_factory=list)
    recommended_regime: str = "new"


# --- Tax Engine (standalone computation) ---
class ComputeTaxRequest(BaseModel):
    salary: dict[str, Any] = Field(
        default_factory=lambda: {
            "basic": 0, "hra_received": 0, "special_allowance": 0,
            "perquisites": 0, "profits_in_lieu": 0,
            "other_income": 0,
        }
    )
    investments: dict[str, Any] = Field(
        default_factory=lambda: {"80C": [], "80D": {}, "nps": 0}
    )
    section_80ccd1: float = 0
    rent_paid: float = 0
    lta_exempt: float = 0
    other_section10_exemptions: float = 0
    home_loan_interest: float = 0
    savings_interest: float = 0
    house_property_income: float = 0
    business_income: float = 0
    other_sources_income: float = 0
    dividend_income: float = 0
    capital_gains_stcg: float = 0
    capital_gains_stcg_pre_23_jul_2024: float = 0
    capital_gains_stcg_post_23_jul_2024: float = 0
    capital_gains_ltcg: float = 0
    equity_stcg: float = 0
    equity_ltcg: float = 0
    capital_gains: dict[str, Any] = Field(default_factory=dict)
    employer_nps_80ccd2: float = 0
    education_loan_interest_80e: float = 0
    electric_vehicle_loan_interest_80eeb: float = 0
    donation_80g_50: float = 0
    donation_80g_100: float = 0
    rent_paid_80gg: float = 0
    claim_80gg: bool = False
    self_is_senior: bool = False
    parents_are_senior: bool = False
    professional_tax_paid: float = 0
    metro: bool = True
    regime: str = "old"  # old | new
    financial_year: str | None = None


class DeductionBreakupItem(BaseModel):
    section: str
    amount: float
    explanation: str
    legal_reference: str
    section_label: str | None = None  # translated


class SlabBreakupItem(BaseModel):
    lower: float
    upper: float
    rate: float
    taxable_at_rate: float
    tax_amount: float


class ComputeTaxResponse(BaseModel):
    regime: str
    slab_income: float = 0
    net_salary: float = 0
    gross_total_income: float = 0
    gross_income: float
    total_deductions: float
    taxable_income: float
    slab_tax_before_rebate: float = 0
    tax_before_rebate: float
    stcg_tax: float = 0
    ltcg_tax: float = 0
    surcharge: float = 0
    surcharge_rate_pct: float = 0
    marginal_relief: float = 0
    rebate_87a: float
    slab_tax_after_rebate: float = 0
    total_tax_before_cess: float = 0
    tax_after_rebate: float
    cess: float
    total_tax: float
    effective_rate_pct: float
    marginal_rate_pct: float = 0
    surcharge_applies: bool = False
    rebate_applies: bool = False
    deduction_breakup: list[DeductionBreakupItem] = Field(default_factory=list)
    slab_breakup: list[SlabBreakupItem] = Field(default_factory=list)


class OptimizeTaxRequest(BaseModel):
    salary: dict[str, Any] = Field(default_factory=dict)
    investments: dict[str, Any] = Field(default_factory=dict)
    section_80ccd1: float = 0
    rent_paid: float = 0
    lta_exempt: float = 0
    other_section10_exemptions: float = 0
    home_loan_interest: float = 0
    savings_interest: float = 0
    house_property_income: float = 0
    business_income: float = 0
    other_sources_income: float = 0
    dividend_income: float = 0
    capital_gains_stcg: float = 0
    capital_gains_stcg_pre_23_jul_2024: float = 0
    capital_gains_stcg_post_23_jul_2024: float = 0
    capital_gains_ltcg: float = 0
    equity_stcg: float = 0
    equity_ltcg: float = 0
    capital_gains: dict[str, Any] = Field(default_factory=dict)
    equity_stcg: float = 0
    equity_ltcg: float = 0
    employer_nps_80ccd2: float = 0
    education_loan_interest_80e: float = 0
    electric_vehicle_loan_interest_80eeb: float = 0
    donation_80g_50: float = 0
    donation_80g_100: float = 0
    rent_paid_80gg: float = 0
    claim_80gg: bool = False
    self_is_senior: bool = False
    parents_are_senior: bool = False
    professional_tax_paid: float = 0
    metro: bool = True
    financial_year: str | None = None


class SuggestedInvestmentItem(BaseModel):
    section: str
    current_claim: float
    max_deduction: float
    suggested_additional: float
    message: str


class OptimizeTaxResponse(BaseModel):
    recommended_regime: str
    tax_old: float
    tax_new: float
    savings_if_switch: float
    result_old: dict[str, Any]
    result_new: dict[str, Any]
    suggested_investments: list[SuggestedInvestmentItem] = Field(default_factory=list)


class GenerateITRRequest(BaseModel):
    salary: dict[str, Any] = Field(default_factory=dict)
    investments: dict[str, Any] = Field(default_factory=dict)
    section_80ccd1: float = 0
    rent_paid: float = 0
    lta_exempt: float = 0
    other_section10_exemptions: float = 0
    home_loan_interest: float = 0
    savings_interest: float = 0
    house_property_income: float = 0
    business_income: float = 0
    other_sources_income: float = 0
    dividend_income: float = 0
    capital_gains_stcg: float = 0
    capital_gains_stcg_pre_23_jul_2024: float = 0
    capital_gains_stcg_post_23_jul_2024: float = 0
    capital_gains_ltcg: float = 0
    equity_stcg: float = 0
    equity_ltcg: float = 0
    capital_gains: dict[str, Any] = Field(default_factory=dict)
    equity_stcg: float = 0
    equity_ltcg: float = 0
    employer_nps_80ccd2: float = 0
    education_loan_interest_80e: float = 0
    electric_vehicle_loan_interest_80eeb: float = 0
    donation_80g_50: float = 0
    donation_80g_100: float = 0
    rent_paid_80gg: float = 0
    claim_80gg: bool = False
    self_is_senior: bool = False
    parents_are_senior: bool = False
    professional_tax_paid: float = 0
    metro: bool = True
    financial_year: str | None = None
    regime_override: str | None = None


class GenerateITRResponse(BaseModel):
    total_income: float
    gross_income: float
    total_deductions: float
    taxable_income: float
    tax_payable: float
    regime_selected: str
    recommended_regime: str
    deduction_breakup: list[dict[str, Any]] = Field(default_factory=list)
    comparison: dict[str, float] = Field(default_factory=dict)


class ExplainSectionRequest(BaseModel):
    section: str  # 80C, 80D, HRA, 80CCD(1B), 24(b), 80TTA, standard_deduction
    context: dict[str, Any] = Field(default_factory=dict)
    regime: str = "old"
    language: str = "en"  # en, hi, ml


class ExplainSectionResponse(BaseModel):
    section: str
    claimed: float
    eligible_limit: float | None
    explanation: str
    suggestion: str | None
    legal_reference: str
    section_label: str | None = None


# --- Conversation ---
class ConversationMessage(BaseModel):
    role: str  # user | assistant
    content: str
    language: str | None = None


class ConversationRequest(BaseModel):
    message: str
    session_id: str | None = None
    language_hint: str | None = None  # en, hi, ta, te, etc.
    intent: str | None = None  # optional override
    parsed_docs: list[dict[str, Any]] | None = None  # Uploaded document context
    conversation_history: list[dict[str, str]] | None = None  # Previous messages
    user_profile: dict[str, Any] | None = None  # Age, filing_status, etc.
    enable_voice: bool = True  # Generate TTS audio


class ConversationResponse(BaseModel):
    reply: str
    spoken_reply: str | None = None
    intent: str
    language_detected: str = "en"
    language_responded: str = "en"
    tts_audio_url: str | None = None
    tts_audio_data: str | None = None  # Base64-encoded audio data
    avatar_prompt: dict[str, Any] | None = None  # JSON spec for TTS & avatar
    session_id: str | None = None


class TaxDocReviewRequest(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)
    confirm: bool = False
    regime: str | None = None  # old | new


class ITR1MapRequest(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)


class TaxDocReviewResponse(BaseModel):
    document_types: list[str] = Field(default_factory=list)
    extracted: dict[str, Any] = Field(default_factory=dict)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    needs_confirmation: bool = True
    message: str = "Please review extracted data before filing."
    filing_json: dict[str, Any] | None = None
