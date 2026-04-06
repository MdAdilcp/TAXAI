"""Multilingual support: EN, HI, ML. No external API — static strings."""
from typing import Any

# Keys used in explanations; values: { "en": "...", "hi": "...", "ml": "..." }
_TRANSLATIONS: dict[str, dict[str, str]] = {
    "section_80c": {
        "en": "Section 80C — Investments in ELSS, PPF, LIC, etc. (max ₹1.5 Lakh)",
        "hi": "धारा 80C — ELSS, PPF, LIC आदि में निवेश (अधिकतम ₹1.5 लाख)",
        "ml": "സെക്ഷൻ 80C — ELSS, PPF, LIC മുതലായവയിൽ നിക്ഷേപം (പരമാവധി ₹1.5 ലക്ഷം)",
    },
    "section_80d": {
        "en": "Section 80D — Health insurance premium (self & parents)",
        "hi": "धारा 80D — स्वास्थ्य बीमा प्रीमियम (स्वयं व माता-पिता)",
        "ml": "സെക്ഷൻ 80D — ഹെൽത്ത് ഇൻഷുറൻസ് പ്രീമിയം (സ്വയം, മാതാപിതാക്കൾ)",
    },
    "standard_deduction": {
        "en": "Standard deduction (salary)",
        "hi": "मानक कटौती (वेतन)",
        "ml": "സ്റ്റാൻഡേർഡ് കിഴിവ് (ശമ്പളം)",
    },
    "hra": {
        "en": "HRA exemption [Section 10(13A)]",
        "hi": "HRA छूट [धारा 10(13A)]",
        "ml": "HRA ഒഴിവ് [സെക്ഷൻ 10(13A)]",
    },
    "nps": {
        "en": "NPS additional deduction 80CCD(1B) (max ₹50,000)",
        "hi": "NPS अतिरिक्त कटौती 80CCD(1B) (अधिकतम ₹50,000)",
        "ml": "NPS അധിക കിഴിവ് 80CCD(1B) (പരമാവധി ₹50,000)",
    },
    "home_loan_interest": {
        "en": "Home loan interest [Section 24(b)] (max ₹2 Lakh)",
        "hi": "गृह ऋण ब्याज [धारा 24(b)] (अधिकतम ₹2 लाख)",
        "ml": "ഹോം ലോൺ പലിശ [സെക്ഷൻ 24(b)] (പരമാവധി ₹2 ലക്ഷം)",
    },
    "80tta": {
        "en": "Savings account interest (80TTA, max ₹10,000)",
        "hi": "बचत खाता ब्याज (80TTA, अधिकतम ₹10,000)",
        "ml": "സേവിംഗ്സ് അക്കൗണ്ട് പലിശ (80TTA, പരമാവധി ₹10,000)",
    },
    "professional_tax": {
        "en": "Professional tax",
        "hi": "पेशेवर कर",
        "ml": "പ്രൊഫഷണൽ ടാക്സ്",
    },
    "lta_105": {
        "en": "LTA exemption [Section 10(5)]",
        "hi": "LTA छूट [धारा 10(5)]",
        "ml": "LTA ഒഴിവ് [സെക്ഷൻ 10(5)]",
    },
    "invest_more_80c": {
        "en": "Invest more to maximize 80C benefit.",
        "hi": "80C लाभ बढ़ाने के लिए और निवेश करें।",
        "ml": "80C ആനുകൂല്യം പരമാവധിയാക്കാൻ കൂടുതൽ നിക്ഷേപിക്കുക.",
    },
    "recommended_regime": {
        "en": "Recommended regime",
        "hi": "अनुशंसित व्यवस्था",
        "ml": "ശുപാർശ ചെയ്ത ഭരണം",
    },
    "old_regime": {"en": "Old regime", "hi": "पुरानी व्यवस्था", "ml": "പഴയ ഭരണം"},
    "new_regime": {"en": "New regime", "hi": "नई व्यवस्था", "ml": "പുതിയ ഭരണം"},
}

SUPPORTED_LANGUAGES = ["en", "hi", "ml"]


def translate(key: str, lang: str = "en") -> str:
    """Return translated string for key; fallback to English."""
    if lang not in SUPPORTED_LANGUAGES:
        lang = "en"
    return _TRANSLATIONS.get(key, {}).get(lang) or _TRANSLATIONS.get(key, {}).get("en") or key


def translate_deduction_result(result: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    """Add translated section name and explanation key to a deduction result."""
    section_key = result.get("section", "").replace("(", "").replace(")", "").lower()
    if "80ccd" in section_key:
        section_key = "nps"
    elif "24" in section_key:
        section_key = "home_loan_interest"
    elif section_key == "80tta":
        section_key = "80tta"
    elif section_key == "standard_deduction":
        section_key = "standard_deduction"
    elif section_key == "hra":
        section_key = "hra"
    elif section_key == "professional_tax":
        section_key = "professional_tax"
    elif "10" in section_key and "5" in section_key and "lta" in section_key:
        section_key = "lta_105"
    elif "80c" in section_key:
        section_key = "section_80c"
    elif "80d" in section_key:
        section_key = "section_80d"
    result["section_label"] = translate(section_key, lang)
    return result
