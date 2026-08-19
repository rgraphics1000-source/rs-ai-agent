import os
import json
import re
import base64
from pathlib import Path
from google import genai
from google.genai import types

from app.config import settings
from app.database import get_db_connection, get_setting, set_setting, get_all_settings
from app.ai_agent.voice_engine import generate_bangla_voice
from app.ai_agent.order_engine import extract_phone_number, create_order

def get_product_catalog_context() -> str:
    """Fetches active products from DB to feed into Gemini prompt."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, code, price, discount_price, stock, category, description, image_url, gallery_images FROM products WHERE is_active = 1")
    products = cursor.fetchall()
    conn.close()

    if not products:
        return "বর্তমানে কোনো প্রডাক্ট ডাটাবেজে যুক্ত নেই।"

    lines = ["📦 আমাদের স্টোরের বর্তমান প্রডাক্ট ক্যাটালগ:"]
    for p in products:
        price = p["discount_price"] if p["discount_price"] and p["discount_price"] < p["price"] else p["price"]
        old_price = f" (আগের দাম: {p['price']}৳)" if p["discount_price"] and p["discount_price"] < p["price"] else ""
        stock_status = f"স্টক: {p['stock']} টি" if p['stock'] > 0 else "স্টক আউট"
        
        gallery_info = ""
        try:
            imgs = json.loads(p["gallery_images"] or "[]")
            if imgs:
                gallery_info = f" [Images: {', '.join(imgs)}]"
            elif p["image_url"]:
                gallery_info = f" [Image: {p['image_url']}]"
        except Exception:
            if p["image_url"]:
                gallery_info = f" [Image: {p['image_url']}]"

        lines.append(
            f"• [{p['code']}] {p['name']} - দাম: {price}৳{old_price} | {stock_status} | বিবরণ: {p['description']}{gallery_info}"
        )
    return "\n".join(lines)

def build_system_instruction() -> str:
    """Builds the natural, human-like system prompt for Bangladeshi Facebook page admin / sales agent."""
    all_settings = get_all_settings()
    shop_name = all_settings.get("shop_name", settings.SHOP_NAME)
    inside_fee = all_settings.get("delivery_inside_dhaka", str(settings.DELIVERY_FEE_INSIDE_DHAKA))
    outside_fee = all_settings.get("delivery_outside_dhaka", str(settings.DELIVERY_FEE_OUTSIDE_DHAKA))
    custom_prompt = all_settings.get("ai_system_prompt", "")
    catalog = get_product_catalog_context()

    prompt = f"""
তুমি হচ্ছো '{shop_name}' অনলাইন পেজের একজন অত্যন্ত আন্তরিক, বিনম্র ও দক্ষ রিয়েল হিউম্যান সেলস এক্সিকিউটিভ (Online Shop Page Admin)।
কাস্টমার যেন কোনোভাবেই বুঝতে না পারে যে তুমি রোবট বা এআই। তোমাকে কথা বলতে হবে একদম রক্তে-মাংসে গড়া একজন সত্যিকারের মানুষের মতো।

{custom_prompt}

গুরুত্বপূর্ণ নিয়মাবলী (Strict Rules):
1. কথা বলার ধরন:
   - অত্যন্ত সাবলীল, বাস্তব ও আন্তরিক ভাষায় কথা বলবে।
   - কাস্টমারকে সম্মান দিয়ে 'আপু' বা 'ভাইয়া' বলে সম্বোধন করবে (যেমন: "আসসালামু আলাইকুম আপু/ভাইয়া! 😊", "জি আপু, এটা এভেইলেবল আছে", "ডেলিভারির সময় চেক করে নিতে পারবেন")।
   - কখনোই কোনো রোবোটিক কোড (যেমন: [PJ-101], SKU, ID ইত্যাদি) কাস্টমারের মেসেজে লিখবে না। শুধুমাত্র প্রডাক্টের সাধারণ নাম ও কালার বলবে।
   - দাম লেখার সময় দশমিক শূন্য (.0) লিখবে না (যেমন: "১২৫০ টাকা" বা "1250 tk" লিখবে, কখনো "1250.0 টাকা" লিখবে না)।
   - কখনো বলবে না "আমি একটি এআই", "আমার ডাটাবেজ অনুযায়ী", বা "সিস্টেম অনুযায়ী"। তুমি নিজেকে পেজের আসল অ্যাডমিন হিসেবে উপস্থাপন করবে।

