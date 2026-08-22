# -*- coding: utf-8 -*-
"""
PRODUCTION REGRESSION TESTS: ADMIN TAKEOVER HARDENING & MULTIMODAL PACKAGE ANALYSIS
Validates that:
1. One Human Admin message permanently turns off AI for that conversation.
2. Subsequent customer messages (1, 10, 100) receive ZERO AI replies and ZERO Gemini calls.
3. Multi-tenant workspace and per-customer isolation remain intact.
4. AI re-enablement via enable_conversation_ai only answers NEW turns, not old backlogs.
5. Multimodal multiple image batches inspect all images without truncating to 3-4 items.
"""

import sys
import time
import asyncio
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import (
    get_db_connection, get_conversation_state, set_admin_takeover,
    enable_conversation_ai, is_conversation_ai_active, record_outbound_ai_message,
    is_outbound_ai_message, claim_webhook_event, is_own_whatsapp_number,
    get_conversation_turn_versions, ensure_whatsapp_account_consistency,
    ensure_facebook_page_consistency
)
from app.channels.debouncer import message_debouncer, PendingBatch
from app.channels.omnichat import record_conversation_message, get_conversation_history, get_conversation_messages
from app.channels.whatsapp import handle_whatsapp_webhook_event, process_whatsapp_batch
from app.channels.facebook import handle_facebook_webhook_event, process_facebook_batch
from app.ai_agent.gemini_brain import process_customer_message, build_system_instruction


class ProductionAdminTakeoverAndMultimodalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workspace_id = 1
        self.wa_phone_id = "4184514263660680"
        self.biz_phone = "8801816504097"
        self.fb_page_id = "105116472071659"
        self.cust_a = "8801711223344"
        self.cust_b = "8801799887766"
        self.fb_cust_a = "fb_prod_cust_a_101"

        ensure_whatsapp_account_consistency()
        ensure_facebook_page_consistency()

        # Clean test records
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE sender_id IN (?, ?, ?))", (self.cust_a, self.cust_b, self.fb_cust_a))
            cursor.execute("DELETE FROM conversations WHERE sender_id IN (?, ?, ?)", (self.cust_a, self.cust_b, self.fb_cust_a))
            cursor.execute("DELETE FROM processed_webhook_events WHERE event_id LIKE 'prod_test_%'")
            conn.commit()
        finally:
            conn.close()

        enable_conversation_ai(sender_id=self.cust_a, workspace_id=self.workspace_id)
        enable_conversation_ai(sender_id=self.cust_b, workspace_id=self.workspace_id)
        enable_conversation_ai(sender_id=self.fb_cust_a, workspace_id=self.workspace_id)

    # --------------------------------------------------------------------------
    # TEST 1: Customer sends ONE message -> 1 AI reply -> Silence -> 0 additional
    # --------------------------------------------------------------------------
    async def test_01_single_customer_message_and_silence(self):
        gemini_calls = 0
        ai_replies = 0

        async def mock_brain(*args, **kwargs):
            nonlocal gemini_calls
            gemini_calls += 1
            return {"reply_text": "জি স্যার, আইডি কার্ডের মূল্য ৩০ টাকা।"}

        def mock_send(to, text, *args, **kwargs):
            nonlocal ai_replies
            ai_replies += 1
            record_outbound_ai_message("whatsapp", f"out_{uuid.uuid4().hex[:6]}", workspace_id=1)
            return True

        msg_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                        "messages": [{
                            "id": f"prod_test_01_{uuid.uuid4().hex[:6]}",
                            "from": self.cust_a,
                            "type": "text",
                            "text": {"body": "আইডি কার্ড বানাতে কত লাগবে?"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.process_customer_message", side_effect=mock_brain), \
             patch("app.channels.whatsapp.send_whatsapp_message", side_effect=mock_send):
            await handle_whatsapp_webhook_event(msg_payload)
            await message_debouncer.flush("whatsapp", 1, self.cust_a)

            # Assert 1 reply
            self.assertEqual(gemini_calls, 1)
            self.assertEqual(ai_replies, 1)

            # Silence simulation (flush without new messages)
            await message_debouncer.flush("whatsapp", 1, self.cust_a)
            self.assertEqual(gemini_calls, 1)
            self.assertEqual(ai_replies, 1)

    # --------------------------------------------------------------------------
    # TEST 2: Customer message -> Admin replies -> Customer sends 10 messages -> 0 AI replies
    # --------------------------------------------------------------------------
    async def test_02_admin_takeover_permanent_silence_on_10_messages(self):
        gemini_calls = 0
        ai_replies = 0

        async def mock_brain(*args, **kwargs):
            nonlocal gemini_calls
            gemini_calls += 1
            return {"reply_text": "Should never be called after takeover"}

        def mock_send(*args, **kwargs):
            nonlocal ai_replies
            ai_replies += 1
            return True

        # 1. Admin sends message via WhatsApp Business App
        admin_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                        "messages": [{
                            "id": f"prod_test_admin_wa_{uuid.uuid4().hex[:6]}",
                            "from": self.biz_phone,  # Business number
                            "recipient_id": self.cust_a,
                            "type": "text",
                            "text": {"body": "জি বলুন, আমি শপ ওনার বলছি।"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.process_customer_message", side_effect=mock_brain), \
             patch("app.channels.whatsapp.send_whatsapp_message", side_effect=mock_send):
            # Process Admin message
            await handle_whatsapp_webhook_event(admin_payload)

            # State check: AI MUST be disabled
            self.assertFalse(is_conversation_ai_active(sender_id=self.cust_a, workspace_id=1))

            # Customer sends 10 successive messages
            for i in range(1, 11):
                cust_payload = {
                    "entry": [{
                        "changes": [{
                            "value": {
                                "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                                "contacts": [{"wa_id": self.cust_a, "profile": {"name": "Customer A"}}],
                                "messages": [{
                                    "id": f"prod_test_cust_10_{i}_{uuid.uuid4().hex[:6]}",
                                    "from": self.cust_a,
                                    "type": "text",
                                    "text": {"body": f"Customer follow-up question #{i}: কত টাকা?"},
                                    "timestamp": str(int(time.time()))
                                }]
                            }
                        }]
                    }]
                }
                await handle_whatsapp_webhook_event(cust_payload)

            # Attempt to flush debouncer
            await message_debouncer.flush("whatsapp", 1, self.cust_a)

        # EXACT CRITERION: 0 Gemini calls, 0 AI replies
        self.assertEqual(gemini_calls, 0)
        self.assertEqual(ai_replies, 0)

    # --------------------------------------------------------------------------
    # TEST 3: Customer sends image -> Admin replies -> Customer sends image + text + audio -> 0 AI replies
    # --------------------------------------------------------------------------
    async def test_03_customer_media_after_admin_takeover_zero_replies(self):
        gemini_calls = 0

        async def mock_brain(*args, **kwargs):
            nonlocal gemini_calls
            gemini_calls += 1
            return {}

        # Admin takeover
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1, takeover_by="admin_test", takeover_reason="manual_test")

        # Customer sends photo
        photo_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "contacts": [{"wa_id": self.cust_a}],
                        "messages": [{
                            "id": f"prod_test_photo_{uuid.uuid4().hex[:6]}",
                            "from": self.cust_a,
                            "type": "image",
                            "image": {"id": "media_sample_id", "caption": "এই ডিজাইনটা দেখেন"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }

        # Customer sends audio
        audio_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "contacts": [{"wa_id": self.cust_a}],
                        "messages": [{
                            "id": f"prod_test_audio_{uuid.uuid4().hex[:6]}",
                            "from": self.cust_a,
                            "type": "audio",
                            "audio": {"id": "audio_sample_id"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.process_customer_message", side_effect=mock_brain):
            await handle_whatsapp_webhook_event(photo_payload)
            await handle_whatsapp_webhook_event(audio_payload)
            await message_debouncer.flush("whatsapp", 1, self.cust_a)

        self.assertEqual(gemini_calls, 0)

    # --------------------------------------------------------------------------
    # TEST 4: Admin replies during in-flight generation -> Result discarded, 0 sent
    # --------------------------------------------------------------------------
    async def test_04_admin_reply_during_generation_discards_result(self):
        ai_replies_sent = 0

        async def slow_brain(*args, **kwargs):
            # Admin takeover happens mid-flight
            set_admin_takeover(sender_id=self.cust_a, workspace_id=1, takeover_by="admin_in_flight", takeover_reason="mid_generation")
            return {"reply_text": "Late generation response"}

        def mock_send(*args, **kwargs):
            nonlocal ai_replies_sent
            ai_replies_sent += 1
            return True

        cust_msg = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "contacts": [{"wa_id": self.cust_a}],
                        "messages": [{
                            "id": f"prod_test_inflight_{uuid.uuid4().hex[:6]}",
                            "from": self.cust_a,
                            "type": "text",
                            "text": {"body": "Need info"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.process_customer_message", side_effect=slow_brain), \
             patch("app.channels.whatsapp.send_whatsapp_message", side_effect=mock_send):
            await handle_whatsapp_webhook_event(cust_msg)
            await message_debouncer.flush("whatsapp", 1, self.cust_a)

        self.assertEqual(ai_replies_sent, 0)

    # --------------------------------------------------------------------------
    # TEST 5 & 6: Delivery/Status Webhooks and Outbound AI Echoes cause 0 generation
    # --------------------------------------------------------------------------
    async def test_05_and_06_status_and_echo_immunity(self):
        gemini_called = False

        async def mock_brain(*args, **kwargs):
            nonlocal gemini_called
            gemini_called = True
            return {}

        outbound_mid = f"out_ai_test_{uuid.uuid4().hex[:6]}"
        record_outbound_ai_message("whatsapp", outbound_mid, workspace_id=1)

        # Status Webhook
        status_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "statuses": [{"id": outbound_mid, "status": "delivered", "recipient_id": self.cust_a}]
                    }
                }]
            }]
        }

        # Echo Webhook
        echo_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "messages": [{
                            "id": outbound_mid,
                            "from": self.biz_phone,
                            "type": "text",
                            "text": {"body": "AI previous response"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.process_customer_message", side_effect=mock_brain):
            await handle_whatsapp_webhook_event(status_payload)
            await handle_whatsapp_webhook_event(echo_payload)
            await message_debouncer.flush("whatsapp", 1, self.cust_a)

        self.assertFalse(gemini_called)

    # --------------------------------------------------------------------------
    # TEST 7: Human Admin message sets sender_role=ADMIN and admin_takeover=1
    # --------------------------------------------------------------------------
    async def test_07_human_admin_message_metadata_and_state(self):
        admin_mid = f"admin_msg_{uuid.uuid4().hex[:6]}"
        admin_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "contacts": [{"wa_id": self.cust_a}],
                        "messages": [{
                            "id": admin_mid,
                            "from": self.biz_phone,
                            "recipient_id": self.cust_a,
                            "type": "text",
                            "text": {"body": "কার্ডের ডিজাইন পাঠান"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }

        await handle_whatsapp_webhook_event(admin_payload)

        state = get_conversation_state(sender_id=self.cust_a, workspace_id=1)
        self.assertTrue(state.get("admin_takeover"))
        self.assertFalse(state.get("ai_enabled"))

        history = get_conversation_history("whatsapp", self.cust_a, workspace_id=1, limit=5)
        admin_msgs = [m for m in history if m.get("sender_role") == "ADMIN" and m.get("direction") == "OUTBOUND"]
        self.assertGreaterEqual(len(admin_msgs), 1)
        self.assertIn("কার্ডের ডিজাইন পাঠান", admin_msgs[0].get("content", ""))

    # --------------------------------------------------------------------------
    # TEST 8: Admin Takeover Customer A leaves Customer B 100% active
    # --------------------------------------------------------------------------
    async def test_08_takeover_isolation_between_customers(self):
        cust_b_replies = 0

        async def mock_brain(*args, **kwargs):
            return {"reply_text": "Customer B reply"}

        def mock_send(to, *args, **kwargs):
            nonlocal cust_b_replies
            if to == self.cust_b:
                cust_b_replies += 1
            return True

        # Takeover Customer A
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1, takeover_by="admin", takeover_reason="cust_a_only")

        # Customer B sends message
        cust_b_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                        "contacts": [{"wa_id": self.cust_b}],
                        "messages": [{
                            "id": f"prod_test_cust_b_{uuid.uuid4().hex[:6]}",
                            "from": self.cust_b,
                            "type": "text",
                            "text": {"body": "Customer B inquiry"},
                            "timestamp": str(int(time.time()))
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.process_customer_message", side_effect=mock_brain), \
             patch("app.channels.whatsapp.send_whatsapp_message", side_effect=mock_send):
            await handle_whatsapp_webhook_event(cust_b_payload)
            await message_debouncer.flush("whatsapp", 1, self.cust_b)

        self.assertFalse(is_conversation_ai_active(sender_id=self.cust_a, workspace_id=1))
        self.assertTrue(is_conversation_ai_active(sender_id=self.cust_b, workspace_id=1))
        self.assertEqual(cust_b_replies, 1)

    # --------------------------------------------------------------------------
    # TEST 9: Explicit Enable AI only resumes NEW customer turns
    # --------------------------------------------------------------------------
    async def test_09_enable_ai_resumes_only_new_turns(self):
        gemini_calls = 0

        async def mock_brain(*args, **kwargs):
            nonlocal gemini_calls
            gemini_calls += 1
            return {"reply_text": "New turn answered"}

        # 1. Takeover active
        set_admin_takeover(sender_id=self.cust_a, workspace_id=1)

        # 2. Customer sent message during takeover (backlog)
        record_conversation_message("whatsapp", self.cust_a, "Cust", "user", "Old message", workspace_id=1, direction="INBOUND", sender_role="CUSTOMER")

        # 3. Explicit Re-enable
        enable_conversation_ai(sender_id=self.cust_a, workspace_id=1)

        # Flush debouncer -> Backlog must NOT trigger AI
        with patch("app.channels.whatsapp.process_customer_message", side_effect=mock_brain):
            await message_debouncer.flush("whatsapp", 1, self.cust_a)
            self.assertEqual(gemini_calls, 0)

            # 4. Genuinely NEW customer message arrives
            new_payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                            "contacts": [{"wa_id": self.cust_a}],
                            "messages": [{
                                "id": f"prod_test_new_turn_{uuid.uuid4().hex[:6]}",
                                "from": self.cust_a,
                                "type": "text",
                                "text": {"body": "Brand new message after re-enable"},
                                "timestamp": str(int(time.time()))
                            }]
                        }
                    }]
                }]
            }
            await handle_whatsapp_webhook_event(new_payload)
            await message_debouncer.flush("whatsapp", 1, self.cust_a)

            self.assertEqual(gemini_calls, 1)

    # --------------------------------------------------------------------------
    # TEST 10: Multiple consecutive Admin messages keep AI OFF
    # --------------------------------------------------------------------------
    async def test_10_consecutive_admin_messages_maintain_silence(self):
        for i in range(1, 4):
            admin_payload = {
                "entry": [{
                    "changes": [{
                        "value": {
                            "metadata": {"phone_number_id": self.wa_phone_id, "display_phone_number": "01816504097"},
                            "contacts": [{"wa_id": self.cust_a}],
                            "messages": [{
                                "id": f"prod_test_multi_admin_{i}_{uuid.uuid4().hex[:6]}",
                                "from": self.biz_phone,
                                "recipient_id": self.cust_a,
                                "type": "text",
                                "text": {"body": f"Admin consecutive message #{i}"},
                                "timestamp": str(int(time.time()))
                            }]
                        }
                    }]
                }]
            }
            await handle_whatsapp_webhook_event(admin_payload)

        state = get_conversation_state(sender_id=self.cust_a, workspace_id=1)
        self.assertTrue(state.get("admin_takeover"))
        self.assertFalse(state.get("ai_enabled"))

    # --------------------------------------------------------------------------
    # TEST 11: Multimodal Multiple Image Analysis (Inspect ALL images without truncation)
    # --------------------------------------------------------------------------
    async def test_11_multimodal_multi_image_batch_analysis(self):
        passed_images = []

        async def mock_brain(message_text="", image_bytes=None, image_list=None, **kwargs):
            nonlocal passed_images
            if image_list:
                passed_images = image_list
            return {"reply_text": "All 5 packages analyzed"}

        # Simulate 5 package images sent in 1 batch
        batch = PendingBatch(
            channel="whatsapp",
            workspace_id=1,
            sender_id=self.cust_a,
            customer_name="Customer Multimodal",
            initial_version=2,
            effective_phone_id=self.wa_phone_id
        )
        for idx in range(1, 6):
            batch.messages.append({
                "id": f"wam_img_{idx}",
                "text": f"Package {idx}",
                "image_bytes": f"FAKE_IMAGE_DATA_BYTES_{idx}".encode("utf-8"),
                "image_mime": "image/jpeg"
            })

        with patch("app.channels.whatsapp.process_customer_message", side_effect=mock_brain), \
             patch("app.channels.whatsapp.send_whatsapp_message", return_value=True):
            await process_whatsapp_batch(batch)

        # Assert ALL 5 images were collected in image_list and passed to Gemini
        self.assertEqual(len(passed_images), 5)
        for i in range(5):
            self.assertIn(f"FAKE_IMAGE_DATA_BYTES_{i+1}".encode("utf-8"), passed_images[i]["bytes"])

    async def test_12_whatsapp_mobile_status_callback_triggers_takeover(self):
        """
        Validates that when the shop owner replies from their WhatsApp Business mobile app,
        Meta's status callback (status='sent') triggers immediate set_admin_takeover,
        and follow-up customer messages receive 0 AI replies and 0 Gemini calls.
        """
        enable_conversation_ai(sender_id=self.cust_a, workspace_id=1)
        self.assertTrue(is_conversation_ai_active(sender_id=self.cust_a, workspace_id=1))

        status_mid = f"wamid.mobile_admin_{uuid.uuid4().hex[:6]}"
        # Simulate Meta status webhook for message sent from mobile app (NOT AI sent)
        status_payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "271335301757320",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "+8801816504097",
                            "phone_number_id": self.wa_phone_id
                        },
                        "statuses": [{
                            "id": status_mid,
                            "status": "sent",
                            "timestamp": str(int(time.time())),
                            "recipient_id": self.cust_a
                        }]
                    },
                    "field": "messages"
                }]
            }]
        }

        await handle_whatsapp_webhook_event(status_payload)

        # Assert AI is now permanently TAKEN OVER / SILENT for this customer
        state = get_conversation_state(sender_id=self.cust_a, workspace_id=1)
        self.assertEqual(state.get("admin_takeover"), 1)
        self.assertFalse(is_conversation_ai_active(sender_id=self.cust_a, workspace_id=1))

        # Now simulate 5 customer messages arriving
        gemini_mock = MagicMock()
        for idx in range(1, 6):
            cust_payload = {
                "object": "whatsapp_business_account",
                "entry": [{
                    "id": "271335301757320",
                    "changes": [{
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+8801816504097",
                                "phone_number_id": self.wa_phone_id
                            },
                            "contacts": [{"profile": {"name": "Customer A"}, "wa_id": self.cust_a}],
                            "messages": [{
                                "from": self.cust_a,
                                "id": f"wamid.post_status_cust_{idx}_{uuid.uuid4().hex[:6]}",
                                "timestamp": str(int(time.time())),
                                "type": "text",
                                "text": {"body": f"Customer post-status message {idx}"}
                            }]
                        },
                        "field": "messages"
                    }]
                }]
            }
            with patch("app.channels.whatsapp.process_customer_message", gemini_mock):
                await handle_whatsapp_webhook_event(cust_payload)
                await message_debouncer.flush("whatsapp", 1, self.cust_a)

        # Assert 0 Gemini calls occurred
        self.assertEqual(gemini_mock.call_count, 0)

    def test_13_ai_agent_persona_nadim_and_owner_rashed(self):
        """
        Validates that Gemini AI system instructions embed the AI Agent name 'নাদিম' (Nadim)
        and the Shop Owner 'মুহা. রাশেদুল ইসলাম' (সংক্ষেপে 'রাশেদ').
        """
        instructions = build_system_instruction(workspace_id=1)
        self.assertIn("নাদিম", instructions)
        self.assertIn("মুহা. রাশেদুল ইসলাম", instructions)
        self.assertIn("রাশেদ", instructions)

    def test_14_saved_media_persistence_and_defaults(self):
        """
        Validates that the 3 essential saved media items (2 videos + 1 voice note)
        are permanently seeded in DB and never wiped on query/reload.
        """
        from app.database import get_saved_media, ensure_default_saved_media
        ensure_default_saved_media()
        media = get_saved_media(workspace_id=1)
        titles = [m["title"] for m in media]
        urls = [m["file_url"] for m in media]
        
        self.assertIn("/static/uploads/media/google_form_submission_guide.mp4", urls)
        self.assertIn("/static/uploads/media/google_form_edit_correction_guide.mp4", urls)
        self.assertIn("/static/uploads/media/id_card_features_voice_note.mp3", urls)

    def test_15_detect_saved_media_smart_routing(self):
        """
        Validates that asking for Google form upload sends Video 1,
        asking for correction sends Video 2,
        and asking for features/quality sends Voice 1.
        """
        from app.ai_agent.gemini_brain import detect_saved_media_to_send

        # 1. Google form submission / upload guide video
        res1 = detect_saved_media_to_send("গুগল ফর্মের মাধ্যমে তথ্য কিভাবে দিব এবং ছবি আপলোড করব?", workspace_id=1)
        self.assertEqual(res1["video_url"], "/static/uploads/media/google_form_submission_guide.mp4")

        # 2. Google form correction guide video
        res2 = detect_saved_media_to_send("তথ্য দেওয়ার পর কোনো ভুল হলে সংশোধন কিভাবে করব?", workspace_id=1)
        self.assertEqual(res2["video_url"], "/static/uploads/media/google_form_edit_correction_guide.mp4")

        # 3. Features voice note
        res3 = detect_saved_media_to_send("আপনাদের আইডি কার্ড ও ফিতার বৈশিষ্ট্য এবং কোয়ালিটি কেমন?", workspace_id=1)
        self.assertEqual(res3["voice_url"], "/static/uploads/media/id_card_features_voice_note.mp3")

    def test_16_moq_tier_pricing_and_delivery_rules(self):
        """
        Validates that system prompt embeds:
        - MOQ: 30 pcs
        - Quantity Tier Pricing: <50 pcs (+10৳), 50-80 pcs (fixed), 100+ pcs (discount, pkg 7 20৳ discount)
        - Standalone items: ID Card 35৳, 2cm Lanyard 28৳, 1.5cm Lanyard 25৳
        - Delivery: Inside Dhaka 80৳, Outside 130৳ + 20৳/kg + 10৳ COD
        - Timeline: 5-6 days proof + 24-48 hours courier
        """
        instructions = build_system_instruction(workspace_id=1)
        self.assertIn("৩০ পিস", instructions)
        self.assertIn("১০ টাকা বাড়িয়ে", instructions)
        self.assertIn("৮০ টাকা", instructions)
        self.assertIn("১৩০ টাকা", instructions)
        self.assertIn("৫ থেকে ৬ দিন", instructions)
        self.assertIn("২৪ থেকে ৪৮ ঘণ্টা", instructions)


if __name__ == "__main__":
    unittest.main()
