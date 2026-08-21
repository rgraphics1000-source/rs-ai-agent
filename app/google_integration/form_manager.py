import time
from typing import Optional, Dict, Any, List, Tuple

from app.database import (
    get_google_connection, get_generated_form_by_id, get_generated_form_by_institution,
    save_generated_form, save_institution, get_google_form_fields,
    get_whatsapp_account_by_workspace_id
)
from app.google_integration.drive_service import (
    get_or_create_workspace_root_folder, get_or_create_institution_folder,
    copy_master_form_file, verify_file_accessible
)
from app.google_integration.forms_service import (
    customize_cloned_institution_form, get_responder_url
)
from app.google_integration.sheets_service import create_institution_response_sheet

def create_institution_form(
    workspace_id: int,
    institution_name: str,
    template_id: int = None,
    custom_description: str = None,
    fields: List[dict] = None,
    institution_phone: str = None,
    allow_duplicate: bool = False
) -> dict:
    """
    Main Business Service:
    Clones the configured Workspace Master Form, customizes it for the institution,
    preserves File Upload, sets up Google Sheets & Drive folders, and returns public URL.
    """
    ws_id = int(workspace_id or 1)
    clean_inst_name = str(institution_name).strip()
    if not clean_inst_name:
        raise ValueError("Institution name is required.")

    # 1. Check if form already exists for this institution under this workspace
    if not allow_duplicate:
        existing = get_generated_form_by_institution(workspace_id=ws_id, institution_name=clean_inst_name)
        if existing:
            return {
                "success": True,
                "is_existing": True,
                "workspace_id": ws_id,
                "institution_name": clean_inst_name,
                "form_id": existing["form_id"],
                "form_url": existing["form_url"],
                "responder_url": existing.get("responder_uri") or existing["form_url"],
                "edit_url": existing.get("edit_url"),
                "sheet_url": existing.get("response_sheet_url"),
                "drive_folder_id": existing.get("drive_folder_id"),
                "message": f"'{clean_inst_name}' এর জন্য পূর্বেই ফর্ম তৈরি করা আছে।"
            }

    # 2. Validate Google connection and Master Form ID
    conn_data = get_google_connection(workspace_id=ws_id)
    if not conn_data or conn_data.get("status") != "connected":
        raise PermissionError(f"Workspace {ws_id} এ কোনো সচল Google Account কানেক্ট করা নেই। সেটিংস থেকে Google কানেক্ট করুন।")

    master_form_id = conn_data.get("master_form_id")
    if not master_form_id:
        raise ValueError(f"Workspace {ws_id} এ কোনো Master ID Card Form ID সিলেক্ট করা নেই। Google Integration সেকশন থেকে Master Form সেট করুন।")

    # 3. Create or get Institution Folder in Google Drive
    root_folder_id = get_or_create_workspace_root_folder(workspace_id=ws_id)
    inst_folder_id = get_or_create_institution_folder(
        workspace_id=ws_id,
        institution_name=clean_inst_name,
        parent_folder_id=root_folder_id
    )

    # 4. Save/update institution profile record
    inst_record = save_institution(
        workspace_id=ws_id,
        name=clean_inst_name,
        phone=institution_phone,
        drive_folder_id=inst_folder_id
    )

    # 5. Clone Master Form using Google Drive API (Preserves File Upload binding!)
    form_title = f"{clean_inst_name} - ID Card Information"
    copy_result = copy_master_form_file(
        workspace_id=ws_id,
        master_form_id=master_form_id,
        new_title=form_title,
        destination_folder_id=inst_folder_id
    )
    cloned_form_id = copy_result["form_id"]

    # 6. Customize Form Title, Description, and dynamic Questions
    custom_res = customize_cloned_institution_form(
        workspace_id=ws_id,
        form_id=cloned_form_id,
        institution_name=clean_inst_name,
        custom_description=custom_description,
        fields=fields
    )

    responder_url = custom_res.get("responder_url") or get_responder_url(ws_id, cloned_form_id)
    edit_url = custom_res.get("edit_url") or f"https://docs.google.com/forms/d/{cloned_form_id}/edit"

    # 7. Create dedicated Google Response Sheet in the institution's folder
    sheet_data = {}
    try:
        sheet_data = create_institution_response_sheet(
            workspace_id=ws_id,
            institution_name=clean_inst_name,
            folder_id=inst_folder_id
        )
    except Exception as s_err:
        print(f"[Sheets creation warning for {clean_inst_name}]: {s_err}")

    # 8. Save generated form record in database
    saved_form = save_generated_form(
        workspace_id=ws_id,
        institution_name=clean_inst_name,
        form_id=cloned_form_id,
        form_url=responder_url,
        responder_uri=responder_url,
        edit_url=edit_url,
        template_id=template_id,
        institution_id=inst_record.get("id"),
        drive_folder_id=inst_folder_id,
        response_destination_id=sheet_data.get("spreadsheet_id"),
        response_sheet_url=sheet_data.get("sheet_url"),
        status="active"
    )

    return {
        "success": True,
        "is_existing": False,
        "workspace_id": ws_id,
        "institution_name": clean_inst_name,
        "form_id": cloned_form_id,
        "form_url": responder_url,
        "responder_url": responder_url,
        "edit_url": edit_url,
        "sheet_url": sheet_data.get("sheet_url"),
        "drive_folder_id": inst_folder_id,
        "message": f"'{clean_inst_name}' এর জন্য সফলভাবে Google Form ও Google Sheet তৈরি সম্পন্ন হয়েছে।"
    }

def send_form_link_via_whatsapp(
    workspace_id: int,
    form_id: str,
    recipient_phone: str,
    custom_message: str = None
) -> dict:
    """
    Sends the generated Google Form URL directly via the Workspace's WhatsApp account.
    Strictly isolated to the workspace's WhatsApp configuration.
    """
    ws_id = int(workspace_id or 1)
    gen_form = get_generated_form_by_id(form_id)
    if not gen_form:
        return {"success": False, "error": f"Form ID '{form_id}' not found."}

    if int(gen_form.get("workspace_id") or 1) != ws_id:
        raise PermissionError("Access denied: Form belongs to another workspace.")

    inst_name = gen_form.get("institution_name", "প্রতিষ্ঠান")
    form_url = gen_form.get("responder_uri") or gen_form.get("form_url")

    from app.channels.whatsapp import send_whatsapp_message_detailed, normalize_whatsapp_phone_number
    clean_phone = normalize_whatsapp_phone_number(recipient_phone)
    if not clean_phone:
        return {"success": False, "error": "Invalid phone number provided."}

    default_msg = (
        f"আসসালামু আলাইকুম।\n\n"
        f"*{inst_name}* এর আইডি কার্ড (ID Card) তথ্য ও ছবি সংগ্রহের জন্য গুগল ফর্ম প্রস্তুত করা হয়েছে।\n\n"
        f"📝 ফর্ম লিংক:\n{form_url}\n\n"
        f"অনুগ্রহ করে ফর্মটিতে শিক্ষার্থীদের সঠিক তথ্য ও ছবি আপলোড করুন।"
    )
    final_message = custom_message or default_msg

    # Send using workspace WhatsApp account
    send_res = send_whatsapp_message_detailed(
        to_number=clean_phone,
        message_text=final_message,
        workspace_id=ws_id
    )

    return {
        "success": bool(send_res.get("success", False)),
        "workspace_id": ws_id,
        "recipient_phone": clean_phone,
        "delivery_result": send_res
    }
