"""RAG (Retrieval-Augmented Generation) service for tax-aware document context."""
import json
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

TAX_KEYWORDS = {
    "tax", "income tax", "deduction", "deductions", "regime", "old regime", "new regime",
    "80c", "80d", "80g", "80e", "80tta", "80ttb", "80ccd", "hra", "form 16",
    "itr", "return filing", "rebate", "slab", "cess", "surcharge", "tds", "nps",
    "ppf", "elss", "home loan", "section 24", "capital gain", "advance tax",
}

# Load tax knowledge base
KB_PATH = Path(__file__).resolve().parent.parent.parent / "kb" / "deduction_rules.json"
try:
    with open(KB_PATH) as f:
        TAX_KB = json.load(f)
except Exception:
    TAX_KB = {}


def _similarity(a: str, b: str) -> float:
    """Compute string similarity score (0-1)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def retrieve_relevant_deductions(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """
    Retrieve relevant tax deduction sections from KB based on query similarity.
    
    Args:
        query: User query text
        top_k: Number of top results to return
        
    Returns:
        List of relevant deduction rules with citations
    """
    if not query or not TAX_KB:
        return []
    
    results = []
    query_lower = query.lower()
    keywords = query_lower.split()
    
    for section_code, rule_data in TAX_KB.items():
        if not isinstance(rule_data, dict):
            continue
            
        name = rule_data.get("name", "").lower()
        citation = rule_data.get("citation", "").lower()
        note = rule_data.get("note", "").lower()
        
        # Calculate relevance score
        score = 0.0
        for keyword in keywords:
            if len(keyword) > 2:
                if keyword in name:
                    score += 0.5
                if keyword in citation:
                    score += 0.3
                if keyword in note:
                    score += 0.2
        
        # Also check section code matching
        if section_code.lower() in query_lower:
            score += 1.0
            
        # Check instruments
        instruments = rule_data.get("eligible_instruments", [])
        for instr in instruments:
            if isinstance(instr, str) and _similarity(instr.lower(), query_lower) > 0.6:
                score += 0.4
        
        if score > 0:
            results.append({
                "section_code": section_code,
                "name": rule_data.get("name"),
                "max_amount": rule_data.get("max_amount"),
                "citation": rule_data.get("citation"),
                "eligible_instruments": rule_data.get("eligible_instruments", []),
                "requires_proof": rule_data.get("requires_proof", False),
                "score": score,
            })
    
    # Sort by relevance and return top_k
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def extract_document_context(parsed_docs: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extract relevant tax context from uploaded documents.
    
    Args:
        parsed_docs: List of parsed document dictionaries with OCR data
        
    Returns:
        Dictionary with extracted tax-relevant information
    """
    context = {
        "has_salary_doc": False,
        "has_investment_doc": False,
        "has_medical_doc": False,
        "has_rent_receipt": False,
        "has_other_doc": False,
        "extracted_fields_count": 0,
        "documents_summary": "",
        "clarity_issues": [],
        "high_confidence_docs": [],
        "needs_review_docs": [],
    }
    
    if not parsed_docs:
        return context
    
    doc_summaries = []
    for doc in parsed_docs:
        doc_type = doc.get("doc_type", "other").lower()
        
        if "payslip" in doc_type or "form16" in doc_type or "salary" in doc_type:
            context["has_salary_doc"] = True
            doc_summaries.append("Salary/Form 16")
        elif "investment" in doc_type:
            context["has_investment_doc"] = True
            doc_summaries.append("Investment Proof")
        elif "medical" in doc_type or "health" in doc_type:
            context["has_medical_doc"] = True
            doc_summaries.append("Medical Bills (80D eligible)")
        elif "rent" in doc_type or "receipt" in doc_type:
            context["has_rent_receipt"] = True
            doc_summaries.append("Rent Receipt (HRA claimable)")
        else:
            context["has_other_doc"] = True
            doc_summaries.append("Other Document")
        
        # Track OCR status
        extracted = doc.get("extracted_fields", 0)
        context["extracted_fields_count"] += extracted
        
        ocr_status = doc.get("ocr_status", "")
        if ocr_status == "verified":
            context["high_confidence_docs"].append(doc.get("file_name", "document"))
        elif ocr_status == "needs_review":
            context["needs_review_docs"].append(doc.get("file_name", "document"))
        
        issues = doc.get("ocr_issues", [])
        if issues:
            context["clarity_issues"].extend(issues)
    
    context["documents_summary"] = ", ".join(set(doc_summaries))
    return context


def _is_tax_query(query: str) -> bool:
    q = (query or "").lower()
    if not q.strip():
        return True
    return any(k in q for k in TAX_KEYWORDS)


