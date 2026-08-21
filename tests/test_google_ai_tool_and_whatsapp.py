import os
import sys
import unittest
import asyncio
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from app.main import app
from app.database import (
    init_db, save_google_connection, delete_google_connection,
    save_generated_form, save_whatsapp_account, delete_whatsapp_account
)
from app.google_integration.crypto import encrypt_token
from app.google_integration.ai_tool import detect_google_form_intent, create_id_card_google_form
from app.google_integration.form_manager import send_form_link_via_whatsapp
from app.ai_agent.gemini_brain import process_customer_message

class TestGoogleAIToolAndWhatsApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = TestClient(app)
        self.workspace_id = 995
        from app.database import get_db_connection
        conn = get_db_connection()
        conn.execute("DELETE FROM generated_forms WHERE workspace_id = ?", (self.workspace_id,))
        conn.commit()
        conn.close()

        delete_google_connection(workspace_id=self.workspace_id)
        save_google_connection(
            workspace_id=self.workspace_id,
            google_account_email="aitool.test@gmail.com",
            access_token_encrypted=encrypt_token("mock_tok_995"),
            refresh_token_encrypted=encrypt_token("mock_ref_995"),
            master_form_id="master_id_995"
        )
        self.form = save_generated_form(
            workspace_id=self.workspace_id,
            institution_name="জামিয়া রাহমানিয়া আরাবিয়া",
            form_id="form_jamia_995",
            form_url="https://docs.google.com/forms/d/form_jamia_995/viewform",
            responder_uri="https://docs.google.com/forms/d/e/form_jamia_995/viewform"
        )
        save_whatsapp_account({
            "phone_number_id": "wa_phone_id_995",
            "display_phone_number": "01711000995",
            "waba_id": "waba_995",
            "workspace_id": self.workspace_id,
            "access_token": "TOKEN_MOCK_VALID_WHATSAPP_SECRET_KEY_1234567890"
        })

    def tearDown(self):
        delete_google_connection(workspace_id=self.workspace_id)
        delete_whatsapp_account("wa_phone_id_995")

    def test_01_detect_google_form_intent(self):
        """Verifies Bengali and English intent recognition and institution name extraction."""
        m1 = "জামিয়া রাহমানিয়া আরাবিয়ার জন্য ID Card Form বানাও"
        m1_intent = detect_google_form_intent(m1)
        self.assertIsNotNone(m1_intent)
        self.assertIn("জামিয়া রাহমানিয়া আরাবিয়া", m1_intent["institution_name"])

        m2 = "আমাদের মাদরাসার জন্য একটি google form লিংক দিন"
        m2_intent = detect_google_form_intent(m2)
        self.assertIsNotNone(m2_intent)

        m3 = "আইডি কার্ডের দাম কত?"
        m3_intent = detect_google_form_intent(m3)
        self.assertIsNone(m3_intent)
        print("✓ AI Intent detection accurately extracted institution and recognized keywords.")

    @patch("app.channels.whatsapp.validate_whatsapp_token_with_meta")
    @patch("app.channels.whatsapp.requests.post")
    def test_02_send_form_link_via_whatsapp(self, mock_post, mock_validate):
        """Verifies sending the Google Form URL via the workspace WhatsApp account."""
        mock_validate.return_value = {"valid": True, "phone_number_access": True, "token": "TOKEN_MOCK_VALID_WHATSAPP_SECRET_KEY_1234567890"}
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"messages": [{"id": "wamid.HBgL..."}]}

        res = send_form_link_via_whatsapp(
            workspace_id=self.workspace_id,
            form_id="form_jamia_995",
            recipient_phone="01816504097"
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["recipient_phone"], "8801816504097")

        # Verify WhatsApp API was called with the form link in message text
        called_payload = mock_post.call_args[1]["json"]
        self.assertIn("https://docs.google.com/forms/d/e/form_jamia_995/viewform", called_payload["text"]["body"])
        print("✓ WhatsApp form delivery verified with correct URL and phone normalization.")

    @patch("app.ai_agent.gemini_brain.create_id_card_google_form")
    def test_03_gemini_brain_end_to_end_form_intent_response(self, mock_ai_tool):
        """Verifies AI Agent automatically generates and returns the Google Form link when requested."""
        mock_ai_tool.return_value = {
            "success": True,
            "responder_url": "https://docs.google.com/forms/d/e/form_jamia_995/viewform",
            "form_url": "https://docs.google.com/forms/d/e/form_jamia_995/viewform",
            "institution_name": "জামিয়া রাহমানিয়া আরাবিয়া"
        }

        user_message = "জামিয়া রাহমানিয়া আরাবিয়ার জন্য ID Card Form বানাও"
        res = asyncio.run(
            process_customer_message(
                message_text=user_message,
                customer_name="মাওলানা আহমেদ",
                workspace_id=self.workspace_id
            )
        )

        reply = res.get("reply_text", "")
        self.assertIn("docs.google.com/forms", reply)
        self.assertIn("জামিয়া রাহমানিয়া আরাবিয়া", reply)
        print("✓ Gemini Brain seamlessly resolved form intent and returned public link.")

if __name__ == "__main__":
    unittest.main()
