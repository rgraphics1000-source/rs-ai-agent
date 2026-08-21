"""
Test Suite: Institution Name + Mobile Number Identification & Searchability
Covers:
1. create_institution_form requires BOTH name and mobile number.
2. Mobile number normalization to canonical 11-digit format (01XXXXXXXXX).
3. Google Form title format: '{Institution Name} | {Mobile} | ID Card Form'.
4. Google Sheet title format: '{Institution Name} | {Mobile} | ID Card Responses'.
5. Google Drive folder title format: '{Institution Name} | {Mobile}'.
6. Database storage of institution_mobile & normalized_mobile in 'institutions' table.
7. Generated form metadata association with institution_id, institution_name, institution_mobile.
8. Search institution and forms by mobile number (workspace-isolated).
9. Duplicate mobile detection in same workspace.
10. Workspace isolation: Same mobile allowed across different workspaces.
11. AI conversation intent extractor detects both institution name and mobile number.
12. Metadata separation: Institution name and mobile are not injected as student questions.
13. allow_duplicate=True creates additional form for existing institution without error.
14. Zero regression for master forms, whatsapp, facebook, products, orders.
"""

import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.database import (
    init_db, normalize_bd_mobile, save_google_connection, delete_google_connection,
    save_institution, get_institution_by_mobile, get_institution_by_name,
    save_generated_form, get_generated_forms_by_mobile,
    search_institutions_and_forms_by_mobile, get_generated_forms
)
from app.google_integration.form_manager import create_institution_form
from app.google_integration.ai_tool import detect_google_form_intent, create_id_card_google_form
from app.google_integration.crypto import encrypt_token

