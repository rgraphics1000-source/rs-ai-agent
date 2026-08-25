"""
Phase 6.1 Automated Test Suite: Business Rule Governance & Conflict Detection

Tests:
1. Single authoritative rule retrieval
2. Lower-level conflicting rule resolution (Level 1 overrides Level 3/4/5)
3. Level-1 conflict triggers Owner Review
4. Duplicate active rule resolution (sorted by authority and version)
5. Version conflict handling
6. Stale rule handling (effective_to window)
7. Missing authoritative rule detection
8. FAQ conflict resolution
9. Training rule conflict resolution
10. Prompt conflict resolution
11. Gemini receives resolved rule only
12. Owner review triggered for critical conflict
13. Non-critical conflict uses authoritative value without escalation
14. Existing Pricing Engine remains unchanged
15. Existing State Machine remains unchanged
"""

import unittest
from datetime import datetime, timedelta, timezone
from app.database import init_db, ensure_default_saved_media
from app.ai_agent.rule_registry import (
    RuleRegistry, BusinessRule, AuthorityLevel, ConflictType,
    ConflictAction, RuleGovernanceAuditLog
)
from app.ai_agent.pricing_engine import calculate_package_price, PACKAGE_CATALOG
from app.ai_agent.conversation_state import (
    get_structured_conversation_state, SalesStage
)
from app.ai_agent.orchestrator import MasterOrchestrator


