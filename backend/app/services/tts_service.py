"""Text-to-Speech service with multi-language support."""
import os
import io
import base64
from typing import Optional

# Language to Google Cloud TTS voice mapping
LANGUAGE_TO_VOICE = {
    "en": "en-IN-Standard-C",  # English (India) - Female
    "hi": "hi-IN-Standard-B",  # Hindi - Female
    "ta": "ta-IN-Standard-B",  # Tamil - Female
    "te": "te-IN-Standard-A",  # Telugu - Female
    "kn": "kn-IN-Standard-B",  # Kannada - Female
    "ml": "ml-IN-Standard-B",  # Malayalam - Female
    "bn": "bn-IN-Standard-A",  # Bengali - Female
    "mr": "mr-IN-Standard-B",  # Marathi - Female
    "gu": "gu-IN-Standard-B",  # Gujarati - Female
    "pa": "pa-IN-Standard-B",  # Punjabi - Female
}


def get_google_tts_voice(language_code: str) -> str:
    """Get Google Cloud TTS voice for language code."""
    return LANGUAGE_TO_VOICE.get(language_code.lower(), "en-IN-Standard-C")


async def synthesize_speech_google(
    text: str,
    language_code: str = "en",
    speaking_rate: float = 0.95,
) -> Optional[str]:
    """
    Synthesize speech using Google Cloud Text-to-Speech API.
    Returns base64-encoded audio data.
    
    Args:
        text: Text to synthesize
        language_code: Language code (en, hi, ta, etc.)
        speaking_rate: Speech rate (0.25 to 4.0)
        
    Returns:
        Base64-encoded audio content or None if failed
    """
    try:
        from google.cloud import texttospeech
    except ImportError:
        return None
    
    try:
        client = texttospeech.TextToSpeechClient()
        
        # Limit text length for API
        if len(text) > 5000:
            text = text[:5000]
        
        synthesis_input = texttospeech.SynthesisInput(text=text)
        
        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=get_google_tts_voice(language_code),
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE,
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate,
        )
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config,
        )
        
        # Return as base64 data URL
        audio_b64 = base64.b64encode(response.audio_content).decode()
        return f"data:audio/mp3;base64,{audio_b64}"
        
    except Exception as e:
        print(f"TTS Error: {e}")
        return None


async def synthesize_speech_fallback(
    text: str,
    language_code: str = "en",
) -> Optional[str]:
    """
    Fallback TTS using pyttsx3 (offline, lower quality).
    Returns base64-encoded audio data.
    """
    try:
        import pyttsx3
    except ImportError:
        return None
    
    try:
        engine = pyttsx3.init()
        
        # Set language-specific properties
        engine.setProperty("rate", 130)  # Speed
        
        # Build temporary file path
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        
        # Save to file
        engine.save_to_file(text, tmp_path)
        engine.runAndWait()
        
        # Read and encode
        with open(tmp_path, "rb") as f:
            audio_content = f.read()
        
        os.unlink(tmp_path)
        
        audio_b64 = base64.b64encode(audio_content).decode()
        return f"data:audio/mp3;base64,{audio_b64}"
        
    except Exception as e:
        print(f"Fallback TTS Error: {e}")
        return None


async def text_to_speech(
    text: str,
    language_code: str = "en",
    use_google: bool = True,
) -> Optional[str]:
    """
    Convert text to speech with automatic fallback.
    
    Args:
        text: Text to synthesize
        language_code: Language code
        use_google: Try Google Cloud TTS first
        
    Returns:
        Base64-encoded audio data URL or None
    """
    if not text or len(text.strip()) == 0:
        return None
    
    # Try Google first if enabled
    if use_google:
        result = await synthesize_speech_google(text, language_code)
        if result:
            return result
    
    # Fallback to pyttsx3
    return await synthesize_speech_fallback(text, language_code)


def extract_language_code_from_response(tts_config: dict) -> str:
    """Extract language code from TTS config."""
    voice = tts_config.get("voice", "en-IN-Standard-A")
    # Parse language from voice name (e.g., "hi-IN-Standard-A" -> "hi")
    return voice.split("-")[0]
