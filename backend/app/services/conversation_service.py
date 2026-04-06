"""LLM as NLU + response generator; translation pipeline; TTS/avatar JSON spec; RAG integration."""
import asyncio
from datetime import datetime
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import quote_plus
from typing import Any

import httpx

from app.core.config import get_settings
from app.services.rag_service import build_conversation_with_context, retrieve_relevant_deductions
from app.services.tts_service import text_to_speech

INTENTS = ["onboarding", "claim-deduction", "calculate-tax", "submit-return", "explain-why", "general"]

SYSTEM_PROMPT = """You are TaxAI, an expert Indian income-tax advisor (AY 2024-25).

Core rules:
- Always cite the exact Income Tax Act section (e.g. 80C, 24(b), 10(13A)).
- Use concrete ₹ limits and ceilings — never hedge with "it depends" without also stating the maximum.
- Structure every substantive answer using these exact labels (one per line):
    Applicable Section: <section code(s)>
    What You Can Claim: <deduction + ₹ limit>
    Why: <brief legal rule, 1 sentence>
    Next Step: <single concrete action>
    Citation: <Act, section, Finance Act year if amended>
- For greetings or purely conversational messages, skip the structured format and reply naturally.
- If a piece of information needed to answer precisely is missing, ask exactly ONE clarifying question.
- When the user writes in Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, or Punjabi, reply in that same language.
- Never fabricate section numbers; if unsure, say so and direct to a CA."""

GENERAL_CHAT_PROMPT = """You are TaxAI assistant in full general-chat mode.

Rules:
- Answer any normal general question clearly and directly.
- Keep responses concise by default (2-6 lines), unless the user asks for detail.
- Use plain language and practical examples when useful.
- If unsure, say what you know and what may be uncertain.
- Only switch to tax-structured format when the user asks tax-specific questions.
- Maintain conversational continuity with prior turns."""

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "or": "Odia",
    "as": "Assamese",
    "ur": "Urdu",
    "ks": "Kashmiri",
    "mai": "Maithili",
    "mni": "Manipuri",
    "ne": "Nepali",
    "sa": "Sanskrit",
    "sd": "Sindhi",
    "kok": "Konkani",
    "doi": "Dogri",
    "sat": "Santali",
}

FALLBACKS = {
    "onboarding": "Welcome to TaxAI. Upload documents, get deduction recommendations, and compute your tax.",
    "claim-deduction": "Upload your investment proofs. I can help with eligible sections like 80C and 80D.",
    "calculate-tax": "Use the Calculate Tax section after adding salary and deductions. I will compare old and new regimes.",
    "submit-return": "After preparing your return, proceed with submit flow. PAN and consent are required.",
    "explain-why": "Recommendations follow Income Tax Act sections and include legal references.",
    "general": "I can answer basic general questions and also help with deductions, tax calculation, and filing.",
}

_RESPONSE_CACHE: dict[str, tuple[float, str, str]] = {}
_CACHE_TTL_SEC = 90.0
_CACHE_VERSION = "v3-general"
_SESSION_HISTORY: dict[str, tuple[float, list[dict[str, str]]]] = {}
_SESSION_TTL_SEC = 1800.0


def _cache_key(
    message: str,
    language_hint: str | None,
    intent: str,
    parsed_docs: list[dict[str, Any]] | None,
    conversation_history: list[dict[str, str]] | None = None,
) -> str:
    docs_sig = ""
    if parsed_docs:
        docs_sig = "|".join(
            f"{(d.get('doc_type') or 'other')}:{(d.get('ocr_status') or 'na')}"
            for d in parsed_docs[:5]
        )
    history_sig = ""
    if conversation_history:
        history_sig = "|".join(
            f"{(m.get('role') or 'user')}:{(m.get('content') or '')[:80].strip().lower()}"
            for m in conversation_history[-3:]
        )
    return f"{_CACHE_VERSION}::{(language_hint or 'en').lower()}::{intent}::{message.strip().lower()}::{docs_sig}::{history_sig}"


def _get_cached_reply(key: str) -> tuple[str, str] | None:
    data = _RESPONSE_CACHE.get(key)
    if not data:
        return None
    ts, reply, intent = data
    if (time.time() - ts) > _CACHE_TTL_SEC:
        _RESPONSE_CACHE.pop(key, None)
        return None
    return reply, intent


def _set_cached_reply(key: str, reply: str, intent: str) -> None:
    _RESPONSE_CACHE[key] = (time.time(), reply, intent)


def _get_session_history(session_id: str | None) -> list[dict[str, str]]:
    if not session_id:
        return []
    data = _SESSION_HISTORY.get(session_id)
    if not data:
        return []
    ts, history = data
    if (time.time() - ts) > _SESSION_TTL_SEC:
        _SESSION_HISTORY.pop(session_id, None)
        return []
    return history


def _set_session_history(session_id: str, history: list[dict[str, str]]) -> None:
    _SESSION_HISTORY[session_id] = (time.time(), history)


