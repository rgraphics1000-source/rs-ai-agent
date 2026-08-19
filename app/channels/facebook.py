import requests
import asyncio
from app.config import settings
from app.database import get_db_connection, get_setting
from app.ai_agent.gemini_brain import process_customer_message

GRAPH_API_URL = "https://graph.facebook.com/v19.0"

def get_fb_token() -> str:
    token = get_setting("fb_page_access_token")
    return token if token else settings.FB_PAGE_ACCESS_TOKEN

def send_fb_text_message(recipient_id: str, text: str) -> bool:
    """Sends a text message to a Facebook Messenger user."""
    token = get_fb_token()
    if not token or not recipient_id:
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
        return r.status_code == 200
    except Exception as e:
        print(f"[Facebook Send Error]: {e}")
        return False

def send_fb_media_message(recipient_id: str, media_type: str, media_url: str) -> bool:
    """Sends an image or audio attachment to a Facebook Messenger user."""
    token = get_fb_token()
    if not token or not recipient_id or not media_url:
        return False

    url = f"{GRAPH_API_URL}/me/messages"
    params = {"access_token": token}
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": media_type, # 'image' or 'audio'
                "payload": {
                    "url": media_url,
                    "is_reusable": True
                }
            }
        }
    }
    try:
        r = requests.post(url, params=params, json=payload, timeout=10)
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
            # 1. Handle Messenger Messages
            if "messaging" in entry:
                for event in entry["messaging"]:
                    sender_id = event.get("sender", {}).get("id")
                    if not sender_id or "message" not in event:
                        continue

                    message_obj = event["message"]
                    msg_text = message_obj.get("text", "")
                    attachments = message_obj.get("attachments", [])

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
                        send_fb_text_message(sender_id, reply_text)

                    # If AI generated a voice response, send audio
                    voice_url = ai_result.get("voice_url")
                    if voice_url:
                        # Make absolute URL if server domain configured, or send text
                        pass

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
