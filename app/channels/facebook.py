import os
import sys
import json
import time
import requests
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from app.config import settings
from app.database import (
    get_db_connection, get_setting, is_conversation_ai_active,
    get_connected_page, get_all_connected_pages, get_page_ai_config,
    ensure_facebook_page_consistency
)
from app.channels.omnichat import record_conversation_message, get_conversation_history
from app.ai_agent.gemini_brain import process_customer_message

GRAPH_API_URL = "https://graph.facebook.com/v19.0"
PROCESSED_FB_MESSAGE_IDS = set()

def get_fb_token(page_id: str = None) -> str:
    """Retrieves the access token for a specific Page ID, or falls back to global settings / primary connected page."""
    if page_id:
        p = get_connected_page(page_id)
        if p and p.get("page_access_token"):
            return p["page_access_token"]
    token = get_setting("fb_page_access_token") or settings.FB_PAGE_ACCESS_TOKEN
    if not token:
        all_pages = get_all_connected_pages()
        if all_pages and all_pages[0].get("page_access_token"):
            return all_pages[0]["page_access_token"]
    return token or ""

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

def send_fb_media_message(recipient_id: str, media_type: str, media_url: str, page_token: str = None, page_id: str = None) -> bool:
    """Sends an image, video, or audio attachment to a Facebook Messenger user."""
    token = page_token or get_fb_token(page_id)
    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or not recipient_id or not media_url:
        return False

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": clean_token}
    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")
    full_url = media_url if media_url.startswith("http") else f"{base_server_url}{media_url}"

    # 1. URL attachment payload method (Fastest & standard for Messenger)
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
        print(f"[Facebook Media URL Send]: status={r.status_code}, body={r.text}")
        if r.status_code == 200:
            return True
    except Exception as e:
        print(f"[Facebook Media URL Error]: {e}")

    # 2. Local binary fallback if file exists on disk
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
                data = {
                    "recipient": json.dumps({"id": recipient_id}),
                    "message": json.dumps({
                        "attachment": {
                            "type": media_type,
                            "payload": {"is_reusable": True}
                        }
                    })
                }
                with open(p, "rb") as f_bin:
                    mime = "image/jpeg" if media_type == "image" else ("video/mp4" if media_type == "video" else "audio/mp4")
                    files = {"filedata": (p.name, f_bin, mime)}
                    r = requests.post(url, params=params, data=data, files=files, timeout=25)
                    print(f"[Facebook Direct Binary Upload Result]: HTTP {r.status_code}, Body: {r.text}")
                    if r.status_code == 200:
                        return True
            except Exception as up_err:
                print(f"[Facebook Binary Upload Error]: {up_err}")

    return False

def send_fb_audio_message(recipient_id: str, audio_url: str, page_token: str = None, page_id: str = None) -> bool:
    """Sends an audio / voice message via Facebook Messenger."""
    return send_fb_media_message(recipient_id, "audio", audio_url, page_token=page_token, page_id=page_id)

def send_fb_video_message(recipient_id: str, video_url: str, page_token: str = None, page_id: str = None) -> bool:
    """Sends a video attachment via Facebook Messenger."""
    return send_fb_media_message(recipient_id, "video", video_url, page_token=page_token, page_id=page_id)

def reply_to_fb_comment(comment_id: str, message: str, page_token: str = None, page_id: str = None) -> bool:
    """Replies publicly to a Facebook post comment."""
    token = page_token or get_fb_token(page_id)
    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or not comment_id:
        return False

    url = f"{GRAPH_API_URL}/{comment_id}/comments"
    params = {"access_token": clean_token}
    payload = {"message": message}
    try:
        r = requests.post(url, params=params, data=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Facebook Comment Reply Error]: {e}")
        return False