2. শপের ইনফরমেশন:
   - ডেলিভারি চার্জ: ঢাকার ভেতরে {int(float(inside_fee))} টাকা এবং ঢাকার বাইরে {int(float(outside_fee))} টাকা।
   - ক্যাশ অন ডেলিভারি (Cash on Delivery) সুবিধা আছে। ডেলিভারি ম্যানের সামনে প্রোডাক্ট চেক করে রিসিভ করতে পারবেন।
   - ঢাকার ভেতরে ২৪-৪৮ ঘণ্টা এবং বাইরে ২-৩ দিনে ডেলিভারি হয়।

3. প্রডাক্ট তালিকা:
{catalog}

4. অর্ডার নেওয়ার নিয়ম:
কাস্টমার প্রোডাক্ট পছন্দ করে নিতে চাইলে মিষ্টি করে বলবে:
"অর্ডারটি কনফার্ম করতে আপনার নাম, ফোন নাম্বার আর সম্পূর্ণ ঠিকানাটা দিন প্লিজ 😊"
যখন কাস্টমার নাম, ১১ ডিজিটের মোবাইল নম্বর এবং ঠিকানা দিয়ে দেবে, তখন সুন্দরভাবে বলবে:
"ধন্যবাদ আপু/ভাইয়া! আপনার অর্ডারটি গ্রহণ করা হয়েছে। [প্রোডাক্টের নাম, সাইজ/কালার, মোট টাকা ও ডেলিভারি চার্জ] সহ বিস্তারিত জানিয়ে দেওয়া হবে।"
এবং মেসেজের একদম শেষে সিস্টেমের জন্য এই হিডেন ব্লকটি যুক্ত করবে:
```order_json
{{
  "is_order_ready": true,
  "customer_name": "কাস্টমারের নাম",
  "customer_phone": "017XXXXXXXX",
  "customer_address": "সম্পূর্ণ ঠিকানা",
  "items": [
    {{"name": "প্রডাক্টের নাম", "code": "PJ-101", "qty": 1, "price": 1250, "size": "L", "color": "সাদা"}}
  ],
  "notes": ""
}}
```

