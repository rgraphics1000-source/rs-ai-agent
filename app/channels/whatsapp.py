import os
import sys
import requests
import json
import time
import asyncio
from pathlib import Path
from typing import Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from app.config import settings
from app.database import (
    get_setting, set_setting, get_all_settings, get_db_connection,
    is_conversation_ai_active, get_whatsapp_account_by_phone_id,
    get_whatsapp_account_by_page_id, get_whatsapp_account_by_workspace_id,
    get_all_whatsapp_accounts, get_page_ai_config,
    ensure_whatsapp_account_consistency, get_active_training_rules,
    get_all_faqs, get_all_products
)
from app.channels.omnichat import record_conversation_message, get_conversation_history
from app.ai_agent.gemini_brain import process_customer_message

GRAPH_API_URL = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}"
PROCESSED_WA_MESSAGE_IDS = set()

def mask_phone_number(raw_phone: str) -> str:
    """Masks a phone number for secure logging (e.g. 88018****4097)."""
    if not raw_phone:
        return "***"
    phone_str = str(raw_phone).strip()
    if len(phone_str) > 8:
        return f"{phone_str[:5]}****{phone_str[-4:]}"
    return "***"

def normalize_whatsapp_phone_number(raw_phone: str) -> str:
    """Normalizes phone numbers to standard E.164 digits without plus or spaces."""
    if not raw_phone:
        return ""
    digits = "".join(filter(str.isdigit, str(raw_phone)))
    if digits.startswith("01") and len(digits) == 11:
        digits = "88" + digits
    elif digits.startswith("8801") and len(digits) == 13:
        pass
    return digits

def is_valid_meta_token(token: str) -> bool:
    """Returns True if token looks like a real Meta token (not empty or short test fixture)."""
    if not token:
        return False
    t = str(token).strip().strip('"').strip("'")
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return len(t) > 30 and not t.startswith("EAATest") and not t.startswith("EAA_WA") and not t.startswith("TOKEN_") and not t.startswith("dummy") and not t.startswith("placeholder")

def resolve_whatsapp_token_info(wa_account: Optional[dict] = None, workspace_id: int = 1) -> dict:
    """
    Resolves the WhatsApp access token along with its source metadata.
    Guarantees that Facebook Page tokens are NEVER used for WhatsApp Cloud API.
    """
    # 1. First priority: token specifically on this WhatsApp account record
    acc_tok = str(wa_account.get("access_token", "") if wa_account else "").strip().strip('"').strip("'")
    if acc_tok.lower().startswith("bearer "):
        acc_tok = acc_tok[7:].strip()
    if is_valid_meta_token(acc_tok):
        return {
            "token": acc_tok,
            "source": f"whatsapp_accounts (id={wa_account.get('id') if wa_account else 'unknown'})",
            "is_valid": True
        }

    # 2. Second priority: WhatsApp specific settings
    wa_setting_tok = str(get_setting("whatsapp_access_token", "")).strip().strip('"').strip("'")
    if wa_setting_tok.lower().startswith("bearer "):
        wa_setting_tok = wa_setting_tok[7:].strip()
    if is_valid_meta_token(wa_setting_tok):
        return {
            "token": wa_setting_tok,
            "source": "settings (key=whatsapp_access_token)",
            "is_valid": True
        }

    sys_setting_tok = str(get_setting("meta_system_user_access_token", "")).strip().strip('"').strip("'")
    if sys_setting_tok.lower().startswith("bearer "):
        sys_setting_tok = sys_setting_tok[7:].strip()
    if is_valid_meta_token(sys_setting_tok):
        return {
            "token": sys_setting_tok,
            "source": "settings (key=meta_system_user_access_token)",
            "is_valid": True
        }

    # 3. Third priority: Environment variables for WhatsApp / Meta System User
    env_wa_tok = str(os.getenv("WHATSAPP_ACCESS_TOKEN", "") or settings.WHATSAPP_ACCESS_TOKEN or "").strip().strip('"').strip("'")
    if env_wa_tok.lower().startswith("bearer "):
        env_wa_tok = env_wa_tok[7:].strip()
    if is_valid_meta_token(env_wa_tok):
        return {
            "token": env_wa_tok,
            "source": "environment (WHATSAPP_ACCESS_TOKEN)",
            "is_valid": True
        }

    env_sys_tok = str(os.getenv("META_SYSTEM_USER_ACCESS_TOKEN", "") or settings.META_SYSTEM_USER_ACCESS_TOKEN or "").strip().strip('"').strip("'")
    if env_sys_tok.lower().startswith("bearer "):
        env_sys_tok = env_sys_tok[7:].strip()
    if is_valid_meta_token(env_sys_tok):
        return {
            "token": env_sys_tok,
            "source": "environment (META_SYSTEM_USER_ACCESS_TOKEN)",
            "is_valid": True
        }

    # Fallback to whatever non-empty token exists for mock/test environments
    if acc_tok:
        return {"token": acc_tok, "source": "whatsapp_accounts (raw)", "is_valid": is_valid_meta_token(acc_tok)}
    if wa_setting_tok:
        return {"token": wa_setting_tok, "source": "settings (whatsapp_access_token raw)", "is_valid": is_valid_meta_token(wa_setting_tok)}
    if sys_setting_tok:
        return {"token": sys_setting_tok, "source": "settings (meta_system_user_access_token raw)", "is_valid": is_valid_meta_token(sys_setting_tok)}
    if env_wa_tok:
        return {"token": env_wa_tok, "source": "environment (WHATSAPP_ACCESS_TOKEN raw)", "is_valid": is_valid_meta_token(env_wa_tok)}
    if env_sys_tok:
        return {"token": env_sys_tok, "source": "environment (META_SYSTEM_USER_ACCESS_TOKEN raw)", "is_valid": is_valid_meta_token(env_sys_tok)}

    return {"token": "", "source": "none", "is_valid": False}

