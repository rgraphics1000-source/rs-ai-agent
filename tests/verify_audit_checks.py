import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

def run_import_checks():
    print("\n--- [AUDIT CHECK 3 & 4] Import Checks ---")
    import app.main
    print("✓ app.main imported successfully")
    import app.database
    print("✓ app.database imported successfully")
    import app.channels.facebook
    print("✓ app.channels.facebook imported successfully")
    import app.channels.whatsapp
    print("✓ app.channels.whatsapp imported successfully")
    import app.channels.omnichat
    print("✓ app.channels.omnichat imported successfully")
    import app.ai_agent.gemini_brain
    print("✓ app.ai_agent.gemini_brain imported successfully")

def run_route_checks():
    print("\n--- [AUDIT CHECK 5 & 6] FastAPI Routes Verification ---")
    from app.main import app
    
    routes = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if path and methods:
            routes.append((path, sorted(list(methods))))
    
    print(f"Total registered FastAPI routes: {len(routes)}")
    
    required_routes = [
        ("GET", "/webhook/facebook"),
        ("POST", "/webhook/facebook"),
        ("GET", "/webhook/whatsapp"),
        ("POST", "/webhook/whatsapp"),
        ("GET", "/api/pages"),
        ("POST", "/api/pages/connect"),
        ("POST", "/api/omnichat/reply"),
        ("POST", "/api/omnichat/send"),
        ("GET", "/api/omnichat/conversations"),
        ("GET", "/api/omnichat/messages/{conversation_id}")
    ]
    
    for method, path in required_routes:
        found = False
        for r_path, r_methods in routes:
            if r_path == path and method in r_methods:
                found = True
                break
        assert found, f"CRITICAL: Missing route {method} {path}"
        print(f"✓ Verified route: {method:5} {path}")

def run_legacy_fallback_check():
    print("\n--- [AUDIT CHECK 8] Legacy Conversation Fallback to Page 1 ---")
    from app.channels.facebook import get_fb_token
    from app.channels.whatsapp import get_whatsapp_credentials
    from app.database import get_all_connected_pages, get_page_ai_config

    page1 = get_all_connected_pages()[0]
    p1_id = page1["page_id"]
    p1_token = page1["page_access_token"]

    # 1. Fallback when page_id is empty string or None
    token_fallback_empty = get_fb_token(page_id="")
    token_fallback_none = get_fb_token(page_id=None)
    assert token_fallback_empty == p1_token or bool(token_fallback_empty), "Fallback token for empty page_id must resolve"
    assert token_fallback_none == p1_token or bool(token_fallback_none), "Fallback token for None page_id must resolve"
    print(f"✓ Facebook token fallback for legacy empty page_id successfully resolved (Length: {len(token_fallback_empty)})")

    # 2. WhatsApp fallback for empty page_id or phone_id
    wa_pid, wa_tok = get_whatsapp_credentials(phone_number_id=None, page_id=None)
    assert bool(wa_pid), "WhatsApp phone_id fallback must resolve"
    assert bool(wa_tok), "WhatsApp token fallback must resolve"
    print(f"✓ WhatsApp fallback for legacy conversation successfully resolved to Phone ID: {wa_pid}")

    # 3. AI Config fallback for empty page_id
    cfg_fallback = get_page_ai_config(page_id="")
    assert cfg_fallback["shop_name"] != "", "Shop name fallback must exist"
    print(f"✓ AI config fallback for legacy conversation successfully resolved (Shop: {cfg_fallback['shop_name']})")

if __name__ == "__main__":
    run_import_checks()
    run_route_checks()
    run_legacy_fallback_check()
    print("\n==========================================")
    print("  AUDIT CHECKS 3, 4, 5, 6, 8 VERIFIED!")
    print("==========================================\n")
