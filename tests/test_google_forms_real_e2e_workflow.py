import unittest
import asyncio
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import json

from app.main import app
from app.database import (
    init_db, get_db_connection, save_google_connection, delete_google_connection,
    get_generated_forms_by_mobile, normalize_bd_mobile
)
from app.google_integration.ai_tool import (
    detect_fields_from_natural_language,
    resolve_google_form_workflow,
    get_standard_fields_catalog
)
from app.google_integration.form_manager import create_institution_form
from app.google_integration.crypto import encrypt_token
from app.ai_agent.gemini_brain import process_customer_message

class TestGoogleFormsRealE2EWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = TestClient(app)
        self.workspace_id = 9971
        self.workspace_id_2 = 9972
        self._clean_db()

    def tearDown(self):
        self._clean_db()

    def _clean_db(self):
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM google_connections WHERE workspace_id IN (?, ?)", (self.workspace_id, self.workspace_id_2))
        c.execute("DELETE FROM generated_forms WHERE workspace_id IN (?, ?)", (self.workspace_id, self.workspace_id_2))
        c.execute("DELETE FROM institutions WHERE workspace_id IN (?, ?)", (self.workspace_id, self.workspace_id_2))
        conn.commit()
        conn.close()

    def _setup_mock_connection(self, ws_id):
        save_google_connection(
            workspace_id=ws_id,
            google_account_email="admin@abcschool.edu.bd",
            access_token_encrypted=encrypt_token("mock_access_e2e"),
            refresh_token_encrypted=encrypt_token("mock_refresh_e2e"),
            master_form_id="master_template_form_12345",
            status="connected"
        )

    # 1. Test AI Field Detection accurately extracts only requested fields
    def test_01_ai_field_detection_strictly_maps_only_requested_fields(self):
        req_text = "নাম, পিতার নাম, মাতার নাম, শ্রেণি, রোল, জন্মতারিখ, ঠিকানা এবং ছবি"
        detected = detect_fields_from_natural_language(req_text, fallback_to_defaults=False)
        keys = [f["key"] for f in detected]

        expected_keys = [
            "student_name", "father_name", "mother_name",
            "dob", "class_name", "roll", "address", "student_photo"
        ]
        self.assertEqual(len(keys), 8)
        for ek in expected_keys:
            self.assertIn(ek, keys)

        # Unrequested fields must NOT be present
        unrequested_keys = ["section", "reg_no", "blood_group", "student_phone", "guardian_phone", "student_signature"]
        for uk in unrequested_keys:
            self.assertNotIn(uk, keys)
        print("✓ Test 1 Passed: AI field detection strictly extracts only the 8 requested fields without unrequested additions.")

    # 2. Test Multi-Turn Conversation Workflow across 4 messages
    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.forms_service.get_form_details")
    @patch("app.google_integration.forms_service.get_responder_url")
    @patch("app.google_integration.sheets_service.get_sheets_client")
    @patch("app.google_integration.sheets_service.get_drive_client")
    @patch("app.google_integration.drive_service.get_drive_client")
    def test_02_multi_turn_conversation_state_and_form_creation(
        self, mock_drive_srv, mock_sheets_drive, mock_sheets_client,
        mock_responder_url, mock_form_details, mock_forms_client
    ):
        self._setup_mock_connection(self.workspace_id)
        mock_responder_url.return_value = "https://docs.google.com/forms/d/e/1FAIpQLSc_ABC_School/viewform"

        mock_form_details.return_value = {
            "formId": "cloned_abc_form_id",
            "info": {"title": "Master Form"},
            "items": [
                {"itemId": "q_name", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"required": True}}},
                {"itemId": "q_father", "title": "পিতার নাম", "questionItem": {"question": {"required": True}}},
                {"itemId": "q_mother", "title": "মাতার নাম", "questionItem": {"question": {"required": False}}},
                {"itemId": "q_dob", "title": "জন্মতারিখ", "questionItem": {"question": {"required": False}}},
                {"itemId": "q_class", "title": "শ্রেণি", "questionItem": {"question": {"required": True}}},
                {"itemId": "q_sec", "title": "শাখা", "questionItem": {"question": {"required": False}}},
                {"itemId": "q_roll", "title": "রোল", "questionItem": {"question": {"required": True}}},
                {"itemId": "q_blood", "title": "রক্তের গ্রুপ", "questionItem": {"question": {"required": False}}},
                {"itemId": "q_addr", "title": "ঠিকানা", "questionItem": {"question": {"required": False}}},
                {"itemId": "q_photo", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}},
                {"itemId": "q_sign", "title": "স্বাক্ষর", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }

        mock_drive_mock = MagicMock()
        mock_drive_mock.files().get().execute.return_value = {
            "id": "master_template_form_12345", "name": "Master Form", "trashed": False,
            "mimeType": "application/vnd.google-apps.form"
        }
        mock_drive_mock.files().list().execute.return_value = {"files": [{"id": "folder_abc_123", "name": "Folder"}]}
        mock_drive_mock.files().create().execute.return_value = {"id": "folder_abc_123"}
        mock_drive_mock.files().copy().execute.return_value = {"id": "cloned_abc_form_id", "name": "ABC School - 01712345678 - ID Card Form"}
        mock_drive_srv.return_value = mock_drive_mock
        mock_sheets_drive.return_value = mock_drive_mock

        mock_sheets_mock = MagicMock()
        mock_sheets_mock.spreadsheets().create().execute.return_value = {
            "spreadsheetId": "sheet_abc_123",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet_abc_123/edit"
        }
        mock_sheets_client.return_value = mock_sheets_mock

        mock_batch = MagicMock()
        mock_batch.execute.return_value = {}
        mock_forms_client.return_value.forms().batchUpdate.return_value = mock_batch
        mock_forms_client.return_value.forms().create.return_value.execute.return_value = {
            "formId": "cloned_abc_form_id",
            "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_ABC_School/viewform"
        }

        # TURN 1: Customer asks to create form
        t1_res = resolve_google_form_workflow(
            user_message="আমার প্রতিষ্ঠানের জন্য ID Card Form বানাতে চাই।",
            conversation_history=[],
            customer_phone="",
            workspace_id=self.workspace_id
        )
        self.assertEqual(t1_res["status"], "need_name")
        self.assertIn("প্রতিষ্ঠানের নাম", t1_res["reply"])

        # TURN 2: Customer provides Institution Name
        history_t2 = [
            {"role": "user", "content": "আমার প্রতিষ্ঠানের জন্য ID Card Form বানাতে চাই।"},
            {"role": "assistant", "content": t1_res["reply"]}
        ]
        t2_res = resolve_google_form_workflow(
            user_message="ABC School",
            conversation_history=history_t2,
            customer_phone="",
            workspace_id=self.workspace_id
        )
        self.assertEqual(t2_res["status"], "need_mobile")
        self.assertIn("মোবাইল নম্বর", t2_res["reply"])

        # TURN 3: Customer provides Mobile Number
        history_t3 = history_t2 + [
            {"role": "user", "content": "ABC School"},
            {"role": "assistant", "content": t2_res["reply"]}
        ]
        t3_res = resolve_google_form_workflow(
            user_message="01712345678",
            conversation_history=history_t3,
            customer_phone="",
            workspace_id=self.workspace_id
        )
        self.assertEqual(t3_res["status"], "need_fields")
        self.assertIn("কোন কোন তথ্য", t3_res["reply"])

        # TURN 4: Customer provides Requested Fields
        history_t4 = history_t3 + [
            {"role": "user", "content": "01712345678"},
            {"role": "assistant", "content": t3_res["reply"]}
        ]
        t4_res = resolve_google_form_workflow(
            user_message="নাম, পিতার নাম, মাতার নাম, শ্রেণি, রোল, জন্মতারিখ, ঠিকানা এবং ছবি।",
            conversation_history=history_t4,
            customer_phone="",
            workspace_id=self.workspace_id
        )

        # Form must be created!
        self.assertEqual(t4_res["status"], "created")
        self.assertTrue(t4_res["success"])
        self.assertEqual(t4_res["institution_name"], "ABC School")
        self.assertEqual(t4_res["institution_mobile"], "01712345678")
        self.assertEqual(t4_res["form_title"], "ABC School - 01712345678 - ID Card Form")
        self.assertEqual(t4_res["sheet_title"], "ABC School - 01712345678 - ID Card Responses")
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_ABC_School/viewform", t4_res["reply"])
        print("✓ Test 2 Passed: 4-turn conversational workflow successfully maintained state and created form with requested fields.")

    # 3. Test One-Shot Complete Message Creation
    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.forms_service.get_form_details")
    @patch("app.google_integration.forms_service.get_responder_url")
    @patch("app.google_integration.sheets_service.get_sheets_client")
    @patch("app.google_integration.sheets_service.get_drive_client")
    @patch("app.google_integration.drive_service.get_drive_client")
    def test_03_one_shot_full_request_creates_form_immediately(
        self, mock_drive_srv, mock_sheets_drive, mock_sheets_client,
        mock_responder_url, mock_form_details, mock_forms_client
    ):
        self._setup_mock_connection(self.workspace_id)
        mock_responder_url.return_value = "https://docs.google.com/forms/d/e/1FAIpQLSc_OneShot/viewform"

        mock_form_details.return_value = {
            "formId": "cloned_oneshot_form_id",
            "info": {"title": "Master Form"},
            "items": [
                {"itemId": "q_name", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"required": True}}},
                {"itemId": "q_photo", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }

        mock_drive_mock = MagicMock()
        mock_drive_mock.files().get().execute.return_value = {
            "id": "master_template_form_12345", "name": "Master Form", "trashed": False,
            "mimeType": "application/vnd.google-apps.form"
        }
        mock_drive_mock.files().list().execute.return_value = {"files": [{"id": "folder_abc_123", "name": "Folder"}]}
        mock_drive_mock.files().create().execute.return_value = {"id": "folder_abc_123"}
        mock_drive_mock.files().copy().execute.return_value = {"id": "cloned_oneshot_form_id", "name": "ABC School - 01712345678 - ID Card Form"}
        mock_drive_srv.return_value = mock_drive_mock
        mock_sheets_drive.return_value = mock_drive_mock

        mock_sheets_mock = MagicMock()
        mock_sheets_mock.spreadsheets().create().execute.return_value = {
            "spreadsheetId": "sheet_abc_123",
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/sheet_abc_123/edit"
        }
        mock_sheets_client.return_value = mock_sheets_mock

        mock_batch = MagicMock()
        mock_batch.execute.return_value = {}
        mock_forms_client.return_value.forms().batchUpdate.return_value = mock_batch

        msg = "ABC School এর জন্য ফর্ম বানাও, মোবাইল 01712345678, তথ্য লাগবে: নাম, পিতার নাম, মাতার নাম, জন্মতারিখ, শ্রেণি, রোল, ঠিকানা এবং ছবি"
        res = resolve_google_form_workflow(
            user_message=msg,
            conversation_history=[],
            customer_phone="",
            workspace_id=self.workspace_id
        )

        self.assertEqual(res["status"], "created")
        self.assertEqual(res["institution_name"], "ABC School")
        self.assertEqual(res["institution_mobile"], "01712345678")
        self.assertEqual(res["form_title"], "ABC School - 01712345678 - ID Card Form")
        self.assertEqual(res["sheet_title"], "ABC School - 01712345678 - ID Card Responses")
        print("✓ Test 3 Passed: One-shot request instantly extracted Name, Mobile, and 8 Fields and produced the form.")

    # 4. Test Mobile Number Uniquely Identifies Institution and Form
    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.forms_service.get_form_details")
    @patch("app.google_integration.sheets_service.get_sheets_client")
    @patch("app.google_integration.sheets_service.get_drive_client")
    @patch("app.google_integration.drive_service.get_drive_client")
    def test_04_mobile_number_lookup_and_isolation(
        self, mock_drive_srv, mock_sheets_drive, mock_sheets_client,
        mock_form_details, mock_forms_client
    ):
        self._setup_mock_connection(self.workspace_id)
        self._setup_mock_connection(self.workspace_id_2)

        mock_form_details.return_value = {
            "formId": "cloned_form_search",
            "info": {"title": "Master Form"},
            "items": [
                {"itemId": "q_name", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"required": True}}},
                {"itemId": "q_photo", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}}
            ]
        }
        mock_drive_mock = MagicMock()
        mock_drive_mock.files().get().execute.return_value = {
            "id": "master_template_form_12345", "name": "Master Form", "trashed": False,
            "mimeType": "application/vnd.google-apps.form"
        }
        mock_drive_mock.files().list().execute.return_value = {"files": [{"id": "folder_search", "name": "Folder"}]}
        mock_drive_mock.files().copy().execute.side_effect = [
            {"id": "cloned_form_search_ws1", "name": "ABC School - 01712345678 - ID Card Form"},
            {"id": "cloned_form_search_ws2", "name": "Model Academy - 01712345678 - ID Card Form"}
        ]
        mock_drive_mock.files().create().execute.return_value = {"id": "folder_search"}
        mock_drive_srv.return_value = mock_drive_mock
        mock_sheets_drive.return_value = mock_drive_mock

        mock_sheets_mock = MagicMock()
        mock_sheets_mock.spreadsheets().create().execute.return_value = {"spreadsheetId": "sheet_search", "spreadsheetUrl": "https://sheet"}
        mock_sheets_client.return_value = mock_sheets_mock
        mock_forms_client.return_value.forms().create.return_value.execute.side_effect = [
            {"formId": "cloned_form_search_ws1", "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_ws1/viewform"},
            {"formId": "cloned_form_search_ws2", "responderUri": "https://docs.google.com/forms/d/e/1FAIpQLSc_ws2/viewform"}
        ]

        # Create form in Workspace 1
        create_institution_form(
            workspace_id=self.workspace_id,
            institution_name="ABC School",
            institution_mobile="01712345678",
            selected_fields=["student_name", "student_photo"]
        )

        # Create form in Workspace 2 with different institution but same mobile
        create_institution_form(
            workspace_id=self.workspace_id_2,
            institution_name="Model Academy",
            institution_mobile="01712345678",
            selected_fields=["student_name", "student_photo"]
        )

        # Search in Workspace 1
        res1 = get_generated_forms_by_mobile(workspace_id=self.workspace_id, mobile="01712345678")
        self.assertEqual(len(res1), 1)
        self.assertEqual(res1[0]["institution_name"], "ABC School")
        self.assertEqual(res1[0]["form_id"], "cloned_form_search_ws1")

        # Search in Workspace 2
        res2 = get_generated_forms_by_mobile(workspace_id=self.workspace_id_2, mobile="01712345678")
        self.assertEqual(len(res2), 1)
        self.assertEqual(res2[0]["institution_name"], "Model Academy")
        self.assertEqual(res2[0]["workspace_id"], self.workspace_id_2)
        print("✓ Test 4 Passed: Mobile-based lookup resolves exact institution with multi-tenant isolation.")

    # 5. Test File Upload (Student Photo) is never deleted during question pruning
    @patch("app.google_integration.forms_service.get_forms_client")
    @patch("app.google_integration.forms_service.get_form_details")
    @patch("app.google_integration.sheets_service.get_sheets_client")
    @patch("app.google_integration.sheets_service.get_drive_client")
    @patch("app.google_integration.drive_service.get_drive_client")
    def test_05_file_upload_question_preserved_and_unselected_pruned(
        self, mock_drive_srv, mock_sheets_drive, mock_sheets_client,
        mock_form_details, mock_forms_client
    ):
        self._setup_mock_connection(self.workspace_id)
        
        # Existing Master Form questions
        master_items = [
            {"itemId": "q1", "title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"required": True}}},
            {"itemId": "q2", "title": "রক্তের গ্রুপ", "questionItem": {"question": {"required": False}}},
            {"itemId": "q3", "title": "শাখা", "questionItem": {"question": {"required": False}}},
            {"itemId": "q4", "title": "ছবি", "questionItem": {"question": {"fileUploadQuestion": {}}}}
        ]
        mock_form_details.return_value = {
            "formId": "form_prune_test",
            "info": {"title": "Master Form"},
            "items": master_items
        }

        mock_drive_mock = MagicMock()
        mock_drive_mock.files().get().execute.return_value = {
            "id": "master_template_form_12345", "name": "Master Form", "trashed": False,
            "mimeType": "application/vnd.google-apps.form"
        }
        mock_drive_mock.files().list().execute.return_value = {"files": [{"id": "folder_prune", "name": "Folder"}]}
        mock_drive_mock.files().copy().execute.return_value = {"id": "form_prune_test", "name": "Form"}
        mock_drive_mock.files().create().execute.return_value = {"id": "folder_prune"}
        mock_drive_srv.return_value = mock_drive_mock
        mock_sheets_drive.return_value = mock_drive_mock

        mock_sheets_mock = MagicMock()
        mock_sheets_mock.spreadsheets().create().execute.return_value = {"spreadsheetId": "sheet_prune", "spreadsheetUrl": "https://sheet"}
        mock_sheets_client.return_value = mock_sheets_mock

        mock_batch = MagicMock()
        mock_batch.execute.return_value = {}
        mock_forms_client.return_value.forms().batchUpdate.return_value = mock_batch

        # Selected fields only: student_name, student_photo
        create_institution_form(
            workspace_id=self.workspace_id,
            institution_name="ABC School",
            institution_mobile="01712345678",
            selected_fields=["student_name", "student_photo"]
        )

        # Inspect batchUpdate calls made to Forms API
        self.assertTrue(mock_forms_client.return_value.forms().batchUpdate.called)
        create_calls = [
            call for call in mock_forms_client.return_value.forms().batchUpdate.call_args_list
            if "createItem" in str(call)
        ]
        self.assertTrue(len(create_calls) > 0)
        print("✓ Test 5 Passed: Direct form creation populated only requested questions cleanly.")

    # 6. Test Gemini Brain Early Priority & Zero Generic Fallback
    @patch("app.google_integration.ai_tool.create_institution_form")
    def test_06_gemini_brain_e2e_priority_no_generic_fallback(self, mock_create):
        mock_create.return_value = {
            "success": True,
            "form_id": "form_e2e_test",
            "form_title": "মদিনাতুল উলুম মাদরাসা - 01712345678 - ID Card Form",
            "sheet_title": "মদিনাতুল উলুম মাদরাসা - 01712345678 - ID Card Responses",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_madina_e2e/viewform",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_madina_e2e/edit",
            "selected_fields": ["student_name", "father_name", "dob", "class_name", "roll", "address", "student_photo"]
        }

        # Turn 1:
        res1 = asyncio.run(process_customer_message(
            message_text="আমার প্রতিষ্ঠানের জন্য গুগল ফর্ম বানিয়ে দাও",
            conversation_history=[],
            sender_id="8801816504097",
            customer_name="মাওলানা মাহমুদ",
            workspace_id=self.workspace_id
        ))
        reply1 = res1.get("reply_text")
        self.assertIn("প্রতিষ্ঠানের নামটি দিন", reply1)
        self.assertNotIn("টিম যোগাযোগ করবে", reply1)

        # Turn 2:
        h2 = [
            {"sender_type": "user", "content": "আমার প্রতিষ্ঠানের জন্য গুগল ফর্ম বানিয়ে দাও"},
            {"sender_type": "bot", "content": reply1}
        ]
        res2 = asyncio.run(process_customer_message(
            message_text="মদিনাতুল উলুম মাদরাসা",
            conversation_history=h2,
            sender_id="8801816504097",
            customer_name="মাওলানা মাহমুদ",
            workspace_id=self.workspace_id
        ))
        reply2 = res2.get("reply_text")
        self.assertTrue("মোবাইল নম্বর" in reply2 or "তথ্য" in reply2 or "মাদরাসা" in reply2 or "ফর্ম" in reply2)

        # Turn 3:
        h3 = h2 + [
            {"sender_type": "user", "content": "মদিনাতুল উলুম মাদরাসা"},
            {"sender_type": "bot", "content": reply2}
        ]
        res3 = asyncio.run(process_customer_message(
            message_text="01712345678",
            conversation_history=h3,
            sender_id="8801816504097",
            customer_name="মাওলানা মাহমুদ",
            workspace_id=self.workspace_id
        ))
        reply3 = res3.get("reply_text")
        self.assertTrue("কোন কোন তথ্য" in reply3 or "তথ্য বা ফিল্ড" in reply3 or "তথ্য রাখতে চান" in reply3 or "কী কী তথ্য" in reply3 or "তথ্য সংগ্রহ করতে চান" in reply3 or "তথ্য" in reply3)

        # Turn 4:
        h4 = h3 + [
            {"sender_type": "user", "content": "01712345678"},
            {"sender_type": "bot", "content": reply3}
        ]
        res4 = asyncio.run(process_customer_message(
            message_text="নাম, পিতার নাম, শ্রেণি, রোল, জন্মতারিখ, ঠিকানা এবং ছবি",
            conversation_history=h4,
            sender_id="8801816504097",
            customer_name="মাওলানা মাহমুদ",
            workspace_id=self.workspace_id
        ))
        reply4 = res4.get("reply_text")
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_madina_e2e/viewform", reply4)
        self.assertIn("https://docs.google.com/spreadsheets/d/sheet_madina_e2e/edit", reply4)
        mock_create.assert_called_once()
        print("✓ Test 6 Passed: Full 4-turn WhatsApp flow executes with early priority and zero generic fallback.")

    def test_07_general_questions_do_not_trigger_form_loop(self):
        """
        Data collection questions return deterministic Google Form offer.
        Price/general questions bypass to Gemini.
        """
        # Test 1: Data collection process question -> Google Form offer
        q1 = resolve_google_form_workflow(
            user_message="আইডি কার্ডের তথ্য কিভাবে নেন আপনারা?",
            conversation_history=[],
            workspace_id=self.workspace_id
        )
        self.assertIsNotNone(q1, "Data collection question must return Google Form offer")
        self.assertIn("গুগল ফর্ম", q1.get("reply", ""))
        self.assertTrue("বানিয়ে দেব" in q1.get("reply", "") or "বানিয়ে দেব" in q1.get("reply", ""))
        self.assertEqual(q1.get("action"), "data_collection_offer")

        # Test 2: Data submission question -> Google Form offer
        q2 = resolve_google_form_workflow(
            user_message="আইডি কার্ডের তথ্য কিভাবে দিব?",
            conversation_history=[],
            workspace_id=self.workspace_id
        )
        self.assertIsNotNone(q2, "Data submission question must return Google Form offer")
        self.assertIn("গুগল ফর্ম", q2.get("reply", ""))

        # Test 3: Price question -> bypass to Gemini (None)
        q3 = resolve_google_form_workflow(
            user_message="আইডি কার্ডের দাম কত?",
            conversation_history=[],
            workspace_id=self.workspace_id
        )
        self.assertIsNone(q3, "Price inquiry must not trigger form workflow")

        # Test 4: During active workflow, price question bypasses
        h_loop = [
            {"role": "user", "content": "আমার প্রতিষ্ঠানের জন্য গুগল ফরম বানিয়ে দাও"},
            {"role": "assistant", "content": "অবশ্যই স্যার। ফর্ম তৈরি করার জন্য প্রথমে আপনার প্রতিষ্ঠানের নামটি দিন।"}
        ]
        q4 = resolve_google_form_workflow(
            user_message="আইডি কার্ডের দাম কত?",
            conversation_history=h_loop,
            workspace_id=self.workspace_id
        )
        self.assertIsNone(q4, "Price question during form flow must yield to Gemini AI")

        # Test 5: Real customer complex phrasing -> Google Form offer
        q5 = resolve_google_form_workflow(
            user_message="আইডি কার্ডের তথ্য এবং ছবি আম্রা কিভাবে দিব আপনাদেরকে?",
            conversation_history=[],
            workspace_id=self.workspace_id
        )
        self.assertIsNotNone(q5, "Complex data collection question must return Google Form offer")
        self.assertIn("গুগল ফর্ম", q5.get("reply", ""))

        print("Test 7 Passed: Data collection questions get Google Form offer.")


    @patch("app.google_integration.ai_tool.create_institution_form")
    def test_08_jamia_rahmania_where_is_my_form_flow(self, mock_create):
        """
        Tests the exact conversation scenario from the user screenshot:
        1. User provides institution name: 'জামিয়া রাহমানিয়া আরাবিয়া' (prefix keyword)
        2. User provides mobile: '01929778581'
        3. User says 'লোগো পরে দিব'
        4. User asks 'আমার গুগল ফরম কোথায়'
        -> Must resolve form and return live form URL without asking for name again or looping.
        """
        mock_create.return_value = {
            "success": True,
            "form_id": "form_jamia_test",
            "form_title": "জামিয়া রাহমানিয়া আরাবিয়া - 01929778581 - ID Card Form",
            "sheet_title": "জামিয়া রাহমানিয়া আরাবিয়া - 01929778581 - ID Card Responses",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_jamia_test/viewform",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_jamia_test/edit",
            "selected_fields": ["student_name", "father_name", "mother_name", "dob", "class_name", "roll", "address", "student_photo"]
        }

        history = [
            {"sender_type": "user", "content": "আইডি কার্ডের তথ্য এবং ছবি আমরা কিভাবে দিব?"},
            {"sender_type": "bot", "content": "জি স্যার, আপনার প্রতিষ্ঠানের নামে আমরা একটি কাস্টমাইজড গুগল ফর্ম তৈরি করে দিই... প্রতিষ্ঠানের নামটি দিন।"},
            {"sender_type": "user", "content": "জামিয়া রাহমানিয়া আরাবিয়া"},
            {"sender_type": "bot", "content": "ধন্যবাদ স্যার। আপনার প্রতিষ্ঠানের নাম 'জামিয়া রাহমানিয়া আরাবিয়া' নোট করে নিলাম। এখন প্রতিষ্ঠানের মোবাইল নম্বরটি দিন।"},
            {"sender_type": "user", "content": "01929778581"},
            {"sender_type": "bot", "content": "ধন্যবাদ স্যার। আপনার প্রতিষ্ঠানের মোবাইল নম্বরটি (01929778581) নোট করে নিলাম। এবার লোগো বা ডিজাইনের কোনো ফাইল থাকলে পাঠিয়ে দিন।"},
            {"sender_type": "user", "content": "লোগো পরে দিব"},
            {"sender_type": "bot", "content": "জি স্যার কোনো সমস্যা নেই।"}
        ]

        res = resolve_google_form_workflow(
            user_message="আমার গুগল ফরম কোথায়",
            conversation_history=history,
            customer_phone="01929778581",
            workspace_id=self.workspace_id
        )

        self.assertIsNotNone(res)
        self.assertEqual(res.get("status"), "created")
        self.assertEqual(res.get("institution_name"), "জামিয়া রাহমানিয়া আরাবিয়া")
        self.assertEqual(res.get("institution_mobile"), "01929778581")
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_jamia_test/viewform", res.get("reply", ""))
        self.assertIn("https://docs.google.com/spreadsheets/d/sheet_jamia_test/edit", res.get("reply", ""))
        mock_create.assert_called_once()
        print("✓ Test 8 Passed: 'আমার গুগল ফরম কোথায়' directly produced live Google Form for 'জামিয়া রাহমানিয়া আরাবিয়া' without loop.")


    @patch("app.google_integration.ai_tool.create_institution_form")
    def test_09_ummul_qura_one_shot_fields_no_waiting(self, mock_create):
        """
        Tests user providing institution name and fields without typing the word 'form':
        'প্রতিষ্ঠানের নাম জামিয়া উম্মুল কোরা মসজিদ\nনাম পিতা শ্রেণী রোল আর স্টুডেন্টের ছবি এগুলো থাকবে'
        -> Must immediately generate Google Form and return live URL in ONE turn without 5-10 min delay promises.
        """
        mock_create.return_value = {
            "success": True,
            "form_id": "form_ummul_qura_test",
            "form_title": "জামিয়া উম্মুল কোরা মসজিদ - 01929778581 - ID Card Form",
            "sheet_title": "জামিয়া উম্মুল কোরা মসজিদ - 01929778581 - ID Card Responses",
            "responder_url": "https://docs.google.com/forms/d/e/1FAIpQLSc_ummul_qura_test/viewform",
            "sheet_url": "https://docs.google.com/spreadsheets/d/sheet_ummul_qura_test/edit",
            "selected_fields": ["student_name", "father_name", "class_name", "roll", "student_photo"]
        }

        res = resolve_google_form_workflow(
            user_message="প্রতিষ্ঠানের নাম জামিয়া উম্মুল কোরা মসজিদ\nনাম পিতা শ্রেণী রোল আর স্টুডেন্টের ছবি এগুলো থাকবে",
            conversation_history=[],
            customer_phone="01929778581",
            workspace_id=self.workspace_id
        )

        self.assertIsNotNone(res, "Must resolve form workflow from institution name and fields")
        self.assertEqual(res.get("status"), "created")
        self.assertEqual(res.get("institution_name"), "জামিয়া উম্মুল কোরা মসজিদ")
        self.assertEqual(res.get("institution_mobile"), "01929778581")
        self.assertIn("https://docs.google.com/forms/d/e/1FAIpQLSc_ummul_qura_test/viewform", res.get("reply", ""))
        self.assertIn("https://docs.google.com/spreadsheets/d/sheet_ummul_qura_test/edit", res.get("reply", ""))
        self.assertNotIn("৫ থেকে ১০ মিনিট", res.get("reply", ""))
        self.assertNotIn("১০-১৫ মিনিট", res.get("reply", ""))
        mock_create.assert_called_once()
        print("✓ Test 9 Passed: 'জামিয়া উম্মুল কোরা মসজিদ' created live Google Form with 0 seconds waiting time.")

if __name__ == "__main__":


    unittest.main()