def _merge_histories(
    stored: list[dict[str, str]],
    incoming: list[dict[str, str]] | None,
    max_turns: int,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in [*(stored or []), *((incoming or []))]:
        role = (item.get("role") or "user").strip()
        content = (item.get("content") or "").strip()
        if not content:
            continue
        key = (role, content)
        if key in seen:
            continue
        seen.add(key)
        merged.append({"role": role, "content": content})
    return merged[-max_turns:]


def _spoken_fallback(reply: str, max_chars: int) -> str:
    lines = []
    for line in (reply or "").splitlines():
        cleaned = re.sub(r"^[A-Za-z][A-Za-z\s()]{1,32}:\s*", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    spoken = " ".join(lines) if lines else (reply or "")
    spoken = re.sub(r"\s+", " ", spoken).strip()
    return spoken[:max_chars].rstrip(" ,.;:")


def _resolve_llm_provider() -> str | None:
    settings = get_settings()

    def openrouter_key() -> str | None:
        explicit = (settings.openrouter_api_key or "").strip()
        if explicit:
            return explicit
        openai_like = (settings.openai_api_key or "").strip()
        return openai_like if openai_like.startswith("sk-or-") else None

    preferred = (settings.llm_provider or "auto").strip().lower()
    openai_key = (settings.openai_api_key or "").strip()
    has_openai = bool(openai_key and not openai_key.startswith("sk-or-"))
    has_openrouter = bool(openrouter_key())
    has_gemini = bool(settings.gemini_api_key)

    if preferred == "openai":
        if has_openai:
            return "openai"
        if has_openrouter:
            return "openrouter"
        return "gemini" if has_gemini else None
    if preferred == "openrouter":
        if has_openrouter:
            return "openrouter"
        if has_openai:
            return "openai"
        return "gemini" if has_gemini else None
    if preferred == "gemini":
        if has_gemini:
            return "gemini"
        if has_openrouter:
            return "openrouter"
        return "openai" if has_openai else None
    if has_openai:
        return "openai"
    if has_openrouter:
        return "openrouter"
    if has_gemini:
        return "gemini"
    return None


def _get_openrouter_key() -> str | None:
    settings = get_settings()

    # Prefer explicit OpenRouter key from settings.
    explicit = (settings.openrouter_api_key or "").strip()
    if explicit:
        return explicit

    # Support OPENROUTER_API_KEY directly from process environment.
    env_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if env_key:
        return env_key

    # Fallback: read backend/.env so key resolution works even if process was started
    # without pydantic loading the expected env file.
    try:
        env_path = Path(__file__).resolve().parents[2] / ".env"
        if env_path.exists():
            for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == "OPENROUTER_API_KEY":
                    val = v.strip().strip('"').strip("'")
                    if val:
                        return val
                    break
    except Exception:
        # Non-fatal fallback path; continue to OpenAI-like key detection.
        pass

    # Legacy compatibility: allow sk-or-* in OPENAI_API_KEY.
    openai_like = (settings.openai_api_key or "").strip()
    return openai_like if openai_like.startswith("sk-or-") else None


def _flatten_messages_for_gemini(messages: list[dict[str, str]]) -> tuple[str | None, str]:
    system_parts: list[str] = []
    convo_parts: list[str] = []
    for msg in messages:
        role = (msg.get("role") or "user").lower().strip()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        speaker = "Assistant" if role == "assistant" else "User"
        convo_parts.append(f"{speaker}: {content}")
    return ("\n\n".join(system_parts) or None), "\n".join(convo_parts)


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    content = (candidates[0] or {}).get("content") or {}
    parts = content.get("parts") or []
    out: list[str] = []
    for part in parts:
        text = (part or {}).get("text")
        if text:
            out.append(text)
    return "\n".join(out).strip()


async def _gemini_chat_completion(
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float,
) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        return ""

    system_instruction, transcript = _flatten_messages_for_gemini(messages)
    if not transcript:
        return ""

    prompt = (
        "Continue this conversation naturally and answer the user's latest message.\n"
        "Keep context from previous turns and be direct.\n\n"
        f"{transcript}"
    )
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "maxOutputTokens": int(max_tokens),
        },
    }
    if system_instruction:
        body["system_instruction"] = {"parts": [{"text": system_instruction}]}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={settings.gemini_api_key}"
    async with httpx.AsyncClient(timeout=14.0) as client:
        resp = await client.post(url, json=body)
        if resp.status_code >= 400:
            raise RuntimeError(f"Gemini error: {resp.status_code}")
        return _extract_gemini_text(resp.json())


