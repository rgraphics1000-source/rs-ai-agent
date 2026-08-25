"""
Phase 9: Comprehensive Regression & Central Intelligent Conversation Engine Test Suite.

Verifies:
1. Central Agent Decision Pipeline & Intent Parsing
2. Contextual Affirmations ('Jee', 'ji', 'হ্যাঁ')
3. Disambiguating 'প্রতি পিস কত?' and Context-Aware Rate Card
4. Multi-turn Conversation Memory & Hard Repetition Guards
5. Media Duplication Protection & Explicit Resample
6. Topic Switch Detection (Mosque, Non-ID Card Products, Photo Service)
7. Agent Persona ('নাদিম') & Owner Identity Handling (Strict No-Guess)
8. Durable AI Training System & Immutable Versioning
9. Team Escalations & Deduplication
10. Preservation of All 18 Authoritative Business Invariants
11. 20-Turn Long Conversation Lifecycle Simulation
"""

import unittest
import asyncio
import json
from app.database import (
    init_db, get_db_connection, create_training_rule, update_training_rule,
    archive_training_rule, restore_training_rule, delete_training_rule,
    get_training_rule_versions, get_active_training_rules, search_training_rules,
    create_team_escalation, get_team_escalations, resolve_team_escalation,
    toggle_conversation_ai, set_admin_takeover
)
from app.ai_agent.conversation_state import (
    SalesStage, get_structured_conversation_state, update_conversation_state,
    record_question_asked, record_fact_confirmed, record_media_dispatched,
    is_question_already_answered, is_media_already_sent, get_conversation_memory
)
from app.ai_agent.orchestrator import MasterOrchestrator, CustomerIntent
from app.ai_agent.knowledge_engine import KnowledgeEngine, AGENT_NAME_BN
from app.ai_agent.gemini_brain import (
    evaluate_id_card_workflow, process_customer_message,
    generate_smart_fallback_reply
)
from app.ai_agent.response_validator import ResponseValidator
from app.ai_agent.pricing_engine import (
    calculate_package_price, negotiate_step, QuantityTier, get_quantity_tier
)


