import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.database import (
    get_google_connection, update_google_master_ids, delete_google_connection,
    save_google_connection, get_setting, set_setting,
    get_generated_forms, get_generated_form_by_id, get_google_form_fields,
    save_google_form_field, delete_google_form_field, get_form_submissions,
    get_institutions, get_whatsapp_account_by_workspace_id
)
from app.google_integration.oauth_service import (
    get_oauth_authorization_url, exchange_code_for_tokens, get_google_account_status,
    get_client_config, get_workspace_credentials
)
from app.google_integration.crypto import encrypt_token
from app.google_integration.drive_service import (
    verify_file_accessible, get_drive_client
)
from app.google_integration.forms_service import get_form_details
from app.google_integration.form_manager import (
    create_institution_form, send_form_link_via_whatsapp
)
from app.google_integration.sync_service import sync_form_responses

router = APIRouter(prefix="/api/google", tags=["Google Integration"])

# --- Request Models ---
class DisconnectRequest(BaseModel):
    workspace_id: int = 1

class SaveGoogleCredentialsRequest(BaseModel):
    workspace_id: int = 1
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    refresh_token: Optional[str] = None
    account_email: Optional[str] = None
    redirect_uri: Optional[str] = None

class MasterFormSelectRequest(BaseModel):
    workspace_id: int = 1
    master_form_id: str
    master_sheet_id: Optional[str] = None

class CreateFormRequest(BaseModel):
    workspace_id: int = 1
    institution_name: str
    institution_mobile: Optional[str] = None
    institution_phone: Optional[str] = None
    custom_description: Optional[str] = None
    selected_fields: Optional[List[Any]] = None
    selected_field_keys: Optional[List[str]] = None
    allow_duplicate: Optional[bool] = False

class PreviewFieldsRequest(BaseModel):
    workspace_id: int = 1
    text: Optional[str] = None
    selected_field_keys: Optional[List[str]] = None

class SendWhatsAppRequest(BaseModel):
    workspace_id: int = 1
    recipient_phone: str
    custom_message: Optional[str] = None

class FormFieldRequest(BaseModel):
    workspace_id: int = 1
    field_key: str
    field_label: str
    field_type: str = "short_answer"
    required: int = 1
    sort_order: int = 0
    options: Optional[List[str]] = []
    field_id: Optional[int] = None

# --- Endpoints ---

@router.get("/status")
def get_status(workspace_id: int = Query(1)):
    """Returns Google integration diagnostics for the specified workspace."""
    return get_google_account_status(workspace_id=workspace_id)

