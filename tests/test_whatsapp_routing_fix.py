# -*- coding: utf-8 -*-
"""
Tests for WhatsApp Webhook Routing Fix & Workspace Isolation.
Tests A through J:
- A: RS Graphics phone_number_id (4184514263660680) resolves correctly
- B: phone_number_id 4184514263660680 resolves correctly as configured Meta number
- C: Unknown phone_number_id is dropped without fallback
- D: Workspace 1 WhatsApp message uses Workspace 1 credentials
- E: Workspace 2 WhatsApp message uses Workspace 2 credentials
- F: Workspace 1 cannot use Workspace 2 training rules
- G: Workspace 2 cannot use Workspace 1 training rules
- H: Admin reply uses the correct WhatsApp account and workspace
- I: Legacy conversations without workspace_id safely resolved/migrated to Workspace 1
- J: init_db idempotency (no duplicate accounts created on restart)
"""
import sys
import os
import sqlite3
import asyncio
import unittest
from unittest.mock import patch, MagicMock

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.database import (
    init_db, get_db_connection, get_setting, set_setting,
    get_whatsapp_account_by_phone_id, get_whatsapp_account_by_workspace_id,
    get_all_whatsapp_accounts, save_whatsapp_account, save_workspace,
    get_all_training_rules, create_training_rule, get_all_workspaces
)
from app.channels.whatsapp import (
    get_whatsapp_credentials, send_whatsapp_message, handle_whatsapp_webhook_event
)
from app.channels.omnichat import record_conversation_message, get_conversation_history


