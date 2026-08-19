import os
import json
import requests
import asyncio
from pathlib import Path
from app.config import settings
from app.database import get_db_connection, get_setting
from app.ai_agent.gemini_brain import process_customer_message

GRAPH_API_URL = "https://graph.facebook.com/v19.0"

def get_fb_token() -> str:
    token = get_setting("fb_page_access_token")
    return token if token else settings.FB_PAGE_ACCESS_TOKEN

def get_fb_user_profile(sender_id: str) -> str:
    """Fetches the user name from Facebook Graph API."""
    token = get_fb_token()
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

def record_conversation_message(channel: str, sender_id: str, customer_name: str, sender_type: str, content: str, media_url: str = ""):
    """Saves incoming and outgoing messages to conversations & messages table."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if conversation exists
        cursor.execute("SELECT id, customer_name FROM conversations WHERE sender_id = ?", (sender_id,))
        row = cursor.fetchone()
        
        if row:
            conv_id = row["id"]
            cust_name = row["customer_name"] if row["customer_name"] and row["customer_name"] != "Facebook User" else customer_name
            cursor.execute("""
                UPDATE conversations 
                SET last_message = ?, customer_name = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (content or (f"[Image Attachment]" if media_url else ""), cust_name, conv_id))
        else:
            cursor.execute("""
                INSERT INTO conversations (channel, sender_id, customer_name, last_message, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (channel, sender_id, customer_name, content or (f"[Image Attachment]" if media_url else "")))
            conv_id = cursor.lastrowid
            
        cursor.execute("""
            INSERT INTO messages (conversation_id, sender_type, content, media_url)
            VALUES (?, ?, ?, ?)
        """, (conv_id, sender_type, content, media_url))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Record Conversation Error]: {e}")

def send_fb_text_message(recipient_id: str, text: str) -> bool:
    """Sends a text message to a Facebook Messenger user."""
    token = get_fb_token()
    if not token:
        print("[Facebook Send Error]: Facebook Page Access Token is NOT configured in Settings!")
        return False
    if not recipient_id:
        print("[Facebook Send Error]: Missing recipient_id!")
        return False

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": token}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE"
    }
    try:
        r = requests.post(url, params=params, json=payload, timeout=10)
        print(f"[Facebook Send Result]: HTTP {r.status_code}, Body: {r.text}")
        return r.status_code == 200
    except Exception as e:
        print(f"[Facebook Send Exception]: {e}")
        return False

def send_fb_media_message(recipient_id: str, media_type: str, media_url: str) -> bool:
    """Sends an image or audio attachment to a Facebook Messenger user (via binary upload or URL)."""
    token = get_fb_token()
    if not token or not recipient_id or not media_url:
        return False

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": token}

    # 1. Try local file binary upload if file exists on server disk (100% reliable)
    filename = Path(media_url).name
    candidate_paths = [
        settings.UPLOADS_DIR / filename,
        settings.BASE_DIR / media_url.lstrip("/"),
        settings.STATIC_DIR / media_url.replace("/static/", "").lstrip("/"),
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
                    mime = "image/jpeg" if media_type == "image" else "audio/mp4"
                    files = {"filedata": (p.name, f_bin, mime)}
                    r = requests.post(url, params=params, data=data, files=files, timeout=25)
                    print(f"[Facebook Direct Binary Upload Result]: HTTP {r.status_code}, Body: {r.text}")
                    if r.status_code == 200:
                        return True
            except Exception as up_err:
                print(f"[Facebook Binary Upload Error]: {up_err}")

    # 2. Fallback to URL payload
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
        print(f"[Facebook Media URL Send Result]: HTTP {r.status_code}, Body: {r.text}")
        return r.status_code == 200
    except Exception as e:
        print(f"[Facebook Media Send Error]: {e}")
        return False

def reply_to_fb_comment(comment_id: str, message: str) -> bool:
    """Replies publicly to a Facebook post comment."""
    token = get_fb_token()
    if not token or not comment_id:
        return False

    url = f"{GRAPH_API_URL}/{comment_id}/comments"
    params = {"access_token": token}
    payload = {"message": message}
    try:
        r = requests.post(url, params=params, data=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Facebook Comment Reply Error]: {e}")
        return False

def send_fb_private_reply_to_comment(comment_id: str, message: str) -> bool:
    """Sends a private message to the user who commented on a post."""
    token = get_fb_token()
    if not token or not comment_id:
        return False

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": token}
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
    """Processes incoming Messenger messages and Facebook post comments."""
    try:
        object_type = data.get("object")
        if object_type != "page":
            return

        entries = data.get("entry", [])
        for entry in entries:
            page_id = entry.get("id")
            
            # 1. Handle Messenger Messages
            if "messaging" in entry:
                for event in entry["messaging"]:
                    sender_id = event.get("sender", {}).get("id")
                    if not sender_id or "message" not in event:
                        continue

                    message_obj = event["message"]
                    
                    # Ignore echoes (messages sent by page itself)
                    if message_obj.get("is_echo") or sender_id == page_id:
                        continue

                    msg_text = message_obj.get("text", "")
                    attachments = message_obj.get("attachments", [])
                    print(f"[Facebook Messenger Incoming]: From {sender_id}, Text: '{msg_text}', Attachments: {len(attachments)}")

                    image_bytes = None
                    audio_bytes = None
                    image_mime = "image/jpeg"
                    audio_mime = "audio/mp3"

                    # Check for image or audio attachments
                    for att in attachments:
                        att_type = att.get("type")
                        att_url = att.get("payload", {}).get("url")
                        if att_url:
                            try:
                                resp = requests.get(att_url, timeout=10)
                                if resp.status_code == 200:
                                    if att_type == "image":
                                        image_bytes = resp.content
                                        image_mime = resp.headers.get("content-type", "image/jpeg")
                                    elif att_type in ["audio", "voice"]:
                                        audio_bytes = resp.content
                                        audio_mime = resp.headers.get("content-type", "audio/mp4")
                            except Exception as dl_err:
                                print(f"[Attachment Download Error]: {dl_err}")

                    # Fetch customer name and record customer message
                    customer_name = get_fb_user_profile(sender_id)
                    record_conversation_message("facebook", sender_id, customer_name, "user", msg_text)

                    # Check if AI Master Switch is enabled
                    ai_enabled = get_setting("ai_enabled", "true").lower() == "true"
                    if not ai_enabled:
                        print("[Facebook Messenger]: AI Agent is currently PAUSED by Admin.")
                        continue

                    # Process with Gemini AI Brain
                    ai_result = await process_customer_message(
                        message_text=msg_text,
                        image_bytes=image_bytes,
                        image_mime=image_mime,
                        audio_bytes=audio_bytes,
                        audio_mime=audio_mime,
                        channel="facebook",
                        sender_id=sender_id,
                        generate_voice_reply=bool(audio_bytes)
                    )

                    reply_text = ai_result.get("reply_text", "")
                    if reply_text:
                        print(f"[Facebook Messenger Replying]: '{reply_text[:60]}...' to {sender_id}")
                        send_fb_text_message(sender_id, reply_text)
                        record_conversation_message("facebook", sender_id, customer_name, "bot", reply_text)

                    # Send all matched product images as rich media attachments
                    matched_images = ai_result.get("matched_images", [])
                    base_server_url = get_setting("server_domain", "https://rs-ai-agent.onrender.com").rstrip("/")

                    for img_path in matched_images:
                        if not img_path:
                            continue
                        full_img_url = img_path if img_path.startswith("http") else f"{base_server_url}{img_path}"
                        print(f"[Facebook Messenger Sending Image]: {full_img_url} to {sender_id}")
                        send_fb_media_message(sender_id, "image", img_path)
                        record_conversation_message("facebook", sender_id, customer_name, "bot", "", full_img_url)

            # 2. Handle Feed Comments (Auto Comment Reply & Private Inbox Message)
            if "changes" in entry:
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
                        page_id = get_setting("fb_page_id", settings.FB_PAGE_ID)
                        if user_id == page_id:
                            continue

                        # Check settings
                        ai_enabled = get_setting("ai_enabled", "true").lower() == "true"
                        if not ai_enabled:
                            continue

                        auto_comment = get_setting("comment_auto_reply", "true").lower() == "true"
                        send_private = get_setting("private_message_on_comment", "true").lower() == "true"
                        template = get_setting("comment_reply_template", "ধন্যবাদ {name} আপু/ভাইয়া! বিস্তারিত তথ্য আপনার ইনবক্সে পাঠানো হয়েছে 🥰")
                        
                        public_reply_text = template.replace("{name}", user_name)

                        # Public comment reply
                        if auto_comment and comment_id:
                            reply_to_fb_comment(comment_id, public_reply_text)

                        # Private inbox reply
                        private_reply_text = ""
                        if send_private and comment_id:
                            # Generate tailored inbox message
                            inbox_prompt = f"কাস্টমার '{user_name}' ফেসবুক পোস্টে কমেন্ট করেছেন: '{comment_text}'। তাকে ইনবক্সে প্রডাক্টের বিস্তারিত দাম ও অর্ডার করার নিয়ম জানিয়ে একটি সুন্দর প্রাইভেট মেসেজ দাও।"
                            inbox_res = await process_customer_message(
                                message_text=inbox_prompt,
                                channel="facebook",
                                sender_id=user_id or comment_id
                            )
                            private_reply_text = inbox_res.get("reply_text", "")
                            if private_reply_text:
                                send_fb_private_reply_to_comment(comment_id, private_reply_text)

                        # Log to database
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("""
                            INSERT OR IGNORE INTO comment_logs (
                                post_id, comment_id, user_id, user_name, comment_text, public_reply, private_reply
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            post_id,
                            comment_id,
                            user_id,
                            user_name,
                            comment_text,
                            public_reply_text if auto_comment else "",
                            private_reply_text if send_private else ""
                        ))
                        conn.commit()
                        conn.close()

    except Exception as e:
        print(f"[Facebook Webhook Handler Error]: {e}")
