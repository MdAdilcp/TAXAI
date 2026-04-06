import { useState, useRef, useEffect } from 'react'
import type { AvatarPrompt } from './Avatar'

const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
const API_FALLBACK = (import.meta.env.VITE_API_FALLBACK_URL || '').replace(/\/$/, '')
const DEV_LOCAL_FALLBACK = 'http://127.0.0.1:8001'

type Message = { role: 'user' | 'assistant'; content: string }

async function postConversation(payload: unknown) {
  const endpoint = `${API_BASE}/api/conversation`
  const fallbackBase = API_FALLBACK || (import.meta.env.DEV ? DEV_LOCAL_FALLBACK : '')
  const fallbackEndpoint = fallbackBase ? `${fallbackBase}/api/conversation` : ''
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 25000)
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    })
    if (!res.ok) {
      throw new Error(`Primary API failed: ${res.status}`)
    }
    return await res.json()
  } catch {
    if (!fallbackEndpoint || fallbackEndpoint === endpoint) {
      throw new Error('Conversation API failed on primary endpoint')
    }
    const fallbackRes = await fetch(fallbackEndpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!fallbackRes.ok) {
      throw new Error(`Fallback API failed: ${fallbackRes.status}`)
    }
    return await fallbackRes.json()
  } finally {
    clearTimeout(timeout)
  }
}

/** Parse a structured "Label: content  OtherLabel: content" AI response into sections */
function parseStructuredResponse(text: string): Array<{ label: string; body: string }> | null {
  // Match capitalized multi-word labels followed by colon
  const labelRe = /([A-Z][A-Za-z\s()]{1,32}?):\s*/g
  const positions: Array<{ index: number; label: string }> = []
  let m: RegExpExecArray | null
  while ((m = labelRe.exec(text)) !== null) {
    positions.push({ index: m.index, label: m[1].trim() })
  }
  if (positions.length < 2) return null
  return positions.map((pos, i) => {
    const start = pos.index + pos.label.length + 1 // skip "Label:"
    const end = positions[i + 1]?.index ?? text.length
    return { label: pos.label, body: text.slice(start, end).trim() }
  })
}

const LABEL_CATEGORY: Record<string, string> = {
  'Applicable Section': 'section',
  'What You Can Claim': 'claim',
  'Why': 'why',
  'Next Step': 'step',
  'Citation': 'cite',
  'Requires': 'note',
}

function sectionCategory(label: string): string {
  for (const key of Object.keys(LABEL_CATEGORY)) {
    if (label.toLowerCase().startsWith(key.toLowerCase())) return LABEL_CATEGORY[key]
  }
  return 'default'
}

interface AssistantMessageProps { content: string }
function AssistantMessage({ content }: AssistantMessageProps) {
  const sections = parseStructuredResponse(content)
  if (!sections) {
    // Plain text — split on newlines
    return (
      <div className="chat-plain-text">
        {content.split('\n').map((line, i) =>
          line.trim() ? <p key={i}>{line}</p> : <br key={i} />
        )}
      </div>
    )
  }
  return (
    <div className="chat-structured">
      {sections.map((s, i) => (
        <div key={i} className="chat-section" data-cat={sectionCategory(s.label)}>
          <span className="chat-section-label">{s.label}</span>
          <span className="chat-section-body">{s.body}</span>
        </div>
      ))}
    </div>
  )
}

interface ConversationWidgetProps {
  onAvatarPrompt?: (prompt: AvatarPrompt | null) => void
  onSpeakingChange?: (speaking: boolean) => void
  languageHint: string
  uploadedDocs?: Array<{ file_name: string; doc_type: string; extracted_fields: number; ocr_status?: string }>
  userProfile?: { age?: number; filing_status?: string }
  /** localStorage key for persisting chat per user. When absent, history is in-memory only. */
  storageKey?: string
}

