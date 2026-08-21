import os
import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
from app.config import settings

def _get_fernet_instance() -> Fernet:
    """Derives a deterministic 32-byte URL-safe base64 key for Fernet encryption."""
    raw_key = os.getenv("GOOGLE_ENCRYPTION_KEY", "") or settings.GOOGLE_ENCRYPTION_KEY
    if not raw_key:
        raw_key = os.getenv("META_APP_ID", "") + "-rs-ai-secret-encryption-salt-2026"
    
    # SHA-256 hash yields 32 bytes, which Fernet requires
    key_bytes = hashlib.sha256(raw_key.encode("utf-8")).digest()
    b64_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(b64_key)

def encrypt_token(plaintext: str) -> str:
    """Encrypts a token string for secure database storage at rest."""
    if not plaintext:
        return ""
    try:
        f = _get_fernet_instance()
        encrypted = f.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")
    except Exception as e:
        print(f"[Crypto Encryption Error]: {e}")
        return plaintext

def decrypt_token(ciphertext: str) -> str:
    """Decrypts an encrypted token string retrieved from the database."""
    if not ciphertext:
        return ""
    try:
        f = _get_fernet_instance()
        decrypted = f.decrypt(ciphertext.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception:
        # If decryption fails (e.g. unencrypted legacy string or test fixture), return as is
        return ciphertext

def mask_token(token: str) -> str:
    """Masks an access or refresh token for safe logging/display (e.g. ya29.a0...x89q)."""
    if not token:
        return "***"
    t = str(token).strip()
    if len(t) <= 8:
        return "***"
    return f"{t[:6]}...{t[-4:]}"

def mask_email(email: str) -> str:
    """Masks an email address (e.g. ex***e@gmail.com)."""
    if not email or "@" not in email:
        return "***"
    parts = email.split("@")
    user, domain = parts[0], parts[1]
    if len(user) <= 2:
        masked_user = user[0] + "*"
    else:
        masked_user = user[:2] + "***" + user[-1]
    return f"{masked_user}@{domain}"
