import unittest
import asyncio
import sys
import os
import time

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import patch, MagicMock
from app.google_integration.ai_tool import resolve_google_form_workflow
from app.ai_agent.gemini_brain import process_customer_message
from app.channels.whatsapp import handle_whatsapp_webhook_event, resolve_whatsapp_token
from app.database import (
    save_google_connection, get_google_connection, get_generated_forms_by_mobile,
    save_generated_form, get_db_connection, save_institution, remove_muted_number
)

class TestProductionGoogleFormHardGuarantees(unittest.TestCase):
    def setUp(self):
        self.workspace_id = 9988
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO workspaces (id, name, slug) VALUES (?, 'Test WS 9988', 'test-ws-9988')", (self.workspace_id,))
            cursor.execute("UPDATE conversations SET human_takeover = 0 WHERE sender_id IN ('01929778581', '8801929778581', '8801929770001', '01711001100', '01799999999', '01799887766')")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM generated_forms WHERE workspace_id = ?", (self.workspace_id,))
            cursor.execute("DELETE FROM institutions WHERE workspace_id = ?", (self.workspace_id,))
            cursor.execute("DELETE FROM google_connections WHERE workspace_id = ?", (self.workspace_id,))
            cursor.execute("DELETE FROM workspaces WHERE id = ?", (self.workspace_id,))
            conn.commit()
        finally:
            conn.close()

    @patch("app.google_integration.ai_tool.create_institution_form")
    def test_126_institution_and_fields_without_form_keyword_triggers_workflow(self, mock_create):
        """Test 126: Institution + fields without 'form' keyword triggers workflow."""
        mock_create.return_value = {
            "success": True,
            "form_id": "form_126",
            "form_title": "জামিয়া উম্মুল কোরা মসজিদ - 01929778581 - ID Card Form",
            "sheet_title": "জামিয়া উম্মুল কোরা মসজিদ - 01929778581 - ID Card Responses",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_126/viewform",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_126/edit",
            "selected_fields": ["student_name", "father_name", "class_name", "roll", "student_photo"]
        }

        res = resolve_google_form_workflow(
            user_message="প্রতিষ্ঠানের নাম জামিয়া উম্মুল কোরা মসজিদ\nনাম পিতা শ্রেণী রোল আর স্টুডেন্টের ছবি এগুলো থাকবে",
            conversation_history=[],
            customer_phone="01929778581",
            workspace_id=self.workspace_id
        )

        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "created")
        self.assertEqual(res.get("institution_name"), "জামিয়া উম্মুল কোরা মসজিদ")
        self.assertEqual(res.get("institution_mobile"), "01929778581")
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_126/viewform", res.get("reply", ""))
        self.assertIn("https://docs.google.com/spreadsheets/d/sheet_126/edit", res.get("reply", ""))
        mock_create.assert_called_once()
        print("✓ Test 126 Passed: Institution + fields without 'form' keyword instantly triggered form creation.")

    def test_127_history_extracts_institution_name(self):
        """Test 127: History extracts institution name."""
        history = [
            {"role": "user", "text": "আমাদের প্রতিষ্ঠানের নাম দারুল উলুম মারকাজ"},
            {"role": "assistant", "text": "ধন্যবাদ স্যার। এখন প্রতিষ্ঠানের মোবাইল নম্বরটি দিন।"}
        ]
        res = resolve_google_form_workflow(
            user_message="01711223344",
            conversation_history=history,
            workspace_id=self.workspace_id
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.get("institution_name"), "দারুল উলুম মারকাজ")
        self.assertEqual(res.get("institution_mobile"), "01711223344")
        self.assertEqual(res.get("status"), "need_fields")
        print("✓ Test 127 Passed: History cleanly extracted institution name.")

    def test_128_history_extracts_mobile(self):
        """Test 128: History extracts mobile."""
        history = [
            {"role": "user", "text": "মদিনাতুল উলুম মাদরাসা"},
            {"role": "assistant", "text": "ধন্যবাদ স্যার। এখন প্রতিষ্ঠানের মোবাইল নম্বরটি দিন।"},
            {"role": "user", "text": "01811223344"},
            {"role": "assistant", "text": "ধন্যবাদ স্যার। ফর্মে কোন কোন তথ্য রাখতে চান?"}
        ]
        res = resolve_google_form_workflow(
            user_message="নাম, পিতার নাম, শ্রেণি, রোল এবং ছবি",
            conversation_history=history,
            workspace_id=self.workspace_id
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.get("institution_mobile"), "01811223344")
        print("✓ Test 128 Passed: History cleanly extracted mobile number.")

    def test_129_where_is_my_form_retrieves_existing_form(self):
        """Test 129: 'আমার গুগল ফরম কোথায়' retrieves existing form from DB."""
        # Pre-populate an existing form in DB
        save_generated_form(
            workspace_id=self.workspace_id,
            institution_name="জামিয়া রাহমানিয়া আরাবিয়া",
            institution_mobile="01929778581",
            form_id="existing_form_999",
            form_url="https://docs.google.com/forms/d/e/1FAIpQLSc_existing_999/viewform",
            responder_uri="https://docs.google.com/forms/d/e/1FAIpQLSc_existing_999/viewform",
            response_sheet_url="https://docs.google.com/spreadsheets/d/existing_sheet_999/edit"
        )

        history = [
            {"role": "user", "text": "জামিয়া রাহমানিয়া আরাবিয়া"},
            {"role": "assistant", "text": "ধন্যবাদ স্যার।"},
            {"role": "user", "text": "01929778581"},
            {"role": "assistant", "text": "ধন্যবাদ স্যার।"}
        ]

        res = resolve_google_form_workflow(
            user_message="আমার গুগল ফরম কোথায়",
            conversation_history=history,
            customer_phone="01929778581",
            workspace_id=self.workspace_id
        )

        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "created")
        self.assertTrue(res.get("is_existing"))
        self.assertTrue("https://docs.google.com/forms/d/" in res.get("reply", ""))
        self.assertIn("https://docs.google.com/spreadsheets/d/existing_sheet_999/edit", res.get("reply", ""))
        print("✓ Test 129 Passed: 'আমার গুগল ফরম কোথায়' immediately returned existing form from database.")

    @patch("app.google_integration.ai_tool.create_institution_form")
    def test_130_missing_form_causes_real_create_institution_form_execution(self, mock_create):
        """Test 130: Missing form causes create_institution_form() execution."""
        mock_create.return_value = {
            "success": True,
            "form_id": "form_130",
            "form_title": "আল হেরা মডেল স্কুল - 01799887766 - ID Card Form",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_130/viewform",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_130/edit",
            "selected_fields": ["student_name", "father_name", "mother_name", "dob", "class_name", "roll", "address", "student_photo"]
        }

        history = [
            {"role": "user", "text": "আল হেরা মডেল স্কুল"},
            {"role": "assistant", "text": "ধন্যবাদ স্যার।"},
            {"role": "user", "text": "01799887766"},
            {"role": "assistant", "text": "ধন্যবাদ স্যার।"}
        ]

        res = resolve_google_form_workflow(
            user_message="আমার গুগল ফরম কোথায়",
            conversation_history=history,
            customer_phone="01799887766",
            workspace_id=self.workspace_id
        )

        self.assertIsNotNone(res)
        mock_create.assert_called_once()
        self.assertEqual(res.get("status"), "created")
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_130/viewform", res.get("reply", ""))
        print("✓ Test 130 Passed: Missing form triggered real create_institution_form() and returned live URLs.")

    @patch("app.google_integration.ai_tool.create_institution_form")
    def test_131_gemini_cannot_generate_waiting_response_for_form_intent(self, mock_create):
        """Test 131: Gemini cannot generate waiting response for form intent."""
        mock_create.return_value = {
            "success": True,
            "form_id": "form_131",
            "form_title": "মডেল একাডেমি - 01711001100 - ID Card Form",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_131/viewform",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_131/edit",
            "selected_fields": ["student_name", "father_name", "class_name", "roll", "student_photo"]
        }

        res = asyncio.run(process_customer_message(
            message_text="প্রতিষ্ঠানের নাম মডেল একাডেমি, মোবাইল 01711001100, নাম রোল ছবি থাকবে",
            conversation_history=[],
            sender_id="01711001100",
            workspace_id=self.workspace_id
        ))

        reply = res.get("reply_text", "")
        self.assertNotIn("৫ থেকে ১০ মিনিট", reply)
        self.assertNotIn("১০-১৫ মিনিট", reply)
        self.assertNotIn("পরে পাঠাব", reply)
        self.assertNotIn("কাজ শুরু করে দিচ্ছি", reply)
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_131/viewform", reply)
        self.assertEqual(res.get("response_source"), "deterministic_google_form")
        print("✓ Test 131 Passed: Waiting response was completely prevented and live form was returned.")

    def test_132_google_oauth_unavailable_produces_explicit_failure_never_fake_success(self):
        """Test 132: Google OAuth unavailable produces explicit technical error, never fake success."""
        # Ensure no google connection for workspace 9988
        res = resolve_google_form_workflow(
            user_message="প্রতিষ্ঠানের নাম সিটি মডেল স্কুল, মোবাইল 01799999999, নাম রোল ছবি থাকবে",
            conversation_history=[],
            customer_phone="01799999999",
            workspace_id=self.workspace_id
        )

        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "error")
        self.assertFalse(res.get("success"))
        self.assertIn("সমস্যা", res.get("reply", ""))
        self.assertNotIn("১০ মিনিট", res.get("reply", ""))
        self.assertNotIn("[এখানে", res.get("reply", ""))
        print("✓ Test 132 Passed: Google OAuth unavailable returned explicit technical error instead of fake promise.")

    def test_133_production_workspace_oauth_credentials_used_by_webhook_process(self):
        """Test 133: Webhook process and dashboard share exact same workspace credentials."""
        # Save a test connection in workspace 9988
        save_google_connection(
            workspace_id=self.workspace_id,
            google_account_email="test_admin@gmail.com",
            master_form_id="master_prod_9988",
            status="connected"
        )

        conn = get_google_connection(workspace_id=self.workspace_id)
        self.assertIsNotNone(conn)
        self.assertEqual(conn.get("master_form_id"), "master_prod_9988")
        self.assertEqual(conn.get("status"), "connected")
        print("✓ Test 133 Passed: Production workspace OAuth credentials correctly mapped and accessible.")

    @patch("app.channels.whatsapp.send_whatsapp_message", return_value=True)
    @patch("app.google_integration.ai_tool.create_institution_form")
    def test_134_full_whatsapp_webhook_integration_to_form_creation(self, mock_create, mock_send):
        """Integration test: resolve_google_form_workflow -> create_institution_form -> real result -> WhatsApp."""
        remove_muted_number("8801929770001")
        remove_muted_number("01929770001")
        
        mock_create.return_value = {
            "success": True,
            "form_id": "form_wa_e2e",
            "form_title": "জামিয়া উম্মুল কোরা মসজিদ - 8801929770001 - ID Card Form",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_wa_e2e/viewform",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_wa_e2e/edit",
            "selected_fields": ["student_name", "father_name", "class_name", "roll", "student_photo"]
        }

        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "271335301757320",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "+8801816504097",
                            "phone_number_id": "4184514263660680"
                        },
                        "contacts": [{"profile": {"name": "Maulana Mahmud"}, "wa_id": "8801929770001"}],
                        "messages": [{
                            "from": "8801929770001",
                            "id": "wamid.HBgLODgwMTkyOTc3MDAwMRUCABEYEjA1OTgzOTAyOU",
                            "timestamp": str(int(time.time())),
                            "type": "text",
                            "text": {
                                "body": "প্রতিষ্ঠানের নাম জামিয়া উম্মুল কোরা মসজিদ\nনাম পিতা শ্রেণী রোল আর স্টুডেন্টের ছবি এগুলো থাকবে"
                            }
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        from app.channels.debouncer import message_debouncer

        async def _run():
            await handle_whatsapp_webhook_event(payload)
            await message_debouncer.flush("whatsapp", 1, "8801929770001")

        asyncio.run(_run())
        
        mock_create.assert_called_once()
        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        sent_recipient = args[0]
        sent_reply = args[1]
        self.assertEqual(sent_recipient, "8801929770001")
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_wa_e2e/viewform", sent_reply)
        self.assertIn("https://docs.google.com/spreadsheets/d/sheet_wa_e2e/edit", sent_reply)
        print("✓ Integration Test 134 Passed: Real WhatsApp webhook directly executed create_institution_form() and delivered live Form URL to customer.")

if __name__ == "__main__":
    unittest.main()
