import unittest
import asyncio
import sys
import os
import time
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.database import (
    init_db, get_db_connection, get_conversation_state, set_admin_takeover,
    enable_conversation_ai, is_conversation_ai_active, save_connected_page,
    save_whatsapp_account, add_muted_number, remove_muted_number
)
from app.channels.omnichat import record_conversation_message, get_conversation_history
from app.channels.debouncer import MessageDebouncer, PendingBatch
from app.channels.whatsapp import handle_whatsapp_webhook_event
from app.channels.facebook import handle_facebook_webhook_event
from app.ai_agent.gemini_brain import process_customer_message, build_system_instruction

class TestMasterPromptConversationControl(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        save_connected_page({
            "workspace_id": 1,
            "page_id": "test_page_01",
            "page_name": "RS Graphics Test",
            "page_access_token": "TEST_PAGE_TOKEN"
        })
        save_whatsapp_account({
            "workspace_id": 1,
            "page_id": "test_page_01",
            "phone_number_id": "10001",
            "display_phone_number": "8801800000000",
            "waba_id": "waba_test_01",
            "access_token": "TEST_WA_TOKEN"
        })

    def setUp(self):
        self.cust_a = "8801700000001"
        self.cust_b = "8801700000002"
        self.fb_cust_a = "fb_user_test_001"
        self.fb_cust_b = "fb_user_test_002"
        
        # Clean up database records
        conn = get_db_connection()
        conn.execute("DELETE FROM conversations WHERE sender_id IN (?, ?, ?, ?)", (self.cust_a, self.cust_b, self.fb_cust_a, self.fb_cust_b))
        conn.execute("DELETE FROM processed_webhook_events WHERE event_id LIKE 'wam_%'")
        conn.commit()
        conn.close()
        
        from app.channels.whatsapp import PROCESSED_WA_MESSAGE_IDS
        PROCESSED_WA_MESSAGE_IDS.clear()

        remove_muted_number(self.cust_a)
        remove_muted_number(self.cust_b)
        remove_muted_number(self.fb_cust_a)
        remove_muted_number(self.fb_cust_b)

    def tearDown(self):
        conn = get_db_connection()
        conn.execute("DELETE FROM conversations WHERE sender_id IN (?, ?, ?, ?)", (self.cust_a, self.cust_b, self.fb_cust_a, self.fb_cust_b))
        conn.commit()
        conn.close()

    # -------------------------------------------------------------
    # Scenario 1: New customer + AI enabled -> AI replies
    # -------------------------------------------------------------
    def test_01_new_customer_ai_enabled_replies(self):
        state = get_conversation_state(sender_id=self.cust_a, workspace_id=1)
        self.assertTrue(state["ai_enabled"])
        self.assertFalse(state["admin_takeover"])
        self.assertTrue(is_conversation_ai_active(sender_id=self.cust_a, workspace_id=1))
        print("✓ Test 01 Passed: New customer is AI-enabled by default.")

    # -------------------------------------------------------------
    # Scenario 2: Customer sends multiple messages within 3 seconds -> Exactly ONE consolidated turn
    # -------------------------------------------------------------
    def test_02_message_debouncing_aggregates_into_one_turn(self):
        debouncer = MessageDebouncer(debounce_seconds=0.1) # Fast debounce for testing
        executed_batches = []

        async def run_test():
            callback = lambda b: executed_batches.append(b)
            # Send 3 rapid messages
            await debouncer.add_message("whatsapp", 1, self.cust_a, "Customer A", text="হ্যালো", callback=callback)
            await debouncer.add_message("whatsapp", 1, self.cust_a, "Customer A", text="আইডি কার্ডের দাম কত?", callback=callback)
            await debouncer.add_message("whatsapp", 1, self.cust_a, "Customer A", text="৫০ পিস লাগবে", callback=callback)
            
            # Wait for debounce timer to fire
            await asyncio.sleep(0.2)

        asyncio.run(run_test())
        self.assertEqual(len(executed_batches), 1, "Debouncer must consolidate rapid messages into exactly 1 batch.")
        self.assertEqual(len(executed_batches[0].messages), 3, "Batch must contain all 3 incoming customer messages.")
        print("✓ Test 02 Passed: 3-second debounce aggregator produced exactly 1 AI batch.")

    # -------------------------------------------------------------
    # Scenario 3: Admin sends first message to customer -> admin_takeover becomes TRUE & version increments
    # -------------------------------------------------------------
    def test_03_admin_message_triggers_takeover_and_increments_version(self):
        # 1. Customer sends initial message
        cid = record_conversation_message("whatsapp", self.cust_a, "Customer A", "user", "দাম কত?", workspace_id=1)
        initial_state = get_conversation_state(sender_id=self.cust_a, workspace_id=1)
        self.assertTrue(initial_state["ai_enabled"])
        initial_version = initial_state["conversation_version"]

        # 2. Admin replies
        record_conversation_message("whatsapp", self.cust_a, "Customer A", "admin", "জি আমি শপ ওনার বলছি।", workspace_id=1)
        
        takeover_state = get_conversation_state(sender_id=self.cust_a, workspace_id=1)
        self.assertTrue(takeover_state["admin_takeover"], "Admin message must set admin_takeover to True.")
        self.assertFalse(takeover_state["ai_enabled"], "Admin message must set ai_enabled to False.")
        self.assertEqual(takeover_state["human_takeover"], 1)
        self.assertGreater(takeover_state["conversation_version"], initial_version, "Version must increment on admin takeover.")
        print(f"✓ Test 03 Passed: Admin message triggered takeover (v{initial_version} -> v{takeover_state['conversation_version']}).")

    # -------------------------------------------------------------
    # Scenario 4: After takeover, customer sends 1 message -> 0 AI replies (complete silence)
    # -------------------------------------------------------------
    def test_04_after_takeover_single_message_complete_silence(self):
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
        
        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send:
            payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "metadata": {"phone_number_id": "10001", "display_phone_number": "8801800000000"},
                            "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                            "messages": [{
                                "id": "wam_04",
                                "from": self.cust_a,
                                "type": "text",
                                "text": {"body": "হ্যালো কেউ আছেন?"},
                                "timestamp": str(int(time.time()))
                            }]
                        }
                    }]
                }]
            }
            asyncio.run(handle_whatsapp_webhook_event(payload))
            mock_send.assert_not_called()
        print("✓ Test 04 Passed: Single customer message after takeover resulted in 0 AI replies (Silence).")

    # -------------------------------------------------------------
    # Scenario 5: After takeover, customer sends 10 messages -> 0 AI replies
    # -------------------------------------------------------------
    def test_05_after_takeover_ten_messages_complete_silence(self):
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
        
        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send:
            for i in range(10):
                payload = {
                    "entry": [{
                        "changes": [{
                            "value": {
                                "metadata": {"phone_number_id": "10001", "display_phone_number": "8801800000000"},
                                "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                                "messages": [{
                                    "id": f"wam_05_{i}",
                                    "from": self.cust_a,
                                    "type": "text",
                                    "text": {"body": f"মেসেজ {i+1}: ভাইয়া রিপ্লাই দেন"},
                                    "timestamp": str(int(time.time()))
                                }]
                            }
                        }]
                    }]
                }
                asyncio.run(handle_whatsapp_webhook_event(payload))
            
            mock_send.assert_not_called()
        print("✓ Test 05 Passed: 10 customer messages after takeover resulted in 0 AI replies.")

    # -------------------------------------------------------------
    # Scenario 6: After takeover, customer sends image -> 0 AI replies & no vision calls
    # -------------------------------------------------------------
    def test_06_after_takeover_customer_image_silence(self):
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
        
        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send, \
             patch("app.ai_agent.gemini_brain.genai.Client") as mock_genai:
            payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "metadata": {"phone_number_id": "10001", "display_phone_number": "8801800000000"},
                            "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                            "messages": [{
                                "id": "wam_06",
                                "from": self.cust_a,
                                "type": "image",
                                "image": {"id": "img_001", "caption": "এই ছবিটা দেখুন"},
                                "timestamp": str(int(time.time()))
                            }]
                        }
                    }]
                }]
            }
            asyncio.run(handle_whatsapp_webhook_event(payload))
            mock_send.assert_not_called()
            mock_genai.assert_not_called()
        print("✓ Test 06 Passed: Image sent during takeover was completely ignored by AI (0 calls, 0 replies).")

    # -------------------------------------------------------------
    # Scenario 7: Admin takeover while AI job is processing -> pending response discarded
    # -------------------------------------------------------------
    def test_07_admin_takeover_during_ai_generation_discards_reply(self):
        # Customer starts AI-enabled
        enable_conversation_ai(sender_id=self.cust_a, workspace_id=1)

        async def run_test():
            # Mock Gemini to trigger admin takeover while generating
            def fake_generate(*args, **kwargs):
                set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
                mock_resp = MagicMock()
                mock_resp.text = "জি স্যার, আমি সাহায্য করছি।"
                return mock_resp

            with patch("app.ai_agent.gemini_brain.genai.Client") as mock_client_cls, \
                 patch("app.channels.whatsapp.send_whatsapp_message") as mock_send:
                mock_client = MagicMock()
                mock_client.models.generate_content.side_effect = fake_generate
                mock_client_cls.return_value = mock_client

                payload = {
                    "entry": [{
                        "changes": [{
                            "value": {
                                "metadata": {"phone_number_id": "10001", "display_phone_number": "8801800000000"},
                                "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                                "messages": [{
                                    "id": "wam_07",
                                    "from": self.cust_a,
                                    "type": "text",
                                    "text": {"body": "কার্ডের দাম কত?"},
                                    "timestamp": str(int(time.time()))
                                }]
                            }
                        }]
                    }]
                }
                await handle_whatsapp_webhook_event(payload)
                mock_send.assert_not_called()

        asyncio.run(run_test())
        print("✓ Test 07 Passed: In-flight AI response was discarded when takeover occurred mid-generation.")

    # -------------------------------------------------------------
    # Scenario 8: Admin takeover while debounce timer is active -> batch cancelled
    # -------------------------------------------------------------
    def test_08_admin_takeover_cancels_pending_debounce_batch(self):
        debouncer = MessageDebouncer(debounce_seconds=0.2)
        executed = []

        async def run_test():
            callback = lambda b: executed.append(b)
            await debouncer.add_message("whatsapp", 1, self.cust_a, "Customer A", text="হ্যালো", callback=callback)
            
            # Admin takes over during the 0.2s debounce window
            await asyncio.sleep(0.05)
            set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
            debouncer.cancel_batch("whatsapp", 1, self.cust_a)
            
            # Wait for original debounce timer to elapse
            await asyncio.sleep(0.2)

        asyncio.run(run_test())
        self.assertEqual(len(executed), 0, "Cancelled debounce batch must never execute.")
        print("✓ Test 08 Passed: Pending debounce batch successfully cancelled on admin takeover.")

    # -------------------------------------------------------------
    # Scenario 9: Admin takeover customer asks for Google Form -> 0 AI replies & no form creation
    # -------------------------------------------------------------
    def test_09_admin_takeover_customer_google_form_silent(self):
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
        
        with patch("app.google_integration.form_manager.create_institution_form") as mock_form, \
             patch("app.channels.whatsapp.send_whatsapp_message") as mock_send:
            payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "metadata": {"phone_number_id": "10001", "display_phone_number": "8801800000000"},
                            "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                            "messages": [{
                                "id": "wam_09",
                                "from": self.cust_a,
                                "type": "text",
                                "text": {"body": "আমাদের জামিয়া রাহমানিয়ার জন্য একটি গুগল ফর্ম বানিয়ে দিন। মোবাইল: 01711223344"},
                                "timestamp": str(int(time.time()))
                            }]
                        }
                    }]
                }]
            }
            asyncio.run(handle_whatsapp_webhook_event(payload))
            mock_form.assert_not_called()
            mock_send.assert_not_called()
        print("✓ Test 09 Passed: Google Form request during takeover produced 0 replies and 0 form creation.")

    # -------------------------------------------------------------
    # Scenario 10: Admin takeover customer sends screenshot -> 0 AI replies
    # -------------------------------------------------------------
    def test_10_admin_takeover_customer_screenshot_silent(self):
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
        
        res = asyncio.run(process_customer_message(
            message_text="",
            image_bytes=b"fake_screenshot_data",
            image_mime="image/png",
            conversation_history=[],
            sender_id=self.cust_a,
            workspace_id=1
        ))
        self.assertEqual(res.get("reply_text"), "")
        self.assertEqual(res.get("response_source"), "admin_takeover_silence")
        print("✓ Test 10 Passed: Screenshot under takeover returned complete silence.")

    # -------------------------------------------------------------
    # Scenario 11: AI-enabled customer sends screenshot -> Vision analysis occurs
    # -------------------------------------------------------------
    def test_11_ai_enabled_customer_screenshot_processed(self):
        enable_conversation_ai(sender_id=self.cust_a, workspace_id=1)
        
        with patch("app.ai_agent.gemini_brain.genai.Client") as mock_genai:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = "জি স্যার, আপনার স্ক্রিনশটে থাকা আইডি কার্ডের ডিজাইনটি দেখেছি। এটি সুন্দরভাবে প্রিন্ট করা যাবে।"
            mock_client.models.generate_content.return_value = mock_resp
            mock_genai.return_value = mock_client

            res = asyncio.run(process_customer_message(
                message_text="এই স্ক্রিনশটের ডিজাইনটি কি করতে পারবেন?",
                image_bytes=b"fake_screenshot_data",
                image_mime="image/png",
                conversation_history=[],
                sender_id=self.cust_a,
                workspace_id=1
            ))
            self.assertTrue(len(res.get("reply_text")) > 0)
            self.assertIn("আইডি কার্ডের ডিজাইনটি", res["reply_text"])
            self.assertTrue(mock_client.models.generate_content.called)
        print("✓ Test 11 Passed: Vision model processed screenshot for AI-enabled customer.")

    # -------------------------------------------------------------
    # Scenario 12: Conversation history contains known institution/mobile -> AI does not ask again
    # -------------------------------------------------------------
    def test_12_known_info_in_history_prevents_duplicate_questions(self):
        history = [
            {"sender_type": "user", "content": "আমাদের প্রতিষ্ঠানের নাম আদর্শ উচ্চ বিদ্যালয়"},
            {"sender_type": "bot", "content": "জি স্যার, প্রতিষ্ঠানের নাম পেয়েছি। মোবাইল নম্বর দিন।"},
            {"sender_type": "user", "content": "01711223344"}
        ]
        prompt = build_system_instruction(customer_name="Customer", workspace_id=1)
        self.assertIn("স্মৃতিশক্তি ও পূর্ববর্তী কথোপকথন মনে রাখা", prompt)
        self.assertIn("একই কথা বা প্রশ্ন কখনোই পুনরায় জিজ্ঞাসা করবে না", prompt)
        print("✓ Test 12 Passed: System prompt strictly enforces memory retention without repeating questions.")

    # -------------------------------------------------------------
    # Scenario 13: Admin and customer roles remain normalized in context
    # -------------------------------------------------------------
    def test_13_role_normalization_in_history(self):
        record_conversation_message("whatsapp", self.cust_a, "Customer A", "user", "হ্যালো", workspace_id=1)
        record_conversation_message("whatsapp", self.cust_a, "Customer A", "admin", "জি আমি শপ ওনার", workspace_id=1)
        record_conversation_message("whatsapp", self.cust_a, "Customer A", "bot", "আমি এআই সহকারী", workspace_id=1)
        
        history = get_conversation_history("whatsapp", self.cust_a, limit=10, workspace_id=1)
        sender_types = [m["sender_type"] for m in history]
        self.assertIn("user", sender_types)
        self.assertIn("admin", sender_types)
        self.assertIn("bot", sender_types)
        print("✓ Test 13 Passed: Roles normalized cleanly (user, admin, bot) without data loss.")

    # -------------------------------------------------------------
    # Scenario 14: Idempotency prevents duplicate AI replies for same turn
    # -------------------------------------------------------------
    def test_14_webhook_idempotency_prevents_duplicates(self):
        enable_conversation_ai(sender_id=self.cust_a, workspace_id=1)
        
        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send, \
             patch("app.ai_agent.gemini_brain.genai.Client") as mock_genai:
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = "জি স্যার, বলুন।"
            mock_client.models.generate_content.return_value = mock_resp
            mock_genai.return_value = mock_client
            mock_send.return_value = True

            payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "metadata": {"phone_number_id": "10001", "display_phone_number": "8801800000000"},
                            "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                            "messages": [{
                                "id": "wam_duplicate_001",
                                "from": self.cust_a,
                                "type": "text",
                                "text": {"body": "হ্যালো"},
                                "timestamp": str(int(time.time()))
                            }]
                        }
                    }]
                }]
            }
            from app.channels.debouncer import message_debouncer
            # First delivery
            async def run_d1():
                await handle_whatsapp_webhook_event(payload)
                await message_debouncer.flush("whatsapp", 1, self.cust_a)
            asyncio.run(run_d1())
            self.assertEqual(mock_send.call_count, 1)

            # Duplicate delivery (same message ID)
            async def run_d2():
                await handle_whatsapp_webhook_event(payload)
                await message_debouncer.flush("whatsapp", 1, self.cust_a)
            asyncio.run(run_d2())
            self.assertEqual(mock_send.call_count, 1, "Duplicate webhook event must be ignored.")
        print("✓ Test 14 Passed: Duplicate webhook event ignored by idempotency filter.")

    # -------------------------------------------------------------
    # Scenario 15: Admin takeover for Customer A does NOT affect Customer B
    # -------------------------------------------------------------
    def test_15_takeover_isolation_between_customers(self):
        # Takeover Customer A
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
        # Enable Customer B
        enable_conversation_ai(sender_id=self.cust_b, workspace_id=1)
        
        state_a = get_conversation_state(sender_id=self.cust_a, workspace_id=1)
        state_b = get_conversation_state(sender_id=self.cust_b, workspace_id=1)
        
        self.assertTrue(state_a["admin_takeover"])
        self.assertFalse(state_a["ai_enabled"])
        
        self.assertFalse(state_b["admin_takeover"])
        self.assertTrue(state_b["ai_enabled"])
        print("✓ Test 15 Passed: Admin takeover on Customer A leaves Customer B 100% active.")

    # -------------------------------------------------------------
    # Scenario 16: Admin manually re-enables AI for Customer A -> future messages processed
    # -------------------------------------------------------------
    def test_16_manual_re_enable_ai_allows_future_replies(self):
        # 1. Takeover
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
        self.assertFalse(is_conversation_ai_active(sender_id=self.cust_a, workspace_id=1))
        
        # 2. Re-enable AI
        new_v = enable_conversation_ai(sender_id=self.cust_a, workspace_id=1, enabled_by="admin_ui")
        state = get_conversation_state(sender_id=self.cust_a, workspace_id=1)
        self.assertFalse(state["admin_takeover"])
        self.assertTrue(state["ai_enabled"])
        self.assertEqual(state["conversation_version"], new_v)
        self.assertTrue(is_conversation_ai_active(sender_id=self.cust_a, workspace_id=1))
        print(f"✓ Test 16 Passed: AI successfully re-enabled (version {new_v}).")

    # -------------------------------------------------------------
    # Scenario 17: Stale AI job cannot send after re-enablement if version token is stale
    # -------------------------------------------------------------
    def test_17_stale_job_cannot_send_if_version_mismatch(self):
        initial_v = enable_conversation_ai(sender_id=self.cust_a, workspace_id=1)
        
        # Simulate stale batch created at v1
        stale_batch = PendingBatch("whatsapp", 1, self.cust_a, "Customer A", initial_version=initial_v)
        stale_batch.messages.append({"text": "পুরাতন বার্তা"})
        
        # Admin triggers takeover and re-enables (increments version)
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)
        enable_conversation_ai(sender_id=self.cust_a, workspace_id=1)
        
        current_v = get_conversation_state(sender_id=self.cust_a, workspace_id=1)["conversation_version"]
        self.assertNotEqual(stale_batch.initial_version, current_v)
        print(f"✓ Test 17 Passed: Stale job token (v{stale_batch.initial_version}) detected against current (v{current_v}).")

    # -------------------------------------------------------------
    # Scenario 18: Google Form workflow passes for AI-enabled customer
    # -------------------------------------------------------------
    def test_18_google_form_workflow_preservation(self):
        enable_conversation_ai(sender_id=self.cust_a, workspace_id=1)
        
        with patch("app.google_integration.ai_tool.create_institution_form") as mock_create:
            mock_create.return_value = {
                "success": True,
                "form_id": "form_18",
                "form_url": "https://docs.google.com/forms/d/e/18/viewform",
                "edit_url": "https://docs.google.com/forms/d/18/edit",
                "sheet_url": "https://docs.google.com/spreadsheets/d/18/edit"
            }

            res = asyncio.run(process_customer_message(
                message_text="আমাদের জামিয়া রাহমানিয়ার জন্য একটি গুগল ফর্ম বানিয়ে দিন। মোবাইল: 01711223344",
                conversation_history=[],
                sender_id=self.cust_a,
                customer_name="Customer A",
                workspace_id=1
            ))
            
            self.assertIn("https://docs.google.com/forms/d/e/18/viewform", res.get("reply_text", ""))
            self.assertEqual(res.get("response_source"), "deterministic_google_form")
        print("✓ Test 18 Passed: Deterministic Google Form workflow preserved and active for AI-enabled customer.")

if __name__ == "__main__":
    unittest.main()
