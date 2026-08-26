import os
import time
import requests
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

from app.config import settings
from app.database import (
    get_google_connection, save_google_connection, delete_google_connection,
    get_setting, set_setting
)
from app.google_integration.crypto import encrypt_token, decrypt_token, mask_token, mask_email

# Official OAuth Scopes for Forms, Drive, Sheets, and Account Info
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/userinfo.email"
]

def get_client_config() -> Tuple[str, str, str]:
    """Resolves Client ID, Client Secret, and Redirect URI."""
    client_id = (
        os.getenv("GOOGLE_CLIENT_ID") 
        or get_setting("google_client_id") 
        or settings.GOOGLE_CLIENT_ID
    )
    client_secret = (
        os.getenv("GOOGLE_CLIENT_SECRET") 
        or get_setting("google_client_secret") 
        or settings.GOOGLE_CLIENT_SECRET
    )
    redirect_uri = (
        os.getenv("GOOGLE_REDIRECT_URI") 
        or get_setting("google_redirect_uri") 
        or settings.GOOGLE_REDIRECT_URI
        or "https://rs-ai-agent.onrender.com/api/google/auth/callback"
    )
    return client_id, client_secret, redirect_uri

def get_oauth_authorization_url(workspace_id: int = 1, redirect_uri: str = None) -> str:
    """Generates the Google OAuth 2.0 authorization URL for a specific workspace."""
    client_id, _, default_redirect = get_client_config()
    final_redirect = redirect_uri or default_redirect
    
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID is not configured in settings or environment.")

    scopes_str = "%20".join(GOOGLE_SCOPES)
    state = f"ws_{workspace_id}"
    
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={final_redirect}&"
        f"response_type=code&"
        f"scope={scopes_str}&"
        f"access_type=offline&"
        f"prompt=consent&"
        f"state={state}"
    )
    return auth_url

def exchange_code_for_tokens(code: str, redirect_uri: str = None, workspace_id: int = 1) -> dict:
    """Exchanges authorization code for access and refresh tokens and stores in database."""
    client_id, client_secret, default_redirect = get_client_config()
    final_redirect = redirect_uri or default_redirect

    if not client_id or not client_secret:
        raise ValueError("Google OAuth credentials (Client ID / Secret) are missing.")

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": final_redirect,
        "grant_type": "authorization_code"
    }

    resp = requests.post(token_url, data=data, timeout=15)
    if resp.status_code != 200:
        err_msg = resp.text
        print(f"[Google OAuth Token Exchange Error]: {resp.status_code} {err_msg}")
        return {
            "success": False,
            "error": f"Token exchange failed: {resp.status_code} - {err_msg}"
        }

    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    expiry_time = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).strftime("%Y-%m-%d %H:%M:%S")

    # Fetch user email using access token
    user_email = "connected_user@gmail.com"
    try:
        userinfo_resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        if userinfo_resp.status_code == 200:
            user_email = userinfo_resp.json().get("email", user_email)
    except Exception as e:
        print(f"[Google Userinfo Fetch Warning]: {e}")

    # Encrypt tokens for secure DB storage
    acc_enc = encrypt_token(access_token)
    ref_enc = encrypt_token(refresh_token) if refresh_token else ""

    # Preserve previous refresh token if new one wasn't returned in consent
    if not ref_enc:
        prev_conn = get_google_connection(workspace_id=workspace_id)
        if prev_conn and prev_conn.get("refresh_token_encrypted"):
            ref_enc = prev_conn["refresh_token_encrypted"]
        elif get_setting(f"google_refresh_token_ws_{workspace_id}"):
            ref_enc = get_setting(f"google_refresh_token_ws_{workspace_id}")
        elif get_setting("google_refresh_token"):
            ref_enc = get_setting("google_refresh_token")

    saved_row = save_google_connection(
        workspace_id=workspace_id,
        google_account_email=user_email,
        access_token_encrypted=acc_enc,
        refresh_token_encrypted=ref_enc,
        token_expiry=expiry_time,
        status="connected"
    )

    # Durable fallback storage in settings table
    if ref_enc:
        set_setting(f"google_refresh_token_ws_{workspace_id}", ref_enc)
        set_setting("google_refresh_token", ref_enc)
    if user_email:
        set_setting(f"google_account_email_ws_{workspace_id}", user_email)
        set_setting("google_account_email", user_email)

    return {
        "success": True,
        "workspace_id": workspace_id,
        "email": user_email,
        "masked_email": mask_email(user_email),
        "status": "connected"
    }

