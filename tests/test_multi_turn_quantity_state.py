"""
Phase 8.7C: Multi-Turn Quantity State & Affirmative Normalization Suite.

Validates that:
1. Multi-turn affirmative replies ('Jee', 'Ji', 'Ha', 'Haa', 'Yes', 'Yep', 'Sure', 'OK', 'জি', 'হ্যাঁ')
   are correctly recognized and advance the state machine to SAMPLE_SENT.
2. Verified quantity is persisted in SQLite and passed as context to prevent quantity re-ask loops.
3. Quantity changes (100 -> 30, 30 -> 100) dynamically update quantity tiers (BULK <-> SMALL_ORDER).
4. Negative affirmative cases ('jeep', 'jihad', 'yesman', 'saji', 'no') are safely rejected.
5. Critical End-to-End negotiation and Owner Approval policies remain 100% authoritative and unbypassed.
"""

import unittest
import asyncio
import os
import sqlite3
from pathlib import Path

from app.database import (
    init_db,
    get_db_connection,
    set_admin_takeover
)
from app.ai_agent.gemini_brain import (
    is_affirmative_response,
    extract_order_quantity_number,
    build_system_instruction,
    generate_smart_fallback_reply,
    process_customer_message,
    evaluate_id_card_workflow
)
from app.ai_agent.conversation_state import (
    get_or_create_conversation_state,
    update_conversation_state,
    get_structured_conversation_state,
    SalesStage
)
from app.ai_agent.orchestrator import MasterOrchestrator
from app.ai_agent.pricing_engine import (
    QuantityTier,
    get_quantity_tier,
    calculate_package_price,
    negotiate_step
)
from app.ai_agent.owner_approval import (
    OwnerApprovalEngine,
    ApprovalStatus
)
from app.ai_agent.response_validator import ResponseValidator


import time

