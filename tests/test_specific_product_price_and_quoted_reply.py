import unittest
import os
import sqlite3
from app.database import get_db_connection, init_db, resolve_quoted_message_media, ensure_default_products
from app.ai_agent.gemini_brain import generate_smart_fallback_reply, evaluate_id_card_workflow

class TestSpecificProductPriceAndQuotedReply(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        ensure_default_products()

    def test_01_ensure_default_products_populated(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, name, price FROM products WHERE workspace_id = 1")
        rows = cursor.fetchall()
        conn.close()
        codes = [r["code"] for r in rows]
        self.assertIn("COV-T014V-10", codes)
        self.assertIn("FITA-2CM-28", codes)
        self.assertIn("IDC-UV-35", codes)

    def test_02_resolve_quoted_message_media(self):
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversations (workspace_id, channel, sender_id, customer_name, last_message)
            VALUES (1, 'facebook', 'fb_test_quote_user_1', 'Test Customer', 'Sample photo')
        """)
        conv_id = cursor.lastrowid
        cursor.execute("""
            INSERT INTO messages (
                conversation_id, sender_type, message_type, content, media_url, external_message_id
            )
            VALUES (?, 'bot', 'image', 'T-014V Soft Cover', '/static/uploads/cover/T-014V_SOFT_COVER_10_TK_4.png', 'mid_test_12345')
        """, (conv_id,))
        conn.commit()
        conn.close()

        resolved = resolve_quoted_message_media("mid_test_12345", workspace_id=1)
        self.assertTrue(resolved)
        self.assertEqual(resolved.get("filename"), "T-014V_SOFT_COVER_10_TK_4.png")
        self.assertIn("/static/uploads/cover/T-014V_SOFT_COVER_10_TK_4.png", resolved.get("media_url"))

    def test_03_fallback_specific_cover_pricing(self):
        reply_t014 = generate_smart_fallback_reply("এই কভার টা কত করে [কাস্টমার পূর্ববর্তী এই ছবির রিপ্লাই দিয়েছেন: T-014V_SOFT_COVER_10_TK_4.png]", workspace_id=1)
        self.assertIn("১০", reply_t014)
        self.assertIn("T-014V", reply_t014)

        reply_dx = generate_smart_fallback_reply("DX কভার কত টাকা?", workspace_id=1)
        self.assertIn("১২", reply_dx)

        reply_metal = generate_smart_fallback_reply("মেটাল কভারের দাম কত?", workspace_id=1)
        self.assertIn("৩০", reply_metal)

    def test_04_fallback_specific_fita_and_card_pricing(self):
        reply_fita = generate_smart_fallback_reply("এই ফিতার দাম কত", workspace_id=1)
        self.assertIn("২৮", reply_fita)

        reply_card = generate_smart_fallback_reply("এই কার্ডের দাম কত", workspace_id=1)
        self.assertIn("৩৫", reply_card)

    def test_05_evaluate_id_card_workflow_does_not_block_specific_item_inquiry(self):
        # A specific price inquiry must NOT be intercepted by the generic "আইডি কার্ড কত পিস বানাবেন" gate
        res1 = evaluate_id_card_workflow("এই ফিতার দাম কত", workspace_id=1)
        self.assertIsNone(res1)

        res2 = evaluate_id_card_workflow("এই কভার টা কত করে", workspace_id=1)
        self.assertIsNone(res2)

    def test_06_quality_inquiry_sends_quality_voice_note(self):
        res = evaluate_id_card_workflow("আপনাদের কার্ড ও ফিতার কোয়ালিটি কেমন হবে?", workspace_id=1)
        self.assertIsNotNone(res)
        self.assertIn("id_card_and_fita_quality.aac", res.get("voice_url"))
        self.assertIn("কোয়ালিটি ও বৈশিষ্ট্য", res.get("reply_text"))

if __name__ == "__main__":
    unittest.main()
