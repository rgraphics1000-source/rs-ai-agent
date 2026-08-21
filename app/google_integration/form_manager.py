import time
import json
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
    institution_mobile: str = None,
    template_id: int = None,
    custom_description: str = None,
    fields: List[dict] = None,
    selected_fields: List[Any] = None,
    institution_phone: str = None,
    allow_duplicate: bool = False
) -> dict:
    """
    Main Business Service:
    Clones the configured Workspace Master Form, customizes it for the institution,
    preserves File Upload, sets up Google Sheets & Drive folders, and returns public URL.
    Identifies institution by BOTH Name and Mobile Number.
    """
    ws_id = int(workspace_id or 1)
    clean_inst_name = str(institution_name or "").strip()
    raw_mobile = str(institution_mobile or institution_phone or "").strip()
    
    if not clean_inst_name:
        raise ValueError("প্রতিষ্ঠানের নাম প্রদান করা বাধ্যতামূলক।")
    if not raw_mobile:
        raise ValueError("প্রতিষ্ঠানের মোবাইল নম্বর প্রদান করা বাধ্যতামূলক।")

    from app.database import normalize_bd_mobile, get_institution_by_mobile
    canonical_mobile = normalize_bd_mobile(raw_mobile)
    if not canonical_mobile or len(canonical_mobile) < 6:
        raise ValueError("সঠিক মোবাইল নম্বর প্রদান করুন (যেমন: 01712345678)।")

    # 1. Check if an institution / form with this mobile number already exists in this workspace
    existing_form = get_generated_form_by_institution(workspace_id=ws_id, institution_name=clean_inst_name, institution_mobile=canonical_mobile)

    if existing_form and not allow_duplicate:
        return {
            "success": True,
            "is_existing": True,
            "workspace_id": ws_id,
            "institution_id": existing_form.get("institution_id"),
            "institution_name": clean_inst_name,
            "institution_mobile": canonical_mobile,
            "form_id": existing_form["form_id"],
            "form_title": existing_form.get("form_title") or f"{clean_inst_name} - {canonical_mobile} - ID Card Form",
            "sheet_title": existing_form.get("sheet_title") or f"{clean_inst_name} - {canonical_mobile} - ID Card Responses",
            "form_url": existing_form["form_url"],
            "responder_url": existing_form.get("responder_uri") or existing_form["form_url"],
            "edit_url": existing_form.get("edit_url"),
            "sheet_url": existing_form.get("response_sheet_url"),
            "drive_folder_id": existing_form.get("drive_folder_id"),
            "selected_fields": existing_form.get("selected_fields"),
            "message": f"এই মোবাইল নম্বরের একটি প্রতিষ্ঠান ইতোমধ্যে আছে:\n\nপ্রতিষ্ঠান: {clean_inst_name}\nমোবাইল: {canonical_mobile}\n\nপূর্বের তৈরি ফর্মটি ব্যবহার করতে পারেন অথবা নতুন ফর্ম তৈরি করুন।"
        }

    # 2. Validate Google connection and Master Form ID
    conn_data = get_google_connection(workspace_id=ws_id)
    if not conn_data or conn_data.get("status") != "connected":
        raise PermissionError(f"Workspace {ws_id} এ কোনো সচল Google Account কানেক্ট করা নেই। সেটিংস থেকে Google কানেক্ট করুন।")

    master_form_id = conn_data.get("master_form_id")
    if not master_form_id:
        raise ValueError(f"Workspace {ws_id} এ কোনো Master ID Card Form ID সিলেক্ট করা নেই। Google Integration সেকশন থেকে Master Form সেট করুন।")

    # 3. Create or get Institution Folder in Google Drive (Tagged with mobile number)
    root_folder_id = get_or_create_workspace_root_folder(workspace_id=ws_id)
    inst_folder_id = get_or_create_institution_folder(
        workspace_id=ws_id,
        institution_name=clean_inst_name,
        institution_mobile=canonical_mobile,
        parent_folder_id=root_folder_id
    )

    # 4. Save/update institution profile record
    inst_record = save_institution(
        workspace_id=ws_id,
        name=clean_inst_name,
        phone=canonical_mobile,
        institution_mobile=canonical_mobile,
        drive_folder_id=inst_folder_id
    )

    # 5. Clone Master Form using Google Drive API (Tagged with mobile number)
    form_title = f"{clean_inst_name} - {canonical_mobile} - ID Card Form"
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
        institution_mobile=canonical_mobile,
        custom_description=custom_description,
        fields=fields,
        selected_fields=selected_fields
    )

    responder_url = custom_res.get("responder_url") or get_responder_url(ws_id, cloned_form_id)
    edit_url = custom_res.get("edit_url") or f"https://docs.google.com/forms/d/{cloned_form_id}/edit"
    final_selected_fields = custom_res.get("selected_fields") or selected_fields or []

    # 7. Create dedicated Google Response Sheet in the institution's folder (Tagged with mobile number)
    sheet_data = {}
    try:
        sheet_data = create_institution_response_sheet(
            workspace_id=ws_id,
            institution_name=clean_inst_name,
            institution_mobile=canonical_mobile,
            folder_id=inst_folder_id
        )
    except Exception as s_err:
        print(f"[Sheets creation warning for {clean_inst_name}]: {s_err}")

    sheet_title = sheet_data.get("title") or f"{clean_inst_name} - {canonical_mobile} - ID Card Responses"

    # 8. Save generated form record in database
    selected_fields_str = json.dumps(final_selected_fields, ensure_ascii=False) if isinstance(final_selected_fields, (list, dict)) else str(final_selected_fields or "")
    saved_form = save_generated_form(
        workspace_id=ws_id,
        institution_name=clean_inst_name,
        institution_mobile=canonical_mobile,
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
        "institution_id": inst_record.get("id"),
        "institution_name": clean_inst_name,
        "institution_mobile": canonical_mobile,
        "form_id": cloned_form_id,
        "form_title": form_title,
        "sheet_title": sheet_title,
        "form_url": responder_url,
        "responder_url": responder_url,
        "edit_url": edit_url,
        "sheet_url": sheet_data.get("sheet_url"),
        "drive_folder_id": inst_folder_id,
        "selected_fields": final_selected_fields,
        "message": f"'{clean_inst_name}' এর জন্য নতুন Google Form ও Google Sheet সফলভাবে তৈরি হয়েছে।"
    }

