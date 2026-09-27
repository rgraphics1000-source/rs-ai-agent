import unittest
import sys
import os

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.database import (
    add_muted_number, remove_muted_number, get_muted_numbers,
    is_conversation_ai_active, get_muted_contacts_detailed
)

class TestMutedContacts(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_phone = "+8801576-656763"
        # Clear test phone
        remove_muted_number(self.test_phone)

    def tearDown(self):
        remove_muted_number(self.test_phone)

    def test_01_api_add_muted_contact(self):
        """Tests POST /api/muted-contacts/add with formatted BD phone number."""
        resp = self.client.post("/api/muted-contacts/add", json={"phone": self.test_phone})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        
        # Verify AI is paused for this number across all format variations
        self.assertFalse(is_conversation_ai_active("01576656763"))
        self.assertFalse(is_conversation_ai_active("8801576656763"))
        self.assertFalse(is_conversation_ai_active("+8801576-656763"))
        print("✓ Test 1 Passed: Number successfully muted and AI paused across all number formats.")

    def test_02_api_get_muted_contacts(self):
        """Tests GET /api/muted-contacts."""
        add_muted_number(self.test_phone)
        resp = self.client.get("/api/muted-contacts")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        phone_list = [c["phone"] for c in data.get("contacts", [])]
        self.assertIn(self.test_phone, phone_list)
        print("✓ Test 2 Passed: Muted contacts list returned successfully.")

    def test_04_api_add_and_remove_facebook_messenger_customer(self):
        """Tests muting and unmuting Facebook Messenger customers (PSID / username)."""
        fb_cust = "fb_cust_messenger_9901"
        try:
            # 1. Add Facebook Customer to mute list
            resp = self.client.post("/api/muted-contacts/add", json={"phone": fb_cust})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data.get("success"))
            
            # Verify AI is paused for this Facebook Messenger customer
            self.assertFalse(is_conversation_ai_active(sender_id=fb_cust, workspace_id=1))
            
            # 2. Check presence in GET /api/muted-contacts
            resp_get = self.client.get("/api/muted-contacts")
            self.assertEqual(resp_get.status_code, 200)
            phones = [c["phone"] for c in resp_get.json().get("contacts", [])]
            self.assertIn(fb_cust, phones)

            # 3. Unmute Facebook Customer
            resp_del = self.client.post("/api/muted-contacts/remove", json={"phone": fb_cust})
            self.assertEqual(resp_del.status_code, 200)
            self.assertTrue(resp_del.json().get("success"))

            # Verify AI is active again for this Facebook Messenger customer
            self.assertTrue(is_conversation_ai_active(sender_id=fb_cust, workspace_id=1))
            print("✓ Test 4 Passed: Facebook Messenger customer successfully muted and unmuted.")
        finally:
            remove_muted_number(fb_cust)

    def test_05_api_toggle_chat_ai_without_status(self):
        """Tests POST /api/omnichat/toggle-ai toggling AI state without explicit status parameter (matching frontend UI)."""
        from app.database import get_db_connection
        test_sender = "8801999998888"
        try:
            # 1. Create a fresh conversation
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (workspace_id, channel, sender_id, customer_name, human_takeover, admin_takeover, ai_enabled)
                VALUES (1, 'whatsapp', ?, 'Test Customer Toggle', 0, 0, 1)
            """, (test_sender,))
            cid = cursor.lastrowid
            conn.commit()
            conn.close()

            # Ensure AI is currently active
            self.assertTrue(is_conversation_ai_active(sender_id=test_sender, workspace_id=1))

            # 2. Toggle AI (admin clicks block/pause button -> sends only conversation_id)
            resp = self.client.post("/api/omnichat/toggle-ai", json={"conversation_id": cid})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("human_takeover"), 1)
            self.assertTrue(data.get("blocked"))

            # Verify AI is now strictly SILENT / BLOCKED
            self.assertFalse(is_conversation_ai_active(sender_id=test_sender, workspace_id=1))

            # 3. Toggle AI again (admin clicks resume button -> sends only conversation_id)
            resp2 = self.client.post("/api/omnichat/toggle-ai", json={"conversation_id": cid})
            self.assertEqual(resp2.status_code, 200)
            data2 = resp2.json()
            self.assertTrue(data2.get("success"))
            self.assertEqual(data2.get("human_takeover"), 0)
            self.assertFalse(data2.get("blocked"))

            # Verify AI is active again
            self.assertTrue(is_conversation_ai_active(sender_id=test_sender, workspace_id=1))
            print("✓ Test 5 Passed: Omnichat AI Toggle correctly inverts state and blocks AI replies without status parameter.")
        finally:
            remove_muted_number(test_sender)
            try:
                conn = get_db_connection()
                conn.cursor().execute("DELETE FROM conversations WHERE sender_id = ?", (test_sender,))
                conn.commit()
                conn.close()
            except Exception:
                pass

    def test_06_debouncer_drops_and_cancels_when_customer_blocked(self):
        """Tests that when a customer is blocked, Debouncer drops incoming messages and cancels active batches."""
        import asyncio
        from app.channels.debouncer import message_debouncer

        test_sender = "8801888887777"
        remove_muted_number(test_sender)

        async def run_check():
            # 1. Initially allowed
            enqueued = await message_debouncer.add_message(
                channel="whatsapp",
                workspace_id=1,
                sender_id=test_sender,
                customer_name="Debounce Test Cust",
                msg_id="test_msg_001",
                text="Hello AI"
            )
            self.assertTrue(enqueued)

            # 2. Block customer via add_muted_number
            add_muted_number(test_sender)

            # Verify batch was cancelled by add_muted_number
            key = message_debouncer._get_key("whatsapp", 1, test_sender)
            self.assertNotIn(key, message_debouncer._batches)

            # 3. Subsequent message attempts are strictly rejected at the debouncer gate
            enqueued_after_block = await message_debouncer.add_message(
                channel="whatsapp",
                workspace_id=1,
                sender_id=test_sender,
                customer_name="Debounce Test Cust",
                msg_id="test_msg_002",
                text="Are you still there?"
            )
            self.assertFalse(enqueued_after_block)

        try:
            asyncio.run(run_check())
            print("✓ Test 6 Passed: Debouncer immediately cancels in-flight batch and rejects messages when customer is blocked.")
        finally:
            remove_muted_number(test_sender)


if __name__ == "__main__":
    unittest.main()
