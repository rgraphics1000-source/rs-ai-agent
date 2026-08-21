import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database import (
    get_db_connection, save_generated_form,
    save_google_connection,
    get_generated_form_by_institution
)
from app.google_integration.crypto import encrypt_token
from app.google_integration.forms_service import (
    inspect_and_verify_master_form, verify_generated_form
)
from app.google_integration.form_manager import create_institution_form
from app.google_integration.ai_tool import resolve_google_form_workflow


class TestGoogleFormsFileUploadAuditAndVerification(unittest.TestCase):
    """
    Comprehensive test suite for Google Forms File Upload audit and verification:
    Covers all 10 user-mandated test scenarios.
    """

    def setUp(self):
        self.workspace_id = 9981
        self.master_form_id = "master_template_12345"
        self._clean_db()
        self._setup_mock_connection()

    def tearDown(self):
        self._clean_db()

    def _clean_db(self):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM google_connections WHERE workspace_id = ?", (self.workspace_id,))
        c.execute("DELETE FROM generated_forms WHERE workspace_id = ?", (self.workspace_id,))
        c.execute("DELETE FROM institutions WHERE workspace_id = ?", (self.workspace_id,))
        conn.commit()
        conn.close()

    def _setup_mock_connection(self):
        save_google_connection(
            workspace_id=self.workspace_id,
            google_account_email="admin@test.com",
            access_token_encrypted=encrypt_token("mock_access_token"),
            refresh_token_encrypted=encrypt_token("mock_refresh_token"),
            master_form_id=self.master_form_id,
            status="connected"
        )

    # TEST 1: Master Form has File Upload -> PASS
    @patch("app.google_integration.drive_service.verify_file_accessible")
    @patch("app.google_integration.forms_service.get_form_details")
    @patch("app.google_integration.sheets_service.create_institution_response_sheet")
    @patch("app.google_integration.drive_service.get_or_create_workspace_root_folder")
    @patch("app.google_integration.drive_service.get_or_create_institution_folder")
    def test_01_master_form_has_file_upload_passes(
        self, mock_inst_folder, mock_root_folder, mock_sheet, mock_form_details, mock_drive_verify
    ):
        mock_root_folder.return_value = "root_folder_123"
        mock_inst_folder.return_value = "templates_folder_123"
        mock_drive_verify.return_value = (True, {"id": self.master_form_id, "name": "Master Form", "trashed": False})
        mock_form_details.return_value = {
            "formId": self.master_form_id,
            "info": {"title": "Master Form"},
            "responderUri": f"https://docs.google.com/forms/d/e/1FAIpQLSc_master/viewform",
            "items": [
                {"itemId": "q1", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"required": True}}},
                {"itemId": "q2", "title": "ছবি (পাসপোর্ট সাইজ)", "questionItem": {"question": {"fileUploadQuestion": {"folderId": "uf_folder_123"}}}}
            ]
        }
        mock_sheet.return_value = {
            "spreadsheet_id": "sheet_master_123",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_master_123/edit"
        }

        res = inspect_and_verify_master_form(workspace_id=self.workspace_id, form_id=self.master_form_id)
        self.assertTrue(res.get("valid"))
        self.assertTrue(res.get("has_file_upload"))
        print("[PASS] Test 1: Master Form with native File Upload passes inspection and verification.")

    # TEST 2: Generated form missing File Upload -> MUST FAIL verification
    @patch("app.google_integration.drive_service.verify_file_accessible")
    @patch("app.google_integration.forms_service.get_form_details")
    def test_02_generated_form_missing_file_upload_must_fail(
        self, mock_form_details, mock_drive_verify
    ):
        mock_drive_verify.return_value = (True, {"id": "form_missing_upload", "name": "Form No Upload", "trashed": False})
        mock_form_details.return_value = {
            "formId": "form_missing_upload",
            "info": {"title": "Form No Upload"},
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_no_upload/viewform",
            "items": [
                {"itemId": "q1", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"itemId": "q2", "title": "পিতার নাম", "questionItem": {"question": {"textQuestion": {}}}}
            ]
        }

        res = verify_generated_form(
            workspace_id=self.workspace_id,
            form_id="form_missing_upload",
            expected_fields=["student_name", "student_photo"],
            sheet_id="sheet_valid_123",
            sheet_url="https://docs.google.com/spreadsheets/d/sheet_valid_123/edit",
            check_file_upload=True
        )

        self.assertFalse(res.get("success"))
        self.assertFalse(res.get("valid"))
        self.assertEqual(res.get("failure_reason"), "MISSING_FILE_UPLOAD_QUESTION")
        print("[PASS] Test 2: Generated form missing native File Upload question strictly FAILS verification.")

    # TEST 3: Generated form has File Upload and valid folder -> PASS
    @patch("app.google_integration.drive_service.verify_file_accessible")
    @patch("app.google_integration.forms_service.get_form_details")
    def test_03_generated_form_has_file_upload_and_valid_folder_passes(
        self, mock_form_details, mock_drive_verify
    ):
        def drive_verify_side_effect(workspace_id, file_id):
            return True, {"id": file_id, "name": f"File {file_id}", "trashed": False}

        mock_drive_verify.side_effect = drive_verify_side_effect
        mock_form_details.return_value = {
            "formId": "form_valid_123",
            "info": {"title": "Valid Form"},
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_valid/viewform",
            "items": [
                {"itemId": "q1", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"itemId": "q2", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {"folderId": "folder_uf_valid"}}}}
            ]
        }

        res = verify_generated_form(
            workspace_id=self.workspace_id,
            form_id="form_valid_123",
            expected_fields=["student_name", "student_photo"],
            sheet_id="sheet_valid_123",
            sheet_url="https://docs.google.com/spreadsheets/d/sheet_valid_123/edit",
            drive_folder_id="inst_folder_123",
            check_file_upload=True
        )

        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("valid"))
        self.assertTrue(res.get("has_file_upload"))
        self.assertEqual(res.get("upload_folder_id"), "folder_uf_valid")
        print("[PASS] Test 3: Generated form with native File Upload and valid folder PASSES verification.")

    # TEST 4: Generated form has invalid/missing upload folder -> FAIL
    @patch("app.google_integration.drive_service.verify_file_accessible")
    @patch("app.google_integration.forms_service.get_form_details")
    def test_04_generated_form_invalid_upload_folder_fails(
        self, mock_form_details, mock_drive_verify
    ):
        def drive_verify_side_effect(workspace_id, file_id):
            if file_id == "broken_uf_folder":
                return False, {"error": "Folder not found in Google Drive"}
            return True, {"id": file_id, "name": f"File {file_id}", "trashed": False}

        mock_drive_verify.side_effect = drive_verify_side_effect
        mock_form_details.return_value = {
            "formId": "form_broken_folder",
            "info": {"title": "Broken Folder Form"},
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_broken_folder/viewform",
            "items": [
                {"itemId": "q1", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {"folderId": "broken_uf_folder"}}}}
            ]
        }

        res = verify_generated_form(
            workspace_id=self.workspace_id,
            form_id="form_broken_folder",
            expected_fields=["student_photo"],
            sheet_id="sheet_valid_123",
            sheet_url="https://docs.google.com/spreadsheets/d/sheet_valid_123/edit",
            check_file_upload=True
        )

        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("failure_reason"), "INVALID_FILE_UPLOAD_FOLDER")
        print("[PASS] Test 4: Generated form with missing/broken upload folder FAILS verification.")

    # TEST 5: Generated form has no Sheet -> FAIL
    @patch("app.google_integration.drive_service.verify_file_accessible")
    @patch("app.google_integration.forms_service.get_form_details")
    def test_05_generated_form_missing_sheet_fails(
        self, mock_form_details, mock_drive_verify
    ):
        mock_drive_verify.return_value = (True, {"id": "form_123", "name": "Form", "trashed": False})
        mock_form_details.return_value = {
            "formId": "form_123",
            "info": {"title": "Form"},
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_123/viewform",
            "items": [
                {"itemId": "q1", "title": "নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"itemId": "q2", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }

        res = verify_generated_form(
            workspace_id=self.workspace_id,
            form_id="form_123",
            expected_fields=["student_name", "student_photo"],
            sheet_id="",
            sheet_url="",
            check_file_upload=True
        )

        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("failure_reason"), "MISSING_RESPONSE_SHEET")
        print("[PASS] Test 5: Form without response Sheet strictly FAILS verification.")

    # TEST 6: Fake form ID -> FAIL
    @patch("app.google_integration.drive_service.verify_file_accessible")
    def test_06_fake_form_id_fails(self, mock_drive_verify):
        mock_drive_verify.return_value = (False, {"error": "File not found 404"})

        res = verify_generated_form(
            workspace_id=self.workspace_id,
            form_id="fake_fabricated_form_id_999",
            sheet_id="sheet_123",
            sheet_url="https://docs.google.com/spreadsheets/d/sheet_123/edit"
        )

        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("failure_reason"), "FORM_INACCESSIBLE")
        print("[PASS] Test 6: Fake Form ID strictly FAILS verification.")

    # TEST 7: Fake Sheet URL -> FAIL
    @patch("app.google_integration.drive_service.verify_file_accessible")
    @patch("app.google_integration.forms_service.get_form_details")
    def test_07_fake_sheet_url_fails(self, mock_form_details, mock_drive_verify):
        mock_drive_verify.return_value = (True, {"id": "form_123", "name": "Form", "trashed": False})
        mock_form_details.return_value = {
            "formId": "form_123",
            "info": {"title": "Form"},
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_123/viewform",
            "items": [
                {"itemId": "q1", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }

        res = verify_generated_form(
            workspace_id=self.workspace_id,
            form_id="form_123",
            sheet_url="https://fake-link.com/invalid_sheet",
            check_file_upload=True
        )

        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("failure_reason"), "INVALID_SHEET_URL")
        print("[PASS] Test 7: Fake Sheet URL strictly FAILS verification.")

    # TEST 8: Existing invalid form record -> must NOT return success
    @patch("app.google_integration.drive_service.verify_file_accessible")
    def test_08_existing_invalid_form_record_must_not_return_success(self, mock_drive_verify):
        save_generated_form(
            workspace_id=self.workspace_id,
            institution_name="দারুল উলুম মাদ্রাসা",
            institution_mobile="01799887766",
            form_id="stale_broken_form_id",
            form_url="https://docs.google.com/forms/d/stale_broken_form_id/viewform",
            response_sheet_url="https://docs.google.com/spreadsheets/d/stale_sheet/edit"
        )

        mock_drive_verify.return_value = (False, {"error": "File not found (404)"})

        res = resolve_google_form_workflow(
            user_message="আমার গুগল ফরম দেন",
            conversation_history=[],
            customer_phone="01799887766",
            customer_name="",
            workspace_id=self.workspace_id
        )

        self.assertNotEqual(res.get("form_id"), "stale_broken_form_id")
        print("[PASS] Test 8: Existing invalid/broken form record is NOT returned as a successful link.")

    # TEST 9: Existing valid form record -> return existing URLs
    @patch("app.google_integration.drive_service.verify_file_accessible")
    @patch("app.google_integration.forms_service.get_form_details")
    def test_09_existing_valid_form_record_returns_existing_urls(
        self, mock_form_details, mock_drive_verify
    ):
        valid_form_id = "valid_form_id_888"
        valid_resp_url = f"https://docs.google.com/forms/d/e/1FAIpQLSc_{valid_form_id}/viewform"
        valid_sheet_url = "https://docs.google.com/spreadsheets/d/valid_sheet_888/edit"

        save_generated_form(
            workspace_id=self.workspace_id,
            institution_name="দারুল উলুম মাদ্রাসা",
            institution_mobile="01799887766",
            form_id=valid_form_id,
            form_url=valid_resp_url,
            responder_uri=valid_resp_url,
            response_sheet_url=valid_sheet_url
        )

        mock_drive_verify.return_value = (True, {"id": valid_form_id, "name": "Form", "trashed": False})
        mock_form_details.return_value = {
            "formId": valid_form_id,
            "info": {"title": "দারুল উলুম মাদ্রাসা - 01799887766 - ID Card Form"},
            "responderUri": valid_resp_url,
            "items": [
                {"itemId": "q1", "title": "নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"itemId": "q2", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }

        res = resolve_google_form_workflow(
            user_message="আমার গুগল ফরম দেন",
            conversation_history=[],
            customer_phone="01799887766",
            customer_name="",
            workspace_id=self.workspace_id
        )

        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("form_id"), valid_form_id)
        self.assertEqual(res.get("form_url"), valid_resp_url)
        self.assertEqual(res.get("sheet_url"), valid_sheet_url)
        self.assertIn(valid_resp_url, res.get("reply", ""))
        print("[PASS] Test 9: Verified existing valid form record successfully returns existing URLs.")

    # TEST 10: WhatsApp 4-turn workflow -> only send success after real verification
    @patch("app.google_integration.drive_service.verify_file_accessible")
    @patch("app.google_integration.forms_service.get_form_details")
    @patch("app.google_integration.form_manager.get_or_create_workspace_root_folder")
    @patch("app.google_integration.form_manager.get_or_create_institution_folder")
    @patch("app.google_integration.form_manager.save_institution")
    @patch("app.google_integration.form_manager.copy_master_form_file")
    @patch("app.google_integration.form_manager.customize_cloned_institution_form")
    @patch("app.google_integration.form_manager.create_institution_response_sheet")
    def test_10_whatsapp_workflow_only_sends_success_after_real_verification(
        self, mock_sheet, mock_custom, mock_copy, mock_save_inst, mock_inst_f, mock_root_f, mock_form_details, mock_drive_verify
    ):
        mock_root_f.return_value = "root_folder_123"
        mock_inst_f.return_value = "inst_folder_123"
        mock_save_inst.return_value = {"id": 1, "name": "জামিয়া কারিমিয়া"}
        mock_drive_verify.return_value = (True, {"id": "cloned_wa_123", "name": "Form", "trashed": False})
        mock_form_details.return_value = {
            "formId": "cloned_wa_123",
            "info": {"title": "জামিয়া কারিমিয়া - 01812345678 - ID Card Form"},
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_wa_123/viewform",
            "items": [
                {"itemId": "q1", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"textQuestion": {}}}},
                {"itemId": "q2", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }
        mock_copy.return_value = {"form_id": "cloned_wa_123", "title": "জামিয়া কারিমিয়া - 01812345678 - ID Card Form"}
        mock_custom.return_value = {
            "form_id": "cloned_wa_123",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_wa_123/viewform",
            "form_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_wa_123/viewform",
            "selected_fields": ["student_name", "student_photo"]
        }
        mock_sheet.return_value = {
            "spreadsheet_id": "sheet_wa_123",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_wa_123/edit"
        }

        # Turn 1: User asks for form -> prompts for name
        t1 = resolve_google_form_workflow(
            user_message="আইডি কার্ডের জন্য গুগল ফর্ম তৈরি করে দিন",
            conversation_history=[],
            customer_phone="01812345678",
            customer_name="",
            workspace_id=self.workspace_id
        )
        self.assertEqual(t1["status"], "need_name")

        # Turn 2: User provides Name -> prompts for mobile
        history_t2 = [
            {"role": "user", "content": "আইডি কার্ডের জন্য গুগল ফর্ম তৈরি করে দিন"},
            {"role": "assistant", "content": t1["reply"]}
        ]
        t2 = resolve_google_form_workflow(
            user_message="জামিয়া কারিমিয়া",
            conversation_history=history_t2,
            customer_phone="",
            customer_name="",
            workspace_id=self.workspace_id
        )
        self.assertEqual(t2["status"], "need_mobile")

        # Turn 3: User provides Mobile -> prompts for fields
        history_t3 = history_t2 + [
            {"role": "user", "content": "জামিয়া কারিমিয়া"},
            {"role": "assistant", "content": t2["reply"]}
        ]
        t3 = resolve_google_form_workflow(
            user_message="01812345678",
            conversation_history=history_t3,
            customer_phone="01812345678",
            customer_name="",
            workspace_id=self.workspace_id
        )
        self.assertEqual(t3["status"], "need_fields")

        # Turn 4: User provides fields -> Triggers form creation & verification -> sends real live link
        history_t4 = history_t3 + [
            {"role": "user", "content": "01812345678"},
            {"role": "assistant", "content": t3["reply"]}
        ]
        t4 = resolve_google_form_workflow(
            user_message="শিক্ষার্থীর নাম এবং ছবি লাগবে",
            conversation_history=history_t4,
            customer_phone="01812345678",
            customer_name="",
            workspace_id=self.workspace_id
        )

        self.assertEqual(t4["status"], "created")
        self.assertTrue(t4["success"])
        self.assertEqual(t4["form_id"], "cloned_wa_123")
        self.assertEqual(t4["form_url"], "https://docs.google.com/forms/d/e/1FAIpQLSc_wa_123/viewform")
        self.assertEqual(t4["sheet_url"], "https://docs.google.com/spreadsheets/d/sheet_wa_123/edit")
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_wa_123/viewform", t4["reply"])
        print("[PASS] Test 10: WhatsApp 4-turn conversational workflow successfully verifies form and sends live URLs.")


if __name__ == "__main__":
    unittest.main()
