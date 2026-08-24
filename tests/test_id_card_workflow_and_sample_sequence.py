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
        self.assertIn("কত পিস বানাবেন", res["reply_text"])
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

    def test_05_quantity_80_to_100_triggers_full_sequence_with_review_link_packages_and_voice(self):
        """Quantity >= 80 (e.g. 80, 90, 100 pcs) sends: Cards -> Text 1 -> Fita -> Text 2 -> Covers -> Review Link -> Packages -> Voice Note."""
        res = evaluate_id_card_workflow(
            message_text="১০০ পিস বানাবো",
            customer_name="Al-Amin",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertIn("স্যাম্পল", res["reply_text"])
        seq = res["media_sequence"]
        
        # Verify sequence components
        types = [s["type"] for s in seq]
        self.assertIn("images", types)
        self.assertIn("text", types)
        self.assertIn("voice", types)
        
        # Verify review link presence
        text_contents = [s.get("text", "") for s in seq if s["type"] == "text"]
        self.assertTrue(any(REVIEW_FACEBOOK_POST_URL in t for t in text_contents))
        
        # Verify cards text and fita text
        self.assertTrue(any("আমাদের কার্ড" in t for t in text_contents))
        self.assertTrue(any("প্রিন্ট করা ফিতা" in t for t in text_contents))
        
        # Verify package images in sequence
        pkg_seq = [s for s in seq if s.get("category") == "package"]
        self.assertEqual(len(pkg_seq), 1)
        self.assertEqual(len(pkg_seq[0]["urls"]), 7)
        
        # Verify voice note in sequence
        voice_seq = [s for s in seq if s["type"] == "voice"]
        self.assertEqual(len(voice_seq), 1)
        self.assertEqual(voice_seq[0]["url"], VOICE_PACKAGE_SPECIAL_OFFER)
        self.assertEqual(res["voice_url"], VOICE_PACKAGE_SPECIAL_OFFER)

    def test_06_quantity_30_to_40_triggers_sequence_with_10tk_rule_and_no_voice(self):
        """Quantity 30-40 pcs sends sequence with +10 TK rule explanation and NO voice note."""
        res = evaluate_id_card_workflow(
            message_text="৪০ পিস আইডি কার্ড বানাবো",
            customer_name="Kawsar Ahmed",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        seq = res["media_sequence"]
        
        # Verify NO voice note
        voice_seq = [s for s in seq if s["type"] == "voice"]
        self.assertEqual(len(voice_seq), 0)
        self.assertEqual(res["voice_url"], "")
        
        # Verify +10 TK rule explanation text
        text_contents = [s.get("text", "") for s in seq if s["type"] == "text"]
        self.assertTrue(any("১০ টাকা করে বৃদ্ধি হবে" in t for t in text_contents))
        self.assertTrue(any(REVIEW_FACEBOOK_POST_URL in t for t in text_contents))

    def test_07_quantity_50_to_60_triggers_sequence_with_fixed_catalog_rate_and_no_voice(self):
        """Quantity 50-60 pcs sends sequence with fixed regular rate explanation and NO voice note."""
        res = evaluate_id_card_workflow(
            message_text="৫০ পিস বানাবো",
            customer_name="Kawsar Ahmed",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        seq = res["media_sequence"]
        
        # Verify NO voice note
        voice_seq = [s for s in seq if s["type"] == "voice"]
        self.assertEqual(len(voice_seq), 0)
        self.assertEqual(res["voice_url"], "")
        
        # Verify fixed regular rate text
        text_contents = [s.get("text", "") for s in seq if s["type"] == "text"]
        self.assertTrue(any("রেগুলার মূল্যে" in t for t in text_contents))
        self.assertTrue(any(REVIEW_FACEBOOK_POST_URL in t for t in text_contents))

    def test_08_direct_package_request(self):
        """Customer asking 'প্যাকেজের ছবি দিন' receives Review Link and 7 Package photos."""
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
        self.assertIn("৮২ টাকা", prompt)
        self.assertIn("৫ টাকা", prompt)

if __name__ == "__main__":
    unittest.main()
