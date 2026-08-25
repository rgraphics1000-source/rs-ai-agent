"""
Phase 6.0 Automated Test Suite: Master Brain Orchestrator Architecture Tests

Tests:
1. Price inquiry uses Pricing Engine
2. Negotiation uses Pricing Engine
3. Media inquiry uses Media Router
4. State is read before decision
5. Human takeover blocks orchestrator (absolute silence)
6. Unknown data triggers safe fallback
7. Multi-intent message selects multiple tools
8. Gemini cannot override verified price
9. Orchestrator does not duplicate pricing logic
10. Orchestrator does not duplicate media logic
11. Orchestrator does not duplicate state
12. Validation remains mandatory
"""

import unittest
from unittest.mock import patch
from app.database import init_db, ensure_default_saved_media, get_db_connection
from app.ai_agent.orchestrator import MasterOrchestrator, CustomerIntent
from app.ai_agent.pricing_engine import calculate_package_price, PACKAGE_CATALOG
from app.ai_agent.media_router import MediaRouter, MediaIntent
from app.ai_agent.conversation_state import (
    update_conversation_state, get_structured_conversation_state, SalesStage
)
from app.ai_agent.response_validator import ResponseValidator


class TestMasterOrchestrator(unittest.TestCase):

    def setUp(self):
        init_db()
        ensure_default_saved_media()
        self.ws_id = 1
        self.test_sender = f"orch_test_{self._testMethodName}"
        from app.database import enable_conversation_ai
        enable_conversation_ai(sender_id=self.test_sender, workspace_id=self.ws_id, enabled_by="test_setup")

    def test_01_price_inquiry_uses_pricing_engine(self):
        """TEST 1: Price inquiry selects Pricing Engine and calculates authoritative price."""
        msg = "১০০টা Package 7 এর দাম কত?"
        intent_res = MasterOrchestrator.detect_intents_and_entities(msg)
        self.assertIn(CustomerIntent.PRICE_INQUIRY, intent_res["intents"])
        self.assertEqual(intent_res["entities"]["quantity"], 100)
        self.assertEqual(intent_res["entities"]["package_id"], "7")

        decision = MasterOrchestrator.execute_decision(
            customer_message=msg,
            sender_id=self.test_sender,
            workspace_id=self.ws_id
        )
        self.assertIn("pricing_engine", decision["orchestrator_log"]["selected_tools"])
        self.assertIn("91", decision["reply_text"])
        print("[PASSED] Test 01: Price inquiry uses Pricing Engine.")

    def test_02_negotiation_uses_pricing_engine(self):
        """TEST 2: Negotiation selects Pricing Engine with discount bounds."""
        # 100 pcs Package 7, customer asks for 80 tk (below floor of 82 tk)
        msg = "১০০টা প্যাকেজ ৭ নেব, ৮০ টাকা করে দেন।"
        intent_res = MasterOrchestrator.detect_intents_and_entities(msg)
        self.assertIn(CustomerIntent.NEGOTIATION, intent_res["intents"])
        self.assertEqual(intent_res["entities"]["demanded_price"], 80.0)

        decision = MasterOrchestrator.execute_decision(
            customer_message=msg,
            sender_id=self.test_sender,
            workspace_id=self.ws_id
        )
        self.assertIn("pricing_engine", decision["orchestrator_log"]["selected_tools"])
        # Demanded 80 tk < floor 82 tk -> requires owner approval
        self.assertTrue(decision["orchestrator_log"]["requires_owner_approval"])
        print("[PASSED] Test 02: Negotiation uses Pricing Engine and flags owner approval.")

    def test_03_media_inquiry_uses_media_router(self):
        """TEST 3: Media inquiries route to Media Router."""
        msg = "গুগল ফর্মে তথ্য সাবমিট করার পর ভুল হলে সংশোধন করার ভিডিও দেন"
        intent_res = MasterOrchestrator.detect_intents_and_entities(msg)
        self.assertIn(CustomerIntent.GOOGLE_FORM_CORRECTION_HELP, intent_res["intents"])

        decision = MasterOrchestrator.execute_decision(
            customer_message=msg,
            sender_id=self.test_sender,
            workspace_id=self.ws_id
        )
        self.assertIn("media_router", decision["orchestrator_log"]["selected_tools"])
        self.assertIn("google_form_edit_correction_guide.mp4", decision["video_url"])
        print("[PASSED] Test 03: Media inquiry selects Media Router.")

    def test_04_state_is_read_before_decision(self):
        """TEST 4: Existing conversation state is inherited before decision execution."""
        # Seed conversation state with quantity=200 and package_id=3
        update_conversation_state(
            sender_id=self.test_sender,
            updates={
                "quantity": 200,
                "package_id": "3",
                "current_sales_stage": SalesStage.PRICE_READY.value
            },
            workspace_id=self.ws_id
        )

        # Customer sends message without mentioning quantity or package: "মোট কত খরচ পড়বে?"
        intent_res = MasterOrchestrator.detect_intents_and_entities(
            message="মোট কত খরচ পড়বে?",
            conversation_state=get_structured_conversation_state(self.test_sender, self.ws_id)
        )
        self.assertEqual(intent_res["entities"]["quantity"], 200)
        self.assertEqual(intent_res["entities"]["package_id"], "3")
        print("[PASSED] Test 04: State is loaded before decision.")

    def test_05_human_takeover_blocks_orchestrator(self):
        """TEST 5: Human / Admin takeover enforces absolute silence."""
        from app.database import set_admin_takeover, enable_conversation_ai
        set_admin_takeover(sender_id=self.test_sender, workspace_id=self.ws_id, takeover_by="admin", takeover_reason="test")

        decision = MasterOrchestrator.execute_decision(
            customer_message="হ্যালো, প্যাকেজ ৭ এর দাম কত?",
            sender_id=self.test_sender,
            workspace_id=self.ws_id
        )
        self.assertTrue(decision["is_blocked"])
        self.assertEqual(decision["reply_text"], "")
        self.assertEqual(decision["block_reason"], "admin_takeover_active")

        # Re-enable AI
        enable_conversation_ai(sender_id=self.test_sender, workspace_id=self.ws_id)
        print("[PASSED] Test 05: Human takeover blocks orchestrator with absolute silence.")

    def test_06_unknown_data_triggers_safe_fallback(self):
        """TEST 6: Unknown / unhandled intent generates safe courteous fallback."""
        msg = "আপনার অফিসের ছাদের রঙ কী?"
        decision = MasterOrchestrator.execute_decision(
            customer_message=msg,
            sender_id=self.test_sender,
            workspace_id=self.ws_id
        )
        self.assertTrue("আমাদের টিম" in decision["reply_text"] or "আইডি কার্ড" in decision["reply_text"])
        self.assertEqual(decision["orchestrator_log"]["primary_intent"], CustomerIntent.UNKNOWN)
        print("[PASSED] Test 06: Unknown inquiry triggers safe fallback.")

    def test_07_multi_intent_message_selects_multiple_tools(self):
        """TEST 7: Multi-intent message (Price + Delivery) selects multiple tools."""
        msg = "১০০টা Package 7 কত আর ঢাকার ভেতরে কুরিয়ার চার্জ কত?"
        intent_res = MasterOrchestrator.detect_intents_and_entities(msg)
        self.assertIn(CustomerIntent.PRICE_INQUIRY, intent_res["intents"])
        self.assertIn(CustomerIntent.DELIVERY_INQUIRY, intent_res["intents"])

        decision = MasterOrchestrator.execute_decision(
            customer_message=msg,
            sender_id=self.test_sender,
            workspace_id=self.ws_id
        )
        tools = decision["orchestrator_log"]["selected_tools"]
        self.assertIn("pricing_engine", tools)
        self.assertIn("delivery_calculator", tools)
        print("[PASSED] Test 07: Multi-intent message selects multiple tools.")

    def test_08_gemini_cannot_override_verified_price(self):
        """TEST 8: ResponseValidator guarantees invalid/hallucinated price is sanitized."""
        hallucinated_draft = {
            "reply_text": "প্যাকেজ ৭ এর দাম প্রতি পিস ৫০ টাকা মাত্র এবং পুরো ক্যাশ অন ডেলিভারি দেওয়া হবে।",
            "matched_images": [],
            "media_sequence": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }
        val = ResponseValidator.validate_and_sanitize(
            draft_response=hallucinated_draft,
            customer_message="প্যাকেজ ৭ এর দাম কত?",
            sender_id=self.test_sender,
            workspace_id=self.ws_id
        )
        self.assertNotIn("৫০ টাকা", val["reply_text"])
        self.assertNotIn("পুরো ক্যাশ অন ডেলিভারি", val["reply_text"])
        print("[PASSED] Test 08: Verified price & COD policy cannot be overridden.")

    def test_09_orchestrator_does_not_duplicate_pricing_logic(self):
        """TEST 9: Orchestrator invokes authoritative pricing_engine functions."""
        with patch("app.ai_agent.orchestrator.calculate_package_price", wraps=calculate_package_price) as mock_price:
            MasterOrchestrator.execute_decision(
                customer_message="১০০টা Package 7 এর রেট কত?",
                sender_id=self.test_sender,
                workspace_id=self.ws_id
            )
            mock_price.assert_called()
        print("[PASSED] Test 09: Orchestrator delegates pricing calculation to pricing_engine.")

    def test_10_orchestrator_does_not_duplicate_media_logic(self):
        """TEST 10: Orchestrator invokes authoritative MediaRouter."""
        with patch.object(MediaRouter, "route_media", wraps=MediaRouter.route_media) as mock_media:
            MasterOrchestrator.execute_decision(
                customer_message="তথ্য সংশোধনের নিয়ম কি?",
                sender_id=self.test_sender,
                workspace_id=self.ws_id
            )
            mock_media.assert_called()
        print("[PASSED] Test 10: Orchestrator delegates media routing to MediaRouter.")

    def test_11_orchestrator_does_not_duplicate_state(self):
        """TEST 11: Orchestrator loads state via get_structured_conversation_state."""
        with patch("app.ai_agent.orchestrator.get_structured_conversation_state", wraps=get_structured_conversation_state) as mock_state:
            MasterOrchestrator.execute_decision(
                customer_message="আমার কার্ডের খবর কি?",
                sender_id=self.test_sender,
                workspace_id=self.ws_id
            )
            mock_state.assert_called()
        print("[PASSED] Test 11: Orchestrator reads state via conversation_state machine.")

    def test_12_validation_remains_mandatory(self):
        """TEST 12: Every orchestrator execution runs through ResponseValidator."""
        with patch.object(ResponseValidator, "validate_and_sanitize", wraps=ResponseValidator.validate_and_sanitize) as mock_val:
            MasterOrchestrator.execute_decision(
                customer_message="প্যাকেজ ১ কত?",
                sender_id=self.test_sender,
                workspace_id=self.ws_id
            )
            mock_val.assert_called()
        print("[PASSED] Test 12: Validation pipeline remains mandatory.")


if __name__ == "__main__":
    unittest.main()
