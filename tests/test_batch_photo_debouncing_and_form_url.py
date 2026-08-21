import unittest
import asyncio
import sys
import os
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import patch, MagicMock
from app.channels.whatsapp import handle_whatsapp_webhook_event
from app.google_integration.ai_tool import resolve_google_form_workflow
from app.database import (
    save_generated_form, get_db_connection, remove_muted_number
)

class TestBatchPhotoDebouncingAndFormUrl(unittest.TestCase):
    def setUp(self):
        self.test_phone = "8801929778581"
        remove_muted_number(self.test_phone)

    def tearDown(self):
        remove_muted_number(self.test_phone)

    @patch("app.channels.whatsapp.send_whatsapp_message", return_value=True)
    @patch("app.channels.whatsapp.process_customer_message")
    def test_01_batch_5_photos_produces_single_ai_reply(self, mock_process, mock_send):
        """When customer sends 5 photos simultaneously, AI processes them as 1 turn and sends 1 reply."""
        async def fake_process(**kwargs):
            return {
                "reply_text": "জি স্যার, আপনার ৫টি ছবি পেয়েছি। আমরা চমৎকার প্রিন্টিং করে দেব।",
                "matched_images": []
            }
        mock_process.side_effect = fake_process

        # Simulate WhatsApp payload with 5 images sent together
        now_ts = str(int(time.time()))
        messages = [
            {
                "from": self.test_phone,
                "id": f"wamid.batch_img_{i}_{now_ts}",
                "timestamp": now_ts,
                "type": "image",
                "image": {"id": f"img_id_{i}", "caption": f"ছবি {i}" if i == 0 else ""}
            }
            for i in range(5)
        ]

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
                        "contacts": [{"profile": {"name": "Customer Mahmud"}, "wa_id": self.test_phone}],
                        "messages": messages
                    },
                    "field": "messages"
                }]
            }]
        }

        asyncio.run(handle_whatsapp_webhook_event(payload))

        # Verify process_customer_message was called EXACTLY ONCE for all 5 images
        self.assertEqual(mock_process.call_count, 1, "Must call AI brain exactly once for 5 photos in one batch.")
        # Verify WhatsApp sent reply EXACTLY ONCE
        self.assertEqual(mock_send.call_count, 1, "Must send exactly one reply to the customer, not 5 separate replies.")
        print("✓ Test 1 Passed: 5 photos simultaneously debounced into exactly 1 AI call and 1 response.")

    @patch("app.channels.whatsapp.send_whatsapp_message")
    @patch("app.channels.whatsapp.process_customer_message")
    def test_02_stale_message_does_not_trigger_ai(self, mock_process, mock_send):
        """Messages older than 30 minutes do not trigger retroactive AI reply."""
        async def fake_process(**kwargs):
            return {"reply_text": "reply"}
        mock_process.side_effect = fake_process
        old_ts = str(int(time.time()) - 3600) # 1 hour ago (stale)
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
                        "contacts": [{"profile": {"name": "Customer Mahmud"}, "wa_id": self.test_phone}],
                        "messages": [{
                            "from": self.test_phone,
                            "id": f"wamid.stale_{old_ts}",
                            "timestamp": old_ts,
                            "type": "text",
                            "text": {"body": "পুরাতন মেসেজ"}
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        asyncio.run(handle_whatsapp_webhook_event(payload))
        mock_process.assert_not_called()
        mock_send.assert_not_called()
        print("✓ Test 2 Passed: Stale message (>5m) skipped AI reply generation without back-to-back storm.")

    def test_03_existing_form_returns_canonical_form_id_url(self):
        """Verify existing form returns https://docs.google.com/forms/d/{form_id}/viewform."""
        # Save a record with legacy /forms/d/e/... in DB
        save_generated_form(
            workspace_id=1,
            institution_name="খাদিমুল কুরআন মাদ্রাসা",
            institution_mobile="01929778581",
            form_id="1rMRMmos-MBWXyX2U3NT7IptnofTn7lV7CyN8bsh1r3E",
            form_url="https://docs.google.com/forms/d/e/1FAIpQLScQs80089RHpbKM7iu8R5ssHUQZYGxzOUlBZvpqrzpckVsWjw/viewform",
            responder_uri="https://docs.google.com/forms/d/e/1FAIpQLScQs80089RHpbKM7iu8R5ssHUQZYGxzOUlBZvpqrzpckVsWjw/viewform",
            response_sheet_url="https://docs.google.com/spreadsheets/d/14vIV4slkdUtE5jmAaixk-dPIKv5Wvbmfip30KlN1C4c/edit"
        )

        res = resolve_google_form_workflow(
            user_message="আমার গুগল ফর্মের লিঙ্ক দেন",
            conversation_history=[],
            customer_phone="01929778581",
            workspace_id=1
        )

        self.assertIsNotNone(res)
        self.assertEqual(res.get("form_url"), "https://docs.google.com/forms/d/1rMRMmos-MBWXyX2U3NT7IptnofTn7lV7CyN8bsh1r3E/viewform")
        self.assertIn("https://docs.google.com/forms/d/1rMRMmos-MBWXyX2U3NT7IptnofTn7lV7CyN8bsh1r3E/viewform", res.get("reply", ""))
        self.assertNotIn("1FAIpQLScQs80089", res.get("reply", ""))
        print("✓ Test 3 Passed: Form resolution returned exact canonical cloned form URL (https://docs.google.com/forms/d/1rMRMmos-MBWXyX2U3NT7IptnofTn7lV7CyN8bsh1r3E/viewform).")

if __name__ == "__main__":
    unittest.main()
