"""Tax computation engine API — no external government APIs."""
from decimal import Decimal
from typing import Any

from fastapi import APIRouter

from app.models.schemas import (
    ComputeTaxRequest,
    ComputeTaxResponse,
    DeductionBreakupItem,
    SlabBreakupItem,
    OptimizeTaxRequest,
    OptimizeTaxResponse,
    SuggestedInvestmentItem,
    GenerateITRRequest,
    GenerateITRResponse,
    ExplainSectionRequest,
    ExplainSectionResponse,
)
from tax_engine.calculator import compute_tax
from tax_engine.optimizer import optimize_tax
from tax_engine.itr_generator import generate_itr
from tax_engine.explain import explain_section
from tax_engine.translations import translate_deduction_result, SUPPORTED_LANGUAGES


router = APIRouter(prefix="/api", tags=["tax-engine"])


def _to_decimal(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v)) if v is not None else Decimal("0")


def _normalize_investments(investments: dict[str, Any]) -> dict[str, Any]:
    """Accept flexible frontend payloads and normalize to tax_engine format.

    tax_engine expects keys like:
    - 80C: list[number]
    - 80D_self, 80D_parents
    - nps
    """
    raw = investments or {}
    out: dict[str, Any] = dict(raw)

    # 80C may come as [150000] OR [{amount: 150000}, ...]
    inv_80c = raw.get("80C", [])
    if isinstance(inv_80c, list):
        norm_80c: list[float] = []
        for item in inv_80c:
            if isinstance(item, dict):
                norm_80c.append(float(_to_decimal(item.get("amount", 0))))
            else:
                norm_80c.append(float(_to_decimal(item)))
        out["80C"] = norm_80c

    # 80D may come as nested object: { self_family, parents }
    inv_80d = raw.get("80D")
    if isinstance(inv_80d, dict):
        out["80D_self"] = float(_to_decimal(inv_80d.get("self_family", 0)))
        out["80D_parents"] = float(_to_decimal(inv_80d.get("parents", 0)))

    # Keep compatibility for alternate keys
    if "80D_self" not in out:
        out["80D_self"] = float(_to_decimal(raw.get("80D_self", 0)))
    if "80D_parents" not in out:
        out["80D_parents"] = float(_to_decimal(raw.get("80D_parents", 0)))

    out["nps"] = float(_to_decimal(raw.get("nps", 0)))
    return out


def _resolve_capital_gains(req: Any) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]:
    cg = req.capital_gains or {}
    stcg = _to_decimal(req.capital_gains_stcg)
    stcg_pre = _to_decimal(req.capital_gains_stcg_pre_23_jul_2024)
    stcg_post = _to_decimal(req.capital_gains_stcg_post_23_jul_2024)
    ltcg = _to_decimal(req.capital_gains_ltcg)

    if stcg == 0:
        stcg = _to_decimal(cg.get("capital_gains_stcg", cg.get("stcg", 0)))
    if stcg_pre == 0:
        stcg_pre = _to_decimal(cg.get("capital_gains_stcg_pre_23_jul_2024", 0))
    if stcg_post == 0:
        stcg_post = _to_decimal(cg.get("capital_gains_stcg_post_23_jul_2024", 0))
    if ltcg == 0:
        ltcg = _to_decimal(cg.get("capital_gains_ltcg", cg.get("ltcg", 0)))

    equity_stcg = _to_decimal(req.equity_stcg)
    equity_ltcg = _to_decimal(req.equity_ltcg)
    if equity_stcg == 0:
        equity_stcg = _to_decimal(cg.get("equity_stcg", 0))
    if equity_ltcg == 0:
        equity_ltcg = _to_decimal(cg.get("equity_ltcg", 0))

    return stcg, stcg_pre, stcg_post, ltcg, equity_stcg, equity_ltcg