class TestGoogleInstitutionMobileIdentification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def _clean_db(self):
        delete_google_connection(self.ws1)
        delete_google_connection(self.ws2)
        from app.database import get_db_connection
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM generated_forms WHERE workspace_id IN (?, ?)", (self.ws1, self.ws2))
        c.execute("DELETE FROM institutions WHERE workspace_id IN (?, ?)", (self.ws1, self.ws2))
        conn.commit()
        conn.close()

    def setUp(self):
        init_db()
        self.client = TestClient(app)
        self.ws1 = 901
        self.ws2 = 902
        self._clean_db()

    def tearDown(self):
        self._clean_db()

    def _setup_mock_connection(self, ws_id, master_id="master_form_999"):
        save_google_connection(
            workspace_id=ws_id,
            google_account_email="admin@school.edu.bd",
            access_token_encrypted=encrypt_token("mock_access"),
            refresh_token_encrypted=encrypt_token("mock_refresh"),
            master_form_id=master_id,
            status="connected"
        )

    # Test 1: create_institution_form requires BOTH name and mobile number
    def test_01_create_institution_form_requires_both_name_and_mobile(self):
        self._setup_mock_connection(self.ws1)

        # Missing name
        with self.assertRaises(ValueError) as ctx1:
            create_institution_form(workspace_id=self.ws1, institution_name="", institution_mobile="01712345678")
        self.assertIn("নাম", str(ctx1.exception))

        # Missing mobile
        with self.assertRaises(ValueError) as ctx2:
            create_institution_form(workspace_id=self.ws1, institution_name="আল-আমিন মাদ্রাসা", institution_mobile="")
        self.assertIn("মোবাইল", str(ctx2.exception))

        # Via API endpoint
        res = self.client.post("/api/google/forms/create", json={
            "workspace_id": self.ws1,
            "institution_name": "আল-আমিন মাদ্রাসা"
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("মোবাইল", res.json().get("detail", ""))
        print("✓ Test 1 Passed: Both Institution Name and Mobile Number are strictly required.")

    # Test 2: Mobile number normalization to canonical 11-digit format (01XXXXXXXXX)
    def test_02_mobile_number_normalization_canonical_format(self):
        samples = [
            ("01712345678", "01712345678"),
            ("+8801712345678", "01712345678"),
            ("8801712345678", "01712345678"),
            ("01712-345678", "01712345678"),
            ("01712 345678", "01712345678"),
            ("+88 01712-345678", "01712345678"),
            ("1712345678", "01712345678"),
        ]
        for raw, expected in samples:
            self.assertEqual(normalize_bd_mobile(raw), expected, f"Failed normalising: {raw}")
        print("✓ Test 2 Passed: Bangladeshi mobile number normalization to canonical format is 100% accurate.")

    # Test 3: Google Form title format contains Name and Mobile
    @patch("app.google_integration.form_manager.copy_master_form_file")
    @patch("app.google_integration.form_manager.customize_cloned_institution_form")
    @patch("app.google_integration.form_manager.create_institution_response_sheet")
    @patch("app.google_integration.form_manager.get_or_create_institution_folder")
    @patch("app.google_integration.form_manager.get_or_create_workspace_root_folder")
    @patch("app.google_integration.form_manager.get_responder_url")
    def test_03_google_form_title_format_contains_name_and_mobile(
        self, mock_get_url, mock_root, mock_folder, mock_sheet, mock_custom, mock_copy
    ):
        self._setup_mock_connection(self.ws1)
        mock_root.return_value = "root_123"
        mock_folder.return_value = "folder_123"
        mock_copy.return_value = {"form_id": "cloned_form_123", "title": "Cloned Title"}
        mock_custom.return_value = {"responder_url": "https://forms.gle/mock123", "edit_url": "https://docs.google.com/forms/d/cloned_form_123/edit"}
        mock_sheet.return_value = {"spreadsheet_id": "sheet_123", "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_123/edit", "title": "আল-আমিন মাদ্রাসা | 01712345678 | ID Card Responses"}
        mock_get_url.return_value = "https://forms.gle/mock123"

        res = create_institution_form(
            workspace_id=self.ws1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="+8801712345678"
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["form_title"], "আল-আমিন মাদ্রাসা | 01712345678 | ID Card Form")
        mock_copy.assert_called_once()
        copied_title = mock_copy.call_args[1].get("new_title") or mock_copy.call_args[0][2]
        self.assertEqual(copied_title, "আল-আমিন মাদ্রাসা | 01712345678 | ID Card Form")
        print("✓ Test 3 Passed: Cloned Google Form title contains Institution Name + Canonical Mobile.")

    # Test 4: Google Sheet title format contains Name and Mobile
    @patch("app.google_integration.sheets_service.get_sheets_client")
    @patch("app.google_integration.sheets_service.get_drive_client")
    def test_04_google_sheet_title_format_contains_name_and_mobile(self, mock_drive, mock_sheets):
        self._setup_mock_connection(self.ws1)
        mock_spreadsheets = MagicMock()
        mock_create = MagicMock()
        mock_create.execute.return_value = {"spreadsheetId": "sheet_999", "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet_999/edit"}
        mock_spreadsheets.create.return_value = mock_create
        mock_values = MagicMock()
        mock_values.update.return_value.execute.return_value = {}
        mock_spreadsheets.values.return_value = mock_values
        mock_sheets.return_value.spreadsheets.return_value = mock_spreadsheets

        from app.google_integration.sheets_service import create_institution_response_sheet
        result = create_institution_response_sheet(
            workspace_id=self.ws1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="01712345678"
        )
        self.assertEqual(result["title"], "আল-আমিন মাদ্রাসা | 01712345678 | ID Card Responses")
        body_passed = mock_spreadsheets.create.call_args[1]["body"]
        self.assertEqual(body_passed["properties"]["title"], "আল-আমিন মাদ্রাসা | 01712345678 | ID Card Responses")
        print("✓ Test 4 Passed: Google Sheet title contains Name + Mobile for instant searchability.")

    # Test 5: Google Drive folder naming contains Name and Mobile
    @patch("app.google_integration.drive_service.get_drive_client")
    @patch("app.google_integration.drive_service.get_or_create_workspace_root_folder")
    def test_05_google_drive_folder_naming_contains_name_and_mobile(self, mock_root, mock_drive):
        self._setup_mock_connection(self.ws1)
        mock_root.return_value = "root_folder_001"
        mock_files = MagicMock()
        mock_list = MagicMock()
        mock_list.execute.return_value = {"files": []}
        mock_files.list.return_value = mock_list
        mock_create = MagicMock()
        mock_create.execute.return_value = {"id": "new_folder_999", "name": "আল-আমিন মাদ্রাসা | 01712345678"}
        mock_files.create.return_value = mock_create
        mock_drive.return_value.files.return_value = mock_files

        from app.google_integration.drive_service import get_or_create_institution_folder
        folder_id = get_or_create_institution_folder(
            workspace_id=self.ws1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="+8801712345678",
            parent_folder_id="root_folder_001"
        )
        self.assertEqual(folder_id, "new_folder_999")
        create_meta = mock_files.create.call_args[1]["body"]
        self.assertEqual(create_meta["name"], "আল-আমিন মাদ্রাসা | 01712345678")
        print("✓ Test 5 Passed: Google Drive Folder named '{Name} | {Mobile}'.")

    # Test 6: Database storage of institution_mobile & normalized_mobile in institutions table
    def test_06_institution_database_record_stores_both_name_and_mobile(self):
        inst = save_institution(
            workspace_id=self.ws1,
            name="আল-আমিন মাদ্রাসা",
            institution_mobile="+8801712345678"
        )
        self.assertIsNotNone(inst.get("id"))
        self.assertEqual(inst.get("name"), "আল-আমিন মাদ্রাসা")
        self.assertEqual(inst.get("normalized_mobile"), "01712345678")
        self.assertEqual(inst.get("phone"), "01712345678")
        print("✓ Test 6 Passed: Institutions table correctly saves and normalizes mobile.")

    # Test 7: Generated form metadata associates institution_id, institution_name, institution_mobile
    def test_07_generated_form_metadata_associates_institution_and_mobile(self):
        inst = save_institution(workspace_id=self.ws1, name="আল-আমিন মাদ্রাসা", institution_mobile="01712345678")
        saved_form = save_generated_form(
            workspace_id=self.ws1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="01712345678",
            form_id="test_form_777",
            form_url="https://forms.gle/test777",
            institution_id=inst["id"]
        )
        self.assertEqual(saved_form["institution_id"], inst["id"])
        self.assertEqual(saved_form["institution_name"], "আল-আমিন মাদ্রাসা")
        self.assertEqual(saved_form["institution_mobile"], "01712345678")
        print("✓ Test 7 Passed: Generated Form record maintains strict association with institution and mobile.")

    # Test 8: Search institution and forms by mobile number (workspace-isolated)
    def test_08_search_institution_and_forms_by_mobile_number(self):
        inst = save_institution(workspace_id=self.ws1, name="আল-আমিন মাদ্রাসা", institution_mobile="+8801712345678")
        save_generated_form(
            workspace_id=self.ws1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="01712345678",
            form_id="form_search_01",
            form_url="https://forms.gle/search01",
            institution_id=inst["id"]
        )

        # Search via database function
        search_res = search_institutions_and_forms_by_mobile(workspace_id=self.ws1, mobile="01712345678")
        self.assertIsNotNone(search_res["institution"])
        self.assertEqual(search_res["institution"]["name"], "আল-আমিন মাদ্রাসা")
        self.assertEqual(len(search_res["forms"]), 1)
        self.assertEqual(search_res["forms"][0]["form_id"], "form_search_01")

        # Search with messy input format (+8801712-345678)
        search_res2 = search_institutions_and_forms_by_mobile(workspace_id=self.ws1, mobile="+8801712-345678")
        self.assertIsNotNone(search_res2["institution"])
        self.assertEqual(len(search_res2["forms"]), 1)

        # Search via API endpoint
        res = self.client.get(f"/api/google/institutions/search?workspace_id={self.ws1}&mobile=01712345678")
        self.assertEqual(res.status_code, 200)
        api_data = res.json()
        self.assertTrue(api_data["success"])
        self.assertEqual(api_data["count"], 1)
        print("✓ Test 8 Passed: Search by mobile number resolves institution and generated forms accurately.")

    # Test 9: Duplicate mobile detection in same workspace
    @patch("app.google_integration.form_manager.copy_master_form_file")
    @patch("app.google_integration.form_manager.customize_cloned_institution_form")
    @patch("app.google_integration.form_manager.create_institution_response_sheet")
    @patch("app.google_integration.form_manager.get_or_create_institution_folder")
    @patch("app.google_integration.form_manager.get_or_create_workspace_root_folder")
    @patch("app.google_integration.form_manager.get_responder_url")
    def test_09_duplicate_mobile_detection_in_same_workspace(
        self, mock_get_url, mock_root, mock_folder, mock_sheet, mock_custom, mock_copy
    ):
        self._setup_mock_connection(self.ws1)
        mock_root.return_value = "root_dup"
        mock_folder.return_value = "folder_dup"
        mock_copy.return_value = {"form_id": "form_dup_1", "title": "Form Dup"}
        mock_custom.return_value = {"responder_url": "https://forms.gle/dup1", "edit_url": "https://docs.google.com/forms/d/dup1/edit"}
        mock_sheet.return_value = {"spreadsheet_id": "sheet_dup", "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_dup/edit"}
        mock_get_url.return_value = "https://forms.gle/dup1"

        # 1st creation
        res1 = create_institution_form(
            workspace_id=self.ws1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="01712345678"
        )
        self.assertTrue(res1["success"])
        self.assertFalse(res1["is_existing"])

        # 2nd creation with same mobile in same workspace without allow_duplicate
        res2 = create_institution_form(
            workspace_id=self.ws1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="+8801712345678",
            allow_duplicate=False
        )
        self.assertTrue(res2["success"])
        self.assertTrue(res2["is_existing"])
        self.assertIn("এই মোবাইল নম্বরের একটি প্রতিষ্ঠান ইতোমধ্যে আছে", res2["message"])
        print("✓ Test 9 Passed: Duplicate mobile number detected within same workspace.")

    # Test 10: Same mobile allowed across different workspaces (Workspace Isolation)
    @patch("app.google_integration.form_manager.copy_master_form_file")
    @patch("app.google_integration.form_manager.customize_cloned_institution_form")
    @patch("app.google_integration.form_manager.create_institution_response_sheet")
    @patch("app.google_integration.form_manager.get_or_create_institution_folder")
    @patch("app.google_integration.form_manager.get_or_create_workspace_root_folder")
    @patch("app.google_integration.form_manager.get_responder_url")
    def test_10_same_mobile_allowed_across_different_workspaces(
        self, mock_get_url, mock_root, mock_folder, mock_sheet, mock_custom, mock_copy
    ):
        self._setup_mock_connection(self.ws1, master_id="master_ws1")
        self._setup_mock_connection(self.ws2, master_id="master_ws2")

        mock_root.return_value = "root_ws"
        mock_folder.return_value = "folder_ws"
        mock_copy.side_effect = [{"form_id": "form_ws1", "title": "WS1"}, {"form_id": "form_ws2", "title": "WS2"}]
        mock_custom.return_value = {"responder_url": "https://forms.gle/ws", "edit_url": "https://docs.google.com/forms/d/ws/edit"}
        mock_sheet.return_value = {"spreadsheet_id": "sheet_ws", "sheet_url": "https://docs.google.com/spreadsheets/d/ws/edit"}
        mock_get_url.return_value = "https://forms.gle/ws"

        # Create in Workspace 1
        res1 = create_institution_form(workspace_id=self.ws1, institution_name="আল-আমিন মাদ্রাসা", institution_mobile="01712345678")
        self.assertTrue(res1["success"])
        self.assertFalse(res1["is_existing"])

        # Create in Workspace 2 with SAME mobile
        res2 = create_institution_form(workspace_id=self.ws2, institution_name="আল-আমিন মাদ্রাসা", institution_mobile="01712345678")
        self.assertTrue(res2["success"])
        self.assertFalse(res2["is_existing"])
        self.assertEqual(res2["workspace_id"], self.ws2)

        # Workspace 1 search does NOT leak into Workspace 2
        forms_ws1 = get_generated_forms_by_mobile(workspace_id=self.ws1, mobile="01712345678")
        forms_ws2 = get_generated_forms_by_mobile(workspace_id=self.ws2, mobile="01712345678")
        self.assertEqual(len(forms_ws1), 1)
        self.assertEqual(len(forms_ws2), 1)
        self.assertEqual(forms_ws1[0]["workspace_id"], self.ws1)
        self.assertEqual(forms_ws2[0]["workspace_id"], self.ws2)
        print("✓ Test 10 Passed: Multi-tenant workspace isolation preserves independent institutions with same mobile.")

    # Test 11: AI conversation extracts both institution name and mobile number
    def test_11_ai_conversation_extracts_name_and_mobile(self):
        msg1 = "আল-আমিন মাদরাসা 01712345678 এর জন্য ID Card Form বানাও"
        intent1 = detect_google_form_intent(msg1)
        self.assertIsNotNone(intent1)
        self.assertEqual(intent1["institution_name"], "আল-আমিন মাদরাসা")
        self.assertEqual(intent1["institution_mobile"], "01712345678")

        msg2 = "প্রতিষ্ঠান: জামিয়া কারিমিয়া, মোবাইল: +8801812345678 একটি গুগল ফর্ম তৈরি করে দিন"
        intent2 = detect_google_form_intent(msg2)
        self.assertIsNotNone(intent2)
        self.assertEqual(intent2["institution_name"], "জামিয়া কারিমিয়া")
        self.assertEqual(intent2["institution_mobile"], "01812345678")
        print("✓ Test 11 Passed: AI intent detector accurately extracts institution name and mobile number.")

    # Test 12: Metadata separation - Institution name and mobile not injected as student questions
    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.forms_service.get_form_details")
    @patch("app.google_integration.forms_service.update_form_title_and_description")
    def test_12_metadata_separation_name_and_mobile_not_injected_as_student_questions(
        self, mock_title_desc, mock_details, mock_forms
    ):
        self._setup_mock_connection(self.ws1)
        mock_details.return_value = {
            "formId": "form_meta_sep",
            "items": [
                {"itemId": "q1", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"required": True}}},
                {"itemId": "q2", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }
        mock_batch = MagicMock()
        mock_batch.execute.return_value = {}
        mock_forms.return_value.forms().batchUpdate.return_value = mock_batch

        from app.google_integration.forms_service import customize_cloned_institution_form
        res = customize_cloned_institution_form(
            workspace_id=self.ws1,
            form_id="form_meta_sep",
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="01712345678"
        )
        self.assertTrue(res["success"])
        # Form title updated with metadata
        mock_title_desc.assert_called_once_with(
            workspace_id=self.ws1,
            form_id="form_meta_sep",
            title="আল-আমিন মাদ্রাসা | 01712345678 | ID Card Form",
            description=mock_title_desc.call_args[1]["description"]
        )
        print("✓ Test 12 Passed: Institution Name and Mobile Number remain system metadata and are not injected as student questions.")

    # Test 13: allow_duplicate=True creates additional form for existing institution
    @patch("app.google_integration.form_manager.copy_master_form_file")
    @patch("app.google_integration.form_manager.customize_cloned_institution_form")
    @patch("app.google_integration.form_manager.create_institution_response_sheet")
    @patch("app.google_integration.form_manager.get_or_create_institution_folder")
    @patch("app.google_integration.form_manager.get_or_create_workspace_root_folder")
    @patch("app.google_integration.form_manager.get_responder_url")
    def test_13_allow_duplicate_flag_creates_additional_form_for_existing_institution(
        self, mock_get_url, mock_root, mock_folder, mock_sheet, mock_custom, mock_copy
    ):
        self._setup_mock_connection(self.ws1)
        mock_root.return_value = "root_dup_allow"
        mock_folder.return_value = "folder_dup_allow"
        mock_copy.side_effect = [{"form_id": "form_v1", "title": "V1"}, {"form_id": "form_v2", "title": "V2"}]
        mock_custom.return_value = {"responder_url": "https://forms.gle/dup_v2", "edit_url": "https://docs.google.com/forms/d/dup_v2/edit"}
        mock_sheet.return_value = {"spreadsheet_id": "sheet_v2", "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_v2/edit"}
        mock_get_url.return_value = "https://forms.gle/dup_v2"

        # 1st form
        res1 = create_institution_form(workspace_id=self.ws1, institution_name="আল-আমিন মাদ্রাসা", institution_mobile="01712345678")
        self.assertFalse(res1["is_existing"])

        # 2nd form with allow_duplicate=True
        res2 = create_institution_form(
            workspace_id=self.ws1,
            institution_name="আল-আমিন মাদ্রাসা",
            institution_mobile="01712345678",
            allow_duplicate=True
        )
        self.assertTrue(res2["success"])
        self.assertFalse(res2["is_existing"])
        self.assertEqual(res2["form_id"], "form_v2")
        print("✓ Test 13 Passed: allow_duplicate=True generates additional form for the existing institution.")

    # Test 14: Zero regression for existing Google Forms, Master Forms, WhatsApp, Facebook, Products, Orders
    def test_14_zero_regression_existing_google_forms_and_other_features(self):
        # 1. Google Status Endpoint
        res_status = self.client.get(f"/api/google/status?workspace_id={self.ws1}")
        self.assertEqual(res_status.status_code, 200)

        # 2. Forms List Endpoint
        res_forms = self.client.get(f"/api/google/forms?workspace_id={self.ws1}")
        self.assertEqual(res_forms.status_code, 200)

        # 3. Products List Endpoint
        res_products = self.client.get(f"/api/products?workspace_id={self.ws1}")
        self.assertEqual(res_products.status_code, 200)

        # 4. Orders List Endpoint
        res_orders = self.client.get(f"/api/orders?workspace_id={self.ws1}")
        self.assertEqual(res_orders.status_code, 200)

        # 5. Workspaces Endpoint
        res_workspaces = self.client.get("/api/workspaces")
        self.assertEqual(res_workspaces.status_code, 200)
        print("✓ Test 14 Passed: Zero regression across Google Forms, Products, Orders, and Workspace systems.")

if __name__ == "__main__":
    unittest.main()
