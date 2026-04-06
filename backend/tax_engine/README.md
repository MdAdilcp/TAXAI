# TaxAI Tax Computation Engine

Standalone Indian income tax computation — **no government API dependencies** (no ERI, GSTN, UIDAI, PAN verification). Pure logic for Old/New regime tax, deductions, and ITR-ready output.

## Design

- **Modular**: `slabs`, `deductions`, `hra`, `calculator`, `optimizer`, `itr_generator`, `explain` are separate modules.
- **Configurable**: Tax slabs and section limits are in `config/slabs_ay_2024_25.json` for easy yearly updates.
- **Deterministic**: Same inputs always produce the same outputs; no external calls.
- **Explainable**: Each deduction returns amount, explanation, legal reference, and optional suggestion.

## Tax Calculation Flow

```
1. Input: salary (basic, hra_received, special_allowance, other_income), investments (80C, 80D, nps),
          rent_paid, home_loan_interest, savings_interest, professional_tax_paid, metro.

2. Gross income = annualized salary + other_income.

3. Deductions (Old regime):
   - Standard deduction (₹75,000)
   - Professional tax
   - HRA exemption (min of actual HRA, 50%/40% of basic, rent − 10% basic)
   - Section 80C (max ₹1,50,000)
   - Section 80D (self + parents, caps 25k/50k)
   - NPS 80CCD(1B) (max ₹50,000)
   - Home loan interest 24(b) (max ₹2,00,000)
   - Section 80TTA (max ₹10,000)

   New regime: only standard deduction (+ professional tax).

4. Taxable income = max(0, gross_income − total_deductions).

5. Tax = slab-wise tax on taxable income; subtract Rebate 87A if income within limit; add 4% cess.

6. Output: tax_payable, deduction_breakup, effective_rate.
```

## Module Overview

| File | Purpose |
|------|--------|
| `slabs.py` | Load slab config from JSON; expose new/old regime slabs, rebate 87A, standard deduction, section limits. |
| `deductions.py` | 80C, 80D, standard deduction, NPS 80CCD(1B), 24(b), 80TTA, professional tax. Each returns amount + explanation + legal ref. |
| `hra.py` | HRA exemption per Section 10(13A), Rule 2A (metro / non-metro). |
| `calculator.py` | `compute_tax(salary, investments, ..., regime)` → TaxResult with breakup. |
| `optimizer.py` | `optimize_tax(...)` → compare old vs new, recommend regime, suggest additional 80C/80D/NPS. |
| `itr_generator.py` | `generate_itr(...)` → ITR-ready JSON (total_income, total_deductions, taxable_income, tax_payable, regime). |
| `explain.py` | `explain_section(section, context, regime)` → explainable output for one section. |
| `translations.py` | EN / HI / ML labels for sections (no external API). |

## Updating for a New Year

1. Copy `config/slabs_ay_2024_25.json` to e.g. `config/slabs_ay_2025_26.json`.
2. Update slab brackets, rebate 87A limits/amounts, standard deduction, and section limits per Finance Act.
3. In `slabs.py`, point `_DEFAULT_SLABS_PATH` to the new file (or pass path to `load_slabs(path)`).

## API Endpoints (FastAPI)

- **POST /api/compute-tax** — Compute tax for given income + deductions under one regime.
- **POST /api/optimize-tax** — Compare regimes, recommend one, suggest extra investments.
- **POST /api/generate-itr** — Get ITR-ready JSON.
- **POST /api/explain-section** — Explain a single section (with optional language en/hi/ml).

No external APIs are called from these endpoints.
