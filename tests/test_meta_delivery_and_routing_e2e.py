import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import (
    init_db, get_db_connection, ensure_facebook_page_consistency,
    ensure_whatsapp_account_consistency, get_connected_page,
    get_whatsapp_account_by_phone_id, get_active_training_rules,
    get_all_faqs, get_all_products, save_connected_page, save_whatsapp_account
)
from app.channels.facebook import send_fb_text_message, send_fb_media_message, handle_facebook_webhook_event
from app.channels.whatsapp import send_whatsapp_message, send_whatsapp_image, send_whatsapp_audio, send_whatsapp_video, handle_whatsapp_webhook_event

class TestMetaDeliveryAndRoutingE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        ensure_facebook_page_consistency()
        ensure_whatsapp_account_consistency()
        cls.client = TestClient(app)

    def setUp(self):
        self.client = TestClient(app)

    # A. Webhook GET verification for Facebook
    def test_A_facebook_webhook_get_verification(self):
        token = settings.FB_VERIFY_TOKEN
        resp = self.client.get(f"/webhook/facebook?hub.mode=subscribe&hub.verify_token={token}&hub.challenge=test_fb_challenge_123")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "test_fb_challenge_123")

    # B. Webhook GET verification for WhatsApp
    def test_B_whatsapp_webhook_get_verification(self):
        token = settings.WHATSAPP_VERIFY_TOKEN
        resp = self.client.get(f"/webhook/whatsapp?hub.mode=subscribe&hub.verify_token={token}&hub.challenge=test_wa_challenge_456")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "test_wa_challenge_456")

    # C. Incoming Facebook Messenger message -> routes to Workspace 1 (recipient_id: 105116472071659)
    @patch("app.channels.facebook.process_customer_message")
    @patch("app.channels.facebook.send_fb_text_message")
    def test_C_facebook_messenger_routing_workspace_1(self, mock_send, mock_ai):
        mock_ai.return_value = {"reply_text": "আসসালামু আলাইকুম! RS Graphics এ স্বাগতম।", "matched_images": []}
        mock_send.return_value = True

        payload = {
            "object": "page",
            "entry": [{
                "id": "105116472071659",
                "messaging": [{
                    "sender": {"id": "fb_cust_99901"},
                    "recipient": {"id": "105116472071659"},
                    "message": {"mid": "m_test_c_001", "text": "দাম কত?"}
                }]
            }]
        }
        resp = self.client.post("/webhook/facebook", json=payload)
        self.assertEqual(resp.status_code, 200)

    # D. Incoming Facebook message for another Page ID -> routes to its own workspace
    @patch("app.channels.facebook.process_customer_message")
    @patch("app.channels.facebook.send_fb_text_message")
    def test_D_facebook_messenger_routing_page_2(self, mock_send, mock_ai):
        mock_ai.return_value = {"reply_text": "Page 2 Store reply", "matched_images": []}
        mock_send.return_value = True

        # Ensure page 2 exists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM connected_pages WHERE page_id = 'page_fb_test_222'")
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO connected_pages (workspace_id, page_id, page_name, page_access_token, page_status, messenger_enabled, comments_enabled, ai_enabled)
                VALUES (2, 'page_fb_test_222', 'Test Shop 2', 'EAA_TEST_PAGE_2_TOKEN_999999', 'connected', 1, 1, 1)
            """)
            conn.commit()
        conn.close()

        payload = {
            "object": "page",
            "entry": [{
                "id": "page_fb_test_222",
                "messaging": [{
                    "sender": {"id": "fb_cust_99902"},
                    "recipient": {"id": "page_fb_test_222"},
                    "message": {"mid": "m_test_d_002", "text": "Hello shop 2"}
                }]
            }]
        }
        resp = self.client.post("/webhook/facebook", json=payload)
        self.assertEqual(resp.status_code, 200)

    # E. Unknown Facebook Page ID -> safely dropped with warning log (no crash)
    def test_E_unknown_facebook_page_dropped(self):
        payload = {
            "object": "page",
            "entry": [{
                "id": "unknown_page_99999999999",
                "messaging": [{
                    "sender": {"id": "fb_cust_99903"},
                    "recipient": {"id": "unknown_page_99999999999"},
                    "message": {"mid": "m_test_e_003", "text": "Hello unknown"}
                }]
            }]
        }
        resp = self.client.post("/webhook/facebook", json=payload)
        self.assertEqual(resp.status_code, 200)

    # F. Incoming WhatsApp text message -> routes to Workspace 1 (4184514263660680)
    @patch("app.channels.whatsapp.process_customer_message")
    @patch("app.channels.whatsapp.send_whatsapp_message")
    def test_F_whatsapp_routing_workspace_1(self, mock_send, mock_ai):
        mock_ai.return_value = {"reply_text": "আসসালামু আলাইকুম! RS Graphics WhatsApp", "matched_images": []}
        mock_send.return_value = True

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "27905447135785944",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "8801816504097",
                            "phone_number_id": "4184514263660680"
                        },
                        "contacts": [{"profile": {"name": "Customer A"}, "wa_id": "8801711111111"}],
                        "messages": [{
                            "from": "8801711111111",
                            "id": "wamid_test_f_001",
                            "timestamp": "1740000000",
                            "text": {"body": "প্রডাক্ট দেখতে চাই"},
                            "type": "text"
                        }]
                    }
                }]
            }]
        }
        resp = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status_code, 200)

    # G. Incoming WhatsApp message for another registered phone_number_id -> routes to its workspace
    @patch("app.channels.whatsapp.process_customer_message")
    @patch("app.channels.whatsapp.send_whatsapp_message")
    def test_G_whatsapp_routing_account_2(self, mock_send, mock_ai):
        mock_ai.return_value = {"reply_text": "Shop 2 WhatsApp Reply", "matched_images": []}
        mock_send.return_value = True

        # Ensure account 2 exists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM whatsapp_accounts WHERE phone_number_id = '8888777766665555'")
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO whatsapp_accounts (workspace_id, phone_number_id, display_phone_number, waba_id, access_token, connection_status)
                VALUES (2, '8888777766665555', '+8801722222222', '1111222233334444', 'TOKEN_WA_TEST_22222222', 'connected')
            """)
            conn.commit()
        conn.close()

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "1111222233334444",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "8801722222222",
                            "phone_number_id": "8888777766665555"
                        },
                        "contacts": [{"profile": {"name": "Customer B"}, "wa_id": "8801722222222"}],
                        "messages": [{
                            "from": "8801722222222",
                            "id": "wamid_test_g_002",
                            "timestamp": "1740000000",
                            "text": {"body": "Hello WA 2"},
                            "type": "text"
                        }]
                    }
                }]
            }]
        }
        resp = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status_code, 200)

    # H. Unknown WhatsApp phone_number_id -> safely dropped with warning log (no crash)
    def test_H_unknown_whatsapp_phone_dropped(self):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "9999999999999999",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "8801999999999",
                            "phone_number_id": "9999999999999999"
                        },
                        "contacts": [{"profile": {"name": "Unknown User"}, "wa_id": "8801999999999"}],
                        "messages": [{
                            "from": "8801999999999",
                            "id": "wamid_test_h_003",
                            "timestamp": "1740000000",
                            "text": {"body": "Unknown body"},
                            "type": "text"
                        }]
                    }
                }]
            }]
        }
        resp = self.client.post("/webhook/whatsapp", json=payload)
        self.assertEqual(resp.status_code, 200)

    # I. Outbound Facebook text send -> uses correct page_access_token
    @patch("requests.post")
    def test_I_facebook_outbound_text_send(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"recipient_id":"123","message_id":"m_123"}'
        mock_post.return_value = mock_resp

        res = send_fb_text_message("fb_user_123", "Hello Customer", page_token="EAA_VALID_FB_PAGE_TOKEN_12345", page_id="105116472071659")
        self.assertTrue(res)
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        call_params = mock_post.call_args[1].get("params", {})
        self.assertIn("me/messages", call_url)
        self.assertEqual(call_params.get("access_token"), "EAA_VALID_FB_PAGE_TOKEN_12345")

    # J. Outbound WhatsApp text send -> uses correct access_token and POST /{phone_number_id}/messages
    @patch("requests.post")
    def test_J_whatsapp_outbound_text_send(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"messages":[{"id":"wamid.123"}]}'
        mock_post.return_value = mock_resp

        res = send_whatsapp_message(
            "01816504097", "Hello WhatsApp Customer",
            phone_id="4184514263660680",
            token="EAA_VALID_WA_SYSTEM_TOKEN_12345",
            workspace_id=1
        )
        self.assertTrue(res)
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        call_headers = mock_post.call_args[1].get("headers", {})
        self.assertIn("4184514263660680/messages", call_url)
        self.assertEqual(call_headers.get("Authorization"), "Bearer EAA_VALID_WA_SYSTEM_TOKEN_12345")

    # K. Outbound WhatsApp image send -> uses correct credentials and endpoint
    @patch("requests.post")
    def test_K_whatsapp_outbound_image_send(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"messages":[{"id":"wamid.img_123"}]}'
        mock_post.return_value = mock_resp

        res = send_whatsapp_image(
            "01816504097", "https://rs-ai-agent.onrender.com/static/uploads/sample.jpg",
            phone_id="4184514263660680",
            token="EAA_VALID_WA_SYSTEM_TOKEN_12345",
            workspace_id=1
        )
        self.assertTrue(res)
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        self.assertIn("4184514263660680/messages", call_url)

    # L. Outbound WhatsApp voice/audio send -> uses correct credentials and endpoint
    @patch("requests.post")
    def test_L_whatsapp_outbound_audio_send(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"messages":[{"id":"wamid.aud_123"}]}'
        mock_post.return_value = mock_resp

        res = send_whatsapp_audio(
            "01816504097", "https://rs-ai-agent.onrender.com/static/audio/voice.mp3",
            phone_id="4184514263660680",
            token="EAA_VALID_WA_SYSTEM_TOKEN_12345",
            workspace_id=1
        )
        self.assertTrue(res)
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        self.assertIn("4184514263660680/messages", call_url)

    # M. Outbound WhatsApp video send -> uses correct credentials and endpoint
    @patch("requests.post")
    def test_M_whatsapp_outbound_video_send(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"messages":[{"id":"wamid.vid_123"}]}'
        mock_post.return_value = mock_resp

        res = send_whatsapp_video(
            "01816504097", "https://rs-ai-agent.onrender.com/static/uploads/demo.mp4",
            phone_id="4184514263660680",
            token="EAA_VALID_WA_SYSTEM_TOKEN_12345",
            workspace_id=1
        )
        self.assertTrue(res)
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        self.assertIn("4184514263660680/messages", call_url)

    # N. AI response generation -> loads Workspace 1 training rules, faqs, products
    def test_N_workspace_1_data_loading(self):
        rules = get_active_training_rules(workspace_id=1)
        faqs = get_all_faqs(workspace_id=1)
        products = get_all_products(workspace_id=1)
        self.assertIsInstance(rules, list)
        self.assertIsInstance(faqs, list)
        self.assertIsInstance(products, list)
        self.assertGreater(len(rules) + len(faqs) + len(products), 0)

    # O. Workspace isolation -> Page 2 / Account 2 data never bleeds into Workspace 1
    def test_O_workspace_isolation_separation(self):
        wa1 = get_whatsapp_account_by_phone_id("4184514263660680")
        wa2 = get_whatsapp_account_by_phone_id("8888777766665555")
        self.assertIsNotNone(wa1)
        self.assertIsNotNone(wa2)
        self.assertEqual(wa1["workspace_id"], 1)
        self.assertEqual(wa2["workspace_id"], 2)
        self.assertNotEqual(wa1["phone_number_id"], wa2["phone_number_id"])

    # P. Database migration/restart safety -> server restarts 5 times without losing data or duplicating accounts
    def test_P_restart_safety_idempotence(self):
        for _ in range(5):
            ensure_facebook_page_consistency()
            ensure_whatsapp_account_consistency()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM connected_pages WHERE page_id = '105116472071659'")
        p_count = cursor.fetchone()[0]
        self.assertEqual(p_count, 1)

        cursor.execute("SELECT COUNT(*) FROM whatsapp_accounts WHERE phone_number_id = '4184514263660680'")
        wa_count = cursor.fetchone()[0]
        self.assertEqual(wa_count, 1)
        conn.close()

    # Q. GET /api/diagnostics/meta returns HTTP 200 with masked data
    def test_Q_diagnostics_meta_endpoint(self):
        resp = self.client.get("/api/diagnostics/meta")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["rs_graphics_workspace_1"]["facebook_ready"])
        self.assertTrue(data["rs_graphics_workspace_1"]["whatsapp_ready"])
        self.assertEqual(data["rs_graphics_workspace_1"]["canonical_facebook_page_id"], "105116472071659")
        self.assertEqual(data["rs_graphics_workspace_1"]["canonical_whatsapp_phone_id"], "4184514263660680")

if __name__ == "__main__":
    unittest.main()