async def _voice_reply_from_text(
    reply: str,
    language_hint: str | None,
    intent: str,
) -> str:
    settings = get_settings()
    max_chars = max(120, int(settings.voice_reply_max_chars or 320))
    if not reply:
        return ""

    provider = _resolve_llm_provider()
    if not provider:
        return _spoken_fallback(reply, max_chars)

    try:
        language_name = LANGUAGE_NAMES.get((language_hint or "en").lower(), language_hint or "English")
        prompt_messages = [
            {
                "role": "system",
                "content": (
                    f"Rewrite the answer into natural spoken {language_name}. "
                    "Keep it to 2-4 short sentences. Preserve key section codes and ₹ amounts. "
                    "Do not use labels like Applicable Section or Citation."
                ),
            },
            {
                "role": "user",
                "content": f"Intent: {intent}\n\nAnswer to rewrite:\n{reply}",
            },
        ]

        if provider == "gemini":
            model = settings.gemini_fallback_model or settings.gemini_chat_model
            content = await _gemini_chat_completion(prompt_messages, model, 140, 0.2)
            return (content[:max_chars].rstrip() if content else _spoken_fallback(reply, max_chars))

        from openai import AsyncOpenAI

        if provider == "openrouter":
            client = AsyncOpenAI(
                api_key=_get_openrouter_key(),
                base_url=settings.openrouter_base_url,
            )
            model_name = settings.openrouter_fallback_model or settings.openrouter_model or settings.llm_fallback_model
        else:
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            model_name = settings.voice_reply_model or settings.llm_fallback_model

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=model_name,
                max_tokens=140,
                temperature=0.2,
                messages=prompt_messages,
            ),
            timeout=8.0,
        )
        content = (response.choices[0].message.content or "").strip()
        return content[:max_chars].rstrip() or _spoken_fallback(reply, max_chars)
    except Exception:
        return _spoken_fallback(reply, max_chars)


def _fast_tax_reply(user_message: str, language_hint: str | None, intent: str) -> str | None:
    """Return a structured reply from KB when no LLM key is available or as a quick path."""
    lang = (language_hint or "en").lower()
    if lang != "en":
        return None
    if intent not in {"claim-deduction", "calculate-tax", "explain-why"}:
        return None

    sections = retrieve_relevant_deductions(user_message, top_k=3)
    if not sections:
        return None

    lines: list[str] = []
    # Primary section — full structured block
    primary = sections[0]
    p_code = primary.get("section_code", "N/A")
    p_name = primary.get("name", "Deduction")
    p_max  = primary.get("max_amount")
    p_cite = primary.get("citation", "Income Tax Act 1961")
    p_proof = primary.get("requires_proof", False)
    amount_line = f"Up to ₹{p_max:,}" if isinstance(p_max, int) else "Limit per eligibility"
    proof_note  = " — proof documents required." if p_proof else "."

    lines.append(f"Applicable Section: {p_code}")
    lines.append(f"What You Can Claim: {p_name}. {amount_line}{proof_note}")
    lines.append(f"Why: {p_code} allows this deduction under the Income Tax Act.")
    lines.append(f"Next Step: Upload supporting documents and run Calculate Tax for exact savings.")
    lines.append(f"Citation: {p_cite}")

    # Related sections (2nd, 3rd) appended as a note
    if len(sections) > 1:
        related = ", ".join(
            f"{s['section_code']} ({s['name']}, max ₹{s['max_amount']:,})"
            if isinstance(s.get('max_amount'), int)
            else f"{s['section_code']} ({s['name']})"
            for s in sections[1:]
        )
        lines.append(f"Related Sections: {related}")

    return "\n".join(lines)

