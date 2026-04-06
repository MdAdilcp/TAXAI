"""
Update pipeline for Finance Act / deduction limits.
Run annually or when rules change; updates kb/deduction_rules.json.
Input: JSON or CSV with section, max_amount, citation, effective_from.
"""
import json
import sys
from pathlib import Path

KB_PATH = Path(__file__).resolve().parent.parent / "kb" / "deduction_rules.json"


def load_kb() -> dict:
    with open(KB_PATH) as f:
        return json.load(f)


def save_kb(data: dict) -> None:
    with open(KB_PATH, "w") as f:
        json.dump(data, f, indent=2)


def apply_updates(updates: list[dict]) -> None:
    kb = load_kb()
    for u in updates:
        key = u.get("section") or u.get("code")
        if not key:
            continue
        if key not in kb:
            kb[key] = {}
        for k, v in u.items():
            if k != "section" and k != "code":
                kb[key][k] = v
    save_kb(kb)
    print("KB updated.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python update_finance_act.py updates.json")
        sys.exit(1)
    with open(sys.argv[1]) as f:
        updates = json.load(f)
    if isinstance(updates, list):
        apply_updates(updates)
    else:
        apply_updates([updates])