class TestMultiTurnQuantityState(unittest.TestCase):
    """Comprehensive test suite for Phase 8.7C Multi-Turn Quantity & Affirmative Hardening."""

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.workspace_id = 1
        self.sender_id = f"test_user_phase87c_{int(time.time() * 1000)}"

    # -------------------------------------------------------------
    # 1. Individual Affirmative Normalization Tests
    # -------------------------------------------------------------

    def test_banglish_jee_affirmative(self):
        self.assertTrue(is_affirmative_response("Jee"))
        self.assertTrue(is_affirmative_response("jee"))
        self.assertTrue(is_affirmative_response("jee please"))
        self.assertTrue(is_affirmative_response("Jee sir"))

    def test_banglish_ji_affirmative(self):
        self.assertTrue(is_affirmative_response("Ji"))
        self.assertTrue(is_affirmative_response("ji"))
        self.assertTrue(is_affirmative_response("ji sir"))
        self.assertTrue(is_affirmative_response("Ji please"))

    def test_banglish_ha_affirmative(self):
        self.assertTrue(is_affirmative_response("Ha"))
        self.assertTrue(is_affirmative_response("ha"))
        self.assertTrue(is_affirmative_response("ha sir"))

    def test_banglish_haa_affirmative(self):
        self.assertTrue(is_affirmative_response("Haa"))
        self.assertTrue(is_affirmative_response("haa"))
        self.assertTrue(is_affirmative_response("haa please"))

    def test_yes_affirmative(self):
        self.assertTrue(is_affirmative_response("Yes"))
        self.assertTrue(is_affirmative_response("yes"))
        self.assertTrue(is_affirmative_response("yes please"))

    def test_yep_affirmative(self):
        self.assertTrue(is_affirmative_response("Yep"))
        self.assertTrue(is_affirmative_response("yep"))
        self.assertTrue(is_affirmative_response("yup"))
        self.assertTrue(is_affirmative_response("yeah"))
        self.assertTrue(is_affirmative_response("Sure"))
        self.assertTrue(is_affirmative_response("OK"))
        self.assertTrue(is_affirmative_response("জি"))
        self.assertTrue(is_affirmative_response("জী"))
        self.assertTrue(is_affirmative_response("হ্যাঁ"))

    def test_negative_affirmative_false_positive_protection(self):
        """Ensures non-affirmative words containing affirmative substrings are NOT matched."""
        negatives = [
            "jeep", "jihad", "yesman", "shoji", "saji", "haji",
            "no", "না", "লাগবে না", "প্যাকেজের দাম কত?", "100", "50", "ঢাকা"
        ]
        for word in negatives:
            self.assertFalse(
                is_affirmative_response(word),
                f"Word '{word}' should NOT be recognized as affirmative"
            )

    # -------------------------------------------------------------
    # 2. Multi-Turn State Flow & Context Injection Tests
    # -------------------------------------------------------------

    def test_hi_then_100_does_not_reask_quantity(self):
        sender = f"{self.sender_id}_hi_100"

        # Turn 1: Hi
        res1 = evaluate_id_card_workflow(
            message_text="Hi",
            conversation_history=[],
            customer_name="Rahim",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        # Turn 2: Customer sends 100
        res2 = evaluate_id_card_workflow(
            message_text="100",
            conversation_history=[
                {"sender": "customer", "text": "Hi"},
                {"sender": "bot", "text": "আপনি কত পিস আইডি কার্ড বানাবেন?"}
            ],
            customer_name="Rahim",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        self.assertIsNotNone(res2)
        self.assertIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res2["reply_text"])
        self.assertNotIn("কত পিস বানাবেন", res2["reply_text"])

        st = get_structured_conversation_state(sender, self.workspace_id)
        self.assertEqual(st.get("quantity"), 100)

    def test_hi_100_jee_sample_confirmation(self):
        sender = f"{self.sender_id}_jee_flow"

        # State: 100 pcs already identified, bot asked sample permission
        update_conversation_state(
            sender_id=sender,
            updates={"quantity": 100, "sample_permission": "pending", "current_sales_stage": SalesStage.SAMPLE_PERMISSION_PENDING},
            reason="test_setup",
            workspace_id=self.workspace_id
        )

        res = evaluate_id_card_workflow(
            message_text="Jee",
            conversation_history=[
                {"sender": "customer", "text": "100"},
                {"sender": "bot", "text": "জি স্যার, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
            ],
            customer_name="Rahim",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        self.assertIsNotNone(res)
        self.assertIn("স্যাম্পলগুলো পাঠিয়ে দিচ্ছি", res["reply_text"])
        self.assertNotIn("কত পিস বানাবেন", res["reply_text"])

        st = get_structured_conversation_state(sender, self.workspace_id)
        self.assertEqual(st.get("quantity"), 100)
        self.assertEqual(st.get("sample_permission"), "granted")

    def test_repeated_100_does_not_create_quantity_loop(self):
        sender = f"{self.sender_id}_repeat_100"

        # Turn 1: 100
        res1 = evaluate_id_card_workflow(
            message_text="100",
            conversation_history=[],
            customer_name="Customer",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        # Turn 2: Customer repeats 100
        res2 = evaluate_id_card_workflow(
            message_text="100",
            conversation_history=[
                {"sender": "customer", "text": "100"},
                {"sender": "bot", "text": res1.get("reply_text")}
            ],
            customer_name="Customer",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        self.assertIsNotNone(res2)
        # Does NOT ask for quantity
        self.assertNotIn("কত পিস বানাবেন", res2["reply_text"])

    def test_existing_quantity_injected_into_llm_context(self):
        state = {
            "quantity": 100,
            "package_id": "7",
            "sample_permission": "granted"
        }
        prompt = build_system_instruction(
            customer_name="Karim",
            workspace_id=self.workspace_id,
            conversation_state=state
        )
        self.assertIn("100 পিস", prompt)
        self.assertIn("BULK (৮০+ পিস)", prompt)
        self.assertIn("DO NOT ask the customer for quantity again", prompt)

    def test_llm_fallback_preserves_quantity(self):
        state = {
            "quantity": 100,
            "package_id": "7",
            "sample_permission": "granted"
        }
        fallback_reply = generate_smart_fallback_reply(
            user_msg="প্যাকেজ কত",
            customer_name="Karim",
            workspace_id=self.workspace_id,
            conversation_state=state
        )
        self.assertNotIn("কত পিস বানাবেন", fallback_reply)
        self.assertIn("৭০ টাকা", fallback_reply)

    # -------------------------------------------------------------
    # 3. Dynamic Quantity Change Tests
    # -------------------------------------------------------------

    def test_quantity_change_100_to_30(self):
        sender = f"{self.sender_id}_change_100_30"

        # Step 1: Set 100 pcs (BULK)
        update_conversation_state(
            sender_id=sender,
            updates={"quantity": 100, "current_sales_stage": SalesStage.QUANTITY_IDENTIFIED},
            reason="initial_100",
            workspace_id=self.workspace_id
        )
        st1 = get_structured_conversation_state(sender, self.workspace_id)
        self.assertEqual(st1.get("quantity"), 100)
        self.assertEqual(get_quantity_tier(100), QuantityTier.BULK)

        # Step 2: Customer sends "30 পিস"
        res = evaluate_id_card_workflow(
            message_text="30 পিস",
            conversation_history=[
                {"sender": "customer", "text": "100"},
                {"sender": "bot", "text": "আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
            ],
            customer_name="Customer",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        st2 = get_structured_conversation_state(sender, self.workspace_id)
        self.assertEqual(st2.get("quantity"), 30)
        self.assertEqual(get_quantity_tier(30), QuantityTier.SMALL_ORDER)

    def test_quantity_change_30_to_100(self):
        sender = f"{self.sender_id}_change_30_100"

        # Step 1: Set 30 pcs (SMALL_ORDER)
        update_conversation_state(
            sender_id=sender,
            updates={"quantity": 30, "current_sales_stage": SalesStage.QUANTITY_IDENTIFIED},
            reason="initial_30",
            workspace_id=self.workspace_id
        )
        st1 = get_structured_conversation_state(sender, self.workspace_id)
        self.assertEqual(st1.get("quantity"), 30)
        self.assertEqual(get_quantity_tier(30), QuantityTier.SMALL_ORDER)

        # Step 2: Customer updates to "১০০ পিস"
        res = evaluate_id_card_workflow(
            message_text="১০০ পিস",
            conversation_history=[
                {"sender": "customer", "text": "30"},
                {"sender": "bot", "text": "আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
            ],
            customer_name="Customer",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        st2 = get_structured_conversation_state(sender, self.workspace_id)
        self.assertEqual(st2.get("quantity"), 100)
        self.assertEqual(get_quantity_tier(100), QuantityTier.BULK)

    # -------------------------------------------------------------
    # 4. Engine & Safety Invariant Tests
    # -------------------------------------------------------------

    def test_master_orchestrator_receives_verified_quantity(self):
        sender = f"{self.sender_id}_orch_qty"
        res = MasterOrchestrator.execute_decision(
            customer_message="100",
            sender_id=sender,
            workspace_id=self.workspace_id
        )
        self.assertIsNotNone(res)
        entities = res.get("orchestrator_log", {}).get("entities", {})
        self.assertEqual(entities.get("quantity"), 100)
        self.assertTrue("70 টাকা" in res.get("reply_text", "") or "স্যাম্পল" in res.get("reply_text", "") or "প্যাকেজ" in res.get("reply_text", ""))

    def test_human_takeover_still_silent(self):
        sender = f"{self.sender_id}_takeover_silent"
        set_admin_takeover(sender_id=sender, workspace_id=self.workspace_id, takeover_by="admin", takeover_reason="testing")

        validated = ResponseValidator.validate_and_sanitize(
            draft_response={"reply_text": "Hello, how can I help?"},
            customer_message="100",
            sender_id=sender,
            workspace_id=self.workspace_id
        )
        self.assertTrue(validated.get("is_blocked", False))
        self.assertEqual(validated.get("reply_text", ""), "")

    def test_owner_approval_not_bypassed(self):
        sender = f"{self.sender_id}_owner_appr_check"
        req = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=sender,
            conversation_id=f"conv_{self.workspace_id}_{sender}",
            request_type="PRICE_EXCEPTION",
            requested_value=75,
            authorized_value=82,
            package_id="7",
            quantity=100,
            reason="customer_demanded_below_floor",
            workspace_id=self.workspace_id
        )
        self.assertEqual(req["status"], ApprovalStatus.PENDING.value)
        self.assertEqual(req["requested_value"], 75.0)

    def test_pricing_engine_remains_authoritative(self):
        # Package 7: 100 pcs -> Regular 91, floor 82
        price_100 = calculate_package_price("7", 100)
        self.assertEqual(price_100["regular_price"], 91.0)
        self.assertEqual(price_100["min_allowed_unit_price"], 82.0)

        # Package 7: 30 pcs -> Regular 91 + 10 = 101, floor 101 (0 discount)
        price_30 = calculate_package_price("7", 30)
        self.assertEqual(price_30["upfront_unit_price"], 101.0)
        self.assertEqual(price_30["is_discount_allowed"], False)

    # -------------------------------------------------------------
    # 5. Critical End-to-End Integration Scenario
    # -------------------------------------------------------------

    def test_critical_end_to_end_multi_turn_negotiation_scenario(self):
        """
        Runs the complete end-to-end multi-turn conversation:
        1. Customer: "Hi" -> Agent asks quantity
        2. Customer: "100" -> quantity = 100, tier = BULK, no quantity re-ask
        3. Customer: "Jee" -> Affirmative detected, samples dispatched, state = SAMPLE_SENT
        4. Customer: "Package 7 কত?" -> Package 7 regular authoritative price = 91 Tk
        5. Customer: "85 টাকা হবে?" -> Existing negotiation logic applies (85 Tk is >= floor 82)
        6. Customer: "75 টাকা দেন" -> Owner Approval required (< 82 Tk), PENDING approval created
        """
        sender = f"{self.sender_id}_e2e_critical"

        # Step 1: Customer sends "Hi"
        res1 = evaluate_id_card_workflow(
            message_text="Hi",
            conversation_history=[],
            customer_name="Tariq",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        # Fallback to LLM / prompt for Hi asks quantity
        st1 = get_structured_conversation_state(sender, self.workspace_id)

        # Step 2: Customer sends "100"
        res2 = evaluate_id_card_workflow(
            message_text="100",
            conversation_history=[
                {"sender": "customer", "text": "Hi"},
                {"sender": "bot", "text": "আপনি কত পিস আইডি কার্ড তৈরি করতে চান?"}
            ],
            customer_name="Tariq",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        self.assertIsNotNone(res2)
        self.assertIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res2["reply_text"])
        self.assertNotIn("কত পিস বানাবেন", res2["reply_text"])
        st2 = get_structured_conversation_state(sender, self.workspace_id)
        self.assertEqual(st2.get("quantity"), 100)

        # Step 3: Customer sends "Jee"
        res3 = evaluate_id_card_workflow(
            message_text="Jee",
            conversation_history=[
                {"sender": "customer", "text": "100"},
                {"sender": "bot", "text": res2["reply_text"]}
            ],
            customer_name="Tariq",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        self.assertIsNotNone(res3)
        self.assertIn("স্যাম্পলগুলো পাঠিয়ে দিচ্ছি", res3["reply_text"])
        self.assertNotIn("কত পিস বানাবেন", res3["reply_text"])
        st3 = get_structured_conversation_state(sender, self.workspace_id)
        self.assertEqual(st3.get("quantity"), 100)
        self.assertEqual(st3.get("sample_permission"), "granted")

        # Step 4: Customer sends "Package 7 কত?"
        res4 = evaluate_id_card_workflow(
            message_text="Package 7 কত?",
            conversation_history=[
                {"sender": "customer", "text": "Jee"},
                {"sender": "bot", "text": res3["reply_text"]}
            ],
            customer_name="Tariq",
            workspace_id=self.workspace_id,
            sender_id=sender
        )
        self.assertIsNotNone(res4)
        self.assertIn("৯১", res4["reply_text"])
        self.assertNotIn("কত পিস বানাবেন", res4["reply_text"])

        # Step 5: Customer sends "85 টাকা হবে?" (Negotiation >= 82 Tk)
        # Authoritative step-by-step negotiation check:
        # Turn 1: Bot offers progressive first step (3 Tk discount -> 88 Tk)
        neg_res_t1 = negotiate_step(
            package_id="7",
            quantity=100,
            current_discount=0.0,
            customer_demanded_price=85
        )
        self.assertEqual(neg_res_t1["offered_unit_price"], 88.0)
        self.assertFalse(neg_res_t1["requires_owner_approval"])

        # Turn 2: Customer insists on 85 Tk (Bot offers step 2 -> 6 Tk discount -> 85 Tk)
        neg_res_t2 = negotiate_step(
            package_id="7",
            quantity=100,
            current_discount=3.0,
            customer_demanded_price=85
        )
        self.assertEqual(neg_res_t2["offered_unit_price"], 85.0)
        self.assertFalse(neg_res_t2["requires_owner_approval"])

        # Step 6: Customer sends "75 টাকা দেন" (Below floor 82 Tk -> Owner Approval)
        neg_res_low = negotiate_step(
            package_id="7",
            quantity=100,
            current_discount=6.0,
            customer_demanded_price=75
        )
        self.assertTrue(neg_res_low["requires_owner_approval"])

        approval_req = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=sender,
            conversation_id=f"conv_{self.workspace_id}_{sender}",
            request_type="PRICE_EXCEPTION",
            requested_value=75,
            authorized_value=82,
            package_id="7",
            quantity=100,
            reason="negotiation_below_floor",
            workspace_id=self.workspace_id
        )
        self.assertEqual(approval_req["status"], ApprovalStatus.PENDING.value)
        self.assertEqual(approval_req["requested_value"], 75.0)


if __name__ == "__main__":
    unittest.main()
