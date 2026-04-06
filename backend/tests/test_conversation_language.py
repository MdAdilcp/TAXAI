from app.services.conversation_service import _detect_language, _resolve_response_language


def test_detect_language_malayalam_script():
    assert _detect_language("എനിക്ക് നികുതി സഹായം വേണം") == "ml"


def test_detect_language_tamil_script():
    assert _detect_language("எனக்கு வரி உதவி வேண்டும்") == "ta"


def test_resolve_prefers_detected_script_over_hint():
    responded, detected = _resolve_response_language("എനിക്ക് നികുതി സഹായം വേണം", "ta")
    assert detected == "ml"
    assert responded == "ml"


def test_resolve_uses_hint_for_english_text():
    responded, detected = _resolve_response_language("help me with tax", "ml")
    assert detected == "en"
    assert responded == "ml"
