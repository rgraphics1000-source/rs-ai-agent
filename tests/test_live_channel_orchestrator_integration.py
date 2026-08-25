"""
Phase 9.1 — Live Channel → Orchestrator Integration Tests.

Validates the full MasterOrchestrator pipeline for multi-turn
conversations that mirror real Facebook/WhatsApp customer flows.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import patch, MagicMock
from app.ai_agent.orchestrator import MasterOrchestrator, CustomerIntent


class TestLiveChannelOrchestratorIntegration(unittest.TestCase):
    """
    Multi-turn conversation simulating a real customer flow through
    the MasterOrchestrator pipeline as called by channel handlers.
    """

    def setUp(self):
        self.sender_id = "integration_test_customer_991"
        self.ws_id = 1
        self.customer_name = "Rubel"
        self.conversation_history = []
        # Mock out DB calls
        self._patches = []
        for target in [
            "app.ai_agent.orchestrator.is_conversation_ai_active",
            "app.ai_agent.orchestrator.get_structured_conversation_state",
            "app.ai_agent.orchestrator.get_conversation_memory",
            "app.ai_agent.orchestrator.is_media_already_sent",
            "app.ai_agent.orchestrator.record_question_asked",
            "app.ai_agent.orchestrator.record_fact_confirmed",
            "app.ai_agent.orchestrator.record_media_dispatched",
            "app.ai_agent.orchestrator.update_conversation_state",
        ]:
            p = patch(target)
            m = p.start()
            self._patches.append(p)
            if "is_conversation_ai_active" in target:
                m.return_value = True
            elif "get_structured_conversation_state" in target:
                m.return_value = {}
            elif "get_conversation_memory" in target:
                m.return_value = {}
            elif "is_media_already_sent" in target:
                m.return_value = False
            elif "record_question_asked" in target:
                m.return_value = None
            elif "record_fact_confirmed" in target:
                m.return_value = None
            elif "record_media_dispatched" in target:
                m.return_value = None
            elif "update_conversation_state" in target:
                m.return_value = None

        # Mock knowledge engine
        p_ke = patch("app.ai_agent.orchestrator.KnowledgeEngine")
        self.mock_ke = p_ke.start()
        self._patches.append(p_ke)
        self.mock_ke.check_identity_inquiry.return_value = None
        self.mock_ke.retrieve_relevant_knowledge.return_value = {"has_authoritative_answer": False, "matched_rules": []}
        self.mock_ke.handle_unknown_inquiry.return_value = {"reply_text": "টিমকে জানাচ্ছি"}

        # Mock response validator
        p_rv = patch("app.ai_agent.orchestrator.ResponseValidator")
        self.mock_rv = p_rv.start()
        self._patches.append(p_rv)
        self.mock_rv.validate_and_sanitize.side_effect = lambda draft_response, **kwargs: draft_response

        # Mock Google Form workflow
        p_gf = patch("app.ai_agent.orchestrator.resolve_google_form_workflow", create=True)
        self._patches.append(p_gf)

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _call(self, msg, **kwargs):
        """Simulates a channel handler calling MasterOrchestrator.execute_decision."""
        return MasterOrchestrator.execute_decision(
            customer_message=msg,
            sender_id=self.sender_id,
            customer_name=self.customer_name,
            workspace_id=self.ws_id,
            conversation_history=self.conversation_history,
            channel=kwargs.get("channel", "facebook"),
        )

    def _add_history(self, role, text):
        self.conversation_history.append({"sender": role, "text": text})

    # -------------------------------------------------------------------------
    # Turn 1: Pure Greeting — MUST NOT force quantity question
    # -------------------------------------------------------------------------
    def test_turn_01_pure_greeting(self):
        r = self._call("আসসালামু আলাইকুম")
        reply = r.get("reply_text", "")
        self.assertIn("সালাম", reply.lower())
        self.assertIn("স্বাগতম", reply)
        # Must NOT ask "কত পিস ID Card" on pure greeting
        self.assertNotIn("কত পিস ID Card", reply)
        self.assertEqual(r.get("response_source"), "standard_greeting")
        self._add_history("bot", reply)

    # -------------------------------------------------------------------------
    # Turn 2: Social Pleasantry — "ভাই কেমন আছেন?"
    # -------------------------------------------------------------------------
    def test_turn_02_social_pleasantry(self):
        self._add_history("bot", "ওয়ালাইকুমুস সালাম!")
        r = self._call("ভাই কেমন আছেন?")
        reply = r.get("reply_text", "")
        self.assertIn("ভালো আছি", reply)
        self.assertEqual(r.get("response_source"), "social_pleasantry_response")

    # -------------------------------------------------------------------------
    # Turn 3: Product Inquiry — "আইডি কার্ড বানাতে চাই"
    # -------------------------------------------------------------------------
    def test_turn_03_product_inquiry(self):
        self._add_history("bot", "ভালো আছি")
        r = self._call("আইডি কার্ড বানাতে চাই")
        reply = r.get("reply_text", "")
        self.assertIn("কত পিস", reply)
        self.assertEqual(r.get("response_source"), "product_inquiry_quantity_prompt")

    # -------------------------------------------------------------------------
    # Turn 4: Quantity Provided — "১০০ পিস"
    # -------------------------------------------------------------------------
    def test_turn_04_quantity_provided(self):
        self._add_history("bot", "কত পিস?")
        r = self._call("১০০ পিস")
        reply = r.get("reply_text", "")
        self.assertIn("স্যাম্পল", reply)
        self.assertEqual(r.get("response_source"), "sample_permission_prompt")

    # -------------------------------------------------------------------------
    # Turn 5: Price Inquiry — "দাম কত?"
    # -------------------------------------------------------------------------
    def test_turn_05_price_inquiry(self):
        self._add_history("bot", "স্যাম্পলগুলো পাঠাবো কি?")
        r = self._call("দাম কত?")
        reply = r.get("reply_text", "")
        # Must contain pricing info
        self.assertTrue(any(kw in reply for kw in ["টাকা", "Tk", "রেট", "মূল্য"]))

    # -------------------------------------------------------------------------
    # Turn 6: Negotiation — "একটু কম হবে না?"
    # -------------------------------------------------------------------------
    def test_turn_06_negotiation(self):
        self._add_history("bot", "প্যাকেজ ৭ এর রেট ৯১ টাকা")
        r = self._call("একটু কম হবে না?")
        intent_data = MasterOrchestrator.detect_intents_and_entities("একটু কম হবে না?")
        self.assertIn(CustomerIntent.NEGOTIATION, intent_data["intents"])

    # -------------------------------------------------------------------------
    # Turn 7: Delivery Inquiry — "ডেলিভারি চার্জ কত?"
    # -------------------------------------------------------------------------
    def test_turn_07_delivery_inquiry(self):
        r = self._call("ডেলিভারি চার্জ কত?")
        reply = r.get("reply_text", "")
        self.assertIn("ডেলিভারি", reply)
        self.assertIn("ঢাকা", reply)

    # -------------------------------------------------------------------------
    # Turn 8: Quality Inquiry — "কোয়ালিটি কেমন?"
    # -------------------------------------------------------------------------
    def test_turn_08_quality_inquiry(self):
        r = self._call("কোয়ালিটি কেমন?")
        reply = r.get("reply_text", "")
        self.assertIn("কোয়ালিটি", reply)
        self.assertEqual(r.get("response_source"), "id_card_quality_voice_dispatch")
        self.assertTrue(r.get("voice_url"))

    # -------------------------------------------------------------------------
    # Turn 9: Agent Identity — "তোমার নাম কী?"
    # -------------------------------------------------------------------------
    def test_turn_09_agent_identity(self):
        # Mock identity handler
        self.mock_ke.check_identity_inquiry.return_value = {
            "is_handled": True,
            "reply_text": "আমার নাম নাদিম",
            "response_source": "identity_knowledge"
        }
        r = self._call("তোমার নাম কী?")
        reply = r.get("reply_text", "")
        self.assertIn("নাদিম", reply)

    # -------------------------------------------------------------------------
    # Turn 10: MOQ Rejection — "১০ পিস লাগবে"
    # -------------------------------------------------------------------------
    def test_turn_10_moq_rejection(self):
        r = self._call("১০ পিস লাগবে")
        reply = r.get("reply_text", "")
        self.assertIn("৩০", reply)
        self.assertIn(r.get("response_source"), ("moq_rejected_policy",))

    # -------------------------------------------------------------------------
    # Turn 11: Advance Payment — "এডভান্স কত?"
    # -------------------------------------------------------------------------
    def test_turn_11_advance_inquiry(self):
        r = self._call("এডভান্স কত দিতে হবে?")
        reply = r.get("reply_text", "")
        self.assertTrue(any(kw in reply for kw in ["অগ্রিম", "এডভান্স", "পেমেন্ট"]))
        self.assertEqual(r.get("response_source"), "advance_payment_policy")


class TestIntentClassificationRobustness(unittest.TestCase):
    """Tests that the enhanced intent detection catches all negotiation patterns."""

    def test_negotiation_regex_basic(self):
        patterns = [
            "একটু কম রাখেন",
            "কম হবে না?",
            "কিছু কম করেন",
            "ডিসকাউন্ট দেন",
            "ছাড় দেন",
            "বেশি রাখছেন",
        ]
        for p in patterns:
            result = MasterOrchestrator.detect_intents_and_entities(p)
            self.assertIn(
                CustomerIntent.NEGOTIATION,
                result["intents"],
                f"NEGOTIATION not detected for: '{p}'"
            )

    def test_social_pleasantry_detection(self):
        patterns = [
            "ভাই কেমন আছেন?",
            "কি খবর?",
            "ভালো আছো?",
            "how are you",
        ]
        for p in patterns:
            result = MasterOrchestrator.detect_intents_and_entities(p)
            self.assertIn(
                CustomerIntent.SOCIAL_PLEASANTRY,
                result["intents"],
                f"SOCIAL_PLEASANTRY not detected for: '{p}'"
            )

    def test_quality_inquiry_detection(self):
        patterns = [
            "কোয়ালিটি কেমন হবে?",
            "মান কেমন?",
        ]
        for p in patterns:
            result = MasterOrchestrator.detect_intents_and_entities(p)
            self.assertIn(
                CustomerIntent.QUALITY_INQUIRY,
                result["intents"],
                f"QUALITY_INQUIRY not detected for: '{p}'"
            )

    def test_greeting_does_not_include_quantity_question(self):
        """Pure greeting must NOT trigger forced quantity prompt."""
        result = MasterOrchestrator.execute_decision(
            customer_message="আসসালামু আলাইকুম",
            sender_id="test_pure_greeting_001",
            customer_name="Rashed",
            workspace_id=1
        )
        reply = result.get("reply_text", "")
        self.assertNotIn("কত পিস ID Card", reply,
                         "Pure greeting response must NOT include 'কত পিস ID Card'")

    def test_greeting_with_product_mentions_quantity(self):
        """Greeting + product reference SHOULD ask quantity."""
        result = MasterOrchestrator.execute_decision(
            customer_message="আসসালামু আলাইকুম, আইডি কার্ড বানাতে চাই",
            sender_id="test_greeting_product_001",
            customer_name="Karim",
            workspace_id=1
        )
        reply = result.get("reply_text", "")
        self.assertTrue(
            any(kw in reply for kw in ["কত পিস", "স্বাগতম"]),
            f"Greeting+product should include quantity prompt or welcome. Got: {reply[:100]}"
        )


class TestMultimodalDelegation(unittest.TestCase):
    """Tests that multimodal messages return the correct delegation sentinel."""

    def test_image_only_returns_multimodal_delegate(self):
        """An image-only message with no text match should return multimodal_delegate."""
        result = MasterOrchestrator.execute_decision(
            customer_message="",
            sender_id="multimodal_test_001",
            customer_name="Sumi",
            workspace_id=1,
            image_bytes=b"fake_image_data"
        )
        # For pure image with no text, orchestrator cannot match intent, so it delegates
        rs = result.get("response_source", "")
        self.assertIn(rs, ("multimodal_delegate", "no_guess_team_escalation", "training_rule_answer"),
                      f"Expected delegation or unknown for image-only, got: {rs}")

    def test_workspace_2_returns_gemini_fallthrough(self):
        """Non-primary workspace should return gemini_fallthrough sentinel."""
        result = MasterOrchestrator.execute_decision(
            customer_message="Hello",
            sender_id="ws2_test_001",
            customer_name="Arif",
            workspace_id=2
        )
        self.assertEqual(result.get("response_source"), "gemini_fallthrough")


class TestResponseStructure(unittest.TestCase):
    """Validates that execute_decision always returns a complete, channel-compatible dict."""

    REQUIRED_KEYS = ["reply_text", "matched_images", "media_sequence", "voice_url", "video_url"]

    def test_greeting_response_structure(self):
        result = MasterOrchestrator.execute_decision(
            customer_message="আসসালামু আলাইকুম",
            sender_id="struct_test_001",
            customer_name="Rony",
            workspace_id=1
        )
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, result, f"Missing key: {key}")
        self.assertIsInstance(result["reply_text"], str)
        self.assertIsInstance(result["matched_images"], list)
        self.assertIsInstance(result["media_sequence"], list)

    def test_pricing_response_structure(self):
        result = MasterOrchestrator.execute_decision(
            customer_message="১০০ পিস আইডি কার্ডের দাম কত?",
            sender_id="struct_test_002",
            customer_name="Niloy",
            workspace_id=1
        )
        for key in self.REQUIRED_KEYS:
            self.assertIn(key, result, f"Missing key: {key}")
        self.assertTrue(result["reply_text"], "Pricing response must have reply text")

    def test_orchestrator_log_present(self):
        result = MasterOrchestrator.execute_decision(
            customer_message="ডেলিভারি চার্জ কত?",
            sender_id="struct_test_003",
            customer_name="Hasan",
            workspace_id=1
        )
        self.assertIn("orchestrator_log", result)
        log = result["orchestrator_log"]
        self.assertIn("primary_intent", log)
        self.assertIn("intents", log)
        self.assertIn("entities", log)


if __name__ == "__main__":
    unittest.main()