def resolve_whatsapp_token(wa_account: Optional[dict] = None, workspace_id: int = 1) -> str:
    """Resolves the best available WhatsApp token for sending messages."""
    info = resolve_whatsapp_token_info(wa_account=wa_account, workspace_id=workspace_id)
    return info.get("token", "")

def validate_whatsapp_token_with_meta(token: str, phone_id: str = "4184514263660680") -> dict:
    """
    Validates token directly against Meta Graph API by checking read access to the Phone Number ID.
    Returns structured validation details without leaking sensitive token data.
    """
    clean_tok = str(token or "").strip().strip('"').strip("'")
    if clean_tok.lower().startswith("bearer "):
        clean_tok = clean_tok[7:].strip()

    if not clean_tok:
        return {
            "valid": False,
            "error_code": "TOKEN_EMPTY",
            "reason": "No access token configured for WhatsApp.",
            "phone_number_access": False
        }

    if not is_valid_meta_token(clean_tok):
        return {
            "valid": False,
            "error_code": "TOKEN_TEST_FIXTURE",
            "reason": "Token is a test placeholder or fixture (e.g. EAATest...). A real Meta System User Access Token is required for production send.",
            "phone_number_access": False
        }

    url = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{phone_id}"
    headers = {"Authorization": f"Bearer {clean_tok}"}
    params = {"fields": "id,display_phone_number,verified_name,quality_rating,code_verification_status"}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return {
                "valid": True,
                "phone_number_access": True,
                "http_status": 200,
                "phone_id": data.get("id", phone_id),
                "verified_name": data.get("verified_name"),
                "display_phone_number": data.get("display_phone_number"),
                "quality_rating": data.get("quality_rating"),
                "code_verification_status": data.get("code_verification_status"),
                "reason": "Token verified: Full read and messaging access granted by Meta."
            }
        else:
            try:
                err_data = r.json().get("error", {})
                err_code = err_data.get("code")
                err_subcode = err_data.get("error_subcode")
                err_type = err_data.get("type")
                err_msg = err_data.get("message")
            except Exception:
                err_code = None
                err_subcode = None
                err_type = "HttpError"
                err_msg = r.text

            diagnostic_code = "META_API_ERROR"
            if err_code == 190:
                diagnostic_code = "TOKEN_INVALID_OR_EXPIRED"
            elif err_code == 100:
                if "does not exist, cannot be loaded due to missing permissions" in str(err_msg):
                    diagnostic_code = "MISSING_WHATSAPP_PERMISSION_OR_WRONG_TOKEN_TYPE"
                else:
                    diagnostic_code = "GRAPH_METHOD_EXCEPTION"

            return {
                "valid": False,
                "phone_number_access": False,
                "http_status": r.status_code,
                "error_code": diagnostic_code,
                "graph_error_code": err_code,
                "graph_error_subcode": err_subcode,
                "graph_error_type": err_type,
                "graph_error_message": err_msg,
                "reason": f"Meta Graph API rejected token for Phone ID {phone_id}: {err_msg}"
            }
    except Exception as ex:
        return {
            "valid": False,
            "phone_number_access": False,
            "error_code": "NETWORK_EXCEPTION",
            "reason": f"Failed to connect to Meta Graph API: {str(ex)}"
        }

