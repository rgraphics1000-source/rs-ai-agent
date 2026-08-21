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

    def test_03_api_remove_muted_contact(self):
        """Tests POST /api/muted-contacts/remove."""
        add_muted_number(self.test_phone)
        resp = self.client.post("/api/muted-contacts/remove", json={"phone": self.test_phone})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        
        # Verify AI is active again
        self.assertTrue(is_conversation_ai_active("01576656763"))
        print("✓ Test 3 Passed: Number successfully unmuted and AI active again.")

if __name__ == "__main__":
    unittest.main()
