import unittest
import asyncio
import re
from app.database import init_db, get_db_connection, resolve_quoted_message_media
from app.ai_agent.gemini_brain import (
    has_customer_consented_or_requested_photos,
    process_customer_message,
    generate_smart_fallback_reply
)

class TestTextQuoteAndFutureInfoPromise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_01_text_quote_resolution_does_not_return_media(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversations (workspace_id, channel, sender_id, customer_name, last_message)
            VALUES (1, 'whatsapp', '8801816504097', 'Test Customer', 'ভাই সব নামগুলো দিয়েন')
        """)
        conv_id = cursor.lastrowid
        mid = "wamid.text_quote_test_001"
        cursor.execute("""
            INSERT INTO messages (
                conversation_id, sender_type, sender_role, message_type, content, media_url, external_message_id
            )
            VALUES (?, 'admin', 'ADMIN', 'text', 'ভাই সব নামগুলো দিয়েন', '', ?)
        """, (conv_id, mid))
        conn.commit()
        conn.close()

        res = resolve_quoted_message_media(mid, workspace_id=1)
        self.assertTrue(res)
        self.assertEqual(res.get("media_url"), "")
        self.assertEqual(res.get("content"), "ভাই সব নামগুলো দিয়েন")
        self.assertEqual(res.get("sender_role"), "ADMIN")

    def test_02_unresolved_quote_returns_empty_dict(self):
        res = resolve_quoted_message_media("non_existent_wamid_99999", workspace_id=1)
        self.assertEqual(res, {})

    def test_03_customer_promising_info_is_not_photo_consent(self):
        phrases = [
            "আজকের মধ্যে সব দিবো ইনশাআল্লাহ",
            "আজকের মধ্যে সব দিব ইনশাআল্লাহ",
            "আজকে সব দিব",
            "কালকে নামগুলো দিবো",
            "সব নামগুলো পাঠিয়ে দেব",
            "দিব ইনশাআল্লাহ",
            "আজকের মধ্যে সব দিবো ইনশাআল্লাহ [কাস্টমার পূর্ববর্তী এই বার্তার রিপ্লাই দিয়েছেন: \"ভাই সব নামগুলো দিয়েন\"]"
        ]
        for p in phrases:
            self.assertFalse(
                has_customer_consented_or_requested_photos(p),
                f"Expected False for phrase: {p}"
            )

    def test_04_namgulo_does_not_trigger_mug_inquiry(self):
        text = "ভাই সব নামগুলো দিয়েন"
        reply = generate_smart_fallback_reply(text, workspace_id=1)
        self.assertNotIn("মগ", reply)
        self.assertNotIn("সিরামিক", reply)

    def test_05_process_customer_message_on_info_promise(self):
        from app.database import enable_conversation_ai, remove_muted_number
        fresh_sender = "8801899997788"
        enable_conversation_ai(sender_id=fresh_sender, workspace_id=1)
        remove_muted_number(fresh_sender)

        q_msg = "আজকের মধ্যে সব দিবো ইনশাআল্লাহ [কাস্টমার পূর্ববর্তী এই বার্তার রিপ্লাই দিয়েছেন: \"ভাই সব নামগুলো দিয়েন\"]"
        res = asyncio.run(process_customer_message(
            q_msg,
            conversation_history=[],
            customer_name="Test Customer",
            sender_id=fresh_sender,
            workspace_id=1
        ))
        reply = res.get("reply_text", "")
        images = res.get("matched_images", [])

        # Strict checks
        self.assertEqual(images, [], "No images should be dispatched when customer is promising to send data.")
        self.assertNotIn("স্যাম্পল ছবিগুলো দেওয়া হলো", reply)
        self.assertNotIn("রেডি প্যাকেজের ছবি", reply)
        self.assertNotIn("সিরামিক মগ", reply)
        self.assertTrue(any(k in reply for k in ["ইনশাআল্লাহ", "তথ্য", "কাজ"]), f"Unexpected reply: {reply}")

if __name__ == "__main__":
    unittest.main()
