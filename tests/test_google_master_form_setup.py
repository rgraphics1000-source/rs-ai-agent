"""
Test Suite: Master Google Form Setup, Selection, Verification & Workspace Isolation
Validates:
1. Not-connected and not-configured clean status messages (no fake data).
2. Master Form creation via Google Drive folder scoping and Google Forms API.
3. Master Form selection and live verification (File Upload question check & Sheets binding).
4. Multi-Tenant isolation of Master Form templates and connection metadata.
"""

import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import (
    save_google_connection, delete_google_connection, get_google_connection,
    save_master_form_template, get_master_form_templates, update_google_master_ids
)
from app.google_integration.crypto import encrypt_token

class TestGoogleMasterFormSetup(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.ws1 = 801
        self.ws2 = 802
        # Clean test workspaces
        delete_google_connection(self.ws1)
        delete_google_connection(self.ws2)

    def tearDown(self):
        delete_google_connection(self.ws1)
        delete_google_connection(self.ws2)

    def test_01_status_when_not_connected_and_not_configured(self):
        """Verifies clean, non-fake status when no account is connected."""
        res = self.client.get(f"/api/google/status?workspace_id={self.ws1}")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertFalse(data["connected"])
        self.assertEqual(data["connection_message"], "Google Account is not connected.")
        self.assertEqual(data["master_status"], "not_configured")
        self.assertEqual(data["master_message"], "Master Form is not configured.")
        self.assertIsNone(data["master_form_id"])
        self.assertIsNone(data["google_account_email"])
        print("✓ Clean not-connected and not-configured status verified without fake data.")

    def test_02_status_when_connected_without_master_form(self):
        """Verifies status when Google account is connected but Master Form is not yet configured."""
        save_google_connection(
            workspace_id=self.ws1,
            google_account_email="test.user@gmail.com",
            access_token_encrypted=encrypt_token("ya29.mock_token_801"),
            refresh_token_encrypted=encrypt_token("1//mock_refresh_801"),
            status="connected"
        )

        res = self.client.get(f"/api/google/status?workspace_id={self.ws1}")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data["connected"])
        self.assertEqual(data["connection_message"], "Google Account is connected.")
        self.assertEqual(data["masked_email"], "te***r@gmail.com")
        self.assertEqual(data["master_status"], "not_configured")
        self.assertEqual(data["master_message"], "Master Form is not configured.")
        self.assertIsNone(data["master_form_id"])
        print("✓ Connected status accurately indicates Master Form is not configured.")

    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.drive_service.get_drive_client")
    @patch("app.google_integration.sheets_service.get_sheets_client")
    def test_03_create_master_form_template_endpoint(self, mock_sheets, mock_drive, mock_forms):
        """Verifies creating a Master Form template in Google Drive."""
        save_google_connection(
            workspace_id=self.ws1,
            google_account_email="admin@school.com",
            access_token_encrypted=encrypt_token("ya29.mock_801"),
            refresh_token_encrypted=encrypt_token("1//mock_801"),
            status="connected"
        )

        # Mock Drive folder search & creation
        mock_drive.return_value.files.return_value.list.return_value.execute.return_value = {"files": []}
        mock_drive.return_value.files.return_value.create.return_value.execute.return_value = {"id": "folder_master_templates_801"}
        mock_drive.return_value.files.return_value.update.return_value.execute.return_value = {"id": "form_master_801"}

        # Mock Forms API creation & batchUpdate
        mock_forms.return_value.forms.return_value.create.return_value.execute.return_value = {
            "formId": "form_master_801",
            "responderUri": "https://docs.google.com/forms/d/e/form_master_801/viewform"
        }
        mock_forms.return_value.forms.return_value.batchUpdate.return_value.execute.return_value = {"formId": "form_master_801"}
        mock_forms.return_value.forms.return_value.get.return_value.execute.return_value = {
            "formId": "form_master_801",
            "responderUri": "https://docs.google.com/forms/d/e/form_master_801/viewform",
            "info": {"title": "ID Card Information Form"}
        }

        # Mock Sheets API creation
        mock_sheets.return_value.spreadsheets.return_value.create.return_value.execute.return_value = {
            "spreadsheetId": "sheet_master_801",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet_master_801/edit"
        }

        payload = {
            "workspace_id": self.ws1,
            "title": "ID Card Information Form",
            "description": "অনুগ্রহ করে সকল তথ্য সঠিকভাবে পূরণ করুন।"
        }
        res = self.client.post("/api/google/master-forms/create-template", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data["success"])
        self.assertEqual(data["form_id"], "form_master_801")
        self.assertEqual(data["form_name"], "ID Card Information Form")
        self.assertIn("docs.google.com/forms/d/form_master_801/edit", data["edit_url"])
        self.assertEqual(data["spreadsheet_id"], "sheet_master_801")

        # Verify status endpoint reflects newly created master form
        status_res = self.client.get(f"/api/google/status?workspace_id={self.ws1}")
        status_data = status_res.json()
        self.assertEqual(status_data["master_status"], "configured")
        self.assertEqual(status_data["master_form_id"], "form_master_801")
        print("✓ Master Form creation and automatic configuration verified.")

    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.drive_service.get_drive_client")
    @patch("app.google_integration.sheets_service.get_sheets_client")
    def test_04_select_and_verify_master_form_with_file_upload(self, mock_sheets, mock_drive, mock_forms):
        """Verifies selecting an existing Master Form and detecting File Upload question."""
        save_google_connection(
            workspace_id=self.ws1,
            google_account_email="admin@school.com",
            access_token_encrypted=encrypt_token("ya29.mock_801"),
            refresh_token_encrypted=encrypt_token("1//mock_801"),
            status="connected"
        )

        # Mock Drive file verification
        mock_drive.return_value.files.return_value.get.return_value.execute.return_value = {
            "id": "1FAIpQLSc_Real_Master_Form",
            "name": "জামিয়া রাহমানিয়া আরাবিয়া Master ID Form",
            "mimeType": "application/vnd.google-apps.form"
        }
        mock_drive.return_value.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "folder_root"}]}

        # Mock Forms API with real File Upload question item
        mock_forms.return_value.forms.return_value.get.return_value.execute.return_value = {
            "formId": "1FAIpQLSc_Real_Master_Form",
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_Real_Master_Form/viewform",
            "info": {
                "title": "জামিয়া রাহমানিয়া আরাবিয়া Master ID Form",
                "description": "ID Card তৈরির তথ্য ও ছবি প্রদান করুন"
            },
            "items": [
                {"title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"title": "পিতার নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"title": "শিক্ষার্থীর ছবি (পাসপোর্ট সাইজ)", "questionItem": {"question": {"fileUploadQuestion": {"folderId": "drive_folder_123"}}}}
            ]
        }

        # Mock Sheets creation
        mock_sheets.return_value.spreadsheets.return_value.create.return_value.execute.return_value = {
            "spreadsheetId": "sheet_master_real_123",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet_master_real_123/edit"
        }

        select_payload = {
            "workspace_id": self.ws1,
            "master_form_id": "1FAIpQLSc_Real_Master_Form"
        }
        res = self.client.post("/api/google/master-forms/select", json=select_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertTrue(data["success"])
        self.assertEqual(data["master_form_id"], "1FAIpQLSc_Real_Master_Form")
        self.assertEqual(data["master_form_name"], "জামিয়া রাহমানিয়া আরাবিয়া Master ID Form")
        self.assertTrue(data["has_file_upload"])
        self.assertEqual(data["items_count"], 3)

        # Check status endpoint
        status_res = self.client.get(f"/api/google/status?workspace_id={self.ws1}")
        status_data = status_res.json()
        self.assertTrue(status_data["master_has_file_upload"])
        self.assertEqual(status_data["master_form_id"], "1FAIpQLSc_Real_Master_Form")
        print("✓ Master Form selection and File Upload question inspection verified.")

    def test_05_multi_tenant_workspace_isolation_for_master_forms(self):
        """Verifies Workspace 1 and Workspace 2 have completely separate Master Forms."""
        save_google_connection(
            workspace_id=self.ws1,
            google_account_email="ws1@company.com",
            access_token_encrypted=encrypt_token("token_ws1"),
            refresh_token_encrypted=encrypt_token("ref_ws1"),
            status="connected"
        )
        update_google_master_ids(
            workspace_id=self.ws1,
            master_form_id="master_form_ws1",
            master_form_name="WS1 ID Card Form",
            master_has_file_upload=1
        )

        save_google_connection(
            workspace_id=self.ws2,
            google_account_email="ws2@store.com",
            access_token_encrypted=encrypt_token("token_ws2"),
            refresh_token_encrypted=encrypt_token("ref_ws2"),
            status="connected"
        )
        update_google_master_ids(
            workspace_id=self.ws2,
            master_form_id="master_form_ws2",
            master_form_name="WS2 Student Form",
            master_has_file_upload=0
        )

        res1 = self.client.get(f"/api/google/status?workspace_id={self.ws1}").json()
        res2 = self.client.get(f"/api/google/status?workspace_id={self.ws2}").json()

        self.assertEqual(res1["master_form_id"], "master_form_ws1")
        self.assertEqual(res1["master_form_name"], "WS1 ID Card Form")
        self.assertTrue(res1["master_has_file_upload"])

        self.assertEqual(res2["master_form_id"], "master_form_ws2")
        self.assertEqual(res2["master_form_name"], "WS2 Student Form")
        self.assertFalse(res2["master_has_file_upload"])

        self.assertNotEqual(res1["master_form_id"], res2["master_form_id"])
        print("✓ Strict Workspace isolation of Master Form configuration verified.")

if __name__ == "__main__":
    unittest.main()
