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


if __name__ == "__main__":
    unittest.main()
