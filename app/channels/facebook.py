import os
import sys
import json
import time
import requests
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
import hashlib
from app.config import settings
from app.database import (
    get_db_connection, get_setting, is_conversation_ai_active,
    get_connected_page, get_all_connected_pages, get_page_ai_config,
    ensure_facebook_page_consistency,
    is_webhook_event_processed, mark_webhook_event_processed,
    claim_media_delivery, update_media_delivery_status
)
from app.channels.omnichat import record_conversation_message, get_conversation_history
from app.ai_agent.gemini_brain import process_customer_message, detect_customer_gender_title

GRAPH_API_URL = "https://graph.facebook.com/v19.0"

def get_fb_token(page_id: str = None) -> str:
    """Retrieves the access token for a specific Page ID, or falls back to global settings / primary connected page."""
    if page_id:
        p = get_connected_page(page_id)
        if p and p.get("page_access_token"):
            tok = str(p["page_access_token"]).strip()
            if tok and len(tok) > 10 and not tok.startswith("EAA_TEST"):
                return tok
    
    token = get_setting("fb_page_access_token") or os.getenv("FB_PAGE_ACCESS_TOKEN") or settings.FB_PAGE_ACCESS_TOKEN
    if not token or len(str(token)) < 10 or str(token).startswith("EAA_TEST"):
        all_pages = get_all_connected_pages()
        for p in all_pages:
            tok = str(p.get("page_access_token", "")).strip()
            if tok and len(tok) > 10 and not tok.startswith("EAA_TEST"):
                return tok
    return str(token or "").strip()

def get_fb_user_profile(sender_id: str, page_token: str = None, page_id: str = None) -> str:
    """Fetches the user name from Facebook Graph API."""
    token = page_token or get_fb_token(page_id)
    if not token or not sender_id:
        return "Facebook User"
    try:
        url = f"{GRAPH_API_URL}/{sender_id}"
        r = requests.get(url, params={"fields": "first_name,last_name,name", "access_token": token}, timeout=5)
        if r.status_code == 200:
            data = r.json()
            return data.get("name") or f"{data.get('first_name', '')} {data.get('last_name', '')}".strip() or "Facebook User"
    except Exception:
        pass
    return "Facebook User"

def subscribe_facebook_page_webhooks(page_id: str = None, page_token: str = None) -> Dict[str, Any]:
    """
    Subscribes the Facebook Page to this app's webhooks using POST /{page_id}/subscribed_apps.
    Subscribed fields include: feed, messages, messaging_postbacks, message_deliveries, message_reads, conversations.
    This is MANDATORY for Meta to deliver feed (comment) and messaging webhooks to our server.
    """
    pid = page_id or get_setting("fb_page_id") or os.getenv("FB_PAGE_ID") or settings.FB_PAGE_ID or "105116472071659"
    token = page_token or get_fb_token(pid)
    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or clean_token.startswith("EAA_TEST"):
        return {
            "success": False,
            "error": "missing_or_dummy_token",
            "message": "Valid Facebook Page Access Token is required to subscribe webhooks."
        }

    graph_version = getattr(settings, "META_GRAPH_VERSION", "v23.0") or "v23.0"
    url = f"https://graph.facebook.com/{graph_version}/{pid}/subscribed_apps"
    params = {
        "subscribed_fields": "feed,messages,messaging_postbacks,message_deliveries,message_reads,conversations",
        "access_token": clean_token
    }

    try:
        r = requests.post(url, params=params, timeout=12)
        resp_data = {}
        try:
            resp_data = r.json()
        except Exception:
            resp_data = {"raw": r.text}

        if r.status_code == 200 and resp_data.get("success") is True:
            print(f"[Facebook Webhook Subscription SUCCESS]: Page {pid} subscribed to fields (feed, messages).")
            return {
                "success": True,
                "page_id": pid,
                "subscribed_fields": ["feed", "messages", "messaging_postbacks", "conversations"],
                "message": "Facebook Page successfully subscribed to Meta Webhook (feed, messages)!"
            }
        else:
            print(f"[Facebook Webhook Subscription ERROR {r.status_code}]: {r.text}")
            return {
                "success": False,
                "status_code": r.status_code,
                "error": resp_data.get("error", {}).get("message", r.text),
                "message": f"Meta returned error {r.status_code}: {resp_data.get('error', {}).get('message', r.text)}"
            }
    except Exception as e:
        print(f"[Facebook Webhook Subscription EXCEPTION]: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": f"Network exception while connecting to Meta Graph API: {e}"
        }

