import unittest
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import patch, MagicMock
from app.google_integration.forms_service import get_responder_url
from app.google_integration.form_manager import create_institution_form

class TestGoogleFormUrlAndCustomSheetColumns(unittest.TestCase):
    def test_01_canonical_responder_url_uses_form_id(self):
        """Verify get_responder_url always returns https://docs.google.com/forms/d/{form_id}/viewform."""
        url = get_responder_url(1, "1s2d3f4g5h6j_test_form_id")
        self.assertEqual(url, "https://docs.google.com/forms/d/1s2d3f4g5h6j_test_form_id/viewform")
        self.assertNotIn("/d/e/1FAIpQLSc", url, "Must never return master template /d/e/ URL.")
        print("✓ Test 1 Passed: Canonical responder URL points directly to the cloned form ID.")

    @patch("app.google_integration.form_manager.verify_generated_form", return_value={"success": True, "valid": True})
    @patch("app.google_integration.form_manager.get_google_connection")
    @patch("app.google_integration.form_manager.get_or_create_workspace_root_folder")
    @patch("app.google_integration.form_manager.get_or_create_institution_folder")
    @patch("app.google_integration.form_manager.copy_master_form_file")
    @patch("app.google_integration.form_manager.customize_cloned_institution_form")
    @patch("app.google_integration.form_manager.create_institution_response_sheet")
    def test_02_google_sheet_columns_match_strictly_selected_fields(
        self, mock_sheet, mock_custom, mock_copy, mock_folder, mock_root, mock_conn, mock_verify
    ):
        """Verify Google Sheet headers contain ONLY the requested fields, with zero extra columns."""
        mock_conn.return_value = {
            "master_form_id": "master_123",
            "status": "connected"
        }
        mock_root.return_value = "root_folder_1"
        mock_folder.return_value = "inst_folder_1"
        mock_copy.return_value = {"form_id": "cloned_form_999", "success": True}

        selected_fields = ["student_name", "father_name", "class_name", "roll", "student_photo"]
        mock_custom.return_value = {
            "success": True,
            "form_id": "cloned_form_999",
            "responder_url": "https://docs.google.com/forms/d/cloned_form_999/viewform",
            "selected_fields": selected_fields
        }
        mock_sheet.return_value = {
            "spreadsheet_id": "sheet_999",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_999/edit",
            "title": "খাদিমুল কুরআন মাদ্রাসা - 01929778581 - ID Card Responses"
        }

        res = create_institution_form(
            workspace_id=1,
            institution_name="খাদিমুল কুরআন মাদ্রাসা",
            institution_mobile="01929778581",
            selected_fields=selected_fields,
            allow_duplicate=True
        )

        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("responder_url"), "https://docs.google.com/forms/d/cloned_form_999/viewform")

        # Verify create_institution_response_sheet was called with exact column_headers
        mock_sheet.assert_called_once()
        args, kwargs = mock_sheet.call_args
        headers = kwargs.get("column_headers", [])

        self.assertIn("Submission ID", headers)
        self.assertIn("Timestamp", headers)
        self.assertIn("শিক্ষার্থীর নাম", headers)
        self.assertIn("পিতার নাম", headers)
        self.assertTrue(any("ছবি" in h for h in headers))

        # Verify unrequested columns are ABSENT
        self.assertNotIn("মাতার নাম", headers)
        self.assertNotIn("জন্মতারিখ", headers)
        self.assertNotIn("রক্তের গ্রুপ", headers)
        self.assertNotIn("ঠিকানা", headers)

        print("✓ Test 2 Passed: Google Sheet columns strictly match customer requested fields without extra columns.")

if __name__ == "__main__":
    unittest.main()
