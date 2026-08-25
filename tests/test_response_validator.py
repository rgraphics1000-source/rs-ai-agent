"""
Phase 4 Automated Test Suite: Response Validator & Policy Guard
Tests:
- Admin / Human Takeover silence guard
- MOQ rejection guard for < 30 pcs
- Mandatory Advance & Prohibited Full COD interception
- Free delivery hallucination correction
- Special offer voice stripped for < 80 pcs and passed for 80+ pcs
- Package 7 minimum floor price (82 Tk) protection
- Small order (30-49) & Regular (50-79) zero discount enforcement
- Persona honorific and markdown cleanliness
- Image deduplication and capping
- Clean compliant draft passes intact
"""

import unittest
import uuid
from app.database import (
    init_db, set_admin_takeover, enable_conversation_ai,
    get_or_create_conversation_state, update_conversation_state
)
from app.ai_agent.response_validator import ResponseValidator
from app.ai_agent.conversation_state import SalesStage


class TestResponseValidator(unittest.TestCase):

    def setUp(self):
        init_db()
        self.ws_id = 1
        self.cust_id = f"test_val_{uuid.uuid4().hex[:8]}"

    def test_01_human_takeover_blocks_and_silences_all_replies(self):
        """TEST 1: When takeover is active, draft is completely silenced."""
        # Enable takeover
        set_admin_takeover(sender_id=self.cust_id, workspace_id=self.ws_id, takeover_by="human_admin")

        draft = {
            "reply_text": "জি স্যার, আমি সাহায্য করছি।",
            "matched_images": ["/static/uploads/card/card1.png"],
            "voice_url": "https://example.com/voice.opus",
            "video_url": "",
            "order_created": None
        }

        validated = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_message="হ্যালো",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )

        self.assertTrue(validated["is_blocked"])
        self.assertEqual(validated["reply_text"], "")
        self.assertEqual(len(validated["matched_images"]), 0)
        self.assertEqual(validated["voice_url"], "")
        self.assertIn("HUMAN_TAKEOVER_ACTIVE", validated["validation_flags"])
        print("[PASSED] Test 01: Human takeover absolute silence verified.")

    def test_02_moq_under_30_intercepts_unauthorized_order_promise(self):
        """TEST 2: When quantity < 30 pcs, draft is intercepted with standard MOQ text."""
        # Customer says 20 pcs
        draft = {
            "reply_text": "জি স্যার, আপনার ২০ পিস আইডি কার্ডের অর্ডার কনফার্ম করা হলো। মোট ১০০০ টাকা।",
            "matched_images": ["/static/uploads/card/sample.png"],
            "voice_url": "https://example.com/voice.opus",
            "video_url": "",
            "order_created": {"id": 123}
        }

        validated = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_message="আমার ২০টা আইডি কার্ড লাগবে",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )

        self.assertIn("সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস", validated["reply_text"])
        self.assertEqual(len(validated["matched_images"]), 0)
        self.assertEqual(validated["voice_url"], "")
        self.assertIsNone(validated["order_created"])
        self.assertIn("MOQ_UNDER_30_ENFORCED", validated["validation_flags"])
        print("[PASSED] Test 02: MOQ < 30 pcs order interception verified.")

    def test_03_mandatory_advance_intercepts_prohibited_full_cod(self):
        """TEST 3: Intercepts unauthorized 'কোনো অগ্রিম লাগবে না' / full COD claims."""
        draft = {
            "reply_text": "জি স্যার, আপনার কোনো অগ্রিম লাগবে না, সম্পূর্ণ ক্যাশ অন ডেলিভারিতে নিতে পারবেন।",
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }

        validated = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_message="অগ্রিম ছাড়া দেওয়া যাবে?",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )

        self.assertNotIn("কোনো অগ্রিম লাগবে না", validated["reply_text"])
        self.assertIn("অগ্রিম পেমেন্ট বাধ্যতামূলক", validated["reply_text"])
        self.assertIn("PROHIBITED_COD_INTERCEPTED", validated["validation_flags"])
        print("[PASSED] Test 03: Mandatory advance enforcement & full COD blockage verified.")

    def test_04_free_delivery_hallucination_correction(self):
        """TEST 4: Replaces free delivery hallucination with standard delivery charges."""
        draft = {
            "reply_text": "জি স্যার, আমরা ফ্রি ডেলিভারিতে আপনার ঠিকানায় পাঠিয়ে দেব।",
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }

        validated = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_message="ডেলিভারি চার্জ কত?",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )

        self.assertNotIn("ফ্রি ডেলিভারি", validated["reply_text"])
        self.assertIn("৮০ টাকা", validated["reply_text"])
        self.assertIn("১৩০ টাকা", validated["reply_text"])
        self.assertIn("FREE_DELIVERY_CORRECTED", validated["validation_flags"])
        print("[PASSED] Test 04: Free delivery correction verified.")

    def test_05_special_offer_voice_guard_by_quantity(self):
        """TEST 5: Special offer voice stripped under 80 pcs, passed for 80+ pcs."""
        special_voice = "https://example.com/PTT-20260119-WA0105.opus"

        # Case A: Quantity = 50 pcs (Under 80) -> Must strip voice
        draft_50 = {
            "reply_text": "জি স্যার, স্যাম্পল পাঠিয়ে দিচ্ছি।",
            "matched_images": [],
            "voice_url": special_voice,
            "video_url": "",
            "order_created": None
        }
        val_50 = ResponseValidator.validate_and_sanitize(
            draft_response=draft_50,
            customer_message="৫০টা লাগবে",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )
        self.assertEqual(val_50["voice_url"], "")
        self.assertIn("SPECIAL_VOICE_STRIPPED_UNDER_80", val_50["validation_flags"])

        # Case B: Quantity = 100 pcs (80+) -> Must keep voice
        draft_100 = {
            "reply_text": "জি স্যার, স্যাম্পল পাঠিয়ে দিচ্ছি।",
            "matched_images": [],
            "voice_url": special_voice,
            "video_url": "",
            "order_created": None
        }
        val_100 = ResponseValidator.validate_and_sanitize(
            draft_response=draft_100,
            customer_message="১০০টা লাগবে",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )
        self.assertEqual(val_100["voice_url"], special_voice)
        print("[PASSED] Test 05: Special offer voice quantity gate (<80 stripped, >=80 kept) verified.")

    def test_06_package_7_floor_price_protection(self):
        """TEST 6: Package 7 price quoted below 82 Tk is auto-corrected with floor protection."""
        draft = {
            "reply_text": "জি স্যার, আপনার জন্য প্যাকেজ ৭ প্রতি সেট ৭৫ টাকা করে রাখা যাবে।",
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }

        validated = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_message="প্যাকেজ ৭ ৭৫ টাকা রাখবেন?",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )

        self.assertNotIn("৭৫ টাকা", validated["reply_text"])
        self.assertIn("৮২ টাকার নিচে দেওয়া সম্ভব হচ্ছে না", validated["reply_text"])
        self.assertIn("Owner স্যারের অনুমতি প্রয়োজন", validated["reply_text"])
        self.assertIn("PACKAGE_7_FLOOR_PROTECTED", validated["validation_flags"])
        print("[PASSED] Test 06: Package 7 minimum floor protection (82 Tk) verified.")

    def test_07_small_order_and_regular_tier_zero_discount_guard(self):
        """TEST 7: Small Order (30-49) & Regular (50-79) zero discount enforcement."""
        # 40 pcs with illegal discount in draft
        draft_40 = {
            "reply_text": "জি স্যার, আপনার ৪০ পিসের জন্য বিশেষ ছাড় দেওয়া হলো প্রতি সেটে ৫ টাকা কম।",
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }
        val_40 = ResponseValidator.validate_and_sanitize(
            draft_response=draft_40,
            customer_message="৪০ পিস লাগবে",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )
        self.assertIn("১০ টাকা করে বেশি হবে", val_40["reply_text"])
        self.assertIn("SMALL_ORDER_DISCOUNT_STRIPPED", val_40["validation_flags"])

        # 60 pcs with illegal discount in draft
        draft_60 = {
            "reply_text": "জি স্যার, আপনার ৬০ পিসের জন্য ডিসকাউন্ট দেওয়া হলো।",
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }
        val_60 = ResponseValidator.validate_and_sanitize(
            draft_response=draft_60,
            customer_message="৬০ পিস লাগবে",
            sender_id=self.cust_id,
            customer_name="Rahim",
            workspace_id=self.ws_id
        )
        self.assertIn("৫০-৭৯ পিসের ক্ষেত্রে প্যাকেজের ছবিতে উল্লেখিত রেগুলার মূল্যে", val_60["reply_text"])
        self.assertIn("REGULAR_TIER_DISCOUNT_STRIPPED", val_60["validation_flags"])
        print("[PASSED] Test 07: Surcharge & regular tier discount stripping verified.")

    def test_08_persona_honorific_and_cleanliness(self):
        """TEST 8: Replaces informal 'ভাইয়া/আপু' with formal honorific and removes markdown file tags."""
        draft = {
            "reply_text": "জি ভাইয়া, নিচে দেখুন ![card](/static/uploads/card.png) আমাদের ছবি।",
            "matched_images": ["/static/uploads/card.png"],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }

        # Male name -> স্যার
        val_male = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_name="Tanvir Hossain",
            workspace_id=self.ws_id
        )
        self.assertNotIn("ভাইয়া", val_male["reply_text"])
        self.assertIn("স্যার", val_male["reply_text"])
        self.assertNotIn("![card]", val_male["reply_text"])
        self.assertNotIn("/static/uploads", val_male["reply_text"])

        # Female name -> ম্যাম
        val_fem = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_name="Nusrat Jahan",
            workspace_id=self.ws_id
        )
        self.assertNotIn("ভাইয়া", val_fem["reply_text"])
        self.assertIn("ম্যাম", val_fem["reply_text"])
        print("[PASSED] Test 08: Honorific and markdown tag cleanliness verified.")

    def test_09_image_deduplication_and_capping(self):
        """TEST 9: Image list deduplication and capping."""
        draft = {
            "reply_text": "জি স্যার, ছবিগুলো দেওয়া হলো।",
            "matched_images": [
                "/static/uploads/sample1.png",
                "/static/uploads/sample1.png", # Duplicate
                "/static/uploads/sample2.png",
                "/static/uploads/sample3.png",
                "/static/uploads/sample4.png", # Exceeds 3 standard cap
            ],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }

        validated = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_message="কিছু ছবি পাঠান",
            workspace_id=self.ws_id
        )

        self.assertLessEqual(len(validated["matched_images"]), 3)
        self.assertEqual(len(set(validated["matched_images"])), len(validated["matched_images"]))
        print("[PASSED] Test 09: Image deduplication and 3-photo capping verified.")

    def test_10_compliant_draft_passes_intact(self):
        """TEST 10: Clean compliant draft passes through validator intact."""
        clean_text = "জি স্যার, ১০০+ পিস অর্ডারের ক্ষেত্রে আমাদের প্যাকেজ ১ এর রেগুলার রেট প্রতি সেট ৭০ টাকা।"
        draft = {
            "reply_text": clean_text,
            "matched_images": ["/static/uploads/p1.png"],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "gemini_brain"
        }

        validated = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_message="প্যাকেজ ১ এর দাম কত?",
            customer_name="Rahim",
            workspace_id=self.ws_id
        )

        self.assertFalse(validated["is_blocked"])
        self.assertEqual(validated["reply_text"], clean_text)
        self.assertEqual(len(validated["matched_images"]), 1)
        self.assertEqual(len(validated["validation_flags"]), 0)
        print("[PASSED] Test 10: Clean compliant draft passes intact.")


if __name__ == "__main__":
    unittest.main()