def get_fb_page_details(page_id: str = None, page_token: str = None) -> Dict[str, Any]:
    """Fetches real-time status and metadata for the Facebook Page from Graph API."""
    pid = page_id or get_setting("fb_page_id") or os.getenv("FB_PAGE_ID") or settings.FB_PAGE_ID or "105116472071659"
    token = page_token or get_fb_token(pid)
    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or clean_token.startswith("EAA_TEST"):
        return {
            "connected": False,
            "page_id": pid,
            "error": "No valid Page Access Token configured."
        }

    graph_version = getattr(settings, "META_GRAPH_VERSION", "v23.0") or "v23.0"
    url = f"https://graph.facebook.com/{graph_version}/{pid}"
    try:
        r = requests.get(url, params={"fields": "id,name,link,category,verification_status", "access_token": clean_token}, timeout=8)
        if r.status_code == 200:
            data = r.json()
            return {
                "connected": True,
                "page_id": data.get("id", pid),
                "page_name": data.get("name", "RS Graphics"),
                "link": data.get("link", ""),
                "category": data.get("category", ""),
                "token_valid": True
            }
        else:
            return {
                "connected": False,
                "page_id": pid,
                "error": r.json().get("error", {}).get("message", r.text),
                "token_valid": False
            }
    except Exception as e:
        return {
            "connected": False,
            "page_id": pid,
            "error": str(e),
            "token_valid": False
        }

def send_fb_text_message(recipient_id: str, text: str, page_token: str = None, page_id: str = None) -> bool:
    """Sends a text message to a Facebook Messenger user using specific Page credentials."""
    token = page_token or get_fb_token(page_id)
    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token:
        print(f"[Facebook Send Error]: Page Access Token missing for Page ID {page_id or 'default'}!")
        return False
    if not recipient_id:
        print("[Facebook Send Error]: Missing recipient_id!")
        return False

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": clean_token}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE"
    }
    try:
        r = requests.post(url, params=params, json=payload, timeout=10)
        status_ok = r.status_code == 200
        print(f"[Facebook Send Result]: HTTP {r.status_code}, Body: {r.text}")
        return status_ok
    except Exception as e:
        print(f"[Facebook Send Exception]: {e}")
        return False

def compute_media_fingerprint(media_url: str) -> Tuple[str, Optional[Path]]:
    """Computes a stable SHA-256 fingerprint for a media file or URL."""
    if not media_url:
        return "empty", None
    filename = Path(media_url).name
    candidate_paths = [
        settings.STATIC_DIR / media_url.replace("/static/", "").lstrip("/"),
        settings.BASE_DIR / media_url.lstrip("/"),
        settings.UPLOADS_DIR / filename,
        settings.BASE_DIR / "static" / "uploads" / filename
    ]
    for p in candidate_paths:
        if p.exists() and p.is_file():
            try:
                with open(p, "rb") as f_bin:
                    content_chunk = f_bin.read(131072)
                    fp = hashlib.sha256(content_chunk).hexdigest()[:16]
                    return fp, p
            except Exception:
                pass
    fp = hashlib.sha256(str(media_url).strip().encode("utf-8")).hexdigest()[:16]
    return fp, None

