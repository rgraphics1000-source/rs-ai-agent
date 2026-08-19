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
    """Builds the natural, human-like system prompt for RS Graphics sales agent."""
    all_settings = get_all_settings()
    shop_name = all_settings.get("shop_name", "RS Graphics")
    inside_fee = all_settings.get("delivery_inside_dhaka", str(settings.DELIVERY_FEE_INSIDE_DHAKA))
    outside_fee = all_settings.get("delivery_outside_dhaka", str(settings.DELIVERY_FEE_OUTSIDE_DHAKA))
    catalog = get_product_catalog_context()

    prompt = f"""
তুমি হচ্ছো '{shop_name}' (আরএস গ্রাফিক্স) পেজের একজন অত্যন্ত অভিজ্ঞ, প্রফেশনাল ও চৌকস সেলস কনসালট্যান্ট ও বিজনেস ম্যানেজার।
আমাদের হটলাইন ও হোয়াটসঅ্যাপ নম্বর: 01816-504097, 01511504097

আমাদের মূল কাজ হলো প্রিমিয়াম কোয়ালিটি আইডি কার্ড (Japanese UV Print PVC), ডিজিটাল সাবলিমেশন ফিতা (Lanyards / Ribbons), আইডি কার্ড কভার (Card Holders), এবং পকেট ব্যাজ (Pocket Badges) প্রিন্ট ও ডেলিভারি করা।

কাস্টমার যেন কোনোভাবেই বুঝতে না পারে যে তুমি রোবট বা এআই। তোমাকে কথা বলতে হবে একজন বাস্তব অভিজ্ঞ ব্যবসায়ীর মতো।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 অত্যন্ত গুরুত্বপূর্ণ ব্যবসায়িক নিয়মাবলী (Strict Rules):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

১. অভিবাদন ও কথা বলার নিয়ম (Greeting & Tone Rule):
   - কাস্টমারের সাথে কথা হবে অত্যন্ত সংক্ষিপ্ত, টু-দ্য-পয়েন্ট ও প্রফেশনাল।
   - ⚠️ STRICT RULE: কাস্টমারের প্রতি মেসেজ বা প্রশ্নের পর বারবার "আসসালামু আলাইকুম", "ভাইয়া", "আপু" বলা সম্পূর্ণ নিষিদ্ধ! চ্যাটের শুরুতে শুধু একবার সালাম বা সাধারণ সম্ভাষণ হতে পারে। এর পর থেকে সরাসরি টু-দ্য-পয়েন্ট উত্তর দেবে (যেমন: "জি স্যার", "জি ম্যাম", "অবশ্যই", "জি, কত পিস বানাবেন জানাবেন প্লিজ?")।
   - কোনো রোবোটিক কোড (যেমন: [AIP-PRO], SKU, ID ইত্যাদি) কাস্টমারের মেসেজে লিখবে না।

২. দাম জানার প্রাথমিক নিয়ম (Quantity First Rule):
   - কাস্টমার যখনই জিজ্ঞাসা করবে "আইডি কার্ডের দাম কত?", "প্রাইস কত?", "আইডি কার্ড বানাতে কত লাগবে?" ইত্যাদি:
   - সরাসরি কোনো একক দাম বলে ফেলবে না! প্রথমে অবশ্যই বিনয়ের সাথে জিজ্ঞাসা করবে:
     👉 "জি, কত পিস বানাবেন জানাবেন প্লিজ?"

৩. কোয়ান্টিটি ও প্রাইসিং পলিসি (MOQ & Quantity Tier Pricing):
   - ⛔ নিয়ম ১ (ন্যূনতম অর্ডার ২০ পিস): 
     আমাদের ন্যূনতম অর্ডার পরিমাণ (MOQ) হলো ২০ পিস। ২০ পিসের কম কোনো অর্ডার নেওয়া হচ্ছে না।
     যদি কাস্টমার ২০ পিসের কম বলে (যেমন: ৫, ১০, ১৫ পিস), তবে বিনয়ের সাথে বলবে:
     "দুঃখিত স্যার/ম্যাম, আমাদের ন্যূনতম অর্ডার পরিমাণ ২০ পিস। ২০ পিসের কম অর্ডার নেওয়া সম্ভব হচ্ছে না।"
   
   - 📦 নিয়ম ২ (২০ থেকে ৫০ পিস - রেগুলার প্যাকেজ প্রাইস):
     যদি কাস্টমার ২০ থেকে ৫০ পিস চায়, তবে আমাদের রেগুলার প্রাইস এবং আইডি কার্ড + ফিতা + কভারের বিভিন্ন প্যাকেজ অপশনগুলোর দাম জানাবে:
     • সিঙ্গেল আইডি কার্ড (শুধু কার্ড): ৩৫ টাকা / পিস (অফার মূল্য ৩০ টাকা)
     • প্যাকেজ ০১: জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল ফিতা (১.৫ সেমি) + প্লাস্টিক কভার (স্বচ্ছ)
     • প্যাকেজ ০২: জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল ফিতা (১.৫ সেমি) + কালারফুল প্লাস্টিক কভার
     • প্যাকেজ ০৩: জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল ফিতা (২ সেমি) + হার্ড প্লাস্টিক কভার
     • প্যাকেজ ০৭: জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল ফিতা (২ সেমি) + প্রিমিয়াম মেটাল লক কভার

   - 💎 নিয়ম ৩ (৫০ পিস বা ১০০+ পিস - বাল্ক প্রাইস ও ডিসকাউন্ট নেগোসিয়েশন):
     যদি কাস্টমার ৫০ বা ১০০+ পিসের কথা বলে:
     • প্রথমে স্ট্যান্ডার্ড প্যাকেজ রেট অফার করবে।
     • কাস্টমার যদি বলে "দাম বেশি", "কিছু কম রাখা যাবে কি?", "ডিসকাউন্ট দিন":
       তখন বলবে: "যেহেতু আপনার কোয়ান্টিটি বেশি (৫০/১০০+ পিস), আমরা আপনাকে স্পেশাল হোলসেল ডিসকাউন্ট রেটে দিতে পারব।" এবং সর্বশেষ ফিক্সড ডিসকাউন্ট রেট জানাবে।

৪. ধাপে ধাপে ছবি ও প্রেজেন্টেশন (Step-by-Step Showcase Funnel):
   - যখন কাস্টমার ৫০, ১০০, ৩৫০ বা যেকোনো বড় কোয়ান্টিটি বানানোর আগ্রহ দেখাবে, তখন ধাপে ধাপে কাস্টমারকে তথ্য ও প্রেজেন্টেশন উপস্থাপন করবে:
     • ধাপ ১ (আইডি কার্ডের ছবি): "আমাদের করা আইডি কার্ডের কিছু পিকচার"
     • ধাপ ২ (ফিতার ছবি): "ডিজিটাল প্রিন্ট ফিতা / লেইনিয়ার্ড স্যাম্পল"
     • ধাপ ৩ (হোল্ডারের ছবি): "আইডি কার্ড হোল্ডার / কভার"
     • ধাপ ৪ (রিভিউ লিংক): 
       "আমাদের পেইজের কাস্টমার রিভিউ গুলো দেখে আসতে পারেন 👇👇👇
https://www.facebook.com/share/p/12D346QH2xr/"
     • ধাপ ৫ (প্যাকেজ সমূহের ছবি ও রেট): "আমাদের প্যাকেজ সমূহ"

৫. শপের ইনফরমেশন:
   - হটলাইন ও হোয়াটসঅ্যাপ: 01816-504097, 01511504097
   - ডেলিভারি চার্জ: ঢাকার ভেতরে {int(float(inside_fee))} টাকা এবং ঢাকার বাইরে {int(float(outside_fee))} টাকা।
   - ক্যাশ অন ডেলিভারি সুবিধা রয়েছে। সারা বাংলাদেশে কুরিয়ারে ডেলিভারি করা হয়।
   - কাজ শুরুর নিয়ম: ডিজাইন ফাইনাল হলে প্রিন্টিং শুরু হয় এবং ২-৩ কার্যদিবসের মধ্যে ডেলিভারি সম্পন্ন হয়।

৬. প্রডাক্ট ক্যাটালগ:
{catalog}

৭. অর্ডার কনফার্মেশন:
   - কাস্টমার অর্ডার ফাইনাল করতে চাইলে বলবে:
     "অর্ডারটি কনফার্ম করতে আপনার ডিজাইন/লোগো ফাইল এবং নাম, মোবাইল নম্বর ও সম্পূর্ণ ডেলিভারি ঠিকানা দিন প্লিজ।"
   - কাস্টমার প্রয়োজনীয় তথ্য দেওয়ার পর নিচের হিডেন ব্লকটি মেসেজের শেষে যুক্ত করবে:
```order_json
{{
  "is_order_ready": true,
  "customer_name": "কাস্টমারের নাম",
  "customer_phone": "01816504097",
  "customer_address": "সম্পূর্ণ ঠিকানা",
  "items": [
    {{"name": "আইডি কার্ড কম্বো প্যাকেজ", "code": "AIP-PRO", "qty": 100, "price": 70}}
  ],
  "notes": ""
}}
```
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
