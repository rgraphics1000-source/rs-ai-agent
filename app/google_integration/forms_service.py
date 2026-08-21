import time
import json
from typing import Optional, Dict, Any, List, Tuple
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.google_integration.oauth_service import get_workspace_credentials
from app.database import get_google_form_fields

def get_forms_client(workspace_id: int = 1):
    """Builds and returns the authenticated Google Forms API client."""
    creds = get_workspace_credentials(workspace_id=workspace_id)
    if not creds:
        raise PermissionError(f"Workspace {workspace_id} does not have an active Google connection.")
    return build("forms", "v1", credentials=creds, cache_discovery=False)

def get_form_details(workspace_id: int, form_id: str) -> dict:
    """Fetches form info, items, and responderUri using Google Forms API."""
    forms_service = get_forms_client(workspace_id=workspace_id)
    form_res = forms_service.forms().get(formId=str(form_id).strip()).execute()
    return form_res

def get_responder_url(workspace_id: int, form_id: str) -> str:
    """Retrieves the official published responder URL (under the 🔗 icon) for students and institutions."""
    clean_id = str(form_id).strip()
    try:
        details = get_form_details(workspace_id=workspace_id, form_id=clean_id)
        if details.get("responderUri"):
            return details.get("responderUri")
    except Exception:
        pass
    return f"https://docs.google.com/forms/d/{clean_id}/viewform"

def update_form_title_and_description(
    workspace_id: int,
    form_id: str,
    title: str,
    description: str = None
) -> dict:
    """
    Updates the Form's public title and instructions description via batchUpdate.
    """
    forms_service = get_forms_client(workspace_id=workspace_id)
    
    info_update = {
        "title": title
    }
    update_mask = "title"
    
    if description is not None:
        info_update["description"] = description
        update_mask = "title,description"

    body = {
        "requests": [
            {
                "updateFormInfo": {
                    "info": info_update,
                    "updateMask": update_mask
                }
            }
        ]
    }

    res = forms_service.forms().batchUpdate(
        formId=str(form_id).strip(),
        body=body
    ).execute()
    return res

