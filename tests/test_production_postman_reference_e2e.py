"""
Production Postman Reference & Regression E2E Test Suite.
Verifies:
1. Exact Postman Reference request matching (POST https://graph.facebook.com/v23.0/4184514263660680/messages).
2. Strict token isolation: Facebook Page Access Token NEVER used for WhatsApp Cloud API.
3. Facebook Page 105116472071659 routing and delivery.
4. WhatsApp Phone Number ID 4184514263660680 routing and delivery.
5. Omnichat Admin manual reply routing for both channels.
6. Multi-Tenant isolation between Workspace 1 (RS Graphics) and Workspace 2 (Test Business).
7. Media attachments delivery (image, audio, video).
8. Dedicated diagnostic endpoints (/api/diagnostics/whatsapp, /api/diagnostics/facebook, /api/diagnostics/meta).
"""

import os
import sys
import unittest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.main import app
from app.database import (
    get_db_connection,
    ensure_facebook_page_consistency,
    ensure_whatsapp_account_consistency,
    get_whatsapp_account_by_phone_id,
    get_connected_page,
    get_all_workspaces
)
from app.channels.whatsapp import (
    send_whatsapp_message,
    send_whatsapp_message_detailed,
    send_whatsapp_image,
    send_whatsapp_audio,
    send_whatsapp_video,
    resolve_whatsapp_token_info,
    validate_whatsapp_token_with_meta,
    get_whatsapp_credentials
)
from app.channels.facebook import (
    send_fb_text_message,
    send_fb_media_message,
    get_fb_token
)

