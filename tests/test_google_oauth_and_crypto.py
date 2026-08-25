import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from app.main import app
from app.database import (
    init_db, get_google_connection, save_google_connection, delete_google_connection
)
from app.google_integration.crypto import encrypt_token, decrypt_token, mask_token, mask_email
from app.google_integration.oauth_service import (
    get_oauth_authorization_url, get_google_account_status
)

class TestGoogleOAuthAndCrypto(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = TestClient(app)
        delete_google_connection(workspace_id=991)
        delete_google_connection(workspace_id=992)

    def tearDown(self):
        delete_google_connection(workspace_id=991)
        delete_google_connection(workspace_id=992)

    def test_01_crypto_encryption_and_decryption(self):
        """Verifies token encryption at rest and transparent decryption."""
        raw_token = "ya29.a0AWY7Ckm_SecretAccessToken_Example123456789"
        encrypted = encrypt_token(raw_token)
        self.assertNotEqual(raw_token, encrypted)

        decrypted = decrypt_token(encrypted)
        self.assertEqual(raw_token, decrypted)
        print("✓ Token encryption at rest & decryption verified.")

    def test_02_token_and_email_masking(self):
        """Verifies tokens and emails are never leaked in plaintext."""
        raw_token = "ya29.a0AWY7Ckm_SecretAccessToken_Example123456789"
        masked = mask_token(raw_token)
        self.assertIn("...", masked)
        self.assertNotIn("SecretAccessToken", masked)

        email = "jamia.rahmania@gmail.com"
        masked_em = mask_email(email)
        self.assertIn("***", masked_em)
        self.assertTrue(masked_em.endswith("@gmail.com"))
        print("✓ Token & email masking verified.")

    def test_03_oauth_authorization_url_generation(self):
        """Verifies OAuth URL includes correct workspace state and required Google scopes."""
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "mock-client-id-12345"}):
            url = get_oauth_authorization_url(workspace_id=991)
            self.assertIn("client_id=mock-client-id-12345", url)
            self.assertIn("state=ws_991", url)
            self.assertIn("forms.body", url)
            self.assertIn("drive", url)
            self.assertIn("spreadsheets", url)
            print("✓ Google OAuth authorization URL generated with workspace state.")

    def test_04_workspace_google_connection_isolation(self):
        """Verifies Workspace 991 connection is completely isolated from Workspace 992."""
        # Save connection for Workspace 991
        save_google_connection(
            workspace_id=991,
            google_account_email="workspace991@gmail.com",
            access_token_encrypted=encrypt_token("tok_991"),
            refresh_token_encrypted=encrypt_token("ref_991"),
            master_form_id="master_form_991"
        )

        # Verify Workspace 991 has connection
        conn_991 = get_google_account_status(workspace_id=991)
        self.assertTrue(conn_991["connected"])
        self.assertEqual(conn_991["master_form_id"], "master_form_991")

        # Verify Workspace 992 has NO connection
        conn_992 = get_google_account_status(workspace_id=992)
        self.assertFalse(conn_992["connected"])
        self.assertIsNone(conn_992["master_form_id"])

        # Check API status endpoint
        r991 = self.client.get("/api/google/status?workspace_id=991")
        self.assertEqual(r991.status_code, 200)
        self.assertTrue(r991.json()["connected"])

        r992 = self.client.get("/api/google/status?workspace_id=992")
        self.assertEqual(r992.status_code, 200)
        self.assertFalse(r992.json()["connected"])
        print("✓ Google connection workspace isolation verified.")

if __name__ == "__main__":
    unittest.main()
