import unittest
import os
import sqlite3
from unittest.mock import patch, MagicMock

from app.database import (
    get_db_connection, save_google_connection, get_google_connection,
    update_google_master_ids, delete_google_connection, get_setting, set_setting
)
from app.google_integration.oauth_service import (
    get_google_account_status, get_workspace_credentials, exchange_code_for_tokens
)
from app.google_integration.crypto import encrypt_token, decrypt_token

class TestGoogleConnectionPersistence(unittest.TestCase):
    def setUp(self):
        self.ws_id = 9981
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO workspaces (id, name, slug) VALUES (?, 'Test WS 9981', 'test-ws-9981')", (self.ws_id,))
            cur.execute("DELETE FROM google_connections WHERE workspace_id = ?", (self.ws_id,))
            cur.execute("DELETE FROM settings WHERE key LIKE ?", (f"%ws_{self.ws_id}%",))
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM google_connections WHERE workspace_id = ?", (self.ws_id,))
            cur.execute("DELETE FROM settings WHERE key LIKE ?", (f"%ws_{self.ws_id}%",))
            cur.execute("DELETE FROM workspaces WHERE id = ?", (self.ws_id,))
            conn.commit()
        finally:
            conn.close()

    def test_01_save_google_connection_persists_and_backups_to_settings(self):
        """Saving connection stores tokens in google_connections AND settings backup."""
        enc_acc = encrypt_token("mock-access-token-123")
        enc_ref = encrypt_token("mock-refresh-token-456")
        email = "business_owner@gmail.com"

        saved = save_google_connection(
            workspace_id=self.ws_id,
            google_account_email=email,
            access_token_encrypted=enc_acc,
            refresh_token_encrypted=enc_ref,
            status="connected"
        )
        self.assertEqual(saved.get("google_account_email"), email)
        self.assertEqual(saved.get("status"), "connected")

        # Verify settings backup was written
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key = ?", (f"google_refresh_token_ws_{self.ws_id}",))
            ref_row = cur.fetchone()
            self.assertIsNotNone(ref_row)
            self.assertEqual(ref_row[0], enc_ref)

            cur.execute("SELECT value FROM settings WHERE key = ?", (f"google_account_email_ws_{self.ws_id}",))
            email_row = cur.fetchone()
            self.assertIsNotNone(email_row)
            self.assertEqual(email_row[0], email)
        finally:
            conn.close()

    def test_02_status_auto_restores_from_settings_on_reload_with_empty_tokens(self):
        """When google_connections row has empty tokens (e.g. wiped or recreated), get_google_account_status auto-restores it."""
        enc_ref = encrypt_token("1//mock-durable-refresh-token")
        email = "durable_admin@gmail.com"

        set_setting(f"google_refresh_token_ws_{self.ws_id}", enc_ref)
        set_setting(f"google_account_email_ws_{self.ws_id}", email)

        # Recreate an empty/disconnected row in google_connections
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO google_connections (
                    workspace_id, google_account_email, access_token_encrypted, refresh_token_encrypted,
                    status, master_form_id, updated_at
                ) VALUES (?, '', '', '', 'connected', '1MasterFormID789', CURRENT_TIMESTAMP)
            """, (self.ws_id,))
            conn.commit()
        finally:
            conn.close()

        # Check status - it must auto-recover and be connected
        status = get_google_account_status(workspace_id=self.ws_id)
        self.assertTrue(status["connected"])
        self.assertEqual(status["status"], "connected")
        self.assertEqual(status["google_account_email"], email)
        self.assertEqual(status["master_form_id"], "1MasterFormID789")

    def test_03_update_master_ids_preserves_tokens_and_email(self):
        """Calling update_google_master_ids does not wipe out tokens or email."""
        enc_acc = encrypt_token("mock-acc-token")
        enc_ref = encrypt_token("mock-ref-token")
        email = "keeper@gmail.com"

        save_google_connection(
            workspace_id=self.ws_id,
            google_account_email=email,
            access_token_encrypted=enc_acc,
            refresh_token_encrypted=enc_ref,
            status="connected"
        )

        # Update master form info
        update_google_master_ids(
            workspace_id=self.ws_id,
            master_form_id="1NewMasterForm999",
            master_form_name="New Master Template",
            master_form_url="https://docs.google.com/forms/d/1NewMasterForm999/viewform"
        )

        # Re-fetch connection
        conn_data = get_google_connection(workspace_id=self.ws_id)
        self.assertEqual(conn_data.get("google_account_email"), email)
        self.assertEqual(conn_data.get("refresh_token_encrypted"), enc_ref)
        self.assertEqual(conn_data.get("master_form_id"), "1NewMasterForm999")

        status = get_google_account_status(workspace_id=self.ws_id)
        self.assertTrue(status["connected"])
        self.assertEqual(status["master_status"], "configured")
        self.assertEqual(status["master_form_id"], "1NewMasterForm999")

    def test_04_credentials_endpoint_saves_and_persists_refresh_token(self):
        """Directly saving credentials via routes/service persists tokens and email permanently."""
        from app.google_integration.routes import save_credentials, SaveGoogleCredentialsRequest

        payload = SaveGoogleCredentialsRequest(
            workspace_id=self.ws_id,
            client_id="123456789.apps.googleusercontent.com",
            client_secret="GOCSPX-SecretMock123",
            refresh_token="1//04MockDirectRefreshToken99",
            account_email="direct_setup@gmail.com"
        )

        res = save_credentials(payload)
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("status", {}).get("connected"))
        self.assertEqual(res.get("status", {}).get("google_account_email"), "direct_setup@gmail.com")

        # Verify DB connection status
        status = get_google_account_status(workspace_id=self.ws_id)
        self.assertTrue(status["connected"])
        self.assertEqual(status["google_account_email"], "direct_setup@gmail.com")

if __name__ == "__main__":
    unittest.main()