# Real translated fallbacks for major Indian languages (no API required)
MULTILINGUAL_FALLBACKS: dict[str, dict[str, str]] = {
    "hi": {
        "onboarding":      "TaxAI में आपका स्वागत है। दस्तावेज़ अपलोड करें और कटौती की सिफारिशें पाएं।",
        "claim-deduction": "निवेश प्रमाण अपलोड करें। धारा 80C और 80D में सहायता मिलेगी।",
        "calculate-tax":   "वेतन और कटौती दर्ज करने के बाद पुरानी व नई कर व्यवस्था की तुलना होगी।",
        "submit-return":   "रिटर्न तैयार करने के बाद सबमिट करें। PAN और सहमति ज़रूरी है।",
        "explain-why":     "सिफारिशें आयकर अधिनियम की धाराओं पर आधारित हैं।",
        "general":         "मैं कर कटौती, गणना और फाइलिंग में मदद कर सकता हूं। आप क्या जानना चाहते हैं?",
    },
    "ta": {
        "onboarding":      "TaxAI-ல் வரவேற்கிறோம். ஆவணங்கள் பதிவேற்றி விலக்கு பரிந்துரைகள் பெறுங்கள்.",
        "claim-deduction": "முதலீட்டு சான்றுகளை பதிவேற்றவும். 80C, 80D பிரிவுகளில் உதவி கிடைக்கும்.",
        "calculate-tax":   "சம்பளம் மற்றும் விலக்குகள் உள்ளிட்டு பழைய-புதிய ஆட்சி ஒப்பீடு பெறுங்கள்.",
        "submit-return":   "வருமான வரி அறிக்கை தயாரித்து சமர்ப்பிக்கவும். PAN தேவை.",
        "explain-why":     "பரிந்துரைகள் வருமான வரி சட்ட பிரிவுகளை அடிப்படையாக கொண்டவை.",
        "general":         "வரி விலக்கு, கணக்கீடு மற்றும் தாக்கல் குறித்து உதவ முடியும். என்ன தெரிந்துகொள்ள விரும்புகிறீர்கள்?",
    },
    "te": {
        "onboarding":      "TaxAI కి స్వాగతం. పత్రాలు అప్లోడ్ చేసి మినహాయింపు సూచనలు పొందండి.",
        "claim-deduction": "పెట్టుబడి రుజువులు అప్లోడ్ చేయండి. 80C, 80D సిఫారసులు పొందండి.",
        "calculate-tax":   "జీతం మరియు మినహాయింపులు నమోదు చేసి పాత-కొత్త పథకం పోల్చండి.",
        "submit-return":   "రిటర్న్ సిద్ధం చేసిన తర్వాత సబ్మిట్ చేయండి. PAN అవసరం.",
        "explain-why":     "సూచనలు ఆదాయపు పన్ను చట్టం ప్రకారం ఉంటాయి.",
        "general":         "పన్ను మినహాయింపు, లెక్కింపు, ఫైలింగ్ విషయంలో సహాయం చేయగలను.",
    },
    "kn": {
        "onboarding":      "TaxAI ಗೆ ಸ್ವಾಗತ. ದಾಖಲೆಗಳನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ, ಕಡಿತ ಶಿಫಾರಸುಗಳನ್ನು ಪಡೆಯಿರಿ.",
        "claim-deduction": "ಹೂಡಿಕೆ ಪುರಾವೆಗಳನ್ನು ಅಪ್‌ಲೋಡ್ ಮಾಡಿ. 80C, 80D ಅಡಿಯಲ್ಲಿ ಸಹಾಯ ಮಾಡಲಾಗುವುದು.",
        "calculate-tax":   "ವೇತನ ಮತ್ತು ಕಡಿತಗಳನ್ನು ನಮೂದಿಸಿ ಹಳೆ-ಹೊಸ ವ್ಯವಸ್ಥೆ ಹೋಲಿಸಿ.",
        "submit-return":   "ರಿಟರ್ನ್‌ ತಯಾರಿಸಿದ ನಂತರ ಸಲ್ಲಿಸಿ. PAN ಅಗತ್ಯ.",
        "explain-why":     "ಶಿಫಾರಸುಗಳು ಆದಾಯ ತೆರಿಗೆ ಕಾಯ್ದೆ ವಿಭಾಗಗಳನ್ನು ಅನುಸರಿಸುತ್ತವೆ.",
        "general":         "ತೆರಿಗೆ ಕಡಿತ, ಲೆಕ್ಕಾಚಾರ ಮತ್ತು ಫೈಲಿಂಗ್ ಬಗ್ಗೆ ಸಹಾಯ ಮಾಡಬಲ್ಲೆ.",
    },
    "ml": {
        "onboarding":      "TaxAI-ലേക്ക് സ്വാഗതം. രേഖകൾ അപ്‌ലോഡ് ചെയ്ത് കിഴിവ് നിർദ്ദേശങ്ങൾ നേടൂ.",
        "claim-deduction": "നിക്ഷേപ തെളിവുകൾ അപ്‌ലോഡ് ചെയ്യൂ. 80C, 80D വകുപ്പുകളിൽ സഹായം.",
        "calculate-tax":   "ശമ്പളവും കിഴിവുകളും നൽകി പഴയ-പുതിയ സ്കീം താരതമ്യം ചെയ്യൂ.",
        "submit-return":   "റിട്ടേൺ തയ്യാറാക്കിയ ശേഷം സമർപ്പിക്കൂ. PAN ആവശ്യമാണ്.",
        "explain-why":     "ശുപാർശകൾ ആദായ നികുതി നിയമ വകുപ്പുകൾ പ്രകാരമാണ്.",
        "general":         "നികുതി കിഴിവ്, കണക്കുകൂട്ടൽ, ഫയലിംഗ് എന്നിവയിൽ സഹായിക്കാം.",
    },
    "bn": {
        "onboarding":      "TaxAI-এ স্বাগতম। নথি আপলোড করুন এবং কর ছাড়ের সুপারিশ পান।",
        "claim-deduction": "বিনিয়োগের প্রমাণ আপলোড করুন। ৮০সি ও ৮০ডি ধারায় সহায়তা পাবেন।",
        "calculate-tax":   "বেতন ও ছাড় যোগ করে পুরনো-নতুন কর ব্যবস্থার তুলনা করুন।",
        "submit-return":   "রিটার্ন তৈরির পর জমা দিন। প্যান ও সম্মতি আবশ্যক।",
        "explain-why":     "সুপারিশগুলি আয়কর আইনের ধারা অনুযায়ী।",
        "general":         "কর ছাড়, গণনা ও ফাইলিং বিষয়ে সাহায্য করতে পারি।",
    },
    "mr": {
        "onboarding":      "TaxAI मध्ये स्वागत आहे. कागदपत्रे अपलोड करा, कपातीच्या शिफारसी मिळवा.",
        "claim-deduction": "गुंतवणूक पुरावे अपलोड करा. ८०सी व ८०डी प्रकरणांत मदत होईल.",
        "calculate-tax":   "पगार व कपाती नोंदवून जुनी व नवी करप्रणाली तुलना करा.",
        "submit-return":   "रिटर्न तयार केल्यावर सबमिट करा. PAN व संमती आवश्यक आहे.",
        "explain-why":     "शिफारसी आयकर कायद्याच्या कलमांनुसार आहेत.",
        "general":         "कर कपात, गणना आणि फाइलिंगसाठी मदद करू शकतो.",
    },
    "gu": {
        "onboarding":      "TaxAI માં આપનું સ્વાગત છે. દસ્તાવેજ અપલોડ કરો, કપાત ભલામણ મેળવો.",
        "claim-deduction": "રોકાણ પ્રૂફ અપલોડ કરો. 80C, 80D વિભાગ માટે મદ‍દ મળશે.",
        "calculate-tax":   "પગાર અને કપાત ઉમેરી જૂની-નવી ટેક્સ વ્યવસ્થા સરખામણ કરો.",
        "submit-return":   "રિટર્ન તૈયાર કર્યા પછી સબમિટ કરો. PAN જ‍રૂ‍રી છે.",
        "explain-why":     "ભલામણો આવકવેરા કાયદાની કલમો મુ‍જ‍બ છે.",
        "general":         "ટેક્સ કપાત, ગ‍ણ‍ત‍રી અ‍ને ફ‍ા‍ઇ‍લ‍િ‍ં‍ગ ‍માટ‍ે ‍મ‍દ‍દ ‍ક‍ર‍ી ‍શ‍ક‍ું ‍છ‍ું.",
    },
    "pa": {
        "onboarding":      "TaxAI ਵਿੱਚ ਜੀ ਆਇਆਂ। ਦਸਤਾਵੇਜ਼ ਅਪਲੋਡ ਕਰੋ, ਕਟੌਤੀ ਸਿਫਾਰਸ਼ਾਂ ਪ੍ਰਾਪਤ ਕਰੋ।",
        "claim-deduction": "ਨਿਵੇਸ਼ ਸਬੂਤ ਅਪਲੋਡ ਕਰੋ। 80C, 80D ਤਹਿਤ ਮਦਦ ਮਿਲੇਗੀ।",
        "calculate-tax":   "ਤਨਖਾਹ ਅਤੇ ਕਟੌਤੀ ਦਰਜ ਕਰਕੇ ਪੁਰਾਣੀ-ਨਵੀਂ ਵਿਵਸਥਾ ਤੁਲਨਾ ਕਰੋ।",
        "submit-return":   "ਰਿਟਰਨ ਤਿਆਰ ਕਰਨ ਤੋਂ ਬਾਅਦ ਜਮ੍ਹਾਂ ਕਰੋ। PAN ਜ਼ਰੂਰੀ ਹੈ।",
        "explain-why":     "ਸਿਫਾਰਸ਼ਾਂ ਆਮਦਨ ਕਰ ਐਕਟ ਦੀਆਂ ਧਾਰਾਵਾਂ ਮੁਤਾਬਕ ਹਨ।",
        "general":         "ਟੈਕਸ ਕਟੌਤੀ, ਹਿਸਾਬ ਅਤੇ ਫਾਈਲਿੰਗ ਲਈ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ।",
    },
}