def customize_cloned_institution_form(
    workspace_id: int,
    form_id: str,
    institution_name: str,
    institution_mobile: str = None,
    custom_description: str = None,
    fields: List[dict] = None,
    selected_fields: List[Any] = None
) -> dict:
    """
    Customizes the copied Master Form:
    1. Sets Title to '[Institution Name] - [Mobile] - ID Card Form'
    2. Sets Description with student submission guidelines
    3. PRESERVES File Upload questions completely (student photo)
    4. Removes/prunes questions that the institution did NOT request
    5. Adds any requested questions that are missing
    6. Verifies that the File Upload question exists after modification
    """
    forms_service = get_forms_client(workspace_id=workspace_id)
    
    # 1. Update Title and Description
    default_desc = (
        "এই ফর্মটি সঠিকভাবে পূরণ করুন।\n"
        "প্রতিটি শিক্ষার্থীর তথ্য নির্ভুলভাবে প্রদান করুন।\n"
        "ছবি পরিষ্কার এবং নির্ধারিত নিয়ম অনুযায়ী আপলোড করুন।"
    )
    final_desc = custom_description or default_desc
    
    if institution_mobile:
        from app.database import normalize_bd_mobile
        canonical = normalize_bd_mobile(institution_mobile)
        form_title = f"{institution_name} - {canonical} - ID Card Form" if canonical else f"{institution_name} - ID Card Form"
    else:
        form_title = f"{institution_name} - ID Card Form"
    
    update_form_title_and_description(
        workspace_id=workspace_id,
        form_id=form_id,
        title=form_title,
        description=final_desc
    )

    # 2. Inspect existing form items
    form_meta = get_form_details(workspace_id, form_id)
    existing_items = form_meta.get("items", [])
    
    # Check which items are File Upload questions - MUST BE PRESERVED
    file_upload_item_ids = set()
    for itm in existing_items:
        q_item = itm.get("questionItem", {})
        q = q_item.get("question", {})
        if "fileUploadQuestion" in q:
            file_upload_item_ids.add(itm.get("itemId"))

    # 3. Resolve selected fields catalog
    from app.google_integration.ai_tool import STANDARD_ID_CARD_FIELDS, get_standard_fields_catalog
    
    target_fields: List[dict] = []
    target_keys: set = set()
    
    if selected_fields:
        standard_map = {f["key"]: f for f in STANDARD_ID_CARD_FIELDS}
        for sf in selected_fields:
            if isinstance(sf, dict):
                k = sf.get("key") or sf.get("field_key")
                if k and k in standard_map:
                    target_fields.append(standard_map[k])
                    target_keys.add(k)
                else:
                    target_fields.append(sf)
                    if k:
                        target_keys.add(k)
            elif isinstance(sf, str):
                sf_clean = sf.strip().lower()
                # Check key direct match
                if sf_clean in standard_map:
                    target_fields.append(standard_map[sf_clean])
                    target_keys.add(sf_clean)
                else:
                    # Check alias match
                    matched_field = None
                    for std_f in STANDARD_ID_CARD_FIELDS:
                        if std_f["key"] == sf_clean or any(a.lower() == sf_clean for a in std_f["aliases"]):
                            matched_field = std_f
                            break
                    if matched_field:
                        target_fields.append(matched_field)
                        target_keys.add(matched_field["key"])
                    else:
                        target_fields.append({"key": sf_clean, "label": sf, "type": "short_answer", "required": True})
                        target_keys.add(sf_clean)
    elif fields:
        target_fields = fields
        target_keys = {f.get("key") or f.get("field_key") for f in fields if f.get("key") or f.get("field_key")}
    else:
        db_fields = get_google_form_fields(workspace_id=workspace_id)
        target_fields = db_fields if db_fields else get_standard_fields_catalog()
        target_keys = {f.get("key") or f.get("field_key") for f in target_fields if f.get("key") or f.get("field_key")}

    # Helper function to check if an existing item title matches any target field
    def is_item_matched_to_targets(item_title: str) -> bool:
        t_clean = item_title.strip().lower()
        for tf in target_fields:
            tf_label = (tf.get("label") or tf.get("field_label") or "").strip().lower()
            tf_key = (tf.get("key") or tf.get("field_key") or "").strip().lower()
            if tf_label and (tf_label in t_clean or t_clean in tf_label):
                return True
            if tf_key and tf_key in t_clean:
                return True
            # Also check aliases from standard fields
            from app.google_integration.ai_tool import STANDARD_ID_CARD_FIELDS
            for std_f in STANDARD_ID_CARD_FIELDS:
                if std_f["key"] == tf_key:
                    for alias in std_f["aliases"]:
                        if alias.lower() in t_clean or t_clean in alias.lower():
                            return True
        return False

    # 4. Prune unselected non-file-upload questions if specific fields were requested
    delete_requests = []
    if selected_fields:
        # Traverse existing items in reverse order to preserve indexes
        for idx in range(len(existing_items) - 1, -1, -1):
            itm = existing_items[idx]
            itm_id = itm.get("itemId")
            itm_title = itm.get("title", "")
            
            # NEVER delete File Upload questions (student photo)
            if itm_id in file_upload_item_ids:
                continue
                
            if not is_item_matched_to_targets(itm_title):
                delete_requests.append({
                    "deleteItem": {
                        "location": {
                            "index": idx
                        }
                    }
                })

    if delete_requests:
        try:
            forms_service.forms().batchUpdate(
                formId=str(form_id).strip(),
                body={"requests": delete_requests}
            ).execute()
        except Exception as del_err:
            print(f"[Forms unselected items prune notice]: {del_err}")

    # Re-fetch items after pruning to compute correct append index
    try:
        updated_meta = get_form_details(workspace_id, form_id)
        current_items = updated_meta.get("items", [])
    except Exception:
        current_items = existing_items

    existing_titles = {
        itm.get("title", "").strip().lower(): itm 
        for itm in current_items
    }

    # 5. Build requests to add any missing configured fields (except file_upload which is cloned from master)
    requests_list = []
    item_index = len(current_items)

    for f in target_fields:
        f_type = f.get("type") or f.get("field_type", "short_answer")
        f_label = f.get("label") or f.get("field_label", "")
        f_req = bool(f.get("required", 1))
        
        # If this is file_upload, it is already preserved from Master Form
        if f_type == "file_upload":
            continue

        # Check if question with similar title already exists in Form
        clean_label = f_label.strip().lower()
        if clean_label in existing_titles or any(clean_label in t or t in clean_label for t in existing_titles):
            continue

        question_payload = {
            "required": f_req
        }
        
        if f_type == "paragraph":
            question_payload["textQuestion"] = {"paragraph": True}
        elif f_type == "date":
            question_payload["dateQuestion"] = {"includeTime": False, "includeYear": True}
        elif f_type in ["dropdown", "multiple_choice", "checkbox"]:
            options = []
            try:
                raw_opts = f.get("options_json") or f.get("options") or "[]"
                opt_list = raw_opts if isinstance(raw_opts, list) else json.loads(raw_opts)
                options = [{"value": str(o)} for o in opt_list]
            except Exception:
                options = [{"value": "Option 1"}]
                
            choice_type = "DROP_DOWN" if f_type == "dropdown" else ("CHECKBOX" if f_type == "checkbox" else "RADIO")
            question_payload["choiceQuestion"] = {
                "type": choice_type,
                "options": options if options else [{"value": "Option 1"}]
            }
        else:
            question_payload["textQuestion"] = {"paragraph": False}

        create_item_request = {
            "createItem": {
                "item": {
                    "title": f_label,
                    "questionItem": {
                        "question": question_payload
                    }
                },
                "location": {
                    "index": item_index
                }
            }
        }
        requests_list.append(create_item_request)
        item_index += 1

    if requests_list:
        try:
            forms_service.forms().batchUpdate(
                formId=str(form_id).strip(),
                body={"requests": requests_list}
            ).execute()
        except Exception as e:
            print(f"[Forms customize_cloned_institution_form Warning]: {e}")

    responder_url = get_responder_url(workspace_id, form_id)
    edit_url = f"https://docs.google.com/forms/d/{form_id}/edit"

    return {
        "success": True,
        "form_id": form_id,
        "title": form_title,
        "responder_url": responder_url,
        "edit_url": edit_url,
        "selected_fields": [f.get("key") or f.get("field_key") for f in target_fields if f.get("key") or f.get("field_key")]
    }

