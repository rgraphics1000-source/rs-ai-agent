import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.database import (
    get_google_connection, update_google_master_ids, delete_google_connection,
    get_generated_forms, get_generated_form_by_id, get_google_form_fields,
    save_google_form_field, delete_google_form_field, get_form_submissions,
    get_institutions, get_whatsapp_account_by_workspace_id
)
from app.google_integration.oauth_service import (
    get_oauth_authorization_url, exchange_code_for_tokens, get_google_account_status
)
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

class MasterFormSelectRequest(BaseModel):
    workspace_id: int = 1
    master_form_id: str
    master_sheet_id: Optional[str] = None

class CreateFormRequest(BaseModel):
    workspace_id: int = 1
    institution_name: str
    custom_description: Optional[str] = None
    institution_phone: Optional[str] = None
    allow_duplicate: Optional[bool] = False

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

@router.get("/auth/start")
def start_oauth(workspace_id: int = Query(1), redirect_uri: Optional[str] = None):
    """Generates Google OAuth 2.0 URL for connecting Google Account."""
    try:
        auth_url = get_oauth_authorization_url(workspace_id=workspace_id, redirect_uri=redirect_uri)
        return {"success": True, "auth_url": auth_url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/auth/callback")
def oauth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """Handles Google OAuth callback, exchanges code for tokens, and returns friendly HTML redirect."""
    if error:
        return HTMLResponse(content=f"<h3>Google Authentication Failed: {error}</h3><p><a href='/'>Return to Dashboard</a></p>")

    if not code:
        return HTMLResponse(content="<h3>Missing authorization code.</h3><p><a href='/'>Return to Dashboard</a></p>")

    # Parse workspace_id from state (e.g. ws_1)
    workspace_id = 1
    if state and state.startswith("ws_"):
        try:
            workspace_id = int(state.split("_")[1])
        except Exception:
            workspace_id = 1

    try:
        res = exchange_code_for_tokens(code=code, workspace_id=workspace_id)
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
            return HTMLResponse(content=f"<h3>Token Exchange Failed: {res.get('error')}</h3><p><a href='/'>Return</a></p>")
    except Exception as e:
        return HTMLResponse(content=f"<h3>Exception: {str(e)}</h3><p><a href='/'>Return</a></p>")

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

@router.post("/forms/create")
def create_form(payload: CreateFormRequest):
    """Creates a new institution Google Form based on the workspace Master Form."""
    try:
        res = create_institution_form(
            workspace_id=payload.workspace_id,
            institution_name=payload.institution_name,
            custom_description=payload.custom_description,
            institution_phone=payload.institution_phone,
            allow_duplicate=payload.allow_duplicate or False
        )
        return res
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Form creation failed: {str(e)}")

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
