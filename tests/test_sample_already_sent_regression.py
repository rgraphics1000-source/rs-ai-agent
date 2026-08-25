"""
Tests for Phase 8.8C: Sample Already Sent Regression & Monotonic State Protection.

Guarantees:
1. Once samples are dispatched (sample_sent=1, sample_permission='granted', stage=SAMPLE_SENT),
   the system NEVER re-asks 'আমাদের স্যাম্পলগুলো পাঠাবো কি?'.
2. Monotonic state guard blocks regressing to SAMPLE_PERMISSION_PENDING or sample_permission='pending'.
3. Follow-up customer intents (pricing, negotiation, quantity change, delivery, photo service)
   are handled normally without duplicate sample dispatch or permission prompts.
4. Step-by-step negotiation (80+ bulk tier) and below-floor Owner Approval (82 Tk floor on Package 7)
   work flawlessly after SAMPLE_SENT.
5. State survives application restarts and SQLite database reloads.
6. Explicit re-requests for samples ('আবার স্যাম্পল পাঠাবেন?') are handled properly.
"""

import unittest
import asyncio
import uuid
from app.database import get_db_connection, enable_conversation_ai
from app.ai_agent.conversation_state import (
    get_or_create_conversation_state,
    update_conversation_state,
    SalesStage
)
from app.ai_agent.gemini_brain import evaluate_id_card_workflow, generate_smart_fallback_reply
from app.ai_agent.pricing_engine import negotiate_step, PACKAGE_CATALOG