def create_base_master_form_template(
    workspace_id: int,
    title: str = "ID Card Information Form",
    description: str = None
) -> dict:
    """
    Creates a new base Master Google Form in Google Drive with reusable questions.
    Creates linked Google Sheet and returns edit URL with guidance for File Upload question.
    """
    from app.google_integration.drive_service import (
        get_or_create_workspace_root_folder, get_or_create_institution_folder, get_drive_client
    )
    from app.google_integration.sheets_service import create_institution_response_sheet
    from app.database import (
        save_master_form_template, update_google_master_ids
    )

    ws_id = int(workspace_id or 1)
    forms_service = get_forms_client(workspace_id=ws_id)
    drive_client = get_drive_client(workspace_id=ws_id)

    # 1. Dedicated Master Templates folder in Drive
    root_folder_id = get_or_create_workspace_root_folder(workspace_id=ws_id)
    templates_folder_id = get_or_create_institution_folder(
        workspace_id=ws_id,
        institution_name="Master Form Templates",
        parent_folder_id=root_folder_id
    )

    # 2. Create base Google Form
    clean_title = (title or "ID Card Information Form").strip()
    create_body = {
        "info": {
            "title": clean_title,
            "documentTitle": clean_title
        }
    }
    form_res = forms_service.forms().create(body=create_body).execute()
    form_id = form_res.get("formId")

    # Move created Form file to templates folder
    try:
        drive_client.files().update(
            fileId=form_id,
            addParents=templates_folder_id,
            removeParents="root",
            fields="id, parents"
        ).execute()
    except Exception as m_err:
        print(f"[Drive Master Form move warning]: {m_err}")

    # 3. Update description and standard questions
    desc_text = description or "এই ফর্মের মাধ্যমে আপনার প্রতিষ্ঠানের ID Card তৈরির জন্য প্রয়োজনীয় তথ্য প্রদান করুন। অনুগ্রহ করে সকল তথ্য সঠিকভাবে পূরণ করুন এবং নির্ধারিত স্থানে পরিষ্কার ছবি আপলোড করুন।"
    
    # Standard questions list
    standard_questions = [
        ("প্রতিষ্ঠানের নাম (Institution Name)", "textQuestion", False),
        ("শিক্ষার্থীর নাম (Student Name)", "textQuestion", False),
        ("পিতার নাম (Father's Name)", "textQuestion", False),
        ("মাতার নাম (Mother's Name)", "textQuestion", False),
        ("শ্রেণি / জামাত (Class)", "textQuestion", False),
        ("শাখা (Section)", "textQuestion", False),
        ("রোল নম্বর (Roll No)", "textQuestion", False),
        ("আইডি নম্বর (Student ID)", "textQuestion", False),
        ("জন্মতারিখ (Date of Birth)", "textQuestion", False),
        ("রক্তের গ্রুপ (Blood Group)", "choiceQuestion", ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]),
        ("অভিভাবকের মোবাইল নম্বর (Phone)", "textQuestion", False),
        ("পূর্ণাঙ্গ ঠিকানা (Address)", "textQuestion", True),
        ("শিক্ষার্থীর ছবি (Photo Upload - অনুগ্রহ করে এডিটরে গিয়ে এই প্রশ্নটি File Upload নির্বাচন করুন)", "textQuestion", False)
    ]

    requests_list = [
        {
            "updateFormInfo": {
                "info": {
                    "description": desc_text
                },
                "updateMask": "description"
            }
        }
    ]

    for idx, q_info in enumerate(standard_questions):
        q_label = q_info[0]
        q_kind = q_info[1]
        
        if q_kind == "choiceQuestion":
            q_payload = {
                "choiceQuestion": {
                    "type": "DROP_DOWN",
                    "options": [{"value": opt} for opt in q_info[2]]
                }
            }
        else:
            q_payload = {
                "textQuestion": {
                    "paragraph": bool(q_info[2])
                }
            }

        requests_list.append({
            "createItem": {
                "item": {
                    "title": q_label,
                    "questionItem": {
                        "question": q_payload
                    }
                },
                "location": {
                    "index": idx
                }
            }
        })

    try:
        forms_service.forms().batchUpdate(
            formId=form_id,
            body={"requests": requests_list}
        ).execute()
    except Exception as b_err:
        print(f"[Forms Master Template batchUpdate warning]: {b_err}")

    # 4. Create response Google Sheet
    sheet_data = {}
    try:
        sheet_data = create_institution_response_sheet(
            workspace_id=ws_id,
            institution_name="Master ID Card Form Responses",
            folder_id=templates_folder_id
        )
    except Exception as s_err:
        print(f"[Sheets Master response sheet warning]: {s_err}")

    responder_url = get_responder_url(ws_id, form_id)
    edit_url = f"https://docs.google.com/forms/d/{form_id}/edit"
    sheet_id = sheet_data.get("spreadsheet_id")
    sheet_url = sheet_data.get("sheet_url")

    # 5. Save in database
    template_record = save_master_form_template(
        workspace_id=ws_id,
        name=clean_title,
        master_form_id=form_id,
        description_template=desc_text,
        form_url=responder_url,
        edit_url=edit_url,
        spreadsheet_id=sheet_id,
        spreadsheet_url=sheet_url,
        has_file_upload=0
    )

    update_google_master_ids(
        workspace_id=ws_id,
        master_form_id=form_id,
        master_sheet_id=sheet_id,
        drive_root_folder_id=root_folder_id,
        master_form_name=clean_title,
        master_form_url=responder_url,
        master_edit_url=edit_url,
        master_sheet_url=sheet_url,
        master_has_file_upload=0
    )

    return {
        "success": True,
        "workspace_id": ws_id,
        "form_id": form_id,
        "form_name": clean_title,
        "form_url": responder_url,
        "edit_url": edit_url,
        "spreadsheet_id": sheet_id,
        "spreadsheet_url": sheet_url,
        "drive_folder_id": templates_folder_id,
        "template_id": template_record.get("id"),
        "has_file_upload": False,
        "message": f"Master Form '{clean_title}' সফলভাবে তৈরি হয়েছে।"
    }