def send_fb_media_message(
    recipient_id: str,
    media_type: str,
    media_url: str,
    page_token: str = None,
    page_id: str = None,
    workspace_id: int = 1,
    batch_id: str = "",
    conversation_id: int = None
) -> bool:
    """
    Sends an image, video, or audio attachment to a Facebook Messenger user with strict idempotency.
    Guarantees effectively-once delivery per logical media item.
    """
    token = page_token or get_fb_token(page_id)
    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or not recipient_id or not media_url:
        return False

    eff_page_id = str(page_id or "default").strip()
    filename = Path(media_url).name
    fingerprint, local_file_path = compute_media_fingerprint(media_url)
    delivery_key = f"fb_media:{workspace_id}:{eff_page_id}:{recipient_id}:{fingerprint}"

    masked_rec = f"{recipient_id[:6]}****{recipient_id[-4:]}" if len(recipient_id) > 10 else "***"
    masked_key = f"fb_media:{workspace_id}:{eff_page_id}:{masked_rec}:{fingerprint}"

    # Atomic claim check
    can_send, claim_record = claim_media_delivery(
        delivery_key=delivery_key,
        workspace_id=workspace_id,
        page_id=eff_page_id,
        recipient_id=recipient_id,
        media_type=media_type,
        media_url=media_url,
        media_filename=filename,
        media_fingerprint=fingerprint,
        batch_id=batch_id,
        conversation_id=conversation_id
    )

    if not can_send:
        existing_status = claim_record.get("status", "UNKNOWN")
        if existing_status == "SENT":
            print(f"[Facebook Media Delivery SKIPPED] workspace_id={workspace_id} recipient={masked_rec} media={filename} reason=already_sent delivery_key={masked_key}")
            return True
        elif existing_status == "UNKNOWN":
            print(f"[Facebook Media Delivery UNKNOWN] workspace_id={workspace_id} recipient={masked_rec} media={filename} reason=network_timeout retry_blocked=true delivery_key={masked_key}")
            return False
        else:
            print(f"[Facebook Media Delivery SKIPPED] workspace_id={workspace_id} recipient={masked_rec} media={filename} reason=concurrent_worker_active delivery_key={masked_key}")
            return False

    attempt_num = claim_record.get("attempt_count", 1)
    print(f"[Facebook Media Delivery START] workspace_id={workspace_id} page_id={eff_page_id} recipient={masked_rec} media={filename} fingerprint={fingerprint} delivery_key={masked_key} status=SENDING attempt={attempt_num}")

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": clean_token}

    # 1. If local file exists on disk, use direct binary upload (fastest, eliminates Meta callback timeout loop)
    if local_file_path and local_file_path.exists() and local_file_path.is_file():
        try:
            data = {
                "recipient": json.dumps({"id": recipient_id}),
                "message": json.dumps({
                    "attachment": {
                        "type": media_type,
                        "payload": {"is_reusable": True}
                    }
                })
            }
            with open(local_file_path, "rb") as f_bin:
                mime = "image/jpeg" if media_type == "image" else ("video/mp4" if media_type == "video" else "audio/mp4")
                files = {"filedata": (local_file_path.name, f_bin, mime)}
                r = requests.post(url, params=params, data=data, files=files, timeout=25)
                
            if r.status_code == 200:
                try:
                    res_json = r.json()
                    msg_id = res_json.get("message_id", "")
                    att_id = res_json.get("attachment_id", "")
                except Exception:
                    msg_id, att_id = "", ""
                update_media_delivery_status(delivery_key, "SENT", meta_message_id=msg_id, attachment_id=att_id)
                print(f"[Facebook Media Delivery SUCCESS] workspace_id={workspace_id} recipient={masked_rec} media={filename} http_status=200 message_id={msg_id} attachment_id={att_id}")
                return True
            else:
                err_text = r.text
                update_media_delivery_status(delivery_key, "FAILED", last_error=err_text)
                print(f"[Facebook Media Delivery FAILED] workspace_id={workspace_id} recipient={masked_rec} media={filename} http_status={r.status_code} error={err_text}")
                return False
        except requests.exceptions.Timeout as t_err:
            update_media_delivery_status(delivery_key, "UNKNOWN", last_error="Binary upload timeout (25s)")
            print(f"[Facebook Media Delivery UNKNOWN] workspace_id={workspace_id} recipient={masked_rec} media={filename} reason=network_timeout retry_blocked=true")
            return False
        except Exception as up_err:
            update_media_delivery_status(delivery_key, "FAILED", last_error=str(up_err))
            print(f"[Facebook Media Delivery FAILED] workspace_id={workspace_id} recipient={masked_rec} media={filename} error={up_err}")
            return False

    # 2. Remote URL attachment payload
    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
    full_url = media_url if media_url.startswith("http") else f"{base_server_url}{media_url}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": media_type,
                "payload": {
                    "url": full_url,
                    "is_reusable": True
                }
            }
        }
    }
    try:
        r = requests.post(url, params=params, json=payload, timeout=15)
        if r.status_code == 200:
            try:
                res_json = r.json()
                msg_id = res_json.get("message_id", "")
                att_id = res_json.get("attachment_id", "")
            except Exception:
                msg_id, att_id = "", ""
            update_media_delivery_status(delivery_key, "SENT", meta_message_id=msg_id, attachment_id=att_id)
            print(f"[Facebook Media Delivery SUCCESS] workspace_id={workspace_id} recipient={masked_rec} media={filename} http_status=200 message_id={msg_id} attachment_id={att_id}")
            return True
        else:
            err_text = r.text
            update_media_delivery_status(delivery_key, "FAILED", last_error=err_text)
            print(f"[Facebook Media Delivery FAILED] workspace_id={workspace_id} recipient={masked_rec} media={filename} http_status={r.status_code} error={err_text}")
            return False
    except requests.exceptions.Timeout as t_err:
        # Crucial fix: Do NOT blindly retry upon timeout (Meta might have processed the request)
        update_media_delivery_status(delivery_key, "UNKNOWN", last_error="URL send read timeout (15s)")
        print(f"[Facebook Media Delivery UNKNOWN] workspace_id={workspace_id} recipient={masked_rec} media={filename} reason=network_timeout retry_blocked=true")
        return False
    except Exception as e:
        update_media_delivery_status(delivery_key, "FAILED", last_error=str(e))
        print(f"[Facebook Media Delivery FAILED] workspace_id={workspace_id} recipient={masked_rec} media={filename} error={e}")
        return False

