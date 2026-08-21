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
    """Retrieves the official public canonical URL for students and institutions."""
    clean_id = str(form_id).strip()
    # Always use the specific cloned form's canonical public URL (/forms/d/{id}/viewform)
    # Never return the master template's /d/e/1FAIpQLSc... URL which shows 'Form not published' error
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

