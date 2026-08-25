import asyncio
import os
import sys
from unittest.mock import patch, MagicMock

# Ensure project root is on PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from app.database import (
    init_db, save_connected_page, delete_connected_page,
    save_whatsapp_account, delete_whatsapp_account, get_all_connected_pages
)
from app.channels.facebook import handle_facebook_webhook_event
from app.channels.whatsapp import handle_whatsapp_webhook_event

async def test_facebook_messenger_routing():
    print("\n--- [E2E TEST 1] Facebook Messenger Multi-Page Webhook Routing ---")
    page1 = get_all_connected_pages()[0]
    p1_id = page1["page_id"]

    # Register Page 2
    p2_id = "fb_page_2_isolated_test"
    p2_token = "PAGE_2_TOKEN_ABC123"
    save_connected_page({
        "page_id": p2_id,
        "page_name": "Page 2 Test Shop",
        "shop_name": "Page 2 Test Shop",
        "page_access_token": p2_token
    })

    # 1. Simulate Messenger Event for Page 1
    p1_event = {
        "object": "page",
        "entry": [{
            "id": p1_id,
            "messaging": [{
                "sender": {"id": "messenger_user_101"},
                "recipient": {"id": p1_id},
                "message": {"mid": "mid_001", "text": "Hello Page 1"}
            }]
        }]
    }

    with patch("app.channels.facebook.send_fb_text_message") as mock_fb_send, \
         patch("app.channels.facebook.process_customer_message") as mock_ai:

        mock_ai.return_value = {"reply_text": "Hello from AI on Page 1!", "matched_images": []}
        mock_fb_send.return_value = True

        await handle_facebook_webhook_event(p1_event)
        assert mock_fb_send.called, "send_fb_text_message should be called for Page 1"
        _, kwargs = mock_fb_send.call_args
        assert kwargs.get("page_id") == p1_id, f"Expected page_id {p1_id}, got {kwargs.get('page_id')}"
        print("✓ Page 1 Messenger webhook dispatched with Page 1 token.")

    # 2. Simulate Messenger Event for Page 2
    p2_event = {
        "object": "page",
        "entry": [{
            "id": p2_id,
            "messaging": [{
                "sender": {"id": "messenger_user_202"},
                "recipient": {"id": p2_id},
                "message": {"mid": "mid_002", "text": "Hello Page 2"}
            }]
        }]
    }

    with patch("app.channels.facebook.send_fb_text_message") as mock_fb_send, \
         patch("app.channels.facebook.process_customer_message") as mock_ai:

        mock_ai.return_value = {"reply_text": "Hello from AI on Page 2!", "matched_images": []}
        mock_fb_send.return_value = True

        await handle_facebook_webhook_event(p2_event)
        assert mock_fb_send.called, "send_fb_text_message should be called for Page 2"
        _, kwargs = mock_fb_send.call_args
        assert kwargs.get("page_id") == p2_id, f"Expected page_id {p2_id}, got {kwargs.get('page_id')}"
        assert kwargs.get("page_token") == p2_token, f"Expected page_token {p2_token}, got {kwargs.get('page_token')}"
        print("✓ Page 2 Messenger webhook dispatched with Page 2 token.")

    # Clean up
    delete_connected_page(p2_id)
    print("✓ [E2E TEST 1 PASSED] Facebook Messenger Multi-Page Webhook Routing verified.")

async def test_whatsapp_multi_account_routing():
    print("\n--- [E2E TEST 2] WhatsApp Multi-Account Webhook Routing ---")
    wa2_phone_id = "wa_phone_id_999222"
    wa2_token = "WA_TOKEN_999222"

    save_whatsapp_account({
        "page_id": "wa_linked_page_2",
        "phone_number_id": wa2_phone_id,
        "display_phone_number": "01799922200",
        "waba_id": "waba_999222",
        "access_token": wa2_token
    })

    # Simulate WhatsApp incoming message on Account 2
    wa_event = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "waba_999222",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "01799922200",
                        "phone_number_id": wa2_phone_id
                    },
                    "contacts": [{"profile": {"name": "Test WA Customer"}}],
                    "messages": [{
                        "from": "8801711112222",
                        "id": "wamid.TEST_001",
                        "timestamp": "1724160000",
                        "text": {"body": "Price of product?"},
                        "type": "text"
                    }]
                },
                "field": "messages"
            }]
        }]
    }

    with patch("app.channels.whatsapp.send_whatsapp_message") as mock_wa_send, \
         patch("app.channels.whatsapp.process_customer_message") as mock_ai:

        mock_ai.return_value = {"reply_text": "Price is 500 BDT", "matched_images": []}
        mock_wa_send.return_value = True

        await handle_whatsapp_webhook_event(wa_event)
        assert mock_wa_send.called, "send_whatsapp_message should be called for WA Account 2"
        _, kwargs = mock_wa_send.call_args
        assert kwargs.get("phone_id") == wa2_phone_id, f"Expected phone_id {wa2_phone_id}, got {kwargs.get('phone_id')}"
        assert kwargs.get("token") == wa2_token, f"Expected token {wa2_token}, got {kwargs.get('token')}"
        print("✓ WhatsApp Account 2 webhook dispatched with exact Account 2 token.")

    # Clean up
    delete_whatsapp_account(wa2_phone_id)
    print("✓ [E2E TEST 2 PASSED] WhatsApp Multi-Account Webhook Routing verified.")

async def main():
    init_db()
    await test_facebook_messenger_routing()
    await test_whatsapp_multi_account_routing()
    print("\n==========================================")
    print("  ALL E2E WEBHOOK ROUTING TESTS PASSED!")
    print("==========================================\n")

if __name__ == "__main__":
    asyncio.run(main())