def _serialize_tax_result(result: Any) -> dict[str, Any]:
    return {
        "regime": result.regime,
        "slab_income": float(result.slab_income),
        "net_salary": float(result.net_salary),
        "gross_total_income": float(result.gross_total_income),
        "gross_income": float(result.gross_income),
        "total_deductions": float(result.total_deductions),
        "taxable_income": float(result.taxable_income),
        "slab_tax_before_rebate": float(result.slab_tax_before_rebate),
        "tax_before_rebate": float(result.tax_before_rebate),
        "stcg_tax": float(result.stcg_tax),
        "ltcg_tax": float(result.ltcg_tax),
        "surcharge": float(result.surcharge),
        "surcharge_rate_pct": result.surcharge_rate_pct,
        "marginal_relief": float(result.marginal_relief),
        "rebate_87a": float(result.rebate_87a),
        "slab_tax_after_rebate": float(result.slab_tax_after_rebate),
        "total_tax_before_cess": float(result.total_tax_before_cess),
        "tax_after_rebate": float(result.tax_after_rebate),
        "cess": float(result.cess),
        "total_tax": float(result.total_tax),
        "effective_rate_pct": result.effective_rate_pct,
        "marginal_rate_pct": result.marginal_rate_pct,
        "surcharge_applies": result.surcharge_applies,
        "rebate_applies": result.rebate_applies,
        "deduction_breakup": [
            {
                "section": r.section,
                "amount": float(r.amount),
                "explanation": r.explanation,
                "legal_reference": r.legal_reference,
            }
            for r in result.deduction_breakup
        ],
        "slab_breakup": [
            {
                "lower": float(s["lower"]),
                "upper": float(s["upper"]),
                "rate": float(s["rate"]),
                "taxable_at_rate": float(s["taxable_at_rate"]),
                "tax_amount": float(s["tax_amount"]),
            }
            for s in result.slab_breakup
        ],
    }


@router.post("/compute-tax", response_model=ComputeTaxResponse)
def compute_tax_endpoint(req: ComputeTaxRequest) -> ComputeTaxResponse:
    """Compute tax for given income and deductions under specified regime (old/new)."""
    salary = req.salary or {}
    investments = _normalize_investments(req.investments or {})
    if _to_decimal(req.section_80ccd1) > 0:
        investments.setdefault("80C", [])
        investments["80C"].append(float(_to_decimal(req.section_80ccd1)))
    stcg, stcg_pre, stcg_post, ltcg, equity_stcg, equity_ltcg = _resolve_capital_gains(req)
    result = compute_tax(
        salary=salary,
        investments=investments,
        rent_paid=_to_decimal(req.rent_paid),
        lta_exempt=_to_decimal(req.lta_exempt),
        other_section10_exemptions=_to_decimal(req.other_section10_exemptions),
        home_loan_interest=_to_decimal(req.home_loan_interest),
        savings_interest=_to_decimal(req.savings_interest),
        house_property_income=_to_decimal(req.house_property_income),
        business_income=_to_decimal(req.business_income),
        other_sources_income=_to_decimal(req.other_sources_income),
        dividend_income=_to_decimal(req.dividend_income),
        capital_gains_stcg=stcg,
        capital_gains_stcg_pre_23_jul_2024=stcg_pre,
        capital_gains_stcg_post_23_jul_2024=stcg_post,
        capital_gains_ltcg=ltcg,
        equity_stcg=equity_stcg,
        equity_ltcg=equity_ltcg,
        employer_nps_80ccd2=_to_decimal(req.employer_nps_80ccd2),
        education_loan_interest_80e=_to_decimal(req.education_loan_interest_80e),
        electric_vehicle_loan_interest_80eeb=_to_decimal(req.electric_vehicle_loan_interest_80eeb),
        donation_80g_50=_to_decimal(req.donation_80g_50),
        donation_80g_100=_to_decimal(req.donation_80g_100),
        rent_paid_80gg=_to_decimal(req.rent_paid_80gg),
        claim_80gg=req.claim_80gg,
        self_is_senior=req.self_is_senior,
        parents_are_senior=req.parents_are_senior,
        professional_tax_paid=_to_decimal(req.professional_tax_paid),
        metro=req.metro,
        regime=req.regime,
        financial_year=req.financial_year,
    )
    lang = "en"
    breakup = [
        DeductionBreakupItem(
            section=r.section,
            amount=float(r.amount),
            explanation=r.explanation,
            legal_reference=r.legal_reference,
            section_label=translate_deduction_result(
                {"section": r.section}, lang
            ).get("section_label"),
        )
        for r in result.deduction_breakup
    ]
    slab_breakup = [
        SlabBreakupItem(
            lower=float(s["lower"]),
            upper=float(s["upper"]),
            rate=float(s["rate"]),
            taxable_at_rate=float(s["taxable_at_rate"]),
            tax_amount=float(s["tax_amount"]),
        )
        for s in result.slab_breakup
    ]
    return ComputeTaxResponse(
        regime=result.regime,
        slab_income=float(result.slab_income),
        net_salary=float(result.net_salary),
        gross_total_income=float(result.gross_total_income),
        gross_income=float(result.gross_income),
        total_deductions=float(result.total_deductions),
        taxable_income=float(result.taxable_income),
        slab_tax_before_rebate=float(result.slab_tax_before_rebate),
        tax_before_rebate=float(result.tax_before_rebate),
        stcg_tax=float(result.stcg_tax),
        ltcg_tax=float(result.ltcg_tax),
        surcharge=float(result.surcharge),
        surcharge_rate_pct=result.surcharge_rate_pct,
        marginal_relief=float(result.marginal_relief),
        rebate_87a=float(result.rebate_87a),
        slab_tax_after_rebate=float(result.slab_tax_after_rebate),
        total_tax_before_cess=float(result.total_tax_before_cess),
        tax_after_rebate=float(result.tax_after_rebate),
        cess=float(result.cess),
        total_tax=float(result.total_tax),
        effective_rate_pct=result.effective_rate_pct,
        marginal_rate_pct=result.marginal_rate_pct,
        surcharge_applies=result.surcharge_applies,
        rebate_applies=result.rebate_applies,
        deduction_breakup=breakup,
        slab_breakup=slab_breakup,
    )