def build_tax_aware_prompt(
    user_query: str,
    parsed_docs: list[dict[str, Any]],
    conversation_history: list[dict[str, str]] | None = None,
    user_profile: dict[str, Any] | None = None,
) -> str:
    """
    Build enhanced system prompt with tax context and RAG results.
    
    Args:
        user_query: Current user message
        parsed_docs: List of uploaded document data
        conversation_history: Previous messages for context
        user_profile: User profile (age, filing status, etc.)
        
    Returns:
        Enhanced system prompt with tax and document context
    """
    if not _is_tax_query(user_query):
        return """You are TaxAI assistant.

The user asked a general (non-tax) question.
Rules:
- Answer naturally in 2-5 short sentences.
- Be accurate and concise.
- Do not force tax-section labels for non-tax questions.
- If the user then asks about tax, switch back to tax-expert mode.
- Keep tone friendly and practical."""

    base_system = """You are TaxAI, an expert Indian income-tax advisor (FY 2024-25 / AY 2025-26).

Core rules:
- Always cite the exact Income Tax Act section (e.g. 80C, 24(b), 10(13A)).
- Use concrete ₹ limits and ceilings — never hedge with "it depends" without also stating the maximum.
- Structure every substantive answer using these exact labels (one per line):
    Applicable Section: <section code(s)>
    What You Can Claim: <deduction + ₹ limit>
    Why: <brief legal rule in 1 sentence>
    Next Step: <single concrete action for this user>
    Citation: <Act, section, Finance Act year if amended>
- For greetings or purely conversational messages skip the structured format and reply naturally.
- If a critical input (salary, rent, premium, etc.) is missing, ask exactly ONE clarifying question.
- Never fabricate section numbers; if unsure, say "please verify with a CA".
- Regime choice: when comparing regimes, show which saves more tax with a ₹ figure."""

    # Add document context
    doc_context = extract_document_context(parsed_docs)
    if parsed_docs:
        base_system += f"""

DOCUMENTS UPLOADED:
- Types: {doc_context['documents_summary']}
- Total Extracted Fields: {doc_context['extracted_fields_count']}
- High Confidence Count: {len(doc_context['high_confidence_docs'])}
- Needs Review Count: {len(doc_context['needs_review_docs'])}
"""
        if doc_context["clarity_issues"]:
            base_system += f"- OCR Issues: {'; '.join(doc_context['clarity_issues'][:2])}\n"
    
    # Add user profile context
    if user_profile:
        age = user_profile.get("age")
        filing_status = user_profile.get("filing_status", "Individual")
        senior_citizen = age and age >= 60
        
        base_system += f"""

USER PROFILE:
- Filing Status: {filing_status}
- Age: {age if age else 'Not specified'}{' (Senior Citizen - 80TTB eligible)' if senior_citizen else ''}
"""
    
    # Add relevant KB results
    relevant_sections = retrieve_relevant_deductions(user_query, top_k=3)
    if relevant_sections:
        base_system += "\nRELEVANT SECTIONS FOR THIS QUERY:\n"
        for item in relevant_sections:
            base_system += f"- {item['section_code']}: {item['name']}"
            if item["max_amount"]:
                base_system += f" (Max: ₹{item['max_amount']:,})"
            base_system += f"\n  Citation: {item['citation']}\n"
            instruments = item.get("eligible_instruments", [])
            if instruments:
                base_system += f"  Eligible instruments: {', '.join(str(x) for x in instruments[:5])}\n"
    
    base_system += "\nBe precise and brief."
    
    return base_system


def build_conversation_with_context(
    user_message: str,
    parsed_docs: list[dict[str, Any]],
    conversation_history: list[dict[str, str]] | None = None,
    user_profile: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """
    Build message list for LLM with context injected as system prompt.
    
    Args:
        user_message: Current user query
        parsed_docs: Uploaded documents with OCR data
        conversation_history: Previous conversation messages
        user_profile: User profile data
        
    Returns:
        List of messages with system prompt, history, and current query
    """
    messages = [
        {
            "role": "system",
            "content": build_tax_aware_prompt(user_message, parsed_docs, conversation_history, user_profile),
        }
    ]
    
    # Add compact conversation history (last 6 turns)
    if conversation_history:
        for msg in conversation_history[-6:]:
            role = msg.get("role", "user")
            content = (msg.get("content") or "")[:400]
            messages.append({"role": role, "content": content})
    
    # Add current user message
    messages.append({"role": "user", "content": user_message})
    
    return messages


def search_kb(query: str, top_k: int = 10) -> list[dict[str, Any]]:
    """
    General KB search for tax rules, sections, amounts, etc.
    
    Args:
        query: Search query
        top_k: Number of results
        
    Returns:
        Relevant KB entries with scores
    """
    return retrieve_relevant_deductions(query, top_k=top_k)
