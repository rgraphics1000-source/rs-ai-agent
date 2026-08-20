import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from app.main import app

def test_token_masking_security():
    print("\n--- [AUDIT CHECK 15] Token Masking & Security Audit ---")
    client = TestClient(app)

    # 1. Check /api/settings
    r_settings = client.get("/api/settings")
    assert r_settings.status_code == 200
    s_data = r_settings.json().get("settings", {})
    for k in ["fb_page_access_token", "whatsapp_access_token", "meta_system_user_access_token", "gemini_api_key"]:
        val = s_data.get(k, "")
        if val:
            assert "..." in val or "*" in val, f"Token {k} was exposed in plaintext: {val}"
            print(f"✓ /api/settings: {k} is properly masked ({val})")

    # 2. Check /api/pages
    r_pages = client.get("/api/pages")
    assert r_pages.status_code == 200
    pages = r_pages.json().get("pages", [])
    for p in pages:
        tok = p.get("page_access_token", "")
        if tok:
            assert "..." in tok or "*" in tok, f"Page access token was exposed in plaintext: {tok}"
            print(f"✓ /api/pages: page_access_token for '{p['page_name']}' is properly masked ({tok})")

    print("\n✓ [AUDIT CHECK 15 PASSED] Frontend token exposure audit 100% verified.")

if __name__ == "__main__":
    test_token_masking_security()
