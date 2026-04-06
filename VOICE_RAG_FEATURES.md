# TaxAI Voice & RAG Features Documentation

## Overview

TaxAI now includes a powerful voice-enabled, context-aware AI assistant powered by Retrieval-Augmented Generation (RAG) and tax-specific knowledge. The system provides:

1. **Voice Input/Output (Speech-to-Text & Text-to-Speech)**
2. **Context-Aware Responses** using uploaded documents
3. **Tax-Aware Responses** using knowledge base and RAG
4. **Multi-Language Support** with language-specific TTS voices

## Architecture

### Backend Components

#### 1. RAG Service (`app/services/rag_service.py`)
Retrieves relevant tax deductions and document context to enhance AI responses.

**Key Functions:**
- `retrieve_relevant_deductions(query, top_k)` - Search deduction rules by similarity
- `extract_document_context(parsed_docs)` - Extract tax-relevant info from uploaded docs
- `build_tax_aware_prompt(user_query, parsed_docs, conversation_history, user_profile)` - Build enhanced system prompt with context
- `build_conversation_with_context()` - Prepare LLM messages with RAG context

**How it works:**
1. Analyzes user query for keywords and deduction section codes
2. Retrieves matching entries from tax knowledge base (`kb/deduction_rules.json`)
3. Extracts document context (clarity, accuracy, doc types)
4. Injects context into system prompt for tax-aware AI responses

#### 2. TTS Service (`app/services/tts_service.py`)
Converts text to speech in multiple Indian languages with automatic fallback.

**Key Functions:**
- `text_to_speech(text, language_code)` - Main TTS conversion
- `synthesize_speech_google(text, language_code)` - Google Cloud TTS (primary)
- `synthesize_speech_fallback(text, language_code)` - pyttsx3 fallback

**Supported Languages:**
- English (en-IN-Standard-A)
- Hindi (hi-IN-Standard-A)
- Tamil, Telugu, Kannada, Malayalam (all -Standard-A variants)
- Bengali, Marathi, Gujarati, Punjabi

#### 3. Enhanced Conversation Service
Updated to integrate RAG and tax context.

**New Parameters:**
```python
async def converse(
    message: str,
    session_id: str | None,
    language_hint: str | None,
    intent_override: str | None,
    parsed_docs: list[dict] | None,        # NEW: Document context
    conversation_history: list[dict] | None, # NEW: Previous messages
    user_profile: dict | None,             # NEW: User age, filing status, etc.
) -> dict
```

### API Endpoints

#### POST `/api/conversation`
**Enhanced Request Body:**
```json
{
  "message": "User query text",
  "session_id": "optional-session-id",
  "language_hint": "hi|en|ta|te|kn|ml|bn|mr|gu|pa",
  "intent": "optional-intent-override",
  "parsed_docs": [
    {
      "file_name": "salary_2024.pdf",
      "doc_type": "payslip",
      "extracted_fields": 15,
      "ocr_status": "verified"
    }
  ],
  "conversation_history": [
    {"role": "user", "content": "Previous question"},
    {"role": "assistant", "content": "Previous answer"}
  ],
  "user_profile": {
    "age": 35,
    "filing_status": "Individual"
  },
  "enable_voice": true
}
```

**Response:**
```json
{
  "reply": "Tax-aware response text",
  "intent": "claim-deduction|calculate-tax|etc",
  "language_detected": "hi",
  "language_responded": "hi",
  "tts_audio_data": "data:audio/mp3;base64,...",
  "tts_audio_url": null,
  "avatar_prompt": {...},
  "session_id": "session-uuid"
}
```

#### GET `/api/tts?text=...&lang=en`
Generate TTS audio for any text.

**Returns:** MP3 audio bytes (audio/mpeg)

#### POST `/api/stt`
Convert speech to text.

**Form Data:**
- `file`: Audio file (WAV, MP3, etc.)
- `language`: Language code (default: en)

**Response:**
```json
{
  "text": "Transcribed text",
  "language": "en",
  "confidence": 0.95
}
```

### Frontend Components

#### ConversationWidget Enhancement
Added voice input/output with context awareness.

**New Props:**
```typescript
interface ConversationWidgetProps {
  languageHint: string
  onAvatarPrompt?: (prompt: AvatarPrompt | null) => void
  onSpeakingChange?: (speaking: boolean) => void
  uploadedDocs?: Array<{              // NEW
    file_name: string
    doc_type: string
    extracted_fields: number
    ocr_status?: string
  }>
  userProfile?: {                     // NEW
    age?: number
    filing_status?: string
  }
}
```

**Features:**
1. **Voice Input Button (🎤)** - Click to start/stop listening
   - Uses Web Speech API (SpeechRecognition)
   - Supports all 9 Indian languages
   - Real-time transcription with interim results
   - Animated "listening" state with pulse effect

2. **Voice Output** - Auto-plays TTS response
   - Plays base64-encoded MP3 from backend
   - Falls through to old `/api/tts` endpoint if needed
   - Language-aware voice selection

3. **Document Context** - Passes uploaded documents to backend
   - Assistant knows which documents are uploaded
   - Can reference specific doc types and clarity
   - Enables "I see your rent receipt" type responses

4. **Conversation History** - Maintains context across messages
   - Sends last 8 messages to backend
   - Backend injects history into RAG prompt
   - Better multi-turn conversation quality

## Usage Flow

### 1. User uploads documents (in DocumentUpload component)
```
- Document → OCR → Clarity/Accuracy assessment
- Stored in uploadedHistory state
- Details passed to ConversationWidget
```

### 2. User asks question with voice or text
```
- Voice: Click 🎤 → Speak → Auto-converted to text
- Text: Type → Press Enter or click Send
```

