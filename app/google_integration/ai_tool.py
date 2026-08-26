import re
from typing import Optional, Dict, Any, List

from app.google_integration.form_manager import create_institution_form
from app.database import get_google_connection, normalize_bd_mobile

# ============================================================
# APPROVED STANDARD ID CARD FIELD CATALOG
# ============================================================
STANDARD_ID_CARD_FIELDS: List[Dict[str, Any]] = [
    {
        "key": "student_name",
        "label": "শিক্ষার্থীর নাম",
        "type": "short_answer",
        "required": True,
        "aliases": [
            "নাম", "ছাত্রের নাম", "শিক্ষার্থীর নাম", "ছাত্রীর নাম", "ছাত্রছাত্রীর নাম",
            "স্টুডেন্ট নাম", "student name", "name", "full name", "student_name"
        ]
    },
    {
        "key": "father_name",
        "label": "পিতার নাম",
        "type": "short_answer",
        "required": True,
        "aliases": [
            "পিতার নাম", "বাবার নাম", "পিতা", "বাবা", "আব্বুর নাম", "আব্বা", "বাপের নাম",
            "father name", "father's name", "father", "father_name"
        ]
    },
    {
        "key": "mother_name",
        "label": "মাতার নাম",
        "type": "short_answer",
        "required": False,
        "aliases": [
            "মাতার নাম", "মায়ের নাম", "মায়ের", "মাতা", "আম্মুর নাম", "আম্মা", "আম্মু",
            "mother name", "mother's name", "mother", "mother_name"
        ]
    },
    {
        "key": "dob",
        "label": "জন্মতারিখ",
        "type": "date",
        "required": False,
        "aliases": [
            "জন্মতারিখ", "জন্ম তারিখ", "জন্মদিন", "জন্ম সন", "date of birth", "dob",
            "birth date", "birth_date"
        ]
    },
    {
        "key": "class_name",
        "label": "শ্রেণি",
        "type": "short_answer",
        "required": True,
        "aliases": [
            "শ্রেণি", "শ্রেণী", "ক্লাস", "জামাত", "শ্রেণির নাম", "class", "grade",
            "class_name"
        ]
    },
    {
        "key": "section",
        "label": "শাখা",
        "type": "short_answer",
        "required": False,
        "aliases": [
            "শাখা", "সেকশন", "ক্লাস শাখা", "section", "sec"
        ]
    },
    {
        "key": "roll",
        "label": "রোল",
        "type": "short_answer",
        "required": True,
        "aliases": [
            "রোল", "রোল নম্বর", "রোল নং", "রোল নাম্বার", "ক্লাস রোল", "roll", "roll no",
            "roll number", "roll_no"
        ]
    },
    {
        "key": "reg_no",
        "label": "রেজিস্ট্রেশন নম্বর",
        "type": "short_answer",
        "required": False,
        "aliases": [
            "রেজিস্ট্রেশন", "রেজিস্ট্রেশন নম্বর", "রেজিস্ট্রেশন নং", "রেজিস্ট্রেশন নাম্বার",
            "দাখিলা নং", "আইডি নম্বর", "রেজি নং", "reg no", "registration no",
            "registration", "reg_no", "id_no"
        ]
    },
    {
        "key": "blood_group",
        "label": "রক্তের গ্রুপ",
        "type": "dropdown",
        "required": False,
        "aliases": [
            "রক্তের গ্রুপ", "ব্লাড গ্রুপ", "রক্তের দল", "ব্লাড", "blood group",
            "blood", "blood_group"
        ]
    },
    {
        "key": "student_phone",
        "label": "শিক্ষার্থীর মোবাইল",
        "type": "short_answer",
        "required": False,
        "aliases": [
            "শিক্ষার্থীর মোবাইল", "শিক্ষার্থীর ফোন", "ছাত্রের মোবাইল", "ছাত্রের ফোন",
            "স্টুডেন্ট মোবাইল", "ছাত্রছাত্রীর মোবাইল", "student phone", "student mobile",
            "student_phone", "student_mobile"
        ]
    },
    {
        "key": "guardian_phone",
        "label": "অভিভাবকের মোবাইল",
        "type": "short_answer",
        "required": False,
        "aliases": [
            "অভিভাবকের মোবাইল", "অভিভাবকের ফোন", "অভিভাবক মোবাইল", "পিতার মোবাইল",
            "বাবার মোবাইল", "বাবার ফোন", "প্যারেন্টস মোবাইল", "guardian phone",
            "guardian mobile", "parent phone", "guardian_phone"
        ]
    },
    {
        "key": "address",
        "label": "ঠিকানা",
        "type": "paragraph",
        "required": False,
        "aliases": [
            "ঠিকানা", "বর্তমান ঠিকানা", "স্থায়ী ঠিকানা", "বাসার ঠিকানা", "গ্রাম",
            "address", "present address", "permanent address", "home address"
        ]
    },
    {
        "key": "student_photo",
        "label": "ছবি",
        "type": "file_upload",
        "required": True,
        "aliases": [
            "ছবি", "শিক্ষার্থীর ছবি", "পাসপোর্ট ছবি", "ফটো", "পাসপোর্ট সাইজ ছবি", "পাসপোর্ট সাইজের ছবি",
            "পিকচার", "ইমেজ", "photo", "student photo", "picture", "image",
            "file upload", "upload", "student_photo"
        ]
    },
    {
        "key": "student_signature",
        "label": "স্বাক্ষর",
        "type": "file_upload",
        "required": False,
        "aliases": [
            "স্বাক্ষর", "দস্তখত", "সিগনেচার", "ছাত্রের স্বাক্ষর", "signature", "sign",
            "student_signature"
        ]
    }
]