def get_workspace_credentials(workspace_id: int = 1) -> Optional[Credentials]:
    """Retrieves and refreshes valid google.oauth2.credentials.Credentials for the workspace."""
    conn_data = get_google_connection(workspace_id=workspace_id)
    has_token = bool(conn_data.get("access_token_encrypted") or conn_data.get("refresh_token_encrypted")) if conn_data else False

    if not conn_data or not has_token:
        # Fallback from settings/env (workspace-isolated)
        ws_ref = get_setting(f"google_refresh_token_ws_{workspace_id}")
        ws_acc = get_setting(f"google_access_token_ws_{workspace_id}")
        ws_email = get_setting(f"google_account_email_ws_{workspace_id}")
        ws_master = get_setting(f"google_master_form_id_ws_{workspace_id}")

        if workspace_id == 1:
            env_ref = ws_ref or os.getenv("GOOGLE_REFRESH_TOKEN") or get_setting("google_refresh_token")
            env_acc = ws_acc or os.getenv("GOOGLE_ACCESS_TOKEN") or get_setting("google_access_token")
            env_email = ws_email or os.getenv("GOOGLE_ACCOUNT_EMAIL") or get_setting("google_account_email") or "connected_admin@gmail.com"
            env_master = ws_master or os.getenv("GOOGLE_MASTER_FORM_ID") or get_setting("google_master_form_id") or (conn_data.get("master_form_id") if conn_data else None)
        else:
            env_ref = ws_ref
            env_acc = ws_acc
            env_email = ws_email or "connected_admin@gmail.com"
            env_master = ws_master or (conn_data.get("master_form_id") if conn_data else None)

        if env_ref or env_acc:
            save_google_connection(
                workspace_id=workspace_id,
                google_account_email=env_email,
                access_token_encrypted=encrypt_token(env_acc) if env_acc else "",
                refresh_token_encrypted=encrypt_token(env_ref) if env_ref else "",
                master_form_id=env_master,
                status="connected"
            )
            conn_data = get_google_connection(workspace_id=workspace_id)

    if not conn_data:
        return None

    access_token = decrypt_token(conn_data.get("access_token_encrypted", ""))
    refresh_token = decrypt_token(conn_data.get("refresh_token_encrypted", ""))

    client_id, client_secret, _ = get_client_config()

    if not access_token and not refresh_token:
        return None

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=GOOGLE_SCOPES
    )

    # Check if expired or needs refresh
    if creds.expired or (not creds.token and creds.refresh_token):
        try:
            req = Request()
            creds.refresh(req)
            # Save newly refreshed access token back to DB
            if creds.token:
                save_google_connection(
                    workspace_id=workspace_id,
                    google_account_email=conn_data.get("google_account_email", ""),
                    access_token_encrypted=encrypt_token(creds.token),
                    refresh_token_encrypted=encrypt_token(creds.refresh_token or refresh_token),
                    status="connected"
                )
        except Exception as ref_err:
            print(f"[Google Token Refresh Error for Workspace {workspace_id}]: {ref_err}")
            return None

    return creds