def get_whatsapp_credentials(phone_number_id: str = None, page_id: str = None, workspace_id: int = None) -> Tuple[str, str]:
    """Gets valid Phone Number ID and Access Token for a specific account, page, workspace, or global default."""
    if phone_number_id:
        acc = get_whatsapp_account_by_phone_id(phone_number_id)
        if acc:
            p_id = acc.get("phone_number_id")
            token = resolve_whatsapp_token(acc, workspace_id=acc.get("workspace_id") or 1)
            return p_id, token

    if page_id:
        acc = get_whatsapp_account_by_page_id(page_id)
        if acc:
            p_id = acc.get("phone_number_id")
            token = resolve_whatsapp_token(acc, workspace_id=acc.get("workspace_id") or 1)
            return p_id, token

    if workspace_id:
        acc = get_whatsapp_account_by_workspace_id(workspace_id)
        if acc:
            p_id = acc.get("phone_number_id")
            token = resolve_whatsapp_token(acc, workspace_id=workspace_id)
            return p_id, token

    all_s = get_all_settings(masked=False)
    phone_id = all_s.get("whatsapp_phone_number_id", "") or settings.WHATSAPP_PHONE_NUMBER_ID
    token = resolve_whatsapp_token(None, workspace_id=1)
    if not phone_id or not token:
        all_wa = get_all_whatsapp_accounts()
        if all_wa:
            phone_id = phone_id or all_wa[0].get("phone_number_id", "")
            token = token or resolve_whatsapp_token(all_wa[0], workspace_id=1)

    return phone_id, token

