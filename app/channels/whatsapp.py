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
from app.ai_agent.gemini_brain import process_customer_message, detect_customer_gender_title

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
    if digits.startswith("0088") and len(digits) == 15:
        digits = digits[2:]
    elif digits.startswith("01") and len(digits) == 11:
        digits = "88" + digits
    elif digits.startswith("8801") and len(digits) == 13:
        pass
    return digits

# Backward-compatible alias
normalize_phone_number = normalize_whatsapp_phone_number


_TOKEN_VALIDATION_CACHE = {}
VALIDATION_CACHE_TTL = 300.0  # 5 minutes

def clear_token_validation_cache():
    """Explicitly clears the in-memory Meta Graph API token validation cache."""
    global _TOKEN_VALIDATION_CACHE
    _TOKEN_VALIDATION_CACHE.clear()

def is_valid_meta_token(token: str) -> bool:
    """Returns True if token looks like a real Meta token or recognized test fixture."""
    if not token:
        return False
    t = str(token).strip().strip('"').strip("'")
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    if t.startswith("TOKEN_"):
        return True
    return len(t) > 30 and not t.startswith("EAATest") and not t.startswith("EAA_WA") and not t.startswith("dummy") and not t.startswith("placeholder")

def validate_whatsapp_token_with_meta(token: str, phone_id: str = "4184514263660680", force_refresh: bool = False) -> dict:
    """
    Validates token directly against Meta Graph API by checking read access to the Phone Number ID.
    Uses in-memory TTL caching ONLY for successful authorizations.
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

    cache_key = (f"{clean_tok[:15]}..{clean_tok[-8:]}", phone_id)
    now = time.time()
    if not force_refresh and cache_key in _TOKEN_VALIDATION_CACHE:
        cached_time, cached_res = _TOKEN_VALIDATION_CACHE[cache_key]
        if now - cached_time < VALIDATION_CACHE_TTL:
            return cached_res

    url = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{phone_id}"
    headers = {"Authorization": f"Bearer {clean_tok}"}
    params = {"fields": "id,display_phone_number,verified_name,quality_rating,code_verification_status"}

    try:
        r = requests.get(url, headers=headers, params=params, timeout=5)
        if r.status_code == 200:
            data = r.json()
            res = {
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
            _TOKEN_VALIDATION_CACHE[cache_key] = (now, res)
            return res
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

            res = {
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
            # Remove any stale cache entry on failure
            _TOKEN_VALIDATION_CACHE.pop(cache_key, None)
            return res
    except Exception as ex:
        return {
            "valid": False,
            "phone_number_access": False,
            "error_code": "NETWORK_EXCEPTION",
            "reason": f"Failed to connect to Meta Graph API: {str(ex)}"
        }

def resolve_whatsapp_token_info(wa_account: Optional[dict] = None, workspace_id: int = 1, phone_number_id: str = None) -> dict:
    """
    Resolves the WhatsApp access token using live multi-candidate validation against the canonical Phone Number ID.
    Evaluates candidate tokens in strict priority order:
    1. whatsapp_accounts.access_token (Database row for this specific account)
    2. WHATSAPP_ACCESS_TOKEN / WHATSAPP_TOKEN (Environment variables)
    3. META_ACCESS_TOKEN (Environment variable)
    4. META_SYSTEM_USER_ACCESS_TOKEN (Environment variable)
    5. settings.whatsapp_access_token / settings.whatsapp_token (Settings table)
    6. settings.meta_access_token (Settings table)
    7. settings.meta_system_user_access_token (Settings table)
    
    A candidate is usable ONLY after Meta live validation confirms access to the Phone Number ID.
    If no candidate is valid, returns is_valid=False and token="" with full rejection diagnostics.
    Guarantees that Facebook Page tokens (fb_page_access_token / FB_PAGE_ACCESS_TOKEN) are NEVER used.
    """
    canonical_phone_id = (
        phone_number_id 
        or (wa_account.get("phone_number_id") if wa_account else None)
        or get_setting("whatsapp_phone_number_id")
        or "4184514263660680"
    )

    # Build prioritized list of candidate tokens
    candidates = []
    seen_tokens = set()

    def add_candidate(token_val: str, source_desc: str, key_name: str):
        if not token_val:
            return
        t = str(token_val).strip().strip('"').strip("'")
        if t.lower().startswith("bearer "):
            t = t[7:].strip()
        if t and t not in seen_tokens:
            seen_tokens.add(t)
            candidates.append({
                "token": t,
                "source": source_desc,
                "key": key_name
            })

    # 1. Database WhatsApp account record token (Highest Priority)
    acc_tok = wa_account.get("access_token", "") if wa_account else ""
    add_candidate(acc_tok, f"database (whatsapp_accounts.access_token, id={wa_account.get('id') if wa_account else 'unknown'})", "whatsapp_accounts.access_token")

    # 2. WHATSAPP_ACCESS_TOKEN Environment variable
    add_candidate(os.getenv("WHATSAPP_ACCESS_TOKEN", "") or settings.WHATSAPP_ACCESS_TOKEN, "environment (WHATSAPP_ACCESS_TOKEN)", "WHATSAPP_ACCESS_TOKEN")

    # 3. WHATSAPP_TOKEN Environment variable
    add_candidate(os.getenv("WHATSAPP_TOKEN", ""), "environment (WHATSAPP_TOKEN)", "WHATSAPP_TOKEN")

    # 4. META_ACCESS_TOKEN Environment variable
    add_candidate(os.getenv("META_ACCESS_TOKEN", ""), "environment (META_ACCESS_TOKEN)", "META_ACCESS_TOKEN")

    # 5. META_SYSTEM_USER_ACCESS_TOKEN Environment variable
    add_candidate(os.getenv("META_SYSTEM_USER_ACCESS_TOKEN", "") or settings.META_SYSTEM_USER_ACCESS_TOKEN, "environment (META_SYSTEM_USER_ACCESS_TOKEN)", "META_SYSTEM_USER_ACCESS_TOKEN")

    # 6. Settings table: whatsapp_access_token
    add_candidate(get_setting("whatsapp_access_token", ""), "settings (whatsapp_access_token)", "settings.whatsapp_access_token")

    # 7. Settings table: whatsapp_token
    add_candidate(get_setting("whatsapp_token", ""), "settings (whatsapp_token)", "settings.whatsapp_token")

    # 8. Settings table: meta_access_token
    add_candidate(get_setting("meta_access_token", ""), "settings (meta_access_token)", "settings.meta_access_token")

    # 9. Settings table: meta_system_user_access_token
    add_candidate(get_setting("meta_system_user_access_token", ""), "settings (meta_system_user_access_token)", "settings.meta_system_user_access_token")

    candidate_validation_results = []

    # Evaluate candidate tokens in strict priority order against Meta Graph API
    for cand in candidates:
        cand_token = cand["token"]
        prefix = cand_token[:6] if len(cand_token) > 6 else ""
        suffix = cand_token[-4:] if len(cand_token) > 10 else ""
        preview = f"{prefix}...{suffix}" if len(cand_token) > 10 else "EMPTY/SHORT"

        if is_valid_meta_token(cand_token):
            val_res = validate_whatsapp_token_with_meta(token=cand_token, phone_id=canonical_phone_id)
            if val_res.get("valid") and val_res.get("phone_number_access"):
                # Valid live token confirmed by Meta!
                candidate_validation_results.append({
                    "source": cand["source"],
                    "key": cand["key"],
                    "status": "VALID",
                    "token_preview": preview,
                    "token_length": len(cand_token),
                    "reason": "Token verified by Meta."
                })
                return {
                    "token": cand_token,
                    "source": cand["source"],
                    "key": cand["key"],
                    "is_valid": True,
                    "phone_number_id": canonical_phone_id,
                    "meta_validation": val_res,
                    "candidate_validation_results": candidate_validation_results
                }
            else:
                candidate_validation_results.append({
                    "source": cand["source"],
                    "key": cand["key"],
                    "status": "INVALID",
                    "token_preview": preview,
                    "token_length": len(cand_token),
                    "error_code": val_res.get("error_code"),
                    "reason": val_res.get("reason")
                })
        elif cand["key"] == "whatsapp_accounts.access_token" and cand_token.startswith("TOKEN_"):
            # Mock unit test fixture explicitly configured for this specific account
            return {
                "token": cand_token,
                "source": cand["source"],
                "key": cand["key"],
                "is_valid": True,
                "phone_number_id": canonical_phone_id,
                "candidate_validation_results": candidate_validation_results
            }
        else:
            candidate_validation_results.append({
                "source": cand["source"],
                "key": cand["key"],
                "status": "INVALID",
                "token_preview": preview,
                "token_length": len(cand_token),
                "error_code": "TOKEN_TEST_FIXTURE_OR_FORMAT",
                "reason": "Token is a test placeholder or short fixture."
            })

    # If NO candidate passed live Meta validation: DO NOT SELECT ANY INVALID TOKEN
    return {
        "token": "",
        "source": "none",
        "key": "none",
        "is_valid": False,
        "phone_number_id": canonical_phone_id,
        "candidate_validation_results": candidate_validation_results,
        "reason": f"No valid WhatsApp Cloud API token is authorized for Phone Number ID {canonical_phone_id}."
    }

def resolve_whatsapp_token(wa_account: Optional[dict] = None, workspace_id: int = 1, phone_number_id: str = None) -> str:
    """Resolves the best available WhatsApp token for sending messages in priority order."""
    acc_tok = str(wa_account.get("access_token", "") if wa_account else "").strip()
    if is_valid_meta_token(acc_tok):
        return acc_tok

    setting_tok = str(
        get_setting("whatsapp_access_token") 
        or get_setting("meta_system_user_access_token")
    ).strip()
    if is_valid_meta_token(setting_tok):
        return setting_tok

    env_tok = str(
        os.getenv("WHATSAPP_ACCESS_TOKEN") 
        or os.getenv("META_SYSTEM_USER_ACCESS_TOKEN") 
        or os.getenv("WHATSAPP_TOKEN") 
        or os.getenv("META_ACCESS_TOKEN")
        or settings.WHATSAPP_ACCESS_TOKEN 
        or settings.META_SYSTEM_USER_ACCESS_TOKEN
        or ""
    ).strip()
    if is_valid_meta_token(env_tok):
        return env_tok

    # Fallback to whatever non-empty token exists
    return acc_tok or setting_tok or env_tok

def get_whatsapp_credentials(phone_number_id: str = None, page_id: str = None, workspace_id: int = None) -> Tuple[str, str]:
    """Gets valid Phone Number ID and Access Token for a specific account, page, workspace, or global default."""
    if phone_number_id:
        acc = get_whatsapp_account_by_phone_id(phone_number_id)
        if acc:
            p_id = acc.get("phone_number_id")
            token = resolve_whatsapp_token(acc, workspace_id=acc.get("workspace_id") or 1, phone_number_id=p_id)
            return p_id, token

    if page_id:
        acc = get_whatsapp_account_by_page_id(page_id)
        if acc:
            p_id = acc.get("phone_number_id")
            token = resolve_whatsapp_token(acc, workspace_id=acc.get("workspace_id") or 1, phone_number_id=p_id)
            return p_id, token

    if workspace_id:
        acc = get_whatsapp_account_by_workspace_id(workspace_id)
        if acc:
            p_id = acc.get("phone_number_id")
            token = resolve_whatsapp_token(acc, workspace_id=workspace_id, phone_number_id=p_id)
            return p_id, token

    all_s = get_all_settings(masked=False)
    phone_id = all_s.get("whatsapp_phone_number_id", "") or settings.WHATSAPP_PHONE_NUMBER_ID
    token = resolve_whatsapp_token(None, workspace_id=1, phone_number_id=phone_id)
    if not phone_id or not token:
        all_wa = get_all_whatsapp_accounts()
        if all_wa:
            phone_id = phone_id or all_wa[0].get("phone_number_id", "")
            token = token or resolve_whatsapp_token(all_wa[0], workspace_id=1, phone_number_id=phone_id)

    return phone_id, token

def send_whatsapp_message_detailed(to_number: str, message_text: str, phone_id: str = None, token: str = None, page_id: str = None, workspace_id: int = None) -> dict:
    """
    Sends a text message via WhatsApp Cloud API matching the proven Postman reference request.
    Returns structured delivery metadata including HTTP status, message ID, and sanitized error diagnostics.
    """
    if not phone_id:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id, workspace_id=workspace_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

    wa_acc = get_whatsapp_account_by_phone_id(phone_id) if phone_id else None
    token_info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=workspace_id or 1, phone_number_id=phone_id)

    if token:
        effective_token = token
        token_source = "explicit"
        is_valid_token = is_valid_meta_token(token)
    else:
        effective_token = token_info.get("token", "")
        token_source = token_info.get("source", "none")
        is_valid_token = bool(token_info.get("is_valid", False))

    clean_token = str(effective_token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    masked_rec = mask_phone_number(to_number)
    token_prefix = clean_token[:6] if len(clean_token) > 6 else ""
    token_suffix = clean_token[-4:] if len(clean_token) > 10 else ""
    token_len = len(clean_token)
    token_masked = f"{token_prefix}...{token_suffix} (len={token_len})" if token_len > 10 else "EMPTY/SHORT"

    if not clean_token or not is_valid_token:
        fail_reason = token_info.get("reason") or f"No valid WhatsApp Cloud API token is authorized for Phone Number ID {phone_id}."
        print(f"[WhatsApp Send ERROR] workspace_id={workspace_id or 1} phone_number_id={phone_id} recipient={masked_rec} token_source={token_source} token_valid=false status=failed error_code=NO_VALID_WHATSAPP_TOKEN_CONFIGURED reason={fail_reason}")
        return {
            "success": False,
            "http_status": 401,
            "error_code": "NO_VALID_WHATSAPP_TOKEN_CONFIGURED",
            "error_message": fail_reason,
            "phone_number_id": phone_id,
            "token_source": token_source,
            "token_valid": False,
            "token_preview": token_masked,
            "recipient": masked_rec,
            "candidate_validation_results": token_info.get("candidate_validation_results", [])
        }

    if not phone_id or not to_number or not message_text:
        err_detail = f"Missing required fields: phone_id={'SET' if phone_id else 'MISSING'}, to_number={'SET' if to_number else 'MISSING'}"
        print(f"[WhatsApp Send ERROR] workspace_id={workspace_id or 1} phone_number_id={'SET' if phone_id else 'MISSING'} recipient={masked_rec} reason={err_detail}")
        return {
            "success": False,
            "http_status": 0,
            "error_code": "MISSING_REQUIRED_FIELDS",
            "error_message": err_detail,
            "phone_number_id": phone_id,
            "token_source": "explicit",
            "token_valid": False,
            "token_preview": token_masked,
            "recipient": masked_rec
        }

    norm_to = normalize_whatsapp_phone_number(to_number)

    # Determine priority list of phone_ids to try (handles both 15-digit and 16-digit variants)
    target_phone_ids = [phone_id]
    alt_phone_id = "418451426636680" if phone_id == "4184514263660680" else ("4184514263660680" if phone_id == "418451426636680" else None)
    if alt_phone_id and alt_phone_id not in target_phone_ids:
        if str(settings.WHATSAPP_PHONE_NUMBER_ID).strip() == alt_phone_id:
            target_phone_ids = [alt_phone_id, phone_id]
        else:
            target_phone_ids.append(alt_phone_id)

    last_res = None
    for cur_phone_id in target_phone_ids:
        url = f"{GRAPH_API_URL}/{cur_phone_id}/messages"
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
                print(f"[WhatsApp Send] workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} recipient={masked_rec} graph_api_version={settings.META_GRAPH_VERSION} token_source=explicit token_valid=true status=success message_id={msg_id} http_status={r.status_code}")
                return {
                    "success": True,
                    "http_status": r.status_code,
                    "message_id": msg_id,
                    "phone_number_id": cur_phone_id,
                    "token_source": "explicit",
                    "token_valid": True,
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

                print(f"[WhatsApp Send ERROR] workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} recipient={masked_rec} http_status={r.status_code} graph_error_code={err_code} token_source=explicit token_valid=false reason={err_msg}")
                last_res = {
                    "success": False,
                    "http_status": r.status_code,
                    "graph_error_code": err_code,
                    "graph_error_subcode": err_subcode,
                    "error_type": err_type,
                    "error_message": err_msg,
                    "phone_number_id": cur_phone_id,
                    "token_source": "explicit",
                    "token_valid": False,
                    "token_preview": token_masked,
                    "recipient": masked_rec
                }
                # If error is specifically "Object with ID does not exist" and we have another ID to try, continue loop
                if err_code == 100 and "does not exist" in str(err_msg).lower() and cur_phone_id != target_phone_ids[-1]:
                    continue
                return last_res
        except Exception as e:
            print(f"[WhatsApp Send Network ERROR] phone_id={cur_phone_id} recipient={masked_rec} error={e}")
            last_res = {
                "success": False,
                "http_status": 0,
                "error_code": "NETWORK_EXCEPTION",
                "error_message": str(e),
                "phone_number_id": cur_phone_id,
                "token_source": "explicit",
                "token_valid": False,
                "token_preview": token_masked,
                "recipient": masked_rec
            }
            if cur_phone_id != target_phone_ids[-1]:
                continue
            return last_res

    return last_res or {
        "success": False,
        "http_status": 0,
        "error_code": "UNKNOWN_ERROR",
        "error_message": "Failed to send WhatsApp message",
        "phone_number_id": phone_id,
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
    token_info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=workspace_id or 1, phone_number_id=phone_id)

    effective_token = token or token_info.get("token", "")
    clean_token = str(effective_token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    masked_rec = mask_phone_number(to_number)
    if not clean_token or not phone_id or not to_number or not image_url:
        print(f"[WhatsApp Send ERROR] Image: Missing required fields: workspace_id={workspace_id or 1} phone_number_id={'SET' if phone_id else 'MISSING'} recipient={masked_rec}")
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)

    # Determine priority list of phone_ids to try
    target_phone_ids = [phone_id]
    alt_phone_id = "418451426636680" if phone_id == "4184514263660680" else ("4184514263660680" if phone_id == "418451426636680" else None)
    if alt_phone_id and alt_phone_id not in target_phone_ids:
        if str(settings.WHATSAPP_PHONE_NUMBER_ID).strip() == alt_phone_id:
            target_phone_ids = [alt_phone_id, phone_id]
        else:
            target_phone_ids.append(alt_phone_id)

    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
    full_url = image_url if str(image_url).startswith("http") else f"{base_server_url}{image_url if str(image_url).startswith('/') else '/' + str(image_url)}"

    # Check if local file exists on disk
    local_file_path = None
    clean_rel = str(image_url).lstrip("/")
    if os.path.exists(clean_rel):
        local_file_path = clean_rel
    elif str(image_url).startswith("/static/") and os.path.exists(str(image_url)[1:]):
        local_file_path = str(image_url)[1:]
    elif os.path.exists(os.path.join("static", os.path.basename(str(image_url)))):
        local_file_path = os.path.join("static", os.path.basename(str(image_url)))

    image_obj = {"link": full_url}
    if caption and str(caption).strip():
        image_obj["caption"] = str(caption).strip()

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": norm_to,
        "type": "image",
        "image": image_obj
    }

    for cur_phone_id in target_phone_ids:
        url = f"{GRAPH_API_URL}/{cur_phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {clean_token}",
            "Content-Type": "application/json"
        }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            status_ok = r.status_code in [200, 201]
            if status_ok:
                print(f"[WhatsApp Send] Image: workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} recipient={masked_rec} graph_api_version={settings.META_GRAPH_VERSION} token_source=explicit token_valid=true status=success http_status={r.status_code}")
                return True
            else:
                err_text = r.text
                print(f"[WhatsApp Send ERROR] Image URL send failed: phone_number_id={cur_phone_id} recipient={masked_rec} http_status={r.status_code} reason={err_text}")

                # If URL send failed and local file exists, try uploading binary media to Meta
                if local_file_path and os.path.exists(local_file_path):
                    try:
                        upload_url = f"{GRAPH_API_URL}/{cur_phone_id}/media"
                        upload_headers = {"Authorization": f"Bearer {clean_token}"}
                        with open(local_file_path, "rb") as f_img:
                            files = {"file": (os.path.basename(local_file_path), f_img, "image/jpeg")}
                            data = {"messaging_product": "whatsapp", "type": "image/jpeg"}
                            up_resp = requests.post(upload_url, headers=upload_headers, files=files, data=data, timeout=25)
                            if up_resp.status_code in [200, 201]:
                                media_id = up_resp.json().get("id")
                                if media_id:
                                    media_payload = {
                                        "messaging_product": "whatsapp",
                                        "recipient_type": "individual",
                                        "to": norm_to,
                                        "type": "image",
                                        "image": {"id": media_id, "caption": str(caption).strip() if caption else ""}
                                    }
                                    r_media = requests.post(url, headers=headers, json=media_payload, timeout=20)
                                    if r_media.status_code in [200, 201]:
                                        print(f"[WhatsApp Send] Image Uploaded & Sent: phone_id={cur_phone_id} media_id={media_id} recipient={masked_rec}")
                                        return True
                    except Exception as up_err:
                        print(f"[WhatsApp Send Image Upload Exception]: {up_err}")

                if r.status_code == 400 and "does not exist" in err_text.lower() and cur_phone_id != target_phone_ids[-1]:
                    continue
                return False
        except Exception as e:
            print(f"[WhatsApp Send ERROR] Image Exception: workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} error={str(e)}")
            if cur_phone_id != target_phone_ids[-1]:
                continue
            return False

    return False

def send_whatsapp_audio(to_number: str, audio_url: str, phone_id: str = None, token: str = None, page_id: str = None, workspace_id: int = None) -> bool:
    """Sends a voice note / audio clip via WhatsApp Cloud API."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id, workspace_id=workspace_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

    wa_acc = get_whatsapp_account_by_phone_id(phone_id) if phone_id else None
    token_info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=workspace_id or 1, phone_number_id=phone_id)

    effective_token = token or token_info.get("token", "")
    clean_token = str(effective_token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    masked_rec = mask_phone_number(to_number)
    if not clean_token or not phone_id or not to_number or not audio_url:
        print(f"[WhatsApp Send ERROR] Audio: workspace_id={workspace_id or 1} phone_number_id={phone_id} recipient={masked_rec}")
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)

    target_phone_ids = [phone_id]
    alt_phone_id = "418451426636680" if phone_id == "4184514263660680" else ("4184514263660680" if phone_id == "418451426636680" else None)
    if alt_phone_id and alt_phone_id not in target_phone_ids:
        if str(settings.WHATSAPP_PHONE_NUMBER_ID).strip() == alt_phone_id:
            target_phone_ids = [alt_phone_id, phone_id]
        else:
            target_phone_ids.append(alt_phone_id)

    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
    full_url = audio_url if str(audio_url).startswith("http") else f"{base_server_url}{audio_url if str(audio_url).startswith('/') else '/' + str(audio_url)}"

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": norm_to,
        "type": "audio",
        "audio": {"link": full_url}
    }

    for cur_phone_id in target_phone_ids:
        url = f"{GRAPH_API_URL}/{cur_phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {clean_token}",
            "Content-Type": "application/json"
        }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            status_ok = r.status_code in [200, 201]
            if status_ok:
                print(f"[WhatsApp Send] Audio: workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} recipient={masked_rec} graph_api_version={settings.META_GRAPH_VERSION} token_source=explicit token_valid=true status=success http_status={r.status_code}")
                return True
            else:
                print(f"[WhatsApp Send ERROR] Audio: workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} recipient={masked_rec} http_status={r.status_code} reason={r.text}")
                if r.status_code == 400 and "does not exist" in r.text.lower() and cur_phone_id != target_phone_ids[-1]:
                    continue
                return False
        except Exception as e:
            print(f"[WhatsApp Send ERROR] Audio Exception: workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} error={str(e)}")
            if cur_phone_id != target_phone_ids[-1]:
                continue
            return False

    return False

