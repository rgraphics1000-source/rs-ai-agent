import os
import requests
import json
import time
from pathlib import Path
from app.config import settings
from app.database import (
    get_setting, set_setting, get_all_settings,
    is_conversation_ai_active
)
from app.channels.omnichat import record_conversation_message, get_conversation_history
from app.ai_agent.gemini_brain import process_customer_message

GRAPH_API_URL = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}"
PROCESSED_WA_MESSAGE_IDS = set()

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

def get_whatsapp_credentials():
    """Gets valid Phone Number ID and Access Token."""
    all_s = get_all_settings(masked=False)
    phone_id = all_s.get("whatsapp_phone_number_id", "")
    token = (
        all_s.get("meta_system_user_access_token") 
        or all_s.get("whatsapp_access_token") 
        or all_s.get("fb_page_access_token")
    )
    return phone_id, token

def send_whatsapp_message(to_number: str, message_text: str) -> bool:
    """Sends a text message via WhatsApp Cloud API."""
    phone_id, token = get_whatsapp_credentials()
    if not phone_id or not token or not to_number or not message_text:
        print(f"[WhatsApp Send] Missing credentials or recipient! phone_id={'SET' if phone_id else 'MISSING'}, token={'SET' if token else 'MISSING'}, recipient={to_number}")
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)
    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
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

    print(f"[WhatsApp Send] recipient={norm_to}")
    print(f"[WhatsApp Send] endpoint={url}")

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"[WhatsApp Send] status={r.status_code}")
        print(f"[WhatsApp Send] response={r.text}")

        if r.status_code in [200, 201]:
            try:
                res_data = r.json()
                messages = res_data.get("messages", [])
                if messages and len(messages) > 0:
                    msg_id = messages[0].get("id", "")
                    if msg_id:
                        print(f"[WhatsApp Send] message_id={msg_id}")
                return True
            except Exception:
                return True
        else:
            print(f"[WhatsApp Send ERROR] recipient={norm_to} status={r.status_code} response={r.text}")
            return False
    except Exception as e:
        print(f"[WhatsApp Send Exception]: {e}")
        return False

def send_whatsapp_image(to_number: str, image_url: str, caption: str = "") -> bool:
    """Sends an image via WhatsApp Cloud API."""
    phone_id, token = get_whatsapp_credentials()
    if not phone_id or not token or not to_number or not image_url:
        print(f"[WhatsApp Image Send] Missing credentials or recipient! phone_id={'SET' if phone_id else 'MISSING'}, token={'SET' if token else 'MISSING'}, recipient={to_number}")
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)
    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
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

    print(f"[WhatsApp Image Send] recipient={norm_to}")
    print(f"[WhatsApp Image Send] endpoint={url}")
    print(f"[WhatsApp Image Send] image_url={full_url}")

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"[WhatsApp Image Send] status={r.status_code}")
        print(f"[WhatsApp Image Send] response={r.text}")
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"[WhatsApp Image Send Exception]: {e}")
        return False

def send_whatsapp_audio(to_number: str, audio_url: str) -> bool:
    """Sends a voice note / audio clip via WhatsApp Cloud API."""
    phone_id, token = get_whatsapp_credentials()
    if not phone_id or not token or not to_number or not audio_url:
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)
    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
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
        print(f"[WhatsApp Audio Send] status={r.status_code} response={r.text}")
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"[WhatsApp Audio Send Exception]: {e}")
        return False

def send_whatsapp_video(to_number: str, video_url: str, caption: str = "") -> bool:
    """Sends a video clip via WhatsApp Cloud API."""
    phone_id, token = get_whatsapp_credentials()
    if not phone_id or not token or not to_number or not video_url:
        return False

    norm_to = normalize_whatsapp_phone_number(to_number)
    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
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
        print(f"[WhatsApp Video Send] status={r.status_code} response={r.text}")
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"[WhatsApp Video Send Exception]: {e}")
        return False

