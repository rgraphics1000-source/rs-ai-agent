import unittest
import asyncio
from app.ai_agent.gemini_brain import (
    extract_order_quantity_number,
    get_id_card_sample_images,
    get_fita_sample_images,
    get_cover_sample_images,
    get_package_sample_images,
    build_full_sample_sequence,
    evaluate_id_card_workflow,
    process_customer_message,
    REVIEW_FACEBOOK_POST_URL,
    VOICE_PACKAGE_SPECIAL_OFFER
)

class TestIdCardWorkflowAndSampleSequence(unittest.IsolatedAsyncioTestCase):

    def test_01_extract_order_quantity_number(self):
        """Test Bengali and English quantity extraction."""
        self.assertEqual(extract_order_quantity_number("আমি ৫০ পিস বানাবো"), 50)
        self.assertEqual(extract_order_quantity_number("100 pcs id card"), 100)
        self.assertEqual(extract_order_quantity_number("১০ পিস হবে?"), 10)
        self.assertEqual(extract_order_quantity_number("১৫ টা কার্ড"), 15)
        self.assertEqual(extract_order_quantity_number("৩০ পিস অর্ডার"), 30)
        self.assertEqual(extract_order_quantity_number("৮০ পিস লাগবে"), 80)
        self.assertEqual(extract_order_quantity_number("৯০ টা"), 90)
        self.assertEqual(extract_order_quantity_number("আমি আইডি কার্ড বানাতে চাই"), None)

    def test_02_sample_media_counts(self):
        """Verify sample images loaded: 15 Cards, 8 Fita, 8 Covers, 7 Packages."""
        card_imgs = get_id_card_sample_images()
        fita_imgs = get_fita_sample_images()
        cover_imgs = get_cover_sample_images()
        pkg_imgs = get_package_sample_images()

        self.assertGreaterEqual(len(card_imgs), 15, "Must have at least 15 ID card images.")
        self.assertGreaterEqual(len(fita_imgs), 8, "Must have at least 8 Fita images.")
        self.assertGreaterEqual(len(cover_imgs), 8, "Must have at least 8 Cover images.")
        self.assertEqual(len(pkg_imgs), 7, "Must have exactly 7 Package images.")

    def test_03_inquiry_without_quantity_asks_how_many_pieces(self):
        """'আমি আইডি কার্ড বানাতে চাই' without quantity triggers 'আপনি আইডি কার্ড কত পিস বানাবেন?'."""
        res = evaluate_id_card_workflow(
            message_text="আমি আইডি কার্ড বানাতে চাই",
            customer_name="Kamrul Hasan",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertIn("কত পিস", res["reply_text"])
        self.assertEqual(len(res["media_sequence"]), 0)

    def test_04_inquiry_with_under_30_quantity_triggers_moq(self):
        """Quantity < 30 (e.g. 10, 15, 20 pcs) politely rejects with MOQ 30 rule."""
        res = evaluate_id_card_workflow(
            message_text="১০ পিস বানাবো",
            customer_name="Rahim Uddin",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertIn("সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস", res["reply_text"])
        self.assertEqual(len(res["media_sequence"]), 0)

    def test_05_stating_quantity_asks_sample_permission(self):
        """Stating quantity (e.g. 50, 100, 500 pcs) asks permission: 'আমাদের স্যাম্পলগুলো পাঠাবো কি?'."""
        res = evaluate_id_card_workflow(
            message_text="১০০ পিস বানাবো",
            customer_name="Al-Amin",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])
        self.assertEqual(len(res["media_sequence"]), 0)
        self.assertEqual(res["response_source"], "id_card_ask_sample_permission")

    def test_06_confirming_permission_triggers_full_sequence(self):
        """Replying 'হ্যাঁ পাঠান' after permission request triggers full sequence with review and packages."""
        history = [
            {"sender": "user", "content": "১০০ পিস আইডি কার্ড করব"},
            {"sender": "bot", "content": "জি স্যার, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
        ]
        res = evaluate_id_card_workflow(
            message_text="হ্যাঁ পাঠান",
            customer_name="Al-Amin",
            conversation_history=history,
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertIn("স্যাম্পলগুলো পাঠিয়ে দিচ্ছি", res["reply_text"])
        seq = res["media_sequence"]

        # Verify sequence components
        types = [s["type"] for s in seq]
        self.assertIn("images", types)
        self.assertIn("text", types)
        self.assertIn("voice", types)

        # Verify review link presence
        text_contents = [s.get("text", "") for s in seq if s["type"] == "text"]
        self.assertTrue(any(REVIEW_FACEBOOK_POST_URL in t for t in text_contents))
        self.assertTrue(any("এগুলো আমাদের কার্ড" in t for t in text_contents))
        self.assertTrue(any("এগুলো আমাদের প্রিন্ট করা ফিতা" in t for t in text_contents))

        # Verify card, fita, cover, package images in sequence
        pkg_seq = [s for s in seq if s.get("category") == "package"]
        self.assertEqual(len(pkg_seq), 1)
        self.assertEqual(len(pkg_seq[0]["urls"]), 7)

        card_seq = [s for s in seq if s.get("category") == "id_card"]
        self.assertEqual(len(card_seq), 1)
        self.assertGreaterEqual(len(card_seq[0]["urls"]), 15)

        fita_seq = [s for s in seq if s.get("category") == "fita"]
        self.assertEqual(len(fita_seq), 1)
        self.assertGreaterEqual(len(fita_seq[0]["urls"]), 8)

        cover_seq = [s for s in seq if s.get("category") == "cover"]
        self.assertEqual(len(cover_seq), 1)
        self.assertGreaterEqual(len(cover_seq[0]["urls"]), 8)

        # Verify voice note in sequence
        voice_seq = [s for s in seq if s["type"] == "voice"]
        self.assertEqual(len(voice_seq), 1)
        self.assertEqual(voice_seq[0]["url"], VOICE_PACKAGE_SPECIAL_OFFER)
        self.assertEqual(res["voice_url"], VOICE_PACKAGE_SPECIAL_OFFER)

    def test_07_package_pricing_inquiry_returns_breakdown(self):
        """Asking package price states price is written on images and gives 7-package text breakdown."""
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজের দাম কত",
            customer_name="Kawsar Ahmed",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertIn("প্রতিটি প্যাকেজের ছবির সাথে দাম লেখা আছে", res["reply_text"])
        self.assertIn("প্যাকেজ ১", res["reply_text"])
        self.assertIn("৭০ টাকা", res["reply_text"])
        self.assertIn("প্যাকেজ ৭", res["reply_text"])
        self.assertIn("৯১ টাকা", res["reply_text"])
        self.assertEqual(res["response_source"], "id_card_package_pricing_breakdown")

    def test_08_direct_package_request(self):
        """Customer asking 'প্যাকেজের ছবি দিন' receives full sequence with Review Link and Packages."""
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজের ছবি দিন",
            customer_name="Mamun",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "package_sample_dispatch")
        seq = res["media_sequence"]
        text_contents = [s.get("text", "") for s in seq if s["type"] == "text"]
        self.assertTrue(any(REVIEW_FACEBOOK_POST_URL in t for t in text_contents))
        pkg_seq = [s for s in seq if s.get("category") == "package"]
        self.assertEqual(len(pkg_seq), 1)
        self.assertEqual(len(pkg_seq[0]["urls"]), 7)

    def test_09_master_prompt_persona_and_negotiation_rules(self):
        """Verify Nadim persona, Owner Sir addressing protocol, and Step-by-step negotiation."""
        from app.ai_agent.gemini_brain import build_system_instruction
        prompt = build_system_instruction(workspace_id=1)

        # Agent name Nadim and Owner Md Rashedul Islam
        self.assertIn("নাদিম", prompt)
        self.assertIn("মোহাম্মদ রাশেদুল ইসলাম", prompt)
        self.assertIn("ওনার স্যার", prompt)

        # Step-by-step negotiation rules
        self.assertIn("ধাপে ধাপে", prompt)
        self.assertIn("শুরুতে সবসময় প্যাকেজের নির্ধারিত রেগুলার রেট", prompt)
    def test_10_quantity_change_after_samples_sent_explains_tier_rule(self):
        """When packages were already sent in chat and customer asks 'আর যদি ৩০ পিস করাই', answer +10 TK rule immediately."""
        history = [
            {"sender": "user", "content": "১০০ পিস বানাব"},
            {"sender": "bot", "content": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"},
            {"sender": "bot", "content": "আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন স্যার।"}
        ]
        res = evaluate_id_card_workflow(
            message_text="আর যদি ৩০ পিস করাই",
            customer_name="MD Rashadul Islam",
            conversation_history=history,
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "id_card_tier_text_reply")
        self.assertIn("১০ টাকা করে বেশি হবে", res["reply_text"])
        self.assertEqual(len(res["media_sequence"]), 0)
        self.assertEqual(len(res["matched_images"]), 0)

    def test_11_samples_already_sent_acknowledgment_without_resending_photos(self):
        """When customer says 'স্যাম্পলগুলো তো পাঠিয়েছেন', acknowledge politely with zero photos."""
        history = [
            {"sender": "bot", "content": "জি স্যার, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
        ]
        res = evaluate_id_card_workflow(
            message_text="স্যাম্পলগুলো তো পাঠিয়েছেন",
            customer_name="MD Rashadul Islam",
            conversation_history=history,
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "samples_already_sent_acknowledged")
        self.assertIn("আন্তরিকভাবে দুঃখিত", res["reply_text"])
        self.assertIn("কোন প্যাকেজটি পছন্দ", res["reply_text"])
        self.assertEqual(len(res["media_sequence"]), 0)
        self.assertEqual(len(res["matched_images"]), 0)

    def test_12_specific_package_price_confirmation(self):
        """When customer asks 'প্যাকেজ ৬, ১০০+ অর্ডারে কত??', respond with 83 Tk directly without sending sample images."""
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজ ৬, ১০০+ অর্ডারে কত??",
            customer_name="MD Rashadul Islam",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "specific_package_price_confirmed")
        self.assertIn("৮৩ টাকা", res["reply_text"])
        self.assertEqual(len(res["media_sequence"]), 0)
        self.assertEqual(len(res["matched_images"]), 0)

    def test_13_prevent_duplicate_sample_dispatch_when_already_sent(self):
        """When samples were already sent in history, asking general package/sample doesn't blast all images again."""
        history = [
            {"sender": "bot", "content": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"},
            {"sender": "bot", "media_url": "/uploads/package/wa0002.jpg"}
        ]
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজ",
            customer_name="MD Rashadul Islam",
            conversation_history=history,
            workspace_id=1
        )
        # Should not re-dispatch full 30 images
        if res is not None and res.get("response_source") == "package_sample_dispatch":
            self.fail("Should not re-dispatch package samples when already sent in history!")

if __name__ == "__main__":
    unittest.main()