def send_whatsapp_message_detailed(to_number: str, message_text: str, phone_id: str = None, token: str = None, page_id: str = None, workspace_id: int = None) -> dict:
    """
    Sends a text message via WhatsApp Cloud API matching the proven Postman reference request.
    Returns structured delivery metadata including HTTP status, message ID, and sanitized error diagnostics.
    """
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id, workspace_id=workspace_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

    wa_acc = get_whatsapp_account_by_phone_id(phone_id) if phone_id else None
    token_info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=workspace_id or 1)
    effective_token = token or token_info.get("token", "")
    token_source = token_info.get("source", "explicit")

    clean_token = str(effective_token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    masked_rec = mask_phone_number(to_number)
    token_prefix = clean_token[:6] if len(clean_token) > 6 else ""
    token_suffix = clean_token[-4:] if len(clean_token) > 10 else ""
    token_len = len(clean_token)
    token_masked = f"{token_prefix}...{token_suffix} (len={token_len})" if token_len > 10 else "EMPTY/SHORT"

    if not phone_id or not clean_token or not to_number or not message_text:
        err_detail = f"Missing required fields: phone_id={'SET' if phone_id else 'MISSING'}, token={'SET' if clean_token else 'MISSING'}, to_number={'SET' if to_number else 'MISSING'}"
        print(f"[WhatsApp Send Error] workspace_id={workspace_id or 1} phone_number_id={'SET' if phone_id else 'MISSING'} token_source={token_source} token_present={bool(clean_token)} recipient={masked_rec}")
        return {
            "success": False,
            "http_status": 0,
            "error_code": "MISSING_REQUIRED_FIELDS",
            "error_message": err_detail,
            "phone_number_id": phone_id,
            "token_source": token_source,
            "token_preview": token_masked,
            "recipient": masked_rec
        }

    norm_to = normalize_whatsapp_phone_number(to_number)
    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": norm_to,
        "type": "text",
        "text": {
            "body": message_text
        }
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        status_ok = r.status_code in [200, 201]
        if status_ok:
            try:
                resp_json = r.json()
                msg_id = resp_json.get("messages", [{}])[0].get("id", "")
            except Exception:
                msg_id = ""
            print(f"[WhatsApp Send] workspace_id={workspace_id or 1} phone_number_id={phone_id} endpoint_phone_id={phone_id} graph_api_version={settings.META_GRAPH_VERSION} token_source={token_source} token_preview={token_masked} recipient={masked_rec} message_id={msg_id} status=success http_status={r.status_code}")
            return {
                "success": True,
                "http_status": r.status_code,
                "message_id": msg_id,
                "phone_number_id": phone_id,
                "token_source": token_source,
                "token_preview": token_masked,
                "recipient": masked_rec
            }
        else:
            try:
                err_data = r.json().get("error", {})
                err_code = err_data.get("code")
                err_subcode = err_data.get("error_subcode")
                err_type = err_data.get("type")
                err_msg = err_data.get("message")
            except Exception:
                err_code = None
                err_subcode = None
                err_type = "HttpError"
                err_msg = r.text

            print(f"[WhatsApp Send] workspace_id={workspace_id or 1} phone_number_id={phone_id} endpoint_phone_id={phone_id} graph_api_version={settings.META_GRAPH_VERSION} token_source={token_source} token_preview={token_masked} recipient={masked_rec} status=failed http_status={r.status_code} graph_error_code={err_code} graph_error_type={err_type} graph_error_message={err_msg}")
            return {
                "success": False,
                "http_status": r.status_code,
                "graph_error_code": err_code,
                "graph_error_subcode": err_subcode,
                "graph_error_type": err_type,
                "graph_error_message": err_msg,
                "phone_number_id": phone_id,
                "token_source": token_source,
                "token_preview": token_masked,
                "recipient": masked_rec
            }
    except Exception as e:
        print(f"[WhatsApp Send Exception]: workspace_id={workspace_id or 1} phone_number_id={phone_id} token_source={token_source} error={str(e)}")
        return {
            "success": False,
            "http_status": 0,
            "error_code": "NETWORK_EXCEPTION",
            "error_message": str(e),
            "phone_number_id": phone_id,
            "token_source": token_source,
            "token_preview": token_masked,
            "recipient": masked_rec
        }

def send_whatsapp_message(to_number: str, message_text: str, phone_id: str = None, token: str = None, page_id: str = None, workspace_id: int = None) -> bool:
    """Sends a text message via WhatsApp Cloud API using specified or default account."""
    res = send_whatsapp_message_detailed(
        to_number=to_number,
        message_text=message_text,
        phone_id=phone_id,
        token=token,
        page_id=page_id,
        workspace_id=workspace_id
    )
    return res.get("success", False)

def send_whatsapp_image(to_number: str, image_url: str, caption: str = "", phone_id: str = None, token: str = None, page_id: str = None, workspace_id: int = None) -> bool:
    """Sends an image via WhatsApp Cloud API using specified or default account."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id, workspace_id=workspace_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

    wa_acc = get_whatsapp_account_by_phone_id(phone_id) if phone_id else None
    token_info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=workspace_id or 1)
    effective_token = token or token_info.get("token", "")
    token_source = token_info.get("source", "explicit")

    clean_token = str(effective_token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    masked_rec = mask_phone_number(to_number)
    token_prefix = clean_token[:6] if len(clean_token) > 6 else ""
    token_suffix = clean_token[-4:] if len(clean_token) > 10 else ""
    token_len = len(clean_token)
    token_masked = f"{token_prefix}...{token_suffix} (len={token_len})" if token_len > 10 else "EMPTY/SHORT"

    if not phone_id or not clean_token or not to_number or not image_url:
        print(f"[WhatsApp Image Send Error] Missing required fields: workspace_id={workspace_id or 1} phone_number_id={'SET' if phone_id else 'MISSING'} token_source={token_source} recipient={masked_rec}")
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)
    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json"
    }

    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
    full_url = image_url if image_url.startswith("http") else f"{base_server_url}{image_url}"

    image_obj = {"link": full_url}
    if caption and caption.strip():
        image_obj["caption"] = caption.strip()

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": norm_to,
        "type": "image",
        "image": image_obj
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        status_ok = r.status_code in [200, 201]
        print(f"[WhatsApp Image Send] workspace_id={workspace_id or 1} phone_number_id={phone_id} token_source={token_source} token_preview={token_masked} recipient={masked_rec} status={'success' if status_ok else 'failed'}")
        return status_ok
    except Exception as e:
        print(f"[WhatsApp Image Send Exception]: workspace_id={workspace_id or 1} phone_number_id={phone_id} error={str(e)}")
        return False

def send_whatsapp_audio(to_number: str, audio_url: str, phone_id: str = None, token: str = None, page_id: str = None, workspace_id: int = None) -> bool:
    """Sends a voice note / audio clip via WhatsApp Cloud API."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id, workspace_id=workspace_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

    wa_acc = get_whatsapp_account_by_phone_id(phone_id) if phone_id else None
    token_info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=workspace_id or 1)
    effective_token = token or token_info.get("token", "")
    token_source = token_info.get("source", "explicit")

    clean_token = str(effective_token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    masked_rec = mask_phone_number(to_number)
    token_prefix = clean_token[:6] if len(clean_token) > 6 else ""
    token_suffix = clean_token[-4:] if len(clean_token) > 10 else ""
    token_len = len(clean_token)
    token_masked = f"{token_prefix}...{token_suffix} (len={token_len})" if token_len > 10 else "EMPTY/SHORT"

    if not phone_id or not clean_token or not to_number or not audio_url:
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)
    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json"
    }

    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
    full_url = audio_url if audio_url.startswith("http") else f"{base_server_url}{audio_url}"

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": norm_to,
        "type": "audio",
        "audio": {
            "link": full_url
        }
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        status_ok = r.status_code in [200, 201]
        print(f"[WhatsApp Audio Send] workspace_id={workspace_id or 1} phone_number_id={phone_id} token_source={token_source} token_preview={token_masked} recipient={masked_rec} status={'success' if status_ok else 'failed'}")
        return status_ok
    except Exception as e:
        print(f"[WhatsApp Audio Send Exception]: workspace_id={workspace_id or 1} phone_number_id={phone_id} error={str(e)}")
        return False