def get_google_account_status(workspace_id: int = 1) -> dict:
    """Returns workspace-isolated Google connection diagnostics without leaking tokens."""
    conn_data = get_google_connection(workspace_id=workspace_id)
    has_token = bool(conn_data.get("access_token_encrypted") or conn_data.get("refresh_token_encrypted")) if conn_data else False

    if not conn_data or not has_token:
        # Check settings / env fallback (workspace-isolated)
        ws_ref = get_setting(f"google_refresh_token_ws_{workspace_id}")
        ws_acc = get_setting(f"google_access_token_ws_{workspace_id}")
        ws_email = get_setting(f"google_account_email_ws_{workspace_id}")
        ws_master = get_setting(f"google_master_form_id_ws_{workspace_id}")

        if workspace_id == 1:
            env_ref = ws_ref or os.getenv("GOOGLE_REFRESH_TOKEN") or get_setting("google_refresh_token")
            env_acc = ws_acc or os.getenv("GOOGLE_ACCESS_TOKEN") or get_setting("google_access_token")
            env_email = ws_email or os.getenv("GOOGLE_ACCOUNT_EMAIL") or get_setting("google_account_email")
            env_master = ws_master or os.getenv("GOOGLE_MASTER_FORM_ID") or get_setting("google_master_form_id") or (conn_data.get("master_form_id") if conn_data else None)
        else:
            env_ref = ws_ref
            env_acc = ws_acc
            env_email = ws_email
            env_master = ws_master or (conn_data.get("master_form_id") if conn_data else None)

        if env_ref or env_acc:
            save_google_connection(
                workspace_id=workspace_id,
                google_account_email=env_email or "connected_admin@gmail.com",
                access_token_encrypted=encrypt_token(env_acc) if env_acc else "",
                refresh_token_encrypted=encrypt_token(env_ref) if env_ref else "",
                master_form_id=env_master,
                status="connected"
            )
            conn_data = get_google_connection(workspace_id=workspace_id)

    if not conn_data:
        return {
            "connected": False,
            "workspace_id": workspace_id,
            "google_account_email": None,
            "masked_email": None,
            "status": "not_connected",
            "connection_message": "Google Account is not connected.",
            "drive_connected": False,
            "forms_connected": False,
            "sheets_connected": False,
            "master_status": "not_configured",
            "master_message": "Master Form is not configured.",
            "master_form_id": None,
            "master_form_name": None,
            "master_form_url": None,
            "master_edit_url": None,
            "master_sheet_id": None,
            "master_sheet_url": None,
            "master_has_file_upload": False,
            "master_verified_at": None,
            "drive_root_folder_id": None
        }

    email = conn_data.get("google_account_email", "")
    master_form_id = conn_data.get("master_form_id", "")
    has_token = bool(conn_data.get("access_token_encrypted") or conn_data.get("refresh_token_encrypted"))
    is_connected = has_token and conn_data.get("status") == "connected"

    master_sheet_id = conn_data.get("master_sheet_id") or ""
    sheet_url = conn_data.get("master_sheet_url") or (f"https://docs.google.com/spreadsheets/d/{master_sheet_id}/edit" if master_sheet_id else None)
    form_url = conn_data.get("master_form_url") or (f"https://docs.google.com/forms/d/{master_form_id}/viewform" if master_form_id else None)
    edit_url = conn_data.get("master_edit_url") or (f"https://docs.google.com/forms/d/{master_form_id}/edit" if master_form_id else None)

    return {
        "connected": is_connected,
        "workspace_id": workspace_id,
        "google_account_email": email,
        "masked_email": mask_email(email) if email else None,
        "status": conn_data.get("status", "connected") if is_connected else "not_connected",
        "connection_message": "Google Account is connected." if is_connected else "Google Account is not connected.",
        "drive_connected": is_connected,
        "forms_connected": is_connected,
        "sheets_connected": is_connected,
        "master_status": "configured" if master_form_id else "not_configured",
        "master_message": "Master Form is configured and active." if master_form_id else "Master Form is not configured.",
        "master_form_id": master_form_id or None,
        "master_form_name": conn_data.get("master_form_name") or ("ID Card Information Form" if master_form_id else None),
        "master_form_url": form_url,
        "master_edit_url": edit_url,
        "master_sheet_id": master_sheet_id or None,
        "master_sheet_url": sheet_url,
        "master_has_file_upload": bool(conn_data.get("master_has_file_upload", 0)),
        "master_verified_at": conn_data.get("master_verified_at"),
        "drive_root_folder_id": conn_data.get("drive_root_folder_id", "") or None,
        "last_updated": conn_data.get("updated_at", "")
    }