5. অডিও ও ইমেজ:
- কাস্টমার যদি বাংলায় ভয়েস নোট পাঠায়, তুমি তার সম্পূর্ণ কথা মনোযোগ দিয়ে শুনে বুঝে শুধুমাত্র মিষ্টি, আন্তরিক ও সাবলীল বাংলায় টেক্সট মেসেজে উত্তর দেবে।
- কাস্টমার ছবি পাঠালে ছবি দেখে সুন্দর করে টেক্সট মেসেজে দাম ও বিবরণ জানাবে।
"""
    return prompt

async def process_customer_message(
    message_text: str = "",
    image_bytes: bytes = None,
    image_mime: str = "image/jpeg",
    audio_bytes: bytes = None,
    audio_mime: str = "audio/mp3",
    conversation_history: list = None,
    channel: str = "facebook",
    sender_id: str = "web_user",
    generate_voice_reply: bool = False
) -> dict:
    """
    Multimodal message processing via Google GenAI (Gemini 2.0 Flash / 1.5 Flash).
    Handles text, images, and audio voice notes.
    """
    api_key = get_setting("gemini_api_key", settings.GEMINI_API_KEY)
    
    # Check if API key is provided
    if not api_key:
        fallback_reply = (
            "আসসালামু আলাইকুম! আমাদের শপে স্বাগতম। "
            "আপনার অর্ডার ও প্রশ্নের উত্তর দেওয়ার জন্য এআই এজেন্ট প্রস্তুত। "
            "(দয়া করে অ্যাডমিন ড্যাশবোর্ডের Settings থেকে আপনার ফ্রি Gemini API Key-টি সেট করুন)।"
        )
        voice_url = await generate_bangla_voice(fallback_reply) if generate_voice_reply else ""
        return {
            "reply_text": fallback_reply,
            "voice_url": voice_url,
            "order_created": None,
            "matched_images": []
        }

    try:
        client = genai.Client(api_key=api_key)
        model_name = get_setting("gemini_model", settings.GEMINI_MODEL)
        
        contents = []
        
        # Add conversation history
        if conversation_history:
            history_text = "[পূর্ববর্তী চ্যাট হিস্ট্রি]:\n"
            for msg in conversation_history[-6:]:
                role = "কাস্টমার" if msg.get("sender_type") == "user" else "এআই এজেন্ট"
                history_text += f"{role}: {msg.get('content', '')}\n"
            contents.append(history_text)

        # Add image attachment
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime))
            if not message_text:
                message_text = "আমি এই ছবিটি পাঠিয়েছি। এই প্রডাক্ট বা ছবিটি দেখে আমাকে বিস্তারিত জানান।"

        # Add audio attachment
        if audio_bytes:
            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=audio_mime))
            if not message_text:
                message_text = "আমি একটি ভয়েস মেসেজ পাঠিয়েছি। দয়া করে শুনুন এবং উত্তর দিন।"

        if message_text:
            contents.append(f"কাস্টমারের মেসেজ: {message_text}")

        saved_model = get_setting("gemini_model", settings.GEMINI_MODEL)
        candidate_models = [saved_model, "gemini-2.5-flash", "gemini-3.6-flash", "gemini-2.5-pro", "gemini-flash-latest"]
        # Remove duplicates while preserving order
        candidate_models = list(dict.fromkeys([m for m in candidate_models if m]))

        response = None
        system_instruction = build_system_instruction()

        for m_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=m_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.7
                    )
                )
                if response and response.text:
                    # Update saved model to the working one
                    set_setting("gemini_model", m_name)
                    break
            except Exception as model_err:
                print(f"[Gemini Model {m_name} failed]: {model_err}")
                continue

        raw_text = response.text if response and response.text else "দুঃখিত, আমি আপনার বার্তাটি বুঝতে পারিনি। আবার বলুন প্লিজ।"

        # Parse order json block if present
        order_created = None
        clean_reply = raw_text

        if "```order_json" in raw_text:
            try:
                parts = raw_text.split("```order_json")
                clean_reply = parts[0].strip()
                json_part = parts[1].split("```")[0].strip()
                order_data = json.loads(json_part)

                if order_data.get("is_order_ready"):
                    phone = order_data.get("customer_phone") or extract_phone_number(message_text)
                    if phone:
                        order_created = create_order(
                            customer_name=order_data.get("customer_name", "Customer"),
                            customer_phone=phone,
                            customer_address=order_data.get("customer_address", "Dhaka"),
                            items=order_data.get("items", []),
                            channel=channel,
                            sender_id=sender_id,
                            notes=order_data.get("notes", "")
                        )
            except Exception as e:
                print(f"[Order Parse Error]: {e}")

        # Extract any image tags from raw_text e.g. [Image: /static/uploads/prod_1.jpg]
        matched_images = []
        found_tags = re.findall(r'\[Image[s]?:\s*([^\]]+)\]', clean_reply)
        for tag in found_tags:
            # Handle comma separated or single URL
            urls = [u.strip() for u in tag.split(",") if u.strip()]
            for u in urls:
                if u not in matched_images:
                    matched_images.append(u)

        # Remove the raw [Image: ...] tags completely from text output
        clean_reply = re.sub(r'\[Image[s]?:\s*[^\]]+\]', '', clean_reply).strip()

        # If customer explicitly asked for photo/picture, match products from DB
        user_lower = (message_text or "").lower()
        is_asking_photo = any(w in user_lower for w in ["ছবি", "পিক", "photo", "image", "pic", "কালার", "দেখাও", "কার্ডের ছবি", "ছবি দাও", "ছবি দিন"])

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT code, name, image_url, gallery_images FROM products WHERE is_active = 1")
        all_prods = cursor.fetchall()
        conn.close()

        for p in all_prods:
            name_match = (p["name"] and p["name"] in clean_reply) or (p["name"] and p["name"].lower() in user_lower)
            code_match = (p["code"] and p["code"] in clean_reply) or (p["code"] and p["code"].lower() in user_lower)
            
            if name_match or code_match or is_asking_photo:
                # Add main image
                if p["image_url"] and p["image_url"] not in matched_images:
                    matched_images.append(p["image_url"])
                # Add gallery images
                try:
                    g_imgs = json.loads(p["gallery_images"] or "[]")
                    for gu in g_imgs:
                        if gu and gu not in matched_images:
                            matched_images.append(gu)
                except Exception:
                    pass

        # AI always replies in pure text
        voice_url = ""

        return {
            "reply_text": clean_reply,
            "voice_url": "",
            "order_created": order_created,
            "matched_images": matched_images
        }

    except Exception as e:
        print(f"[GeminiBrain Error]: {e}")
        err_msg = f"ধন্যবাদ আপনার বার্তার জন্য! আমাদের একজন প্রতিনিধি খুব শীঘ্রই আপনার সাথে যোগাযোগ করবেন।"
        return {
            "reply_text": err_msg,
            "voice_url": "",
            "order_created": None,
            "matched_images": []
        }
