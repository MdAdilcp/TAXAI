"""Tax slabs — configurable via JSON for yearly updates."""
import json
from pathlib import Path
from typing import Any

from decimal import Decimal

_DEFAULT_SLABS_PATH = Path(__file__).resolve().parent / "config" / "slabs_ay_2024_25.json"
_slabs_cache: dict[str, Any] | None = None


def _decimalize(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_decimalize(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _decimalize(v) for k, v in obj.items()}
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return Decimal(str(obj))
    return obj


def load_slabs(path: Path | None = None) -> dict[str, Any]:
    """Load slab config from JSON. Cached for process lifetime."""
    global _slabs_cache
    if _slabs_cache is not None:
        return _slabs_cache
    p = path or _DEFAULT_SLABS_PATH
    if not p.exists():
        raise FileNotFoundError(f"Slabs config not found: {p}")
    with open(p) as f:
        _slabs_cache = _decimalize(json.load(f))
    return _slabs_cache


def get_new_regime_slabs() -> list[tuple[Decimal, Decimal, Decimal]]:
    """Returns list of (low, high, rate) for new regime."""
    cfg = load_slabs()
    slabs = cfg["new_regime"]["slabs"]
    return [
        (
            Decimal(str(s[0])),
            Decimal("Infinity") if s[1] is None else Decimal(str(s[1])),
            Decimal(str(s[2])),
        )
        for s in slabs
    ]


def get_old_regime_slabs() -> list[tuple[Decimal, Decimal, Decimal]]:
    """Returns list of (low, high, rate) for old regime."""
    cfg = load_slabs()
    slabs = cfg["old_regime"]["slabs"]
    return [
        (
            Decimal(str(s[0])),
            Decimal("Infinity") if s[1] is None else Decimal(str(s[1])),
            Decimal(str(s[2])),
        )
        for s in slabs
    ]


def get_cess_rate() -> Decimal:
    return load_slabs().get("cess_rate", Decimal("0.04"))


def get_rebate_87a(regime: str, financial_year: str | None = None) -> tuple[Decimal, Decimal]:
    """(income_limit, rebate_amount) for rebate u/s 87A, optionally by financial year."""
    cfg = load_slabs()
    key = "new_regime" if regime == "new" else "old_regime"
    r = cfg[key]
    if regime == "new" and financial_year:
        fy_map = r.get("rebate_87a_by_financial_year", {})
        fy_cfg = fy_map.get(financial_year)
        if isinstance(fy_cfg, dict):
            limit = fy_cfg.get("limit", r.get("rebate_87a_limit"))
            amount = fy_cfg.get("amount", r.get("rebate_87a_amount"))
            return Decimal(str(limit)), Decimal(str(amount))
    return Decimal(str(r["rebate_87a_limit"])), Decimal(str(r["rebate_87a_amount"]))


def get_standard_deduction(regime: str) -> Decimal:
    cfg = load_slabs()
    if regime == "old":
        # Compliance guardrail: old regime standard deduction must remain 50,000.
        return Decimal("50000")
    key = "new_regime"
    return Decimal(str(cfg[key]["standard_deduction"]))


def get_surcharge_slabs() -> list[tuple[Decimal, Decimal, Decimal]]:
    cfg = load_slabs()
    surcharge = cfg.get("surcharge", [])
    if isinstance(surcharge, dict):
        slabs = surcharge.get("common", [])
        old_high = surcharge.get("above_5cr_old_regime")
        if old_high is not None:
          slabs = list(slabs) + [[50000000, None, old_high]]
        surcharge = slabs
    return [
        (
            Decimal(str(s[0])),
            Decimal("Infinity") if s[1] is None else Decimal(str(s[1])),
            Decimal(str(s[2])),
        )
        for s in surcharge
    ]


def get_section_limits() -> dict[str, Decimal]:
    """Section limits (80C, 80D, etc.) from config."""
    cfg = load_slabs()
    deductions_cfg = cfg.get("deductions", cfg)
    out = {}
    for k in ["section_80c_limit", "section_80d_self", "section_80d_senior_self",
              "section_80d_parents", "section_80d_parents_senior", "section_80ccd_1b",
              "section_80ccd_2_new_rate", "section_80tta", "section_80ttb",
              "section_24b_interest_home_loan", "section_80gg_monthly_limit"]:
        if k in deductions_cfg:
            out[k] = Decimal(str(deductions_cfg[k]))
    return out
