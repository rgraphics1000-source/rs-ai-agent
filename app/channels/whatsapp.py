import os
import requests
import json
import time
import asyncio
from pathlib import Path
from typing import Optional, Tuple
from app.config import settings
from app.database import (
    get_setting, set_setting, get_all_settings,
    is_conversation_ai_active, get_whatsapp_account_by_phone_id,
    get_whatsapp_account_by_page_id, get_page_ai_config
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

def get_whatsapp_credentials(phone_number_id: str = None, page_id: str = None) -> Tuple[str, str]:
    """Gets valid Phone Number ID and Access Token for a specific account, page, or global default."""
    if phone_number_id:
        acc = get_whatsapp_account_by_phone_id(phone_number_id)
        if acc:
            p_id = acc.get("phone_number_id")
            token = acc.get("access_token") or (
                get_setting("meta_system_user_access_token") 
                or get_setting("whatsapp_access_token") 
                or get_setting("fb_page_access_token")
            )
            return p_id, token

    if page_id:
        acc = get_whatsapp_account_by_page_id(page_id)
        if acc:
            p_id = acc.get("phone_number_id")
            token = acc.get("access_token") or (
                get_setting("meta_system_user_access_token") 
                or get_setting("whatsapp_access_token") 
                or get_setting("fb_page_access_token")
            )
            return p_id, token

    all_s = get_all_settings(masked=False)
    phone_id = all_s.get("whatsapp_phone_number_id", "")
    token = (
        all_s.get("meta_system_user_access_token") 
        or all_s.get("whatsapp_access_token") 
        or all_s.get("fb_page_access_token")
    )
    return phone_id, token

def send_whatsapp_message(to_number: str, message_text: str, phone_id: str = None, token: str = None, page_id: str = None) -> bool:
    """Sends a text message via WhatsApp Cloud API using specified or default account."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

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

    print(f"[WhatsApp Send (Phone ID: {phone_id})] recipient={norm_to}")

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"[WhatsApp Send Result] status={r.status_code}, response={r.text}")

        if r.status_code in [200, 201]:
            return True
        else:
            print(f"[WhatsApp Send ERROR] recipient={norm_to} status={r.status_code} response={r.text}")
            return False
    except Exception as e:
        print(f"[WhatsApp Send Exception]: {e}")
        return False

def send_whatsapp_image(to_number: str, image_url: str, caption: str = "", phone_id: str = None, token: str = None, page_id: str = None) -> bool:
    """Sends an image via WhatsApp Cloud API using specified or default account."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

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

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"[WhatsApp Image Send (Phone ID: {phone_id})] status={r.status_code}")
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"[WhatsApp Image Send Exception]: {e}")
        return False