async def handle_whatsapp_webhook_event(data: dict):
    """Processes incoming WhatsApp messages."""
    try:
        entries = data.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                
                # Check metadata for phone_number_id auto-detection if needed
                metadata = value.get("metadata", {})
                meta_phone_id = metadata.get("phone_number_id")
                if meta_phone_id:
                    current_phone_id = get_setting("whatsapp_phone_number_id", "")
                    if not current_phone_id:
                        set_setting("whatsapp_phone_number_id", str(meta_phone_id))
                        print(f"[WhatsApp Webhook] Auto-detected phone_number_id from metadata: {meta_phone_id}")

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
                    msg_type = msg.get("type")
                    msg_text = ""
                    image_bytes = None
                    audio_bytes = None

                    print(f"[WhatsApp Webhook] received from={sender_phone} type={msg_type} msg_id={msg_id}")

                    if msg_type == "text":
                        msg_text = msg.get("text", {}).get("body", "")
                    elif msg_type == "image":
                        image_id = msg.get("image", {}).get("id")
                        phone_id, token = get_whatsapp_credentials()
                        if image_id and token:
                            try:
                                media_meta = requests.get(f"{GRAPH_API_URL}/{image_id}", headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
                                media_url = media_meta.get("url")
                                if media_url:
                                    img_resp = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
                                    if img_resp.status_code == 200:
                                        image_bytes = img_resp.content
                            except Exception as dl_err:
                                print(f"[WhatsApp Image DL Error]: {dl_err}")
                        msg_text = msg.get("image", {}).get("caption", "")
                    elif msg_type in ["audio", "voice"]:
                        audio_id = msg.get("audio", {}).get("id") or msg.get("voice", {}).get("id")
                        phone_id, token = get_whatsapp_credentials()
                        if audio_id and token:
                            try:
                                media_meta = requests.get(f"{GRAPH_API_URL}/{audio_id}", headers={"Authorization": f"Bearer {token}"}, timeout=10).json()
                                media_url = media_meta.get("url")
                                if media_url:
                                    aud_resp = requests.get(media_url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
                                    if aud_resp.status_code == 200:
                                        audio_bytes = aud_resp.content
                            except Exception as dl_err:
                                print(f"[WhatsApp Audio DL Error]: {dl_err}")

                    if msg_text or image_bytes or audio_bytes:
                        # Record incoming customer message
                        customer_name = raw_customer_name or f"WhatsApp User ({sender_phone})"
                        record_conversation_message("whatsapp", sender_phone, customer_name, "user", msg_text)

                        # Check if AI Master Switch or Per-Customer Takeover is active
                        if not is_conversation_ai_active(sender_id=sender_phone):
                            print(f"[WhatsApp]: AI is PAUSED for customer {sender_phone} (Human Takeover). AI will stay silent.")
                            continue

                        # Fetch conversation history
                        history = get_conversation_history("whatsapp", sender_phone, limit=8)

                        # Process with Gemini AI
                        ai_result = await process_customer_message(
                            message_text=msg_text,
                            image_bytes=image_bytes,
                            audio_bytes=audio_bytes,
                            conversation_history=history,
                            channel="whatsapp",
                            sender_id=sender_phone,
                            customer_name=customer_name,
                            generate_voice_reply=bool(audio_bytes)
                        )

                        reply_text = ai_result.get("reply_text", "")
                        print(f"[AI Reply] generated for={sender_phone}: {reply_text[:60] if reply_text else 'None'}...")

                        if reply_text and sender_phone:
                            send_ok = send_whatsapp_message(sender_phone, reply_text)
                            if send_ok:
                                record_conversation_message("whatsapp", sender_phone, customer_name, "bot", reply_text)
                            else:
                                print(f"[WhatsApp Send] Delivery FAILED for {sender_phone}. AI message was NOT recorded as sent.")

                        # Batch send sample images if requested
                        matched_images = ai_result.get("matched_images", [])
                        if matched_images:
                            print(f"[WhatsApp Batch Images] Sending {len(matched_images)} images to {sender_phone}...")
                            for img_path in matched_images:
                                if not img_path:
                                    continue
                                img_ok = send_whatsapp_image(sender_phone, img_path)
                                if img_ok:
                                    record_conversation_message("whatsapp", sender_phone, customer_name, "bot", "", img_path)
                                time.sleep(0.3) # Brief delay between batch attachments

    except Exception as e:
        print(f"[WhatsApp Webhook Handler Error]: {e}")
