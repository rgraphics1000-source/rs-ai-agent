import unittest
import asyncio
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import patch, MagicMock
from app.google_integration.ai_tool import resolve_google_form_workflow
from app.google_integration.form_manager import create_institution_form
from app.database import (
    save_generated_form, save_master_form_template, update_google_master_ids,
    get_generated_forms_by_mobile
)

class TestDataCollectionAndFormIsolation(unittest.TestCase):
    def setUp(self):
        self.ws_id = 1
        # Set a master form template ID
        self.master_form_id = "1ODat2PI-nUgPoAilC3ouHf8Yse0W6Gr6eNKJEwR6a6c"
        update_google_master_ids(
            workspace_id=self.ws_id,
            master_form_id=self.master_form_id,
            master_form_name="Master ID Card Template",
            master_form_url=f"https://docs.google.com/forms/d/{self.master_form_id}/viewform"
        )

    def test_01_data_collection_questions_prioritize_google_form(self):
        """When customer asks how to submit data/photos, Google Form is promoted as #1 priority."""
        test_questions = [
            "তথ্য কিভাবে দিবো",
            "আইডি কার্ডের তথ্য কিভাবে দিব",
            "ছবি ও তথ্য কিভাবে পাঠাব",
            "তথ্য কিভাবে নেন আপনারা?",
            "তথ্য পাঠানোর নিয়ম কি",
            "তথ্য কোথায় জমা দিব"
        ]

        for q in test_questions:
            res = resolve_google_form_workflow(
                user_message=q,
                conversation_history=[],
                customer_phone="01929778581",
                workspace_id=self.ws_id
            )
            self.assertIsNotNone(res, f"Failed for query: {q}")
            reply = res.get("reply", "")
            self.assertIn("গুগল ফর্ম", reply, f"Google Form not found in reply for query: {q}")
            self.assertIn("প্রধান", reply, f"'প্রধান' priority not emphasized for query: {q}")
            self.assertNotIn("মেইল", reply, f"Email/Mail should never be mentioned for query: {q}")
            self.assertNotIn("email", reply.lower(), f"Email should never be mentioned for query: {q}")

        print("✓ Test 1 Passed: All data collection questions prioritize Google Form as #1 and never mention email.")

    @patch("app.google_integration.ai_tool.create_institution_form")
    def test_02_master_form_is_never_returned_as_existing_institution_form(self, mock_create):
        """Master Form ID is strictly isolated and never returned to customers."""
        mock_create.return_value = {
            "success": True,
            "form_id": "cloned_distinct_123",
            "form_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_cloned/viewform",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_cloned/viewform",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_cloned/edit"
        }
        # Accidental master form row saved in generated_forms
        save_generated_form(
            workspace_id=self.ws_id,
            institution_name="মাস্টার ফর্ম টেমপ্লেট",
            institution_mobile="01929778581",
            form_id=self.master_form_id,
            form_url=f"https://docs.google.com/forms/d/{self.master_form_id}/viewform"
        )

        res = resolve_google_form_workflow(
            user_message="আমার গুগল ফরম কোথায়",
            conversation_history=[],
            customer_phone="01929778581",
            workspace_id=self.ws_id
        )
        print("DEBUG test_02 res:", res)

        # Since the only form in DB for this phone is the master form template itself,
        # it should NOT return the master form URL!
        if res:
            self.assertNotIn(self.master_form_id, res.get("form_url", ""))
            self.assertNotIn(self.master_form_id, res.get("reply", ""))
        print("✓ Test 2 Passed: Master Form template ID is strictly excluded from existing form returns.")

    @patch("app.google_integration.form_manager.verify_generated_form", return_value={"success": True, "valid": True})
    @patch("app.google_integration.form_manager.get_or_create_workspace_root_folder", return_value="root_123")
    @patch("app.google_integration.form_manager.get_or_create_institution_folder", return_value="folder_456")
    @patch("app.google_integration.form_manager.save_institution", return_value={"id": 10})
    @patch("app.google_integration.form_manager.copy_master_form_file")
    @patch("app.google_integration.form_manager.customize_cloned_institution_form")
    @patch("app.google_integration.form_manager.create_institution_response_sheet")
    def test_03_cloned_form_creates_new_unique_form_with_responder_url(
        self, mock_sheet, mock_custom, mock_copy, mock_inst, mock_folder, mock_root, mock_verify
    ):
        """When creating a form, a new cloned form ID is generated and returned."""
        cloned_id = "1rMRMmos-MBWXyX2U3NT7IptnofTn7lV7CyN8bsh1r3E"
        mock_copy.return_value = {"form_id": cloned_id, "name": "Cloned Form"}
        mock_custom.return_value = {
            "success": True,
            "form_id": cloned_id,
            "title": "খাদিমুল কুরআন মাদ্রাসা - 01929778581 - ID Card Form",
            "responder_url": f"https://docs.google.com/forms/d/e/1FAIpQLSc_{cloned_id}/viewform",
            "form_url": f"https://docs.google.com/forms/d/e/1FAIpQLSc_{cloned_id}/viewform",
            "edit_url": f"https://docs.google.com/forms/d/{cloned_id}/edit",
            "selected_fields": ["student_name", "father_name", "student_photo"]
        }
        mock_sheet.return_value = {
            "spreadsheet_id": "sheet_123",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_123/edit"
        }

        res = create_institution_form(
            workspace_id=self.ws_id,
            institution_name="খাদিমুল কুরআন মাদ্রাসা",
            institution_mobile="01929778777",
            selected_fields=["student_name", "father_name", "student_photo"],
            allow_duplicate=True
        )

        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("form_id"), cloned_id)
        self.assertEqual(res.get("responder_url"), f"https://docs.google.com/forms/d/e/1FAIpQLSc_{cloned_id}/viewform")
        self.assertNotEqual(res.get("form_id"), self.master_form_id)
        print("✓ Test 3 Passed: Cloned Form creation generated unique cloned form URL without master template pollution.")

if __name__ == "__main__":
    unittest.main()
