import asyncio
import edge_tts
import uuid
from pathlib import Path
from app.config import settings
from app.database import get_setting

# Voice options for Bengali and English
VOICE_MAP = {
    "bn_female": "bn-BD-NabanitaNeural",
    "bn_male": "bn-BD-PradeepNeural",
    "en_female": "en-US-JennyNeural",
    "en_male": "en-US-GuyNeural",
}

async def generate_bangla_voice(text: str, voice_name: str = None) -> str:
    """
    Generates a natural-sounding voice MP3 audio file from text using Edge-TTS.
    Returns relative URL to the audio file (e.g., /static/audio/abc.mp3).
    """
    if not text or not text.strip():
        return ""

    if not voice_name:
        saved_voice = get_setting("voice_type", "bn-BD-NabanitaNeural")
        voice_name = saved_voice if saved_voice else "bn-BD-NabanitaNeural"

    # Clean text to remove markdown asterisks or special tokens for smoother speech
    clean_text = text.replace("*", "").replace("#", "").replace("`", "").strip()

    file_id = f"voice_{uuid.uuid4().hex[:8]}.mp3"
    output_path = settings.AUDIO_DIR / file_id

    try:
        communicate = edge_tts.Communicate(clean_text, voice=voice_name)
        await communicate.save(str(output_path))
        return f"/static/audio/{file_id}"
    except Exception as e:
        print(f"[VoiceEngine Error] Failed to generate TTS: {e}")
        return ""

def list_available_voices():
    """Returns list of popular Bangla and English voices for settings."""
    return [
        {"id": "bn-BD-NabanitaNeural", "name": "বাংলা নারী কণ্ঠ (নবনিতা - বাংলাদেশ)", "lang": "bn-BD"},
        {"id": "bn-BD-PradeepNeural", "name": "বাংলা পুরুষ কণ্ঠ (প্রদীপ - বাংলাদেশ)", "lang": "bn-BD"},
        {"id": "bn-IN-TanishaaNeural", "name": "বাংলা নারী কণ্ঠ (তানিশা - ভারত)", "lang": "bn-IN"},
        {"id": "bn-IN-BashkarNeural", "name": "বাংলা পুরুষ কণ্ঠ (ভাস্কর - ভারত)", "lang": "bn-IN"},
        {"id": "en-US-JennyNeural", "name": "English Female (Jenny)", "lang": "en-US"},
        {"id": "en-US-GuyNeural", "name": "English Male (Guy)", "lang": "en-US"}
    ]