@router.get("/credentials")
def get_credentials_info(request: Request, workspace_id: int = Query(1)):
    """Returns configured OAuth Client ID, Redirect URI, and status without exposing raw secrets."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    computed_redirect = f"{proto}://{host}/api/google/auth/callback"

    client_id, client_secret, default_redirect = get_client_config()
    conn_data = get_google_connection(workspace_id=workspace_id) or {}
    has_token = bool(
        conn_data.get("access_token_encrypted") 
        or conn_data.get("refresh_token_encrypted") 
        or get_setting(f"google_refresh_token_ws_{workspace_id}") 
        or get_setting("google_refresh_token")
    )

    return {
        "success": True,
        "workspace_id": workspace_id,
        "client_id": client_id,
        "has_client_id": bool(client_id),
        "has_client_secret": bool(client_secret),
        "has_refresh_token": has_token,
        "account_email": conn_data.get("google_account_email") or get_setting(f"google_account_email_ws_{workspace_id}") or get_setting("google_account_email"),
        "redirect_uri": computed_redirect,
        "default_redirect": default_redirect
    }

@router.post("/credentials")
def save_credentials(payload: SaveGoogleCredentialsRequest):
    """Saves Google OAuth Client ID/Secret or direct Refresh Token credentials."""
    try:
        ws_id = int(payload.workspace_id or 1)
        if payload.client_id is not None:
            set_setting("google_client_id", payload.client_id.strip())
        if payload.client_secret is not None:
            set_setting("google_client_secret", payload.client_secret.strip())
        if payload.redirect_uri is not None:
            set_setting("google_redirect_uri", payload.redirect_uri.strip())

        if payload.refresh_token:
            clean_token = payload.refresh_token.strip()
            enc_ref = encrypt_token(clean_token)
            email = (payload.account_email or "").strip() or "connected_admin@gmail.com"
            save_google_connection(
                workspace_id=ws_id,
                google_account_email=email,
                refresh_token_encrypted=enc_ref,
                status="connected"
            )
            set_setting(f"google_refresh_token_ws_{ws_id}", enc_ref)
            set_setting("google_refresh_token", enc_ref)
            set_setting(f"google_account_email_ws_{ws_id}", email)
            set_setting("google_account_email", email)

        return {
            "success": True,
            "message": "Google credentials updated successfully.",
            "status": get_google_account_status(workspace_id=ws_id)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/auth/start")
def start_oauth(request: Request, workspace_id: int = Query(1), redirect_uri: Optional[str] = None):
    """Generates Google OAuth 2.0 URL for connecting Google Account."""
    try:
        if not redirect_uri:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("x-forwarded-host", request.url.netloc)
            redirect_uri = f"{proto}://{host}/api/google/auth/callback"
        auth_url = get_oauth_authorization_url(workspace_id=workspace_id, redirect_uri=redirect_uri)
        return {"success": True, "auth_url": auth_url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/auth/callback")
def oauth_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Handles Google OAuth callback, exchanges code for tokens, and returns friendly HTML redirect."""
    if error:
        return HTMLResponse(content=f"<h3>Google Authentication Failed: {error}</h3><p><a href='/?tab=google-forms'>Return to Dashboard</a></p>")

    if not code:
        return HTMLResponse(content="<h3>Missing authorization code.</h3><p><a href='/?tab=google-forms'>Return to Dashboard</a></p>")

    workspace_id = 1
    if state and state.startswith("ws_"):
        try:
            workspace_id = int(state.split("_")[1])
        except Exception:
            workspace_id = 1

    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.url.netloc)
    redirect_uri = f"{proto}://{host}/api/google/auth/callback"

    try:
        res = exchange_code_for_tokens(code=code, redirect_uri=redirect_uri, workspace_id=workspace_id)
        if not res.get("success"):
            # Fallback retry with default redirect URI if mismatch
            client_id, client_secret, default_redirect = get_client_config()
            if default_redirect != redirect_uri:
                res = exchange_code_for_tokens(code=code, redirect_uri=default_redirect, workspace_id=workspace_id)

        if res.get("success"):
            return HTMLResponse(content="""
                <html>
                <head><title>Google Connected</title></head>
                <body style="font-family: sans-serif; background: #0f1523; color: #fff; text-align: center; padding-top: 50px;">
                    <div style="max-width: 450px; margin: auto; background: #1a2234; padding: 30px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1);">
                        <h2 style="color: #34d399;">✓ Google Account Connected!</h2>
                        <p style="color: #94a3b8;">আপনার গুগল একাউন্ট সফলভাবে যুক্ত হয়েছে।</p>
                        <a href="/?tab=google-forms" style="display: inline-block; margin-top: 15px; padding: 10px 20px; background: #3b82f6; color: #fff; text-decoration: none; border-radius: 6px; font-weight: 600;">ড্যাশবোর্ডে ফিরে যান</a>
                    </div>
                    <script>
                        setTimeout(function(){ window.location.href = '/?tab=google-forms'; }, 1500);
                    </script>
                </body>
                </html>
            """)
        else:
            return HTMLResponse(content=f"<h3>Token Exchange Failed: {res.get('error')}</h3><p><a href='/?tab=google-forms'>Return</a></p>")
    except Exception as e:
        return HTMLResponse(content=f"<h3>Exception: {str(e)}</h3><p><a href='/?tab=google-forms'>Return</a></p>")

@router.post("/disconnect")
def disconnect(payload: DisconnectRequest):
    """Disconnects Google Account for the workspace."""
    success = delete_google_connection(workspace_id=payload.workspace_id)
    return {"success": success, "message": "Google account disconnected successfully."}