def get_standard_fields_catalog() -> List[Dict[str, Any]]:
    """Returns the immutable list of approved standard fields with metadata."""
    return [
        {
            "key": f["key"],
            "label": f["label"],
            "type": f["type"],
            "required": f["required"]
        }
        for f in STANDARD_ID_CARD_FIELDS
    ]

def detect_fields_from_natural_language(text: str, fallback_to_defaults: bool = False) -> List[Dict[str, Any]]:
    """
    AI Field Detection Engine:
    Reads natural language Bengali or English customer requirement and maps it
    STRICTLY to the approved standard fields catalog without inventing random fields.
    """
    if not text:
        if fallback_to_defaults:
            default_keys = ["student_name", "father_name", "class_name", "roll", "student_photo"]
            return [f for f in get_standard_fields_catalog() if f["key"] in default_keys]
        return []

    text_lower = text.lower().strip()
    # Strip institutional name references so 'প্রতিষ্ঠানের নাম' does not trigger 'student_name' field
    field_text = re.sub(r'(?:প্রতিষ্ঠানের|স্কুলের|মাদ্রাসার|মাদরাসার|কলেজের|আমাদের|আপনার|দোকানের)\s*নাম[টি]*', '', text_lower)
    detected_fields = []
    detected_keys = set()

    for field in STANDARD_ID_CARD_FIELDS:
        f_key = field["key"]
        matched = False

        for alias in field["aliases"]:
            alias_lower = alias.lower()
            pattern = r'(?<![a-zA-Z0-9\u0980-\u09FF])' + re.escape(alias_lower) + r'(?![a-zA-Z0-9\u0980-\u09FF])'
            if re.search(pattern, field_text):
                matched = True
                break

        if matched and f_key not in detected_keys:
            detected_keys.add(f_key)
            detected_fields.append({
                "key": field["key"],
                "label": field["label"],
                "type": field["type"],
                "required": field["required"]
            })

    if not detected_fields and fallback_to_defaults:
        default_keys = ["student_name", "father_name", "class_name", "roll", "student_photo"]
        detected_fields = [f for f in get_standard_fields_catalog() if f["key"] in default_keys]

    return detected_fields

def create_id_card_google_form(
    workspace_id: int,
    institution_name: str,
    institution_mobile: str = None,
    institution_phone: str = None,
    form_type: str = "id_card",
    custom_description: str = None,
    fields: List[dict] = None,
    selected_fields: List[str] = None
) -> dict:
    """
    AI Agent Tool:
    Creates or retrieves the customized Google Form for the institution.
    """
    mobile = institution_mobile or institution_phone
    if not institution_name or not mobile:
        return {
            "success": False,
            "error": "প্রতিষ্ঠানের নাম এবং মোবাইল নম্বর উভয়ই বাধ্যতামূলক।",
            "workspace_id": int(workspace_id or 1),
            "institution_name": institution_name,
            "institution_mobile": mobile,
            "form_summary": ""
        }

    try:
        res = create_institution_form(
            workspace_id=int(workspace_id or 1),
            institution_name=institution_name,
            institution_mobile=mobile,
            fields=fields,
            selected_fields=selected_fields,
            allow_duplicate=False
        )
        responder_url = res.get("responder_url") or res.get("form_url") or ""
        form_summary = f"{institution_name} এর জন্য Google Form সফলভাবে প্রস্তুত হয়েছে। ফর্ম লিংক: {responder_url}"
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
            "form_url": responder_url,
            "responder_url": responder_url,
            "sheet_url": res.get("sheet_url"),
            "drive_folder_id": res.get("drive_folder_id"),
            "selected_fields": res.get("selected_fields"),
            "form_summary": form_summary,
            "message": res.get("message")
        }
    except Exception as e:
        print(f"[AI Tool create_id_card_google_form Error]: {e}")
        return {
            "success": False,
            "error": str(e),
            "workspace_id": int(workspace_id or 1),
            "institution_name": institution_name,
            "institution_mobile": institution_mobile or institution_phone,
            "form_summary": ""
        }

