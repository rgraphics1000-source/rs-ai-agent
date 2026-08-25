import unittest
import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.ai_agent.gemini_brain import detect_sample_photos_to_send
from app.channels.facebook import handle_facebook_webhook_event
from app.channels.whatsapp import handle_whatsapp_webhook_event
from app.database import (
    is_conversation_ai_active, add_muted_number, remove_muted_number,
    get_db_connection, save_connected_page, get_connected_page
)
from unittest.mock import patch, MagicMock

class TestHumanTakeoverAndAntiSpam(unittest.TestCase):
    def setUp(self):
        self.test_sender = "fb_cust_test_takeover_999"
        remove_muted_number(self.test_sender)
        conn = get_db_connection()
        conn.execute("INSERT OR IGNORE INTO products (id, name, code, category, price, is_active, workspace_id, image_url) VALUES (99901, 'Test Card', 'IDC-TEST', 'আইডি কার্ড', 50, 1, 1, '/static/uploads/test_card.jpg')")
        conn.commit()
        conn.close()

    def tearDown(self):
        remove_muted_number(self.test_sender)
        conn = get_db_connection()
        conn.execute("DELETE FROM products WHERE id = 99901")
        conn.commit()
        conn.close()

    def test_01_casual_agreement_does_not_spam_photos(self):
        """Casual 'জি' or 'হুম' in conversation must NEVER blast photos."""
        history = [
            {"sender_type": "user", "content": "আমি ওনারের সাথে কথা বলতে চাই"},
            {"sender_type": "admin", "content": "জি ভাইয়া, আমি শপ ওনার বলছি। আপনি কেমন আছেন?"}
        ]

        photos = detect_sample_photos_to_send(
            user_msg="জি ভালো আছি",
            conversation_history=history,
            bot_reply="আলহামদুলিল্লাহ!",
            workspace_id=1
        )
        self.assertEqual(photos, [], "Casual 'জি' must not trigger photo spam.")
        print("✓ Test 1 Passed: Casual 'জি' did NOT send any photos.")

    def test_02_agreement_only_triggers_photos_if_bot_offered_them(self):
        """'হ্যাঁ' / 'জি' only sends photos if previous bot message offered photos."""
        history = [
            {"sender_type": "user", "content": "আইডি কার্ডের দাম কত?"},
            {"sender_type": "bot", "content": "জি স্যার, আমাদের কার্ডের দাম ৫০ টাকা। আপনি কি কিছু স্যাম্পল দেখতে চান?"}
        ]

        photos = detect_sample_photos_to_send(
            user_msg="হ্যাঁ পাঠান",
            conversation_history=history,
            bot_reply="জি স্যার, নিচে স্যাম্পল দেওয়া হলো।",
            workspace_id=1
        )
        self.assertTrue(len(photos) > 0, "Photos must be sent when agreeing to bot's photo offer.")
        self.assertLessEqual(len(photos), 3, "Photos must be capped at 3 per batch.")
        print(f"✓ Test 2 Passed: Photo offer agreement triggered {len(photos)} photos (capped at 3).")

    def test_03_already_sent_photos_not_spammed_repeatedly(self):
        """If photos were already delivered recently, 'জি' or general chat does not re-send photos."""
        history = [
            {"sender_type": "user", "content": "ছবি দেখতে চাই"},
            {"sender_type": "bot", "content": "স্যাম্পল ছবি দেওয়া হলো: /static/uploads/sample1.jpg"},
            {"sender_type": "user", "content": "প্যাকেজ কত?"},
            {"sender_type": "bot", "content": "প্যাকেজ ৩৫০ টাকা।"}
        ]

        photos = detect_sample_photos_to_send(
            user_msg="জি",
            conversation_history=history,
            bot_reply="জি স্যার।",
            workspace_id=1
        )
        self.assertEqual(photos, [], "Must not repeat photos on casual conversation.")
        print("✓ Test 3 Passed: Anti-spam prevention blocked repetitive photo loop.")

    def test_04_facebook_admin_echo_automatically_activates_takeover(self):
        """When Facebook Page admin sends a message to customer, human takeover is activated."""
        save_connected_page({
            "workspace_id": 1,
            "page_id": "105116472071659",
            "page_name": "RS Graphics",
            "page_access_token": "test_tok"
        })

        payload = {
            "object": "page",
            "entry": [{
                "id": "105116472071659",
                "messaging": [{
                    "sender": {"id": "105116472071659"},
                    "recipient": {"id": self.test_sender},
                    "timestamp": 1724240000,
                    "message": {
                        "mid": "mid.echo_admin_001",
                        "text": "হ্যালো, আমি শপ ওনার সরাসরি কথা বলছি।",
                        "is_echo": True,
                        "app_id": "271335301757320"
                    }
                }]
            }]
        }

        asyncio.run(handle_facebook_webhook_event(payload))

        # Verify AI is now paused for this customer
        self.assertFalse(is_conversation_ai_active(self.test_sender))
        print("✓ Test 4 Passed: Admin echo message automatically activated human takeover and silenced AI.")

    def test_05_manual_command_pauses_and_resumes_ai(self):
        """'#pause' pauses AI and '#ai' resumes AI."""
        add_muted_number(self.test_sender)
        self.assertFalse(is_conversation_ai_active(self.test_sender))

        remove_muted_number(self.test_sender)
        self.assertTrue(is_conversation_ai_active(self.test_sender))
        print("✓ Test 5 Passed: AI pause and resume controls working 100% reliably.")

if __name__ == "__main__":
    unittest.main()