@router.post("/optimize-tax", response_model=OptimizeTaxResponse)
def optimize_tax_endpoint(req: OptimizeTaxRequest) -> OptimizeTaxResponse:
    """Compare old vs new regime; recommend best; suggest additional investments."""
    investments = _normalize_investments(req.investments or {})
    if _to_decimal(req.section_80ccd1) > 0:
        investments.setdefault("80C", [])
        investments["80C"].append(float(_to_decimal(req.section_80ccd1)))
    stcg, stcg_pre, stcg_post, ltcg, equity_stcg, equity_ltcg = _resolve_capital_gains(req)
    opt = optimize_tax(
        salary=req.salary or {},
        investments=investments,
        rent_paid=_to_decimal(req.rent_paid),
        lta_exempt=_to_decimal(req.lta_exempt),
        other_section10_exemptions=_to_decimal(req.other_section10_exemptions),
        home_loan_interest=_to_decimal(req.home_loan_interest),
        savings_interest=_to_decimal(req.savings_interest),
        house_property_income=_to_decimal(req.house_property_income),
        business_income=_to_decimal(req.business_income),
        other_sources_income=_to_decimal(req.other_sources_income),
        dividend_income=_to_decimal(req.dividend_income),
        capital_gains_stcg=stcg,
        capital_gains_stcg_pre_23_jul_2024=stcg_pre,
        capital_gains_stcg_post_23_jul_2024=stcg_post,
        capital_gains_ltcg=ltcg,
        equity_stcg=equity_stcg,
        equity_ltcg=equity_ltcg,
        employer_nps_80ccd2=_to_decimal(req.employer_nps_80ccd2),
        education_loan_interest_80e=_to_decimal(req.education_loan_interest_80e),
        electric_vehicle_loan_interest_80eeb=_to_decimal(req.electric_vehicle_loan_interest_80eeb),
        donation_80g_50=_to_decimal(req.donation_80g_50),
        donation_80g_100=_to_decimal(req.donation_80g_100),
        rent_paid_80gg=_to_decimal(req.rent_paid_80gg),
        claim_80gg=req.claim_80gg,
        self_is_senior=req.self_is_senior,
        parents_are_senior=req.parents_are_senior,
        professional_tax_paid=_to_decimal(req.professional_tax_paid),
        metro=req.metro,
        financial_year=req.financial_year,
    )
    suggested = [
        SuggestedInvestmentItem(
            section=s["section"],
            current_claim=s["current_claim"],
            max_deduction=s["max_deduction"],
            suggested_additional=s["suggested_additional"],
            message=s["message"],
        )
        for s in opt.suggested_investments
    ]
    return OptimizeTaxResponse(
        recommended_regime=opt.recommended_regime,
        tax_old=float(opt.tax_old),
        tax_new=float(opt.tax_new),
        savings_if_switch=float(opt.savings_if_switch),
        result_old=_serialize_tax_result(opt.result_old),
        result_new=_serialize_tax_result(opt.result_new),
        suggested_investments=suggested,
    )