def _normalize_language_code(language: str | None) -> str:
    if not language:
        return "en"
    raw = language.strip().lower().replace("_", "-")
    if not raw:
        return "en"
    if raw in LANGUAGE_NAMES:
        return raw

    aliases = {
        "english": "en",
        "hindi": "hi",
        "tamil": "ta",
        "telugu": "te",
        "kannada": "kn",
        "malayalam": "ml",
        "bengali": "bn",
        "marathi": "mr",
        "gujarati": "gu",
        "punjabi": "pa",
    }
    if raw in aliases:
        return aliases[raw]

    base = raw.split("-")[0]
    if base in LANGUAGE_NAMES:
        return base
    return "en"


def _detect_language(text: str) -> str:
    if not text or len(text.strip()) < 2:
        return "en"

    script_ranges = [
        (0x0D00, 0x0D7F, "ml"),  # Malayalam
        (0x0B80, 0x0BFF, "ta"),  # Tamil
        (0x0C00, 0x0C7F, "te"),  # Telugu
        (0x0C80, 0x0CFF, "kn"),  # Kannada
        (0x0900, 0x097F, "hi"),  # Devanagari
        (0x0980, 0x09FF, "bn"),  # Bengali / Assamese
        (0x0A00, 0x0A7F, "pa"),  # Gurmukhi
        (0x0A80, 0x0AFF, "gu"),  # Gujarati
    ]

    for ch in text:
        code = ord(ch)
        for low, high, lang in script_ranges:
            if low <= code <= high:
                return lang
    return "en"


def _resolve_response_language(message: str, language_hint: str | None) -> tuple[str, str]:
    detected = _detect_language(message)
    hinted = _normalize_language_code(language_hint)
    if detected != "en":
        return detected, detected
    if hinted:
        return hinted, detected
    return "en", detected


async def _translate_to_target(text: str, target_lang: str) -> str:
    if target_lang == "en" or not text:
        return text
    settings = get_settings()
    if settings.translate_api != "google" or not settings.google_cloud_project:
        return text
    try:
        from google.cloud import translate_v2 as translate
        client = translate.Client()
        out = client.translate(text, target_language=target_lang)
        return out.get("translatedText", text)
    except Exception:
        return text


