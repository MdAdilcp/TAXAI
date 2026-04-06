"""
TaxAI Tax Computation Engine — standalone, no government API dependencies.
"""
from tax_engine.slabs import load_slabs, get_new_regime_slabs, get_old_regime_slabs
from tax_engine.hra import compute_hra_exemption
from tax_engine.deductions import (
    deduction_80c,
    deduction_80d,
    deduction_standard,
    deduction_nps_80ccd_1b,
    deduction_home_loan_interest,
    deduction_80tta,
    DeductionResult,
)
from tax_engine.calculator import compute_tax, TaxResult
from tax_engine.optimizer import optimize_tax, OptimizationResult
from tax_engine.itr_generator import generate_itr
from tax_engine.translations import translate, translate_deduction_result, SUPPORTED_LANGUAGES

__all__ = [
    "load_slabs",
    "get_new_regime_slabs",
    "get_old_regime_slabs",
    "compute_hra_exemption",
    "deduction_80c",
    "deduction_80d",
    "deduction_standard",
    "deduction_nps_80ccd_1b",
    "deduction_home_loan_interest",
    "deduction_80tta",
    "DeductionResult",
    "compute_tax",
    "TaxResult",
    "optimize_tax",
    "OptimizationResult",
    "generate_itr",
    "translate",
    "translate_deduction_result",
    "SUPPORTED_LANGUAGES",
]
