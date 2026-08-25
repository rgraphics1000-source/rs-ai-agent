"""
Phase 9.3: Comprehensive Conversational Intelligence, Strict Response Ownership,
and Anti-Instruction-Leak Verification Suite.

Tests 18 critical invariants:
1. Pending quantity + "ভালো আছেন?" -> social response (never forced quantity)
2. Pending quantity + "কেমন আছেন?" -> social response
3. Pending quantity + "আপনি কে?" -> Nadim identity response
4. Pending quantity + "প্রতি পিস কত?" -> pricing response
5. Pending quantity + "১০০ পিস" -> quantity workflow
6. Unknown question -> team escalation, no hallucination
7. Same inbound event -> exactly one outbound response
8. Same message processed twice -> second processing produces no duplicate outbound response
9. Already-sent media -> no duplicate dispatch
10. Explicit resend request -> media allowed
11. Training rule survives application restart
12. Training rule version history survives update
13. Owner name inquiry -> never invent owner name
14. Agent name inquiry -> "নাদিম"
15. Internal prompt text -> never exposed to customer
16. Topic switch: "১০০ পিস" -> "প্রতি পিস কত?" -> "ঢাকার বাইরে ডেলিভারি কত?" -> each question gets its own correct answer
17. Topic switch: quantity pending -> social question -> product question -> pricing question -> no repeated quantity interrogation
18. Multilingual / Banglish: "Hi", "Jee", "Ji", "Bhalo achen?", "Apnara per piece koto?" -> correct intent resolution
"""

import unittest
import os
import sqlite3
import time
from unittest.mock import patch, MagicMock

from app.ai_agent.orchestrator import MasterOrchestrator, CustomerIntent
from app.ai_agent.knowledge_engine import KnowledgeEngine, AGENT_NAME_BN
from app.ai_agent.response_validator import ResponseValidator
from app.ai_agent.conversation_state import (
    update_conversation_state, get_structured_conversation_state,
    record_media_dispatched, is_media_already_sent, record_question_asked,
    record_fact_confirmed, SalesStage
)
from app.database import (
    init_db, get_db_connection, create_training_rule, update_training_rule,
    get_active_training_rules, get_training_rule_versions, enable_conversation_ai,
    claim_webhook_event, is_webhook_event_processed, create_team_escalation
)


