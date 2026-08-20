import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from app.database import (
    init_db, get_db_connection, save_connected_page, delete_connected_page,
    save_whatsapp_account, delete_whatsapp_account, get_all_connected_pages
)
from app.channels.omnichat import record_conversation_message

def test_admin_reply_isolation():
    print("\n--- [AUDIT CHECK 13 & 14] Cross-Route Isolation & Admin Reply Dispatch ---")
    init_db()

    page1 = get_all_connected_pages()[0]
    p1_id = page1["page_id"]
    p1_token = page1["page_access_token"]

    # Register Page 2
    p2_id = "fb_page_2_audit_test"
    p2_token = "TOKEN_PAGE_2_AUDIT"
    p2_wa_phone_id = "wa_phone_2_audit"
    p2_wa_token = "WA_TOKEN_2_AUDIT"

    save_connected_page({
        "page_id": p2_id,
        "page_name": "RS Page 2 Audit Shop",
        "shop_name": "RS Page 2 Audit Shop",
        "page_access_token": p2_token
    })

    save_whatsapp_account({
        "page_id": p2_id,
        "phone_number_id": p2_wa_phone_id,
        "display_phone_number": "01700998877",
        "waba_id": "waba_audit_2",
        "access_token": p2_wa_token
    })

    # Create 4 test conversations:
    # 1. Page 1 Messenger
    cid_fb_p1 = record_conversation_message("facebook", "fb_user_p1", "User P1", "user", "Hello P1", page_id=p1_id)
    # 2. Page 2 Messenger
    cid_fb_p2 = record_conversation_message("facebook", "fb_user_p2", "User P2", "user", "Hello P2", page_id=p2_id)
    # 3. Page 1 WhatsApp
    cid_wa_p1 = record_conversation_message("whatsapp", "8801811111111", "WA User P1", "user", "Hello WA1", page_id=p1_id)
    # 4. Page 2 WhatsApp
    cid_wa_p2 = record_conversation_message("whatsapp", "8801822222222", "WA User P2", "user", "Hello WA2", page_id=p2_id)

    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)

    # Test Admin Reply on Page 1 Messenger Conversation
    with patch("app.main.send_fb_text_message") as mock_fb_send:
        mock_fb_send.return_value = True
        r = client.post("/api/omnichat/reply", json={"conversation_id": cid_fb_p1, "message": "Admin reply to P1"})
        assert r.status_code == 200, f"Failed: {r.text}"
        assert mock_fb_send.called
        _, kwargs = mock_fb_send.call_args
        assert kwargs.get("page_id") == p1_id, f"Admin reply must target Page 1, got {kwargs.get('page_id')}"
        print("✓ Admin reply on Page 1 Messenger dispatched with Page 1 ID.")

    # Test Admin Reply on Page 2 Messenger Conversation
    with patch("app.main.send_fb_text_message") as mock_fb_send:
        mock_fb_send.return_value = True
        r = client.post("/api/omnichat/reply", json={"conversation_id": cid_fb_p2, "message": "Admin reply to P2"})
        assert r.status_code == 200, f"Failed: {r.text}"
        assert mock_fb_send.called
        _, kwargs = mock_fb_send.call_args
        assert kwargs.get("page_id") == p2_id, f"Admin reply must target Page 2, got {kwargs.get('page_id')}"
        print("✓ Admin reply on Page 2 Messenger dispatched with Page 2 ID.")

    # Test Admin Reply on Page 1 WhatsApp Conversation
    with patch("app.main.send_whatsapp_message") as mock_wa_send:
        mock_wa_send.return_value = True
        r = client.post("/api/omnichat/reply", json={"conversation_id": cid_wa_p1, "message": "Admin reply to WA1"})
        assert r.status_code == 200, f"Failed: {r.text}"
        assert mock_wa_send.called
        _, kwargs = mock_wa_send.call_args
        assert kwargs.get("page_id") == p1_id, f"Admin reply must target Page 1 WA, got {kwargs.get('page_id')}"
        print("✓ Admin reply on Page 1 WhatsApp dispatched with Page 1 ID.")

    # Test Admin Reply on Page 2 WhatsApp Conversation
    with patch("app.main.send_whatsapp_message") as mock_wa_send:
        mock_wa_send.return_value = True
        r = client.post("/api/omnichat/reply", json={"conversation_id": cid_wa_p2, "message": "Admin reply to WA2"})
        assert r.status_code == 200, f"Failed: {r.text}"
        assert mock_wa_send.called
        _, kwargs = mock_wa_send.call_args
        assert kwargs.get("page_id") == p2_id, f"Admin reply must target Page 2 WA, got {kwargs.get('page_id')}"
        print("✓ Admin reply on Page 2 WhatsApp dispatched with Page 2 ID.")

    # Clean up test records
    delete_connected_page(p2_id)
    delete_whatsapp_account(p2_wa_phone_id)
    conn = get_db_connection()
    conn.execute("DELETE FROM conversations WHERE id IN (?, ?, ?, ?)", (cid_fb_p1, cid_fb_p2, cid_wa_p1, cid_wa_p2))
    conn.commit()
    conn.close()

    print("\n✓ [AUDIT CHECKS 13 & 14 PASSED] Cross-Route Isolation & Admin Reply Dispatch 100% verified.")

if __name__ == "__main__":
    test_admin_reply_isolation()
