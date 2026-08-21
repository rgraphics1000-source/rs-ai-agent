import re
from typing import Optional, Dict, Any, List

from app.google_integration.form_manager import create_institution_form
from app.database import get_google_connection, normalize_bd_mobile

def create_id_card_google_form(
    workspace_id: int,
    institution_name: str,
    institution_mobile: str = None,
    institution_phone: str = None,
    form_type: str = "id_card",
    custom_description: str = None,
    fields: List[dict] = None
) -> dict:
    """
    AI Agent Tool:
    Creates or retrieves the customized Google Form for the institution.
    Returns structured form URL and metadata for AI response synthesis.
    """
    try:
        mobile = institution_mobile or institution_phone
        res = create_institution_form(
            workspace_id=workspace_id,
            institution_name=institution_name,
            institution_mobile=mobile,
            custom_description=custom_description,
            fields=fields,
            allow_duplicate=False
        )
        return {
            "success": True,
            "is_existing": res.get("is_existing", False),
            "workspace_id": int(workspace_id or 1),
            "institution_id": res.get("institution_id"),
            "institution_name": institution_name,
            "institution_mobile": res.get("institution_mobile") or (normalize_bd_mobile(mobile) if mobile else ""),
            "form_id": res.get("form_id"),
            "form_title": res.get("form_title"),
            "sheet_title": res.get("sheet_title"),
            "form_url": res.get("form_url") or res.get("responder_url"),
            "responder_url": res.get("responder_url") or res.get("form_url"),
            "sheet_url": res.get("sheet_url"),
            "drive_folder_id": res.get("drive_folder_id"),
            "message": res.get("message")
        }
    except Exception as e:
        print(f"[AI Tool create_id_card_google_form Error]: {e}")
        return {
            "success": False,
            "error": str(e),
            "workspace_id": int(workspace_id or 1),
            "institution_name": institution_name,
            "institution_mobile": institution_mobile or institution_phone
        }

def detect_google_form_intent(user_message: str) -> Optional[dict]:
    """
    Detects if the user or customer asked to create or get an ID Card Google Form.
    Extracts institution name and institution mobile number if mentioned.
    """
    if not user_message:
        return None

    msg = user_message.strip()
    msg_lower = msg.lower()

    # Keywords for form creation
    triggers = [
        "id card form", "google form", "ফর্ম বানাও", "ফর্ম তৈরি", "ফর্ম বানিয়ে দাও",
        "ফর্ম লিঙ্ক", "ফর্ম লিংক", "তথ্য নেওয়ার ফর্ম", "ছাত্রদের ফর্ম", "আইডি কার্ড ফর্ম",
        "id card ফর্ম", "ফর্ম দাও", "ফর্ম পাঠান", "create form", "make form"
    ]

    has_intent = any(t in msg_lower for t in triggers)
    if not has_intent:
        return None

    # 1. Try extracting Bangladeshi mobile number
    inst_mobile = ""
    phone_pattern = r'(?:\+?880|880|0)?1[3-9]\d{2}[-\s]?\d{6}'
    phone_match = re.search(phone_pattern, msg)
    if phone_match:
        inst_mobile = normalize_bd_mobile(phone_match.group(0))

    # 2. Try extracting institution name
    # e.g., 'আল-আমিন মাদরাসা 01712345678 এর জন্য ID Card Form বানাও'
    # e.g., 'জামিয়া রাহমানিয়া আরাবিয়ার জন্য ID Card Form বানাও'
    inst_name = ""

    # Pattern: [Name] এর জন্য / র জন্য / এর / র [ID Card] Form / ফর্ম
    m1 = re.search(r'(.+?)(?:র\s+জন্য|এর\s+জন্য|র\s+|এর\s+)\s*(?:একটি\s+|একটা\s+)?(?:id\s*card\s+|আইডি\s*কার্ড\s+)?(?:form|ফর্ম)', msg, re.IGNORECASE)
    if m1:
        extracted = m1.group(1).strip()
        # Remove phone from name if phone was part of captured name
        if phone_match:
            extracted = re.sub(phone_pattern, '', extracted).strip()
        # Filter out common filler words
        for prefix in ["দয়া করে", "প্লিজ", "ভাই", "স্যার", "আমাদের"]:
            if extracted.startswith(prefix):
                extracted = extracted[len(prefix):].strip()
        if len(extracted) > 1:
            inst_name = extracted

    # Pattern: প্রতিষ্ঠান: [Name] or মাদরাসা: [Name]
    if not inst_name:
        m2 = re.search(r'(?:প্রতিষ্ঠান|মাদরাসা|স্কুল|কলেজ|প্রতিষ্ঠানটি|নাম)[:\s]+([^\n,।]+)', msg, re.IGNORECASE)
        if m2:
            extracted = m2.group(1).strip()
            if phone_match:
                extracted = re.sub(phone_pattern, '', extracted).strip()
            inst_name = extracted

    return {
        "intent": "create_id_card_google_form",
        "institution_name": inst_name or "আমাদের প্রতিষ্ঠান",
        "institution_mobile": inst_mobile or "",
        "raw_message": user_message
    }
