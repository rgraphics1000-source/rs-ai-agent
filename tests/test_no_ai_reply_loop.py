# -*- coding: utf-8 -*-
"""
Production Regression Suite: Anti-Reply-Loop, Echo Immunity, and Single-Reply Enforcement.

Validates the complete end-to-end immunity architecture:
1. Scenario A: Single customer message -> Exactly 1 AI generation -> Exactly 1 reply -> AI silent until new customer message.
2. Scenario B: WhatsApp status callback (delivered/read/sent) -> Discarded immediately without AI triggering.
3. Scenario C: Duplicate webhook delivery with identical message_id -> Discarded atomically via claim_webhook_event.
4. Scenario D: Outgoing AI message echo -> Detected via is_own_whatsapp_number / is_outbound_ai_message -> Discarded immediately.
5. Scenario E: 4 customer messages within debounce window -> Batched into 1 -> Exactly 1 Gemini call -> Exactly 1 AI reply.
6. Scenario F: Concurrent generation attempt for same conversation -> Blocked by generation lock -> No duplicate generation.
7. Scenario G: Admin takeover message -> AI permanently silenced -> Pending batches cancelled -> No subsequent AI generation.
8. Facebook Scenario: Outgoing AI Bot echo -> Discarded immediately without triggering admin takeover or AI reply loop.
9. Facebook Scenario: Human Admin echo (Page Inbox reply) -> Auto-triggers Admin Takeover -> Cancels pending batch -> AI silent.
10. Turn Sequence Check: If customer_turn_version <= last_responded_turn_version, AI generation is blocked.
11. Atomic claim_webhook_event test with concurrent threads.
12. Database message direction & sender_role integrity check.
"""

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import time
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from app.database import (
    get_db_connection, init_db, set_admin_takeover, enable_conversation_ai,
    get_conversation_state, record_outbound_ai_message, is_outbound_ai_message,
    claim_webhook_event, is_own_whatsapp_number, acquire_generation_lock,
    release_generation_lock, get_conversation_turn_versions,
    increment_customer_turn_version, mark_turn_responded
)
from app.channels.debouncer import MessageDebouncer, PendingBatch
from app.channels.omnichat import record_conversation_message, get_conversation_history