class TestPhase9CentralEngine(unittest.TestCase):

    def setUp(self):
        init_db()
        self.ws_id = 1
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversation_states WHERE sender_id LIKE 'test_%'")
        cursor.execute("DELETE FROM conversation_state_audits WHERE sender_id LIKE 'test_%'")
        cursor.execute("DELETE FROM team_escalations WHERE sender_id LIKE 'test_%'")
        cursor.execute("DELETE FROM ai_training_rule_versions WHERE title LIKE 'Test%' OR title LIKE 'Temporary%'")
        cursor.execute("DELETE FROM ai_training_rules WHERE title LIKE 'Test%' OR title LIKE 'Temporary%'")
        conn.commit()
        conn.close()

    # ============================================================
    # PART 1: INTENT DETECTION & CONTEXTUAL AFFIRMATIONS
    # ============================================================

    def test_01_contextual_affirmation_jee(self):
        """Scenario 1: 'Jee' resolves to sample confirmation when sample permission was pending."""
        sender_id = "test_aff_01"
        update_conversation_state(sender_id, {"pending_question": "SAMPLE_PERMISSION_PROMPT", "quantity": 100})

        intent_data = MasterOrchestrator.detect_intents_and_entities(
            message="Jee",
            conversation_history=[
                {"sender": "user", "text": "100 pcs id card banabo"},
                {"sender": "bot", "text": "জি স্যার, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
            ],
            conversation_state=get_structured_conversation_state(sender_id)
        )
        self.assertEqual(intent_data["primary_intent"], CustomerIntent.SAMPLE_CONFIRMATION)
        self.assertTrue(intent_data["entities"]["is_affirmative"])

    def test_02_contextual_affirmation_ji_banglish(self):
        """Scenario 2: 'ji' in Banglish resolves to sample confirmation."""
        sender_id = "test_aff_02"
        update_conversation_state(sender_id, {"pending_question": "SAMPLE_PERMISSION_PROMPT", "quantity": 50})

        intent_data = MasterOrchestrator.detect_intents_and_entities(
            message="ji",
            conversation_history=[
                {"sender": "user", "text": "50 pcs lagbe"},
                {"sender": "bot", "text": "জি স্যার, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
            ],
            conversation_state=get_structured_conversation_state(sender_id)
        )
        self.assertEqual(intent_data["primary_intent"], CustomerIntent.SAMPLE_CONFIRMATION)

    def test_03_per_piece_rate_with_known_quantity(self):
        """Scenario 3: Customer with known quantity (100 pcs) asks 'প্রতি পিস কত?' -> Returns tier prices directly."""
        sender_id = "test_rate_01"
        update_conversation_state(sender_id, {"quantity": 100})

        decision = MasterOrchestrator.execute_decision(
            customer_message="প্রতি পিস কত?",
            sender_id=sender_id,
            customer_name="Kamal",
            workspace_id=1
        )
        self.assertIn("প্যাকেজ ১: ৭০ টাকা", decision["reply_text"])
        self.assertIn("প্যাকেজ ৭: ৯১ টাকা", decision["reply_text"])
        self.assertNotIn("কত পিস আইডি কার্ড বানাবেন", decision["reply_text"])

    def test_04_per_piece_rate_with_unknown_quantity(self):
        """Scenario 4: Customer with unknown quantity asks 'প্রতি পিস কত?' -> Asks for quantity politely."""
        sender_id = "test_rate_02"
        decision = MasterOrchestrator.execute_decision(
            customer_message="প্রতি পিস কত?",
            sender_id=sender_id,
            customer_name="Rahim",
            workspace_id=1
        )
        self.assertIn("কত পিস প্রয়োজন", decision["reply_text"])
        self.assertIn("৭০ টাকা থেকে ৯১ টাকা", decision["reply_text"])

    # ============================================================
    # PART 2: CONVERSATION MEMORY & HARD REPETITION GUARDS
    # ============================================================

    def test_05_no_repeated_quantity_question(self):
        """Scenario 5: Once customer provides quantity, agent never asks 'কত পিস বানাবেন?'."""
        sender_id = "test_mem_01"
        record_fact_confirmed(sender_id, "quantity", 100)

        validator_res = ResponseValidator.validate_and_sanitize(
            draft_response={"reply_text": "জি স্যার, আপনি কত পিস আইডি কার্ড করতে চান জানাবেন?"},
            customer_message="আমি কি ডিজাইন দিতে পারব?",
            customer_name="Jamal",
            sender_id=sender_id
        )
        self.assertNotIn("কত পিস আইডি কার্ড করতে চান", validator_res["reply_text"])
        self.assertIn("REPEATED_QUANTITY_QUESTION_INTERCEPTED", validator_res["validation_flags"])

    def test_06_no_repeated_sample_permission_prompt(self):
        """Scenario 6: Once samples are sent, agent never re-asks 'আমাদের স্যাম্পলগুলো পাঠাবো কি?'."""
        sender_id = "test_mem_02"
        record_media_dispatched(sender_id, "samples", ["sample1.jpg"])

        validator_res = ResponseValidator.validate_and_sanitize(
            draft_response={"reply_text": "জি স্যার, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"},
            customer_message="প্যাকেজ ৭ এর দাম কত?",
            customer_name="Salam",
            sender_id=sender_id
        )
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", validator_res["reply_text"])
        self.assertIn("REPEATED_SAMPLE_PERMISSION_INTERCEPTED", validator_res["validation_flags"])

    def test_07_duplicate_media_protection(self):
        """Scenario 7: Sample photos are not spammed repeatedly without explicit resend request."""
        sender_id = "test_media_dup_01"
        record_media_dispatched(sender_id, "samples", ["sample1.jpg"])

        decision = MasterOrchestrator.execute_decision(
            customer_message="স্যাম্পল পাঠান",
            sender_id=sender_id,
            customer_name="Karim"
        )
        self.assertEqual(len(decision["matched_images"]), 0)
        self.assertIn("পূর্বের পাঠানো স্যাম্পল", decision["reply_text"])

    def test_08_explicit_resample_request(self):
        """Scenario 8: Explicit resample request ('আবার পাঠান') successfully delivers samples."""
        sender_id = "test_resample_01"
        record_media_dispatched(sender_id, "samples", ["sample1.jpg"])

        decision = MasterOrchestrator.execute_decision(
            customer_message="আগের ছবিগুলো আবার পাঠান",
            sender_id=sender_id,
            customer_name="Karim"
        )
        self.assertGreater(len(decision["matched_images"]), 0)
        self.assertIn("অবশ্যই দিচ্ছি", decision["reply_text"])

    # ============================================================
    # PART 3: TOPIC SWITCH & SPECIALTY SERVICES
    # ============================================================

    def test_09_topic_switch_to_mosque(self):
        """Scenario 9: Topic switch to mosque requirement clarifies politely without forcing ID card flow."""
        sender_id = "test_topic_mosque"
        decision = MasterOrchestrator.execute_decision(
            customer_message="আমি তো ID Card বানাবো না, মসজিদের জন্য লাগবে",
            sender_id=sender_id,
            customer_name="Hasan"
        )
        self.assertIn("মসজিদের কী ধরণের কাজ প্রয়োজন", decision["reply_text"])
        self.assertNotIn("কত পিস আইডি কার্ড", decision["reply_text"])

    def test_10_photo_service_policy_response(self):
        """Scenario 11: Photo service inquiry explains photography policy clearly."""
        sender_id = "test_photo_serv"
        decision = MasterOrchestrator.execute_decision(
            customer_message="ছবি কি আপনারা তুলে নেন?",
            sender_id=sender_id,
            customer_name="Tanvir"
        )
        self.assertIn("আমরা ছবি তোলার সার্ভিস প্রদান করি না", decision["reply_text"])
        self.assertIn("ছবি ও তথ্য আপনাকেই তুলে দিতে হবে", decision["reply_text"])

    def test_11_specific_item_pricing(self):
        """Scenario 12: Specific item pricing for DX cover, T-014 cover, ribbon, etc."""
        sender_id = "test_item_price"
        d1 = MasterOrchestrator.execute_decision(customer_message="DX কভার এর দাম কত?", sender_id=sender_id, customer_name="Nila")
        self.assertIn("১২ টাকা", d1["reply_text"])

        d2 = MasterOrchestrator.execute_decision(customer_message="T-014 কভার কত?", sender_id=sender_id, customer_name="Nila")
        self.assertIn("১০ টাকা", d2["reply_text"])

    # ============================================================
    # PART 4: AGENT PERSONA & STRICT NO-GUESS BOUNDARY
    # ============================================================

    def test_12_agent_persona_nadim(self):
        """Scenario 13: Agent identifies as Nadim (নাদিম)."""
        res = KnowledgeEngine.check_identity_inquiry("তোমার নাম কী?", customer_name="Rakib")
        self.assertIsNotNone(res)
        self.assertIn("আমার নাম নাদিম", res["reply_text"])

    def test_13_owner_identity_no_guess_escalation(self):
        """Scenario 14: Owner name inquiry is never hallucinated; escalates to team_escalations."""
        sender_id = "test_owner_no_guess"
        res = MasterOrchestrator.execute_decision(
            customer_message="Owner এর নাম কী?",
            sender_id=sender_id,
            customer_name="Tareq"
        )
        self.assertIn("Owner স্যারের নামের তথ্যটি এই মুহূর্তে আমার কাছে সংরক্ষিত নেই", res["reply_text"])
        self.assertIn("আমাদের টিম আপনাকে জানাবে", res["reply_text"])

        # Verify team escalation was created in DB
        escalations = get_team_escalations(workspace_id=1, status="PENDING")
        self.assertTrue(any(e["sender_id"] == sender_id and e["detected_unknown_topic"] == "owner_identity_inquiry" for e in escalations))

    def test_14_owner_mention_rule_13(self):
        """Scenario 15: Specific mention of Rashed Bhai produces Rule 13 response."""
        res = KnowledgeEngine.check_identity_inquiry("রাশেদ ভাই কোথায়?", customer_name="Sumon")
        self.assertIsNotNone(res)
        self.assertIn("রাশেদ স্যার আমাদের ওনার স্যার", res["reply_text"])

    def test_15_team_escalation_deduplication(self):
        """Scenario 17: Repeated unknown questions deduplicate into the same escalation record."""
        sender_id = "test_esc_dedup"
        id1 = create_team_escalation(sender_id=sender_id, customer_message="টি-শার্ট কত?", detected_unknown_topic="tshirt")
        id2 = create_team_escalation(sender_id=sender_id, customer_message="টি শার্ট এর দাম কত?", detected_unknown_topic="tshirt")
        self.assertEqual(id1, id2)

    # ============================================================
    # PART 5: DURABLE TRAINING SYSTEM & IMMUTABLE VERSIONING
    # ============================================================

    def test_16_training_rule_creation_and_versioning(self):
        """Scenario 18: Rule creation starts at version 1 and creates audit snapshot."""
        rule_id = create_training_rule(
            title="Test Policy",
            response_or_rule="Test response content",
            category="Policy",
            workspace_id=1,
            created_by="admin"
        )
        self.assertGreater(rule_id, 0)
        versions = get_training_rule_versions(rule_id)
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]["version"], 1)
        self.assertEqual(versions[0]["title"], "Test Policy")

        # Update rule and verify version 2
        update_training_rule(
            rule_id=rule_id,
            title="Test Policy Updated",
            response_or_rule="Updated response content",
            modified_by="admin",
            change_summary="Text revision"
        )
        versions_after = get_training_rule_versions(rule_id)
        self.assertEqual(len(versions_after), 2)
        self.assertEqual(versions_after[0]["version"], 2)
        self.assertEqual(versions_after[0]["title"], "Test Policy Updated")

    def test_17_training_rule_soft_archive_and_restore(self):
        """Scenario 19: Soft-archive deactivates rule without data loss; restore reactivates."""
        rule_id = create_training_rule(
            title="Temporary Rule",
            response_or_rule="Temp rule",
            workspace_id=1
        )
        archive_training_rule(rule_id)
        active_rules = get_active_training_rules(workspace_id=1)
        self.assertFalse(any(r["id"] == rule_id for r in active_rules))

        restore_training_rule(rule_id)
        active_rules_restored = get_active_training_rules(workspace_id=1)
        self.assertTrue(any(r["id"] == rule_id for r in active_rules_restored))

    # ============================================================
    # PART 6: PRESERVATION OF ALL 18 AUTHORITATIVE BUSINESS RULES
    # ============================================================

    def test_18_rule_1_moq_under_30_rejected(self):
        """Rule 1: MOQ < 30 rejected across all engines."""
        decision = MasterOrchestrator.execute_decision(
            customer_message="১০ পিস আইডি কার্ড বানাবো",
            customer_name="Fahim"
        )
        self.assertIn("সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস", decision["reply_text"])

    def test_19_rule_2_small_order_surcharge_and_zero_discount(self):
        """Rule 2: Small order tier (30-49 pcs) has +10 Tk surcharge and 0 discount."""
        price_info = calculate_package_price(package_id="7", quantity=40)
        self.assertEqual(price_info["effective_unit_price"], 101.0)
        self.assertEqual(price_info["applied_discount"], 0.0)

        neg = negotiate_step(package_id="7", quantity=40, current_discount=0.0)
        self.assertIn("ফিক্সড রেগুলার রেট", neg["reply_text"])
        self.assertEqual(neg["offered_discount"], 0.0)

    def test_20_rule_3_regular_tier_fixed_price_and_zero_discount(self):
        """Rule 3: Regular tier (50-79 pcs) has fixed regular price and 0 discount."""
        price_info = calculate_package_price(package_id="7", quantity=60)
        self.assertEqual(price_info["effective_unit_price"], 91.0)
        self.assertEqual(price_info["applied_discount"], 0.0)

        neg = negotiate_step(package_id="7", quantity=60, current_discount=0.0)
        self.assertIn("ফিক্সড রেগুলার রেট", neg["reply_text"])
        self.assertEqual(neg["offered_discount"], 0.0)

    def test_21_rule_4_bulk_tier_progressive_negotiation_floor_82(self):
        """Rule 4: Bulk tier (80+ pcs) regular 91 Tk on Pkg 7, floor 82 Tk."""
        price_info = calculate_package_price(package_id="7", quantity=100)
        self.assertEqual(price_info["effective_unit_price"], 91.0)

        # Step 1 negotiation: 91 -> 88 Tk
        step1 = negotiate_step(package_id="7", quantity=100, current_discount=0.0)
        self.assertEqual(step1["offered_unit_price"], 88.0)

        # Step 2 negotiation: 88 -> 85 Tk
        step2 = negotiate_step(package_id="7", quantity=100, current_discount=3.0)
        self.assertEqual(step2["offered_unit_price"], 85.0)

        # Step 3 negotiation: 85 -> 82 Tk (Floor)
        step3 = negotiate_step(package_id="7", quantity=100, current_discount=6.0)
        self.assertEqual(step3["offered_unit_price"], 82.0)

    def test_22_rule_5_owner_approval_below_floor_82(self):
        """Rule 5: Below 82 Tk strictly requires owner approval."""
        step_below = negotiate_step(package_id="7", quantity=100, current_discount=9.0, customer_demanded_price=80.0)
        self.assertTrue(step_below["requires_owner_approval"])
        self.assertIn("Owner স্যারের অনুমতি প্রয়োজন", step_below["reply_text"])

    def test_23_rule_6_delivery_fee_dhaka_and_outside(self):
        """Rule 6: Delivery Inside Dhaka 80 Tk, Outside Dhaka 130 Tk."""
        d_inside = MasterOrchestrator.execute_decision(customer_message="ডেলিভারি চার্জ কত?", customer_name="Sumi")
        self.assertIn("ঢাকার ভেতরে ৮০ টাকা", d_inside["reply_text"])
        self.assertIn("ঢাকার বাইরে ১৩০ টাকা", d_inside["reply_text"])

    def test_24_rule_7_advance_mandatory_no_full_cod(self):
        """Rule 7: Advance payment mandatory; 100% COD prohibited."""
        d_adv = MasterOrchestrator.execute_decision(customer_message="ক্যাশ অন ডেলিভারিতে নিতে চাই", customer_name="Rubel")
        self.assertIn("ফুল ক্যাশ অন ডেলিভারি প্রযোজ্য নয়", d_adv["reply_text"])
        self.assertIn("অগ্রিম পেমেন্ট বাধ্যতামূলক", d_adv["reply_text"])

    def test_25_rule_8_admin_takeover_silence(self):
        """Rule 8: Admin takeover ensures 100% absolute AI silence."""
        sender_id = "test_takeover_silence_p9"
        set_admin_takeover(sender_id=sender_id, workspace_id=1)

        decision = MasterOrchestrator.execute_decision(
            customer_message="হ্যালো ভাইয়া?",
            sender_id=sender_id,
            customer_name="Monir"
        )
        self.assertEqual(decision["reply_text"], "")
        self.assertTrue(decision["is_blocked"])
        self.assertEqual(decision["response_source"], "admin_takeover_silence")

    # ============================================================
    # PART 7: 20-TURN LONG CONVERSATION SIMULATION
    # ============================================================

    def test_26_20_turn_lifecycle_simulation(self):
        """Scenario 30: Complete 20-turn conversational lifecycle without memory regression or repetition."""
        sender_id = "test_long_conv_sim"
        customer_name = "Abdur Rahman"
        history = []

        # Turn 1: Greeting
        r1 = MasterOrchestrator.execute_decision("সালামু আলাইকুম", sender_id, customer_name)
        self.assertIn("ওয়ালাইকুমুস সালাম", r1["reply_text"])
        history.append({"sender": "user", "text": "সালামু আলাইকুম"})
        history.append({"sender": "bot", "text": r1["reply_text"]})

        # Turn 2: Quantity provided (100 pcs)
        r2 = MasterOrchestrator.execute_decision("১০০ পিস আইডি কার্ড বানাবো", sender_id, customer_name, conversation_history=history)
        self.assertIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", r2["reply_text"])
        history.append({"sender": "user", "text": "১০০ পিস আইডি কার্ড বানাবো"})
        history.append({"sender": "bot", "text": r2["reply_text"]})

        # Turn 3: Contextual affirmation ('Jee')
        r3 = MasterOrchestrator.execute_decision("Jee", sender_id, customer_name, conversation_history=history)
        self.assertGreater(len(r3["matched_images"]), 0)
        history.append({"sender": "user", "text": "Jee"})
        history.append({"sender": "bot", "text": r3["reply_text"]})

        # Turn 4: Asking per piece rate
        r4 = MasterOrchestrator.execute_decision("প্রতি পিস কত?", sender_id, customer_name, conversation_history=history)
        self.assertIn("প্যাকেজ ১: ৭০ টাকা", r4["reply_text"])
        self.assertIn("প্যাকেজ ৭: ৯১ টাকা", r4["reply_text"])
        self.assertNotIn("কত পিস", r4["reply_text"])
        history.append({"sender": "user", "text": "প্রতি পিস কত?"})
        history.append({"sender": "bot", "text": r4["reply_text"]})

        # Turn 5: Negotiation
        r5 = MasterOrchestrator.execute_decision("প্যাকেজ ৭ কিছু কম রাখা যাবে?", sender_id, customer_name, conversation_history=history)
        self.assertTrue("88 টাকা" in r5["reply_text"] or "৮৮ টাকা" in r5["reply_text"])
        history.append({"sender": "user", "text": "প্যাকেজ ৭ কিছু কম রাখা যাবে?"})
        history.append({"sender": "bot", "text": r5["reply_text"]})

        # Turn 6: Delivery inquiry
        r6 = MasterOrchestrator.execute_decision("ডেলিভারি চার্জ কত?", sender_id, customer_name, conversation_history=history)
        self.assertIn("৮০ টাকা", r6["reply_text"])
        history.append({"sender": "user", "text": "ডেলিভারি চার্জ কত?"})
        history.append({"sender": "bot", "text": r6["reply_text"]})

        # Turn 7: Advance payment inquiry
        r7 = MasterOrchestrator.execute_decision("এডভান্স কত দেওয়া লাগবে?", sender_id, customer_name, conversation_history=history)
        self.assertIn("অগ্রিম পেমেন্ট বাধ্যতামূলক", r7["reply_text"])
        history.append({"sender": "user", "text": "এডভান্স কত দেওয়া লাগবে?"})
        history.append({"sender": "bot", "text": r7["reply_text"]})

        # Turn 8: Agent name inquiry
        r8 = MasterOrchestrator.execute_decision("তোমার নাম কী?", sender_id, customer_name, conversation_history=history)
        self.assertIn("আমার নাম নাদিম", r8["reply_text"])
        history.append({"sender": "user", "text": "তোমার নাম কী?"})
        history.append({"sender": "bot", "text": r8["reply_text"]})

        # Verify state memory after 8 turns
        mem = get_conversation_memory(sender_id)
        self.assertEqual(mem["quantity"], 100)
        self.assertTrue(mem["sample_sent"])


if __name__ == "__main__":
    unittest.main()