def send_fb_audio_message(recipient_id: str, audio_url: str, page_token: str = None, page_id: str = None, workspace_id: int = 1, batch_id: str = "") -> bool:
    """Sends an audio / voice message via Facebook Messenger with idempotency."""
    return send_fb_media_message(recipient_id, "audio", audio_url, page_token=page_token, page_id=page_id, workspace_id=workspace_id, batch_id=batch_id)

def send_fb_video_message(recipient_id: str, video_url: str, page_token: str = None, page_id: str = None, workspace_id: int = 1, batch_id: str = "") -> bool:
    """Sends a video attachment via Facebook Messenger with idempotency."""
    return send_fb_media_message(recipient_id, "video", video_url, page_token=page_token, page_id=page_id, workspace_id=workspace_id, batch_id=batch_id)

def reply_to_fb_comment(comment_id: str, message: str, page_token: str = None, page_id: str = None) -> bool:
    """Replies publicly to a Facebook post comment."""
    token = page_token or get_fb_token(page_id)
    if not token or str(token).startswith("EAA_TEST"):
        token = get_setting("fb_page_access_token") or os.getenv("FB_PAGE_ACCESS_TOKEN") or settings.FB_PAGE_ACCESS_TOKEN or get_fb_token(page_id)

    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or not comment_id:
        print(f"[Facebook Comment Reply Error]: Missing token or comment_id (comment_id={comment_id})")
        return False

    graph_version = getattr(settings, "META_GRAPH_VERSION", "v23.0") or "v23.0"
    url = f"https://graph.facebook.com/{graph_version}/{comment_id}/comments"
    params = {"access_token": clean_token}
    payload = {"message": message}
    headers = {"Content-Type": "application/json; charset=utf-8"}
    try:
        r = requests.post(url, params=params, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[Facebook Comment Reply SUCCESS]: Replied to comment {comment_id}")
            return True
        # Fallback to form-data (standard Meta Graph API)
        r2 = requests.post(url, params=params, data=payload, timeout=10)
        if r2.status_code == 200:
            print(f"[Facebook Comment Reply SUCCESS (form-data)]: Replied to comment {comment_id}")
            return True
        else:
            print(f"[Facebook Comment Reply Error {r.status_code}/{r2.status_code}]: {r.text} | {r2.text}")
            return False
    except Exception as e:
        print(f"[Facebook Comment Reply Exception]: {e}")
        return False

def send_fb_private_reply_to_comment(comment_id: str, message: str, page_token: str = None, page_id: str = None) -> bool:
    """Sends a private message to the user who commented on a post."""
    token = page_token or get_fb_token(page_id)
    if not token or str(token).startswith("EAA_TEST"):
        token = get_setting("fb_page_access_token") or os.getenv("FB_PAGE_ACCESS_TOKEN") or settings.FB_PAGE_ACCESS_TOKEN or get_fb_token(page_id)

    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or not comment_id:
        print(f"[Facebook Private Reply Error]: Missing token or comment_id (comment_id={comment_id})")
        return False

    graph_version = getattr(settings, "META_GRAPH_VERSION", "v23.0") or "v23.0"
    url = f"https://graph.facebook.com/{graph_version}/me/messages"
    params = {"access_token": clean_token}
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": message}
    }
    headers = {"Content-Type": "application/json; charset=utf-8"}
    try:
        r = requests.post(url, params=params, json=payload, headers=headers, timeout=10)
        if r.status_code == 200:
            print(f"[Facebook Private Reply SUCCESS]: Sent private reply to comment {comment_id}")
            return True
        else:
            print(f"[Facebook Private Reply Error {r.status_code}]: {r.text}")
            return False
    except Exception as e:
        print(f"[Facebook Private Reply Exception]: {e}")
        return False