def detect_google_form_intent(user_message: str) -> Optional[dict]:
    """
    Detects if the user or customer asked to create or get an ID Card Google Form.
    Extracts institution name, mobile number, and field requirements if mentioned.
    """
    if not user_message:
        return None

    msg = user_message.strip()
    msg_lower = msg.lower()

    # Keywords for form creation
    triggers = [
        "id card form", "google form", "gform",
        "ফর্ম বানাও", "ফরম বানাও", "ফর্ম তৈরি", "ফরম তৈরি",
        "ফর্ম বানিয়ে", "ফরম বানিয়ে", "ফর্ম বানিয়ে", "ফরম বানিয়ে",
        "ফর্ম বানিয়ে দাও", "ফরম বানিয়ে দাও", "ফর্ম বানিয়ে দাও", "ফরম বানিয়ে দাও",
        "ফর্ম বানিয়ে দিন", "ফরম বানিয়ে দিন", "ফর্ম বানিয়ে দিন", "ফরম বানিয়ে দিন",
        "বানিয়ে দাও", "বানিয়ে দাও", "বানিয়ে দিন", "বানিয়ে দিন",
        "ফর্ম লিঙ্ক", "ফরম লিঙ্ক", "ফর্ম লিংক", "ফরম লিংক",
        "তথ্য নেওয়ার ফর্ম", "তথ্য নেওয়ার ফরম", "ছাত্রদের ফর্ম", "ছাত্রদের ফরম",
        "আইডি কার্ড ফর্ম", "আইডি কার্ড ফরম", "id card ফর্ম", "id card ফরম",
        "ফর্ম দাও", "ফরম দাও", "ফর্ম পাঠান", "ফরম পাঠান",
        "create form", "make form",
        "ফর্ম", "ফরম", "ফর্মে", "ফরমে", "গুগল ফর্ম", "গুগল ফরম"
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
    inst_name = ""
    m_name_match = re.search(r'(?:প্রতিষ্ঠান|প্রতিষ্ঠানের নাম|নাম|মাদ্রাসার নাম|মাদরাসার নাম|স্কুলের নাম|কলেজের নাম)[:\s]+([^\n,।]+)', msg, re.IGNORECASE)
    if m_name_match:
        extracted = m_name_match.group(1).strip()
        if phone_match:
            extracted = re.sub(phone_pattern, '', extracted).strip()
        inst_name = extracted.split(",")[0].strip()

    if not inst_name:
        m1 = re.search(r'(.+?)(?:র\s+জন্য|এর\s+জন্য|র\s+|এর\s+)\s*(?:একটি\s+|একটা\s+)?(?:id\s*card\s+|আইডি\s*কার্ড\s+)?(?:form|ফর্ম|ফরম)', msg, re.IGNORECASE)
        if m1:
            extracted = m1.group(1).strip()
            if phone_match:
                extracted = re.sub(phone_pattern, '', extracted).strip()
            for prefix in ["দয়া করে", "প্লিজ", "ভাই", "স্যার", "আমাদের"]:
                if extracted.startswith(prefix):
                    extracted = extracted[len(prefix):].strip()
            if len(extracted) > 1:
                inst_name = extracted

    # 3. Detect requested fields from message
    detected_fields = detect_fields_from_natural_language(user_message)

    return {
        "is_form_creation": True,
        "intent": "create_id_card_google_form",
        "extracted_name": inst_name or "আমাদের প্রতিষ্ঠান",
        "extracted_mobile": inst_mobile or "",
        "institution_name": inst_name or "আমাদের প্রতিষ্ঠান",
        "institution_mobile": inst_mobile or "",
        "fields": detected_fields,
        "field_keys": [f["key"] for f in detected_fields],
        "raw_message": user_message
    }

def resolve_google_form_workflow(
    user_message: str,
    conversation_history: list = None,
    customer_phone: str = "",
    customer_name: str = "",
    workspace_id: int = 1
) -> Optional[dict]:
    """
    Multi-turn conversation state manager and executor for Google Form creation.
    Accumulates institution name, institution mobile, and requested fields across messages,
    then executes create_institution_form when all required data is collected.
    """
    if not user_message or not isinstance(user_message, str) or not user_message.strip():
        return None

    msg_raw = user_message.strip()
    msg_lower = msg_raw.lower()

    phone_pattern = r'(?:\+?880|880|0)?1[3-9]\d{2}[-\s]?\d{6}'
    question_pattern = r'(?:\?|কীভাবে|কিভাবে|কত\s*টাকা|দাম\s*কত|দর\s*কত|চার্জ\s*কত|খরচ\s*কত|কেমন\s*দাম|তথ্য\s*(?:কিভাবে|কীভাবে)|(?:কিভাবে|কীভাবে)\s*(?:দিব|দেবো|নেওয়া|নেন|পাঠাব|পাঠাবো)|কবে\s*পাব|কোথায়|কোথায়|(?:^|\s)(?:দাম|চার্জ|খরচ|রেট|প্রাইস)(?:\s|[।\?!,:]|$))'

    from app.ai_agent.gemini_brain import detect_customer_gender_title
    honorific = detect_customer_gender_title(customer_name)

    # Check if user is asking for demo, rules, video or expressing confusion about Google Form
    is_form_demo_or_rule_inquiry = any(k in msg_lower for k in [
        "নিয়ম কি", "নিয়ম কি", "নিয়ম কী", "নিয়ম কী", "ডেমো", "demo", "ভিডিও", "video",
        "বুঝি না", "বুঝিনা", "কেমনে", "কীভাবে দেব", "কিভাবে দেব", "কীভাবে জমা", "কিভাবে জমা",
        "কীভাবে পূরণ", "কিভাবে পূরণ", "কীভাবে করে", "কিভাবে করে", "কীভাবে কাজ করে", "কিভাবে কাজ করে",
        "কোন ডেমো আছে", "ডেমো আছে কিনা", "ডেমো দেখতে চাই", "ডেমো দেন", "ডেমো দিন", "ডেমো দেখান",
        "তথ্য দেওয়ার নিয়ম", "তথ্য দেয়ার নিয়ম", "ছবি দেওয়ার নিয়ম", "ছবি দেয়ার নিয়ম",
        "গুগল ফর্মে তথ্য দেওয়ার নিয়ম", "গুগল ফরম বুঝিনা"
    ])

    if is_form_demo_or_rule_inquiry:
        return {
            "reply": (
                f"জি {honorific}, আমাদের কাছে তথ্য দেওয়ার ২টি সহজ মাধ্যম রয়েছে (যার মধ্যে প্রধান ও সবচেয়ে সুবিধাজনক মাধ্যম হলো গুগল ফর্ম):\n\n"
                "১) WhatsApp: আমাদের অফিসিয়াল হোয়াটসঅ্যাপ নম্বর 01816504097-এ প্রতিষ্ঠানের নাম, লোগো এবং শিক্ষার্থীদের নাম/রোল/ছবি সরাসরি পাঠিয়ে দিতে পারেন।\n"
                "২) Google Form (প্রধান মাধ্যম): আপনার প্রতিষ্ঠানের জন্য আমরা একটি কাস্টমাইজড গুগল ফর্ম তৈরি করে দেব, যাতে অভিভাবক বা শিক্ষার্থীরা মোবাইল থেকেই নাম, শ্রেণি, রোল ও ছবি সুন্দরভাবে জমা দিতে পারবেন।\n\n"
                "গুগল ফর্মে কীভাবে তথ্য ও ছবি আপলোড করতে হয়, তার পূর্ণাঙ্গ ডেমো ভিডিওটি নিচে দেওয়া হলো।\n\n"
                f"আপনার প্রতিষ্ঠানের জন্য কি একটি গুগল ফর্ম তৈরি করে দেব {honorific}?"
            ),
            "video_url": "/static/uploads/media/google_form_submission_guide.mp4",
            "action": "data_collection_demo_video",
            "step": "offered_google_form_and_video"
        }

    # 1. Parse structured conversation history
    flat_history = []
    if conversation_history:
        for m in conversation_history:
            sender_val = str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower()
            role = "user" if sender_val in ("customer", "user") else "assistant"
            content = m.get("content") or m.get("text") or m.get("message") or ""
            if content and isinstance(content, str):
                flat_history.append({"role": role, "text": content.strip()})

    # Find the very last message from assistant to determine active workflow state
    last_assistant_msg = ""
    for m in reversed(flat_history):
        if m["role"] == "assistant":
            last_assistant_msg = m["text"]
            break

    # Determine if last assistant message was a form-related prompt
    is_awaiting_name = any(q in last_assistant_msg for q in ["প্রতিষ্ঠানের নামটি দিন", "প্রতিষ্ঠানের নাম দিন", "প্রতিষ্ঠানের নাম বলুন", "প্রতিষ্ঠানের নাম কী"])
    is_awaiting_mobile = any(q in last_assistant_msg for q in ["প্রতিষ্ঠানের মোবাইল নম্বরটি দিন", "মোবাইল নম্বরটি দিন", "মোবাইল নম্বর দিন", "মোবাইল নম্বর প্রদান করুন"])
    is_awaiting_fields = any(q in last_assistant_msg for q in ["কোন কোন তথ্য রাখতে চান", "কোন কোন তথ্য লাগবে", "কী কী তথ্য লাগবে", "তথ্য বা ফিল্ড লাগবে"])
    is_offering_form = any(q in last_assistant_msg for q in ["গুগল ফর্ম বানিয়ে দেব", "গুগল ফরম বানিয়ে দেব", "গুগল ফর্ম তৈরি করে দেব", "গুগল ফরম তৈরি করে দেব", "ফর্ম বানিয়ে দেব", "ফরম বানিয়ে দেব", "গুগল ফর্মের ব্যবস্থা", "গুগল ফরমের ব্যবস্থা"])

    has_active_form_flow = is_awaiting_name or is_awaiting_mobile or is_awaiting_fields

    # Check for explicit form creation command or institution configuration in current user message
    form_explicit_triggers = [
        r'গুগল\s*ফর্ম|গুগল\s*ফরম|google\s*for[mn]|google\s*from|gform|g-form',
        r'id\s*card\s*(?:এর\s*)?(?:form|ফর্ম|ফরম)',
        r'(?:আইডি\s*কার্ড(?:ের)?\s*(?:জন্য\s*)?)?(?:ফর্ম|ফরম|form)\s*(?:বানাও|বানিয়ে|বানিয়ে|বানাতে|তৈরি|করতে|create|make|দিন|দাও|পাঠান|লিংক|লিঙ্ক|দেন|চাই|হবে|লাগবে|কোথায়|কোথায়|রেডি|হয়েছে|হয়েছে কি|কবে)',
        r'(?:তথ্য|ডাটা)\s*(?:নেওয়ার|দেওয়ার|কালেক্ট\s*করার)\s*(?:জন্য\s*)?(?:গুগল\s*)?(?:ফর্ম|ফরম|form)',
        r'(?:আমার|আমাদের)\s*(?:গুগল\s*)?(?:ফর্ম|ফরম|form)',
        r'(?:ফর্ম|ফরম|form)\s*(?:বানাতে|করতে|লাগবে|চাই|দিন|দাও|হবে|কোথায়|কোথায়|রেডি|কবে|পাঠান|লিংক|লিঙ্ক)',
        r'(?:ফর্ম|ফরম|form)\s*(?:এর\s*)?(?:লিংক|লিঙ্ক|link)',
        r'(?:ফর্মে|ফরমে)\s*(?:নাম|পিতার|শ্রেণি|ছবি|রোল|তথ্য)',
        r'প্রতিষ্ঠানের\s*নাম|স্কুলের\s*নাম|মাদ্রাসার\s*নাম|মাদরাসার\s*নাম|কলেজের\s*নাম',
        r'(?:নাম|পিতা|শ্রেণি|শ্রেণী|রোল|ছবি|জন্মতারিখ).*(?:থাকবে|রাখব|রাখবো|নেব|নেবো|কালেক্ট|ফিল্ড)',
        r'(?:জামিয়া|জামেয়া|মারকাজ|মারকায|মাদ্রাসা|মাদরাসা|স্কুল|School|College).*(?:নাম|পিতা|শ্রেণি|শ্রেণী|রোল|ছবি)'
    ]
    has_explicit_form_intent = any(re.search(p, msg_lower, re.IGNORECASE) for p in form_explicit_triggers)

    # If assistant previously offered to create a form and customer agrees (e.g. "হ্যাঁ", "জি", "বানিয়ে দাও")
    if is_offering_form and re.search(r'^(?:হ্যাঁ|হ্যা|জি|হাঁ|অবশ্যই|বানিয়ে\s*দাও|বানিয়ে\s*দাও|বানাও|দিন|তৈরি\s*করেন|তৈরি\s*করুন|করুন|করেন|yes|ok|okay)', msg_lower):
        has_explicit_form_intent = True

    is_question = bool(re.search(question_pattern, msg_lower))

    # DETERMINISTIC: Data collection questions → always mention Google Form + offer to create
    data_collection_patterns = [
        r'(?:তথ্য|ছবি|ডাটা|data|photo|ইনফরমেশন|ইনফো).*(?:কিভাবে|কীভাবে|কেমনে|কেমন\s*করে|কোথায়|কোনো\s*উপায়|কোন\s*ভাবে).*(?:দিব|দেবো|দিবো|দিতে|নেন|নেবেন|নিবেন|পাঠাব|পাঠাবো|পাঠাই|দেই|সংগ্রহ|কালেক্ট|জমা|submit|send|collect)',
        r'(?:কিভাবে|কীভাবে|কেমনে|কেমন\s*করে|কোথায়).*(?:তথ্য|ছবি|ডাটা|data|photo|ইনফরমেশন|ইনফো).*(?:দিব|দেবো|দিবো|দিতে|নেন|নেবেন|নিবেন|পাঠাব|পাঠাবো|পাঠাই|দেই|সংগ্রহ|কালেক্ট|জমা|submit|send|collect)',
        r'(?:তথ্য|ছবি|ডাটা|data|photo).*(?:দেওয়ার|নেওয়ার|পাঠানোর|জমার|সংগ্রহের).*(?:নিয়ম|পদ্ধতি|উপায়|সিস্টেম|মাধ্যম)',
        r'(?:তথ্য|ছবি|ডাটা).*(?:পাঠাতে|দিতে|জমা\s*দিতে).*(?:চাই|হবে|কি|কী|কেমনে)'
    ]
    if any(re.search(p, msg_lower, re.IGNORECASE) for p in data_collection_patterns) and not has_explicit_form_intent:
        return {
            "reply": (
                f"জি {honorific}, আইডি কার্ডের তথ্য ও ছবি সংগ্রহের জন্য আমাদের প্রধান এবং সবচেয়ে সহজ মাধ্যম হলো **গুগল ফর্ম (Google Form)**।\n\n"
                "আমরা আপনার প্রতিষ্ঠানের নামে একটি কাস্টমাইজড গুগল ফর্ম তৈরি করে দেব, "
                "যেখানে শিক্ষার্থী বা স্টাফরা নিজেরাই নাম, পিতার নাম, শ্রেণি, রোল ও ছবি সুন্দরভাবে জমা দিতে পারবেন।\n\n"
                "আর গুগল ফর্মে দেওয়া কারো কাছে কঠিন মনে হলে, আপনারা সরাসরি এই হোয়াটসঅ্যাপে বা এক্সেল/ওয়ার্ড ফাইলে তালিকা এবং ছবি পাঠিয়ে দিতে পারবেন।\n\n"
                f"আপনার প্রতিষ্ঠানের জন্য কি একটি গুগল ফর্ম বানিয়ে দেব {honorific}?"
            ),
            "action": "data_collection_offer",
            "step": "offered_google_form"
        }

    # If the user is asking a general question (e.g., "আইডি কার্ডের দাম কত?")
    # and has not issued an explicit form creation command, let Gemini AI answer naturally!
    if is_question and not has_explicit_form_intent:
        return None

    # If there is no active form flow and no explicit form command in the message, bypass workflow
    if not has_active_form_flow and not has_explicit_form_intent:
        return None

    # Append current message to local history for unified resolution
    full_thread = flat_history + [{"role": "user", "text": msg_raw}]

    # 2. Extract Mobile Number across thread
    inst_mobile = ""
    for m in reversed(full_thread):
        if m["role"] == "user":
            match = re.search(phone_pattern, m["text"])
            if match:
                norm = normalize_bd_mobile(match.group(0))
                if norm:
                    inst_mobile = norm
                    break
    if not inst_mobile and customer_phone:
        norm_cust = normalize_bd_mobile(customer_phone)
        if norm_cust and len(norm_cust) >= 10:
            inst_mobile = norm_cust

    # Accurate institution candidate validation helper
    def is_valid_inst_cand(c: str) -> bool:
        if not c or len(c.strip()) < 2:
            return False
        c_low = c.strip().lower()
        confusion_phrases = [
            "বুঝি না", "বুঝিনা", "ডেমো", "demo", "ভিডিও", "video", "নিয়ম", "নিয়ম", "কিভাবে", "কীভাবে",
            "বলতেছি", "বলছি", "চাই না", "লাগবে না", "দাম কত", "কত টাকা", "কেমন দাম", "কোথায়", "কোথায়",
            "বানাবো", "বানাব", "বানাতে চাই", "অর্ডার করতে চাই"
        ]
        if any(p in c_low for p in confusion_phrases):
            return False
        if c_low in ["হ্যাঁ", "জি", "হাঁ", "না", "নাই", "নেই", "ধন্যবাদ", "হ্যালো", "ভাই", "স্যার", "ম্যাম", "আসেনি", "পাঠান", "দিন", "দেন", "অর্ডার", "প্যাকেজ", "কার্ড", "id card", "ফর্ম", "ফরম", "form"]:
            return False
        return True

    # 3. Extract Institution Name across thread
    inst_name = ""
    for m in full_thread:
        if m["role"] != "user":
            continue
        t = m["text"]

        m_lbl = re.search(r'(?:প্রতিষ্ঠানের\s*নামটি|প্রতিষ্ঠানের\s*নাম|স্কুলের\s*নাম|মadrasar\s*নাম|মাদ্রাসা[র]*\s*নাম|মাদরাসা[র]*\s*নাম|কলেজের\s*নাম|ইনস্টিটিউটের\s*নাম)\s*[:=\s]\s*([^\n,।]+)', t, re.IGNORECASE)
        if m_lbl:
            cand = m_lbl.group(1).strip()
            cand = re.sub(phone_pattern, '', cand).strip()
            cand = cand.split(",")[0].split("।")[0].strip()
            for pfx in ["দয়া করে", "প্লিজ", "ভাই", "স্যার", "আমাদের", "আমার"]:
                if cand.startswith(pfx):
                    cand = cand[len(pfx):].strip()
            if cand in ["প্রতিষ্ঠান", "প্রতিষ্ঠানের", "স্কুল", "স্কুলের", "মাদ্রাসা", "মাদ্রাসার", "মাদরাসা", "মাদরাসার", "আমাদের প্রতিষ্ঠান", "আমার প্রতিষ্ঠান", "প্রতিষ্ঠানটি", "স্কুলটি", "মাদ্রাসাটি", "id card", "কার্ড"]:
                cand = ""
            if cand and is_valid_inst_cand(cand):
                inst_name = cand
                break

        m_for = re.search(r'(.+?)(?:র\s+জন্য|এর\s+জন্য|র\s+|এর\s+)\s*(?:একটি\s+|একটা\s+)?(?:id\s*card\s+|আইডি\s*কার্ড\s+)?(?:form|ফর্ম|ফরম)', t, re.IGNORECASE)
        if m_for:
            cand = m_for.group(1).strip()
            cand = re.sub(phone_pattern, '', cand).strip()
            for pfx in ["দয়া করে", "প্লিজ", "ভাই", "স্যার", "আমাদের", "আমার"]:
                if cand.startswith(pfx):
                    cand = cand[len(pfx):].strip()
            cand_stem = re.sub(r'(?:ের|র|ে|টি|টির|গুলো)$', '', cand.strip()).strip()
            if cand_stem in ["প্রতিষ্ঠান", "স্কুল", "মাদ্রাসা", "মাদরাসা", "কলেজ", "আমাদের প্রতিষ্ঠান", "আমার প্রতিষ্ঠান", "id card", "কার্ড", ""]:
                cand = ""
            if len(cand) > 1 and is_valid_inst_cand(cand):
                inst_name = cand
                break

        m_suf = re.search(r'((?:(?:জামিয়া|জামেয়া|মারকাজ|মারকায|মাদ্রাসা|মাদরাসা|মাদরাসাহ|দারুল|দারুল\s*উলুম|স্কুল|কলেজ|একাডেমি|একাডেমী|School|College|Academy|Institute)\s+[A-Za-z0-9\u0980-\u09FF\s\.\-]{2,40})|(?:[A-Za-z0-9\u0980-\u09FF\s\.\-]{2,40}\s*(?:মাদ্রাসা|মাদরাসা|মাদরাসাহ|জামিয়া|জামেয়া|মারকাজ|মারকায|স্কুল|School|College|কলেজ|Academy|একাডেমি|একাডেমী|ইনস্টিটিউট|Institute|High School|Primary School|কিন্ডারগার্টেন|বিশ্ববিদ্যালয়|University)))', t, re.IGNORECASE)
        if m_suf:
            cand = m_suf.group(1).strip()
            cand = re.sub(phone_pattern, '', cand).strip()
            for pfx in ["দয়া করে", "প্লিজ", "ভাই", "স্যার", "আমাদের", "আমার"]:
                if cand.startswith(pfx):
                    cand = cand[len(pfx):].strip()
            cand_stem = re.sub(r'(?:ের|র|ে|টি|টির|গুলো)$', '', cand.strip()).strip()
            if cand_stem in ["প্রতিষ্ঠান", "স্কুল", "মাদ্রাসা", "মাদরাসা", "কলেজ", "আমাদের প্রতিষ্ঠান", "আমার প্রতিষ্ঠান", "id card", "কার্ড", ""]:
                cand = ""
            if len(cand) > 1 and is_valid_inst_cand(cand):
                inst_name = cand
                break

    # Contextual reply extraction if user answered assistant's "প্রতিষ্ঠানের নাম" prompt
    if not inst_name and is_awaiting_name:
        cand = msg_raw.split("\n")[0].split(",")[0].split("।")[0].strip()
        cand = re.sub(phone_pattern, '', cand).strip()
        for pfx in ["দয়া করে", "প্লিজ", "আমাদের প্রতিষ্ঠানের নাম", "প্রতিষ্ঠানের নাম", "নাম", "আমাদের", "আমার"]:
            if cand.startswith(pfx):
                cand = cand[len(pfx):].lstrip(": ").strip()
        if len(cand) >= 2 and is_valid_inst_cand(cand) and len(cand.split()) <= 7:
            inst_name = cand

    # FALLBACK: Extract institution name from assistant's own previous messages
    if not inst_name:
        for m in reversed(flat_history):
            if m["role"] == "assistant":
                bot_text = m["text"]
                name_from_bot = re.search(r"প্রতিষ্ঠানের\s*নাম[টি]*\s*['\"\'\"\(]?\s*([^'\"\'\"।\n\(\)]+?)\s*['\"\'\"\)]?\s*(?:নোট|লিখে|রেকর্ড|সংগ্রহ)", bot_text)
                if name_from_bot:
                    cand = name_from_bot.group(1).strip().strip("'\"")
                    if len(cand) >= 2 and cand not in ["আমাদের", "আপনার", "প্রতিষ্ঠান"] and is_valid_inst_cand(cand):
                        inst_name = cand
                        break

    # FALLBACK: If a user message appears directly after a "নামটি দিন" prompt from bot,
    # treat it as the institution name (even without institutional suffixes)
    if not inst_name and has_explicit_form_intent:
        for i, m in enumerate(flat_history):
            if m["role"] == "assistant" and any(q in m["text"] for q in ["নামটি দিন", "নাম দিন", "নাম বলুন"]):
                if i + 1 < len(flat_history) and flat_history[i + 1]["role"] == "user":
                    cand = flat_history[i + 1]["text"].split("\n")[0].split(",")[0].strip()
                    cand = re.sub(phone_pattern, '', cand).strip()
                    if len(cand) >= 2 and not any(kw in cand.lower() for kw in ["ফর্ম", "ফরম", "দাম", "কত", "কিভাবে"]):
                        inst_name = cand
                        break

    # 4. Extract requested fields across thread
    all_detected_fields = []
    seen_keys = set()
    for m in full_thread:
        if m["role"] == "user":
            fields = detect_fields_from_natural_language(m["text"], fallback_to_defaults=False)
            for f in fields:
                if f["key"] not in seen_keys:
                    seen_keys.add(f["key"])
                    all_detected_fields.append(f)

    # 5. Check if form already exists in database for this institution/mobile
    from app.database import get_generated_form_by_institution, get_generated_forms_by_mobile, get_google_connection
    existing_form = None
    conn_data = get_google_connection(workspace_id=int(workspace_id or 1))
    master_form_id = conn_data.get("master_form_id") if conn_data else None

    if inst_name and inst_mobile:
        cand = get_generated_form_by_institution(workspace_id=int(workspace_id or 1), institution_name=inst_name, institution_mobile=inst_mobile)
        if cand and cand.get("form_id") != master_form_id:
            existing_form = cand
    elif inst_mobile and not inst_name and has_explicit_form_intent:
        mobile_forms = get_generated_forms_by_mobile(workspace_id=int(workspace_id or 1), mobile=inst_mobile)
        for mf in mobile_forms:
            if mf.get("form_id") != master_form_id:
                existing_form = mf
                break
    elif inst_name and not inst_mobile and has_explicit_form_intent:
        cand = get_generated_form_by_institution(workspace_id=int(workspace_id or 1), institution_name=inst_name)
        if cand and cand.get("form_id") != master_form_id:
            existing_form = cand

    if existing_form and has_explicit_form_intent:
        e_form_id = existing_form.get("form_id")
        from app.google_integration.forms_service import verify_generated_form
        conn_data = get_google_connection(workspace_id=int(workspace_id or 1))
        is_verified = True
        v_res = {}
        if conn_data and conn_data.get("status") == "connected":
            v_res = verify_generated_form(
                workspace_id=int(workspace_id or 1),
                form_id=e_form_id,
                sheet_url=existing_form.get("response_sheet_url") or existing_form.get("sheet_url"),
                drive_folder_id=existing_form.get("drive_folder_id"),
                check_file_upload=True
            )
            is_verified = v_res.get("success", False)

        if is_verified:
            resp_url = v_res.get("responder_url") or v_res.get("form_url") or existing_form.get("responder_uri") or existing_form.get("form_url") or (f"https://docs.google.com/forms/d/{e_form_id}/viewform" if e_form_id else "")
            sheet_url = v_res.get("sheet_url") or existing_form.get("response_sheet_url") or existing_form.get("sheet_url") or ""
            return {
                "status": "created",
                "success": True,
                "is_existing": True,
                "institution_name": existing_form.get("institution_name") or inst_name,
                "institution_mobile": existing_form.get("institution_mobile") or inst_mobile,
                "form_id": existing_form.get("form_id"),
                "form_url": resp_url,
                "sheet_url": sheet_url,
                "reply": (
                    f"জি স্যার! আপনার প্রতিষ্ঠানের জন্য তৈরি করা Google Form নিচে দেওয়া হলো:\n\n"
                    f"🏫 প্রতিষ্ঠান: {existing_form.get('institution_name') or inst_name}\n"
                    f"📱 মোবাইল: {existing_form.get('institution_mobile') or inst_mobile}\n\n"
                    f"📋 ফর্ম লিংক:\n{resp_url}\n\n"
                    f"📊 রেসপন্স শিট:\n{sheet_url}\n\n"
                    f"এই লিংকের মাধ্যমে খুব সহজেই ছাত্র-ছাত্রীদের তথ্য ও ছবি সংগ্রহ করতে পারবেন।"
                )
            }
        else:
            safe_err = str(v_res.get('error', '')).encode('ascii', 'replace').decode('ascii')
            print(f"[Existing form {e_form_id} verification failed]: {safe_err}. Ignoring broken record.")
            existing_form = None

    # 6. Evaluate state progression
    if not inst_name:
        # If user explicitly asked for a form, prompt for name
        if has_explicit_form_intent:
            return {
                "status": "need_name",
                "institution_name": "",
                "institution_mobile": inst_mobile,
                "selected_fields": all_detected_fields,
                "reply": "অবশ্যই স্যার। ফর্ম তৈরি করার জন্য প্রথমে আপনার প্রতিষ্ঠানের নামটি দিন।"
            }
        return None

    # If user was asked for name (is_awaiting_name), prompt for mobile next
    if is_awaiting_name:
        return {
            "status": "need_mobile",
            "institution_name": inst_name,
            "institution_mobile": inst_mobile,
            "selected_fields": all_detected_fields,
            "reply": "ধন্যবাদ স্যার। এখন প্রতিষ্ঠানের মোবাইল নম্বরটি দিন।"
        }

    if not inst_mobile:
        # If user has form intent or is in mobile flow, prompt for mobile
        if has_explicit_form_intent or is_awaiting_mobile:
            return {
                "status": "need_mobile",
                "institution_name": inst_name,
                "institution_mobile": "",
                "selected_fields": all_detected_fields,
                "reply": "ধন্যবাদ স্যার। এখন প্রতিষ্ঠানের মোবাইল নম্বরটি দিন।"
            }
        return None

    if not all_detected_fields:
        # If user was asked for mobile (is_awaiting_mobile), prompt for fields next
        if is_awaiting_mobile or is_awaiting_fields:
            return {
                "status": "need_fields",
                "institution_name": inst_name,
                "institution_mobile": inst_mobile,
                "selected_fields": [],
                "reply": "ধন্যবাদ স্যার। এবার বলুন, শিক্ষার্থীদের ফর্মে কোন কোন তথ্য রাখতে চান?\nযেমন: নাম, পিতার নাম, মাতার নাম, জন্মতারিখ, শ্রেণি, রোল, ঠিকানা, ছবি ইত্যাদি।"
            }
        elif has_explicit_form_intent:
            # If customer has explicit form intent ("আমার গুগল ফরম কোথায়", "গুগল ফর্ম দাও") and we already have Name & Mobile:
            # Auto-use standard default ID card fields so form is created immediately!
            all_detected_fields = [
                {"key": "student_name", "label": "শিক্ষার্থীর নাম"},
                {"key": "father_name", "label": "পিতার নাম"},
                {"key": "mother_name", "label": "মাতার নাম"},
                {"key": "dob", "label": "জন্মতারিখ"},
                {"key": "class_name", "label": "শ্রেণি"},
                {"key": "roll", "label": "রোল"},
                {"key": "address", "label": "ঠিকানা"},
                {"key": "student_photo", "label": "ছবি"}
            ]
        else:
            return None

    print(f"[GOOGLE_FORM_WORKFLOW] State = READY_TO_CREATE")

    # All 3 required components are collected: CREATE FORM!
    selected_keys = [f["key"] for f in all_detected_fields]
    try:
        create_res = create_institution_form(
            workspace_id=int(workspace_id or 1),
            institution_name=inst_name,
            institution_mobile=inst_mobile,
            selected_fields=selected_keys,
            allow_duplicate=False
        )

        if create_res.get("success") and (create_res.get("responder_url") or create_res.get("form_url")):
            form_url = create_res.get("responder_url") or create_res.get("form_url") or ""
            sheet_url = create_res.get("sheet_url") or ""

            success_reply = (
                f"আলহামদুলিল্লাহ স্যার, আপনার প্রতিষ্ঠানের জন্য Google Form তৈরি হয়ে গেছে।\n\n"
                f"🏫 প্রতিষ্ঠান: {inst_name}\n"
                f"📱 মোবাইল: {inst_mobile}\n\n"
                f"📋 ফর্ম:\n{form_url}\n\n"
                f"📊 Google Sheet:\n{sheet_url}\n\n"
                f"আপনি চাইলে এখনই এই লিংকটি ব্যবহার করতে পারেন।"
            )

            return {
                "status": "created",
                "success": True,
                "institution_name": inst_name,
                "institution_mobile": inst_mobile,
                "selected_fields": all_detected_fields,
                "form_id": create_res.get("form_id"),
                "form_title": create_res.get("form_title"),
                "sheet_title": create_res.get("sheet_title"),
                "form_url": form_url,
                "sheet_url": sheet_url,
                "reply": success_reply
            }
        else:
            err_msg = create_res.get("error") or "Verification failed"
            fail_reason = create_res.get("failure_reason") or "VERIFICATION_FAILED"
            fail_reply = create_res.get("message") or "স্যার, ফর্ম তৈরির সময় ছবির Upload অপশন সক্রিয় করতে সমস্যা হয়েছে। আমি আবার চেষ্টা করছি।"
            print(f"[Form Workflow Creation Failed]: {err_msg} ({fail_reason})")
            return {
                "status": "error",
                "success": False,
                "error": err_msg,
                "failure_reason": fail_reason,
                "institution_name": inst_name,
                "institution_mobile": inst_mobile,
                "reply": fail_reply
            }
    except Exception as e:
        safe_e = str(e).encode('ascii', 'replace').decode('ascii')
        print(f"[resolve_google_form_workflow Error]: {safe_e}")
        return {
            "status": "error",
            "success": False,
            "error": str(e),
            "failure_reason": "EXCEPTION_ERROR",
            "institution_name": inst_name,
            "institution_mobile": inst_mobile,
            "reply": "স্যার, ফর্ম তৈরির সময় ছবির Upload অপশন সক্রিয় করতে সমস্যা হয়েছে। আমি আবার চেষ্টা করছি।"
        }
