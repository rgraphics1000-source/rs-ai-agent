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
        self.assertEqual(res.get("voice_url"), "")
        self.assertIn("কোয়ালিটি", res.get("reply_text"))

    def test_07_phone_numbers_never_trigger_sample_or_quantity_workflow(self):
        # Sending a phone number must NEVER blast photos or be parsed as order quantity
        res1 = evaluate_id_card_workflow("01929778281", workspace_id=1)
        self.assertIsNone(res1)

        res2 = evaluate_id_card_workflow("01816504097", workspace_id=1)
        self.assertIsNone(res2)

        res3 = evaluate_id_card_workflow("আপনি whatsapp নাম্বার দিতে বলেছিলেন তাই দিলাম এগুলো কেন দিচ্ছেন", workspace_id=1)
        self.assertIsNone(res3)

    def test_08_initial_id_card_inquiry_sends_greeting_with_zero_photos(self):
        res = evaluate_id_card_workflow("আমি আইডি কার্ড করতে চাই", workspace_id=1)
        self.assertIsNotNone(res)
        self.assertIn("কত পিস প্রয়োজন", res.get("reply_text"))
        self.assertEqual(len(res.get("matched_images", [])), 0)
        self.assertEqual(len(res.get("media_sequence", [])), 0)

    def test_09_quantity_answer_prompts_permission_and_sends_packages_on_agreement(self):
        res1 = evaluate_id_card_workflow("৫০ পিস বানাবো", workspace_id=1)
        self.assertIsNotNone(res1)
        self.assertEqual(len(res1.get("matched_images", [])), 0)
        self.assertIn("স্যাম্পল ছবিগুলো পাঠাবো", res1.get("reply_text"))

        # Customer agrees to initial sample photos -> receives separate component samples (Cards, Fita, Covers)
        res2 = evaluate_id_card_workflow(
            "হ্যাঁ পাঠান",
            conversation_history=[
                {"sender": "user", "content": "৫০ পিস বানাবো"},
                {"sender": "bot", "content": res1.get("reply_text")}
            ],
            workspace_id=1
        )
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get("response_source"), "initial_component_samples_dispatch")
        self.assertGreaterEqual(len(res2.get("matched_images", [])), 20)

        # Customer asks for price -> bot asks to send Ready Packages
        res3 = evaluate_id_card_workflow(
            "কোনটার দাম কত?",
            conversation_history=[
                {"sender": "user", "content": "হ্যাঁ পাঠান"},
                {"sender": "bot", "content": res2.get("reply_text")}
            ],
            workspace_id=1
        )
        self.assertIsNotNone(res3)
        self.assertEqual(res3.get("response_source"), "ready_package_permission_prompt")

        # Customer agrees to Ready Packages -> receives 7 package images in serial order
        res4 = evaluate_id_card_workflow(
            "জি পাঠান",
            conversation_history=[
                {"sender": "user", "content": "কোনটার দাম কত?"},
                {"sender": "bot", "content": res3.get("reply_text")}
            ],
            workspace_id=1
        )
        self.assertIsNotNone(res4)
        self.assertEqual(res4.get("response_source"), "ready_package_dispatch")
        self.assertEqual(len(res4.get("matched_images", [])), 7)
        for img in res4.get("matched_images", []):
            self.assertIn("package", img.lower())

    def test_10_quality_spelling_variations_send_voice_note(self):
        variations = [
            "আপনাদের কোয়ালিটি সম্পরকে জানতে চাই",
            "কার্ড ও ফিতা এর কোয়ালিটি কেমন হবে",
            "কার্ড ও ফিতা এর কোয়ালিটি কেমন হবে",
            "কোয়ালিটি কেমন",
            "কোয়ালিটি কেমন",
            "কোয়ালিটি সম্পর্কে বলুন"
        ]
        for query in variations:
            res = evaluate_id_card_workflow(query, workspace_id=1)
            self.assertIsNotNone(res, f"Failed for query: {query}")
            self.assertEqual(res.get("voice_url"), "", f"Voice URL should be empty for query: {query}")
            self.assertEqual(len(res.get("matched_images", [])), 0, f"Must not blast images for query: {query}")

    def test_11_salam_is_only_returned_if_customer_gave_salam(self):
        # Without Salam
        res1 = evaluate_id_card_workflow("আমি আইডি কার্ড করতে চাই", workspace_id=1)
        self.assertIsNotNone(res1)
        self.assertTrue(res1["reply_text"].startswith("জি স্যার,"))
        self.assertNotIn("ওয়ালাইকুমুস সালাম", res1["reply_text"])

        # With Salam
        res2 = evaluate_id_card_workflow("আসসালামু আলাইকুম, আমি আইডি কার্ড করতে চাই", workspace_id=1)
        self.assertIsNotNone(res2)
        self.assertTrue(res2["reply_text"].startswith("ওয়ালাইকুমুস সালাম স্যার।"))

    def test_12_customer_refusal_is_politely_acknowledged_without_sales_pitch(self):
        refusal_msgs = [
            "আমি তো আইডি কার্ড বানাতে চাচ্ছি না",
            "লাগবে না তো আমার",
            "দরকার নাই",
            "বানাব না"
        ]
        for rm in refusal_msgs:
            res = evaluate_id_card_workflow(rm, workspace_id=1)
            self.assertIsNotNone(res, f"Failed for refusal: {rm}")
            self.assertEqual(res["response_source"], "customer_not_interested")
            self.assertIn("কোনো সমস্যা নেই", res["reply_text"])
            self.assertNotIn("ওয়ালাইকুমুস সালাম", res["reply_text"])
            self.assertNotIn("কত পিস", res["reply_text"])
            self.assertEqual(len(res.get("matched_images", [])), 0)

    def test_13_package_quoted_or_selected_asks_for_institution_details(self):
        # 1. Quoted package photo reply
        quoted_msg = "[কাস্টমার পূর্ববর্তী এই ছবির রিপ্লাই দিয়েছেন: IMG-20260113-WA0006.jpg]"
        res1 = evaluate_id_card_workflow(quoted_msg, workspace_id=1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1["response_source"], "id_card_package_selection_acknowledged")
        self.assertIn("চমৎকার পছন্দ", res1["reply_text"])
        self.assertIn("প্রতিষ্ঠানের নাম", res1["reply_text"])
        self.assertIn("গুগল ফর্ম", res1["reply_text"])

        # 2. Selecting package with "এটি" or "." after bot asked for package
        history = [
            {"role": "assistant", "content": "আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন স্যার।"}
        ]
        res2 = evaluate_id_card_workflow("এটি", conversation_history=history, workspace_id=1)
        self.assertIsNotNone(res2)
        self.assertEqual(res2["response_source"], "id_card_package_selection_acknowledged")
        self.assertIn("চমৎকার পছন্দ", res2["reply_text"])
        self.assertIn("প্রতিষ্ঠানের নাম", res2["reply_text"])

        # 3. Selecting package with "." or ","
        res3 = evaluate_id_card_workflow(".", conversation_history=history, workspace_id=1)
        self.assertIsNotNone(res3)
        self.assertEqual(res3["response_source"], "id_card_package_selection_acknowledged")
        self.assertIn("প্রতিষ্ঠানের নাম", res3["reply_text"])

    def test_15_specific_category_photo_requests(self):
        from app.ai_agent.gemini_brain import detect_sample_photos_to_send
        bot_cover_reply = "জি স্যার, অবশ্যই দিচ্ছি। আমাদের কাছে বেশ কয়েকটি প্রিমিয়াম ও চমৎকার মানের কভার রয়েছে। নিচে ছবিগুলো দেওয়া হলো স্যার:"
        
        # 1. Cover photo request with count and 'দিয়েন'
        imgs_cover = detect_sample_photos_to_send("দুইটা ভালো মানের কভারের ছবি দিয়েন তো", bot_reply=bot_cover_reply, workspace_id=1)
        self.assertEqual(len(imgs_cover), 2)
        for img in imgs_cover:
            self.assertIn("cover", img.lower())

        # 2. Additional cover photo request
        imgs_more_cover = detect_sample_photos_to_send("আরদুইটা ভালো মানের কভারের ছবি দিয়েন তো", bot_reply=bot_cover_reply, workspace_id=1)
        self.assertEqual(len(imgs_more_cover), 2)
        for img in imgs_more_cover:
            self.assertIn("cover", img.lower())

        # 3. Fita photo request
        bot_fita_reply = "জি স্যার, ফিতার স্যাম্পল নিচে দেওয়া হলো:"
        imgs_fita = detect_sample_photos_to_send("দুইটা ভালো মানের ফিতার ছবি দিয়েন", bot_reply=bot_fita_reply, workspace_id=1)
        self.assertEqual(len(imgs_fita), 2)
        for img in imgs_fita:
            self.assertIn("fita", img.lower())

if __name__ == "__main__":
    unittest.main()