@router.post("/generate-itr", response_model=GenerateITRResponse)
def generate_itr_endpoint(req: GenerateITRRequest) -> GenerateITRResponse:
    """Generate ITR-ready JSON (total_income, deductions, tax_payable, regime)."""
    stcg, stcg_pre, stcg_post, ltcg, equity_stcg, equity_ltcg = _resolve_capital_gains(req)
    itr = generate_itr(
        salary=req.salary or {},
        investments=_normalize_investments(req.investments or {}),
        rent_paid=_to_decimal(req.rent_paid),
        lta_exempt=_to_decimal(req.lta_exempt),
        other_section10_exemptions=_to_decimal(req.other_section10_exemptions),
        home_loan_interest=_to_decimal(req.home_loan_interest),
        savings_interest=_to_decimal(req.savings_interest),
        house_property_income=_to_decimal(req.house_property_income),
        business_income=_to_decimal(req.business_income),
        other_sources_income=_to_decimal(req.other_sources_income),
        capital_gains_stcg=stcg,
        capital_gains_stcg_pre_23_jul_2024=stcg_pre,
        capital_gains_stcg_post_23_jul_2024=stcg_post,
        capital_gains_ltcg=ltcg,
        equity_stcg=equity_stcg,
        equity_ltcg=equity_ltcg,
        employer_nps_80ccd2=_to_decimal(req.employer_nps_80ccd2),
        education_loan_interest_80e=_to_decimal(req.education_loan_interest_80e),
        donation_80g_50=_to_decimal(req.donation_80g_50),
        donation_80g_100=_to_decimal(req.donation_80g_100),
        rent_paid_80gg=_to_decimal(req.rent_paid_80gg),
        claim_80gg=req.claim_80gg,
        self_is_senior=req.self_is_senior,
        parents_are_senior=req.parents_are_senior,
        professional_tax_paid=_to_decimal(req.professional_tax_paid),
        metro=req.metro,
        regime_override=req.regime_override,
    )
    return GenerateITRResponse(
        total_income=itr["total_income"],
        gross_income=itr["gross_income"],
        total_deductions=itr["total_deductions"],
        taxable_income=itr["taxable_income"],
        tax_payable=itr["tax_payable"],
        regime_selected=itr["regime_selected"],
        recommended_regime=itr["recommended_regime"],
        deduction_breakup=itr["deduction_breakup"],
        comparison=itr["comparison"],
    )


@router.post("/explain-section", response_model=ExplainSectionResponse)
def explain_section_endpoint(req: ExplainSectionRequest) -> ExplainSectionResponse:
    """Explain a deduction section with claimed, limit, suggestion (multilingual)."""
    lang = req.language if req.language in SUPPORTED_LANGUAGES else "en"
    out = explain_section(req.section, req.context or {}, req.regime)
    out = translate_deduction_result(out, lang)
    return ExplainSectionResponse(
        section=out["section"],
        claimed=out["claimed"],
        eligible_limit=out.get("eligible_limit"),
        explanation=out["explanation"],
        suggestion=out.get("suggestion"),
        legal_reference=out["legal_reference"],
        section_label=out.get("section_label"),
    )