def _classify_intent(text: str) -> str:
    t = text.lower()

    # Treat explicit question-form inputs as conversational/general queries first.
    if "?" in t:
        return "general"
    
    # Check for general knowledge questions first (these should be answered by Gemini directly)
    general_chat_terms = [
        "what is", "who is", "tell me about", "explain", "summarize", "write", "draft",
        "email", "code", "python", "javascript", "story", "joke", "weather", "news",
        "time", "date", "translate", "meaning", "general",
    ]
    if any(term in t for term in general_chat_terms):
        return "general"
    
    # Tax context terms (but not just bare "tax" - needs action verb)
    tax_context_terms = [
        "income tax", "itr", "deduction", "regime", "section", "refund", "tds", "pan",
        "80c", "80d", "80g", "hra", "form 16", "assessment year", "finance act",
    ]
    has_tax_context = any(term in t for term in tax_context_terms)

    if any(x in t for x in ["start", "hello", "hi ", "hey", "help me", "onboard", "get started", "new user"]):
        return "onboarding"
    if any(x in t for x in [
        "deduction", "80c", "80d", "80g", "80e", "80ee", "80tta", "80ttb",
        "claim", "invest", "ppf", "elss", "nps", "hra", "house rent",
        "medical", "health insurance", "premium", "education loan", "donation",
        "home loan", "interest", "section 24", "save tax",
    ]):
        return "claim-deduction"
    if has_tax_context and any(x in t for x in [
        "calculate", "how much tax", "tax liability", "regime", "old regime",
        "new regime", "slab", "surcharge", "cess", "net tax", "total tax",
        "rebate", "87a", "total income",
    ]):
        return "calculate-tax"
    if has_tax_context and any(x in t for x in [
        "submit", "file", "itr", "return", "form 16", "acknowledgement",
        "e-verify", "xml", "deadline", "due date", "belated",
    ]):
        return "submit-return"
    if has_tax_context and any(x in t for x in [
        "why", "explain", "citation", "legal", "basis", "rule", "act",
        "income tax act", "finance act", "notification",
    ]):
        return "explain-why"
    return "general"


def _fallback_reply(intent: str, language_hint: str | None) -> str:
    lang = (language_hint or "en").lower()
    # Use real translated response if available for this language
    if lang != "en" and lang in MULTILINGUAL_FALLBACKS:
        lang_replies = MULTILINGUAL_FALLBACKS[lang]
        return lang_replies.get(intent, lang_replies["general"])
    # English or unsupported language
    return FALLBACKS.get(intent, FALLBACKS["general"])


def _basic_general_fallback(message: str, language_hint: str | None) -> str | None:
    """Handle simple non-tax/general queries when no LLM key is available."""
    m = (message or "").strip().lower()
    if not m:
        return None

    capital_match = re.search(r"(?:what is\s+)?(?:the\s+)?capital of\s+([a-zA-Z\s\.]+)\??$", m)
    if capital_match:
        country = re.sub(r"\s+", " ", capital_match.group(1)).strip(" .?")
        capitals = {
            "india": "New Delhi",
            "united states": "Washington, D.C.",
            "usa": "Washington, D.C.",
            "united kingdom": "London",
            "uk": "London",
            "france": "Paris",
            "germany": "Berlin",
            "japan": "Tokyo",
            "china": "Beijing",
            "canada": "Ottawa",
            "australia": "Canberra",
            "italy": "Rome",
            "spain": "Madrid",
            "russia": "Moscow",
            "brazil": "Brasília",
            "south africa": "Pretoria (administrative), Cape Town (legislative), Bloemfontein (judicial)",
            "uae": "Abu Dhabi",
            "united arab emirates": "Abu Dhabi",
            "singapore": "Singapore",
        }
        answer = capitals.get(country)
        if answer:
            return f"The capital of {country.title()} is {answer}."
        return f"I’m not fully sure for {country.title()} offline. If you want, I can still give a best-effort answer if web lookup is available."

    if any(g in m for g in ["hello", "hi", "hey", "good morning", "good evening"]):
        return "Hi! I can answer general questions and also help with tax filing, deductions, and regime comparison."

    if "your name" in m or "who are you" in m:
        return "I'm TaxAI, your assistant for general queries and Indian income tax guidance."

    if "time" in m:
        now = datetime.now().strftime("%I:%M %p")
        return f"Current local time is {now}."

    if "date" in m or "today" in m:
        today = datetime.now().strftime("%d %B %Y")
        return f"Today's date is {today}."

    if "what can you do" in m or "help" in m:
        return (
            "I can answer basic general questions, and for tax I can help with deductions, old vs new regime comparison, "
            "document-based extraction, and filing guidance."
        )

    if "photosynthesis" in m:
        return (
            "Photosynthesis is the process by which plants use sunlight, water, and carbon dioxide to make glucose "
            "(food) and release oxygen."
        )

    if "gravity" in m:
        return "Gravity is the force that attracts objects with mass toward each other, like Earth pulling us to the ground."

    if "artificial intelligence" in m or m == "ai" or "what is ai" in m:
        return "AI is software that can learn patterns and perform tasks like language understanding, prediction, and decision support."

    math_match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([+\-*/])\s*(\d+(?:\.\d+)?)\s*", m)
    if math_match:
        left = float(math_match.group(1))
        op = math_match.group(2)
        right = float(math_match.group(3))
        if op == "+":
            out = left + right
        elif op == "-":
            out = left - right
        elif op == "*":
            out = left * right
        else:
            if right == 0:
                return "Division by zero is not defined."
            out = left / right
        return f"Answer: {out:g}"

    if m.startswith("what is ") or m.startswith("who is ") or m.startswith("explain "):
        topic = re.sub(r"^(what is|who is|explain)\s+", "", m).strip(" ?.")
        if topic:
            if m.startswith("who is "):
                return (
                    f"{topic.title()} is known for important contributions in their field. "
                    f"In short: who they are, what they contributed, and why it matters today. "
                    f"Ask 'explain {topic} in 3 points' for a tighter summary."
                )
            return (
                f"{topic.title()} can be understood in three parts: meaning, how it works, and why it matters. "
                f"If you want, ask 'explain {topic} with examples' and I’ll answer in a clearer step format."
            )

    cleaned = re.sub(r"\s+", " ", m).strip(" ?.!")
    if cleaned:
        if cleaned.endswith("?"):
            cleaned = cleaned[:-1].strip()
        return f"{cleaned.title()}: I can give a short overview and practical pointers. Ask 'explain {cleaned} in 3 points' for a structured answer."

    return "Ask me any general question directly, and I’ll answer concisely with practical detail."


