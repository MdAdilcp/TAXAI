from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "TaxAI"
    secret_key: str = "change-me-in-production"
    encryption_key: str | None = None

    # Google
    google_application_credentials: str | None = None
    google_cloud_project: str | None = None

    # LLM
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemini-2.0-flash-001"
    openrouter_fallback_model: str = "openai/gpt-4o-mini"
    gemini_api_key: str | None = None
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"               # primary high-quality chat model
    llm_fallback_model: str = "gpt-4o-mini"
    gemini_chat_model: str = "gemini-2.0-flash"
    gemini_fallback_model: str = "gemini-1.5-flash"
    llm_max_tokens: int = 700
    llm_temperature: float = 0.15
    chat_history_turns: int = 10
    voice_reply_model: str = "gpt-4o-mini"
    voice_reply_max_chars: int = 320
    ocr_preprocess_scans: bool = True
    ocr_provider: str = "gemini"            # auto|vision|gemini|openrouter
    ocr_enable_llm_refine: bool = True
    ocr_llm_provider: str = "openrouter"    # auto|openai|openrouter|gemini
    ocr_llm_model: str = "openai/gpt-4o-mini"
    gemini_ocr_model: str = "gemini-2.0-flash"
    ocr_max_pdf_text_pages: int = 8
    ocr_max_pdf_ocr_pages: int = 8
    ocr_max_image_variants: int = 2
    ocr_target_chars: int = 7000
    ocr_fast_accept_score: float = 108.0
    ocr_openrouter_timeout_sec: float = 18.0
    ocr_openrouter_retries: int = 1
    ocr_openrouter_max_models: int = 1

    # ERI
    eri_sandbox_base_url: str = "https://eportal.incometax.gov.in/ero/sandbox"
    eri_client_id: str = ""
    eri_client_secret: str = ""

    # PAN
    pan_verification_url: str = ""
    pan_api_key: str = ""

    # GST
    gst_gsp_base_url: str = ""

    # Translation & TTS
    translate_api: str = "google"
    tts_provider: str = "google"

    # DB
    database_url: str = "sqlite+aiosqlite:///./taxai.db"

    # Aadhaar (only if authorized)
    uidai_sandbox_url: str = ""
    uidai_aua_code: str = ""

    # Sandbox mode
    sandbox_mode: bool = True

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