class CreateMasterTemplateRequest(BaseModel):
    workspace_id: int = 1
    title: Optional[str] = "ID Card Information Form"
    description: Optional[str] = None

class VerifyMasterFormRequest(BaseModel):
    workspace_id: int = 1
    master_form_id: str

@router.get("/master-forms")
def list_master_forms(workspace_id: int = Query(1)):
    """Lists available Google Forms in the connected Google Drive for selection as Master Form."""
    try:
        drive = get_drive_client(workspace_id=workspace_id)
        query = "mimeType = 'application/vnd.google-apps.form' and trashed = false"
        res = drive.files().list(q=query, spaces="drive", fields="files(id, name, webViewLink, createdTime)", pageSize=30).execute()
        files = res.get("files", [])
        return {"success": True, "forms": files}
    except Exception as e:
        return {"success": False, "error": str(e), "forms": []}

@router.get("/master-forms/templates")
def list_master_templates(workspace_id: int = Query(1)):
    """Lists configured Master Form Templates for the workspace from database."""
    from app.database import get_master_form_templates
    templates = get_master_form_templates(workspace_id=workspace_id)
    return {"success": True, "templates": templates}

@router.post("/master-forms/create-template")
def create_master_template(payload: CreateMasterTemplateRequest):
    """Creates a base Master Google Form in Google Drive with reusable questions and response sheet."""
    from app.google_integration.forms_service import create_base_master_form_template
    try:
        res = create_base_master_form_template(
            workspace_id=payload.workspace_id,
            title=payload.title,
            description=payload.description
        )
        return res
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Master template creation failed: {str(e)}")

@router.post("/master-forms/verify")
def verify_master_form_endpoint(payload: VerifyMasterFormRequest):
    """Live verifies a Master Google Form ID (accessibility, File Upload question, response sheet)."""
    from app.google_integration.forms_service import inspect_and_verify_master_form
    res = inspect_and_verify_master_form(workspace_id=payload.workspace_id, form_id=payload.master_form_id)
    if not res.get("valid"):
        raise HTTPException(status_code=400, detail=res.get("error", "Master Form verification failed."))
    return res

@router.post("/master-forms/select")
def select_master_form(payload: MasterFormSelectRequest):
    """Sets, verifies, and binds the Master Form ID for the workspace."""
    from app.google_integration.forms_service import inspect_and_verify_master_form
    res = inspect_and_verify_master_form(workspace_id=payload.workspace_id, form_id=payload.master_form_id)
    if not res.get("valid"):
        raise HTTPException(status_code=400, detail=res.get("error", "Master Form is inaccessible or invalid."))

    return {
        "success": True,
        "master_form_id": payload.master_form_id,
        "master_form_name": res.get("form_name"),
        "master_form_url": res.get("form_url"),
        "master_edit_url": res.get("edit_url"),
        "master_sheet_id": res.get("spreadsheet_id"),
        "master_sheet_url": res.get("spreadsheet_url"),
        "has_file_upload": res.get("has_file_upload"),
        "items_count": res.get("items_count"),
        "message": res.get("message") or f"Master Form '{res.get('form_name')}' successfully configured and verified."
    }

@router.get("/fields/standard")
def get_standard_fields():
    """Returns the approved immutable standard ID card fields catalog."""
    from app.google_integration.ai_tool import get_standard_fields_catalog
    return {"success": True, "fields": get_standard_fields_catalog()}

@router.post("/forms/preview-fields")
def preview_fields(payload: PreviewFieldsRequest):
    """Extracts standard fields from natural language text or field keys for preview."""
    from app.google_integration.ai_tool import detect_fields_from_natural_language, get_standard_fields_catalog, STANDARD_ID_CARD_FIELDS
    
    if payload.text and payload.text.strip():
        detected = detect_fields_from_natural_language(payload.text)
    elif payload.selected_field_keys:
        std_map = {f["key"]: f for f in STANDARD_ID_CARD_FIELDS}
        detected = [
            {"key": std_map[k]["key"], "label": std_map[k]["label"], "type": std_map[k]["type"], "required": std_map[k]["required"]}
            for k in payload.selected_field_keys if k in std_map
        ]
    else:
        default_keys = ["student_name", "father_name", "class_name", "roll", "student_photo"]
        detected = [f for f in get_standard_fields_catalog() if f["key"] in default_keys]
        
    return {
        "success": True,
        "fields": detected,
        "field_keys": [f["key"] for f in detected]
    }

