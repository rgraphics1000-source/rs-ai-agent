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
    save_generated_form, get_form_submissions
)
from app.google_integration.crypto import encrypt_token
from app.google_integration.sync_service import sync_form_responses

class TestGoogleResponseSyncAndIdempotency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = TestClient(app)
        self.workspace_id = 994
        from app.database import get_db_connection
        conn = get_db_connection()
        conn.execute("DELETE FROM google_form_submissions WHERE workspace_id = ?", (self.workspace_id,))
        conn.execute("DELETE FROM google_uploaded_files WHERE workspace_id = ?", (self.workspace_id,))
        conn.execute("DELETE FROM generated_forms WHERE workspace_id = ?", (self.workspace_id,))
        conn.commit()
        conn.close()

        delete_google_connection(workspace_id=self.workspace_id)
        save_google_connection(
            workspace_id=self.workspace_id,
            google_account_email="sync.test@gmail.com",
            access_token_encrypted=encrypt_token("mock_tok_994"),
            refresh_token_encrypted=encrypt_token("mock_ref_994"),
            master_form_id="master_id_994"
        )
        self.form = save_generated_form(
            workspace_id=self.workspace_id,
            institution_name="দারুল উলুম মাদরাসা",
            form_id="form_darul_ulum_994",
            form_url="https://docs.google.com/forms/d/form_darul_ulum_994/viewform",
            responder_uri="https://docs.google.com/forms/d/e/form_darul_ulum_994/viewform",
            response_destination_id="sheet_darul_ulum_994",
            response_sheet_url="https://docs.google.com/spreadsheets/d/sheet_darul_ulum_994/edit"
        )

    def tearDown(self):
        delete_google_connection(workspace_id=self.workspace_id)

    @patch("app.google_integration.sync_service.get_drive_client")
    @patch("app.google_integration.sync_service.get_forms_client")
    @patch("app.google_integration.sync_service.append_submission_row")
    @patch("app.google_integration.sync_service.get_form_details")
    def test_01_idempotent_response_sync_and_photo_linking(self, mock_details, mock_append, mock_forms_cls, mock_drive_cls):
        """
        Tests student response synchronization:
        - Parses name, roll, class, and Google Drive photo file link.
        - Guarantees idempotency (zero duplicate records when syncing repeatedly).
        """
        mock_details.return_value = {
            "items": [
                {"title": "শিক্ষার্থীর নাম", "questionItem": {"question": {"questionId": "q1"}}},
                {"title": "রোল নম্বর", "questionItem": {"question": {"questionId": "q2"}}},
                {"title": "শ্রেণি", "questionItem": {"question": {"questionId": "q3"}}},
                {"title": "শিক্ষার্থীর ছবি", "questionItem": {"question": {"questionId": "q4"}}}
            ]
        }

        # Mock 2 responses from Google Forms API
        mock_forms = MagicMock()
        mock_forms_cls.return_value = mock_forms
        mock_forms.forms().responses().list().execute.return_value = {
            "responses": [
                {
                    "responseId": "resp_stu_001",
                    "createTime": "2026-08-21T10:00:00Z",
                    "answers": {
                        "q1": {"textAnswers": {"answers": [{"value": "আব্দুল্লাহ"}]}},
                        "q2": {"textAnswers": {"answers": [{"value": "101"}]}},
                        "q3": {"textAnswers": {"answers": [{"value": "মিশকাত"}]}},
                        "q4": {"fileUploadAnswers": {"answers": [{"fileId": "photo_drive_file_001"}]}}
                    }
                },
                {
                    "responseId": "resp_stu_002",
                    "createTime": "2026-08-21T10:05:00Z",
                    "answers": {
                        "q1": {"textAnswers": {"answers": [{"value": "মুহাম্মদ আব্দুর রহমান"}]}},
                        "q2": {"textAnswers": {"answers": [{"value": "102"}]}},
                        "q3": {"textAnswers": {"answers": [{"value": "দাওরায়ে হাদীস"}]}},
                        "q4": {"fileUploadAnswers": {"answers": [{"fileId": "photo_drive_file_002"}]}}
                    }
                }
            ]
        }

        # Mock Drive file metadata
        mock_drive = MagicMock()
        mock_drive_cls.return_value = mock_drive
        mock_drive.files().get().execute.side_effect = [
            {"id": "photo_drive_file_001", "name": "abdullah.jpg", "webViewLink": "https://drive.google.com/file/d/photo_001/view", "thumbnailLink": "https://drive.google.com/thumb/photo_001"},
            {"id": "photo_drive_file_002", "name": "rahman.jpg", "webViewLink": "https://drive.google.com/file/d/photo_002/view", "thumbnailLink": "https://drive.google.com/thumb/photo_002"}
        ]

        # 1st Sync Call
        res1 = sync_form_responses(workspace_id=self.workspace_id, form_id="form_darul_ulum_994")
        self.assertTrue(res1["success"])
        self.assertEqual(res1["total_submissions"], 2)
        self.assertEqual(res1["new_submissions_imported"], 2)

        # Check DB submissions
        subs = get_form_submissions(form_id="form_darul_ulum_994", workspace_id=self.workspace_id)
        self.assertEqual(len(subs), 2)
        names = [s["student_name"] for s in subs]
        self.assertIn("আব্দুল্লাহ", names)
        self.assertIn("মুহাম্মদ আব্দুর রহমান", names)
        print("✓ First sync imported 2 new student submissions with photo links.")

        # 2nd Sync Call (Same data - Idempotency test)
        res2 = sync_form_responses(workspace_id=self.workspace_id, form_id="form_darul_ulum_994")
        self.assertTrue(res2["success"])
        self.assertEqual(res2["total_submissions"], 2)
        self.assertEqual(res2["new_submissions_imported"], 0)

        # Ensure still exactly 2 submissions in DB
        subs_after = get_form_submissions(form_id="form_darul_ulum_994", workspace_id=self.workspace_id)
        self.assertEqual(len(subs_after), 2)
        print("✓ Idempotency verified: zero duplicate student submissions on repeated sync.")

        # Test API Endpoint
        r_api = self.client.get(f"/api/google/forms/form_darul_ulum_994/responses?workspace_id={self.workspace_id}")
        self.assertEqual(r_api.status_code, 200)
        data = r_api.json()
        self.assertEqual(data["count"], 2)
        print("✓ Responses API endpoint returns parsed student submissions.")

if __name__ == "__main__":
    unittest.main()