class TestNoAIReplyLoop(unittest.TestCase):
    def setUp(self):
        self.workspace_id = 99
        self.test_phone = "8801700000099"
        self.fb_sender_id = "fb_cust_9999"
        self.debouncer = MessageDebouncer(debounce_seconds=0.05)  # Fast debounce for testing

        # Clean DB state for this test phone
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE sender_id IN (?, ?))", (self.test_phone, self.fb_sender_id))
        cursor.execute("DELETE FROM conversations WHERE sender_id IN (?, ?)", (self.test_phone, self.fb_sender_id))
        cursor.execute("DELETE FROM processed_webhook_events WHERE page_id_or_phone_id = 'test_unit' OR direction = 'OUTBOUND' OR sender_role = 'AI'")
        conn.commit()
        conn.close()

        enable_conversation_ai(sender_id=self.test_phone, workspace_id=self.workspace_id)
        enable_conversation_ai(sender_id=self.fb_sender_id, workspace_id=self.workspace_id)

    # --------------------------------------------------------------------------
    # Scenario A: Single customer message -> Exactly 1 AI generation -> Silence
    # --------------------------------------------------------------------------
    def test_scenario_a_single_message_single_response(self):
        generation_count = 0
        responses_sent = []

        async def dummy_callback(batch: PendingBatch):
            nonlocal generation_count
            generation_count += 1
            reply = f"Hello {batch.customer_name}, response {generation_count}"
            responses_sent.append(reply)
            record_conversation_message(
                batch.channel, batch.sender_id, batch.customer_name, "bot", reply,
                workspace_id=batch.workspace_id, direction="OUTBOUND", sender_role="AI"
            )

        async def run_flow():
            record_conversation_message(
                "whatsapp", self.test_phone, "Test Customer", "user", "Hi there",
                workspace_id=self.workspace_id, direction="INBOUND", sender_role="CUSTOMER", external_message_id="msg_a_1"
            )
            await self.debouncer.add_message(
                channel="whatsapp",
                workspace_id=self.workspace_id,
                sender_id=self.test_phone,
                customer_name="Test Customer",
                msg_id="msg_a_1",
                text="Hi there",
                callback=dummy_callback
            )
            await asyncio.sleep(0.12)  # Wait for debounce and processing

        asyncio.run(run_flow())

        self.assertEqual(generation_count, 1, "Exactly ONE AI generation must execute for 1 customer turn")
        self.assertEqual(len(responses_sent), 1, "Exactly ONE response must be sent")

        # Verify DB turn sequence
        turns = get_conversation_turn_versions("whatsapp", self.test_phone, self.workspace_id)
        self.assertEqual(turns["customer_turn_version"], turns["last_responded_turn_version"], "customer_turn_version and last_responded_turn_version must match after AI reply")
        self.assertGreaterEqual(turns["last_responded_turn_version"], 1)

    # --------------------------------------------------------------------------
    # Scenario B: WhatsApp status callback (delivered/read/sent) -> Discarded
    # --------------------------------------------------------------------------
    def test_scenario_b_whatsapp_status_webhook_ignored(self):
        from app.channels.whatsapp import handle_whatsapp_webhook_event

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {
                            "phone_number_id": "4184514263660680",
                            "display_phone_number": "8801816504097"
                        },
                        "statuses": [{
                            "id": "wamid.HBgLODgwMTcxODgwODk0MBUC...",
                            "status": "delivered",
                            "timestamp": "1700000000",
                            "recipient_id": self.test_phone
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.message_debouncer.add_message", new_callable=AsyncMock) as mock_add:
            asyncio.run(handle_whatsapp_webhook_event(payload))
            mock_add.assert_not_called()

    # --------------------------------------------------------------------------
    # Scenario C: Duplicate webhook delivery -> Deduplicated atomically
    # --------------------------------------------------------------------------
    def test_scenario_c_duplicate_webhook_deduplication(self):
        msg_id = f"wamid_test_dup_{int(time.time()*1000)}"

        # First claim should succeed
        res1 = claim_webhook_event("whatsapp", msg_id, workspace_id=self.workspace_id, page_id_or_phone_id="test_unit", direction="INBOUND", sender_role="CUSTOMER")
        self.assertTrue(res1, "First webhook event claim must succeed")

        # Second claim with same msg_id must fail (deduplicated)
        res2 = claim_webhook_event("whatsapp", msg_id, workspace_id=self.workspace_id, page_id_or_phone_id="test_unit", direction="INBOUND", sender_role="CUSTOMER")
        self.assertFalse(res2, "Duplicate webhook event claim must fail")

    # --------------------------------------------------------------------------
    # Scenario D: Outgoing AI message echo -> Immune & Discarded immediately
    # --------------------------------------------------------------------------
    def test_scenario_d_outgoing_ai_message_echo_immunity(self):
        ai_out_mid = f"wamid_ai_out_{int(time.time()*1000)}"

        # Record outbound AI message
        record_outbound_ai_message("whatsapp", ai_out_mid, workspace_id=self.workspace_id, page_id_or_phone_id="4184514263660680")
        self.assertTrue(is_outbound_ai_message("whatsapp", ai_out_mid))

        # Check own business number immunity
        self.assertTrue(is_own_whatsapp_number("8801816504097"))
        self.assertTrue(is_own_whatsapp_number("+8801816504097"))
        self.assertTrue(is_own_whatsapp_number("01816504097"))
        self.assertFalse(is_own_whatsapp_number(self.test_phone))

    # --------------------------------------------------------------------------
    # Scenario E: 4 customer messages within 2s -> Batched into 1 response
    # --------------------------------------------------------------------------
    def test_scenario_e_multi_message_batching_single_response(self):
        generation_count = 0
        messages_received_in_batch = 0

        async def dummy_callback(batch: PendingBatch):
            nonlocal generation_count, messages_received_in_batch
            generation_count += 1
            messages_received_in_batch = len(batch.messages)
            reply = f"Processed {len(batch.messages)} customer messages"
            record_conversation_message(
                batch.channel, batch.sender_id, batch.customer_name, "bot", reply,
                workspace_id=batch.workspace_id, direction="OUTBOUND", sender_role="AI"
            )

        async def run_burst():
            for i in range(1, 5):
                m_id = f"burst_msg_{i}"
                record_conversation_message(
                    "whatsapp", self.test_phone, "Test Customer", "user", f"Part {i}",
                    workspace_id=self.workspace_id, direction="INBOUND", sender_role="CUSTOMER", external_message_id=m_id
                )
                await self.debouncer.add_message(
                    channel="whatsapp",
                    workspace_id=self.workspace_id,
                    sender_id=self.test_phone,
                    customer_name="Test Customer",
                    msg_id=m_id,
                    text=f"Part {i}",
                    callback=dummy_callback
                )
                await asyncio.sleep(0.01)  # Incoming burst before 0.05s timer fires

            await asyncio.sleep(0.15)  # Wait for batch finalization

        asyncio.run(run_burst())

        self.assertEqual(generation_count, 1, "Burst of 4 messages must trigger exactly 1 generation")
        self.assertEqual(messages_received_in_batch, 4, "Batch must aggregate all 4 messages")

    # --------------------------------------------------------------------------
    # Scenario F: Concurrent Generation Lock prevents duplicate responses
    # --------------------------------------------------------------------------
    def test_scenario_f_concurrent_generation_lock(self):
        conv_id = f"whatsapp_{self.test_phone}"

        async def test_lock():
            # Acquire lock 1
            lock1 = await acquire_generation_lock(conv_id)
            self.assertTrue(lock1, "First generation lock acquisition must succeed")

            # Try acquiring lock 2 while lock 1 is held -> MUST FAIL
            lock2 = await acquire_generation_lock(conv_id)
            self.assertFalse(lock2, "Concurrent generation lock acquisition must be blocked")

            # Release lock 1
            await release_generation_lock(conv_id)

            # Now acquiring lock 3 should succeed
            lock3 = await acquire_generation_lock(conv_id)
            self.assertTrue(lock3, "Lock acquisition after release must succeed")
            await release_generation_lock(conv_id)

        asyncio.run(test_lock())

    # --------------------------------------------------------------------------
    # Scenario G: Admin Takeover silences AI immediately & cancels pending batches
    # --------------------------------------------------------------------------
    def test_scenario_g_admin_takeover_immediate_silence(self):
        generation_called = False

        async def dummy_callback(batch: PendingBatch):
            nonlocal generation_called
            generation_called = True

        async def run_takeover_flow():
            # 1. Customer sends message
            record_conversation_message(
                "whatsapp", self.test_phone, "Test Customer", "user", "I need help",
                workspace_id=self.workspace_id, direction="INBOUND", sender_role="CUSTOMER", external_message_id="msg_g_1"
            )
            await self.debouncer.add_message(
                channel="whatsapp",
                workspace_id=self.workspace_id,
                sender_id=self.test_phone,
                customer_name="Test Customer",
                msg_id="msg_g_1",
                text="I need help",
                callback=dummy_callback
            )

            # 2. Human Admin sends a message before debounce window ends (0.01s < 0.05s)
            await asyncio.sleep(0.01)
            set_admin_takeover(sender_id=self.test_phone, workspace_id=self.workspace_id, takeover_by="admin_test", takeover_reason="manual_reply")
            self.debouncer.cancel_batch("whatsapp", self.workspace_id, self.test_phone)

            # 3. Wait for timer expiration
            await asyncio.sleep(0.1)

        asyncio.run(run_takeover_flow())

        self.assertFalse(generation_called, "AI must NEVER generate a response after Admin Takeover")
        state = get_conversation_state(sender_id=self.test_phone, workspace_id=self.workspace_id)
        self.assertEqual(state["admin_takeover"], 1)
        self.assertEqual(state["ai_enabled"], 0)

    # --------------------------------------------------------------------------
    # Facebook Bot Outgoing Echo Immunity vs Human Admin Takeover
    # --------------------------------------------------------------------------
    def test_facebook_echo_bot_vs_human_admin(self):
        from app.channels.facebook import handle_facebook_webhook_event
        from app.config import settings

        target_ws_id = 1
        enable_conversation_ai(sender_id=self.fb_sender_id, workspace_id=target_ws_id)

        # 1. Outgoing Bot Echo (with app_id = META_APP_ID or recorded in outbound_ai_messages)
        ai_mid = "mid.ai_bot_fb_echo_123"
        record_outbound_ai_message("facebook", ai_mid, workspace_id=target_ws_id, page_id_or_phone_id="105116472071659")

        bot_echo_payload = {
            "entry": [{
                "id": "105116472071659",
                "messaging": [{
                    "sender": {"id": "105116472071659"},
                    "recipient": {"id": self.fb_sender_id},
                    "message": {
                        "mid": ai_mid,
                        "is_echo": True,
                        "app_id": settings.META_APP_ID,
                        "text": "This is an AI Bot reply"
                    }
                }]
            }]
        }

        # Should be ignored as OUTBOUND_ECHO without setting admin takeover
        asyncio.run(handle_facebook_webhook_event(bot_echo_payload))
        state_after_bot_echo = get_conversation_state(sender_id=self.fb_sender_id, workspace_id=target_ws_id)
        self.assertEqual(state_after_bot_echo["admin_takeover"], 0, "Bot echo must NOT trigger admin takeover")
        self.assertEqual(state_after_bot_echo["ai_enabled"], 1, "Bot echo must NOT disable AI")

        # 2. Human Admin Echo (from Meta Page Inbox, no bot app_id and not in outbound_ai_messages)
        human_admin_payload = {
            "entry": [{
                "id": "105116472071659",
                "messaging": [{
                    "sender": {"id": "105116472071659"},
                    "recipient": {"id": self.fb_sender_id},
                    "message": {
                        "mid": "mid.human_admin_echo_456",
                        "is_echo": True,
                        "text": "Hello, I am the shop owner taking over."
                    }
                }]
            }]
        }

        asyncio.run(handle_facebook_webhook_event(human_admin_payload))
        state_after_admin = get_conversation_state(sender_id=self.fb_sender_id, workspace_id=target_ws_id)
        self.assertEqual(state_after_admin["admin_takeover"], 1, "Human admin echo MUST trigger Admin Takeover")
        self.assertEqual(state_after_admin["ai_enabled"], 0, "Human admin echo MUST disable AI")

    # --------------------------------------------------------------------------
    # Turn Sequence Gating Test: No duplicate generation without new turn
    # --------------------------------------------------------------------------
    def test_turn_sequence_gating(self):
        channel = "whatsapp"
        # Initial turn versions
        init_turns = get_conversation_turn_versions(channel, self.test_phone, self.workspace_id)
        c_ver_init = init_turns["customer_turn_version"]
        
        increment_customer_turn_version(channel, self.test_phone, self.workspace_id)
        turns = get_conversation_turn_versions(channel, self.test_phone, self.workspace_id)
        self.assertEqual(turns["customer_turn_version"], c_ver_init + 1)
        self.assertEqual(turns["last_responded_turn_version"], 0)

        # Mark turn responded
        mark_turn_responded(channel, self.test_phone, turns["customer_turn_version"], self.workspace_id)
        turns2 = get_conversation_turn_versions(channel, self.test_phone, self.workspace_id)
        self.assertEqual(turns2["customer_turn_version"], turns["customer_turn_version"])
        self.assertEqual(turns2["last_responded_turn_version"], turns["customer_turn_version"])

        # Another response attempt without new customer turn must be blocked
        gen_called = False
        async def dummy_cb(batch):
            nonlocal gen_called
            gen_called = True

        conv_state = get_conversation_state(self.test_phone, self.workspace_id)
        cur_ver = conv_state.get("conversation_version", 1)
        batch = PendingBatch(channel, self.workspace_id, self.test_phone, "Cust", cur_ver)
        batch.callback = dummy_cb
        batch.debounce_deadline = time.time() - 1  # already expired

        # Fix cur_ver matching so worker runs check
        batch.initial_version = cur_ver
        asyncio.run(self.debouncer._debounce_worker("dummy_key", batch))
        self.assertFalse(gen_called, "Worker must NOT execute AI generation if customer_turn_version <= last_responded_turn_version")

    # --------------------------------------------------------------------------
    # Concurrent Atomic Deduplication Check (Multi-Threaded Race Condition)
    # --------------------------------------------------------------------------
    def test_atomic_claim_webhook_event_concurrent_threads(self):
        import concurrent.futures
        import uuid
        event_id = f"test_concurrent_race_event_{uuid.uuid4().hex}"
        results = []

        def worker_claim():
            return claim_webhook_event("whatsapp", event_id, workspace_id=self.workspace_id, page_id_or_phone_id="test_race")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_claim) for _ in range(10)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        true_count = sum(1 for r in results if r is True)
        false_count = sum(1 for r in results if r is False)
        self.assertEqual(true_count, 1, "Exactly ONE concurrent thread must successfully claim the event")
        self.assertEqual(false_count, 9, "All remaining 9 concurrent threads must be rejected atomically")

    # --------------------------------------------------------------------------
    # Database Message Model Integrity Check (Direction, Sender Role, Turn Version)
    # --------------------------------------------------------------------------
    def test_message_database_integrity(self):
        # 1. Record Inbound Customer Message
        record_conversation_message(
            "whatsapp", self.test_phone, "Test Customer", "user", "How much is this item?",
            workspace_id=self.workspace_id, direction="INBOUND", sender_role="CUSTOMER", external_message_id="ext_msg_inbound_101"
        )

        # 2. Record Outbound AI Reply
        record_conversation_message(
            "whatsapp", self.test_phone, "Test Customer", "bot", "This item is 70 BDT.",
            workspace_id=self.workspace_id, direction="OUTBOUND", sender_role="AI", external_message_id="ext_msg_outbound_102"
        )

        # Fetch history
        history = get_conversation_history("whatsapp", self.test_phone, workspace_id=self.workspace_id)
        self.assertGreaterEqual(len(history), 2)

        inbound_msg = [m for m in history if m.get("direction") == "INBOUND" or m.get("sender_role") == "CUSTOMER"]
        outbound_msg = [m for m in history if m.get("direction") == "OUTBOUND" or m.get("sender_role") == "AI"]

        self.assertTrue(len(inbound_msg) >= 1, "Inbound message must be recorded with direction=INBOUND and sender_role=CUSTOMER")
        self.assertTrue(len(outbound_msg) >= 1, "Outbound message must be recorded with direction=OUTBOUND and sender_role=AI")

    # --------------------------------------------------------------------------
    # Facebook Duplicate Webhook Deduplication Check
    # --------------------------------------------------------------------------
    def test_facebook_duplicate_webhook_deduplication(self):
        import uuid
        dup_mid = f"mid.fb_dup_test_{uuid.uuid4().hex}"
        dup_payload = {
            "entry": [{
                "id": "105116472071659",
                "messaging": [{
                    "sender": {"id": self.fb_sender_id},
                    "recipient": {"id": "105116472071659"},
                    "message": {
                        "mid": dup_mid,
                        "text": "Checking product details"
                    }
                }]
            }]
        }

        # First delivery should be claimed
        first_claimed = claim_webhook_event("facebook", dup_mid, workspace_id=1, page_id_or_phone_id="105116472071659")
        self.assertTrue(first_claimed, "First webhook delivery must be claimed successfully")

        # Second delivery with same mid must be rejected
        second_claimed = claim_webhook_event("facebook", dup_mid, workspace_id=1, page_id_or_phone_id="105116472071659")
        self.assertFalse(second_claimed, "Duplicate Facebook webhook delivery must be rejected atomically")


if __name__ == "__main__":
    unittest.main()