class TestPhase93ConversationalIntelligence(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["DATABASE_PATH"] = ":memory:"
        init_db()

    def setUp(self):
        self.ws_id = 1
        self.sender_id = f"test_p93_cust_{int(time.time()*1000)}"
        enable_conversation_ai(self.sender_id, self.ws_id)

    # -------------------------------------------------------------
    # 1 & 2. PENDING QUANTITY + SOCIAL PLEASANTRY ("ভালো আছেন?", "কেমন আছেন?")
    # -------------------------------------------------------------
    def test_01_pending_quantity_with_bhalo_achen(self):
        """Invariant 1: Pending quantity must NOT override 'ভালো আছেন?' with quantity demand."""
        record_question_asked(self.sender_id, "QUANTITY_PROMPT", self.ws_id)

        res = MasterOrchestrator.execute_decision(
            customer_message="ভালো আছেন?",
            sender_id=self.sender_id,
            customer_name="Rahim",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        reply = res["reply_text"]
        self.assertTrue("ভালো আছি" in reply or "আলহামদুলিল্লাহ" in reply)
        self.assertNotIn("কত পিস", reply)
        self.assertEqual(res["orchestrator_log"]["primary_intent"], CustomerIntent.SOCIAL_PLEASANTRY)

    def test_02_pending_quantity_with_kemon_achen(self):
        """Invariant 2: Pending quantity must NOT override 'কেমন আছেন?' with quantity demand."""
        record_question_asked(self.sender_id, "QUANTITY_PROMPT", self.ws_id)

        res = MasterOrchestrator.execute_decision(
            customer_message="কেমন আছেন?",
            sender_id=self.sender_id,
            customer_name="Karim",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        reply = res["reply_text"]
        self.assertTrue("ভালো আছি" in reply or "আলহামদুলিল্লাহ" in reply)
        self.assertNotIn("কত পিস", reply)
        self.assertEqual(res["orchestrator_log"]["primary_intent"], CustomerIntent.SOCIAL_PLEASANTRY)

    # -------------------------------------------------------------
    # 3. PENDING QUANTITY + AGENT IDENTITY ("আপনি কে?")
    # -------------------------------------------------------------
    def test_03_pending_quantity_with_apni_ke(self):
        """Invariant 3: Pending quantity must NOT override 'আপনি কে?' with quantity demand."""
        record_question_asked(self.sender_id, "QUANTITY_PROMPT", self.ws_id)

        res = MasterOrchestrator.execute_decision(
            customer_message="আপনি কে?",
            sender_id=self.sender_id,
            customer_name="Customer",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        reply = res["reply_text"]
        self.assertTrue(AGENT_NAME_BN in reply)
        self.assertNotIn("কত পিস", reply)
        self.assertEqual(res["orchestrator_log"]["primary_intent"], CustomerIntent.AGENT_IDENTITY_INQUIRY)

    # -------------------------------------------------------------
    # 4. PENDING QUANTITY + PRICE INQUIRY ("প্রতি পিস কত?")
    # -------------------------------------------------------------
    def test_04_pending_quantity_with_proti_piece_koto(self):
        """Invariant 4: Customer asking price must receive pricing breakdown, not repeated quantity prompt."""
        record_question_asked(self.sender_id, "QUANTITY_PROMPT", self.ws_id)

        res = MasterOrchestrator.execute_decision(
            customer_message="প্রতি পিস কত?",
            sender_id=self.sender_id,
            customer_name="Customer",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        reply = res["reply_text"]
        self.assertTrue("৭০" in reply or "৯১" in reply or "প্যাকেজ" in reply)
        self.assertIn(res["orchestrator_log"]["primary_intent"], (CustomerIntent.PER_PIECE_PRICE, CustomerIntent.PRICE_INQUIRY))

    # -------------------------------------------------------------
    # 5. PENDING QUANTITY + QUANTITY PROVIDED ("১০০ পিস")
    # -------------------------------------------------------------
    def test_05_pending_quantity_with_quantity_provided(self):
        """Invariant 5: When customer provides quantity, transition state and ask for sample permission."""
        record_question_asked(self.sender_id, "QUANTITY_PROMPT", self.ws_id)

        res = MasterOrchestrator.execute_decision(
            customer_message="১০০ পিস",
            sender_id=self.sender_id,
            customer_name="Customer",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        reply = res["reply_text"]
        self.assertTrue("স্যাম্পল" in reply)
        self.assertEqual(res["orchestrator_log"]["primary_intent"], CustomerIntent.QUANTITY_PROVIDED)

    # -------------------------------------------------------------
    # 6. UNKNOWN QUESTION -> TEAM ESCALATION (ZERO HALLUCINATION)
    # -------------------------------------------------------------
    def test_06_unknown_question_team_escalation(self):
        """Invariant 6: Unknown question must escalate cleanly without guessing."""
        res = MasterOrchestrator.execute_decision(
            customer_message="আপনাদের সোনারগাঁওয়ে কি কোনো শাখা আছে?",
            sender_id=self.sender_id,
            customer_name="Customer",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        reply = res["reply_text"]
        self.assertTrue("টিমকে জানাচ্ছি" in reply or "টিম আপনাকে জানাবে" in reply or "সঠিক তথ্য" in reply)
        self.assertNotIn("কত পিস", reply)

    # -------------------------------------------------------------
    # 7 & 8. INBOUND EVENT EXACTLY ONE OUTBOUND RESPONSE & IDEMPOTENCY
    # -------------------------------------------------------------
    def test_07_and_08_webhook_idempotency_deduplication(self):
        """Invariants 7 & 8: Duplicate webhook event must be claimed exactly once."""
        event_id = f"evt_p93_test_{int(time.time()*1000)}"
        first_claim = claim_webhook_event("facebook", event_id, workspace_id=self.ws_id)
        self.assertTrue(first_claim)

        second_claim = claim_webhook_event("facebook", event_id, workspace_id=self.ws_id)
        self.assertFalse(second_claim)

    # -------------------------------------------------------------
    # 9 & 10. MEDIA DUPLICATION PROTECTION & EXPLICIT RESEND
    # -------------------------------------------------------------
    def test_09_media_no_duplicate_dispatch(self):
        """Invariant 9: Media already sent is acknowledged without re-dispatching images."""
        record_media_dispatched(self.sender_id, "samples", ["/static/pkg1.jpg"], self.ws_id)

        res = MasterOrchestrator.execute_decision(
            customer_message="প্যাকেজের ছবি দেখতে চাই",
            sender_id=self.sender_id,
            customer_name="Customer",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        # Should acknowledge previous delivery
        self.assertEqual(len(res["matched_images"]), 0)
        self.assertTrue("পূর্বের পাঠানো স্যাম্পল" in res["reply_text"] or "পছন্দ" in res["reply_text"])

    def test_10_media_explicit_resend_allowed(self):
        """Invariant 10: Explicit resend request permits sending sample images again."""
        record_media_dispatched(self.sender_id, "samples", ["/static/pkg1.jpg"], self.ws_id)

        res = MasterOrchestrator.execute_decision(
            customer_message="ছবিগুলো আবার পাঠান",
            sender_id=self.sender_id,
            customer_name="Customer",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        self.assertTrue(len(res["matched_images"]) > 0 or len(res["media_sequence"]) > 0)

    # -------------------------------------------------------------
    # 11 & 12. TRAINING RULE DURABILITY & VERSION HISTORY
    # -------------------------------------------------------------
    def test_11_training_rule_sqlite_persistence(self):
        """Invariant 11: Training rule created must survive and be retrievable from database."""
        rule_id = create_training_rule(
            title="Durable Test Rule",
            response_or_rule="এটি একটি স্থায়ী টেস্ট উত্তর।",
            rule_type="response",
            question_or_trigger="টেস্ট প্রশ্ন",
            category="Test Category",
            workspace_id=self.ws_id
        )
        self.assertIsNotNone(rule_id)

        rules = get_active_training_rules(self.ws_id)
        found = any(r["id"] == rule_id and r["title"] == "Durable Test Rule" for r in rules)
        self.assertTrue(found)

    def test_12_training_rule_version_history_audit(self):
        """Invariant 12: Updating a training rule increments version and preserves audit trail."""
        rule_id = create_training_rule(
            title="Versioned Rule",
            response_or_rule="ভার্সন ১ উত্তর",
            rule_type="response",
            question_or_trigger="ভার্সন প্রশ্ন",
            category="Audit",
            workspace_id=self.ws_id
        )
        update_training_rule(
            rule_id=rule_id,
            title="Versioned Rule v2",
            rule_type="response",
            question_or_trigger="ভার্সন প্রশ্ন",
            response_or_rule="ভার্সন ২ উত্তর",
            category="Audit",
            modified_by="admin_test"
        )
        versions = get_training_rule_versions(rule_id)
        self.assertGreaterEqual(len(versions), 2)
        self.assertEqual(versions[0]["version"], 2)

    # -------------------------------------------------------------
    # 13 & 14. OWNER PRIVACY & AGENT IDENTITY
    # -------------------------------------------------------------
    def test_13_owner_privacy_no_hallucination(self):
        """Invariant 13: Inquiring owner name never hallucinates facts."""
        res = MasterOrchestrator.execute_decision(
            customer_message="Owner এর নাম কী?",
            sender_id=self.sender_id,
            customer_name="Customer",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        reply = res["reply_text"]
        self.assertTrue("টিমকে জানাচ্ছি" in reply or "সংরক্ষিত নেই" in reply)
        self.assertNotIn("রাশেদুল ইসলাম", reply)

    def test_14_agent_identity_nadim(self):
        """Invariant 14: Inquiring agent identity returns 'নাদিম'."""
        res = MasterOrchestrator.execute_decision(
            customer_message="আপনার নাম কী?",
            sender_id=self.sender_id,
            customer_name="Customer",
            workspace_id=self.ws_id,
            channel="facebook"
        )
        reply = res["reply_text"]
        self.assertIn("নাদিম", reply)

    # -------------------------------------------------------------
    # 15. INTERNAL PROMPT TEXT LEAK PROTECTION
    # -------------------------------------------------------------
    def test_15_internal_prompt_leak_sanitization(self):
        """Invariant 15: Leaked developer instructions/prompts are intercepted and sanitized."""
        leaked_draft = {
            "reply_text": "জি স্যার, কাস্টমার প্রথমে মেসেজ দিলে সরাসরি প্রথম মেসেজেই দাম বলা যাবে না। Sales Protocol অনুযায়ী কথা বলুন।",
            "matched_images": [],
            "media_sequence": [],
            "voice_url": "",
            "video_url": "",
            "response_source": "gemini_brain"
        }
        validated = ResponseValidator.validate_and_sanitize(
            draft_response=leaked_draft,
            customer_message="Hi",
            customer_name="Customer",
            workspace_id=self.ws_id
        )
        self.assertNotIn("Sales Protocol", validated["reply_text"])
        self.assertNotIn("কাস্টমার প্রথমে মেসেজ দিলে", validated["reply_text"])
        self.assertIn("INTERNAL_INSTRUCTION_LEAK_REJECTED", validated["validation_flags"])

    # -------------------------------------------------------------
    # 16. TOPIC SWITCH MULTI-TURN FLOW
    # -------------------------------------------------------------
    def test_16_topic_switch_distinct_answers(self):
        """Invariant 16: Sequential questions receive their respective correct answers."""
        # Turn 1: 100 pcs
        r1 = MasterOrchestrator.execute_decision("১০০ পিস", self.sender_id, "Customer", self.ws_id)
        self.assertIn("স্যাম্পল", r1["reply_text"])

        # Turn 2: Price per piece
        r2 = MasterOrchestrator.execute_decision("প্রতি পিস কত?", self.sender_id, "Customer", self.ws_id)
        self.assertTrue("প্যাকেজ" in r2["reply_text"] or "টাকা" in r2["reply_text"])

        # Turn 3: Delivery fee outside Dhaka
        r3 = MasterOrchestrator.execute_decision("ঢাকার বাইরে ডেলিভারি কত?", self.sender_id, "Customer", self.ws_id)
        self.assertTrue("130" in r3["reply_text"] or "১৩০" in r3["reply_text"])

    # -------------------------------------------------------------
    # 17. TOPIC SWITCH IMMUNITY FROM REPEATED QUANTITY PROMPTS
    # -------------------------------------------------------------
    def test_17_topic_switch_no_repeated_quantity_interrogation(self):
        """Invariant 17: Switching from pending state to social/product/pricing avoids repeated quantity prompt."""
        record_question_asked(self.sender_id, "QUANTITY_PROMPT", self.ws_id)

        # Social
        r1 = MasterOrchestrator.execute_decision("ভাই কেমন আছেন?", self.sender_id, "Customer", self.ws_id)
        self.assertNotIn("কত পিস", r1["reply_text"])
        self.assertTrue("ভালো আছি" in r1["reply_text"] or "আলহামদুলিল্লাহ" in r1["reply_text"])

        # Delivery
        r2 = MasterOrchestrator.execute_decision("ঢাকার বাইরে ডেলিভারি চার্জ কত?", self.sender_id, "Customer", self.ws_id)
        self.assertNotIn("কত পিস", r2["reply_text"])
        self.assertTrue("130" in r2["reply_text"] or "১৩০" in r2["reply_text"])

        # Identity
        r3 = MasterOrchestrator.execute_decision("আপনি কে?", self.sender_id, "Customer", self.ws_id)
        self.assertNotIn("কত পিস", r3["reply_text"])
        self.assertIn("নাদিম", r3["reply_text"])

    # -------------------------------------------------------------
    # 18. MULTILINGUAL & BANGLISH INTENT RESOLUTION
    # -------------------------------------------------------------
    def test_18_multilingual_and_banglish_intent_resolution(self):
        """Invariant 18: Banglish terms correctly resolve to their semantic intents."""
        cases = [
            ("Hi", CustomerIntent.GREETING),
            ("Jee", CustomerIntent.SAMPLE_CONFIRMATION),
            ("Ji", CustomerIntent.SAMPLE_CONFIRMATION),
            ("Bhalo achen?", CustomerIntent.SOCIAL_PLEASANTRY),
            ("Apni ke?", CustomerIntent.AGENT_IDENTITY_INQUIRY),
            ("Apnara per piece koto?", CustomerIntent.PER_PIECE_PRICE),
            ("Delivery charge koto?", CustomerIntent.DELIVERY_INQUIRY),
        ]
        for msg, expected_intent in cases:
            res = MasterOrchestrator.detect_intents_and_entities(msg)
            self.assertEqual(
                res["primary_intent"], expected_intent,
                f"Failed for message: '{msg}', got {res['primary_intent']} instead of {expected_intent}"
            )

    # -------------------------------------------------------------
    # 19. FOOD PLEASANTRIES & IDENTITY DISTINCTION
    # -------------------------------------------------------------
    def test_19_food_pleasantries_and_identity_distinction(self):
        """Invariant 19: Food pleasantries answered warmly; 'আপনি কেমন আছেন?' does not trigger identity."""
        # 1. 'আপনি কেমন আছেন?' -> Social pleasantry, NOT identity
        r_how_are_you = MasterOrchestrator.execute_decision("আপনি কেমন আছেন?", self.sender_id, "Customer", self.ws_id)
        self.assertIn("ভালো আছি", r_how_are_you["reply_text"])
        self.assertNotIn("আমার নাম নাদিম", r_how_are_you["reply_text"])
        self.assertNotIn("কত পিস", r_how_are_you["reply_text"])
        self.assertEqual(r_how_are_you["response_source"], "social_pleasantry_response")

        # 2. 'খাবার খেয়েছেন?' -> Food pleasantry
        r_food = MasterOrchestrator.execute_decision("খাবার খেয়েছেন?", self.sender_id, "Customer", self.ws_id)
        self.assertTrue("খাওয়া হয়েছে" in r_food["reply_text"] or "খেয়েছি" in r_food["reply_text"])
        self.assertNotIn("টিমকে জানাচ্ছি", r_food["reply_text"])
        self.assertNotIn("নিশ্চিতভাবে বুঝতে পারছি না", r_food["reply_text"])
        self.assertEqual(r_food["response_source"], "social_pleasantry_response")

        # 3. 'রাতের খাবার খেয়েছেন নাকি' -> Night meal pleasantry
        r_dinner = MasterOrchestrator.execute_decision("রাতের খাবার খেয়েছেন নাকি", self.sender_id, "Customer", self.ws_id)
        self.assertTrue("খাওয়া হয়েছে" in r_dinner["reply_text"] or "খেয়েছি" in r_dinner["reply_text"])
        self.assertNotIn("টিমকে জানাচ্ছি", r_dinner["reply_text"])
        self.assertEqual(r_dinner["response_source"], "social_pleasantry_response")

        # 4. 'ভাত খেয়েছেন?' -> Rice/meal pleasantry
        r_bhat = MasterOrchestrator.execute_decision("ভাত খেয়েছেন?", self.sender_id, "Customer", self.ws_id)
        self.assertTrue("খাওয়া হয়েছে" in r_bhat["reply_text"] or "খেয়েছি" in r_bhat["reply_text"])
        self.assertNotIn("টিমকে জানাচ্ছি", r_bhat["reply_text"])
        self.assertEqual(r_bhat["response_source"], "social_pleasantry_response")

        # 5. 'নাস্তা করেছেন?' -> Breakfast/snack pleasantry
        r_nasta = MasterOrchestrator.execute_decision("নাস্তা করেছেন?", self.sender_id, "Customer", self.ws_id)
        self.assertTrue("নাস্তা" in r_nasta["reply_text"] or "খাওয়া হয়েছে" in r_nasta["reply_text"])
        self.assertNotIn("টিমকে জানাচ্ছি", r_nasta["reply_text"])
        self.assertEqual(r_nasta["response_source"], "social_pleasantry_response")

        # 6. 'আপনি কে?' -> True identity inquiry
        r_identity = MasterOrchestrator.execute_decision("আপনি কে?", self.sender_id, "Customer", self.ws_id)
        self.assertIn("নাদিম", r_identity["reply_text"])
        self.assertEqual(r_identity["response_source"], "agent_identity_inquiry")

    # -------------------------------------------------------------
    # 20. HI / HELLO VS SALAM GREETING DISTINCTION
    # -------------------------------------------------------------
    def test_20_hi_hello_greeting_distinction(self):
        """Invariant 20: 'Hi' / 'Hello' does not return 'ওয়ালাইকুমুস সালাম'; Salam returns 'ওয়ালাইকুমুস সালাম'."""
        # 1. 'Hi'
        r_hi = MasterOrchestrator.execute_decision("Hi", self.sender_id, "Customer", self.ws_id)
        self.assertNotIn("ওয়ালাইকুমুস সালাম", r_hi["reply_text"])
        self.assertIn("স্বাগতম", r_hi["reply_text"])
        self.assertEqual(r_hi["response_source"], "standard_greeting")

        # 2. 'Hello'
        r_hello = MasterOrchestrator.execute_decision("Hello", self.sender_id, "Customer", self.ws_id)
        self.assertNotIn("ওয়ালাইকুমুস সালাম", r_hello["reply_text"])
        self.assertIn("স্বাগতম", r_hello["reply_text"])
        self.assertEqual(r_hello["response_source"], "standard_greeting")

        # 3. 'আসসালামু আলাইকুম'
        r_salam = MasterOrchestrator.execute_decision("আসসালামু আলাইকুম", self.sender_id, "Customer", self.ws_id)
        self.assertIn("ওয়ালাইকুমুস সালাম", r_salam["reply_text"])
        self.assertIn("স্বাগতম", r_salam["reply_text"])
        self.assertEqual(r_salam["response_source"], "standard_greeting")

    # -------------------------------------------------------------
    # 21. AGENT CAPABILITY & CASUAL CHIT-CHAT (NO UNNECESSARY ESCALATION)
    # -------------------------------------------------------------
    def test_21_capability_and_conversational_chit_chat(self):
        """Invariant 21: Capabilities and casual chit-chat answered naturally without team escalation."""
        # 1. 'আপনি কি কি জানেন?' -> Capability overview
        r_cap = MasterOrchestrator.execute_decision("আপনি কি কি জানেন?", self.sender_id, "Customer", self.ws_id)
        self.assertIn("নাদিম", r_cap["reply_text"])
        self.assertIn("আইডি কার্ড", r_cap["reply_text"])
        self.assertNotIn("টিমকে জানাচ্ছি", r_cap["reply_text"])
        self.assertEqual(r_cap["response_source"], "agent_capability_inquiry")

        # 2. 'আপনার কাজ কি?' -> Capability overview
        r_work = MasterOrchestrator.execute_decision("আপনার কাজ কি?", self.sender_id, "Customer", self.ws_id)
        self.assertIn("নাদিম", r_work["reply_text"])
        self.assertNotIn("টিমকে জানাচ্ছি", r_work["reply_text"])
        self.assertEqual(r_work["response_source"], "agent_capability_inquiry")

        # 3. 'গোসল করতে যাবে?' -> Chit-chat
        r_bath = MasterOrchestrator.execute_decision("গোসল করতে যাবে?", self.sender_id, "Customer", self.ws_id)
        self.assertNotIn("টিমকে জানাচ্ছি", r_bath["reply_text"])
        self.assertNotIn("নিশ্চিতভাবে বুঝতে পারছি না", r_bath["reply_text"])

        # 4. 'গোসল কাকে বলে?' -> Chit-chat / GK
        r_def = MasterOrchestrator.execute_decision("গোসল কাকে বলে?", self.sender_id, "Customer", self.ws_id)
        self.assertNotIn("টিমকে জানাচ্ছি", r_def["reply_text"])
        self.assertNotIn("নিশ্চিতভাবে বুঝতে পারছি না", r_def["reply_text"])

        # 5. 'চা খাবেন?' -> Chit-chat
        r_tea = MasterOrchestrator.execute_decision("চা খাবেন?", self.sender_id, "Customer", self.ws_id)
        self.assertNotIn("টিমকে জানাচ্ছি", r_tea["reply_text"])
        self.assertTrue("ধন্যবাদ" in r_tea["reply_text"] or "চা" in r_tea["reply_text"])

    # -------------------------------------------------------------
    # 22. RASHED INQUIRY & HUMAN TALK DEMAND CONTINUITY
    # -------------------------------------------------------------
    def test_22_rashed_and_human_request_continuity(self):
        """Invariant 22: 'রাশেদ কোথায়?' states Rashed is owner; 'তাকে একটু দরকার' acknowledges talk demand."""
        # 1. 'রাশেদ কোথায়?'
        r_rashed = MasterOrchestrator.execute_decision("রাশেদ কোথায়?", self.sender_id, "Customer", self.ws_id)
        self.assertIn("রাশেদ", r_rashed["reply_text"])
        self.assertIn("ওনার", r_rashed["reply_text"])
        self.assertEqual(r_rashed["response_source"], "owner_mention_rule_13")

        # 2. 'তাকে একটু দরকার'
        r_need_him = MasterOrchestrator.execute_decision("তাকে একটু দরকার", self.sender_id, "Customer", self.ws_id)
        self.assertTrue("যোগাযোগ" in r_need_him["reply_text"] or "জানিয়ে" in r_need_him["reply_text"])
        self.assertEqual(r_need_him["response_source"], "human_request_acknowledgement")

        # 3. 'উনাকে দরকার'
        r_need_owner = MasterOrchestrator.execute_decision("উনাকে দরকার", self.sender_id, "Customer", self.ws_id)
        self.assertTrue("যোগাযোগ" in r_need_owner["reply_text"] or "জানিয়ে" in r_need_owner["reply_text"])
        self.assertEqual(r_need_owner["response_source"], "human_request_acknowledgement")


if __name__ == "__main__":
    unittest.main()