def send_whatsapp_audio(to_number: str, audio_url: str, phone_id: str = None, token: str = None, page_id: str = None) -> bool:
    """Sends a voice note / audio clip via WhatsApp Cloud API."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

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
        print(f"[WhatsApp Audio Send (Phone ID: {phone_id})] status={r.status_code}")
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"[WhatsApp Audio Send Exception]: {e}")
        return False

def send_whatsapp_video(to_number: str, video_url: str, caption: str = "", phone_id: str = None, token: str = None, page_id: str = None) -> bool:
    """Sends a video clip via WhatsApp Cloud API."""
    if not phone_id or not token:
        resolved_pid, resolved_tok = get_whatsapp_credentials(phone_number_id=phone_id, page_id=page_id)
        phone_id = phone_id or resolved_pid
        token = token or resolved_tok

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
        print(f"[WhatsApp Video Send (Phone ID: {phone_id})] status={r.status_code}")
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"[WhatsApp Video Send Exception]: {e}")
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
                meta_phone_id = metadata.get("phone_number_id")

                # Resolve specific WhatsApp account and linked Page configuration
                wa_account = get_whatsapp_account_by_phone_id(meta_phone_id)
                if wa_account:
                    effective_phone_id = wa_account.get("phone_number_id")
                    effective_token = wa_account.get("access_token") or (
                        get_setting("meta_system_user_access_token") 
                        or get_setting("whatsapp_access_token") 
                        or get_setting("fb_page_access_token")
                    )
                    page_id = wa_account.get("page_id") or ""
                    page_name = wa_account.get("shop_name") or wa_account.get("page_name") or "RS Graphics"
                else:
                    effective_phone_id, effective_token = get_whatsapp_credentials(meta_phone_id)
                    page_id = get_setting("fb_page_id", settings.FB_PAGE_ID)
                    page_name = get_setting("shop_name", settings.SHOP_NAME)

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
                    image_mime = "image/jpeg"
                    audio_bytes = None
                    audio_mime = "audio/mp4"

                    print(f"[WhatsApp Webhook (Account: {effective_phone_id})] received from={sender_phone} type={msg_type} msg_id={msg_id}")

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
                        # Record incoming customer message scoped to this Page
                        customer_name = raw_customer_name or f"WhatsApp User ({sender_phone})"
                        record_conversation_message("whatsapp", sender_phone, customer_name, "user", msg_text, page_id=page_id)

                        # Check if AI Master Switch or Per-Customer Takeover is active
                        if not is_conversation_ai_active(sender_id=sender_phone):
                            print(f"[WhatsApp]: AI is PAUSED for customer {sender_phone} on account {effective_phone_id} (Human Takeover). AI will stay silent.")
                            continue

                        # Fetch conversation history scoped to this Page
                        history = get_conversation_history("whatsapp", sender_phone, limit=8, page_id=page_id)

                        # Process with Gemini AI Brain
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
                            generate_voice_reply=bool(audio_bytes)
                        )

                        reply_text = ai_result.get("reply_text", "")
                        print(f"[AI Reply on WA {effective_phone_id}] generated for={sender_phone}: {reply_text[:60] if reply_text else 'None'}...")

                        if reply_text and sender_phone:
                            send_ok = send_whatsapp_message(
                                sender_phone, reply_text,
                                phone_id=effective_phone_id, token=effective_token, page_id=page_id
                            )
                            if send_ok:
                                record_conversation_message("whatsapp", sender_phone, customer_name, "bot", reply_text, page_id=page_id)
                            else:
                                print(f"[WhatsApp Send] Delivery FAILED for {sender_phone}. AI message was NOT recorded as sent.")

                        # Batch send sample images if requested
                        matched_images = ai_result.get("matched_images", [])
                        if matched_images:
                            print(f"[WhatsApp Batch Images on WA {effective_phone_id}] Sending {len(matched_images)} images to {sender_phone}...")
                            for img_path in matched_images:
                                if not img_path:
                                    continue
                                img_ok = send_whatsapp_image(
                                    sender_phone, img_path,
                                    phone_id=effective_phone_id, token=effective_token, page_id=page_id
                                )
                                if img_ok:
                                    record_conversation_message("whatsapp", sender_phone, customer_name, "bot", "", img_path, page_id=page_id)
                                await asyncio.sleep(0.15)

                        # Send video demo if requested
                        matched_video = ai_result.get("video_url", "")
                        if matched_video:
                            print(f"[WhatsApp Video on WA {effective_phone_id}] Sending video demo to {sender_phone}...")
                            v_ok = send_whatsapp_video(
                                sender_phone, matched_video,
                                phone_id=effective_phone_id, token=effective_token, page_id=page_id
                            )
                            if v_ok:
                                record_conversation_message("whatsapp", sender_phone, customer_name, "bot", "[Video Demo]", matched_video, page_id=page_id)

                        # Send voice note if requested / generated
                        voice_url = ai_result.get("voice_url", "")
                        if voice_url:
                            print(f"[WhatsApp Voice on WA {effective_phone_id}] Sending voice note to {sender_phone}...")
                            a_ok = send_whatsapp_audio(
                                sender_phone, voice_url,
                                phone_id=effective_phone_id, token=effective_token, page_id=page_id
                            )
                            if a_ok:
                                record_conversation_message("whatsapp", sender_phone, customer_name, "bot", "[Voice Note]", voice_url, page_id=page_id)

    except Exception as e:
        print(f"[WhatsApp Webhook Handler Error]: {e}")

