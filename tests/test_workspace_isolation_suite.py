# -*- coding: utf-8 -*-
"""
Comprehensive Workspace Isolation & Multi-Tenant Test Suite
Verifies:
1. Workspace Creation & Management
2. AI Training Rules Isolation (W1 vs W2)
3. Product Catalog Isolation (W1 vs W2)
4. FAQ Isolation (W1 vs W2)
5. Customer & Conversation History Isolation (same sender_id across W1 & W2)
6. Order Processing Isolation (W1 vs W2)
7. Facebook Messenger Webhook Strict Routing & No Fallback on Unknown Page ID
8. WhatsApp Webhook Strict Routing & No Fallback on Unknown Phone ID
9. AI System Instruction Leakage Check (W2 prompt must NOT contain RS Graphics)
10. Page 1 / Workspace 1 Zero-Regression Verification
"""

import sys
import os
import json
import uuid
import asyncio
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import (
    init_db, DB_PATH,
    get_all_workspaces, get_workspace, save_workspace, delete_workspace,
    get_workspace_by_page_id, get_workspace_by_phone_id,
    get_connected_page, save_connected_page,
    get_whatsapp_account_by_phone_id, save_whatsapp_account,
    get_active_training_rules, create_training_rule,
    get_faqs, create_faq,
    create_saved_media, get_saved_media,
    get_page_ai_config
)
from app.ai_agent.gemini_brain import (
    get_product_catalog_context,
    build_system_instruction,
    process_customer_message
)
from app.ai_agent.order_engine import (
    create_order,
    list_orders
)
from app.channels.omnichat import (
    record_conversation_message,
    get_conversation_history,
    get_all_conversations
)
from app.channels.facebook import (
    handle_facebook_webhook_event
)
from app.channels.whatsapp import (
    handle_whatsapp_webhook_event
)


class TestWorkspaceIsolationSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        # Ensure Workspace 1 exists
        w1 = get_workspace(1)
        if not w1:
            save_workspace({"id": 1, "name": "RS Graphics", "shop_name": "RS Graphics", "ai_enabled": 1})

    def setUp(self):
        # Create a fresh unique secondary workspace for tests
        uid = uuid.uuid4().hex[:6]
        self.w2_id = save_workspace({
            "name": f"SmartTech Store {uid}",
            "slug": f"smarttech-store-{uid}",
            "shop_name": "স্মার্টটেক গ্যাজেট শপ",
            "shop_phone": "01799887766",
            "shop_address": "মিরপুর ১০, ঢাকা",
            "delivery_inside_dhaka": 60,
            "delivery_outside_dhaka": 120,
            "ai_enabled": 1
        })
        self.assertIsNotNone(self.w2_id)
        self.assertGreater(self.w2_id, 1)

    def tearDown(self):
        # Clean up secondary workspace data
        if self.w2_id and self.w2_id > 1:
            delete_workspace(self.w2_id)

    # -------------------------------------------------------------
    # 1. AI TRAINING RULES ISOLATION
    # -------------------------------------------------------------
    def test_01_ai_training_rules_isolation(self):
        print("\n[TEST 1] AI Training Rules Isolation...")
        # Create a rule in Workspace 2
        r2_id = create_training_rule(
            title="SmartTech Return Policy",
            category="Policy",
            rule_type="instruction",
            question_or_trigger="ওয়ারেন্টি",
            response_or_rule="স্মার্টটেক শপে সকল প্রোডাক্টে ১ বছরের রিপ্লেসমেন্ট ওয়ারেন্টি থাকে।",
            is_active=1,
            workspace_id=self.w2_id
        )

        w1_rules = get_active_training_rules(workspace_id=1)
        w2_rules = get_active_training_rules(workspace_id=self.w2_id)

        w1_rule_texts = " ".join([r.get("response_or_rule", "") for r in w1_rules])
        w2_rule_texts = " ".join([r.get("response_or_rule", "") for r in w2_rules])

        # Workspace 1 rules must NOT contain Workspace 2 warranty text
        self.assertNotIn("স্মার্টটেক শপে", w1_rule_texts, "LEAKAGE: Workspace 1 has Workspace 2 rule!")
        # Workspace 2 rules must contain its own rule
        self.assertIn("স্মার্টটেক শপে", w2_rule_texts, "Workspace 2 should have its own rule")
        print("  -> AI Training Rules are strictly isolated between Workspace 1 and Workspace 2.")

    # -------------------------------------------------------------
    # 2. PRODUCT CATALOG ISOLATION
    # -------------------------------------------------------------
    def test_02_product_catalog_isolation(self):
        print("\n[TEST 2] Product Catalog Isolation...")
        prod_code = f"SW-Z9-{uuid.uuid4().hex[:6]}"
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO products (name, code, category, price, discount_price, stock, is_active, workspace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("Ultra Smartwatch Z9", prod_code, "Smartwatch", 2500, 2200, 15, 1, self.w2_id))
        conn.commit()
        conn.close()

        w1_catalog = get_product_catalog_context(workspace_id=1)
        w2_catalog = get_product_catalog_context(workspace_id=self.w2_id)

        self.assertNotIn("Ultra Smartwatch Z9", w1_catalog, "LEAKAGE: Workspace 1 catalog contains Workspace 2 product!")
        self.assertIn("Ultra Smartwatch Z9", w2_catalog, "Workspace 2 catalog should contain Ultra Smartwatch Z9")
        print("  -> Product catalogs are strictly isolated between Workspace 1 and Workspace 2.")

    # -------------------------------------------------------------
    # 3. FAQ ISOLATION
    # -------------------------------------------------------------
    def test_03_faq_isolation(self):
        print("\n[TEST 3] FAQ Isolation...")
        create_faq("স্মার্টটেকের দোকান কোথায়?", "মিরপুর ১০ গোলচত্বর, ঢাকা", workspace_id=self.w2_id)

        w1_faqs = get_faqs(workspace_id=1)
        w2_faqs = get_faqs(workspace_id=self.w2_id)

        w1_answers = " ".join([f.get("answer", "") for f in w1_faqs])
        w2_answers = " ".join([f.get("answer", "") for f in w2_faqs])

        self.assertNotIn("মিরপুর ১০ গোলচত্বর", w1_answers, "LEAKAGE: Workspace 1 has Workspace 2 FAQ!")
        self.assertIn("মিরপুর ১০ গোলচত্বর", w2_answers, "Workspace 2 should have its FAQ")
        print("  -> FAQs are strictly isolated.")

    # -------------------------------------------------------------
    # 4. CUSTOMER & CONVERSATION HISTORY ISOLATION
    # -------------------------------------------------------------
    def test_04_customer_conversation_history_isolation(self):
        print("\n[TEST 4] Conversation History Isolation for Identical Sender ID...")
        shared_sender_id = f"test_shared_user_{uuid.uuid4().hex[:6]}"

        # Record message for Workspace 1
        record_conversation_message(
            channel="messenger",
            sender_id=shared_sender_id,
            customer_name="Rahim Khan",
            sender_type="user",
            content="আমি আরএস গ্রাফিক্স থেকে আইডি কার্ড বানাতে চাই।",
            workspace_id=1
        )

        # Record message for Workspace 2
        record_conversation_message(
            channel="messenger",
            sender_id=shared_sender_id,
            customer_name="Rahim Khan",
            sender_type="user",
            content="আপনাদের স্মার্টওয়াচের দাম কত?",
            workspace_id=self.w2_id
        )

        w1_history = get_conversation_history("messenger", shared_sender_id, workspace_id=1)
        w2_history = get_conversation_history("messenger", shared_sender_id, workspace_id=self.w2_id)

        w1_texts = " ".join([m.get("content", "") for m in w1_history])
        w2_texts = " ".join([m.get("content", "") for m in w2_history])

        self.assertIn("আইডি কার্ড", w1_texts)
        self.assertNotIn("স্মার্টওয়াচের দাম", w1_texts, "LEAKAGE: Workspace 1 conversation has Workspace 2 message!")

        self.assertIn("স্মার্টওয়াচের দাম", w2_texts)
        self.assertNotIn("আইডি কার্ড বানাতে", w2_texts, "LEAKAGE: Workspace 2 conversation has Workspace 1 message!")
        print("  -> Conversation history for identical sender ID is completely isolated across workspaces.")

    # -------------------------------------------------------------
    # 5. ORDER PROCESSING ISOLATION
    # -------------------------------------------------------------
    def test_05_order_processing_isolation(self):
        print("\n[TEST 5] Order Processing Isolation...")
        # Create order in Workspace 1
        order_w1 = create_order(
            customer_name="Customer W1",
            customer_phone="01711111111",
            customer_address="Dhanmondi, Dhaka",
            items=[{"name": "ID Card", "qty": 1, "price": 150}],
            channel="messenger",
            workspace_id=1
        )

        # Create order in Workspace 2
        order_w2 = create_order(
            customer_name="Customer W2",
            customer_phone="01722222222",
            customer_address="Mirpur, Dhaka",
            items=[{"name": "Smartwatch Z9", "qty": 1, "price": 2200}],
            channel="messenger",
            workspace_id=self.w2_id
        )

        w1_orders = list_orders(workspace_id=1)
        w2_orders = list_orders(workspace_id=self.w2_id)

        w1_codes = [o["order_code"] for o in w1_orders]
        w2_codes = [o["order_code"] for o in w2_orders]

        self.assertIn(order_w1["order_code"], w1_codes)
        self.assertNotIn(order_w2["order_code"], w1_codes, "LEAKAGE: Workspace 1 contains Workspace 2 order!")

        self.assertIn(order_w2["order_code"], w2_codes)
        self.assertNotIn(order_w1["order_code"], w2_codes, "LEAKAGE: Workspace 2 contains Workspace 1 order!")
        print("  -> Orders are strictly scoped and isolated by workspace.")

    # -------------------------------------------------------------
    # 6. FACEBOOK WEBHOOK ROUTING & NO FALLBACK FOR UNKNOWN PAGE
    # -------------------------------------------------------------
    def test_06_facebook_webhook_routing_and_no_fallback(self):
        print("\n[TEST 6] Facebook Messenger Routing & Strict No-Fallback Check...")
        uid = uuid.uuid4().hex[:6]
        p1_id = f"page_fb_1001_{uid}"
        p2_id = f"page_fb_2002_{uid}"

        # Connect page 1 to Workspace 1
        save_connected_page({
            "page_id": p1_id,
            "page_name": "RS Graphics Page",
            "page_access_token": "EAA_TEST_TOKEN_1",
            "workspace_id": 1,
            "is_active": 1
        })
        # Connect page 2 to Workspace 2
        save_connected_page({
            "page_id": p2_id,
            "page_name": "SmartTech Page",
            "page_access_token": "EAA_TEST_TOKEN_2",
            "workspace_id": self.w2_id,
            "is_active": 1
        })

        # Test A: Known Page 1 routes to Workspace 1
        payload_p1 = {
            "object": "page",
            "entry": [{
                "id": p1_id,
                "messaging": [{
                    "sender": {"id": "fb_cust_11"},
                    "recipient": {"id": p1_id},
                    "message": {"mid": "mid.111", "text": "Hello Page 1"}
                }]
            }]
        }
        with patch("app.channels.facebook.send_fb_text_message") as mock_send, \
             patch("app.channels.facebook.process_customer_message") as mock_ai:
            mock_ai.return_value = {"reply": "Hello from W1", "orders": []}
            asyncio.run(handle_facebook_webhook_event(payload_p1))
            self.assertTrue(mock_ai.called)
            # Verify workspace_id passed was 1
            call_kwargs = mock_ai.call_args.kwargs
            self.assertEqual(call_kwargs.get("workspace_id"), 1)

        # Test B: Known Page 2 routes to Workspace 2
        payload_p2 = {
            "object": "page",
            "entry": [{
                "id": p2_id,
                "messaging": [{
                    "sender": {"id": "fb_cust_22"},
                    "recipient": {"id": p2_id},
                    "message": {"mid": "mid.222", "text": "Hello Page 2"}
                }]
            }]
        }
        with patch("app.channels.facebook.send_fb_text_message") as mock_send, \
             patch("app.channels.facebook.process_customer_message") as mock_ai:
            mock_ai.return_value = {"reply": "Hello from W2", "orders": []}
            asyncio.run(handle_facebook_webhook_event(payload_p2))
            self.assertTrue(mock_ai.called)
            # Verify workspace_id passed was w2_id
            call_kwargs = mock_ai.call_args.kwargs
            self.assertEqual(call_kwargs.get("workspace_id"), self.w2_id)

        # Test C: Unknown Page ID must be DROPPED and NOT trigger AI reply
        payload_unknown = {
            "object": "page",
            "entry": [{
                "id": "page_unknown_9999",
                "messaging": [{
                    "sender": {"id": "fb_cust_99"},
                    "recipient": {"id": "page_unknown_9999"},
                    "message": {"mid": "mid.999", "text": "Hello unknown page"}
                }]
            }]
        }
        with patch("app.channels.facebook.send_fb_text_message") as mock_send, \
             patch("app.channels.facebook.process_customer_message") as mock_ai:
            asyncio.run(handle_facebook_webhook_event(payload_unknown))
            # Must NOT call AI reply
            self.assertFalse(mock_ai.called, "CRITICAL ERROR: Unknown Page ID fell back to AI reply!")
            self.assertFalse(mock_send.called, "CRITICAL ERROR: Sent message for unregistered Page ID!")
        print("  -> Facebook Webhook routes accurately to respective workspace and rejects unknown pages without fallback.")

    # -------------------------------------------------------------
    # 7. WHATSAPP WEBHOOK ROUTING & NO FALLBACK FOR UNKNOWN PHONE
    # -------------------------------------------------------------
    def test_07_whatsapp_webhook_routing_and_no_fallback(self):
        print("\n[TEST 7] WhatsApp Routing & Strict No-Fallback Check...")
        import asyncio
        uid = uuid.uuid4().hex[:6]
        phone1_id = f"wa_phone_101_{uid}"
        phone2_id = f"wa_phone_202_{uid}"

        save_whatsapp_account({
            "phone_number_id": phone1_id,
            "account_name": "RS WhatsApp",
            "access_token": "EAA_WA_TOKEN_1",
            "workspace_id": 1,
            "is_active": 1
        })
        save_whatsapp_account({
            "phone_number_id": phone2_id,
            "account_name": "SmartTech WhatsApp",
            "access_token": "EAA_WA_TOKEN_2",
            "workspace_id": self.w2_id,
            "is_active": 1
        })

        # Test A: Known WA Phone 1 routes to Workspace 1
        payload_wa1 = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": phone1_id},
                        "contacts": [{"wa_id": "8801700000001", "profile": {"name": "WA User 1"}}],
                        "messages": [{"id": "wamid.1", "from": "8801700000001", "type": "text", "text": {"body": "Hi WA 1"}}]
                    }
                }]
            }]
        }
        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send, \
             patch("app.channels.whatsapp.process_customer_message") as mock_ai:
            mock_ai.return_value = {"reply": "WA Reply 1", "orders": []}
            asyncio.run(handle_whatsapp_webhook_event(payload_wa1))
            self.assertTrue(mock_ai.called)
            self.assertEqual(mock_ai.call_args.kwargs.get("workspace_id"), 1)

        # Test B: Known WA Phone 2 routes to Workspace 2
        payload_wa2 = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": phone2_id},
                        "contacts": [{"wa_id": "8801700000002", "profile": {"name": "WA User 2"}}],
                        "messages": [{"id": "wamid.2", "from": "8801700000002", "type": "text", "text": {"body": "Hi WA 2"}}]
                    }
                }]
            }]
        }
        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send, \
             patch("app.channels.whatsapp.process_customer_message") as mock_ai:
            mock_ai.return_value = {"reply": "WA Reply 2", "orders": []}
            asyncio.run(handle_whatsapp_webhook_event(payload_wa2))
            self.assertTrue(mock_ai.called)
            self.assertEqual(mock_ai.call_args.kwargs.get("workspace_id"), self.w2_id)

        # Test C: Unknown Phone Number ID must be DROPPED without AI reply
        payload_wa_unknown = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {"phone_number_id": "wa_phone_unknown_999"},
                        "contacts": [{"wa_id": "8801700000009", "profile": {"name": "WA User 9"}}],
                        "messages": [{"id": "wamid.9", "from": "8801700000009", "type": "text", "text": {"body": "Hi unknown"}}]
                    }
                }]
            }]
        }
        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send, \
             patch("app.channels.whatsapp.process_customer_message") as mock_ai:
            asyncio.run(handle_whatsapp_webhook_event(payload_wa_unknown))
            self.assertFalse(mock_ai.called, "CRITICAL ERROR: Unknown Phone ID fell back to AI reply!")
            self.assertFalse(mock_send.called, "CRITICAL ERROR: Sent WhatsApp message for unregistered Phone ID!")
        print("  -> WhatsApp Webhook routes accurately to respective workspace and rejects unknown phone IDs without fallback.")

    # -------------------------------------------------------------
    # 8. LIVE GEMINI SYSTEM INSTRUCTION LEAKAGE CHECK
    # -------------------------------------------------------------
    def test_08_system_instruction_prompt_leakage(self):
        print("\n[TEST 8] System Instruction Prompt Leakage Check...")
        prompt_w1 = build_system_instruction(customer_name="Test Customer", workspace_id=1)
        prompt_w2 = build_system_instruction(customer_name="Test Customer", workspace_id=self.w2_id)

        # Workspace 2 prompt MUST contain its shop name
        self.assertIn("স্মার্টটেক", prompt_w2)
        # Workspace 2 prompt MUST NOT contain RS Graphics, Panjabi, PVC card, or RS contact info
        self.assertNotIn("RS Graphics", prompt_w2, "PROMPT LEAKAGE: Workspace 2 prompt mentions RS Graphics!")
        self.assertNotIn("rsgraphics", prompt_w2.lower(), "PROMPT LEAKAGE: Workspace 2 prompt contains rsgraphics!")
        self.assertNotIn("01867140880", prompt_w2, "PROMPT LEAKAGE: Workspace 2 prompt contains Workspace 1 phone number!")

        # Workspace 1 prompt MUST contain RS Graphics shop name
        self.assertIn("RS Graphics", prompt_w1)
        print("  -> Gemini AI System Instructions are completely isolated with zero prompt bleeding.")

    # -------------------------------------------------------------
    # 9. WORKSPACE 1 / PAGE 1 ZERO-REGRESSION VERIFICATION
    # -------------------------------------------------------------
    def test_09_workspace_1_zero_regression(self):
        print("\n[TEST 9] Page 1 / Workspace 1 Zero-Regression Verification...")
        w1 = get_workspace(1)
        self.assertIsNotNone(w1)
        self.assertIn("RS Graphics", w1["name"])

        # Verify RS Graphics catalog is accessible
        w1_catalog = get_product_catalog_context(workspace_id=1)
        self.assertTrue(len(w1_catalog) > 0, "Workspace 1 product catalog should not be empty")

        # Verify RS Graphics AI training rules are accessible
        w1_rules = get_active_training_rules(workspace_id=1)
        self.assertTrue(len(w1_rules) > 0, "Workspace 1 training rules should not be empty")
        print(f"  -> Workspace 1 has {len(w1_rules)} active training rules and catalog is fully operational.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