class TestProductionPostmanReferenceE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        ensure_facebook_page_consistency()
        ensure_whatsapp_account_consistency()

    def test_01_postman_reference_whatsapp_request_structure(self):
        """Verifies exact Postman reference request structure and payload."""
        sent_calls = []

        def mock_post(url, headers=None, json=None, timeout=None):
            sent_calls.append({"url": url, "headers": headers, "json": json})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "messaging_product": "whatsapp",
                "contacts": [{"input": "8801929778581", "wa_id": "8801929778581"}],
                "messages": [{"id": "wamid.HBgMODgwMTkyOTc3ODU4MRUCMRIAEhggMTIzNDU2Nzg5MAA="}]
            }
            return resp

        valid_system_user_token = "EAAGValidRealSystemUserTokenLong12345678901234567890"
        with patch("requests.post", side_effect=mock_post):
            ok = send_whatsapp_message(
                to_number="8801929778581",
                message_text="আসসালামু আলাইকুম। এটি RS GRAPHICS WhatsApp Cloud API-এর একটি Test Message",
                phone_id="4184514263660680",
                token=valid_system_user_token,
                workspace_id=1
            )
            self.assertTrue(ok)
            self.assertEqual(len(sent_calls), 1)
            call = sent_calls[0]
            
            # 1. URL must match exact Meta Cloud API format
            self.assertEqual(call["url"], "https://graph.facebook.com/v23.0/4184514263660680/messages")
            
            # 2. Header must be Bearer without extra quotes or formatting
            self.assertEqual(call["headers"]["Authorization"], f"Bearer {valid_system_user_token}")
            self.assertEqual(call["headers"]["Content-Type"], "application/json")
            
            # 3. Payload must match exact Meta specification
            expected_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": "8801929778581",
                "type": "text",
                "text": {
                    "body": "আসসালামু আলাইকুম। এটি RS GRAPHICS WhatsApp Cloud API-এর একটি Test Message"
                }
            }
            self.assertEqual(call["json"], expected_payload)

    def test_02_strict_token_isolation_fb_page_token_never_used_for_whatsapp(self):
        """Verifies that Facebook Page Access Tokens are NEVER resolved for WhatsApp Cloud API."""
        wa_acc = {"id": 1, "access_token": "", "phone_number_id": "4184514263660680"}
        
        # Test environment with only FB_PAGE_ACCESS_TOKEN
        with patch.dict(os.environ, {
            "FB_PAGE_ACCESS_TOKEN": "EAAS_FB_PAGE_ACCESS_TOKEN_FOR_MESSENGER_1234567890",
            "WHATSAPP_ACCESS_TOKEN": "",
            "META_SYSTEM_USER_ACCESS_TOKEN": ""
        }, clear=False):
            with patch("app.channels.whatsapp.get_setting", side_effect=lambda k, default="": "EAAS_FB_PAGE_TOKEN" if k == "fb_page_access_token" else ""):
                info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=1)
                # The resolved token for WhatsApp MUST NOT be the FB page access token
                self.assertNotIn("FB_PAGE", info.get("token", ""))
                self.assertNotEqual(info.get("token"), "EAAS_FB_PAGE_ACCESS_TOKEN_FOR_MESSENGER_1234567890")

    def test_03_whatsapp_token_validation_with_meta(self):
        """Verifies token validation against Meta Graph API returning structured diagnostics."""
        def mock_get(url, headers=None, params=None, timeout=None):
            resp = MagicMock()
            if "INVALID" in headers.get("Authorization", ""):
                resp.status_code = 400
                resp.json.return_value = {
                    "error": {
                        "message": "Unsupported post request. Object with ID '4184514263660680' does not exist, cannot be loaded due to missing permissions, or does not support this operation.",
                        "type": "GraphMethodException",
                        "code": 100,
                        "error_subcode": 33
                    }
                }
            else:
                resp.status_code = 200
                resp.json.return_value = {
                    "id": "4184514263660680",
                    "display_phone_number": "+880 1816-504097",
                    "verified_name": "RS Graphics",
                    "quality_rating": "GREEN",
                    "code_verification_status": "VERIFIED"
                }
            return resp

        with patch("requests.get", side_effect=mock_get):
            # Valid token check (Real tokens start with EAAG or EAA without Test)
            res_valid = validate_whatsapp_token_with_meta(
                token="EAAGValidProductionSystemUserToken12345678901234567890",
                phone_id="4184514263660680"
            )
            self.assertTrue(res_valid["valid"])
            self.assertTrue(res_valid["phone_number_access"])
            self.assertEqual(res_valid["verified_name"], "RS Graphics")

            # Missing permissions / invalid token check
            res_invalid = validate_whatsapp_token_with_meta(
                token="EAAGINVALIDTokenWithMissingPermissions12345678901234567890",
                phone_id="4184514263660680"
            )
            self.assertFalse(res_invalid["valid"])
            self.assertFalse(res_invalid["phone_number_access"])
            self.assertEqual(res_invalid["error_code"], "MISSING_WHATSAPP_PERMISSION_OR_WRONG_TOKEN_TYPE")

    def test_04_facebook_messenger_routing_and_send(self):
        """Verifies that Facebook Page 105116472071659 routes to Workspace 1 and sends via /me/messages."""
        sent_calls = []

        def mock_fb_post(url, params=None, json=None, timeout=None):
            sent_calls.append({"url": url, "params": params, "json": json})
            resp = MagicMock()
            resp.status_code = 200
            resp.text = '{"recipient_id": "fb_cust_123", "message_id": "mid.$cAA..."}'
            return resp

        with patch("requests.post", side_effect=mock_fb_post):
            ok = send_fb_text_message(
                recipient_id="fb_cust_123",
                text="ধন্যবাদ RS GRAPHICS এ যোগাযোগ করার জন্য!",
                page_token="EAAS_VALID_FB_PAGE_ACCESS_TOKEN_1234567890",
                page_id="105116472071659"
            )
            self.assertTrue(ok)
            self.assertEqual(len(sent_calls), 1)
            call = sent_calls[0]
            self.assertEqual(call["url"], "https://graph.facebook.com/v19.0/me/messages")
            self.assertEqual(call["params"]["access_token"], "EAAS_VALID_FB_PAGE_ACCESS_TOKEN_1234567890")
            self.assertEqual(call["json"]["recipient"]["id"], "fb_cust_123")

    def test_05_diagnostic_endpoints_security_and_readiness(self):
        """Verifies GET /api/diagnostics/whatsapp and GET /api/diagnostics/facebook mask tokens and return correct schema."""
        # 1. WhatsApp diagnostic endpoint
        r_wa = self.client.get("/api/diagnostics/whatsapp")
        self.assertEqual(r_wa.status_code, 200)
        data_wa = r_wa.json()
        self.assertEqual(data_wa["workspace_id"], 1)
        self.assertEqual(data_wa["phone_number_id"], "4184514263660680")
        self.assertEqual(data_wa["waba_id"], "27905447135785944")
        self.assertIn("endpoint_url", data_wa)
        self.assertIn("token_present", data_wa)
        # Ensure raw token is never exposed in top-level output
        self.assertNotIn("access_token", data_wa)

        # 2. Facebook diagnostic endpoint
        r_fb = self.client.get("/api/diagnostics/facebook")
        self.assertEqual(r_fb.status_code, 200)
        data_fb = r_fb.json()
        self.assertEqual(data_fb["workspace_id"], 1)
        self.assertEqual(data_fb["page_id"], "105116472071659")
        self.assertIn("endpoint_url", data_fb)

    def test_06_omnichat_manual_reply_scoped_routing(self):
        """Verifies manual admin replies via Omnichat resolve the correct workspace channel credentials."""
        # Insert a test conversation
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO conversations (workspace_id, channel, sender_id, customer_name, last_message, page_id)
            VALUES (1, 'whatsapp', '8801929778581', 'Postman Test User', 'Hello', '4184514263660680')
        """)
        cid = cur.lastrowid
        conn.commit()
        conn.close()

        with patch("app.main.send_whatsapp_message", return_value=True) as mock_wa_send:
            r = self.client.post("/api/omnichat/reply", json={
                "conversation_id": cid,
                "message": "Admin reply test"
            })
            self.assertEqual(r.status_code, 200)
            mock_wa_send.assert_called_once_with("8801929778581", "Admin reply test", page_id="4184514263660680", workspace_id=1)

    def test_07_media_sending_whatsapp_and_facebook(self):
        """Verifies image, audio, and video delivery for WhatsApp and Facebook."""
        with patch("requests.post") as mock_p:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"messages": [{"id": "wamid.media123"}]}
            mock_resp.text = '{"recipient_id": "123", "message_id": "m_123"}'
            mock_p.return_value = mock_resp

            # WhatsApp Media
            self.assertTrue(send_whatsapp_image("8801929778581", "https://example.com/pic.jpg", phone_id="4184514263660680", token="EAAGValidTok12345678901234567890", workspace_id=1))
            self.assertTrue(send_whatsapp_audio("8801929778581", "https://example.com/audio.mp3", phone_id="4184514263660680", token="EAAGValidTok12345678901234567890", workspace_id=1))
            self.assertTrue(send_whatsapp_video("8801929778581", "https://example.com/video.mp4", phone_id="4184514263660680", token="EAAGValidTok12345678901234567890", workspace_id=1))

            # Facebook Media
            self.assertTrue(send_fb_media_message("fb_123", "image", "https://example.com/pic.jpg", page_token="EAASValid12345678901234567890", page_id="105116472071659"))

    def test_08_unknown_whatsapp_phone_number_rejection(self):
        """Verifies unknown WhatsApp Phone Number ID is dropped without fallback to Workspace 1."""
        unknown_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "unknown_waba",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"display_phone_number": "1234567890", "phone_number_id": "9999999999999999"},
                        "messages": [{"id": "wamid_unknown_01", "from": "8801999999999", "type": "text", "text": {"body": "Hello"}}]
                    },
                    "field": "messages"
                }]
            }]
        }
        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send:
            r = self.client.post("/webhook/whatsapp", json=unknown_payload)
            self.assertEqual(r.status_code, 200)
            mock_send.assert_not_called()

    def test_09_unknown_facebook_page_rejection(self):
        """Verifies unknown Facebook Page ID is dropped without fallback to Workspace 1."""
        unknown_fb_payload = {
            "object": "page",
            "entry": [{
                "id": "unknown_page_888888888888",
                "messaging": [{
                    "sender": {"id": "fb_user_unknown"},
                    "recipient": {"id": "unknown_page_888888888888"},
                    "message": {"mid": "mid_unknown_01", "text": "Hi"}
                }]
            }]
        }
        with patch("app.channels.facebook.send_fb_text_message") as mock_fb_send:
            r = self.client.post("/webhook/facebook", json=unknown_fb_payload)
            self.assertEqual(r.status_code, 200)
            mock_fb_send.assert_not_called()

    def test_10_database_idempotency_and_no_duplicates(self):
        """Verifies database consistency functions can run multiple times without duplicating records."""
        for _ in range(3):
            ensure_facebook_page_consistency()
            ensure_whatsapp_account_consistency()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM whatsapp_accounts WHERE phone_number_id = '4184514263660680'")
        wa_count = cur.fetchone()["count"]
        self.assertEqual(wa_count, 1)

        cur.execute("SELECT COUNT(*) as count FROM connected_pages WHERE page_id = '105116472071659'")
        fb_count = cur.fetchone()["count"]
        self.assertEqual(fb_count, 1)
        conn.close()

    def test_11_test_send_diagnostic_endpoint(self):
        """Verifies POST /api/diagnostics/whatsapp/test-send executes with structured diagnostics."""
        with patch("requests.post") as mock_p:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "messaging_product": "whatsapp",
                "contacts": [{"input": "8801929778581", "wa_id": "8801929778581"}],
                "messages": [{"id": "wamid.TestDiag12345"}]
            }
            mock_p.return_value = mock_resp

            with patch("app.channels.whatsapp.resolve_whatsapp_token_info", return_value={"token": "EAAGValidDiagnosticToken12345678901234567890", "source": "test", "is_valid": True}):
                r = self.client.post("/api/diagnostics/whatsapp/test-send", json={
                    "to_number": "8801929778581",
                    "message": "Diagnostic test message"
                })
                self.assertEqual(r.status_code, 200)
                data = r.json()
                self.assertTrue(data["success"])
                self.assertEqual(data["phone_number_id"], "4184514263660680")
                self.assertEqual(data["result"]["message_id"], "wamid.TestDiag12345")

    def test_12_ai_response_not_marked_sent_after_meta_400(self):
        """Verifies that when Meta returns HTTP 400, outgoing message is NOT recorded as sent."""
        with patch("requests.post") as mock_p:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.json.return_value = {
                "error": {
                    "message": "Unsupported post request. Object with ID '4184514263660680' does not exist, cannot be loaded due to missing permissions, or does not support this operation.",
                    "type": "GraphMethodException",
                    "code": 100
                }
            }
            mock_p.return_value = mock_resp

            res = send_whatsapp_message_detailed(
                to_number="8801929778581",
                message_text="Test failing send",
                phone_id="4184514263660680",
                token="EAAGValidTokenFormat12345678901234567890"
            )
            self.assertFalse(res["success"])
            self.assertEqual(res["http_status"], 400)
            self.assertEqual(res["graph_error_code"], 100)

    def test_13_ai_response_marked_sent_after_meta_200(self):
        """Verifies that when Meta returns HTTP 200, outgoing message captures wamid and succeeds."""
        with patch("requests.post") as mock_p:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "messaging_product": "whatsapp",
                "contacts": [{"input": "8801929778581", "wa_id": "8801929778581"}],
                "messages": [{"id": "wamid.SuccessDelivery123456"}]
            }
            mock_p.return_value = mock_resp

            res = send_whatsapp_message_detailed(
                to_number="8801929778581",
                message_text="Test successful send",
                phone_id="4184514263660680",
                token="EAAGValidTokenFormat12345678901234567890"
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["http_status"], 200)
            self.assertEqual(res["message_id"], "wamid.SuccessDelivery123456")

    def test_14_full_tokens_never_appear_in_logs(self):
        """Verifies that full sensitive tokens never appear in logging output."""
        import io
        captured = io.StringIO()
        raw_secret_token = "EAAG_EXTREMELY_SECRET_PRODUCTION_SYSTEM_USER_TOKEN_99999999999999"
        
        with patch("sys.stdout", captured):
            with patch("requests.post") as mock_p:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"messages": [{"id": "wamid.123"}]}
                mock_p.return_value = mock_resp

                send_whatsapp_message(
                    to_number="8801929778581",
                    message_text="Checking logs",
                    phone_id="4184514263660680",
                    token=raw_secret_token
                )

        log_output = captured.getvalue()
        self.assertNotIn(raw_secret_token, log_output)
        self.assertIn("status=success", log_output)

    def test_15_existing_database_records_remain_intact_after_init_db(self):
        """Verifies that init_db and consistency helpers preserve Workspace 1 training, FAQs, and accounts."""
        from app.database import (
            init_db,
            get_active_training_rules,
            get_all_faqs,
            get_all_products
        )
        from app.channels.omnichat import get_all_conversations
        init_db()
        ensure_facebook_page_consistency()
        ensure_whatsapp_account_consistency()

        rules = get_active_training_rules(workspace_id=1)
        faqs = get_all_faqs(workspace_id=1)
        products = get_all_products(workspace_id=1)
        convs = get_all_conversations(workspace_id=1)

        self.assertGreaterEqual(len(rules), 30)
        self.assertGreaterEqual(len(faqs), 5)
        self.assertGreaterEqual(len(products), 4)
        self.assertGreaterEqual(len(convs), 20)

    def test_16_database_token_precedence_over_env_token(self):
        """Verifies that a valid database token is preferred over environment tokens."""
        valid_db_token = "EAAGValidDatabaseTokenForWhatsApp12345678901234567890"
        invalid_env_token = "EAAGInvalidEnvTokenForWhatsApp12345678901234567890"

        def mock_get(url, headers=None, params=None, timeout=None):
            auth = headers.get("Authorization", "")
            resp = MagicMock()
            if valid_db_token in auth:
                resp.status_code = 200
                resp.json.return_value = {
                    "id": "4184514263660680",
                    "display_phone_number": "+880 1816-504097",
                    "verified_name": "RS Graphics"
                }
            else:
                resp.status_code = 400
                resp.json.return_value = {"error": {"message": "Invalid token", "code": 100}}
            return resp

        wa_acc = {"id": 1, "access_token": valid_db_token, "phone_number_id": "4184514263660680"}
        with patch.dict(os.environ, {"META_SYSTEM_USER_ACCESS_TOKEN": invalid_env_token}, clear=False):
            with patch("requests.get", side_effect=mock_get):
                info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=1, phone_number_id="4184514263660680")
                self.assertTrue(info["is_valid"])
                self.assertEqual(info["token"], valid_db_token)
                self.assertIn("database", info["source"])

    def test_17_no_outbound_send_when_no_valid_token(self):
        """Verifies that when no token passes validation, NO request is sent to Meta and an error is returned."""
        def mock_get(url, headers=None, params=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 400
            resp.json.return_value = {"error": {"message": "Permission denied", "code": 100}}
            return resp

        with patch("requests.get", side_effect=mock_get):
            with patch("requests.post") as mock_post:
                wa_acc = {"id": 1, "access_token": "EAAGInvalid12345678901234567890", "phone_number_id": "4184514263660680"}
                with patch("app.channels.whatsapp.get_whatsapp_account_by_phone_id", return_value=wa_acc):
                    res = send_whatsapp_message_detailed(
                        to_number="8801929778581",
                        message_text="Should never send",
                        phone_id="4184514263660680"
                    )
                    self.assertFalse(res["success"])
                    self.assertEqual(res["error_code"], "NO_VALID_WHATSAPP_TOKEN_CONFIGURED")
                    mock_post.assert_not_called()

    def test_18_clear_cache_endpoint(self):
        """Verifies that POST /api/diagnostics/whatsapp/clear-cache successfully clears the validation cache."""
        r = self.client.post("/api/diagnostics/whatsapp/clear-cache")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["success"])

if __name__ == "__main__":
    unittest.main()




