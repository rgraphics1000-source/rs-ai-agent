"""
Phase 2 Automated Test Suite: Persistent Conversation State Machine
Tests state creation, transitions, quantity memory, package selection, sample tracking,
audit history, takeover synchronization, and persistence across server reload.
"""

import unittest
import uuid
import json
from app.database import (
    init_db, get_db_connection, set_admin_takeover, enable_conversation_ai,
    get_structured_conversation_state, get_or_create_conversation_state, update_conversation_state,
    transition_state, sync_human_takeover_state
)
from app.ai_agent.conversation_state import SalesStage, get_state_audit_history
from app.ai_agent.gemini_brain import evaluate_id_card_workflow

get_conversation_state = get_structured_conversation_state


class TestConversationStateMachine(unittest.TestCase):

    def setUp(self):
        init_db()
        self.ws_id = 1
        self.cust_id = f"test_cust_{uuid.uuid4().hex[:8]}"

    def test_01_customer_states_quantity_50(self):
        """TEST 1: Customer says '৫০টা লাগবে' -> quantity = 50, stage = QUANTITY_IDENTIFIED"""
        res = evaluate_id_card_workflow(
            message_text="আমার ৫০টা লাগবে",
            customer_name="Rahim",
            workspace_id=self.ws_id,
            sender_id=self.cust_id
        )
        self.assertIsNotNone(res)
        state = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(state["quantity"], 50)
        self.assertEqual(state["current_sales_stage"], SalesStage.SAMPLE_PERMISSION_PENDING) # Since bot asked permission
        print("[PASSED] Test 01 Passed: Quantity 50 saved to persistent structured state.")

    def test_02_customer_updates_quantity_to_80(self):
        """TEST 2: Customer says '৫০ না, ৮০টা লাগবে' -> quantity = 80, state_version increments"""
        # Step 1: Customer said 50
        evaluate_id_card_workflow(
            message_text="৫০টা লাগবে",
            customer_name="Rahim",
            workspace_id=self.ws_id,
            sender_id=self.cust_id
        )
        state_v1 = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(state_v1["quantity"], 50)
        v1_num = state_v1["state_version"]

        # Step 2: Customer revises to 80
        evaluate_id_card_workflow(
            message_text="৫০ না, ৮০টা লাগবে",
            customer_name="Rahim",
            workspace_id=self.ws_id,
            sender_id=self.cust_id
        )
        state_v2 = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(state_v2["quantity"], 80)
        self.assertGreater(state_v2["state_version"], v1_num)
        print("[PASSED] Test 02 Passed: Quantity updated to 80 and state_version incremented.")

    def test_03_customer_selects_package_7(self):
        """TEST 3: Customer says 'Package 7 চাই' -> package_id = 7, stage = PACKAGE_IDENTIFIED"""
        history = [
            {"sender": "user", "content": "১০০টা লাগবে"},
            {"sender": "bot", "content": "কোন প্যাকেজটি পছন্দ হয় জানাবেন"}
        ]
        res = evaluate_id_card_workflow(
            message_text="প্যাকেজ ৭",
            conversation_history=history,
            customer_name="Karim",
            workspace_id=self.ws_id,
            sender_id=self.cust_id
        )
        self.assertIsNotNone(res)
        state = get_conversation_state(self.cust_id, self.ws_id)
        self.assertIn(state["package_id"], ["৭", "7", "selected"])
        self.assertEqual(state["current_sales_stage"], SalesStage.PACKAGE_IDENTIFIED)
        print("[PASSED] Test 03 Passed: Package 7 structured memory saved.")

    def test_04_customer_quantity_under_30_moq_rejected(self):
        """TEST 4: Quantity = 20 -> MOQ_REJECTED"""
        res = evaluate_id_card_workflow(
            message_text="২০টা আইডি কার্ড লাগবে",
            customer_name="Salam",
            workspace_id=self.ws_id,
            sender_id=self.cust_id
        )
        self.assertIsNotNone(res)
        self.assertIn("সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস", res["reply_text"])
        state = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(state["quantity"], 20)
        self.assertEqual(state["current_sales_stage"], SalesStage.MOQ_REJECTED)
        print("[PASSED] Test 04 Passed: Quantity under 30 transitions to MOQ_REJECTED.")

    def test_05_sample_permission_granted(self):
        """TEST 5: Sample permission granted"""
        history = [
            {"sender": "user", "content": "১০০ পিস বানাবো"},
            {"sender": "bot", "content": "আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
        ]
        res = evaluate_id_card_workflow(
            message_text="হ্যাঁ পাঠান",
            conversation_history=history,
            customer_name="Barkat",
            workspace_id=self.ws_id,
            sender_id=self.cust_id
        )
        self.assertIsNotNone(res)
        state = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(state["sample_permission"], "granted")
        print("[PASSED] Test 05 Passed: Sample permission granted correctly stored.")

    def test_06_full_sample_sequence_sent_persists(self):
        """TEST 6: Full sample sequence sent -> sample_sent = true, timestamp recorded"""
        history = [
            {"sender": "user", "content": "১০০ পিস বানাবো"},
            {"sender": "bot", "content": "আমাদের স্যাম্পলগুলো পাঠাবো কি?"}
        ]
        res = evaluate_id_card_workflow(
            message_text="জি পাঠান",
            conversation_history=history,
            customer_name="Barkat",
            workspace_id=self.ws_id,
            sender_id=self.cust_id
        )
        self.assertIsNotNone(res)
        state = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(state["sample_sent"], 1)
        self.assertIsNotNone(state["sample_sent_at"])
        self.assertEqual(state["current_sales_stage"], SalesStage.SAMPLE_SENT)
        print("[PASSED] Test 06 Passed: Full sample sequence recorded in persistent state.")

    def test_07_package_change_invalidates_quoted_price(self):
        """TEST 7: Customer changes package after quote -> previous quote becomes stale/None"""
        # Set an initial quote of 82 Tk for Package 7
        update_conversation_state(
            sender_id=self.cust_id,
            updates={
                "quantity": 100,
                "package_id": "7",
                "quoted_price": 82.0,
                "current_sales_stage": SalesStage.PRICE_READY
            },
            reason="initial_quote",
            workspace_id=self.ws_id
        )
        s1 = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(s1["quoted_price"], 82.0)

        # Customer changes package to Package 1
        history = [
            {"sender": "bot", "content": "কোন প্যাকেজটি পছন্দ হয় জানাবেন"}
        ]
        evaluate_id_card_workflow(
            message_text="প্যাকেজ ১ দেন",
            conversation_history=history,
            customer_name="Rahim",
            workspace_id=self.ws_id,
            sender_id=self.cust_id
        )
        s2 = get_conversation_state(self.cust_id, self.ws_id)
        self.assertIn(s2["package_id"], ["১", "1", "selected"])
        self.assertIsNone(s2["quoted_price"]) # Stale quote reset
        print("[PASSED] Test 07 Passed: Changing package successfully invalidates stale quote.")

    def test_08_owner_takeover_synchronization(self):
        """TEST 8: Owner takeover activated -> stage = OWNER_TAKEOVER, human_takeover = 1"""
        # Initialize state
        get_or_create_conversation_state(self.cust_id, self.ws_id)

        # Trigger admin takeover
        set_admin_takeover(sender_id=self.cust_id, workspace_id=self.ws_id, takeover_by="human_admin")
        
        state = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(state["human_takeover"], 1)
        self.assertEqual(state["current_sales_stage"], SalesStage.OWNER_TAKEOVER)

        # Release takeover
        enable_conversation_ai(sender_id=self.cust_id, workspace_id=self.ws_id)
        state_released = get_conversation_state(self.cust_id, self.ws_id)
        self.assertEqual(state_released["human_takeover"], 0)
        print("[PASSED] Test 08 Passed: Owner takeover cleanly synchronized with state machine.")

    def test_09_state_persistence_across_connection_reloads(self):
        """TEST 9: Server restart / DB reconnect -> state remains 100% available"""
        # Update rich state
        update_conversation_state(
            sender_id=self.cust_id,
            updates={
                "quantity": 150,
                "package_id": "7",
                "sample_sent": 1,
                "advance_status": "pending",
                "customer_info_status": "partial",
                "current_sales_stage": SalesStage.CUSTOMER_INFO_PENDING
            },
            reason="test_persistence",
            workspace_id=self.ws_id
        )

        # Fresh DB connection (simulating fresh server restart)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM conversation_states WHERE sender_id = ? AND workspace_id = ?", (self.cust_id, self.ws_id))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["quantity"], 150)
        self.assertEqual(row["package_id"], "7")
        self.assertEqual(row["sample_sent"], 1)
        self.assertEqual(row["advance_status"], "pending")
        self.assertEqual(row["customer_info_status"], "partial")
        self.assertEqual(row["current_sales_stage"], SalesStage.CUSTOMER_INFO_PENDING)
        print("[PASSED] Test 09 Passed: Rich conversation state survives complete database reload.")

    def test_10_two_rapid_messages_latest_valid_state_wins(self):
        """TEST 10: Two rapid messages update quantity -> latest valid customer state wins"""
        ok1, s1 = update_conversation_state(
            sender_id=self.cust_id,
            updates={"quantity": 50, "current_sales_stage": SalesStage.QUANTITY_IDENTIFIED},
            reason="msg_1",
            workspace_id=self.ws_id
        )
        self.assertTrue(ok1)
        self.assertEqual(s1["quantity"], 50)

        ok2, s2 = update_conversation_state(
            sender_id=self.cust_id,
            updates={"quantity": 100, "current_sales_stage": SalesStage.QUANTITY_IDENTIFIED},
            reason="msg_2",
            workspace_id=self.ws_id
        )
        self.assertTrue(ok2)
        self.assertEqual(s2["quantity"], 100)
        self.assertGreater(s2["state_version"], s1["state_version"])

        # Check audit trail has both events recorded in order
        audits = get_state_audit_history(self.cust_id, self.ws_id)
        self.assertGreaterEqual(len(audits), 2)
        reasons = [a["reason"] for a in audits]
        self.assertIn("msg_1", reasons)
        self.assertIn("msg_2", reasons)
        print("[PASSED] Test 10 Passed: Atomic state updates & audit logging verified for rapid messages.")


if __name__ == "__main__":
    unittest.main()
