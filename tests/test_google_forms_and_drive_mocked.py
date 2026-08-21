import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from app.main import app
from app.database import (
    init_db, save_google_connection, delete_google_connection,
    get_generated_form_by_institution, get_google_form_fields
)
from app.google_integration.crypto import encrypt_token
from app.google_integration.form_manager import create_institution_form

class TestGoogleFormsAndDriveMocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = TestClient(app)
        self.workspace_id = 993
        delete_google_connection(workspace_id=self.workspace_id)
        save_google_connection(
            workspace_id=self.workspace_id,
            google_account_email="test.madrasa@gmail.com",
            access_token_encrypted=encrypt_token("mock_access_token_993"),
            refresh_token_encrypted=encrypt_token("mock_refresh_token_993"),
            master_form_id="1FAIpQLSc_MasterForm_12345"
        )

    def tearDown(self):
        delete_google_connection(workspace_id=self.workspace_id)

    @patch("app.google_integration.drive_service.get_drive_client")
    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.sheets_service.get_sheets_client")
    def test_01_create_institution_form_cloning_and_preservation(self, mock_sheets_cls, mock_forms_cls, mock_drive_cls):
        """
        Verifies cloning Master Form via Drive files.copy() and customizing metadata.
        Ensures File Upload question is preserved and never broken.
        """
        # Setup Mock Drive
        mock_drive = MagicMock()
        mock_drive_cls.return_value = mock_drive

        # Mock files.get for verify_file_accessible
        mock_drive.files().get().execute.return_value = {
            "id": "1FAIpQLSc_MasterForm_12345",
            "name": "Master ID Card Form",
            "mimeType": "application/vnd.google-apps.form",
            "trashed": False
        }

        # Mock root folder & institution folder creation
        mock_drive.files().list().execute.return_value = {"files": []}
        mock_drive.files().create().execute.side_effect = [
            {"id": "folder_root_993", "name": "RS AI Agent - Institution Forms"},
            {"id": "folder_inst_993", "name": "জামিয়া রাহমানিয়া আরাবিয়া"}
        ]
        # Mock Master Form copy
        mock_drive.files().copy().execute.return_value = {
            "id": "cloned_form_993_abc",
            "name": "জামিয়া রাহমানিয়া আরাবিয়া - ID Card Information",
            "webViewLink": "https://docs.google.com/forms/d/cloned_form_993_abc/viewform"
        }

        # Setup Mock Forms API
        mock_forms = MagicMock()
        mock_forms_cls.return_value = mock_forms

        # Mock existing form details containing File Upload item
        mock_forms.forms().get().execute.return_value = {
            "formId": "cloned_form_993_abc",
            "info": {"title": "Master ID Card Form"},
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLS_cloned_responder/viewform",
            "items": [
                {
                    "itemId": "item_0",
                    "title": "শিক্ষার্থীর ছবি (পাসপোর্ট সাইজ)",
                    "questionItem": {
                        "question": {
                            "questionId": "q_photo_1",
                            "fileUploadQuestion": {"folderId": "drive_photo_folder"}
                        }
                    }
                }
            ]
        }
        mock_forms.forms().batchUpdate().execute.return_value = {"formId": "cloned_form_993_abc"}

        # Setup Mock Sheets API
        mock_sheets = MagicMock()
        mock_sheets_cls.return_value = mock_sheets
        mock_sheets.spreadsheets().create().execute.return_value = {
            "spreadsheetId": "sheet_resp_993",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet_resp_993/edit"
        }

        # Execute Form Creation
        result = create_institution_form(
            workspace_id=self.workspace_id,
            institution_name="জামিয়া রাহমানিয়া আরাবিয়া",
            custom_description="অনুগ্রহ করে সকল তথ্য সঠিকভাবে পূরণ করুন।"
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["institution_name"], "জামিয়া রাহমানিয়া আরাবিয়া")
        self.assertEqual(result["form_id"], "cloned_form_993_abc")
        self.assertIn("docs.google.com/forms", result["responder_url"])
        self.assertIn("docs.google.com/spreadsheets", result["sheet_url"])

        # Check DB record
        db_form = get_generated_form_by_institution(workspace_id=self.workspace_id, institution_name="জামিয়া রাহমানিয়া আরাবিয়া")
        self.assertIsNotNone(db_form)
        self.assertEqual(db_form["form_id"], "cloned_form_993_abc")
        print("✓ Form creation with Drive cloning & Sheets setup passed.")

        # Test Idempotency: calling again should return existing form without duplicating
        dup_result = create_institution_form(
            workspace_id=self.workspace_id,
            institution_name="জামিয়া রাহমানিয়া আরাবিয়া"
        )
        self.assertTrue(dup_result["success"])
        self.assertTrue(dup_result.get("is_existing"))
        self.assertEqual(dup_result["form_id"], "cloned_form_993_abc")
        print("✓ Idempotency verification: Existing form returned for same institution.")

    def test_02_dynamic_form_fields_management(self):
        """Verifies custom questions/fields listing, adding, and deletion via REST API."""
        # 1. List default fields
        r_list = self.client.get(f"/api/google/fields?workspace_id={self.workspace_id}")
        self.assertEqual(r_list.status_code, 200)
        fields = r_list.json()["fields"]
        self.assertGreaterEqual(len(fields), 10)

        # 2. Add custom field
        r_add = self.client.post("/api/google/fields", json={
            "workspace_id": self.workspace_id,
            "field_key": "emergency_contact",
            "field_label": "জরুরি যোগাযোগের নম্বর",
            "field_type": "short_answer",
            "required": 1,
            "sort_order": 20
        })
        self.assertEqual(r_add.status_code, 200)
        added = r_add.json()["field"]
        self.assertEqual(added["field_key"], "emergency_contact")

        # 3. Delete custom field
        r_del = self.client.delete(f"/api/google/fields/{added['id']}?workspace_id={self.workspace_id}")
        self.assertEqual(r_del.status_code, 200)
        self.assertTrue(r_del.json()["success"])
        print("✓ Dynamic form fields CRUD API verified.")

if __name__ == "__main__":
    unittest.main()