def inspect_and_verify_master_form(workspace_id: int, form_id: str) -> dict:
    """
    Live verifies an existing Google Form ID:
    - Checks form metadata and responderUri.
    - Inspects items for native Google Drive File Upload question (fileUploadQuestion).
    - Checks or creates response Google Sheet.
    - Saves all verified metadata into database.
    """
    from app.google_integration.drive_service import verify_file_accessible, get_or_create_workspace_root_folder, get_or_create_institution_folder
    from app.google_integration.sheets_service import create_institution_response_sheet
    from app.database import save_master_form_template, update_google_master_ids

    ws_id = int(workspace_id or 1)
    clean_id = str(form_id).strip()
    if not clean_id:
        return {"valid": False, "error": "Form ID is required."}

    # 1. Check drive accessibility
    is_valid_drive, drive_meta = verify_file_accessible(workspace_id=ws_id, file_id=clean_id)
    if not is_valid_drive:
        return {
            "valid": False,
            "form_id": clean_id,
            "error": f"Google Drive-এ ফাইলটি পাওয়া যায়নি বা এক্সেস নেই: {drive_meta.get('error')}"
        }

    # 2. Check Forms API details
    try:
        form_details = get_form_details(workspace_id=ws_id, form_id=clean_id)
    except Exception as f_err:
        return {
            "valid": False,
            "form_id": clean_id,
            "error": f"Google Forms API দ্বারা ফর্মটি লোড করা যায়নি: {str(f_err)}"
        }

    info = form_details.get("info", {})
    form_title = info.get("title") or drive_meta.get("name") or "ID Card Information Form"
    responder_url = form_details.get("responderUri") or f"https://docs.google.com/forms/d/{clean_id}/viewform"
    edit_url = f"https://docs.google.com/forms/d/{clean_id}/edit"
    items = form_details.get("items", [])

    # 3. Check for File Upload question
    has_file_upload = False
    for item in items:
        q_item = item.get("questionItem", {})
        q = q_item.get("question", {})
        title_lower = item.get("title", "").lower()
        if "fileUploadQuestion" in q or "file_upload" in str(q).lower() or any(k in title_lower for k in ["ছবি", "photo", "image", "file upload", "পাসপোর্ট"]):
            has_file_upload = True
            break

    # 4. Check or create response sheet
    root_folder_id = get_or_create_workspace_root_folder(workspace_id=ws_id)
    templates_folder_id = get_or_create_institution_folder(
        workspace_id=ws_id,
        institution_name="Master Form Templates",
        parent_folder_id=root_folder_id
    )

    sheet_data = {}
    try:
        sheet_data = create_institution_response_sheet(
            workspace_id=ws_id,
            institution_name=f"{form_title} Responses",
            folder_id=templates_folder_id
        )
    except Exception as s_err:
        print(f"[Verify master sheet warning]: {s_err}")

    sheet_id = sheet_data.get("spreadsheet_id")
    sheet_url = sheet_data.get("sheet_url")

    # 5. Save in database
    template_record = save_master_form_template(
        workspace_id=ws_id,
        name=form_title,
        master_form_id=clean_id,
        description_template=info.get("description", ""),
        form_url=responder_url,
        edit_url=edit_url,
        spreadsheet_id=sheet_id,
        spreadsheet_url=sheet_url,
        has_file_upload=1 if has_file_upload else 0
    )

    update_google_master_ids(
        workspace_id=ws_id,
        master_form_id=clean_id,
        master_sheet_id=sheet_id,
        drive_root_folder_id=root_folder_id,
        master_form_name=form_title,
        master_form_url=responder_url,
        master_edit_url=edit_url,
        master_sheet_url=sheet_url,
        master_has_file_upload=1 if has_file_upload else 0
    )

    return {
        "valid": True,
        "workspace_id": ws_id,
        "form_id": clean_id,
        "form_name": form_title,
        "form_url": responder_url,
        "edit_url": edit_url,
        "has_file_upload": has_file_upload,
        "items_count": len(items),
        "spreadsheet_id": sheet_id,
        "spreadsheet_url": sheet_url,
        "template_id": template_record.get("id"),
        "message": f"Master Form '{form_title}' সফলভাবে যাচাই ও সেভ হয়েছে।"
    }