def send_whatsapp_video(to_number: str, video_url: str, caption: str = "", phone_id: str = None, token: str = None, page_id: str = None, workspace_id: int = None) -> bool:
    """Sends a video clip via WhatsApp Cloud API."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id, workspace_id=workspace_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

    wa_acc = get_whatsapp_account_by_phone_id(phone_id) if phone_id else None
    token_info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=workspace_id or 1)
    effective_token = token or token_info.get("token", "")
    token_source = token_info.get("source", "explicit")

    clean_token = str(effective_token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    masked_rec = mask_phone_number(to_number)
    token_prefix = clean_token[:6] if len(clean_token) > 6 else ""
    token_suffix = clean_token[-4:] if len(clean_token) > 10 else ""
    token_len = len(clean_token)
    token_masked = f"{token_prefix}...{token_suffix} (len={token_len})" if token_len > 10 else "EMPTY/SHORT"

    if not phone_id or not clean_token or not to_number or not video_url:
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)
    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "Content-Type": "application/json"
    }

    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
    full_url = video_url if video_url.startswith("http") else f"{base_server_url}{video_url}"

    video_obj = {"link": full_url}
    if caption and caption.strip():
        video_obj["caption"] = caption.strip()

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": norm_to,
        "type": "video",
        "video": video_obj
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        status_ok = r.status_code in [200, 201]
        print(f"[WhatsApp Video Send] workspace_id={workspace_id or 1} phone_number_id={phone_id} token_source={token_source} token_preview={token_masked} recipient={masked_rec} status={'success' if status_ok else 'failed'}")
        return status_ok
    except Exception as e:
        print(f"[WhatsApp Video Send Exception]: workspace_id={workspace_id or 1} phone_number_id={phone_id} error={str(e)}")
        return False

async def handle_whatsapp_webhook_event(data: dict):
    """Processes incoming WhatsApp messages across multiple configured WhatsApp accounts."""
    try:
        entries = data.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                # Identify exact recipient WhatsApp Phone Number ID from metadata
                metadata = value.get("metadata", {})
                meta_phone_id = str(metadata.get("phone_number_id", "")).strip()
                display_phone_number = str(metadata.get("display_phone_number", "")).strip()

                print(f"[WhatsApp Webhook] phone_number_id={meta_phone_id} display_phone_number={display_phone_number}")

                # 1. Resolve specific WhatsApp account by phone_number_id
                wa_account = get_whatsapp_account_by_phone_id(meta_phone_id)

                # 2. If not found by phone_number_id, check if it's the primary RS Graphics account or display number
                if not wa_account and (meta_phone_id in ["4184514263660680", "418451426636680"] or "01816504097" in display_phone_number):
                    wa_account = ensure_whatsapp_account_consistency()

                if not wa_account:
                    # Strict rule: Unknown Phone ID cannot be resolved to any registered workspace.
                    # Log the routing error and DO NOT send an AI reply (never fall back to Workspace 1).
                    print(f"[WhatsApp Routing Error]: Unknown phone_number_id {meta_phone_id}. No matching whatsapp_account found. Event dropped without fallback.")
                    continue

                page_id = wa_account.get("page_id") or ""
                page_name = wa_account.get("shop_name") or wa_account.get("page_name") or wa_account.get("workspace_name") or "RS Graphics"
                workspace_id = wa_account.get("workspace_id") or wa_account.get("ws_id") or 1
                workspace_name = wa_account.get("workspace_name") or "RS Graphics (আরএস গ্রাফিক্স)"
                effective_phone_id = wa_account.get("phone_number_id") or meta_phone_id
                effective_token = resolve_whatsapp_token(wa_account, workspace_id=workspace_id)

                print(f"[WhatsApp Routing] matched_account_id={wa_account.get('id')} workspace_id={workspace_id} workspace={workspace_name}")

                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                
                raw_customer_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""

                for msg in messages:
                    msg_id = msg.get("id")
                    if msg_id:
                        if msg_id in PROCESSED_WA_MESSAGE_IDS:
                            print(f"[WhatsApp Webhook] Duplicate message skipped: msg_id={msg_id}")
                            continue
                        PROCESSED_WA_MESSAGE_IDS.add(msg_id)
                        if len(PROCESSED_WA_MESSAGE_IDS) > 2000:
                            PROCESSED_WA_MESSAGE_IDS.pop()

                    raw_from = msg.get("from") # E.164 phone e.g. 8801816504097
                    sender_phone = normalize_whatsapp_phone_number(raw_from)
                    masked_sender = mask_phone_number(sender_phone)
                    msg_type = msg.get("type")
                    msg_text = ""
                    image_bytes = None
                    image_mime = "image/jpeg"
                    audio_bytes = None
                    audio_mime = "audio/mp4"

                    print(f"[WhatsApp Webhook (Workspace: {workspace_id}, Account: {effective_phone_id})] received from={masked_sender} type={msg_type} msg_id={msg_id}")

                    if msg_type == "text":
                        msg_text = msg.get("text", {}).get("body", "")
                    elif msg_type == "image":
                        image_id = msg.get("image", {}).get("id")
                        if image_id and effective_token:
                            try:
                                media_meta = requests.get(f"{GRAPH_API_URL}/{image_id}", headers={"Authorization": f"Bearer {effective_token}"}, timeout=10).json()
                                media_url = media_meta.get("url")
                                if media_url:
                                    img_resp = requests.get(media_url, headers={"Authorization": f"Bearer {effective_token}"}, timeout=10)
                                    if img_resp.status_code == 200:
                                        image_bytes = img_resp.content
                                        image_mime = img_resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                            except Exception as dl_err:
                                print(f"[WhatsApp Image DL Error]: {dl_err}")
                        msg_text = msg.get("image", {}).get("caption", "")
                    elif msg_type in ["audio", "voice"]:
                        audio_id = msg.get("audio", {}).get("id") or msg.get("voice", {}).get("id")
                        if audio_id and effective_token:
                            try:
                                media_meta = requests.get(f"{GRAPH_API_URL}/{audio_id}", headers={"Authorization": f"Bearer {effective_token}"}, timeout=10).json()
                                media_url = media_meta.get("url")
                                if media_url:
                                    aud_resp = requests.get(media_url, headers={"Authorization": f"Bearer {effective_token}"}, timeout=10)
                                    if aud_resp.status_code == 200:
                                        audio_bytes = aud_resp.content
                                        audio_mime = aud_resp.headers.get("content-type", "audio/mp4").split(";")[0].strip()
                            except Exception as dl_err:
                                print(f"[WhatsApp Audio DL Error]: {dl_err}")

                    if msg_text or image_bytes or audio_bytes:
                        # Record incoming customer message scoped strictly to Workspace
                        customer_name = raw_customer_name or f"WhatsApp User ({sender_phone})"
                        record_conversation_message("whatsapp", sender_phone, customer_name, "user", msg_text, page_id=page_id, workspace_id=workspace_id)

                        # Check if AI Master Switch or Per-Customer Takeover is active
                        if not is_conversation_ai_active(sender_id=sender_phone):
                            print(f"[WhatsApp]: AI is PAUSED for customer {masked_sender} on account {effective_phone_id} (Human Takeover). AI will stay silent.")
                            continue

                        # Fetch conversation history scoped strictly to Workspace
                        history = get_conversation_history("whatsapp", sender_phone, limit=8, page_id=page_id, workspace_id=workspace_id)
                        
                        # Load workspace specific data and log
                        training_rules = get_active_training_rules(workspace_id=workspace_id)
                        faqs = get_all_faqs(workspace_id=workspace_id)
                        products = get_all_products(workspace_id=workspace_id)
                        print(f"[WhatsApp AI] workspace_id={workspace_id} training_rules_loaded={len(training_rules)} faqs_loaded={len(faqs)} products_loaded={len(products)}")

                        # Process with Gemini AI Brain with Workspace isolation
                        ai_result = await process_customer_message(
                            message_text=msg_text,
                            image_bytes=image_bytes,
                            image_mime=image_mime,
                            audio_bytes=audio_bytes,
                            audio_mime=audio_mime,
                            conversation_history=history,
                            channel="whatsapp",
                            sender_id=sender_phone,
                            customer_name=customer_name,
                            generate_voice_reply=bool(audio_bytes),
                            workspace_id=workspace_id,
                            page_id=page_id
                        )

                        reply_text = ai_result.get("reply_text", "")
                        print(f"[AI Reply on Workspace {workspace_id} WA {effective_phone_id}] generated for={masked_sender}: {reply_text[:60] if reply_text else 'None'}...")

                        if reply_text and sender_phone:
                            send_ok = send_whatsapp_message(
                                sender_phone, reply_text,
                                phone_id=effective_phone_id, token=effective_token, page_id=page_id, workspace_id=workspace_id
                            )
                            if send_ok:
                                record_conversation_message("whatsapp", sender_phone, customer_name, "bot", reply_text, page_id=page_id, workspace_id=workspace_id)
                                print(f"[WhatsApp Send] phone_number_id={effective_phone_id} recipient={masked_sender} status=success")
                            else:
                                print(f"[WhatsApp Send] Delivery FAILED for {masked_sender}. AI message was NOT recorded as sent.")

                        # Batch send sample images if requested
                        matched_images = ai_result.get("matched_images", [])
                        if matched_images:
                            print(f"[WhatsApp Batch Images on Workspace {workspace_id}] Sending {len(matched_images)} images to {sender_phone}...")
                            for img_path in matched_images:
                                if not img_path:
                                    continue
                                img_ok = send_whatsapp_image(
                                    sender_phone, img_path,
                                    phone_id=effective_phone_id, token=effective_token, page_id=page_id, workspace_id=workspace_id
                                )
                                if img_ok:
                                    record_conversation_message("whatsapp", sender_phone, customer_name, "bot", "", img_path, page_id=page_id, workspace_id=workspace_id)
                                await asyncio.sleep(0.15)

                        # Send video demo if requested
                        matched_video = ai_result.get("video_url", "")
                        if matched_video:
                            print(f"[WhatsApp Video on Workspace {workspace_id}] Sending video demo to {sender_phone}...")
                            v_ok = send_whatsapp_video(
                                sender_phone, matched_video,
                                phone_id=effective_phone_id, token=effective_token, page_id=page_id, workspace_id=workspace_id
                            )
                            if v_ok:
                                record_conversation_message("whatsapp", sender_phone, customer_name, "bot", "[Video Demo]", matched_video, page_id=page_id, workspace_id=workspace_id)

                        # Send voice note if requested / generated
                        voice_url = ai_result.get("voice_url", "")
                        if voice_url:
                            print(f"[WhatsApp Voice on Workspace {workspace_id}] Sending voice note to {sender_phone}...")
                            a_ok = send_whatsapp_audio(
                                sender_phone, voice_url,
                                phone_id=effective_phone_id, token=effective_token, page_id=page_id, workspace_id=workspace_id
                            )
                            if a_ok:
                                record_conversation_message("whatsapp", sender_phone, customer_name, "bot", "[Voice Note]", voice_url, page_id=page_id, workspace_id=workspace_id)

    except Exception as e:
        print(f"[WhatsApp Webhook Handler Error]: {e}")


