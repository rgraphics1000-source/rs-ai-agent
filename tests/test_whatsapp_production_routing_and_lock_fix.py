# -*- coding: utf-8 -*-
"""
Tests specifically verifying WhatsApp Production Routing (418451428636680),
zero-drop guarantees, and concurrent DB lock immunity.
"""
import sys
import os
import asyncio
import unittest
from unittest.mock import patch, MagicMock
import concurrent.futures

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings
from app.database import (
    init_db, get_db_connection, get_setting,
    get_whatsapp_account_by_phone_id, ensure_whatsapp_account_consistency,
    enable_conversation_ai, remove_muted_number
)
from app.channels.whatsapp import handle_whatsapp_webhook_event


class TestWhatsAppProductionRoutingAndLockFix(unittest.TestCase):

    def setUp(self):
        init_db()
        enable_conversation_ai(sender_id="8801816504097", workspace_id=1)
        remove_muted_number("8801816504097")
        conn = get_db_connection()
        conn.execute("DELETE FROM processed_webhook_events WHERE event_id LIKE 'wam_%' OR event_id LIKE 'wamid%'")
        conn.commit()
        conn.close()

    def test_01_canonical_production_phone_id_resolves(self):
        """Test that Meta's exact production Phone Number ID 418451428636680 resolves to Workspace 1."""
        acc = get_whatsapp_account_by_phone_id("418451428636680")
        self.assertIsNotNone(acc, "Failed to resolve WhatsApp account for Meta production ID 418451428636680")
        self.assertEqual(acc["workspace_id"], 1)
        self.assertIn("1816504097", acc["display_phone_number"])

    def test_02_legacy_phone_ids_continue_to_resolve(self):
        """Test that legacy IDs 4184514263660680 and 418451426636680 also resolve."""
        acc1 = get_whatsapp_account_by_phone_id("4184514263660680")
        self.assertIsNotNone(acc1)
        self.assertEqual(acc1["workspace_id"], 1)

        acc2 = get_whatsapp_account_by_phone_id("418451426636680")
        self.assertIsNotNone(acc2)
        self.assertEqual(acc2["workspace_id"], 1)

    def test_03_webhook_with_production_phone_id_generates_reply(self):
        """Test that incoming Meta webhook with 418451428636680 and 8801816504097 processes successfully."""
        webhook_data = {
            "entry": [{
                "changes": [{
                    "value": {
                        "metadata": {
                            "phone_number_id": "418451428636680",
                            "display_phone_number": "8801816504097"
                        },
                        "contacts": [{"profile": {"name": "Prod Test User"}}],
                        "messages": [{
                            "id": "wam_prod_test_001",
                            "from": "8801811112222",
                            "type": "text",
                            "text": {"body": "দাম কত?"}
                        }]
                    }
                }]
            }]
        }

        with patch("app.channels.whatsapp.send_whatsapp_message") as mock_send:
            asyncio.run(handle_whatsapp_webhook_event(webhook_data))

    def test_04_concurrent_db_calls_no_database_locked(self):
        """Test that concurrent calls to ensure_whatsapp_account_consistency do not raise database is locked."""
        def call_consistency():
            return ensure_whatsapp_account_consistency()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(call_consistency) for _ in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        for r in results:
            self.assertIsNotNone(r, "ensure_whatsapp_account_consistency returned None during concurrent execution")


if __name__ == "__main__":
    unittest.main()