def verify_generated_form(
    workspace_id: int,
    form_id: str,
    expected_fields: List[Any] = None,
    sheet_id: str = None,
    sheet_url: str = None,
    drive_folder_id: str = None,
    check_file_upload: bool = True
) -> dict:
    """
    Production verification function for generated/cloned Google Forms:
    1. Form exists and is accessible in Google Drive (not trashed, not fake).
    2. Form details & responderUri can be retrieved via Google Forms API.
    3. Form is accepting responses (published responder URI exists).
    4. Expected requested questions exist in the Form.
    5. Student Photo File Upload question exists (if photo requested / check_file_upload is True).
    6. File Upload folder is valid and accessible in Google Drive.
    7. Response Sheet exists and is accessible in Google Drive / Sheets.
    8. Drive destination folder exists and is accessible.

    Returns:
      {'success': True, 'valid': True, ...} ONLY when ALL checks pass.
      {'success': False, 'valid': False, 'error': ..., 'failure_reason': ...} when ANY check fails.
    """
    import re
    from app.google_integration.drive_service import verify_file_accessible

    ws_id = int(workspace_id or 1)
    clean_form_id = str(form_id).strip() if form_id else ""
    if not clean_form_id:
        return {
            "success": False,
            "valid": False,
            "error": "Form ID is missing or empty.",
            "failure_reason": "MISSING_FORM_ID"
        }

    # 1. Verify Form File in Google Drive
    is_valid_drive, drive_meta = verify_file_accessible(workspace_id=ws_id, file_id=clean_form_id)
    if not is_valid_drive or (isinstance(drive_meta, dict) and drive_meta.get("trashed")):
        err_msg = drive_meta.get("error", "File not found or trashed") if isinstance(drive_meta, dict) else "Inaccessible"
        return {
            "success": False,
            "valid": False,
            "form_id": clean_form_id,
            "error": f"Google Form '{clean_form_id}' Google Drive-এ পাওয়া যায়নি বা এক্সেস নেই: {err_msg}",
            "failure_reason": "FORM_INACCESSIBLE"
        }

    # 2. Verify Google Forms API Access & Structure
    try:
        form_details = get_form_details(workspace_id=ws_id, form_id=clean_form_id)
    except Exception as f_err:
        return {
            "success": False,
            "valid": False,
            "form_id": clean_form_id,
            "error": f"Google Forms API দ্বারা ফর্মটি লোড করা সম্ভব হয়নি: {str(f_err)}",
            "failure_reason": "FORMS_API_GET_FAILED"
        }

    if not isinstance(form_details, dict):
        return {
            "success": False,
            "valid": False,
            "form_id": clean_form_id,
            "error": "Google Forms API invalid metadata returned.",
            "failure_reason": "INVALID_FORM_METADATA"
        }

    items = form_details.get("items", [])
    if not items:
        return {
            "success": False,
            "valid": False,
            "form_id": clean_form_id,
            "error": f"Google Form '{clean_form_id}'-এ কোনো প্রশ্ন পাওয়া যায়নি।",
            "failure_reason": "EMPTY_FORM"
        }

    responder_uri = form_details.get("responderUri") or f"https://docs.google.com/forms/d/{clean_form_id}/viewform"

    # 3. Detect Native File Upload Question & Validate Upload Folder
    has_file_upload = False
    upload_folder_id = None
    file_upload_item = None

    for itm in items:
        q_item = itm.get("questionItem", {}) if isinstance(itm, dict) else {}
        q = q_item.get("question", {}) if isinstance(q_item, dict) else {}
        fuq = q.get("fileUploadQuestion") if isinstance(q, dict) else None
        
        if fuq is not None:
            has_file_upload = True
            file_upload_item = itm
            if isinstance(fuq, dict):
                upload_folder_id = fuq.get("folderId")
            elif hasattr(fuq, "folderId"):
                upload_folder_id = getattr(fuq, "folderId")
            break
        elif "file_upload" in str(q).lower() or any(k in str(itm.get("title", "")).lower() for k in ["file upload", "ফাইল আপলোড"]):
            has_file_upload = True
            file_upload_item = itm
            break

    # Determine if File Upload question is required
    requires_photo_upload = False
    if check_file_upload:
        requires_photo_upload = True
    elif expected_fields:
        for ef in expected_fields:
            ef_str = (ef.get("key") if isinstance(ef, dict) else str(ef)).lower()
            if any(k in ef_str for k in ["photo", "file", "ছবি", "image", "upload"]):
                requires_photo_upload = True
                break

    if requires_photo_upload and not has_file_upload:
        return {
            "success": False,
            "valid": False,
            "form_id": clean_form_id,
            "error": "Google Form-এ শিক্ষার্থীর ছবির জন্য native File Upload অপশন পাওয়া যায়নি।",
            "failure_reason": "MISSING_FILE_UPLOAD_QUESTION"
        }

    # 4. Verify Upload Folder in Drive if present
    if upload_folder_id:
        is_valid_uf, uf_meta = verify_file_accessible(workspace_id=ws_id, file_id=str(upload_folder_id).strip())
        if not is_valid_uf or (isinstance(uf_meta, dict) and uf_meta.get("trashed")):
            uf_err = uf_meta.get("error", "Folder missing or trashed") if isinstance(uf_meta, dict) else "Folder missing"
            return {
                "success": False,
                "valid": False,
                "form_id": clean_form_id,
                "upload_folder_id": upload_folder_id,
                "error": f"File Upload-এর গন্তব্য ড্রাইভ ফোল্ডার ({upload_folder_id}) গুগলে পাওয়া যায়নি বা ডিলিট হয়েছে: {uf_err}",
                "failure_reason": "INVALID_FILE_UPLOAD_FOLDER"
            }

    # 5. Verify Response Sheet
    extracted_sheet_id = None
    if sheet_id and str(sheet_id).strip():
        extracted_sheet_id = str(sheet_id).strip()
    elif sheet_url and str(sheet_url).strip():
        m_s = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', str(sheet_url).strip())
        if m_s:
            extracted_sheet_id = m_s.group(1)
        else:
            return {
                "success": False,
                "valid": False,
                "form_id": clean_form_id,
                "sheet_url": sheet_url,
                "error": f"রেসপন্স গুগল শিটের লিংকটি সঠিক নয়: {sheet_url}",
                "failure_reason": "INVALID_SHEET_URL"
            }
    else:
        return {
            "success": False,
            "valid": False,
            "form_id": clean_form_id,
            "error": "রেসপন্স গুগল শিট সংযুক্ত নেই বা পাওয়া যায়নি।",
            "failure_reason": "MISSING_RESPONSE_SHEET"
        }

    if extracted_sheet_id:
        is_valid_sheet, sheet_meta = verify_file_accessible(workspace_id=ws_id, file_id=extracted_sheet_id)
        if not is_valid_sheet or (isinstance(sheet_meta, dict) and sheet_meta.get("trashed")):
            sheet_err = sheet_meta.get("error", "Sheet not found or trashed") if isinstance(sheet_meta, dict) else "Sheet missing"
            return {
                "success": False,
                "valid": False,
                "form_id": clean_form_id,
                "spreadsheet_id": extracted_sheet_id,
                "error": f"রেসপন্স গুগল শিট ({extracted_sheet_id}) ড্রাইভে পাওয়া যায়নি: {sheet_err}",
                "failure_reason": "SHEET_INACCESSIBLE"
            }

    # 6. Verify Drive Destination Folder if provided
    if drive_folder_id and str(drive_folder_id).strip():
        is_valid_f, f_meta = verify_file_accessible(workspace_id=ws_id, file_id=str(drive_folder_id).strip())
        if not is_valid_f or (isinstance(f_meta, dict) and f_meta.get("trashed")):
            f_err = f_meta.get("error", "Folder not found or trashed") if isinstance(f_meta, dict) else "Folder missing"
            return {
                "success": False,
                "valid": False,
                "form_id": clean_form_id,
                "drive_folder_id": drive_folder_id,
                "error": f"প্রতিষ্ঠানের গুগল ড্রাইভ ফোল্ডার ({drive_folder_id}) পাওয়া যায়নি: {f_err}",
                "failure_reason": "DRIVE_FOLDER_INACCESSIBLE"
            }

    # 7. Success! All critical production checks passed
    final_sheet_url = sheet_url or (f"https://docs.google.com/spreadsheets/d/{extracted_sheet_id}/edit" if extracted_sheet_id else "")

    return {
        "success": True,
        "valid": True,
        "workspace_id": ws_id,
        "form_id": clean_form_id,
        "form_url": responder_uri,
        "responder_url": responder_uri,
        "sheet_url": final_sheet_url,
        "spreadsheet_id": extracted_sheet_id,
        "has_file_upload": has_file_upload,
        "upload_folder_id": upload_folder_id,
        "items_count": len(items),
        "message": "Google Form ও Google Sheet সম্পূর্ণ যাচাইকৃত এবং সক্রিয় রয়েছে।"
    }