async def _general_knowledge_lookup(message: str) -> str | None:
    """Best-effort web knowledge fallback for general chat when no LLM key is available."""
    query = (message or "").strip()
    if not query:
        return None

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            # DuckDuckGo instant answer API (no key)
            url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_html=1&skip_disambig=1"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                abstract = (data.get("AbstractText") or "").strip()
                heading = (data.get("Heading") or "").strip()
                if abstract:
                    if heading:
                        return f"{heading}: {abstract}"
                    return abstract

            # Wikipedia summary fallback
            title = re.sub(r"^(what is|who is|explain|tell me about)\s+", "", query, flags=re.I).strip(" ?.!")
            if title:
                wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote_plus(title)}"
                wiki_resp = await client.get(wiki_url, headers={"accept": "application/json"})
                if wiki_resp.status_code == 200:
                    w = wiki_resp.json()
                    extract = (w.get("extract") or "").strip()
                    if extract:
                        return extract
    except Exception:
        return None

    return None


async def _llm_response(
    user_message: str,
    intent: str | None,
    language_hint: str | None,
    parsed_docs: list[dict[str, Any]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    user_profile: dict[str, Any] | None = None,
) -> tuple[str, str]:
    settings = get_settings()
    provider = _resolve_llm_provider()
    resolved_intent = intent or _classify_intent(user_message)
    cache_key = _cache_key(user_message, language_hint, resolved_intent, parsed_docs, conversation_history)

    cached = _get_cached_reply(cache_key)
    if cached:
        if not (resolved_intent == "general" and cached[0] == FALLBACKS["general"]):
            return cached

    fast = _fast_tax_reply(user_message, language_hint, resolved_intent)
    if fast:
        _set_cached_reply(cache_key, fast, resolved_intent)
        return fast, resolved_intent

    if not provider:
        if resolved_intent == "general":
            looked_up = await _general_knowledge_lookup(user_message)
            if looked_up:
                _set_cached_reply(cache_key, looked_up, resolved_intent)
                return looked_up, resolved_intent
            general = _basic_general_fallback(user_message, language_hint)
            if general:
                out = general
                if language_hint and language_hint != "en":
                    out = await _translate_to_target(general, language_hint)
                _set_cached_reply(cache_key, out, resolved_intent)
                return out, resolved_intent
        base = _fallback_reply(resolved_intent, language_hint)
        if language_hint and language_hint != "en":
            translated = await _translate_to_target(base, language_hint)
            out = (translated or base)
            _set_cached_reply(cache_key, out, resolved_intent)
            return out, resolved_intent
        _set_cached_reply(cache_key, base, resolved_intent)
        return base, resolved_intent

    try:
        language_name = LANGUAGE_NAMES.get((language_hint or "").lower(), language_hint or "English")
        lang_instruction = f" Respond in {language_name}." if language_hint and language_hint != "en" else ""

        if resolved_intent == "general":
            messages = [{"role": "system", "content": GENERAL_CHAT_PROMPT + lang_instruction}]
            if conversation_history:
                for msg in conversation_history[-8:]:
                    role = msg.get("role", "user")
                    content = (msg.get("content") or "")[:500]
                    if content:
                        messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": user_message})
        else:
            # Tax mode uses RAG-enhanced context
            messages = build_conversation_with_context(
                user_message,
                parsed_docs or [],
                conversation_history,
                user_profile,
            )
            if lang_instruction and messages:
                messages[0]["content"] += lang_instruction
            if resolved_intent and messages:
                messages[0]["content"] += f"\n\nDetected intent: {resolved_intent}"
                messages[0]["content"] += "\nVoice interaction may be enabled, so keep answers clear, natural, and easy to read aloud."

        if provider == "gemini":
            primary_model = settings.gemini_chat_model or "gemini-2.0-flash"
            fallback_model = settings.gemini_fallback_model or primary_model
            try:
                reply = await _gemini_chat_completion(
                    messages,
                    primary_model,
                    settings.llm_max_tokens,
                    settings.llm_temperature,
                )
            except Exception:
                reply = await _gemini_chat_completion(
                    messages,
                    fallback_model,
                    min(settings.llm_max_tokens, 520),
                    settings.llm_temperature,
                )
        elif provider == "openrouter":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=_get_openrouter_key(),
                base_url=settings.openrouter_base_url,
            )
            primary_model = settings.openrouter_model or settings.llm_model
            fallback_model = settings.openrouter_fallback_model or primary_model
            try:
                r = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=primary_model,
                        messages=messages,
                        max_tokens=settings.llm_max_tokens,
                        temperature=settings.llm_temperature,
                    ),
                    timeout=14.0,
                )
            except Exception:
                r = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=fallback_model,
                        messages=messages,
                        max_tokens=min(settings.llm_max_tokens, 520),
                        temperature=settings.llm_temperature,
                    ),
                    timeout=14.0,
                )
            reply = (r.choices[0].message.content or "").strip()
        else:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            try:
                r = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=settings.llm_model,
                        messages=messages,
                        max_tokens=settings.llm_max_tokens,
                        temperature=settings.llm_temperature,
                    ),
                    timeout=14.0,
                )
            except Exception:
                r = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=settings.llm_fallback_model,
                        messages=messages,
                        max_tokens=min(settings.llm_max_tokens, 520),
                        temperature=settings.llm_temperature,
                    ),
                    timeout=14.0,
                )
            reply = (r.choices[0].message.content or "").strip()

        if not reply:
            raise RuntimeError("Empty LLM response")
        _set_cached_reply(cache_key, reply, resolved_intent)
        return reply, resolved_intent
    except Exception:
        if resolved_intent == "general":
            # For general questions, return Gemini's answer if available, otherwise return error
            looked_up = await _general_knowledge_lookup(user_message)
            if looked_up:
                _set_cached_reply(cache_key, looked_up, resolved_intent)
                return looked_up, resolved_intent
            # Skip formatted fallback for general—just return simple response
            simple_reply = "I couldn't find a direct answer. Try asking differently or visit a search engine."
            _set_cached_reply(cache_key, simple_reply, resolved_intent)
            return simple_reply, resolved_intent

        fallback = _fallback_reply(resolved_intent, language_hint)
        _set_cached_reply(cache_key, fallback, resolved_intent)
        return fallback, resolved_intent


