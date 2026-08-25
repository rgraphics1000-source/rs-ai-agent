import unittest
import os
import time
from app.database import (
    init_db,
    get_structured_conversation_state,
    set_admin_takeover,
    enable_conversation_ai,
    is_conversation_ai_active
)
from app.ai_agent.gemini_brain import (
    evaluate_id_card_workflow,
    generate_smart_fallback_reply,
    is_affirmative_response
)
from app.ai_agent.pricing_engine import (
    calculate_package_price,
    negotiate_step,
    QuantityTier
)
from app.ai_agent.owner_approval import (
    OwnerApprovalEngine,
    ApprovalStatus
)
from app.ai_agent.response_validator import ResponseValidator


class TestMessengerMultiTurnPricing(unittest.TestCase):
    """
    Regression Test Suite for Phase 8.8:
    Multi-Turn Facebook Messenger / Omnichannel State, Pricing, and Photo Service Queries.
    """

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.workspace_id = 1
        self.sender_id = f"fb_test_user_{int(time.time() * 1000)}"

    # 1. 30 pcs "প্রতি পিস কত টাকা"
    def test_01_30_pcs_proti_piece_koto_taka(self):
        history = [
            {"sender": "customer", "text": "Hi"},
            {"sender": "bot", "text": "কত পিস বানাবেন?"},
            {"sender": "customer", "text": "30"},
            {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"}
        ]
        res = evaluate_id_card_workflow(
            message_text="প্রতি পিস কত টাকা",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("৮০", reply)
        self.assertIn("প্যাকেজ ১", reply)
        self.assertNotIn("কত পিস বানাবেন", reply)

    # 2. 30 pcs "প্রতি পিস কত রাখবেন"
    def test_02_30_pcs_proti_piece_koto_rakhben(self):
        history = [
            {"sender": "customer", "text": "কত করে পিস"},
            {"sender": "bot", "text": "কত পিস বানাবেন?"},
            {"sender": "customer", "text": "৩০"},
            {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"}
        ]
        res = evaluate_id_card_workflow(
            message_text="প্রতি পিস কত রাখবেন",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("৮০", reply)
        self.assertIn("প্যাকেজ ১", reply)
        self.assertNotIn("কত পিস বানাবেন", reply)

    # 3. 30 pcs "দাম কত"
    def test_03_30_pcs_dam_koto(self):
        history = [
            {"sender": "customer", "text": "30"},
            {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"}
        ]
        res = evaluate_id_card_workflow(
            message_text="দাম কত",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("৮০", reply)
        self.assertNotIn("কত পিস বানাবেন", reply)

    # 4. 30 pcs pricing after media dispatch
    def test_04_30_pcs_pricing_after_media_dispatch(self):
        history = [
            {"sender": "customer", "text": "30"},
            {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"},
            {"sender": "customer", "text": "হ্যাঁ পাঠান"},
            {"sender": "bot", "text": "স্যাম্পলগুলো পাঠিয়ে দিচ্ছি", "media_url": "/static/uploads/package/IMG-20260113-WA0002.jpg"}
        ]
        res = evaluate_id_card_workflow(
            message_text="প্রতি পিস কত টাকা রাখা যাবে?",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("৮০", reply)
        self.assertNotIn("কত পিস বানাবেন", reply)

    # 5. 50 pcs pricing
    def test_05_50_pcs_pricing(self):
        history = [{"sender": "customer", "text": "50"}, {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"}]
        res = evaluate_id_card_workflow(
            message_text="প্রতি পিস কত?",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("৭০", reply)
        self.assertIn("প্যাকেজ ১", reply)
        self.assertNotIn("কত পিস বানাবেন", reply)

    # 6. 80 pcs pricing
    def test_06_80_pcs_pricing(self):
        history = [{"sender": "customer", "text": "80"}, {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"}]
        res = evaluate_id_card_workflow(
            message_text="প্রতি পিস কত টাকা?",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("৭০", reply)
        self.assertIn("প্যাকেজ ১", reply)
        self.assertNotIn("কত পিস বানাবেন", reply)

    # 7. 100 pcs Package 7 pricing
    def test_07_100_pcs_package_7_pricing(self):
        history = [{"sender": "customer", "text": "100"}, {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"}]
        res = evaluate_id_card_workflow(
            message_text="Package 7 কত?",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("৯১", reply)
        self.assertNotIn("কত পিস বানাবেন", reply)

    # 8. Pricing after media dispatch
    def test_08_pricing_after_media_dispatch(self):
        history = [
            {"sender": "customer", "text": "100"},
            {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"},
            {"sender": "customer", "text": "Jee"},
            {"sender": "bot", "text": "স্যাম্পল পাঠানো হলো", "media_url": "/static/uploads/id_card/IMG-20241009-WA0005.jpg"}
        ]
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজ ৩ এর রেট কত",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("৭৩", reply)
        self.assertNotIn("কত পিস বানাবেন", reply)

    # 9. Service question after media dispatch
    def test_09_service_question_after_media_dispatch(self):
        history = [
            {"sender": "customer", "text": "100"},
            {"sender": "bot", "text": "স্যাম্পল পাঠানো হলো", "media_url": "/static/uploads/package/IMG-20260113-WA0002.jpg"}
        ]
        res = evaluate_id_card_workflow(
            message_text="ছবি কি আপনারা তুলে নিয়ে যাবেন কিনা",
            conversation_history=history,
            customer_name="TestUser",
            workspace_id=self.workspace_id,
            sender_id=self.sender_id
        )
        reply = res.get("reply_text", "")
        self.assertIn("আমরা সরাসরি প্রতিষ্ঠানে গিয়ে ছবি তুলি না", reply)
        self.assertNotIn("সহযোগিতা প্রয়োজন হলে জানাবেন", reply)

    # 10. Generic fallback must not override answerable questions
    def test_10_generic_fallback_not_override_answerable_questions(self):
        queries = [
            "ছবি কি আপনারা তুলে নিয়ে যাবেন কিনা",
            "বলতে চাই ছবি আপনারা তুলে নিয়ে যাবেন কিনা",
            "আপনারা এসে ছবি তুলবেন কিনা",
            "ফটোগ্রাফার কি আপনারা পাঠাবেন কিনা"
        ]
        for q in queries:
            fb = generate_smart_fallback_reply(
                user_msg=q,
                customer_name="TestUser",
                workspace_id=self.workspace_id
            )
            self.assertIn("আমরা সরাসরি প্রতিষ্ঠানে গিয়ে ছবি তুলি না", fb, f"Failed for query: {q}")
            self.assertNotIn("সহযোগিতা প্রয়োজন হলে জানাবেন", fb, f"Failed for query: {q}")

    # 11. Quantity preservation across media dispatch
    def test_11_quantity_preservation_across_media_dispatch(self):
        evaluate_id_card_workflow("30", [], "TestUser", self.workspace_id, self.sender_id)
        st = get_structured_conversation_state(self.sender_id, self.workspace_id)
        self.assertEqual(st.get("quantity"), 30)

        # Dispatch sample
        evaluate_id_card_workflow("Jee", [{"sender": "customer", "text": "30"}, {"sender": "bot", "text": "স্যাম্পল পাঠাবো কি?"}], "TestUser", self.workspace_id, self.sender_id)
        st2 = get_structured_conversation_state(self.sender_id, self.workspace_id)
        self.assertEqual(st2.get("quantity"), 30)

    # 12. Full Mandatory Multi-Turn Scenario: Turn 1 (কত করে পিস) -> Turn 2 (৩০) -> Turn 3 (ছবি আপনারা তুলে নিয়ে যাবেন কিনা) -> Turn 4 (প্রতি পিস কত টাকা রাখবেন)
    def test_12_full_mandatory_multi_turn_scenario(self):
        history = []
        # Turn 1: Customer: "কত করে পিস"
        res1 = evaluate_id_card_workflow("কত করে পিস", history, "TestUser", self.workspace_id, self.sender_id)
        reply1 = res1.get("reply_text", "")
        self.assertIn("কত পিস", reply1)
        history.append({"sender": "customer", "text": "কত করে পিস"})
        history.append({"sender": "bot", "text": reply1})

        # Turn 2: Customer: "৩০"
        res2 = evaluate_id_card_workflow("৩০", history, "TestUser", self.workspace_id, self.sender_id)
        reply2 = res2.get("reply_text", "")
        self.assertTrue("আমাদের স্যাম্পলগুলো পাঠাবো কি" in reply2 or "প্রতি প্যাকেজে ১০ টাকা" in reply2)
        history.append({"sender": "customer", "text": "৩০"})
        history.append({"sender": "bot", "text": reply2})

        st2 = get_structured_conversation_state(self.sender_id, self.workspace_id)
        self.assertEqual(st2.get("quantity"), 30)

        # Turn 3: Customer: "ছবি আপনারা তুলে নিয়ে যাবেন কিনা"
        res3 = evaluate_id_card_workflow("ছবি আপনারা তুলে নিয়ে যাবেন কিনা", history, "TestUser", self.workspace_id, self.sender_id)
        reply3 = res3.get("reply_text", "")
        self.assertIn("আমরা সরাসরি প্রতিষ্ঠানে গিয়ে ছবি তুলি না", reply3)
        self.assertNotIn("সহযোগিতা প্রয়োজন হলে জানাবেন", reply3)
        self.assertNotIn("কত পিস বানাবেন", reply3)
        history.append({"sender": "customer", "text": "ছবি আপনারা তুলে নিয়ে যাবেন কিনা"})
        history.append({"sender": "bot", "text": reply3})

        st3 = get_structured_conversation_state(self.sender_id, self.workspace_id)
        self.assertEqual(st3.get("quantity"), 30)

        # Turn 4: Customer: "প্রতি পিস কত টাকা রাখবেন"
        res4 = evaluate_id_card_workflow("প্রতি পিস কত টাকা রাখবেন", history, "TestUser", self.workspace_id, self.sender_id)
        reply4 = res4.get("reply_text", "")
        self.assertIn("৮০", reply4)
        self.assertIn("প্যাকেজ ১", reply4)
        self.assertNotIn("সহযোগিতা প্রয়োজন হলে জানাবেন", reply4)
        self.assertNotIn("কত পিস বানাবেন", reply4)

    # 13. Human takeover remains silent
    def test_13_human_takeover_remains_silent(self):
        set_admin_takeover(
            sender_id=self.sender_id,
            workspace_id=self.workspace_id,
            takeover_by="admin_test",
            takeover_reason="audit_test"
        )
        self.assertFalse(is_conversation_ai_active(self.sender_id, self.workspace_id))

        val = ResponseValidator.validate_and_sanitize(
            draft_response={"reply_text": "Should not be sent"},
            customer_message="প্রতি পিস কত টাকা রাখবেন",
            sender_id=self.sender_id,
            workspace_id=self.workspace_id
        )
        self.assertTrue(val.get("is_blocked"))
        self.assertEqual(val.get("reply_text"), "")

        enable_conversation_ai(sender_id=self.sender_id, workspace_id=self.workspace_id, enabled_by="admin_test")
        self.assertTrue(is_conversation_ai_active(self.sender_id, self.workspace_id))

    # 14. Package 7 floor remains 82 Tk
    def test_14_package_7_floor_remains_82_tk(self):
        calc = calculate_package_price("7", 100)
        self.assertEqual(calc["regular_price"], 91.0)
        self.assertEqual(calc["max_allowed_discount"], 9.0)
        self.assertEqual(calc["min_allowed_unit_price"], 82.0)

    # 15. Owner Approval remains mandatory below floor
    def test_15_owner_approval_mandatory_below_floor(self):
        step = negotiate_step("7", 100, current_discount=9.0, customer_demanded_price=80.0)
        self.assertTrue(step["requires_owner_approval"])
        self.assertEqual(step["offered_unit_price"], 82.0)


if __name__ == "__main__":
    unittest.main()
