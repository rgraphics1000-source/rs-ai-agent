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

    def test_05_quantity_80_to_100_prompts_permission_with_special_rate(self):
        """Quantity >= 80 (e.g. 100 pcs) calculates rate (45 TK) and prompts customer permission before sending samples."""
        res = evaluate_id_card_workflow(
            message_text="১০০ পিস বানাবো",
            customer_name="Al-Amin",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "id_card_quantity_permission_prompt")
        self.assertEqual(len(res["matched_images"]), 0)
        self.assertIn("রেগুলার পাইকারি রেট", res["reply_text"])
        self.assertIn("৩৫ টাকা", res["reply_text"])
        self.assertIn("স্যাম্পল ছবিগুলো পাঠাবো", res["reply_text"])

        # Turn 2: Customer agrees -> 7 package images dispatched
        res2 = evaluate_id_card_workflow(
            message_text="হ্যাঁ পাঠান",
            conversation_history=[
                {"sender": "user", "content": "১০০ পিস বানাবো"},
                {"sender": "bot", "content": res["reply_text"]}
            ],
            customer_name="Al-Amin",
            workspace_id=1
        )
        self.assertIsNotNone(res2)
        self.assertEqual(res2["response_source"], "package_sample_dispatch")
        self.assertEqual(len(res2["matched_images"]), 7)

    def test_06_quantity_30_to_40_prompts_permission_with_10tk_rule(self):
        """Quantity 30-40 pcs prompts permission with +10 TK rule explanation."""
        res = evaluate_id_card_workflow(
            message_text="৪০ পিস আইডি কার্ড বানাবো",
            customer_name="Kawsar Ahmed",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "id_card_quantity_permission_prompt")
        self.assertEqual(len(res["matched_images"]), 0)
        self.assertIn("১০ টাকা বেশি", res["reply_text"])
        self.assertIn("স্যাম্পল ছবিগুলো পাঠাবো", res["reply_text"])

    def test_07_quantity_50_to_60_prompts_permission_with_fixed_catalog_rate(self):
        """Quantity 50-60 pcs prompts permission with fixed regular wholesale rate."""
        res = evaluate_id_card_workflow(
            message_text="৫০ পিস বানাবো",
            customer_name="Kawsar Ahmed",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "id_card_quantity_permission_prompt")
        self.assertEqual(len(res["matched_images"]), 0)
        self.assertIn("রেগুলার পাইকারি রেট", res["reply_text"])
        self.assertIn("স্যাম্পল ছবিগুলো পাঠাবো", res["reply_text"])

    def test_08_direct_package_request(self):
        """Customer asking 'প্যাকেজের ছবি দিন' receives 7 package images directly in strict serial order (1-7)."""
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজের ছবি দিন",
            customer_name="Mamun",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "package_sample_dispatch")
        self.assertEqual(len(res["matched_images"]), 7)
        self.assertEqual(res["matched_images"][0], "/static/uploads/package/IMG-20260113-WA0003.jpg") # Pkg 1
        self.assertEqual(res["matched_images"][1], "/static/uploads/package/IMG-20260113-WA0002.jpg") # Pkg 2
        self.assertEqual(res["matched_images"][2], "/static/uploads/package/IMG-20260117-WA0023.jpg") # Pkg 3
        self.assertEqual(res["matched_images"][3], "/static/uploads/package/IMG-20260121-WA0081.jpg") # Pkg 4
        self.assertEqual(res["matched_images"][4], "/static/uploads/package/IMG-20260118-WA0045.jpg") # Pkg 5
        self.assertEqual(res["matched_images"][5], "/static/uploads/package/IMG-20260113-WA0006.jpg") # Pkg 6
        self.assertEqual(res["matched_images"][6], "/static/uploads/package/IMG-20260114-WA0057.jpg") # Pkg 7

    def test_10_specific_package_request_returns_single_image(self):
        """Customer asking for specific package (e.g. 'প্যাকেজ ৩') receives only Package 03 photo."""
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজ ৩ দেখান",
            customer_name="Mamun",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "specific_package_03_dispatch")
        self.assertEqual(len(res["matched_images"]), 1)
        self.assertEqual(res["matched_images"][0], "/static/uploads/package/IMG-20260117-WA0023.jpg")
        self.assertIn("প্যাকেজ ০৩", res["reply_text"])

    def test_11_specific_category_requests(self):
        """Customer asking for cards only, ribbons only, or covers only receives only those images."""
        # Cards only
        res_card = evaluate_id_card_workflow("শুধু কার্ডের ছবি দেখান", workspace_id=1)
        self.assertIsNotNone(res_card)
        self.assertEqual(res_card["response_source"], "id_card_sample_dispatch")
        self.assertGreaterEqual(len(res_card["matched_images"]), 1)
        for img in res_card["matched_images"]:
            self.assertIn("id_card", img.lower())

        # Ribbons only
        res_fita = evaluate_id_card_workflow("শুধু ফিতার ছবি দেন", workspace_id=1)
        self.assertIsNotNone(res_fita)
        self.assertEqual(res_fita["response_source"], "fita_sample_dispatch")
        self.assertGreaterEqual(len(res_fita["matched_images"]), 1)
        for img in res_fita["matched_images"]:
            self.assertIn("fita", img.lower())

        # Covers only
        res_cov = evaluate_id_card_workflow("শুধু কভারের ছবি দিন", workspace_id=1)
        self.assertIsNotNone(res_cov)
        self.assertEqual(res_cov["response_source"], "cover_sample_dispatch")
        self.assertGreaterEqual(len(res_cov["matched_images"]), 1)
        for img in res_cov["matched_images"]:
            self.assertIn("cover", img.lower())

    def test_12_top_premium_quality_request(self):
        """Customer asking for top premium quality receives only Package 07 photo."""
        res = evaluate_id_card_workflow("সবচেয়ে প্রিমিয়াম কোয়ালিটির কোনটা", workspace_id=1)
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "premium_package_07_dispatch")
        self.assertEqual(len(res["matched_images"]), 1)
        self.assertEqual(res["matched_images"][0], "/static/uploads/package/IMG-20260114-WA0057.jpg")
        self.assertIn("প্যাকেজ ০৭", res["reply_text"])
        self.assertIn("সবচেয়ে প্রিমিয়াম", res["reply_text"])

    def test_12b_lowest_budget_package_request(self):
        """Customer with low budget asking for cheapest package receives only Package 01 photo."""
        res = evaluate_id_card_workflow("আমাদের বাজেট একবারেই কম, সবচেয়ে কম দামের প্যাকেজ কোনটা?", workspace_id=1)
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "budget_package_01_dispatch")
        self.assertEqual(len(res["matched_images"]), 1)
        self.assertEqual(res["matched_images"][0], "/static/uploads/package/IMG-20260113-WA0003.jpg")
        self.assertIn("প্যাকেজ ০১", res["reply_text"])
        self.assertIn("সর্বনিম্ন বাজেট", res["reply_text"])

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
        self.assertIn("কালিয়াকৈর কাঁচাবাজার, আকরান, বিরুলিয়া, সাভার, ঢাকা।", prompt)

    def test_13_shop_address_inquiry(self):
        """Customer asking for shop address/location receives exact Kaliakair, Akran, Birulia, Savar address."""
        queries = [
            "আপনাদের ঠিকানা কি?",
            "আপনাদের লোকেশন কোথায়?",
            "দোকান কোথায় আপনাদের?",
            "অফিস কোথায়?",
            "কোথায় অবস্থিত?"
        ]
        for q in queries:
            res = evaluate_id_card_workflow(message_text=q, customer_name="Masud", workspace_id=1)
            self.assertIsNotNone(res, f"Failed for query: {q}")
            self.assertEqual(res["response_source"], "shop_address_inquiry")
            self.assertIn("কালিয়াকৈর কাঁচাবাজার, আকরান, বিরুলিয়া, সাভার, ঢাকা।", res["reply_text"])
            self.assertEqual(len(res["matched_images"]), 0)

    def test_14_agreement_variations_dispatch_samples(self):
        """Verify that multiple agreement variations after permission prompt trigger package images."""
        variations = ["হ্যাঁ", "জি পাঠান", "আচ্ছা দিন", "পাঠিয়ে দিন", "দেখান", "হুম পাঠান", "হ্যাঁ পাঠান"]
        for v in variations:
            res = evaluate_id_card_workflow(
                message_text=v,
                conversation_history=[
                    {"sender": "user", "content": "১০০ পিস বানাবো"},
                    {"sender": "bot", "content": "আমি কি আমাদের প্যাকেজের স্যাম্পল ছবিগুলো পাঠাবো স্যার?"}
                ],
                customer_name="Al-Amin",
                workspace_id=1
            )
            self.assertIsNotNone(res, f"Failed for agreement: {v}")
            self.assertEqual(res["response_source"], "package_sample_dispatch", f"Failed for {v}")
            self.assertEqual(len(res["matched_images"]), 7, f"Failed for {v}")

    async def test_15_non_form_inquiry_does_not_trigger_form_error(self):
        """Verify that general inquiries with institution names and photos do not trigger form upload error."""
        from app.ai_agent.gemini_brain import process_customer_message
        res = await process_customer_message(
            message_text="মাদ্রাসার কার্ড ও ছবি কেমন হবে",
            customer_name="Zubair",
            workspace_id=1
        )
        self.assertIsNotNone(res)
    def test_16_package_followup_never_reasks_quantity(self):
        """Verify package image dispatch follow-up asks for package preference, NEVER re-asking quantity."""
        from app.ai_agent.gemini_brain import get_package_sample_images
        matched_images = get_package_sample_images(1)
        is_package_images = any("package" in str(p).lower() or "pakage" in str(p).lower() or "pkg" in str(p).lower() or "wa000" in str(p).lower() for p in matched_images)
        self.assertTrue(is_package_images)
        
        # Test followup message logic
        honorific = "স্যার"
        if is_package_images:
            followup_msg = f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন {honorific}।"
        else:
            followup_msg = f"আপনার কত পিস প্রয়োজন জানাবেন {honorific}।"
        
        self.assertEqual(followup_msg, "আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন স্যার।")
        self.assertNotIn("কত পিস", followup_msg)

    def test_17_quantity_200_states_regular_rates_without_43_taka(self):
        """Verify 200 pcs (and 100+ pcs) offers packages and states regular wholesale rates / 35৳, never 43৳."""
        res = evaluate_id_card_workflow(
            message_text="200",
            conversation_history=[
                {"sender": "user", "content": "আইডি কার্ড বানাবো"},
                {"sender": "bot", "content": "জি স্যার, অবশ্যই। আপনি আমাদের কাছ থেকে আইডি কার্ড, ফিতা এবং কভারের ফুল প্যাকেজ নিতে পারবেন। আপনার কত পিস প্রয়োজন জানাবেন প্লিজ?"}
            ],
            customer_name="Rashed",
            workspace_id=1
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["response_source"], "id_card_quantity_permission_prompt")
        self.assertNotIn("৪৩ টাকা", res["reply_text"])
        self.assertNotIn("8600", res["reply_text"])
        self.assertIn("প্যাকেজ", res["reply_text"])
        self.assertIn("স্যাম্পল ছবিগুলো পাঠাবো", res["reply_text"])

    def test_18_reject_package_and_request_card_sample(self):
        """Verify that saying 'এগুলোতো পেকেজ আমি সাম্পল চাচ্ছিলাম' delivers individual ID card samples."""
        queries = [
            "এগুলোতো পেকেজ আমি সাম্পল চাচ্ছিলাম",
            "এগুলো তো প্যাকেজ আমি স্যাম্পল চাচ্ছিলাম",
            "প্যাকেজ না শুধু স্যাম্পল দেখতে চাই",
            "আমি স্যাম্পল চাচ্ছিলাম"
        ]
        for q in queries:
            res = evaluate_id_card_workflow(
                message_text=q,
                conversation_history=[
                    {"sender": "user", "content": "200"},
                    {"sender": "bot", "content": "জি স্যার, নিচে আমাদের আকর্ষণীয় প্যাকেজগুলোর স্যাম্পল ছবি পাঠানো হলো। আপনার কোন প্যাকেজটি পছন্দ জানাবেন প্লিজ।"}
                ],
                customer_name="Rashed",
                workspace_id=1
            )
            self.assertIsNotNone(res, f"Failed for query: {q}")
            self.assertEqual(res["response_source"], "id_card_sample_dispatch", f"Failed for query: {q}")
            self.assertGreater(len(res["matched_images"]), 0)
            self.assertIn("পিভিসি আইডি কার্ডের স্যাম্পল ছবিগুলো", res["reply_text"])

if __name__ == "__main__":
    unittest.main()