class SampleAlreadySentRegressionTests(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.ws_id = 1
        self.sender_id = f"test_sample_{uuid.uuid4().hex[:8]}"
        enable_conversation_ai(sender_id=self.sender_id, workspace_id=self.ws_id, enabled_by="test_setup")

    def tearDown(self):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM conversation_states WHERE sender_id = ?", (self.sender_id,))
        c.execute("DELETE FROM conversation_state_audits WHERE sender_id = ?", (self.sender_id,))
        conn.commit()
        conn.close()

    def _setup_sample_sent_state(self, quantity=100, package_id="7"):
        """Helper to establish a verified SAMPLE_SENT state in DB."""
        update_conversation_state(
            sender_id=self.sender_id,
            updates={
                "quantity": quantity,
                "package_id": package_id,
                "sample_permission": "granted",
                "sample_sent": 1,
                "current_sales_stage": SalesStage.SAMPLE_SENT
            },
            reason="test_setup_sample_sent",
            workspace_id=self.ws_id
        )

    def test_01_sample_sent_never_reasks_permission(self):
        """Rule 1: Once samples are sent, agent must never re-ask sample permission."""
        self._setup_sample_sent_state(quantity=100)

        history = [
            {"sender": "customer", "text": "আইডি কার্ড বানাবো"},
            {"sender": "assistant", "text": "জি, আপনি কত পিস আইডি কার্ড বানাবেন?"},
            {"sender": "customer", "text": "100"},
            {"sender": "assistant", "text": "জি স্যার, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"},
            {"sender": "customer", "text": "Jee"},
            {"sender": "assistant", "text": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"}
        ]

        # Customer sends a follow up inquiry
        res = evaluate_id_card_workflow(
            message_text="এটি কম করা যাবে না?",
            conversation_history=history,
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])
        self.assertNotIn("স্যাম্পল পাঠাবো", res["reply_text"])
        self.assertEqual(len(res["media_sequence"]), 0)

    def test_02_sample_sent_blocks_pending_regression(self):
        """Rule 5: Monotonic state guard blocks regressing to SAMPLE_PERMISSION_PENDING."""
        self._setup_sample_sent_state(quantity=100)

        # Attempt to regress state to pending
        success, state = update_conversation_state(
            sender_id=self.sender_id,
            updates={
                "sample_permission": "pending",
                "current_sales_stage": SalesStage.SAMPLE_PERMISSION_PENDING
            },
            reason="attempted_regression",
            workspace_id=self.ws_id
        )

        self.assertTrue(success)
        # Verify state was NOT regressed
        self.assertEqual(state["sample_permission"], "granted")
        self.assertEqual(state["sample_sent"], 1)
        self.assertNotEqual(state["current_sales_stage"], SalesStage.SAMPLE_PERMISSION_PENDING)

    def test_03_sample_sent_does_not_duplicate_media(self):
        """Rule 6: Agent does not re-dispatch sample batches once sent."""
        self._setup_sample_sent_state(quantity=100)

        history = [
            {"sender": "customer", "text": "100"},
            {"sender": "assistant", "text": "জি স্যার, আমাদের স্যাম্পলগুলো পাঠাবো কি?"},
            {"sender": "customer", "text": "Jee"},
            {"sender": "assistant", "text": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"}
        ]

        # Customer sends package/sample request again without explicit re-send keyword
        res = evaluate_id_card_workflow(
            message_text="স্যাম্পল পাঠান",
            conversation_history=history,
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        self.assertEqual(len(res["media_sequence"]), 0)
        self.assertEqual(len(res["matched_images"]), 0)
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])
        self.assertIn("পূর্বের পাঠানো স্যাম্পল", res["reply_text"])

    def test_04_sample_sent_then_price_question(self):
        """Rule 2: Customer asks 'প্রতি পিস কত টাকা?' after samples sent -> Quotes proper tier price."""
        self._setup_sample_sent_state(quantity=100)

        history = [
            {"sender": "customer", "text": "100"},
            {"sender": "assistant", "text": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"}
        ]

        res = evaluate_id_card_workflow(
            message_text="প্রতি পিস কত টাকা?",
            conversation_history=history,
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        self.assertIn("প্যাকেজ ১: ৭০ টাকা", res["reply_text"])
        self.assertIn("প্যাকেজ ৭: ৯১ টাকা", res["reply_text"])
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])

    def test_05_sample_sent_then_negotiation(self):
        """Rule 2: Customer asks 'এটি কম করা যাবে না?' -> Handles discount negotiation."""
        self._setup_sample_sent_state(quantity=100, package_id="7")

        history = [
            {"sender": "customer", "text": "100"},
            {"sender": "assistant", "text": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"}
        ]

        res = evaluate_id_card_workflow(
            message_text="এটি কম করা যাবে না?",
            conversation_history=history,
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        self.assertTrue("88" in res["reply_text"] or "৮৮" in res["reply_text"])
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])

    def test_06_sample_sent_then_package_price(self):
        """Rule 2: Customer asks 'Package 7 কত?' -> Quotes 91 Tk upfront without sample re-prompt."""
        self._setup_sample_sent_state(quantity=100)

        history = [
            {"sender": "customer", "text": "100"},
            {"sender": "assistant", "text": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"}
        ]

        res = evaluate_id_card_workflow(
            message_text="Package 7 কত?",
            conversation_history=history,
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        self.assertTrue("৯১" in res["reply_text"] or "91" in res["reply_text"])
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])

    def test_07_sample_sent_then_quantity_change(self):
        """Customer updates quantity from 100 to 50 -> Tier text updated, no sample permission asked."""
        self._setup_sample_sent_state(quantity=100)

        history = [
            {"sender": "customer", "text": "100"},
            {"sender": "assistant", "text": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"}
        ]

        res = evaluate_id_card_workflow(
            message_text="50 পিস লাগবে",
            conversation_history=history,
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        self.assertTrue("50" in res["reply_text"] or "৫০" in res["reply_text"])
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])
        # Verify quantity was updated in DB
        state = get_or_create_conversation_state(self.sender_id, self.ws_id)
        self.assertEqual(state["quantity"], 50)
        self.assertEqual(state["sample_permission"], "granted")
        self.assertEqual(state["sample_sent"], 1)

    def test_08_sample_sent_survives_restart(self):
        """Rule 4: State persistence across DB load -> State remains SENT."""
        self._setup_sample_sent_state(quantity=100)

        # Simulate fresh DB lookup (as after restart)
        state = get_or_create_conversation_state(self.sender_id, self.ws_id)
        self.assertEqual(state["sample_sent"], 1)
        self.assertEqual(state["sample_permission"], "granted")

        res = evaluate_id_card_workflow(
            message_text="এটি কম করা যাবে না?",
            conversation_history=[],
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])
        self.assertTrue("88" in res["reply_text"] or "৮৮" in res["reply_text"])

    def test_09_sample_sent_then_below_floor_owner_approval(self):
        """Negotiation below 82 Tk floor on Package 7 requires Owner Approval."""
        self._setup_sample_sent_state(quantity=100, package_id="7")

        res = evaluate_id_card_workflow(
            message_text="৭৫ টাকা দেন",
            conversation_history=[],
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        self.assertTrue("৮২" in res["reply_text"] or "82" in res["reply_text"])
        self.assertIn("Owner", res["reply_text"])
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])

    def test_10_explicit_resample_request(self):
        """Rule 3: Explicit re-request for samples ('স্যাম্পলগুলো আবার পাঠাবেন?') handled properly."""
        self._setup_sample_sent_state(quantity=100)

        res = evaluate_id_card_workflow(
            message_text="স্যাম্পলগুলো আবার পাঠাবেন?",
            conversation_history=[
                {"sender": "assistant", "text": "জি স্যার, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।"}
            ],
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )

        self.assertIsNotNone(res)
        # Dispatches samples since explicitly asked again
        self.assertTrue(len(res["matched_images"]) > 0 or len(res["media_sequence"]) > 0)
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res["reply_text"])

    def test_11_sample_state_persists_after_jee_affirmation(self):
        """Full multi-turn sequence: কার্ড বানাবো -> 100 -> Jee -> sample state is strictly SENT."""
        # Turn 1: কার্ড বানাবো
        res1 = evaluate_id_card_workflow(
            message_text="আইডি কার্ড বানাবো",
            conversation_history=[],
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )
        self.assertIsNotNone(res1)
        self.assertIn("কত পিস", res1["reply_text"])

        # Turn 2: 100
        res2 = evaluate_id_card_workflow(
            message_text="100",
            conversation_history=[
                {"sender": "customer", "text": "আইডি কার্ড বানাবো"},
                {"sender": "assistant", "text": res1["reply_text"]}
            ],
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )
        self.assertIsNotNone(res2)
        self.assertIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res2["reply_text"])

        # Turn 3: Jee
        res3 = evaluate_id_card_workflow(
            message_text="Jee",
            conversation_history=[
                {"sender": "customer", "text": "আইডি কার্ড বানাবো"},
                {"sender": "assistant", "text": res1["reply_text"]},
                {"sender": "customer", "text": "100"},
                {"sender": "assistant", "text": res2["reply_text"]}
            ],
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )
        self.assertIsNotNone(res3)
        self.assertTrue(len(res3["matched_images"]) > 0 or len(res3["media_sequence"]) > 0)

        # Verify DB state
        state = get_or_create_conversation_state(self.sender_id, self.ws_id)
        self.assertEqual(state["sample_sent"], 1)
        self.assertEqual(state["sample_permission"], "granted")
        self.assertEqual(state["current_sales_stage"], SalesStage.SAMPLE_SENT)

        # Turn 4: 'এটি কম করা যাবে না?'
        res4 = evaluate_id_card_workflow(
            message_text="এটি কম করা যাবে না?",
            conversation_history=[
                {"sender": "customer", "text": "100"},
                {"sender": "assistant", "text": res2["reply_text"]},
                {"sender": "customer", "text": "Jee"},
                {"sender": "assistant", "text": res3["reply_text"]}
            ],
            sender_id=self.sender_id,
            workspace_id=self.ws_id
        )
        self.assertIsNotNone(res4)
        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", res4["reply_text"])
        self.assertEqual(len(res4["media_sequence"]), 0)

    def test_12_sample_sent_never_returns_to_permission_pending(self):
        """Ensures that generate_smart_fallback_reply also respects sample_sent state."""
        conv_state = {
            "quantity": 100,
            "sample_sent": 1,
            "sample_permission": "granted",
            "current_sales_stage": "SAMPLE_SENT"
        }

        reply = generate_smart_fallback_reply(
            user_msg="এটি কম করা যাবে না?",
            customer_name="Customer",
            workspace_id=1,
            conversation_state=conv_state
        )

        self.assertNotIn("আমাদের স্যাম্পলগুলো পাঠাবো কি", reply)
        self.assertTrue("88" in reply or "৮৮" in reply)


if __name__ == "__main__":
    unittest.main()