const UI_TEXT: Record<string, { 
  placeholder: string; 
  thinking: string; 
  empty: string; 
  send: string;
  voice_listen: string;
  voice_stop: string;
}> = {
  en: {
    placeholder: 'Type or click 🎤 to speak...',
    thinking: 'Thinking...',
    empty: 'Ask about tax filing, deductions, or say hello in your chosen language.',
    send: 'Send',
    voice_listen: 'Listening...',
    voice_stop: 'Stop',
  },
  hi: {
    placeholder: 'अपना प्रश्न लिखें या 🎤 दबाएं...',
    thinking: 'सोच रहा हूं...',
    empty: 'कर कटौती, फाइलिंग या कोई भी टैक्स सवाल पूछें।',
    send: 'भेजें',
    voice_listen: 'सुन रहे हैं...',
    voice_stop: 'रुकें',
  },
  ta: {
    placeholder: 'கேட்க அல்லது 🎤 அழுத்தவும்...',
    thinking: 'யோசிக்கிறேன்...',
    empty: 'வரி விலக்கு அல்லது தாக்கல் குறித்து கேளுங்கள்.',
    send: 'அனுப்பு',
    voice_listen: 'கேட்டுக்கொண்டிருக்கிறது...',
    voice_stop: 'நிற்கவும்',
  },
  te: {
    placeholder: 'టైప్ చేయండి లేదా 🎤 నొక్కండి...',
    thinking: 'ఆలోచిస్తున్నాను...',
    empty: 'పన్ను మినహాయింపు లేదా ఫైలింగ్ గురించి అడగండి.',
    send: 'పంపు',
    voice_listen: 'విన్నవుండుకుంటున్నాను...',
    voice_stop: 'ఆపండి',
  },
  kn: {
    placeholder: 'ಟೈಪ್ ಮಾಡಿ ಅಥವಾ 🎤 ಒತ್ತಿ...',
    thinking: 'ಯೋಚಿಸುತ್ತಿದ್ದೇನೆ...',
    empty: 'ತೆರಿಗೆ ಕಡಿತ ಅಥವಾ ಫೈಲಿಂಗ್ ಬಗ್ಗೆ ಕೇಳಿ.',
    send: 'ಕಳುಹಿಸು',
    voice_listen: 'ಕೇಳುತ್ತಿದ್ದೇನೆ...',
    voice_stop: 'ನಿಲ್ಲಿಸಿ',
  },
  ml: {
    placeholder: 'ടൈപ്പ് ചെയ്യുക അല്ലെങ്കിൽ 🎤 നില്....',
    thinking: 'ആലോചിക്കുന്നു...',
    empty: 'നികുതി കിഴിവ് അല്ലെങ്കിൽ ഫയലിംഗ് കുറിച്ച് ചോദിക്കൂ.',
    send: 'അയക്കുക',
    voice_listen: 'കേൾക്കുന്നു...',
    voice_stop: 'നിർത്തുക',
  },
  bn: {
    placeholder: 'লিখুন বা 🎤 ক্লিক করুন...',
    thinking: 'ভাবছি...',
    empty: 'কর ছাড় বা ফাইলিং সম্পর্কে জিজ্ঞেস করুন।',
    send: 'পাঠান',
    voice_listen: 'শুনছি...',
    voice_stop: 'থামুন',
  },
  mr: {
    placeholder: 'टाइप करा किंवा 🎤 दाबा...',
    thinking: 'विचार करत आहे...',
    empty: 'कर कपात किंवा फाइलिंगबद्दल विचारा.',
    send: 'पाठवा',
    voice_listen: 'ऐकत आहे...',
    voice_stop: 'थांबा',
  },
  gu: {
    placeholder: 'લખો અથવા 🎤 દબાવો...',
    thinking: 'વિચાર કરું છું...',
    empty: 'ટેક્સ કપાત અથવા ફાઇલિंગ વિશે પૂછો.',
    send: 'મોકલો',
    voice_listen: 'સાંભળી રહ્યો છું...',
    voice_stop: 'બંધ કરો',
  },
  pa: {
    placeholder: 'ਲਿਖੋ ਜਾਂ 🎤 ਅੱਟ ਦਬਾਓ...',
    thinking: 'ਸੋਚ ਰਿਹਾ ਹਾਂ...',
    empty: 'ਟੈਕਸ ਕਟੌਤੀ ਜਾਂ ਫਾਈਲਿੰਗ ਬਾਰੇ ਪੁੱਛੋ।',
    send: 'ਭੇਜੋ',
    voice_listen: 'ਸੁਣ ਰਿਹਾ ਹਾਂ...',
    voice_stop: 'ਰੋਕੋ',
  },
}