class TestRuleGovernance(unittest.TestCase):

    def setUp(self):
        init_db()
        ensure_default_saved_media()
        RuleRegistry.initialize()
        RuleGovernanceAuditLog.clear()
        self.ws_id = 1

    def test_01_single_authoritative_rule_retrieval(self):
        """TEST 1: Retrieval of single authoritative Level-1 business rule."""
        moq_rule = RuleRegistry.get_authoritative_rule("moq")
        self.assertIsNotNone(moq_rule)
        self.assertEqual(moq_rule.value, 30)
        self.assertEqual(moq_rule.authority_level, AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE)
        print("[PASSED] Test 01: Single authoritative rule retrieval.")

    def test_02_lower_level_conflicting_rule_uses_level_1(self):
        """TEST 2: Lower-level rule conflict strictly resolves to Level 1 authoritative value."""
        # Candidate rule from Level 3 training rule with wrong discount of 15
        conflict_res = RuleRegistry.inspect_and_resolve_conflict(
            rule_key="package_7_max_discount",
            candidate_value=15,
            candidate_source="ai_training_rules",
            candidate_authority_level=AuthorityLevel.LEVEL_3_TRAINING_RULES
        )
        self.assertTrue(conflict_res["has_conflict"])
        self.assertEqual(conflict_res["conflict_type"], ConflictType.VALUE_CONFLICT)
        self.assertEqual(conflict_res["resolved_value"], 9)  # Level 1 pricing_engine value
        self.assertEqual(conflict_res["action"], ConflictAction.USE_AUTHORITATIVE)
        self.assertFalse(conflict_res["requires_owner_review"])
        print("[PASSED] Test 02: Lower-level conflicting rule overridden by Level 1.")

    def test_03_level_1_conflict_triggers_owner_review(self):
        """TEST 3: Conflict between two Level-1 sources requires Owner Review."""
        conflict_res = RuleRegistry.inspect_and_resolve_conflict(
            rule_key="package_7_regular_price",
            candidate_value=89,  # Disagrees with Level 1 91 Tk
            candidate_source="discrepant_internal_engine",
            candidate_authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE
        )
        self.assertTrue(conflict_res["has_conflict"])
        self.assertEqual(conflict_res["conflict_type"], ConflictType.SOURCE_CONFLICT)
        self.assertEqual(conflict_res["action"], ConflictAction.REQUIRE_OWNER_REVIEW)
        self.assertTrue(conflict_res["requires_owner_review"])
        print("[PASSED] Test 03: Level-1 conflict triggers Owner Review.")

    def test_04_duplicate_active_rule_precedence(self):
        """TEST 4: Highest authority level wins in duplicate active rule scenarios."""
        # Register a Level 4 FAQ rule for moq with value 50
        faq_moq = BusinessRule(
            rule_id="FAQ_MOQ_OVERRIDE",
            rule_key="moq",
            category="order_policy",
            authority_level=AuthorityLevel.LEVEL_4_FAQ,
            source="faq",
            value=50
        )
        RuleRegistry.register_rule(faq_moq)

        # Authoritative rule must still be Level 1 with value 30
        resolved_moq = RuleRegistry.resolve_rule_value("moq")
        self.assertEqual(resolved_moq, 30)
        print("[PASSED] Test 04: Duplicate active rule precedence verified.")

    def test_05_version_conflict_precedence(self):
        """TEST 5: Higher version of the same authority level takes precedence."""
        v2_rule = BusinessRule(
            rule_id="RULE_PKG_7_PRICE_V2",
            rule_key="package_7_regular_price",
            category="pricing",
            authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
            source="pricing_engine",
            value=95,
            version=2
        )
        RuleRegistry.register_rule(v2_rule)

        resolved_price = RuleRegistry.resolve_rule_value("package_7_regular_price")
        self.assertEqual(resolved_price, 95)
        print("[PASSED] Test 05: Higher active version precedence verified.")

    def test_06_stale_rule_handling(self):
        """TEST 6: Rules with past effective_to date are inactive."""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        past_rule = BusinessRule(
            rule_id="EXPIRED_RULE",
            rule_key="promo_rate",
            category="pricing",
            authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE,
            source="pricing_engine",
            value=50,
            effective_to=yesterday
        )
        RuleRegistry.register_rule(past_rule)

        self.assertFalse(past_rule.is_currently_effective())
        self.assertIsNone(RuleRegistry.get_authoritative_rule("promo_rate"))
        print("[PASSED] Test 06: Stale rule correctly recognized as inactive.")

    def test_07_missing_authoritative_rule_detection(self):
        """TEST 7: Unregistered rule key triggers missing authoritative rule conflict."""
        res = RuleRegistry.inspect_and_resolve_conflict(
            rule_key="completely_unregistered_rule_xyz",
            candidate_value="some_value",
            candidate_source="unknown_prompt",
            candidate_authority_level=AuthorityLevel.LEVEL_5_STATIC_PROMPT
        )
        self.assertTrue(res["has_conflict"])
        self.assertEqual(res["conflict_type"], ConflictType.MISSING_AUTHORITATIVE_RULE)
        self.assertEqual(res["action"], ConflictAction.SAFE_FALLBACK)
        self.assertTrue(res["requires_owner_review"])
        print("[PASSED] Test 07: Missing authoritative rule handled with safe fallback.")

    def test_08_faq_conflict_resolution(self):
        """TEST 8: Conflicting FAQ rule is overridden and logged."""
        res = RuleRegistry.inspect_and_resolve_conflict(
            rule_key="delivery_inside_dhaka_base",
            candidate_value=60,  # FAQ claims 60 Tk instead of 80 Tk
            candidate_source="faq_delivery_question",
            candidate_authority_level=AuthorityLevel.LEVEL_4_FAQ
        )
        self.assertTrue(res["has_conflict"])
        self.assertEqual(res["resolved_value"], 80)
        self.assertEqual(res["action"], ConflictAction.USE_AUTHORITATIVE)
        print("[PASSED] Test 08: FAQ conflict resolves to Level 1 delivery engine.")

    def test_09_training_rule_conflict_resolution(self):
        """TEST 9: Conflicting training rule is overridden by pricing engine."""
        res = RuleRegistry.inspect_and_resolve_conflict(
            rule_key="package_7_floor_price",
            candidate_value=75,  # Training rule claims floor is 75 Tk instead of 82 Tk
            candidate_source="ai_training_rules",
            candidate_authority_level=AuthorityLevel.LEVEL_3_TRAINING_RULES
        )
        self.assertTrue(res["has_conflict"])
        self.assertEqual(res["resolved_value"], 82)
        self.assertEqual(res["action"], ConflictAction.USE_AUTHORITATIVE)
        print("[PASSED] Test 09: Training rule conflict resolves to Level 1 floor price.")

    def test_10_prompt_conflict_resolution(self):
        """TEST 10: Static prompt instruction cannot override COD policy."""
        res = RuleRegistry.inspect_and_resolve_conflict(
            rule_key="full_cod_allowed",
            candidate_value=True,  # Prompt hallucinating COD allowed
            candidate_source="static_prompt_instruction",
            candidate_authority_level=AuthorityLevel.LEVEL_5_STATIC_PROMPT
        )
        self.assertTrue(res["has_conflict"])
        self.assertEqual(res["resolved_value"], False)
        self.assertEqual(res["action"], ConflictAction.USE_AUTHORITATIVE)
        print("[PASSED] Test 10: Prompt conflict resolves to Level 1 COD prohibition.")

    def test_11_gemini_receives_resolved_rule_only(self):
        """TEST 11: MasterOrchestrator provides only verified authoritative values."""
        decision = MasterOrchestrator.execute_decision(
            customer_message="Package 7 এর রেট কত?",
            sender_id="gov_test_user_011",
            workspace_id=self.ws_id
        )
        self.assertIn("91", decision["reply_text"])
        self.assertNotIn("89", decision["reply_text"])
        self.assertNotIn("80", decision["reply_text"])
        print("[PASSED] Test 11: Gemini receives resolved rule only.")

    def test_12_owner_review_triggered_for_critical_conflict(self):
        """TEST 12: Audit log records critical conflict with owner review flag."""
        RuleRegistry.inspect_and_resolve_conflict(
            rule_key="package_7_regular_price",
            candidate_value=999,
            candidate_source="corrupt_engine_module",
            candidate_authority_level=AuthorityLevel.LEVEL_1_DETERMINISTIC_ENGINE
        )
        records = RuleGovernanceAuditLog.get_all_records()
        self.assertTrue(len(records) > 0)
        latest = records[-1]
        self.assertTrue(latest["requires_owner_review"])
        self.assertEqual(latest["conflict_type"], ConflictType.SOURCE_CONFLICT.value)
        print("[PASSED] Test 12: Owner review triggered for critical conflict and audited.")

    def test_13_non_critical_conflict_uses_authoritative_value(self):
        """TEST 13: Non-critical conflict audited without requiring owner review."""
        RuleRegistry.inspect_and_resolve_conflict(
            rule_key="package_1_6_max_discount",
            candidate_value=12,  # FAQ claims 12 Tk discount
            candidate_source="faq",
            candidate_authority_level=AuthorityLevel.LEVEL_4_FAQ
        )
        records = RuleGovernanceAuditLog.get_all_records()
        latest = records[-1]
        self.assertFalse(latest["requires_owner_review"])
        self.assertEqual(latest["authoritative_value"], 5)
        print("[PASSED] Test 13: Non-critical conflict resolved and audited.")

    def test_14_existing_pricing_engine_remains_unchanged(self):
        """TEST 14: Verification that Pricing Engine authoritative calculations are identical."""
        res_100_pkg7 = calculate_package_price("7", 100)
        self.assertEqual(res_100_pkg7["upfront_unit_price"], 91.0)
        self.assertEqual(res_100_pkg7["total_amount"], 9100.0)

        res_40_pkg7 = calculate_package_price("7", 40)
        self.assertEqual(res_40_pkg7["upfront_unit_price"], 101.0)
        self.assertEqual(res_40_pkg7["total_amount"], 4040.0)
        print("[PASSED] Test 14: Existing Pricing Engine calculations unchanged.")

    def test_15_existing_state_machine_remains_unchanged(self):
        """TEST 15: Verification that Persistent State Machine remains identical."""
        state = get_structured_conversation_state("gov_test_user_015", workspace_id=self.ws_id)
        self.assertEqual(state["service_type"], "id_card")
        self.assertEqual(state["current_sales_stage"], SalesStage.NEW.value)
        print("[PASSED] Test 15: Existing State Machine remains unchanged.")


if __name__ == "__main__":
    unittest.main()
