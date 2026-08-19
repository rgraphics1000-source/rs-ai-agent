import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings:
    PROJECT_NAME: str = "RS_AI Agent"
    VERSION: str = "1.0.0"
    
    # Base Directories
    BASE_DIR: Path = BASE_DIR
    STATIC_DIR: Path = BASE_DIR / "static"
    TEMPLATES_DIR: Path = BASE_DIR / "templates"
    UPLOADS_DIR: Path = BASE_DIR / "static" / "uploads"
    AUDIO_DIR: Path = BASE_DIR / "static" / "audio"
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/rs_ai.db")
    
    # Gemini AI
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # Meta & Facebook Graph API
    META_APP_ID: str = os.getenv("META_APP_ID") or "1274136137801052"
    META_EMBEDDED_SIGNUP_CONFIG_ID: str = os.getenv("META_EMBEDDED_SIGNUP_CONFIG_ID") or "10034031760860138"
    FB_PAGE_ACCESS_TOKEN: str = os.getenv("FB_PAGE_ACCESS_TOKEN", "")
    FB_VERIFY_TOKEN: str = os.getenv("FB_VERIFY_TOKEN", "rs_secure_verify_token_2026")
    FB_PAGE_ID: str = os.getenv("FB_PAGE_ID", "")
    FB_APP_SECRET: str = os.getenv("FB_APP_SECRET", "")
    
    # WhatsApp Cloud API & Coexistence
    META_SYSTEM_USER_ACCESS_TOKEN: str = os.getenv("META_SYSTEM_USER_ACCESS_TOKEN", "")
    WHATSAPP_WABA_ID: str = os.getenv("WHATSAPP_WABA_ID", "27905447135785944")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "rs_whatsapp_token_2026")
    WHATSAPP_DISPLAY_PHONE_NUMBER: str = os.getenv("WHATSAPP_DISPLAY_PHONE_NUMBER", "+8801816504097")
    META_GRAPH_VERSION: str = os.getenv("META_GRAPH_VERSION", "v23.0")
    
    # Shop Default Settings
    SHOP_NAME: str = os.getenv("SHOP_NAME", "আমার ই-কমার্স শপ")
    SHOP_PHONE: str = os.getenv("SHOP_PHONE", "01700000000")
    DELIVERY_FEE_INSIDE_DHAKA: float = float(os.getenv("DELIVERY_FEE_INSIDE_DHAKA", "70"))
    DELIVERY_FEE_OUTSIDE_DHAKA: float = float(os.getenv("DELIVERY_FEE_OUTSIDE_DHAKA", "130"))
    AUTO_COMMENT_REPLY: bool = os.getenv("AUTO_COMMENT_REPLY", "true").lower() == "true"
    SEND_PRIVATE_MESSAGE_ON_COMMENT: bool = os.getenv("SEND_PRIVATE_MESSAGE_ON_COMMENT", "true").lower() == "true"

settings = Settings()

# Ensure directories exist
settings.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
settings.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