async def handle_facebook_webhook_event(data: dict):
    """Processes incoming Facebook Messenger messages and post comments across multiple connected Pages with strict workspace isolation."""
    try:
        entries = data.get("entry", [])
        for entry in entries:
            entry_id = str(entry.get("id", "")).strip()

            # 1. Handle Messenger Messages
            if "messaging" in entry:
                for event in entry["messaging"]:
                    sender_id = str(event.get("sender", {}).get("id", "")).strip()
                    recipient_id = str(event.get("recipient", {}).get("id", "")).strip()
                    
                    if not sender_id:
                        continue

                    msg = event.get("message", {})
                    if not msg:
                        continue

                    is_echo = bool(msg.get("is_echo"))

                    # Look up the specific connected page for this message (check recipient, entry_id, or sender)
                    target_page_id = recipient_id or entry_id
                    page_conn = get_connected_page(target_page_id)
                    if not page_conn:
                        page_conn = get_connected_page(entry_id)
                    if not page_conn:
                        page_conn = get_connected_page(sender_id)
                        if page_conn:
                            is_echo = True
                            target_page_id = sender_id

                    if not page_conn and (target_page_id in ["105116472071659", "rs_graphics_page_1"] or sender_id in ["105116472071659", "rs_graphics_page_1"] or entry_id in ["105116472071659", "rs_graphics_page_1"]):
                        page_conn = ensure_facebook_page_consistency()

                    if not page_conn:
                        print(f"[Facebook Routing Error]: Unknown recipient_id {target_page_id}. No matching connected_page found. Event dropped without fallback.")
                        continue

                    workspace_id = page_conn.get("workspace_id", 1)
                    page_id = page_conn.get("page_id", target_page_id)
                    page_token = page_conn.get("page_access_token")
                    page_name = page_conn.get("page_name", "Facebook Page")

                    # Detect if message was sent by the Page Owner / Human Admin
                    if is_echo or (sender_id == page_id) or (get_connected_page(sender_id) is not None):
                        actual_cust_id = recipient_id if (sender_id == page_id or get_connected_page(sender_id) is not None) else sender_id
                        echo_text = msg.get("text", "")
                        from app.database import add_muted_number
                        record_conversation_message("facebook", actual_cust_id, "Customer", "admin", echo_text, page_id=page_id, workspace_id=workspace_id)
                        add_muted_number(actual_cust_id)
                        print(f"[Facebook Human Takeover AUTO-ACTIVATED]: Page Owner/Admin replied to customer {actual_cust_id}: '{echo_text[:30]}'. AI paused for this conversation.")
                        continue

                    print(f"[Facebook Routing] recipient_id={target_page_id} matched_page_id={page_id} workspace_id={workspace_id} page_name={page_name}")

                    msg_id = msg.get("mid")
                    if msg_id:
                        if is_webhook_event_processed("facebook", msg_id):
                            print(f"[Facebook Webhook DUPLICATE] event_id={msg_id} action=ignored_already_processed")
                            continue
                        mark_webhook_event_processed("facebook", msg_id, workspace_id=workspace_id, page_id_or_phone_id=page_id)

                    msg_text = msg.get("text", "")
                    attachments = msg.get("attachments", [])
                    
                    image_bytes = None
                    image_mime = "image/jpeg"
                    audio_bytes = None
                    audio_mime = "audio/mp3"

                    # Process attachments (Voice Note or Photo)
                    for att in attachments:
                        att_type = att.get("type")
                        att_url = att.get("payload", {}).get("url")
                        if not att_url:
                            continue
                        
                        try:
                            if att_type == "image":
                                r = requests.get(att_url, timeout=10)
                                if r.status_code == 200:
                                    image_bytes = r.content
                                    image_mime = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                            elif att_type in ["audio", "voice"]:
                                r = requests.get(att_url, timeout=10)
                                if r.status_code == 200:
                                    audio_bytes = r.content
                                    audio_mime = r.headers.get("content-type", "audio/mp4").split(";")[0].strip()
                        except Exception as e:
                            print(f"[Facebook Media DL Error]: {e}")

                    # Fetch customer name and record customer message scoped to this Workspace & Page
                    customer_name = get_fb_user_profile(sender_id, page_token=page_token, page_id=page_id)
                    record_conversation_message("facebook", sender_id, customer_name, "user", msg_text, page_id=page_id, workspace_id=workspace_id)

                    # Check for Admin / Customer AI Control Commands
                    clean_cmd = msg_text.strip().lower()
                    if clean_cmd in ["#ai", "[ai]", "start ai", "এআই চালু", "এআই অন"]:
                        from app.database import remove_muted_number
                        remove_muted_number(sender_id)
                        send_fb_text_message(sender_id, "জি স্যার, আপনার জন্য এআই অটোমেশন পুনরায় চালু করা হয়েছে।", page_token=page_token, page_id=page_id)
                        continue
                    elif clean_cmd in ["#pause", "[pause]", "[stop]", "এআই বন্ধ", "এআই অফ", "আমি কথা বলছি"]:
                        from app.database import add_muted_number
                        add_muted_number(sender_id)
                        send_fb_text_message(sender_id, "জি স্যার, এআই অটোমেশন সাময়িকভাবে বন্ধ (Paused) করা হয়েছে। আপনি সরাসরি কথা বলতে পারবেন।", page_token=page_token, page_id=page_id)
                        continue

                    # Check if AI Master Switch or Per-Customer Takeover is active
                    if not is_conversation_ai_active(sender_id=sender_id):
                        print(f"[Facebook Messenger]: AI is PAUSED for customer {sender_id} on Page {page_name} (Human Takeover). AI will stay silent.")
                        continue

                    # Fetch conversation history scoped strictly to this Workspace
                    history = get_conversation_history("facebook", sender_id, limit=8, page_id=page_id, workspace_id=workspace_id)

                    # Process with Gemini AI Brain with Workspace-isolated context
                    ai_result = await process_customer_message(
                        message_text=msg_text,
                        image_bytes=image_bytes,
                        image_mime=image_mime,
                        audio_bytes=audio_bytes,
                        audio_mime=audio_mime,
                        conversation_history=history,
                        channel="facebook",
                        sender_id=sender_id,
                        customer_name=customer_name,
                        generate_voice_reply=bool(audio_bytes),
                        workspace_id=workspace_id,
                        page_id=page_id
                    )

                    reply_text = ai_result.get("reply_text", "")
                    if reply_text:
                        print(f"[Facebook Messenger Replying on Workspace {workspace_id} ('{page_name}')]: '{reply_text[:60]}...' to {sender_id}")
                        send_ok = send_fb_text_message(sender_id, reply_text, page_token=page_token, page_id=page_id)
                        if send_ok:
                            record_conversation_message("facebook", sender_id, customer_name, "bot", reply_text, page_id=page_id, workspace_id=workspace_id)

                    # Send all matched product images as rich media attachments with media-level idempotency
                    matched_images = ai_result.get("matched_images", [])
                    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
                    batch_id = f"fb_batch_{sender_id}_{msg_id or int(time.time()*1000)}"
                    fb_img_sent_count = 0

                    for img_path in matched_images:
                        if not img_path:
                            continue
                        full_img_url = img_path if img_path.startswith("http") else f"{base_server_url}{img_path}"
                        img_sent = send_fb_media_message(
                            recipient_id=sender_id,
                            media_type="image",
                            media_url=img_path,
                            page_token=page_token,
                            page_id=page_id,
                            workspace_id=workspace_id,
                            batch_id=batch_id
                        )
                        if img_sent:
                            fb_img_sent_count += 1
                            record_conversation_message("facebook", sender_id, customer_name, "bot", "", full_img_url, page_id=page_id, workspace_id=workspace_id)
                        await asyncio.sleep(0.2)

                    # Send concluding follow-up message after all photos are delivered
                    if fb_img_sent_count > 0 and sender_id:
                        honorific = detect_customer_gender_title(customer_name)
                        if any("pakage" in str(p).lower() or "pkg" in str(p).lower() for p in matched_images):
                            fb_followup = f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন {honorific}।"
                        else:
                            fb_followup = f"আপনার কত পিস প্রয়োজন জানাবেন {honorific}।"

                        await asyncio.sleep(0.4)
                        send_fb_message(
                            sender_id, fb_followup,
                            page_token=page_token, page_id=page_id, workspace_id=workspace_id
                        )
                        record_conversation_message("facebook", sender_id, customer_name, "bot", fb_followup, page_id=page_id, workspace_id=workspace_id)

                    # Send video demo if requested
                    matched_video = ai_result.get("video_url", "")
                    if matched_video:
                        vid_sent = send_fb_video_message(
                            recipient_id=sender_id,
                            video_url=matched_video,
                            page_token=page_token,
                            page_id=page_id,
                            workspace_id=workspace_id,
                            batch_id=batch_id
                        )
                        if vid_sent:
                            record_conversation_message("facebook", sender_id, customer_name, "bot", "[Video Demo]", matched_video, page_id=page_id, workspace_id=workspace_id)

                    # Send voice note if requested / generated
                    voice_url = ai_result.get("voice_url", "")
                    if voice_url:
                        voice_sent = send_fb_audio_message(
                            recipient_id=sender_id,
                            audio_url=voice_url,
                            page_token=page_token,
                            page_id=page_id,
                            workspace_id=workspace_id,
                            batch_id=batch_id
                        )
                        if voice_sent:
                            record_conversation_message("facebook", sender_id, customer_name, "bot", "[Voice Note]", voice_url, page_id=page_id, workspace_id=workspace_id)

            # 2. Handle Feed Comments (Auto Comment Reply & Private Inbox Message)
            if "changes" in entry:
                page_id = str(entry.get("id", "")).strip() # Page ID owning the feed
                page_conn = get_connected_page(page_id)
                if not page_conn:
                    page_conn = ensure_facebook_page_consistency()

                workspace_id = (page_conn.get("workspace_id") if page_conn else 1) or 1
                page_token = (page_conn.get("page_access_token") if page_conn else None) or get_fb_token(page_id)
                if not page_token or str(page_token).startswith("EAA_TEST"):
                    page_token = get_setting("fb_page_access_token") or os.getenv("FB_PAGE_ACCESS_TOKEN") or settings.FB_PAGE_ACCESS_TOKEN or get_fb_token(page_id)
                page_name = (page_conn.get("page_name") if page_conn else None) or settings.SHOP_NAME or "RS Graphics (আরএস গ্রাফিক্স)"

                for change in entry.get("changes", []):
                    field = change.get("field")
                    value = change.get("value", {})
                    
                    verb = value.get("verb", "add")
                    if verb in ["remove", "hide", "block", "unlike", "delete"]:
                        continue

                    is_comment = (
                        (field in ["feed", "comments", "mention"]) and 
                        (value.get("item") == "comment" or bool(value.get("comment_id")))
                    )
                    if not is_comment:
                        continue

                    comment_id = str(value.get("comment_id") or value.get("id") or "").strip()
                    if not comment_id:
                        continue

                    # Check deduplication idempotency
                    if is_webhook_event_processed("facebook", f"comment_{comment_id}"):
                        continue
                    mark_webhook_event_processed("facebook", f"comment_{comment_id}", workspace_id=workspace_id, page_id_or_phone_id=page_id)

                    # Ignore old/historical comments (only reply to fresh comments created within last 10 minutes)
                    created_time = value.get("created_time")
                    if created_time:
                        try:
                            c_ts = float(created_time)
                            now_ts = time.time()
                            if (now_ts - c_ts) > 600:
                                print(f"[Facebook Comment Ignored]: Comment {comment_id} was created at {int(c_ts)} ({int(now_ts - c_ts)}s ago). Skipping old comment.")
                                continue
                        except Exception:
                            pass

                    # Database deduplication check
                    conn_check = get_db_connection()
                    try:
                        cur_check = conn_check.cursor()
                        cur_check.execute("SELECT id FROM comment_logs WHERE comment_id = ?", (comment_id,))
                        if cur_check.fetchone():
                            continue
                    finally:
                        conn_check.close()

                    post_id = str(value.get("post_id") or value.get("parent_id") or "").strip()
                    from_user = value.get("from") or {}
                    user_name = from_user.get("name") or value.get("sender_name") or "কাস্টমার"
                    user_id = str(from_user.get("id") or value.get("sender_id") or "").strip()
                    comment_text = str(value.get("message") or value.get("comment_text") or value.get("text") or "").strip()

                    # Prevent replying to own page comments
                    if user_id and (user_id == page_id or (page_conn and user_id == str(page_conn.get("page_id")))):
                        continue

                    # Check settings
                    ai_enabled = bool(page_conn.get("ai_enabled", 1)) if page_conn else True
                    comments_enabled = bool(page_conn.get("comments_enabled", 1)) if page_conn else True
                    if not ai_enabled or not comments_enabled:
                        print(f"[Facebook Comment Skipped]: AI ({ai_enabled}) or Comments ({comments_enabled}) disabled for page {page_id}")
                        continue

                    auto_comment = get_setting("comment_auto_reply", "true").lower() == "true"
                    send_private = get_setting("private_message_on_comment", "true").lower() == "true"
                    comment_ai_mode = get_setting("comment_ai_mode", "ai_smart").lower()
                    honorific = detect_customer_gender_title(user_name)

                    # Generate AI Smart Comment Reply or Template Reply
                    public_reply_text = ""
                    if auto_comment and comment_id:
                        if comment_ai_mode == "ai_smart":
                            comment_prompt = (
                                f"কাস্টমার '{user_name}' ফেসবুক পেজ '{page_name}'-এর পোস্টে কমেন্ট করেছেন: '{comment_text or '[ছবি/স্টিকার/জিজ্ঞাসা]'}'। "
                                f"আপনি {page_name}-এর নম্র ও বিশ্বস্ত সেলস রিপ্রেজেন্টেটিভ হিসেবে এই কমেন্টের খুব সুন্দর, প্রাসঙ্গিক ও চমৎকার একটি পাবলিক উত্তর দিন। "
                                f"কাস্টমারকে সম্মান জানিয়ে {honorific} সম্বোধন করবেন (ভাইয়া/আপু বলবেন না)। "
                                f"সংক্ষিপ্ত ও অমায়িক ভাষায় কথা বলবেন এবং প্রয়োজনে ইনবক্স চেক করতে বলবেন।"
                            )
                            ai_comment_res = await process_customer_message(
                                message_text=comment_prompt,
                                channel="facebook",
                                sender_id=f"comment_{comment_id}",
                                customer_name=user_name,
                                workspace_id=workspace_id,
                                page_id=page_id
                            )
                            public_reply_text = (ai_comment_res.get("reply_text") or "").strip()
                            if not public_reply_text:
                                public_reply_text = f"ধন্যবাদ {user_name} {honorific}! বিস্তারিত তথ্য আপনার ইনবক্সে পাঠানো হয়েছে 🥰"
                        else:
                            template = get_setting("comment_reply_template", f"ধন্যবাদ {{name}} {honorific}! বিস্তারিত তথ্য আপনার ইনবক্সে পাঠানো হয়েছে 🥰")
                            public_reply_text = template.replace("{name}", user_name)

                        if public_reply_text:
                            print(f"[Facebook Comment AI Reply on Workspace {workspace_id} ('{page_name}')]: '{public_reply_text[:60]}...' to comment {comment_id}")
                            reply_to_fb_comment(comment_id, public_reply_text, page_token=page_token, page_id=page_id)

                    # Private inbox reply
                    private_reply_text = ""
                    if send_private and comment_id:
                        inbox_prompt = (
                            f"কাস্টমার '{user_name}' পেজ '{page_name}'-এর পোস্টে কমেন্ট করেছেন: '{comment_text or '[পণ্য অনুসন্ধান]'}'। "
                            f"তাকে ইনবক্সে প্রডাক্টের বিস্তারিত দাম, অফার ও অর্ডার করার নিয়ম জানিয়ে একটি আকর্ষণীয় প্রাইভেট মেসেজ দিন (সম্বোধন {honorific})।"
                        )
                        inbox_res = await process_customer_message(
                            message_text=inbox_prompt,
                            channel="facebook",
                            sender_id=f"comment_{comment_id}",
                            customer_name=user_name,
                            workspace_id=workspace_id,
                            page_id=page_id
                        )
                        private_reply_text = (inbox_res.get("reply_text") or "").strip()
                        if private_reply_text:
                            send_fb_private_reply_to_comment(comment_id, private_reply_text, page_token=page_token, page_id=page_id)

                    # Log to database scoped by workspace_id and page_id
                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR IGNORE INTO comment_logs (
                            workspace_id, post_id, comment_id, user_id, user_name, comment_text, public_reply, private_reply, page_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        workspace_id,
                        post_id,
                        comment_id,
                        user_id,
                        user_name,
                        comment_text,
                        public_reply_text if auto_comment else "",
                        private_reply_text if send_private else "",
                        page_id
                    ))
                    conn.commit()
                    conn.close()

    except Exception as e:
        print(f"[Facebook Webhook Handler Error]: {e}")


