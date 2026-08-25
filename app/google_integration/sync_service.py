import json
import time
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from app.google_integration.forms_service import get_forms_client, get_form_details
from app.google_integration.drive_service import get_drive_client
from app.google_integration.sheets_service import append_submission_row
from app.database import (
    get_generated_form_by_id, save_form_submission, save_uploaded_file,
    update_generated_form_stats, get_google_form_fields
)

def sync_form_responses(workspace_id: int, form_id: str) -> dict:
    """
    Fetches all student responses for a Google Form and imports them into SQLite database.
    - Preserves tenant isolation (workspace_id).
    - Guarantees duplicate-safe idempotency via (form_id, response_id).
    - Extracts student photos uploaded to Google Drive.
    - Appends row to linked Google Sheet if configured.
    """
    clean_form_id = str(form_id).strip()
    gen_form = get_generated_form_by_id(clean_form_id)
    if not gen_form:
        return {
            "success": False,
            "error": f"Form ID '{clean_form_id}' not found in database."
        }

    # Verify workspace isolation
    if int(gen_form.get("workspace_id") or 1) != int(workspace_id):
        raise PermissionError("Access denied: Form belongs to another workspace.")

    forms_client = get_forms_client(workspace_id=workspace_id)
    drive_client = get_drive_client(workspace_id=workspace_id)

    # 1. Fetch form structure to map question IDs to question titles
    form_meta = get_form_details(workspace_id, clean_form_id)
    question_map = {}
    for item in form_meta.get("items", []):
        title = item.get("title", "").strip()
        q_item = item.get("questionItem", {})
        q = q_item.get("question", {})
        q_id = q.get("questionId")
        if q_id and title:
            question_map[q_id] = title

    # 2. Fetch responses from Google Forms API
    try:
        resp_list_call = forms_client.forms().responses().list(formId=clean_form_id)
        responses_data = resp_list_call.execute()
    except Exception as e:
        print(f"[Forms Responses Fetch Error for {clean_form_id}]: {e}")
        return {
            "success": False,
            "error": f"Google Forms API responses fetch error: {str(e)}"
        }

    responses = responses_data.get("responses", [])
    new_submissions_count = 0
    total_submissions_count = len(responses)

    for resp in responses:
        response_id = resp.get("responseId")
        if not response_id:
            continue

        create_time = resp.get("createTime") or resp.get("lastSubmittedTime")
        answers = resp.get("answers", {})

        # Extract values
        extracted = {
            "student_name": "",
            "father_name": "",
            "mother_name": "",
            "student_class": "",
            "student_section": "",
            "student_roll": "",
            "student_id": "",
            "date_of_birth": "",
            "blood_group": "",
            "guardian_phone": "",
            "address": "",
            "photo_file_ids": []
        }

        # Map answers to fields
        for q_id, ans_obj in answers.items():
            q_title = question_map.get(q_id, "").lower()
            text_answers = ans_obj.get("textAnswers", {}).get("answers", [])
            val = text_answers[0].get("value", "").strip() if text_answers else ""

            # Check file upload answers
            file_answers = ans_obj.get("fileUploadAnswers", {}).get("answers", [])
            if file_answers:
                for f_ans in file_answers:
                    f_id = f_ans.get("fileId")
                    if f_id:
                        extracted["photo_file_ids"].append(f_id)

            if not val:
                continue

            if any(k in q_title for k in ["শিক্ষার্থীর নাম", "student name", "নাম", "name"]) and "পিতা" not in q_title and "মাতা" not in q_title:
                extracted["student_name"] = val
            elif any(k in q_title for k in ["পিতার নাম", "father", "পিতা"]):
                extracted["father_name"] = val
            elif any(k in q_title for k in ["মাতার নাম", "mother", "মাতা"]):
                extracted["mother_name"] = val
            elif any(k in q_title for k in ["শ্রেণি", "শ্রেণী", "class", "জামাত"]):
                extracted["student_class"] = val
            elif any(k in q_title for k in ["শাখা", "section"]):
                extracted["student_section"] = val
            elif any(k in q_title for k in ["রোল", "roll"]):
                extracted["student_roll"] = val
            elif any(k in q_title for k in ["আইডি", "id"]):
                extracted["student_id"] = val
            elif any(k in q_title for k in ["জন্মতারিখ", "birth", "dob"]):
                extracted["date_of_birth"] = val
            elif any(k in q_title for k in ["রক্তের গ্রুপ", "blood"]):
                extracted["blood_group"] = val
            elif any(k in q_title for k in ["মোবাইল", "ফোন", "phone", "mobile", "contact"]):
                extracted["guardian_phone"] = val
            elif any(k in q_title for k in ["ঠিকানা", "address"]):
                extracted["address"] = val

        # Save submission idempotently
        is_new, sub_record = save_form_submission(
            workspace_id=workspace_id,
            generated_form_id=gen_form["id"],
            form_id=clean_form_id,
            response_id=response_id,
            raw_response_json=json.dumps(resp, ensure_ascii=False),
            student_name=extracted["student_name"] or "Student",
            student_roll=extracted["student_roll"],
            student_class=extracted["student_class"],
            student_phone=extracted["guardian_phone"],
            submission_timestamp=create_time
        )

        # Process uploaded photos in Drive
        first_photo_url = ""
        for file_id in extracted["photo_file_ids"]:
            try:
                f_meta = drive_client.files().get(
                    fileId=file_id,
                    fields="id, name, mimeType, webViewLink, thumbnailLink"
                ).execute()

                f_name = f_meta.get("name")
                f_url = f_meta.get("webViewLink")
                f_thumb = f_meta.get("thumbnailLink")
                f_mime = f_meta.get("mimeType")

                if not first_photo_url and f_url:
                    first_photo_url = f_url

                if is_new:
                    save_uploaded_file(
                        workspace_id=workspace_id,
                        generated_form_id=gen_form["id"],
                        response_id=response_id,
                        file_id=file_id,
                        file_name=f_name,
                        drive_url=f_url,
                        mime_type=f_mime,
                        thumbnail_url=f_thumb
                    )
            except Exception as f_err:
                print(f"[Drive photo meta warning for {file_id}]: {f_err}")

        # If new submission and response sheet is linked, append row
        sheet_id = gen_form.get("response_destination_id")
        if is_new and sheet_id:
            row_vals = [
                response_id,
                create_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                extracted["student_name"],
                extracted["father_name"],
                extracted["mother_name"],
                extracted["student_class"],
                extracted["student_section"],
                extracted["student_roll"],
                extracted["student_id"],
                extracted["date_of_birth"],
                extracted["blood_group"],
                extracted["guardian_phone"],
                extracted["address"],
                first_photo_url
            ]
            append_submission_row(workspace_id=workspace_id, spreadsheet_id=sheet_id, row_data=row_vals)

        if is_new:
            new_submissions_count += 1

    # Update stats
    update_generated_form_stats(
        form_id=clean_form_id,
        submission_count=total_submissions_count,
        last_synced_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    return {
        "success": True,
        "form_id": clean_form_id,
        "total_submissions": total_submissions_count,
        "new_submissions_imported": new_submissions_count,
        "last_synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