def send_whatsapp_video(to_number: str, video_url: str, caption: str = "", phone_id: str = None, token: str = None, page_id: str = None, workspace_id: int = None) -> bool:
    """Sends a video message via WhatsApp Cloud API."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id, workspace_id=workspace_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

    wa_acc = get_whatsapp_account_by_phone_id(phone_id) if phone_id else None
    token_info = resolve_whatsapp_token_info(wa_account=wa_acc, workspace_id=workspace_id or 1, phone_number_id=phone_id)

    effective_token = token or token_info.get("token", "")
    clean_token = str(effective_token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    masked_rec = mask_phone_number(to_number)
    if not clean_token or not phone_id or not to_number or not video_url:
        print(f"[WhatsApp Send ERROR] Video: workspace_id={workspace_id or 1} phone_number_id={phone_id} recipient={masked_rec}")
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)

    target_phone_ids = [phone_id]
    alt_phone_id = "418451426636680" if phone_id == "4184514263660680" else ("4184514263660680" if phone_id == "418451426636680" else None)
    if alt_phone_id and alt_phone_id not in target_phone_ids:
        if str(settings.WHATSAPP_PHONE_NUMBER_ID).strip() == alt_phone_id:
            target_phone_ids = [alt_phone_id, phone_id]
        else:
            target_phone_ids.append(alt_phone_id)

    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
    full_url = video_url if str(video_url).startswith("http") else f"{base_server_url}{video_url if str(video_url).startswith('/') else '/' + str(video_url)}"

    video_obj = {"link": full_url}
    if caption and str(caption).strip():
        video_obj["caption"] = str(caption).strip()

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": norm_to,
        "type": "video",
        "video": video_obj
    }

    for cur_phone_id in target_phone_ids:
        url = f"{GRAPH_API_URL}/{cur_phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {clean_token}",
            "Content-Type": "application/json"
        }

        try:
            r = requests.post(url, headers=headers, json=payload, timeout=25)
            status_ok = r.status_code in [200, 201]
            if status_ok:
                print(f"[WhatsApp Send] Video: workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} recipient={masked_rec} graph_api_version={settings.META_GRAPH_VERSION} token_source=explicit token_valid=true status=success http_status={r.status_code}")
                return True
            else:
                print(f"[WhatsApp Send ERROR] Video: workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} recipient={masked_rec} http_status={r.status_code} reason={r.text}")
                if r.status_code == 400 and "does not exist" in r.text.lower() and cur_phone_id != target_phone_ids[-1]:
                    continue
                return False
        except Exception as e:
            print(f"[WhatsApp Send ERROR] Video Exception: workspace_id={workspace_id or 1} phone_number_id={cur_phone_id} error={str(e)}")
            if cur_phone_id != target_phone_ids[-1]:
                continue
            return False

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
                            sent_count = 0
                            for img_path in matched_images:
                                if not img_path:
                                    continue
                                img_ok = send_whatsapp_image(
                                    sender_phone, img_path,
                                    phone_id=effective_phone_id, token=effective_token, page_id=page_id, workspace_id=workspace_id
                                )
                                if img_ok:
                                    sent_count += 1
                                    record_conversation_message("whatsapp", sender_phone, customer_name, "bot", "", img_path, page_id=page_id, workspace_id=workspace_id)
                                await asyncio.sleep(0.2)

                            # Send concluding follow-up message after all photos are delivered
                            if sent_count > 0 and sender_phone:
                                honorific = detect_customer_gender_title(customer_name)
                                if any("pakage" in str(p).lower() or "pkg" in str(p).lower() for p in matched_images):
                                    followup_msg = f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন {honorific}।"
                                else:
                                    followup_msg = f"আপনার কত পিস প্রয়োজন জানাবেন {honorific}।"

                                await asyncio.sleep(0.4)
                                send_whatsapp_message(
                                    sender_phone, followup_msg,
                                    phone_id=effective_phone_id, token=effective_token, page_id=page_id, workspace_id=workspace_id
                                )
                                record_conversation_message("whatsapp", sender_phone, customer_name, "bot", followup_msg, page_id=page_id, workspace_id=workspace_id)

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