export function ConversationWidget({
  onAvatarPrompt,
  onSpeakingChange,
  languageHint,
  uploadedDocs,
  userProfile,
  storageKey,
}: ConversationWidgetProps) {
  const [messages, setMessages] = useState<Message[]>(() => {
    if (!storageKey) return []
    try {
      const saved = localStorage.getItem(storageKey)
      if (saved) {
        const parsed = JSON.parse(saved) as { messages?: Message[] }
        return Array.isArray(parsed.messages) ? parsed.messages : []
      }
    } catch { /* ignore */ }
    return []
  })
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(() => {
    if (!storageKey) return null
    try {
      const saved = localStorage.getItem(storageKey)
      if (saved) {
        const parsed = JSON.parse(saved) as { sessionId?: string }
        return parsed.sessionId || null
      }
    } catch { /* ignore */ }
    return null
  })
  const [isListening, setIsListening] = useState(false)
  const [voiceAvailable, setVoiceAvailable] = useState(false)
  const [isMuted, setIsMuted] = useState<boolean>(() => {
    if (!storageKey) return false
    try {
      return localStorage.getItem(`${storageKey}:mute`) === '1'
    } catch {
      return false
    }
  })
  
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const recognitionRef = useRef<any>(null)

  const stopCurrentPlayback = () => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.currentTime = 0
      audioRef.current = null
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
    onSpeakingChange?.(false)
  }

  const playAudioWithAvatar = async (src: string) => {
    stopCurrentPlayback()
    const audio = new Audio(src)
    audioRef.current = audio
    audio.onplay = () => onSpeakingChange?.(true)
    audio.onended = () => onSpeakingChange?.(false)
    audio.onerror = () => onSpeakingChange?.(false)
    await audio.play()
  }

  const speakWithBrowser = (text: string, lang: string) => {
    if (!('speechSynthesis' in window) || !text.trim()) {
      onSpeakingChange?.(false)
      return false
    }

    stopCurrentPlayback()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = `${lang || 'en'}-IN`
    const voices = window.speechSynthesis.getVoices()
    const langPrefix = (lang || 'en').toLowerCase()
    const femaleVoice = voices.find((v) => {
      const voiceLang = (v.lang || '').toLowerCase()
      const voiceName = (v.name || '').toLowerCase()
      const matchesLang = voiceLang.startsWith(langPrefix)
      const looksFemale = /female|woman|zira|heera|veena|aria|sara|natasha|raveena/.test(voiceName)
      return matchesLang && looksFemale
    })
    if (femaleVoice) {
      utterance.voice = femaleVoice
    }
    utterance.rate = 0.96
    utterance.pitch = 1
    utterance.onstart = () => onSpeakingChange?.(true)
    utterance.onend = () => onSpeakingChange?.(false)
    utterance.onerror = () => onSpeakingChange?.(false)
    window.speechSynthesis.speak(utterance)
    return true
  }

  const playAssistantReply = async (data: any) => {
    if (isMuted) {
      onSpeakingChange?.(false)
      return
    }

    const lang = data.language_responded || languageHint || 'en'
    const spokenText = (data.spoken_reply || data.reply || '').trim()

    try {
      if (data.tts_audio_data) {
        await playAudioWithAvatar(data.tts_audio_data)
        return
      }

      if (data.tts_audio_url) {
        await playAudioWithAvatar(data.tts_audio_url)
        return
      }

      const ttsUrl = `${API_BASE}/api/tts?text=${encodeURIComponent(spokenText)}&lang=${lang}`
      await playAudioWithAvatar(ttsUrl)
    } catch {
      speakWithBrowser(spokenText, lang)
    }
  }

  const waitForRender = async () => {
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  }

  const ui = UI_TEXT[languageHint] || UI_TEXT.en

  // Initialize Web Speech API
  useEffect(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (SpeechRecognition) {
      recognitionRef.current = new SpeechRecognition()
      recognitionRef.current.continuous = false
      recognitionRef.current.interimResults = true
      recognitionRef.current.lang = `${languageHint}-IN`
      
      recognitionRef.current.onstart = () => setIsListening(true)
      recognitionRef.current.onend = () => setIsListening(false)
      recognitionRef.current.onresult = (event: any) => {
        let interimTranscript = ''
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript
          if (event.results[i].isFinal) {
            setInput(prev => prev + transcript)
          } else {
            interimTranscript += transcript
          }
        }
        if (interimTranscript) {
          setInput(prev => prev.split(' ').slice(0, -1).join(' ') + ' ' + interimTranscript)
        }
      }
      recognitionRef.current.onerror = () => setIsListening(false)
      
      setVoiceAvailable(true)
    }
  }, [languageHint])

  // Persist chat history to localStorage whenever messages or sessionId change
  useEffect(() => {
    if (!storageKey) return
    try {
      localStorage.setItem(storageKey, JSON.stringify({ messages, sessionId }))
    } catch { /* storage full — ignore */ }
  }, [storageKey, messages, sessionId])

  useEffect(() => {
    if (!storageKey) return
    try {
      localStorage.setItem(`${storageKey}:mute`, isMuted ? '1' : '0')
    } catch { /* ignore */ }
  }, [storageKey, isMuted])

  useEffect(() => () => {
    stopCurrentPlayback()
  }, [])

  const scrollToBottom = () => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  useEffect(scrollToBottom, [messages])

  const toggleVoiceInput = () => {
    if (!recognitionRef.current) return
    if (isListening) {
      recognitionRef.current.stop()
      setIsListening(false)
    } else {
      recognitionRef.current.start()
    }
  }

  const toggleMute = () => {
    setIsMuted((prev) => {
      const next = !prev
      if (next) {
        stopCurrentPlayback()
      }
      return next
    })
  }

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: text }])
    setLoading(true)
    stopCurrentPlayback()
    
    try {
      // Prepare document context
      const parsedDocs = uploadedDocs?.slice(0, 4).map(doc => ({
        file_name: doc.file_name,
        doc_type: doc.doc_type,
        extracted_fields: doc.extracted_fields,
        ocr_status: doc.ocr_status,
      })) || []

      const compactHistory = messages.slice(-6).map(m => ({
        role: m.role,
        content: m.content.slice(0, 320),
      }))
      
      const data = await postConversation({
        message: text,
        session_id: sessionId,
        language_hint: languageHint,
        parsed_docs: parsedDocs,
        user_profile: userProfile ? { age: userProfile.age, filing_status: userProfile.filing_status } : undefined,
        conversation_history: compactHistory,
        enable_voice: !isMuted,
      })
      if (data.session_id) setSessionId(data.session_id)
      setMessages((m) => [...m, { role: 'assistant', content: data.reply || 'No response.' }])
      onAvatarPrompt?.(data.avatar_prompt || null)
      await waitForRender()
      await playAssistantReply(data)
    } catch {
      setMessages((m) => [...m, { role: 'assistant', content: 'Could not reach the server.' }])
      onSpeakingChange?.(false)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="chat-panel">
      <div className="chat-messages">
        {messages.length === 0 && (
          <p className="msg assistant chat-empty-msg">
            {ui.empty}
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`msg ${msg.role}`}>
            {msg.role === 'assistant'
              ? <AssistantMessage content={msg.content} />
              : msg.content}
          </div>
        ))}
        {loading && (
          <div className="msg assistant">{ui.thinking}</div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-input-wrap">
        <input
          type="text"
          placeholder={isListening ? ui.voice_listen : ui.placeholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
        />
        {voiceAvailable && (
          <button 
            type="button" 
            onClick={toggleVoiceInput}
            disabled={loading}
            title={isListening ? ui.voice_stop : '🎤 Voice input'}
            className={`voice-btn ${isListening ? 'listening' : ''}`}
          >
            🎤
          </button>
        )}
        <button
          type="button"
          onClick={toggleMute}
          disabled={loading}
          title={isMuted ? 'Unmute assistant audio' : 'Mute assistant audio'}
          className={`voice-btn ${isMuted ? 'muted' : ''}`}
        >
          {isMuted ? '🔇' : '🔊'}
        </button>
        <button type="button" onClick={sendMessage} disabled={loading}>
          {ui.send}
        </button>
      </div>
    </div>
  )
}
