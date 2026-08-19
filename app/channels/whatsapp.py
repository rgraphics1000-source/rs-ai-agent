import requests
import json
from app.config import settings
from app.database import get_setting
from app.ai_agent.gemini_brain import process_customer_message

GRAPH_API_URL = "https://graph.facebook.com/v19.0"

def get_whatsapp_credentials():
    phone_id = get_setting("whatsapp_phone_number_id", settings.WHATSAPP_PHONE_NUMBER_ID)
    token = get_setting("whatsapp_access_token", settings.WHATSAPP_ACCESS_TOKEN)
    return phone_id, token

def send_whatsapp_message(to_number: str, text: str) -> bool:
    """Sends a text message via WhatsApp Cloud API."""
    phone_id, token = get_whatsapp_credentials()
    if not phone_id or not token or not to_number:
        return False

    url = f"{GRAPH_API_URL}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {"preview_url": False, "body": text}
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[WhatsApp Send Error]: {e}")
        return False

async def handle_whatsapp_webhook_event(data: dict):
    """Processes incoming WhatsApp messages."""
    try:
        entries = data.get("entry", [])
        for entry in entries:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                
                customer_name = contacts[0].get("profile", {}).get("name", "Customer") if contacts else "Customer"

                for msg in messages:
                    sender_phone = msg.get("from") # E.164 phone e.g. 8801700000000
                    msg_type = msg.get("type")
                    msg_text = ""
                    image_bytes = None
                    audio_bytes = None

                    if msg_type == "text":
                        msg_text = msg.get("text", {}).get("body", "")
                    elif msg_type == "image":
                        image_id = msg.get("image", {}).get("id")
                        msg_text = msg.get("image", {}).get("caption", "")
                        # Fetch image if token present
                        phone_id, token = get_whatsapp_credentials()
                        if image_id and token:
                            try:
                                media_meta = requests.get(f"{GRAPH_API_URL}/{image_id}", headers={"Authorization": f"Bearer {token}"}).json()
                                media_url = media_meta.get("url")
                                if media_url:
                                    img_resp = requests.get(media_url, headers={"Authorization": f"Bearer {token}"})
                                    if img_resp.status_code == 200:
                                        image_bytes = img_resp.content
                            except Exception as dl_err:
                                print(f"[WhatsApp Image DL Error]: {dl_err}")

                    elif msg_type in ["audio", "voice"]:
                        audio_id = msg.get("audio", {}).get("id") or msg.get("voice", {}).get("id")
                        phone_id, token = get_whatsapp_credentials()
                        if audio_id and token:
                            try:
                                media_meta = requests.get(f"{GRAPH_API_URL}/{audio_id}", headers={"Authorization": f"Bearer {token}"}).json()
                                media_url = media_meta.get("url")
                                if media_url:
                                    aud_resp = requests.get(media_url, headers={"Authorization": f"Bearer {token}"})
                                    if aud_resp.status_code == 200:
                                        audio_bytes = aud_resp.content
                            except Exception as dl_err:
                                print(f"[WhatsApp Audio DL Error]: {dl_err}")

                    if msg_text or image_bytes or audio_bytes:
                        # Check if AI Master Switch is enabled
                        ai_enabled = get_setting("ai_enabled", "true").lower() == "true"
                        if not ai_enabled:
                            print("[WhatsApp]: AI Agent is currently PAUSED by Admin.")
                            continue

                        ai_result = await process_customer_message(
                            message_text=msg_text,
                            image_bytes=image_bytes,
                            audio_bytes=audio_bytes,
                            channel="whatsapp",
                            sender_id=sender_phone,
                            generate_voice_reply=bool(audio_bytes)
                        )

                        reply_text = ai_result.get("reply_text", "")
                        if reply_text and sender_phone:
                            send_whatsapp_message(sender_phone, reply_text)

    except Exception as e:
        print(f"[WhatsApp Webhook Handler Error]: {e}")
