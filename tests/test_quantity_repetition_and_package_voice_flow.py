import unittest
import os
import re
from app.database import (
    get_conversation_order_quantity,
    set_conversation_order_quantity,
    init_db
)
from app.ai_agent.gemini_brain import (
    build_initial_component_sample_sequence,
    build_ready_package_sequence,
    evaluate_id_card_workflow,
    analyze_conversation_history_context,
    extract_order_quantity_number,
    extract_bargaining_price_offer,
    VOICE_PACKAGE_SPECIAL_OFFER
)

class TestQuantityRepetitionAndPackageVoiceFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_01_component_sample_sequence_no_sample_feedback_asks_packages(self):
        """
        Verify component samples sequence does NOT ask 'স্যাম্পলগুলো কেমন লাগলো?',
        and instead offers the ready packages with regular wholesale rates.
        """
        seq = build_initial_component_sample_sequence(customer_name="Kamrul Hasan", workspace_id=1)
        self.assertTrue(len(seq) > 0)
        
        last_item = seq[-1]
        self.assertEqual(last_item["type"], "text")
        
        last_text = last_item["text"]
        # Must not ask sample feedback
        self.assertNotIn("স্যাম্পলগুলো কেমন লাগলো", last_text)
        self.assertNotIn("কেমন লাগলো জানাবেন", last_text)
        
        # Must offer ready packages
        self.assertIn("রেডি প্যাকেজ", last_text)
        self.assertIn("ছবি ও বিস্তারিত পাঠাবো", last_text)
        self.assertIn("স্যার", last_text)

    def test_02_agreement_after_component_samples_triggers_ready_packages(self):
        """
        When customer replies 'ভালো', 'সুন্দর', 'ঠিক আছে', 'ঠিক আছে পাঠান', 'হ্যাঁ পাঠান',
        after component samples were sent, evaluate_id_card_workflow dispatches ready packages.
        """
        history_after_samples = [
            {"sender": "customer", "content": "আইডি কার্ড বানাবো"},
            {"sender": "bot", "content": "কত পিস বানাবেন?"},
            {"sender": "customer", "content": "১০০"},
            {"sender": "bot", "content": "১০০ পিস অর্ডারের ক্ষেত্রে আমাদের প্যাকেজের নির্ধারিত রেগুলার পাইকারি রেট প্রযোজ্য হবে। আমি কি আমাদের কার্ড, ফিতা ও কভারের স্যাম্পল ছবিগুলো পাঠাবো স্যার?"},
            {"sender": "customer", "content": "হ্যাঁ পাঠান"},
            {"sender": "bot", "content": "এগুলো আমাদের কার্ড, আমাদের তৈরি করা কার্ড। /static/uploads/card/img1.jpg", "media_url": "/static/uploads/card/img1.jpg"},
            {"sender": "bot", "content": "এগুলো আমাদের প্রিন্ট করা ফিতা। /static/uploads/fita/img2.jpg", "media_url": "/static/uploads/fita/img2.jpg"},
            {"sender": "bot", "content": "/static/uploads/cover/img3.jpg", "media_url": "/static/uploads/cover/img3.jpg"},
            {"sender": "bot", "content": "আমাদের কাজের কোয়ালিটি ও সম্মানিত কাস্টমারদের রিভিউ দেখতে আমাদের ফেসবুক পেজের এই পোস্টটি দেখতে পারেন:\nhttps://www.facebook.com/share/p/19Agfhw4gv/"},
            {"sender": "bot", "content": "এগুলো আমাদের তৈরি করা কার্ড, প্রিন্ট করা ফিতা ও বিভিন্ন মডেলের কভারের স্যাম্পল। আমাদের কার্ড, ফিতা এবং কভার মিলিয়ে কিছু আকর্ষণীয় রেডি প্যাকেজ করা আছে (যার মধ্যে রেগুলার পাইকারি রেট দেওয়া আছে)। আমি কি আমাদের রেডি প্যাকেজগুলোর ছবি ও বিস্তারিত পাঠাবো স্যার?"}
        ]

        for agreement_text in ["ভালো", "অনেক সুন্দর", "ঠিক আছে", "ঠিক আছে পাঠান", "হ্যাঁ পাঠান", "দিন"]:
            res = evaluate_id_card_workflow(
                message_text=agreement_text,
                conversation_history=history_after_samples,
                customer_name="Kamrul Hasan",
                workspace_id=1,
                sender_id="cust_test_flow_01"
            )
            self.assertIsNotNone(res, f"Failed for agreement text: {agreement_text}")
            self.assertEqual(res["response_source"], "ready_package_dispatch", f"Source mismatch for: {agreement_text}")
            self.assertTrue(len(res["matched_images"]) == 7, "Must dispatch 7 ready package photos")
            
            # Since quantity is 100, voice note must be present in media_sequence
            voice_items = [item for item in res["media_sequence"] if item.get("type") == "voice"]
            self.assertEqual(len(voice_items), 1, "Must include voice note for 100 pcs order")
            self.assertEqual(voice_items[0]["url"], VOICE_PACKAGE_SPECIAL_OFFER)

            # Concluding text must ask which package they like (never asking quantity)
            text_items = [item for item in res["media_sequence"] if item.get("type") == "text"]
            self.assertTrue(len(text_items) > 0)
            self.assertIn("আপনার কোন প্যাকেজটি পছন্দ হয়েছে, বলুন স্যার।", text_items[-1]["text"])
            self.assertNotIn("কত পিস", text_items[-1]["text"])

    def test_03_ready_packages_100_plus_includes_voice_note(self):
        """
        Orders of 100 or 100+ pcs (or unspecified) MUST include the special offer voice note
        and end with 'আপনার কোন প্যাকেজটি পছন্দ হয়েছে, বলুন স্যার।'
        """
        for q in [100, 150, 500, None]:
            seq = build_ready_package_sequence(quantity=q, customer_name="Customer", workspace_id=1)
            voice_items = [s for s in seq if s.get("type") == "voice"]
            self.assertEqual(len(voice_items), 1, f"Voice note expected for quantity={q}")
            self.assertEqual(voice_items[0]["url"], VOICE_PACKAGE_SPECIAL_OFFER)

            text_items = [s for s in seq if s.get("type") == "text"]
            self.assertTrue(len(text_items) > 0)
            self.assertIn("আপনার কোন প্যাকেজটি পছন্দ হয়েছে, বলুন স্যার।", text_items[-1]["text"])
            self.assertNotIn("কত পিস", text_items[-1]["text"])

    def test_04_ready_packages_under_100_excludes_voice_note(self):
        """
        Orders of less than 100 pcs (e.g. 30, 45, 75, 90) must NOT include the voice note.
        Must still ask which package they like without re-asking quantity.
        """
        for q in [35, 40, 60, 80, 95]:
            seq = build_ready_package_sequence(quantity=q, customer_name="Customer", workspace_id=1)
            voice_items = [s for s in seq if s.get("type") == "voice"]
            self.assertEqual(len(voice_items), 0, f"Voice note must NOT be included for quantity={q}")

            text_items = [s for s in seq if s.get("type") == "text"]
            self.assertTrue(len(text_items) > 0)
            self.assertIn("আপনার কোন প্যাকেজটি পছন্দ হয়েছে, বলুন স্যার।", text_items[-1]["text"])
            self.assertNotIn("কত পিস বানাবেন", text_items[-1]["text"])

    def test_05_persistent_database_quantity_and_zero_repetition(self):
        """
        Verify that once order quantity is saved in the database for a sender_id,
        subsequent greetings, questions or long chit-chat never asks for quantity again.
        """
        sender_id = "8801700000001"
        set_conversation_order_quantity(sender_id, 100, workspace_id=1)

        saved_qty = get_conversation_order_quantity(sender_id, workspace_id=1)
        self.assertEqual(saved_qty, 100)

        # Context analysis should load quantity from DB even if conversation history is empty
        ctx = analyze_conversation_history_context([], "হাই", sender_id=sender_id, workspace_id=1)
        self.assertEqual(ctx.get("known_quantity"), 100)

        # Pure greeting when bot previously asked quantity must acknowledge known quantity rather than asking again
        history = [
            {"sender": "bot", "content": "জি স্যার, কত পিস বানাবেন?"},
            {"sender": "customer", "content": "১০০ পিস"}
        ]
        res = evaluate_id_card_workflow(
            message_text="হ্যালো",
            conversation_history=history,
            customer_name="Kamrul Hasan",
            workspace_id=1,
            sender_id=sender_id
        )
        self.assertIsNotNone(res)
        self.assertNotIn("কত পিস আইডি কার্ড বানাবেন", res["reply_text"])
        self.assertNotIn("কত পিস বানাবেন", res["reply_text"])
        self.assertIn("১০০ পিস অর্ডারের বিষয়ে", res["reply_text"])

    def test_06_stripping_repetitive_quantity_questions_regex(self):
        """
        Verify that patterns like 'বা কত পিস আইডি কার্ড করতে চান, তা একটু জানাবেন স্যার?'
        are completely removed by our sanitizer regex when quantity is already known.
        """
        known_qty_in_history = 100
        honorific = "স্যার"

        raw_gemini_reply = "জি স্যার, অনেক ধন্যবাদ। আপনার প্রতিষ্ঠানের জন্য কোন প্যাকেজটি পছন্দ হয় বা কত পিস আইডি কার্ড করতে চান, তা একটু জানাবেন স্যার?"

        patterns_to_strip = [
            r'(?:,\s*|বা\s+|এবং\s+)?(?:আপনার\s+)?(?:প্রতিষ্ঠানের\s+জন্য\s+)?(?:মোট\s+)?কত\s*(?:পিস|টি|টা|গুলো|কপি|কোয়ান্টিটি)[^\n।!?]*[।!?]?',
            r'(?:,\s*|বা\s+|এবং\s+)?(?:আপনার\s+)?(?:প্রতিষ্ঠানের\s+জন্য\s+)?(?:মোট\s+)?কত\s*পিস\s*(?:আইডি\s*কার্ড\s*)?(?:করতে|বানাতে)\s*চান[^\n।!?]*[।!?]?',
            r'কোয়ান্টিটি\s+কত[^\n।!?]*[।!?]?',
            r'(?:আপনার\s+)?(?:প্রতিষ্ঠানের\s+জন্য\s+)?পরিমাণ\s+কত[^\n।!?]*[।!?]?'
        ]

        clean_reply = raw_gemini_reply
        for p in patterns_to_strip:
            clean_reply = re.sub(p, '', clean_reply, flags=re.IGNORECASE).strip()

        clean_reply = re.sub(r'[\s,]+(?:বা|এবং|অথবা)\s*$', '।', clean_reply).strip()
        clean_reply = re.sub(r'[\s,]+(?:বা|এবং|অথবা)\s*([।!?])', r'\1', clean_reply).strip()
        clean_reply = re.sub(r'(কোন\s+প্যাকেজটি\s+পছন্দ\s+হয়)\s*([।!?]?)$', rf'\1 জানাবেন {honorific}।', clean_reply).strip()
        if clean_reply and not any(clean_reply.endswith(p) for p in ['।', '!', '?', '.']):
            clean_reply += '।'

        self.assertNotIn("কত পিস", clean_reply)
        self.assertNotIn(" বা ", f" {clean_reply} ")
        self.assertIn("আপনার প্রতিষ্ঠানের জন্য কোন প্যাকেজটি পছন্দ হয় জানাবেন স্যার।", clean_reply)

    def test_07_rate_bargaining_phrases_not_extracted_as_quantity(self):
        """
        Verify that rate bargaining expressions like 'আমি আশি করে দিব',
        '৮০ টাকা করে দেওয়া যাবে?', '৭০ টাকা দেওয়া যাবে না?' are NOT extracted as order quantity.
        """
        # Rate offers should return None for order quantity
        self.assertIsNone(extract_order_quantity_number("আমি আশি করে দিব"))
        self.assertIsNone(extract_order_quantity_number("৮০ টাকা করে দেওয়া যাবে?"))
        self.assertIsNone(extract_order_quantity_number("৭০ টাকা দেওয়া যাবে না?"))
        self.assertIsNone(extract_order_quantity_number("৮০ করে রাখেন"))
        self.assertIsNone(extract_order_quantity_number("আশি টাকা"))
        self.assertIsNone(extract_order_quantity_number("৭০ টাকা"))
        self.assertIsNone(extract_order_quantity_number("৮০ টাকা রাখা যাবে?"))

        # Explicit quantity with rate should still correctly extract quantity
        self.assertEqual(extract_order_quantity_number("১০০ পিস বানাবো ৮০ টাকা করে"), 100)
        self.assertEqual(extract_order_quantity_number("১০০ পিস বানাবো"), 100)
        self.assertEqual(extract_order_quantity_number("১০০ পিস"), 100)
        self.assertEqual(extract_order_quantity_number("১০০"), 100)

    def test_08_bargaining_price_offer_extraction(self):
        """
        Verify that extract_bargaining_price_offer extracts the proposed per-piece rate correctly.
        """
        self.assertEqual(extract_bargaining_price_offer("আমি আশি করে দিব"), 80)
        self.assertEqual(extract_bargaining_price_offer("৮০ টাকা করে দেওয়া যাবে?"), 80)
        self.assertEqual(extract_bargaining_price_offer("৭০ টাকা দেওয়া যাবে না?"), 70)
        self.assertEqual(extract_bargaining_price_offer("৮০ করে রাখেন"), 80)
        self.assertEqual(extract_bargaining_price_offer("৮২ টাকা রাখেন"), 82)
        self.assertEqual(extract_bargaining_price_offer("৮২ টাকা করে দেওয়া যাবে?"), 82)
        self.assertEqual(extract_bargaining_price_offer("৮২ টাকা ফাইনাল করেন"), 82)

        # Pure quantity should not be extracted as price offer
        self.assertIsNone(extract_bargaining_price_offer("১০০ পিস বানাবো"))

    def test_09_known_quantity_protected_against_bargaining(self):
        """
        Verify that once order quantity is confirmed as 100 pcs,
        subsequent price offers ('আমি আশি করে দিব') do not overwrite known_quantity to 80.
        """
        sender_id = "8801999999999"
        set_conversation_order_quantity(sender_id, 100, workspace_id=1)

        history = [
            {"sender": "customer", "content": "১০০ পিস আইডি কার্ড বানাবো"},
            {"sender": "bot", "content": "জি স্যার, আমাদের ৭ নম্বর প্যাকেজটি ১০০+ পিসের ক্ষেত্রে রেগুলার ৯১ টাকা।"},
            {"sender": "bot", "content": "জি স্যার, যেহেতু আপনার ১০০ পিসের অর্ডার, তাই দামাদামির বিষয়টি মাথায় রেখে এই প্যাকেজটি কমিয়ে সর্বনিম্ন ৮২ টাকা পর্যন্ত রাখা সম্ভব। এই দামে কি অর্ডারটি চূড়ান্ত করব স্যার?"}
        ]

        # Customer offers: 'আমি আশি করে দিব'
        ctx = analyze_conversation_history_context(history, "আমি আশি করে দিব", sender_id=sender_id, workspace_id=1)
        self.assertEqual(ctx.get("known_quantity"), 100, "Known quantity must remain 100 pcs, NOT mutated to 80")

        # Database quantity must also remain 100
        saved_qty = get_conversation_order_quantity(sender_id, workspace_id=1)
        self.assertEqual(saved_qty, 100, "DB quantity must remain 100 pcs")

    def test_10_package_07_bargaining_rejects_below_82_tk(self):
        """
        Package 07 regular rate is 91 Tk, and minimum negotiation floor is 82 Tk.
        When customer offers 80 Tk or 70 Tk, evaluate_id_card_workflow firmly rejects below 82 Tk
        and never says '৮০ টাকা করেই চূড়ান্ত করে দিলাম' or confuses price with pieces.
        """
        sender_id = "8801888888888"
        set_conversation_order_quantity(sender_id, 100, workspace_id=1)

        history = [
            {"sender": "customer", "content": "১০০ পিস বানাবো"},
            {"sender": "bot", "content": "জি স্যার, আমাদের ৭ নম্বর প্যাকেজটি ১০০+ পিসের ক্ষেত্রে রেগুলার ৯১ টাকা করে রাখা যায়।"},
            {"sender": "bot", "content": "জি স্যার, যেহেতু আপনার ১০০ পিসের অর্ডার, তাই দামাদামির বিষয়টি মাথায় রেখে এই প্যাকেজটি কমিয়ে সর্বনিম্ন ৮২ টাকা পর্যন্ত রাখা সম্ভব।"}
        ]

        # 1. Customer says: 'আমি আশি করে দিব'
        res_80_word = evaluate_id_card_workflow(
            message_text="আমি আশি করে দিব",
            conversation_history=history,
            customer_name="Customer",
            workspace_id=1,
            sender_id=sender_id
        )
        self.assertIsNotNone(res_80_word)
        self.assertEqual(res_80_word["response_source"], "package_counter_offer_below_floor_rejected")
        reply = res_80_word["reply_text"]
        self.assertIn("৮০ টাকায় দেওয়া সম্ভব নয়", reply)
        self.assertIn("সর্বনিম্ন ৮২ টাকা", reply)
        self.assertIn("১০০ পিসের ক্ষেত্রে", reply)
        self.assertNotIn("৮০ পিস", reply)
        self.assertNotIn("৮০ টাকা করেই চূড়ান্ত করে দিলাম", reply)

        # 2. Customer says: '৮০ টাকা করে দেওয়া যাবে?'
        res_80_tk = evaluate_id_card_workflow(
            message_text="৮০ টাকা করে দেওয়া যাবে?",
            conversation_history=history,
            customer_name="Customer",
            workspace_id=1,
            sender_id=sender_id
        )
        self.assertIsNotNone(res_80_tk)
        self.assertIn("৮০ টাকায় দেওয়া সম্ভব নয়", res_80_tk["reply_text"])
        self.assertIn("সর্বনিম্ন ৮২ টাকা", res_80_tk["reply_text"])
        self.assertNotIn("৮০ পিস", res_80_tk["reply_text"])

        # 3. Customer says: '৭০ টাকা দেওয়া যাবে না?'
        res_70_tk = evaluate_id_card_workflow(
            message_text="৭০ টাকা দেওয়া যাবে না?",
            conversation_history=history,
            customer_name="Customer",
            workspace_id=1,
            sender_id=sender_id
        )
        self.assertIsNotNone(res_70_tk)
        self.assertIn("৭০ টাকায় দেওয়া সম্ভব নয়", res_70_tk["reply_text"])
        self.assertIn("সর্বনিম্ন ৮২ টাকা", res_70_tk["reply_text"])
        self.assertNotIn("৭০ পিস", res_70_tk["reply_text"])

    def test_11_package_07_bargaining_accepts_82_tk(self):
        """
        When customer offers 82 Tk (the floor price), evaluate_id_card_workflow accepts 82 Tk
        and asks for institution name, address, and mobile number.
        """
        sender_id = "8801777777777"
        set_conversation_order_quantity(sender_id, 100, workspace_id=1)

        history = [
            {"sender": "customer", "content": "১০০ পিস বানাবো"},
            {"sender": "bot", "content": "জি স্যার, আমাদের ৭ নম্বর প্যাকেজটি ১০০+ পিসের ক্ষেত্রে রেগুলার ৯১ টাকা করে রাখা যায়।"},
            {"sender": "bot", "content": "সর্বনিম্ন ৮২ টাকা পর্যন্ত রাখা সম্ভব।"}
        ]

        res_82 = evaluate_id_card_workflow(
            message_text="৮২ টাকা করে দেওয়া যাবে?",
            conversation_history=history,
            customer_name="Customer",
            workspace_id=1,
            sender_id=sender_id
        )
        self.assertIsNotNone(res_82)
        self.assertEqual(res_82["response_source"], "package_counter_offer_floor_accepted")
        reply = res_82["reply_text"]
        self.assertIn("৮২ টাকা দরেই চূড়ান্ত করে দিচ্ছি", reply)
        self.assertIn("প্রতিষ্ঠানের নাম", reply)
        self.assertIn("পূর্ণাঙ্গ ঠিকানা", reply)
        self.assertIn("মোবাইল নম্বর", reply)

if __name__ == "__main__":
    unittest.main()
