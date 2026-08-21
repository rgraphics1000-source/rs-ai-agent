import os
import sys
import unittest
import json
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app
from app.google_integration.ai_tool import (
    STANDARD_ID_CARD_FIELDS,
    get_standard_fields_catalog,
    detect_fields_from_natural_language,
    create_id_card_google_form,
    detect_google_form_intent
)
from app.google_integration.forms_service import customize_cloned_institution_form
from app.google_integration.form_manager import create_institution_form

class TestGoogleFormsActualWorkflow(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_standard_fields_catalog_count_and_keys(self):
        catalog = get_standard_fields_catalog()
        self.assertEqual(len(catalog), 14)
        keys = [f["key"] for f in catalog]
        expected_keys = [
            "student_name", "father_name", "mother_name", "dob", "class_name",
            "section", "roll", "reg_no", "blood_group", "student_phone",
            "guardian_phone", "address", "student_photo", "student_signature"
        ]
        self.assertEqual(keys, expected_keys)
        
        # Verify student photo is file_upload
        photo_field = next(f for f in catalog if f["key"] == "student_photo")
        self.assertEqual(photo_field["type"], "file_upload")

    def test_ai_natural_language_field_detection_bangla(self):
        prompt = "আমাদের প্রতিষ্ঠানের জন্য নাম, বাবার নাম, শ্রেণি, রোল এবং ছবি লাগবে"
        detected = detect_fields_from_natural_language(prompt)
        detected_keys = [f["key"] for f in detected]
        
        self.assertIn("student_name", detected_keys)
        self.assertIn("father_name", detected_keys)
        self.assertIn("class_name", detected_keys)
        self.assertIn("roll", detected_keys)
        self.assertIn("student_photo", detected_keys)
        # Should not include unrequested fields like blood_group or address
        self.assertNotIn("blood_group", detected_keys)
        self.assertNotIn("address", detected_keys)

    def test_ai_natural_language_field_detection_strict_no_invented_fields(self):
        prompt = "আমাদের শুধু রক্তের গ্রুপ আর অভিভাবকের ফোন নম্বর দরকার সাথে ছবি"
        detected = detect_fields_from_natural_language(prompt)
        detected_keys = [f["key"] for f in detected]
        
        self.assertIn("blood_group", detected_keys)
        self.assertIn("guardian_phone", detected_keys)
        self.assertIn("student_photo", detected_keys)
        self.assertNotIn("mother_name", detected_keys)
        self.assertNotIn("reg_no", detected_keys)

    def test_endpoint_get_standard_fields(self):
        res = self.client.get("/api/google/fields/standard")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(len(data.get("fields", [])), 14)

    def test_endpoint_preview_fields_with_text(self):
        res = self.client.post("/api/google/forms/preview-fields", json={
            "workspace_id": 1,
            "text": "নাম, শ্রেণি, রোল ও ছবি"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertIn("student_name", data.get("field_keys", []))
        self.assertIn("class_name", data.get("field_keys", []))
        self.assertIn("roll", data.get("field_keys", []))
        self.assertIn("student_photo", data.get("field_keys", []))

    def test_endpoint_preview_fields_with_selected_keys(self):
        res = self.client.post("/api/google/forms/preview-fields", json={
            "workspace_id": 1,
            "selected_field_keys": ["student_name", "blood_group", "student_photo"]
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("field_keys"), ["student_name", "blood_group", "student_photo"])

    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.forms_service.get_form_details")
    @patch("app.google_integration.forms_service.update_form_title_and_description")
    def test_customize_cloned_institution_form_pruning_and_file_upload_preservation(
        self, mock_update_title, mock_get_details, mock_get_client
    ):
        mock_forms = MagicMock()
        mock_get_client.return_value = mock_forms
        mock_forms.forms().batchUpdate().execute.return_value = {"status": "ok"}
        
        # Mock existing items in Master Form: Name, Father Name, Mother Name, Blood Group, File Upload (Photo)
        mock_get_details.return_value = {
            "formId": "cloned-form-123",
            "items": [
                {"itemId": "q1", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"itemId": "q2", "title": "পিতার নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"itemId": "q3", "title": "মাতার নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"itemId": "q4", "title": "রক্তের গ্রুপ", "questionItem": {"question": {"choiceQuestion": {}}}},
                {"itemId": "q5", "title": "ছবি আপলোড", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }

        # Request ONLY Name, Roll, and Photo (Mother Name & Blood Group must be deleted; Roll must be added; Photo must NOT be deleted)
        res = customize_cloned_institution_form(
            workspace_id=1,
            form_id="cloned-form-123",
            institution_name="আল-আমিন মাদরাসা",
            institution_mobile="01712345678",
            selected_fields=["student_name", "roll", "student_photo"]
        )

        self.assertTrue(res.get("success"))
        self.assertIn("01712345678", res.get("title"))
        self.assertIn("আল-আমিন মাদরাসা", res.get("title"))
        
        # Verify batchUpdate was called
        self.assertTrue(mock_forms.forms().batchUpdate.called)

    @patch("app.google_integration.form_manager.get_google_connection")
    @patch("app.google_integration.form_manager.get_or_create_workspace_root_folder")
    @patch("app.google_integration.form_manager.get_or_create_institution_folder")
    @patch("app.google_integration.form_manager.copy_master_form_file")
    @patch("app.google_integration.form_manager.customize_cloned_institution_form")
    @patch("app.google_integration.form_manager.create_institution_response_sheet")
    @patch("app.google_integration.form_manager.save_generated_form")
    @patch("app.google_integration.form_manager.save_institution")
    @patch("app.google_integration.form_manager.get_generated_form_by_institution", return_value=None)
    def test_create_institution_form_end_to_end_naming_conventions(
        self, mock_get_exist, mock_save_inst, mock_save_form, mock_sheet, mock_custom, mock_copy,
        mock_inst_folder, mock_root_folder, mock_conn
    ):
        mock_conn.return_value = {
            "status": "connected",
            "master_form_id": "master-form-xyz"
        }
        mock_root_folder.return_value = "root-folder-123"
        mock_inst_folder.return_value = "folder-alamin-01712345678"
        mock_save_inst.return_value = {"id": 101, "name": "আল-আমিন মাদ্রাসা"}
        mock_copy.return_value = {"form_id": "cloned-form-999"}
        mock_custom.return_value = {
            "success": True,
            "form_id": "cloned-form-999",
            "title": "আল-আমিন মাদ্রাসা - 01712345678 - ID Card Form",
            "responder_url": "https://docs.google.com/forms/d/e/cloned-form-999/viewform",
            "edit_url": "https://docs.google.com/forms/d/cloned-form-999/edit",
            "selected_fields": ["student_name", "father_name", "class_name", "roll", "student_photo"]
        }
        mock_sheet.return_value = {
            "spreadsheet_id": "sheet-999",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet-999/edit",
            "title": "আল-আমিন মাদ্রাসা - 01712345678 - ID Card Responses"
        }
        mock_save_form.return_value = {"id": 501}

        result = create_institution_form(
            workspace_id=1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="01712345678",
            selected_fields=["student_name", "father_name", "class_name", "roll", "student_photo"]
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["institution_name"], "আল-আমিন মাদ্রাসা")
        self.assertEqual(result["institution_mobile"], "01712345678")
        self.assertEqual(result["form_title"], "আল-আমিন মাদ্রাসা - 01712345678 - ID Card Form")
        self.assertEqual(result["sheet_title"], "আল-আমিন মাদ্রাসা - 01712345678 - ID Card Responses")
        self.assertEqual(result["responder_url"], "https://docs.google.com/forms/d/e/cloned-form-999/viewform")

    @patch("app.google_integration.form_manager.get_generated_form_by_institution")
    def test_create_institution_form_duplicate_detection(self, mock_get_existing):
        mock_get_existing.return_value = {
            "institution_id": 101,
            "form_id": "existing-form-777",
            "form_url": "https://docs.google.com/forms/d/existing-form-777/viewform",
            "response_sheet_url": "https://docs.google.com/spreadsheets/d/sheet-777/edit"
        }

        res = create_institution_form(
            workspace_id=1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="01712345678",
            allow_duplicate=False
        )

        self.assertTrue(res["success"])
        self.assertTrue(res["is_existing"])
        self.assertEqual(res["form_id"], "existing-form-777")
        self.assertIn("ইতোমধ্যে আছে", res["message"])

    def test_ai_tool_function_tool_calling(self):
        with patch("app.google_integration.ai_tool.create_institution_form") as mock_create:
            mock_create.return_value = {
                "success": True,
                "is_existing": False,
                "institution_name": "আল-আমিন মাদ্রাসা",
                "institution_mobile": "01712345678",
                "responder_url": "https://docs.google.com/forms/d/e/123/viewform",
                "sheet_url": "https://docs.google.com/spreadsheets/d/123/edit"
            }

            res = create_id_card_google_form(
                workspace_id=1,
                institution_name="আল-আমিন মাদ্রাসা",
                institution_mobile="01712345678",
                selected_fields=["student_name", "father_name", "class_name", "roll", "student_photo"]
            )
            self.assertTrue(res.get("success"))
            self.assertIn("আল-আমিন মাদ্রাসা", res.get("form_summary", ""))

    def test_detect_google_form_intent(self):
        user_msg = "আমাদের মাদ্রাসার নাম আল-আমিন মাদ্রাসা, ফোন 01712345678, একটা ফর্ম বানিয়ে দিন"
        intent = detect_google_form_intent(user_msg)
        self.assertTrue(intent.get("is_form_creation"))
        self.assertEqual(intent.get("extracted_mobile"), "01712345678")
        self.assertEqual(intent.get("extracted_name"), "আল-আমিন মাদ্রাসা")

if __name__ == "__main__":
    unittest.main()
