import asyncio
import os
import sys

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from app.database import (
    init_db, get_db_connection, get_all_connected_pages, get_connected_page,
    save_connected_page, delete_connected_page, get_all_whatsapp_accounts,
    get_whatsapp_account_by_phone_id, get_whatsapp_account_by_page_id,
    save_whatsapp_account, delete_whatsapp_account, get_page_ai_config
)
from app.channels.facebook import get_fb_token, handle_facebook_webhook_event
from app.channels.whatsapp import get_whatsapp_credentials, handle_whatsapp_webhook_event
from app.channels.omnichat import (
    record_conversation_message, get_all_conversations, get_conversation_history
)

def test_database_and_migration():
    print("\n--- [TEST 1] Database & Auto-Migration ---")
    init_db()
    pages = get_all_connected_pages()
    print(f"Total connected pages: {len(pages)}")
    assert len(pages) >= 1, "Expected at least 1 migrated Page"
    page1 = pages[0]
    print(f"Page 1 found: page_id={page1['page_id']}, page_name={page1['page_name']}")
    assert page1['page_id'] != "", "Page 1 page_id must not be empty"

    wa_accounts = get_all_whatsapp_accounts()
    print(f"Total WhatsApp accounts: {len(wa_accounts)}")
    assert len(wa_accounts) >= 1, "Expected at least 1 WhatsApp account"
    print("✓ [TEST 1 PASSED] Database auto-migration working correctly.")

def test_multi_page_crud_and_isolation():
    print("\n--- [TEST 2] Multi-Page CRUD & Token Isolation ---")
    # Add a mock Page 2
    page2_id = "test_page_2_999888"
    page2_token = "EAAS_TEST_TOKEN_PAGE_2"
    wa2_phone_id = "test_wa_phone_id_999888"
    wa2_token = "EAAS_TEST_WA_TOKEN_2"

    save_connected_page({
        "page_id": page2_id,
        "page_name": "RS Smart Accessories",
        "shop_name": "RS Smart Accessories",
        "shop_phone": "01700000000",
        "page_access_token": page2_token,
        "ai_system_prompt": "You are AI for RS Smart Accessories selling phone cases.",
        "delivery_inside_dhaka": 60,
        "delivery_outside_dhaka": 120
    })

    save_whatsapp_account({
        "page_id": page2_id,
        "phone_number_id": wa2_phone_id,
        "display_phone_number": "01700000000",
        "waba_id": "test_waba_2",
        "access_token": wa2_token
    })

    # Verify Page 2 retrieval
    p2 = get_connected_page(page2_id)
    assert p2 is not None, "Page 2 must be retrievable"
    assert p2["page_name"] == "RS Smart Accessories"
    assert p2["delivery_inside_dhaka"] == 60

    # Verify Token Isolation for Facebook
    token_page2 = get_fb_token(page_id=page2_id)
    assert token_page2 == page2_token, f"Expected {page2_token}, got {token_page2}"

    # Verify Page 1 token is DIFFERENT from Page 2 token
    page1 = get_all_connected_pages()[0]
    token_page1 = get_fb_token(page_id=page1["page_id"])
    assert token_page1 != token_page2, "Page 1 and Page 2 must have distinct isolated tokens"

    # Verify Token Isolation for WhatsApp
    wa_pid, wa_tok = get_whatsapp_credentials(phone_number_id=wa2_phone_id)
    assert wa_pid == wa2_phone_id, f"Expected {wa2_phone_id}, got {wa_pid}"
    assert wa_tok == wa2_token, f"Expected {wa2_token}, got {wa_tok}"

    # Verify Page-level AI config
    ai_cfg_2 = get_page_ai_config(page_id=page2_id)
    assert ai_cfg_2["shop_name"] == "RS Smart Accessories"
    assert int(float(ai_cfg_2["delivery_inside_dhaka"])) == 60
    assert "selling phone cases" in ai_cfg_2["ai_system_prompt"]

    print("✓ [TEST 2 PASSED] Multi-Page CRUD & Token Isolation verified.")

def test_omnichat_page_scoping():
    print("\n--- [TEST 3] Omnichat Page Scoping & History Isolation ---")
    page1_id = get_all_connected_pages()[0]["page_id"]
    page2_id = "test_page_2_999888"

    # Record message for customer A on Page 1
    record_conversation_message("facebook", "cust_p1_001", "Rahim Ahmed", "user", "Page 1 ID Card inquiry", page_id=page1_id)
    # Record message for customer B on Page 2
    record_conversation_message("facebook", "cust_p2_002", "Karim Khan", "user", "Page 2 Phone Case inquiry", page_id=page2_id)

    # Fetch conversations filtered by page
    p1_convs = get_all_conversations(page_id=page1_id)
    p2_convs = get_all_conversations(page_id=page2_id)

    p1_senders = [c["sender_id"] for c in p1_convs]
    p2_senders = [c["sender_id"] for c in p2_convs]

    assert "cust_p1_001" in p1_senders, "Customer A must appear in Page 1 list"
    assert "cust_p1_001" not in p2_senders, "Customer A must NOT appear in Page 2 list"
    assert "cust_p2_002" in p2_senders, "Customer B must appear in Page 2 list"
    assert "cust_p2_002" not in p1_senders, "Customer B must NOT appear in Page 1 list"

    # Clean up test Page 2
    delete_connected_page(page2_id)
    delete_whatsapp_account("test_wa_phone_id_999888")

    print("✓ [TEST 3 PASSED] Omnichat Page Scoping & History Isolation verified.")

if __name__ == "__main__":
    test_database_and_migration()
    test_multi_page_crud_and_isolation()
    test_omnichat_page_scoping()
    print("\n==========================================")
    print("  ALL MULTI-PAGE & MULTI-WHATSAPP TESTS PASSED!")
    print("==========================================\n")