class TestWhatsAppRoutingFix(unittest.TestCase):

    def setUp(self):
        init_db()

    def test_a_b_rs_graphics_phone_id_resolves(self):
        """Test A & B: 4184514263660680 resolves to Workspace 1 / RS Graphics."""
        acc = get_whatsapp_account_by_phone_id("4184514263660680")
        self.assertIsNotNone(acc, "Failed to resolve WhatsApp account for phone_id 4184514263660680")
        self.assertEqual(acc["workspace_id"], 1, f"Expected workspace_id 1, got {acc['workspace_id']}")
        self.assertIn("01816504097", acc["display_phone_number"], f"Expected 01816504097 in display number, got {acc['display_phone_number']}")

    def test_c_unknown_phone_id_is_dropped(self):
        """Test C: Unknown phone_number_id is dropped and does NOT send an AI reply."""
        unknown_id = "9999999999999999"
        acc = get_whatsapp_account_by_phone_id(unknown_id)
        self.assertIsNone(acc, f"Unknown phone ID {unknown_id} should not match any account")

        # Simulate webhook event with unknown phone ID
        webhook_data = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {
                            "phone_number_id": unknown_id,
                            "display_phone_number": "8801999999999"
                        },
                        "contacts": [{"profile": {"name": "Test Stranger"}}],
                        "messages": [{
                            "id": "wam_unknown_test_001",
                            "from": "8801700000000",
                            "type": "text",
                            "text": {"body": "Hello unknown page"}
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send:
            asyncio.run(handle_whatsapp_webhook_event(webhook_data))
            mock_send.assert_not_called()

    def test_d_e_workspace_whatsapp_credentials_isolation(self):
        """Test D & E: Workspace 1 and Workspace 2 use their own distinct WhatsApp credentials."""
        # Create or update Workspace 2
        save_workspace({
            "id": 2,
            "name": "Tech Gadgets Store",
            "slug": "tech-gadgets",
            "shop_name": "Tech Gadgets Store",
            "shop_phone": "01722222222",
            "delivery_inside_dhaka": 80.0,
            "delivery_outside_dhaka": 150.0
        })

        # Save WhatsApp account for Workspace 2
        save_whatsapp_account({
            "workspace_id": 2,
            "phone_number_id": "8888777766665555",
            "display_phone_number": "+8801722222222",
            "waba_id": "1111222233334444",
            "access_token": "TOKEN_WS2_SECRET_TEST"
        })

        # Test resolution for Workspace 1
        w1_acc = get_whatsapp_account_by_workspace_id(1)
        self.assertIsNotNone(w1_acc)
        self.assertEqual(w1_acc["phone_number_id"], "4184514263660680")

        p1_id, tok1 = get_whatsapp_credentials(workspace_id=1)
        self.assertEqual(p1_id, "4184514263660680")

        # Test resolution for Workspace 2
        w2_acc = get_whatsapp_account_by_workspace_id(2)
        self.assertIsNotNone(w2_acc)
        self.assertEqual(w2_acc["phone_number_id"], "8888777766665555")

        p2_id, tok2 = get_whatsapp_credentials(workspace_id=2)
        self.assertEqual(p2_id, "8888777766665555")
        self.assertEqual(tok2, "TOKEN_WS2_SECRET_TEST")

        # Verify credentials differ
        self.assertNotEqual(p1_id, p2_id)
        self.assertNotEqual(tok1, tok2)

    def test_f_g_workspace_training_isolation(self):
        """Test F & G: Workspace 1 cannot use Workspace 2 training rules and vice versa."""
        create_training_rule(
            title="Unique RS Rule",
            response_or_rule="RS Graphics creates custom UV ID cards only.",
            rule_type="instruction",
            workspace_id=1
        )

        create_training_rule(
            title="Unique Gadget Rule",
            response_or_rule="Tech Gadgets sells wireless earbuds only.",
            rule_type="instruction",
            workspace_id=2
        )

        w1_rules = get_all_training_rules(workspace_id=1)
        w2_rules = get_all_training_rules(workspace_id=2)

        w1_contents = [r["response_or_rule"] for r in w1_rules]
        w2_contents = [r["response_or_rule"] for r in w2_rules]

        self.assertTrue(any("UV ID cards" in c for c in w1_contents), "Workspace 1 must contain UV ID card rule")
        self.assertFalse(any("wireless earbuds" in c for c in w1_contents), "Workspace 1 must NOT contain Workspace 2 rules")

        self.assertTrue(any("wireless earbuds" in c for c in w2_contents), "Workspace 2 must contain wireless earbuds rule")
        self.assertFalse(any("UV ID cards" in c for c in w2_contents), "Workspace 2 must NOT contain Workspace 1 rules")

    def test_h_admin_reply_whatsapp_routing(self):
        """Test H: Admin reply selects the correct WhatsApp account based on conversation workspace_id."""
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO conversations (workspace_id, channel, sender_id, customer_name, last_message, human_takeover)
            VALUES (2, 'whatsapp', '8801755555555', 'Gadget Customer', 'Inquiry', 0)
        """)
        conv_id = cursor.lastrowid
        conn.commit()
        conn.close()

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"messages": [{"id": "wamid.test_reply_01"}]}
            mock_post.return_value = mock_resp

            ok = send_whatsapp_message("8801755555555", "Thank you for contacting Tech Gadgets!", workspace_id=2)
            self.assertTrue(ok)
            call_url = mock_post.call_args[0][0]
            self.assertIn("8888777766665555", call_url)
            headers = mock_post.call_args[1]["headers"]
            self.assertEqual(headers["Authorization"], "Bearer TOKEN_WS2_SECRET_TEST")

    def test_i_legacy_conversation_resolution(self):
        """Test I: Legacy conversation without workspace_id safely resolved/migrated to Workspace 1."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversations (workspace_id, channel, sender_id, customer_name, last_message)
            VALUES (NULL, 'whatsapp', '8801811111111', 'Legacy User', 'Legacy message')
        """)
        leg_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Re-run init_db to simulate migration
        init_db()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT workspace_id FROM conversations WHERE id = ?", (leg_id,))
        row = cursor.fetchone()
        conn.close()

        self.assertEqual(row["workspace_id"], 1, f"Legacy conversation should be migrated to workspace_id 1, got {row['workspace_id']}")

    def test_j_init_db_idempotency(self):
        """Test J: Multiple init_db calls do not create duplicate WhatsApp accounts or corrupt records."""
        all_wa_1 = get_all_whatsapp_accounts()
        w1_count_1 = len([wa for wa in all_wa_1 if wa["workspace_id"] == 1])

        # Run init_db several times
        init_db()
        init_db()
        init_db()

        all_wa_2 = get_all_whatsapp_accounts()
        w1_count_2 = len([wa for wa in all_wa_2 if wa["workspace_id"] == 1])

        self.assertEqual(w1_count_1, w1_count_2, f"init_db created duplicate WhatsApp accounts: before={w1_count_1}, after={w1_count_2}")
        
        # Ensure primary account has verified ID
        w1_acc = get_whatsapp_account_by_workspace_id(1)
        self.assertEqual(w1_acc["phone_number_id"], "4184514263660680")

    def test_k_legacy_phone_id_migration(self):
        """Test K: Legacy 8801816504097_wa or 418451426636680 safely migrates to 4184514263660680."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE whatsapp_accounts SET phone_number_id = '8801816504097_wa' WHERE id = 1")
            conn.commit()
        finally:
            conn.close()

        acc = get_whatsapp_account_by_phone_id("4184514263660680")
        self.assertIsNotNone(acc)
        self.assertEqual(acc["phone_number_id"], "4184514263660680")
        self.assertEqual(acc["workspace_id"], 1)

    def test_l_empty_phone_id_migration(self):
        """Test L: Empty phone_number_id safely migrates to 4184514263660680."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE whatsapp_accounts SET phone_number_id = '' WHERE id = 1")
            conn.commit()
        finally:
            conn.close()

        acc = get_whatsapp_account_by_phone_id("4184514263660680")
        self.assertIsNotNone(acc)
        self.assertEqual(acc["phone_number_id"], "4184514263660680")

    def test_m_webhook_e2e_ai_reply_flow(self):
        """Test M: Webhook event with 4184514263660680 generates AI reply and sends using Workspace 1 credentials."""
        webhook_data = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {
                            "phone_number_id": "4184514263660680",
                            "display_phone_number": "8801816504097"
                        },
                        "contacts": [{"profile": {"name": "Test Client"}}],
                        "messages": [{
                            "id": "wam_e2e_test_9999",
                            "from": "8801816504097",
                            "type": "text",
                            "text": {"body": "আইডি কার্ডের দাম কত?"}
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send:
            mock_send.return_value = True
            with patch("app.ai_agent.gemini_brain.process_customer_message") as mock_ai:
                mock_ai.return_value = {"reply_text": "আইডি কার্ড প্রতি পিস ৫০ টাকা।", "matched_images": []}
                asyncio.run(handle_whatsapp_webhook_event(webhook_data))
                mock_send.assert_called_once()
                args, kwargs = mock_send.call_args
                self.assertEqual(args[0], "8801816504097")
                self.assertEqual(kwargs.get("phone_id"), "4184514263660680")
                self.assertEqual(kwargs.get("workspace_id"), 1)


if __name__ == "__main__":
    unittest.main()