### 3. Backend processes with RAG
```
- Extract KB rules matching query keywords
- Extract document context (types, clarity, accuracy)
- Build tax-aware system prompt
- Call OpenAI GPT-4o-mini with context
- Add language instruction for non-English
```

### 4. Response generation
```
- LLM generates tax-aware response
- Backend generates TTS audio (MP3)
- Returns both text and audio_data (base64)
- Frontend plays audio automatically
```

### 5. Avatar animation
```
- If avatar enabled, shows speaking animation
- Syncs with TTS playback
- Displays in "Responding in [Language]" mode
```

## Example Query Flow

**User:** "क्या मैं 80C में निवेश से बचत कर सकता हूं?" (Can I save 80C investment?)

**Backend RAG Process:**
1. Detects Hindi language
2. Searches KB: finds Section 80C (max ₹1,50,000)
3. Extracts doc context: sees user uploaded investment proof
4. Builds system prompt including:
   - Section 80C details (eligible instruments, max, citation)
   - Document status (verified investment upload)
   - User age (if available)
5. Sends to GPT-4o-mini with context

**LLM Response (in Hindi):**
> "जी, आपके द्वारा अपलोड किए गए निवेश प्रमाण के साथ, आप धारा 80C के तहत अधिकतम ₹1,50,000 तक की कटौती प्राप्त कर सकते हैं। पात्र साधन: ELSS, PPF, EPF, NSC, LIC, आदि। [Citation: Income Tax Act 1961, Section 80C]"

**Voice Output:**
- Backend generates TTS in Hindi voice (hi-IN-Standard-A)
- Returns base64 MP3 audio
- Frontend plays automatically

## Knowledge Base Integration

Tax rules loaded from `kb/deduction_rules.json`:

```json
{
  "80C": {
    "name": "Deduction under Section 80C",
    "max_amount": 150000,
    "applicable_from": "FY 2021-22",
    "citation": "Income Tax Act 1961, Section 80C",
    "eligible_instruments": ["ELSS", "PPF", "EPF", "LIC", "ULIP", "NSC", "FD_5Y", "Tuition fees"],
    "requires_proof": true
  },
  ...
}
```

**Injected into Prompt:** Backend adds top 3 matching rules to system message, so LLM always has accurate legal citations and limits.

## Configuration

### Environment Variables

**Backend (.env or .venv):**
```bash
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json  # For Google Cloud TTS/STT/Vision
OPENAI_API_KEY=sk-...                                      # For GPT-4o-mini LLM
```

**Frontend (.env):**
```bash
VITE_API_URL=http://localhost:8001  # Backend URL
```

### Dependencies

**Backend:**
```bash
pip install google-cloud-texttospeech  # TTS voice synthesis
pip install google-cloud-speech        # STT voice recognition
pip install openai                     # GPT-4o-mini LLM
pip install pyttsx3                    # Fallback TTS (offline)
```

**Frontend:**
No additional dependencies - uses native Web Speech API

## Fallback Behavior

### TTS Fallback Chain:
1. Try Google Cloud TTS (if GOOGLE_APPLICATION_CREDENTIALS set)
2. Fall back to pyttsx3 (offline, lower quality)
3. Return None if both fail → Frontend uses `/api/tts` endpoint

### STT Fallback:
- Web Speech API on browser (no backend call for speech capture)
- Falls back to text input if STT unavailable
- Graceful degradation

### LLM Fallback:
- If no OpenAI API key: use multilingual fallback responses
- Fallback responses pre-translated to 9 Indian languages
- Always provide actionable tax advice

## Performance Considerations

### Latency:
- **Document Upload**: 2-3s (OCR processing)
- **Voice Input**: ~3-5s (speech recognition + network)
- **AI Response**: ~2-3s (LLM + TTS synthesis)
- **Total Turn**: ~7-11s (upload + ask + hear)

### Optimization:
- Conversation history limited to 8 messages to {token budget}
- Document context summarized (not full text sent)
- TTS cached by browser (replay same response = instant)
- RAG uses simple keyword matching (no embedding model)

## Troubleshooting

### Voice Input Not Working
- Check browser support (Chrome/Edge/Firefox ✓, Safari ❌)
- Verify microphone permissions granted
- Check browser console for errors
- Test with `/api/stt` endpoint directly

### TTS Audio Not Playing
- Check speaker volume and browser audio settings
- Verify CORS headers (API must allow 'audio/mpeg' response)
- Check browser console for CORS errors
- Fallback to text-only mode if needed

### Poor OCR Clarity
- Backend warns "needs_review" if confidence < threshold
- Assistant will ask for re-upload or clarification
- Use better lighting/angle for document photos

### No Tax Context in Responses
- Ensure `parsed_docs` passed to `/api/conversation`
- Check KB file exists at `kb/deduction_rules.json`
- Verify OpenAI API key set (uses GPT fallbacks otherwise)
- Check backend logs for RAG errors

## Future Enhancements

1. **Fine-tuned Model**: Train GPT on 500+ ITR samples for better accuracy
2. **Embedding-based RAG**: Replace keyword matching with semantic search
3. **STT Fallback API**: Implement backend STT using Google Speech API
4. **Audio Chunk Processing**: Stream TTS audio instead of waiting for full synthesis
5. **User Preference Profiles**: Remember user's preferred language, voice speed, etc.
6. **Multi-turn Optimization**: Smarter context window management for long conversations
7. **Document Summarization**: Use LLM to auto-summarize dense OCR text before RAG

---

**Last Updated:** March 2026  
**Version:** 2.0 (Voice + RAG)