@router.post("/forms/create")
@router.post("/forms/generate")
def create_form(payload: CreateFormRequest):
    """Creates a new institution Google Form based on the workspace Master Form."""
    try:
        mobile = payload.institution_mobile or payload.institution_phone
        selected = payload.selected_fields or payload.selected_field_keys
        res = create_institution_form(
            workspace_id=payload.workspace_id,
            institution_name=payload.institution_name,
            institution_mobile=mobile,
            custom_description=payload.custom_description,
            selected_fields=selected,
            allow_duplicate=payload.allow_duplicate or False
        )
        return res
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Form creation failed: {str(e)}")

@router.get("/institutions/search")
def search_institution_by_mobile(mobile: str = Query(...), workspace_id: int = Query(1)):
    """Searches institution profile and generated forms by mobile number in a workspace."""
    from app.database import search_institutions_and_forms_by_mobile
    result = search_institutions_and_forms_by_mobile(workspace_id=workspace_id, mobile=mobile)
    return {
        "success": True,
        "workspace_id": workspace_id,
        "query_mobile": mobile,
        **result
    }

@router.get("/forms")
def list_forms(workspace_id: int = Query(1)):
    """Lists all generated institution forms for the workspace."""
    forms = get_generated_forms(workspace_id=workspace_id)
    return {"success": True, "forms": forms}

@router.get("/forms/{form_id}")
def get_form(form_id: str, workspace_id: int = Query(1)):
    """Retrieves metadata of a single generated form."""
    form = get_generated_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Form not found.")
    if int(form.get("workspace_id") or 1) != int(workspace_id):
        raise HTTPException(status_code=403, detail="Access denied: Form belongs to another workspace.")
    return {"success": True, "form": form}

@router.post("/forms/{form_id}/sync")
def sync_responses(form_id: str, workspace_id: int = Query(1)):
    """Manually triggers synchronization of student responses from Google Forms API."""
    try:
        res = sync_form_responses(workspace_id=workspace_id, form_id=form_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Response sync failed: {str(e)}")

@router.get("/forms/{form_id}/responses")
def get_responses(form_id: str, workspace_id: int = Query(1)):
    """Lists all imported student submissions and uploaded photo links for a form."""
    submissions = get_form_submissions(form_id=form_id, workspace_id=workspace_id)
    return {"success": True, "submissions": submissions, "count": len(submissions)}

@router.post("/forms/{form_id}/send-whatsapp")
def send_whatsapp(form_id: str, payload: SendWhatsAppRequest):
    """Sends the Google Form URL to the client via the workspace's WhatsApp account."""
    try:
        res = send_form_link_via_whatsapp(
            workspace_id=payload.workspace_id,
            form_id=form_id,
            recipient_phone=payload.recipient_phone,
            custom_message=payload.custom_message
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/fields")
def list_fields(workspace_id: int = Query(1)):
    """Lists dynamic form questions/fields for the workspace."""
    fields = get_google_form_fields(workspace_id=workspace_id)
    return {"success": True, "fields": fields}

@router.post("/fields")
def save_field(payload: FormFieldRequest):
    """Adds or edits a dynamic form field."""
    res = save_google_form_field(
        workspace_id=payload.workspace_id,
        field_key=payload.field_key,
        field_label=payload.field_label,
        field_type=payload.field_type,
        required=payload.required,
        sort_order=payload.sort_order,
        options_json=json.dumps(payload.options or [], ensure_ascii=False),
        field_id=payload.field_id
    )
    return {"success": True, "field": res}

@router.delete("/fields/{field_id}")
def delete_field(field_id: int, workspace_id: int = Query(1)):
    """Deletes a custom form field."""
    success = delete_google_form_field(field_id=field_id, workspace_id=workspace_id)
    return {"success": success}