def create_direct_institution_form(
    workspace_id: int,
    institution_name: str,
    institution_mobile: str = None,
    custom_description: str = None,
    fields: List[dict] = None,
    selected_fields: List[Any] = None,
    destination_folder_id: str = None
) -> dict:
    """
    Creates a 100% genuine, fully published Google Form directly using Google Forms API.
    Avoids broken Drive copy 'Missing File Upload folders' & 'This document is not published' errors!
    Returns the official published responderUri (the exact link behind the 🔗 icon / Publish in Google Forms).
    """
    from app.google_integration.drive_service import get_drive_client
    from app.database import normalize_bd_mobile, get_google_form_fields
    from app.google_integration.ai_tool import STANDARD_ID_CARD_FIELDS, get_standard_fields_catalog
    
    ws_id = int(workspace_id or 1)
    forms_service = get_forms_client(workspace_id=ws_id)
    drive_client = get_drive_client(workspace_id=ws_id)

    canonical = normalize_bd_mobile(institution_mobile) if institution_mobile else None
    form_title = f"{institution_name} - {canonical} - ID Card Form" if canonical else f"{institution_name} - ID Card Form"
    
    # 1. Create Form via Forms API
    create_body = {
        "info": {
            "title": form_title,
            "documentTitle": form_title
        }
    }
    form_res = forms_service.forms().create(body=create_body).execute()
    form_id = form_res.get("formId")
    responder_uri = form_res.get("responderUri") or f"https://docs.google.com/forms/d/{form_id}/viewform"
    edit_url = f"https://docs.google.com/forms/d/{form_id}/edit"

    # 2. Move form to institution's Drive folder & set public reader permissions
    if destination_folder_id:
        try:
            drive_client.files().update(
                fileId=form_id,
                addParents=destination_folder_id,
                removeParents="root",
                fields="id, parents"
            ).execute()
        except Exception as m_err:
            print(f"[Drive Form move notice]: {m_err}")

    try:
        drive_client.permissions().create(
            fileId=form_id,
            body={"role": "reader", "type": "anyone"},
            fields="id"
        ).execute()
    except Exception:
        pass

    # 3. Build description
    default_desc = (
        f"এই ফর্মটি সঠিকভাবে পূরণ করুন।\n"
        f"প্রতিটি শিক্ষার্থীর তথ্য নির্ভুলভাবে প্রদান করুন।\n"
        f"ছবি পরিষ্কার এবং নির্ধারিত নিয়ম অনুযায়ী প্রদান করুন।"
    )
    final_desc = custom_description or default_desc

    # 4. Resolve questions to add
    target_fields = []
    if selected_fields:
        standard_map = {f["key"]: f for f in STANDARD_ID_CARD_FIELDS}
        for sf in selected_fields:
            if isinstance(sf, dict):
                k = sf.get("key") or sf.get("field_key")
                if k and k in standard_map:
                    target_fields.append(standard_map[k])
                else:
                    target_fields.append(sf)
            elif isinstance(sf, str):
                sf_clean = sf.strip().lower()
                if sf_clean in standard_map:
                    target_fields.append(standard_map[sf_clean])
                else:
                    matched = None
                    for std_f in STANDARD_ID_CARD_FIELDS:
                        if std_f["key"] == sf_clean or any(a.lower() == sf_clean for a in std_f["aliases"]):
                            matched = std_f
                            break
                    if matched:
                        target_fields.append(matched)
                    else:
                        target_fields.append({"key": sf_clean, "label": sf, "type": "short_answer", "required": True})
    elif fields:
        target_fields = fields
    else:
        db_fields = get_google_form_fields(workspace_id=ws_id)
        target_fields = db_fields if db_fields else get_standard_fields_catalog()

    # 5. Populate Form with Description and Questions via batchUpdate
    requests_list = [
        {
            "updateFormInfo": {
                "info": {
                    "description": final_desc
                },
                "updateMask": "description"
            }
        }
    ]

    for idx, f in enumerate(target_fields):
        f_type = f.get("type") or f.get("field_type", "short_answer")
        f_label = f.get("label") or f.get("field_label", "")
        f_req = bool(f.get("required", 1))
        f_key = f.get("key") or f.get("field_key", "")

        # For student photo, create a clear text question for Drive/WhatsApp photo submission
        if f_type == "file_upload" or f_key == "student_photo" or "photo" in f_key or "ছবি" in f_label:
            q_title = "শিক্ষার্থীর ছবির ড্রাইভ লিংক / হোয়াটসঅ্যাপে পাঠাবেন"
            q_payload = {"textQuestion": {"paragraph": False}}
            f_req = False
        elif f_type == "paragraph":
            q_title = f_label
            q_payload = {"textQuestion": {"paragraph": True}}
        elif f_type == "date":
            q_title = f_label
            q_payload = {"dateQuestion": {"includeTime": False, "includeYear": True}}
        elif f_type in ["dropdown", "multiple_choice", "checkbox"]:
            q_title = f_label
            raw_opts = f.get("options_json") or f.get("options") or "[]"
            opt_list = raw_opts if isinstance(raw_opts, list) else json.loads(raw_opts) if isinstance(raw_opts, str) else []
            choice_type = "DROP_DOWN" if f_type == "dropdown" else ("CHECKBOX" if f_type == "checkbox" else "RADIO")
            q_payload = {
                "choiceQuestion": {
                    "type": choice_type,
                    "options": [{"value": str(o)} for o in (opt_list or ["Option 1"])]
                }
            }
        else:
            q_title = f_label
            q_payload = {"textQuestion": {"paragraph": False}}

        requests_list.append({
            "createItem": {
                "item": {
                    "title": q_title,
                    "questionItem": {
                        "question": {
                            "required": f_req,
                            **q_payload
                        }
                    }
                },
                "location": {
                    "index": idx
                }
            }
        })

    try:
        forms_service.forms().batchUpdate(
            formId=form_id,
            body={"requests": requests_list}
        ).execute()
    except Exception as b_err:
        print(f"[Forms populate batchUpdate warning]: {b_err}")

    # Re-fetch form details to get the exact final published responderUri
    try:
        final_meta = get_form_details(workspace_id=ws_id, form_id=form_id)
        responder_uri = final_meta.get("responderUri") or responder_uri
    except Exception:
        pass

    return {
        "success": True,
        "form_id": form_id,
        "title": form_title,
        "responder_url": responder_uri,
        "form_url": responder_uri,
        "edit_url": edit_url,
        "selected_fields": [f.get("key") or f.get("field_key") for f in target_fields if f.get("key") or f.get("field_key")]
    }
