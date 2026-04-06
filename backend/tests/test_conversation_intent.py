from app.services.conversation_service import _classify_intent


def test_question_mark_forces_general_intent():
    message = "is tax on profession excluded in new regime?"
    assert _classify_intent(message) == "general"


def test_non_question_tax_calculation_intent_still_detected():
    message = "calculate tax liability under new regime"
    assert _classify_intent(message) == "calculate-tax"