def send_form_link_via_whatsapp(
    workspace_id: int,
    form_id: str,
    recipient_phone: str,
    custom_message: str = None
) -> dict:
    """
    Sends the generated Google Form URL directly to the customer's WhatsApp.
    Uses the multi-tenant workspace WhatsApp configuration safely.
    """
    ws_id = int(workspace_id or 1)
    form_meta = get_generated_form_by_id(form_id)
    if not form_meta:
        raise ValueError(f"Form ID '{form_id}' পাওয়া যায়নি।")

    inst_name = form_meta.get("institution_name", "প্রতিষ্ঠান")
    form_url = form_meta.get("responder_uri") or form_meta.get("form_url")
    inst_mobile = form_meta.get("institution_mobile", "")

    # Format selected fields summary for WhatsApp message
    fields_list_str = ""
    try:
        raw_sf = form_meta.get("selected_fields")
        if raw_sf:
            sf_keys = json.loads(raw_sf) if isinstance(raw_sf, str) and raw_sf.startswith("[") else []
            from app.google_integration.ai_tool import STANDARD_ID_CARD_FIELDS
            labels = []
            for k in sf_keys:
                for std_f in STANDARD_ID_CARD_FIELDS:
                    if std_f["key"] == k:
                        labels.append(f"• {std_f['label']}")
                        break
            if labels:
                fields_list_str = "\n\nফর্মে যে তথ্যগুলো নেওয়া হবে:\n" + "\n".join(labels)
    except Exception:
        pass

    if custom_message:
        message_body = custom_message
    else:
        mobile_tag = f" ({inst_mobile})" if inst_mobile else ""
        message_body = (
            f"আসসালামু আলাইকুম।\n\n"
            f"*{inst_name}*{mobile_tag}-এর জন্য ID Card Form প্রস্তুত করা হয়েছে।{fields_list_str}\n\n"
            f"📝 ফর্ম লিংক:\n{form_url}\n\n"
            f"অনুগ্রহ করে শিক্ষার্থীদের সঠিক তথ্য ও ছবি আপলোড করুন।"
        )

    from app.channels.whatsapp import send_whatsapp_message, normalize_phone_number
    normalized_recip = normalize_phone_number(recipient_phone)
    if not normalized_recip:
        raise ValueError("সঠিক প্রাপকের ফোন নম্বর প্রদান করুন।")

    wa_acc = get_whatsapp_account_by_workspace_id(ws_id)
    phone_number_id = wa_acc.get("phone_number_id") if wa_acc else None

    send_success = send_whatsapp_message(
        to_number=normalized_recip,
        message_text=message_body,
        phone_id=phone_number_id,
        workspace_id=ws_id
    )

    if not send_success:
        raise RuntimeError("WhatsApp বার্তা প্রেরণ ব্যর্থ হয়েছে। অনুগ্রহ করে WhatsApp কানেকশন ও টোকেন চেক করুন।")

    return {
        "success": True,
        "recipient_phone": normalized_recip,
        "message_preview": message_body,
        "form_url": form_url
    }