def send_fb_private_reply_to_comment(comment_id: str, message: str, page_token: str = None, page_id: str = None) -> bool:
    """Sends a private message to the user who commented on a post."""
    token = page_token or get_fb_token(page_id)
    clean_token = str(token or "").strip().strip('"').strip("'")
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    if not clean_token or not comment_id:
        return False

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": clean_token}
    payload = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": message}
    }
    try:
        r = requests.post(url, params=params, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Facebook Private Reply Error]: {e}")
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
                    sender_id = event.get("sender", {}).get("id")
                    recipient_id = event.get("recipient", {}).get("id") # Target Page ID
                    
                    target_page_id = str(recipient_id or entry_id).strip()
                    if not target_page_id or not sender_id:
                        continue

                    # Look up the specific connected page for this message
                    page_conn = get_connected_page(target_page_id)
                    if not page_conn and target_page_id in ["105116472071659", "rs_graphics_page_1"]:
                        page_conn = ensure_facebook_page_consistency()

                    if not page_conn:
                        print(f"[Facebook Routing Error]: Unknown recipient_id {target_page_id}. No matching connected_page found. Event dropped without fallback.")
                        continue

                    workspace_id = page_conn.get("workspace_id", 1)
                    page_id = page_conn.get("page_id", target_page_id)
                    page_token = page_conn.get("page_access_token")
                    page_name = page_conn.get("page_name", "Facebook Page")

                    print(f"[Facebook Routing] recipient_id={target_page_id} matched_page_id={page_id} workspace_id={workspace_id} page_name={page_name}")

                    # Prevent replying to messages sent by our own pages
                    if sender_id == recipient_id or get_connected_page(sender_id) is not None:
                        continue

                    msg = event.get("message", {})
                    if not msg:
                        continue

                    msg_id = msg.get("mid")
                    if msg_id:
                        if msg_id in PROCESSED_FB_MESSAGE_IDS:
                            print(f"[Facebook Webhook] Duplicate message skipped: mid={msg_id}")
                            continue
                        PROCESSED_FB_MESSAGE_IDS.add(msg_id)
                        if len(PROCESSED_FB_MESSAGE_IDS) > 2000:
                            PROCESSED_FB_MESSAGE_IDS.pop()

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
                        send_fb_text_message(sender_id, reply_text, page_token=page_token, page_id=page_id)
                        record_conversation_message("facebook", sender_id, customer_name, "bot", reply_text, page_id=page_id, workspace_id=workspace_id)

                    # Send all matched product images as rich media attachments
                    matched_images = ai_result.get("matched_images", [])
                    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")

                    for img_path in matched_images:
                        if not img_path:
                            continue
                        full_img_url = img_path if img_path.startswith("http") else f"{base_server_url}{img_path}"
                        print(f"[Facebook Messenger Sending Image on Workspace {workspace_id}]: {full_img_url} to {sender_id}")
                        send_fb_media_message(sender_id, "image", img_path, page_token=page_token, page_id=page_id)
                        record_conversation_message("facebook", sender_id, customer_name, "bot", "", full_img_url, page_id=page_id, workspace_id=workspace_id)
                        await asyncio.sleep(0.15)

                    # Send video demo if requested
                    matched_video = ai_result.get("video_url", "")
                    if matched_video:
                        print(f"[Facebook Messenger Sending Video on Workspace {workspace_id}]: {matched_video} to {sender_id}")
                        send_fb_video_message(sender_id, matched_video, page_token=page_token, page_id=page_id)
                        record_conversation_message("facebook", sender_id, customer_name, "bot", "[Video Demo]", matched_video, page_id=page_id, workspace_id=workspace_id)

                    # Send voice note if requested / generated
                    voice_url = ai_result.get("voice_url", "")
                    if voice_url:
                        print(f"[Facebook Messenger Sending Audio on Workspace {workspace_id}]: {voice_url} to {sender_id}")
                        send_fb_audio_message(sender_id, voice_url, page_token=page_token, page_id=page_id)
                        record_conversation_message("facebook", sender_id, customer_name, "bot", "[Voice Note]", voice_url, page_id=page_id, workspace_id=workspace_id)

            # 2. Handle Feed Comments (Auto Comment Reply & Private Inbox Message)
            if "changes" in entry:
                page_id = str(entry.get("id", "")).strip() # Page ID owning the feed
                page_conn = get_connected_page(page_id)
                if not page_conn and page_id in ["105116472071659", "rs_graphics_page_1"]:
                    page_conn = ensure_facebook_page_consistency()

                if not page_conn:
                    print(f"[Facebook Routing Error]: Unknown page_id {page_id} for comment. Event dropped without fallback.")
                    continue

                workspace_id = page_conn.get("workspace_id", 1)
                page_token = page_conn.get("page_access_token")
                page_name = page_conn.get("page_name", "Facebook Page")

                for change in entry["changes"]:
                    field = change.get("field")
                    value = change.get("value", {})
                    
                    if field == "feed" and value.get("item") == "comment" and value.get("verb") == "add":
                        comment_id = value.get("comment_id")
                        post_id = value.get("post_id")
                        from_user = value.get("from", {})
                        user_name = from_user.get("name", "কাস্টমার")
                        user_id = from_user.get("id")
                        comment_text = value.get("message", "")

                        # Prevent replying to own page comments
                        if user_id == page_id or (page_conn and user_id == page_conn.get("page_id")):
                            continue

                        # Check settings
                        ai_enabled = bool(page_conn.get("ai_enabled", 1))
                        if not ai_enabled:
                            continue

                        auto_comment = get_setting("comment_auto_reply", "true").lower() == "true"
                        send_private = get_setting("private_message_on_comment", "true").lower() == "true"
                        template = get_setting("comment_reply_template", "ধন্যবাদ {name} আপু/ভাইয়া! বিস্তারিত তথ্য আপনার ইনবক্সে পাঠানো হয়েছে 🥰")
                        
                        public_reply_text = template.replace("{name}", user_name)

                        # Public comment reply
                        if auto_comment and comment_id:
                            reply_to_fb_comment(comment_id, public_reply_text, page_token=page_token, page_id=page_id)

                        # Private inbox reply
                        private_reply_text = ""
                        if send_private and comment_id:
                            # Generate tailored inbox message scoped to workspace
                            inbox_prompt = f"কাস্টমার '{user_name}' পেজ '{page_name}' এর পোস্টে কমেন্ট করেছেন: '{comment_text}'। তাকে ইনবক্সে প্রডাক্টের বিস্তারিত দাম ও অর্ডার করার নিয়ম জানিয়ে একটি সুন্দর প্রাইভেট মেসেজ দাও।"
                            inbox_res = await process_customer_message(
                                message_text=inbox_prompt,
                                channel="facebook",
                                sender_id=user_id or comment_id,
                                workspace_id=workspace_id,
                                page_id=page_id
                            )
                            private_reply_text = inbox_res.get("reply_text", "")
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