def build_avatar_prompt(reply: str, language: str, intent: str) -> dict[str, Any]:
    return {
        "text": reply,
        "language": language,
        "intent": intent,
        "tts": {
            "provider": "google",
            "voice": "hi-IN-Standard-B" if language == "hi" else "en-IN-Standard-C",
            "text": reply,
        },
        "avatar": {
            "expression": "neutral" if intent == "general" else "helpful",
            "gesture": "explaining" if intent in {"claim-deduction", "calculate-tax", "explain-why"} else "idle",
        },
    }


async def converse(
    message: str,
    session_id: str | None,
    language_hint: str | None,
    intent_override: str | None,
    parsed_docs: list[dict[str, Any]] | None = None,
    conversation_history: list[dict[str, str]] | None = None,
    user_profile: dict[str, Any] | None = None,
    enable_voice: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    resolved_session_id = session_id or str(uuid.uuid4())
    stored_history = _get_session_history(resolved_session_id)
    effective_history = _merge_histories(stored_history, conversation_history, settings.chat_history_turns)
    lang_responded, lang_detected = _resolve_response_language(message, language_hint)
    reply, intent = await _llm_response(
        message,
        intent_override,
        lang_responded,
        parsed_docs=parsed_docs,
        conversation_history=effective_history,
        user_profile=user_profile,
    )
    updated_history = [
        *effective_history,
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ][-settings.chat_history_turns:]
    _set_session_history(resolved_session_id, updated_history)

    spoken_reply = await _voice_reply_from_text(reply, lang_responded, intent) if enable_voice else None
    tts_audio_data = None
    if enable_voice and spoken_reply:
        tts_audio_data = await text_to_speech(spoken_reply, lang_responded)

    avatar_prompt = build_avatar_prompt(spoken_reply or reply, lang_responded, intent)
    return {
        "reply": reply,
        "spoken_reply": spoken_reply,
        "intent": intent,
        "language_detected": lang_detected,
        "language_responded": lang_responded,
        "tts_audio_url": None,
        "tts_audio_data": tts_audio_data,
        "avatar_prompt": avatar_prompt,
        "session_id": resolved_session_id,
    }
