# TaxAI — Standalone Indian Tax Computation Engine

TaxAI is a **standalone Indian income tax computation engine** with **no government API dependencies** (no ERI, GSTN, UIDAI, PAN verification). It accepts structured income and deduction data, computes tax under Old and New regimes, suggests optimized deduction strategies, and generates ITR-ready JSON with explainable reasoning per deduction.

## Architecture Overview

- **Backend**: FastAPI (Python 3.11+)
- **Tax engine**: Pure computation in `tax_engine/` — slabs, deductions, HRA, calculator, optimizer, ITR generator, explainable layer
- **Optional**: OCR (Google Vision), conversation (OpenAI), TTS/avatar for UI — not required for tax computation
- **No external filing**: ERI, PAN, GST, UIDAI integrations have been removed; design is modular for future API integration if needed

## Tax Engine (Core)

| Module | Purpose |
|--------|--------|
| `tax_engine/slabs.py` | Configurable tax slabs (JSON) for Old/New regime |
| `tax_engine/deductions.py` | 80C, 80D, standard deduction, NPS, home loan interest, 80TTA |
| `tax_engine/hra.py` | HRA exemption formula [Section 10(13A)] |
| `tax_engine/calculator.py` | Full tax computation for a chosen regime |
| `tax_engine/optimizer.py` | Compare regimes, recommend best, suggest investments |
| `tax_engine/itr_generator.py` | ITR-ready JSON output |
| `tax_engine/explain.py` | Explainable output per section (claimed, limit, suggestion) |
| `tax_engine/translations.py` | Multilingual labels (EN, HI, ML) |

See **`backend/tax_engine/README.md`** for the detailed tax calculation flow and slab/deduction logic.

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+ (optional, for frontend)

### Backend (Tax Engine + API)

```bash
cd taxai
python -m venv .venv
.venv\Scripts\activate   # Windows; on Unix: source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload --port 8001
```

No API keys are required for the **tax computation endpoints**. Optional: set `OPENROUTER_API_KEY` for OCR/conversation and `GOOGLE_APPLICATION_CREDENTIALS` only if you want Vision fallback.

For OpenRouter-first OCR usage, set:

```env
LLM_PROVIDER=openrouter
OCR_PROVIDER=openrouter
OCR_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=google/gemini-2.0-flash-001
OPENROUTER_FALLBACK_MODEL=openai/gpt-4o-mini
OCR_ENABLE_LLM_REFINE=true
```

For Gemini-first usage, set:

```env
LLM_PROVIDER=gemini
OCR_PROVIDER=gemini
OCR_LLM_PROVIDER=gemini
GEMINI_CHAT_MODEL=gemini-2.0-flash
GEMINI_OCR_MODEL=gemini-2.0-flash
```

### Frontend (optional)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 for the avatar + conversation demo.

### Hosting Checklist (Frontend + Backend)

- Deploy backend and expose it via HTTPS.
- Set frontend env `VITE_API_URL` to your backend base URL (example: `https://api.yourdomain.com`).
- Optional: set `VITE_API_FALLBACK_URL` for a secondary backend endpoint.
- If frontend and backend are served from the same origin with reverse proxy, `VITE_API_URL` can be left empty and `/api/*` routes will work directly.
- For local development, backend defaults to port `8001`.

## API Endpoints (Tax Engine — No External APIs)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/compute-tax` | Compute tax for given income + deductions under one regime (old/new) |
| POST | `/api/optimize-tax` | Compare old vs new regime; recommend best; suggest additional 80C/80D/NPS |
| POST | `/api/generate-itr` | Generate ITR-ready JSON (total_income, deductions, tax_payable, regime) |
| POST | `/api/explain-section` | Explain one deduction section (claimed, limit, suggestion); optional language en/hi/ml |

### Other Endpoints (Optional Features)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload-doc` | Upload document → OCR → structured data (OpenRouter-first with fallback) |
| POST | `/api/parse-salary` | Salary breakup from doc/structured data |
| POST | `/api/recommend-deductions` | Ranked deductions from profile + docs |
| POST | `/api/calculate-tax` | Legacy tax calc (uses old service layer) |
| POST | `/api/conversation` | Chat + multilingual (OpenAI or Gemini) |
| GET | `/api/tts` | TTS for avatar (needs Google TTS) |

## Sample Input (Tax Engine)

```json
{
  "salary": {
    "basic": 60000,
    "hra_received": 24000,
    "special_allowance": 10000,
    "other_income": 0
  },
  "investments": {
    "80C": [50000, 50000, 50000],
    "80D_self": 15000,
    "80D_parents": 10000,
    "nps": 25000
  },
  "rent_paid": 288000,
  "home_loan_interest": 150000,
  "savings_interest": 8000,
  "professional_tax_paid": 2400,
  "metro": true
}
```

Salary components can be **monthly** (basic, hra_received, special_allowance); they are annualized internally. `rent_paid`, `home_loan_interest`, `savings_interest`, `professional_tax_paid` are **annual**. See **`backend/sample_input_output.json`** for full sample and response structure.

## Project Structure

```
taxai/
├── backend/
│   ├── app/              # FastAPI app, API routes
│   ├── tax_engine/        # Standalone computation (slabs, deductions, hra, calculator, optimizer, itr_generator, explain)
│   ├── tests/            # Unit tests (test_tax_engine.py)
│   ├── sample_input_output.json
│   └── requirements.txt
├── frontend/             # React + avatar + conversation (optional)
└── README.md
```

## Running Tests

```bash
cd backend
pytest tests/test_tax_engine.py -v
```

Tests cover: 5L salary no deductions, 10L with max 80C, HRA exemption, home loan + NPS, and old vs new regime comparison.

## Yearly Updates

Tax slabs and section limits are in **`backend/tax_engine/config/slabs_ay_2024_25.json`**. To support a new AY, add a new JSON file (e.g. `slabs_ay_2025_26.json`) and point `slabs.load_slabs()` to it (or pass path). No code change required for slab or limit values.

## Constraints

- **Modular**: Tax logic is isolated in `tax_engine/`; presentation and optional OCR/LLM are separate.
- **Deterministic**: Same inputs → same outputs; no external calls in the tax engine.
- **No government APIs**: ERI, PAN, GST, UIDAI have been removed; can be re-added later as adapters if needed.

## License

Proprietary / Internal use. Ensure compliance with Indian tax and data regulations.
