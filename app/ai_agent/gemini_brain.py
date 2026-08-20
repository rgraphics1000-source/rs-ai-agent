import os
import json
import re
import base64
from pathlib import Path
from google import genai
from google.genai import types

from app.config import settings
from app.database import (
    get_db_connection, get_setting, set_setting, get_all_settings, get_active_training_rules
)
from app.ai_agent.voice_engine import generate_bangla_voice
from app.ai_agent.order_engine import extract_phone_number, create_order

def detect_customer_gender_title(customer_name: str) -> str:
    """
    Intelligently recognizes if customer is male/female from their name.
    Returns 'ভাইয়া', 'আপু', or 'স্যার/ম্যাম'.
    """
    if not customer_name:
        return "স্যার/ম্যাম"
    
    name_lower = customer_name.lower().strip()
    
    # Female indicators
    female_patterns = [
        "mst", "mosammat", "most", "mowsumi", "akter", "akteri", "begum", "khatun", "sultana",
        "jahan", "nahar", "farzana", "sumaiya", "ruma", "shampa", "sadia", "nusrat", "mim",
        "tania", "afrin", "tasnim", "nargis", "salma", "parvin", "fatema", "marufa", "mousumi",
        "monira", "sharmin", "afsana", "morium", "khadiza", "ayesha", "khaleda", "tamanna",
        "sonia", "sabina", "swapna", "shirin", "lima", "shila", "nazma", "papia", "shahnaz",
        "আক্তার", "বেগম", "খাতুন", "সুলতানা", "জাহান", "নাহার", "ফারজানা", "সুমাইয়া", "রুমা",
        "সাদিয়া", "নুসরাত", "মিম", "তানিয়া", "মোসাম্মৎ", "মমতাজ", "সালমা", "পারভীন", "ফাতেমা",
        "সোনিয়া", "সাবিনা", "স্বপ্না", "শিরিন", "লিমা", "শীলা", "নাজমা", "পাপিয়া", "শাহনাজ"
    ]
    if any(fp in name_lower for fp in female_patterns):
        return "আপু"
        
    # Male indicators
    male_patterns = [
        "md", "mohammad", "muhammad", "ahmed", "ahmad", "khan", "hasan", "hossain", "islam",
        "rahman", "chowdhury", "tanvir", "sakib", "rakib", "rony", "alamin", "faruk", "rasel",
        "shuvo", "sabbir", "tareq", "mahmud", "arafat", "ashik", "arif", "habib", "nazmul",
        "jewel", "sohel", "saiful", "kawsar", "mizan", "kamrul", "rashed", "shahadat",
        "ripon", "kabir", "jamal", "kamal", "babul", "monir", "farid", "rubel", "jahid",
        "মোঃ", "মোহাম্মদ", "আহমেদ", "খান", "হাসান", "হোসেন", "ইসলাম", "রহমান", "চৌধুরী",
        "তানভীর", "সাকিব", "রাকিব", "রনি", "আলআমিন", "ফারুক", "রাসেল", "শুভ", "সাব্বির",
        "রিপন", "কবির", "জামাল", "কামাল", "বাবুল", "মনির", "ফরিদ", "রুবেল", "জাহিদ"
    ]
    if any(mp in name_lower for mp in male_patterns):
        return "ভাইয়া"
        
    return "স্যার/ম্যাম"

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

def build_system_instruction(customer_name: str = "") -> str:
    """Builds the natural, human-like system prompt for RS Graphics sales agent."""
    all_settings = get_all_settings()
    shop_name = all_settings.get("shop_name", "RS Graphics")
    inside_fee = all_settings.get("delivery_inside_dhaka", str(settings.DELIVERY_FEE_INSIDE_DHAKA))
    outside_fee = all_settings.get("delivery_outside_dhaka", str(settings.DELIVERY_FEE_OUTSIDE_DHAKA))
    catalog = get_product_catalog_context()
    
    honorific = detect_customer_gender_title(customer_name)

    # Load in-app custom training rules from database
    training_rules = get_active_training_rules()
    training_text = ""
    if training_rules:
        training_text = "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🧠 অ্যাডমিন কর্তৃক নির্ধারিত স্পেশাল ট্রেইনিং রুলস (Custom Training Rules):\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for r in training_rules:
            trigger = f" (যদি কাস্টমার বলে: '{r['question_or_trigger']}')" if r.get('question_or_trigger') else ""
            training_text += f"• [{r.get('category', 'Rule')}] {r['title']}{trigger}: {r['response_or_rule']}\n"

    prompt = f"""
তুমি হচ্ছো '{shop_name}' (আরএস গ্রাফিক্স) পেজের একজন অত্যন্ত অভিজ্ঞ, প্রফেশনাল, অমায়িক ও চৌকস সেলস কনসালট্যান্ট ও বিজনেস ম্যানেজার।
আমাদের হটলাইন ও হোয়াটসঅ্যাপ নম্বর: 01816-504097, 01511504097

আমাদের মূল কাজ হলো প্রিমিয়াম কোয়ালিটি আইডি কার্ড (Japanese UV Print PVC), ডিজিটাল সাবলিমেশন ফিতা (Lanyards / Ribbons), আইডি কার্ড কভার (Card Holders), এবং কম্বো প্যাকেজ প্রিন্ট ও ডেলিভারি করা।

⚠️ STRICT HUMAN PERSONA RULE:
কাস্টমার যেন কোনোভাবেই বুঝতে না পারে যে তুমি রোবট বা এআই। তোমাকে কথা বলতে হবে একজন বাস্তব অভিজ্ঞ ও অমায়িক ব্যবসায়ীর মতো। কোনো রোবোটিক ঘোষণা বা এআই পরিচয় দেবে না।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 অত্যন্ত গুরুত্বপূর্ণ সেলস ও বিহেভিয়ার রুলস (Strict Rules):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

১. সংক্ষিপ্ত ও টু-দ্য-পয়েন্ট উত্তর (Strict Conciseness Rule):
   - কাস্টমার যতটুকু প্রশ্ন করবে শুধু ততটুকুরই উত্তর দেবে। কোনো অপ্রয়োজনীয় বড় রচনা বা দীর্ঘ প্যারাগ্রাফ লিখবে না।
   - কাস্টমারের নাম ও সম্মান অনুযায়ী সম্বোধন করবে: {honorific}।
   - ⚠️ কখনোই রূঢ় বা কর্কশ ভাষা ব্যবহার করবে না। সবসময় বিনম্র, আন্তরিক ও প্রফেশনাল থাকবে।
   - প্রতি মেসেজে বারবার "আসসালামু আলাইকুম" বা অযথা ভূমিকা টানবে না। চ্যাটের শুরুতে শুধু একবার সালাম বা সাধারণ সম্ভাষণ হতে পারে।

২. গোপনীয়তা ও মূল্য নির্ধারণ নীতি (Pricing & Cost Protection):
   - ⚠️ কখনোই আমাদের কেনা দাম / নিজস্ব উৎপাদন খরচ বলবে না। সর্বদা বিক্রয়মূল্য (সেল প্রাইস) বলবে।
   - শুরুতেই আগ বাড়িয়ে ডিসকাউন্ট বা অফারের কথা বলবে না। প্রথমে মূল নিয়মিত দাম বলবে।
   - যদি কাস্টমার ৫০ বা ১০০+ পিস বানাতে চায় অথবা সরাসরি ডিসকাউন্ট চায় ("কিছু কম রাখা যাবে কি?"), তখন স্পেশাল হোলসেল রেট অফার করবে।

৩. কোয়ান্টিটি ও প্যাকেজ রুল (MOQ & Quantity Tier):
   - কাস্টমার দাম জিজ্ঞাসা করলে সরাসরি একক দাম না বলে প্রথমে জিজ্ঞাসা করবে:
     👉 "জি {honorific}, কত পিস বানাবেন জানাবেন প্লিজ?"
   - আমাদের ন্যূনতম অর্ডার পরিমাণ (MOQ) হলো ২০ পিস। ২০ পিসের কম অর্ডার নেওয়া হয় না।
   - ২০-৫০ পিসের জন্য আমাদের প্যাকেজ রেট:
     • সিঙ্গেল আইডি কার্ড (শুধু কার্ড): ৩৫ টাকা / পিস (অফার মূল্য ৩০ টাকা)
     • প্যাকেজ ০১: জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল ফিতা (১.৫ সেমি) + প্লাস্টিক কভার (স্বচ্ছ)
     • প্যাকেজ ০২: জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল ফিতা (১.৫ সেমি) + কালারফুল প্লাস্টিক কভার
     • প্যাকেজ ০৩: জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল ফিতা (২ সেমি) + হার্ড প্লাস্টিক কভার
     • প্যাকেজ ০৭: জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল ফিতা (২ সেমি) + প্রিমিয়াম মেটাল লক কভার

৪. স্যাম্পল ছবি পাঠানোর নিয়ম (Sample Image Protocol):
   - কাস্টমার যদি সরাসরি ছবি বা স্যাম্পল দেখতে চায় (যেমন: "আইডি কার্ডের কিছু ছবি দিন", "ছবি দেখতে চাই", "স্যাম্পল দেন", "ফিতার ছবি পাঠান"), তখন সরাসরি সংক্ষিপ্ত উত্তর দিয়ে জানাবে যে নিচে ছবিগুলো পাঠানো হলো। যেমন:
     👉 "জি {honorific}, নিচে আমাদের জাপানি UV প্রিন্ট আইডি কার্ডের স্যাম্পল ছবিগুলো দেওয়া হলো। দয়া করে দেখুন।"
   - যদি কাস্টমার শুধু সাধারণ মূল্য বা বিবরণ জানতে চায় (ছবি চায়নি), তবে প্রথমে তথ্য জানিয়ে বিনয়ের সাথে অনুমতি চেয়ে বলবে:
     👉 "আমি কি আমাদের কিছু স্যাম্পল ছবি পাঠাবো?"
   - ⚠️ কোনো মার্কডাউন ইমেজ ট্যাগ যেমন `![Alt](/static/...)` টেক্সটে লিখবে না। আসল ছবিগুলো সিস্টেম স্বয়ংক্রিয়ভাবে পাঠাবে।

৫. শপের ইনফরমেশন:
   - ডেলিভারি চার্জ: ঢাকার ভেতরে {int(float(inside_fee))} টাকা এবং ঢাকার বাইরে {int(float(outside_fee))} টাকা।
   - ক্যাশ অন ডেলিভারি সুবিধা রয়েছে। সারা বাংলাদেশে কুরিয়ারে ২-৩ কার্যদিবসে ডেলিভারি সম্পন্ন হয়।

৬. প্রডাক্ট ক্যাটালগ:
{catalog}
{training_text}

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

৮. কাস্টমারের ভয়েস মেসেজ প্রসেসিং রুল (Voice Notes Processing):
   - কাস্টমার অডিও বা ভয়েস মেসেজ পাঠালে তা স্বয়ংক্রিয়ভাবে শুনে ও বুঝে কাস্টমারের বক্তব্যের সরাসরি সঠিক উত্তর দেবে।
   - ⚠️ কখনোই কাস্টমারকে বলবে না "ভয়েস মেসেজ পেয়েছি, টাইপ করে জানান" বা "আমি কি আপনার ভয়েসটি শুনে উত্তর দেবো?"।
   - কাস্টমার ভয়েসে যা বলেছে তার সরাসরি স্বাভাবিক ও প্রফেশনাল উত্তর দেবে।

৯. অজানা বিষয়ের উত্তর বানিয়ে না বলা (Strict Anti-Hallucination):
   - যে পণ্য, সেবা, দাম বা পলিসি সম্পর্কে তোমার ক্যাটালগ বা দেওয়া তথ্যে কোনো উল্লেখ নেই, সে বিষয়ে নিজে থেকে কোনো মনগড়া বা কাল্পনিক উত্তর দেবে না।
   - সরাসরি ও বিনয়ের সাথে বলবে:
     👉 "জি {honorific}, এই বিষয়টি আমাদের টিমকে জানিয়েছি। কিছুক্ষণের মধ্যে আমাদের টিম আপনার সাথে যোগাযোগ করে সঠিক তথ্যটি জানিয়ে দেবে। অনুগ্রহ করে একটু সময় দিন।"

১০. পূর্ববর্তী ওনার ইন্টারঅ্যাকশন ও সতর্কতা (Previous Owner Interaction):
   - যদি চ্যাট হিস্ট্রিতে দেখা যায় যে ইতিপূর্বে পেজের ওনার বা কোনো প্রতিনিধি সরাসরি কথা বলেছেন, তাহলে নিজে থেকে অযথা বড় সেলস পিচ বা অতিরিক্ত কথা বলতে যাবে না। সংক্ষিপ্ত ও বিনম্র উত্তর দেবে অথবা বলবে:
     👉 "জি {honorific}, আপনার বার্তাটি পেয়েছি। আমাদের প্রতিনিধি খুব দ্রুতই আপনার সাথে যোগাযোগ করছেন, অনুগ্রহ করে একটু অপেক্ষা করুন।"
"""
    return prompt

def get_category_batch_images(category_or_code: str, max_count: int = 4) -> list:
    """Returns a curated batch of 3-4 sample gallery images for a specific product category."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code, name, image_url, gallery_images FROM products WHERE is_active = 1")
    products = cursor.fetchall()
    conn.close()

    images = []
    for p in products:
        p_code = p["code"]
        if category_or_code and (category_or_code.lower() in p_code.lower() or category_or_code.lower() in p["name"].lower()):
            if p["image_url"] and p["image_url"] not in images:
                images.append(p["image_url"])
            try:
                g_imgs = json.loads(p["gallery_images"] or "[]")
                for gu in g_imgs:
                    if gu and gu not in images:
                        images.append(gu)
            except Exception:
                pass
    # Return at most max_count (3-4) curated images to avoid spamming the customer
    return images[:max_count]

def detect_sample_photos_to_send(user_msg: str, conversation_history: list = None, bot_reply: str = "") -> list:
    """
    Robust detection for sending category sample photos.
    Triggers if user directly asks for photos, confirms previous bot offer, or bot reply states photos are sent.
    STOPS immediately if customer indicates they don't want more photos.
    """
    msg = (user_msg or "").strip().lower()
    reply = (bot_reply or "").strip().lower()

    # 1. Stop / Cancellation check (Never send photos if customer says "আর লাগবে না", "না", "থামুন", etc.)
    stop_phrases = [
        "লাগবে না", "আর লাগবে না", "থামুন", "আর দিয়েন না", "আর পাঠাবেন না", 
        "ছবি লাগবে না", "ফটো লাগবে না", "আর না", "চাই না", "আর দিও না",
        "stop", "no more", "don't send", "dont send"
    ]
    msg_words = msg.split()
    is_stopping = any(sp in msg for sp in stop_phrases) or (len(msg_words) == 1 and msg_words[0] in ["না", "no"])
    if is_stopping:
        return []

    # 2. Direct photo request keywords
    is_asking_photo = any(k in msg for k in [
        "ছবি", "স্যাম্পল", "ফটো", "পিক", "পিকচার", "ফটোগ্রাফ", "দেখতে চাই", "দেখবো",
        "photo", "photos", "picture", "pictures", "sample", "samples", "pic", "pics", "image", "images"
    ])

    # 3. Agreement / confirmation keywords
    agreement_keywords = [
        "হ্যাঁ", "পাঠান", "দেখান", "জি", "হুম", "পাঠাও", "দেখাও", "দিলে ভালো", "দিলে ভালো হয়",
        "yes", "sure", "ok", "okay", "send", "show", "ha", "ji", "achha", "yep", "yeah", "সেন্ড করুন"
    ]
    is_agreeing = any(k in msg for k in agreement_keywords)

    # 4. Check if bot reply explicitly mentions sending photos
    bot_claims_photos = any(k in reply for k in [
        "পাঠিয়ে দেওয়া হলো", "পাঠানো হলো", "ছবি দেওয়া হলো", "স্যাম্পল ছবি", "নিচে দেখুন", "পাঠিয়েছি", "ছবি পাঠাচ্ছি"
    ])

    should_send = is_asking_photo or is_agreeing or bot_claims_photos
    if not should_send:
        return []

    # Combined context for category detection
    hist_text = " ".join([m.get("content", "") for m in (conversation_history or [])[-4:]]).lower()
    context = (hist_text + " " + msg + " " + reply).lower()

    if any(k in context for k in ["ফিতা", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]):
        batch = get_category_batch_images("FITA-02", max_count=4)
        return batch if batch else get_category_batch_images("IDC-01", max_count=4)
    elif any(k in context for k in ["কভার", "হোল্ডার", "holder", "cover"]):
        batch = get_category_batch_images("COV-03", max_count=4)
        return batch if batch else get_category_batch_images("IDC-01", max_count=4)
    elif any(k in context for k in ["প্যাকেজ", "কম্বো", "package", "combo"]):
        batch = get_category_batch_images("PKG-COMBO", max_count=4)
        return batch if batch else get_category_batch_images("IDC-01", max_count=4)
    else:
        # Default category: ID Card sample batch
        return get_category_batch_images("IDC-01", max_count=4)

def generate_smart_fallback_reply(user_msg: str, customer_name: str = "") -> str:
    """Generates an intelligent context-aware reply if Gemini API is unreachable or rate-limited."""
    msg = (user_msg or "").strip().lower()
    honorific = detect_customer_gender_title(customer_name)

    if any(k in msg for k in ["লাগবে না", "আর লাগবে না", "না", "stop", "no"]):
        return f"জি {honorific}, ঠিক আছে। আপনার আর কোনো তথ্য বা অর্ডার সংক্রান্ত সহযোগিতা প্রয়োজন হলে জানাবেন প্লিজ।"
    
    if any(k in msg for k in ["ফিতা", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
        return f"জি {honorific}, নিচে আমাদের ডিজিটাল সাবলিমেশন ফিতার কিছু স্যাম্পল ছবি দেওয়া হলো। আপনার কত পিস ফিতা প্রয়োজন জানাবেন প্লিজ?"

    if any(k in msg for k in ["আইডি", "কার্ড", "id card"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
        return f"জি {honorific}, নিচে আমাদের জাপানি UV প্রিন্ট আইডি কার্ডের কিছু স্যাম্পল ছবি দেওয়া হলো। আপনার কত পিস আইডি কার্ড প্রয়োজন জানাবেন প্লিজ?"

    if any(k in msg for k in ["ফিতা", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]):
        return f"জি {honorific}, আমাদের প্রিমিয়াম কোয়ালিটি ডিজিটাল সাবলিমেশন ফিতা (১.৫ ও ২ সেমি) প্রিন্ট করা হয়। কত পিস প্রয়োজন জানাবেন প্লিজ?"

    if any(k in msg for k in ["দাম", "রেট", "মূল্য", "price", "cost"]):
        return f"জি {honorific}, আমাদের জাপানি মেশিনের UV প্রিন্ট আইডি কার্ডের রেগুলার মূল্য ৩৫ টাকা (অফার মূল্য ৩০ টাকা)। কত পিস বানাবেন জানাবেন প্লিজ? (মিনিমাম অর্ডার ২০ পিস)।"

    if any(k in msg for k in ["ডেলিভারি", "কুরিয়ার", "delivery"]):
        return f"জি {honorific}, ডেলিভারি চার্জ ঢাকার ভেতরে ৭০ টাকা এবং ঢাকার বাইরে ১৩০ টাকা। ক্যাশ অন ডেলিভারি সুবিধা রয়েছে।"

    return f"জি {honorific}, আসসালামু আলাইকুম! আমাদের জাপানি UV প্রিন্ট আইডি কার্ড, ডিজিটাল ফিতা ও কভারের প্রিমিয়াম প্রিন্টিং সেবা রয়েছে। আপনি কত পিস বানাতে চান জানাবেন প্লিজ?"

async def process_customer_message(
    message_text: str = "",
    image_bytes: bytes = None,
    image_mime: str = "image/jpeg",
    audio_bytes: bytes = None,
    audio_mime: str = "audio/mp3",
    conversation_history: list = None,
    channel: str = "facebook",
    sender_id: str = "web_user",
    customer_name: str = "Customer",
    generate_voice_reply: bool = False
) -> dict:
    """
    Multimodal message processing via Google GenAI.
    Handles text, images, voice notes, gender recognition, and batch sample delivery.
    """
    api_key = get_setting("gemini_api_key", settings.GEMINI_API_KEY)
    
    # Check if API key is provided
    if not api_key:
        fallback_reply = generate_smart_fallback_reply(message_text, customer_name)
        return {
            "reply_text": fallback_reply,
            "voice_url": "",
            "order_created": None,
            "matched_images": detect_sample_photos_to_send(message_text, conversation_history, fallback_reply)
        }

    try:
        client = genai.Client(api_key=api_key)
        contents = []
        
        # Add conversation history (up to last 8 turns)
        if conversation_history:
            history_text = "[পূর্ববর্তী চ্যাট হিস্ট্রি]:\n"
            for msg in conversation_history[-8:]:
                role = "কাস্টমার" if msg.get("sender_type") == "user" else "সেলস ম্যানেজার"
                history_text += f"{role}: {msg.get('content', '')}\n"
            contents.append(history_text)

        # Add image attachment
        if image_bytes:
            contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime))
            if not message_text:
                message_text = "আমি এই ছবিটি পাঠিয়েছি। এই প্রডাক্ট বা ছবি দেখে বিস্তারিত জানান।"

        # Add audio attachment (Voice Note)
        if audio_bytes:
            detected_audio_mime = audio_mime or "audio/mp4"
            if audio_bytes.startswith(b"RIFF"):
                detected_audio_mime = "audio/wav"
            elif audio_bytes.startswith(b"OggS"):
                detected_audio_mime = "audio/ogg"
            elif audio_bytes.startswith(b"\xff\xfb") or audio_bytes.startswith(b"\xff\xf3") or audio_bytes.startswith(b"ID3"):
                detected_audio_mime = "audio/mp3"
            elif b"ftyp" in audio_bytes[:20] or b"M4A" in audio_bytes[:20]:
                detected_audio_mime = "audio/mp4"

            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=detected_audio_mime))
            if not message_text:
                message_text = "কাস্টমার একটি অডিও/ভয়েস মেসেজ পাঠিয়েছেন। অডিওটি শুনুন এবং কাস্টমার যা বলেছেন তার সরাসরি সঠিক ও সংক্ষিপ্ত উত্তর দিন।"

        if message_text:
            contents.append(f"কাস্টমারের মেসেজ ({customer_name}): {message_text}")

        # Prioritize high-quota active working models
        candidate_models = [
            "gemini-3.6-flash",
            "gemini-3.5-flash-lite",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-2.5-flash"
        ]

        response = None
        system_instruction = build_system_instruction(customer_name=customer_name)

        for m_name in candidate_models:
            try:
                response = client.models.generate_content(
                    model=m_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.6
                    )
                )
                if response and response.text:
                    set_setting("gemini_model", m_name)
                    break
            except Exception as model_err:
                print(f"[Gemini Model {m_name} failed]: {model_err}")
                continue

        raw_text = response.text if response and response.text else generate_smart_fallback_reply(message_text, customer_name)

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
                            customer_name=order_data.get("customer_name", customer_name or "Customer"),
                            customer_phone=phone,
                            customer_address=order_data.get("customer_address", "Dhaka"),
                            items=order_data.get("items", []),
                            channel=channel,
                            sender_id=sender_id,
                            notes=order_data.get("notes", "")
                        )
            except Exception as e:
                print(f"[Order Parse Error]: {e}")

        # Clean markdown image tags & bracket tags from text
        matched_images = []
        md_img_matches = re.findall(r'!\[([^\]]*)\]\(([^)]+)\)', clean_reply)
        for alt, url in md_img_matches:
            u = url.strip()
            if u and u not in matched_images:
                matched_images.append(u)

        # Clean raw /static/uploads/... links from text if Gemini printed them
        raw_urls = re.findall(r'/static/uploads/\S+', clean_reply)
        for u in raw_urls:
            u_clean = u.strip().rstrip(").,'\"")
            if u_clean and u_clean not in matched_images:
                matched_images.append(u_clean)

        clean_reply = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', clean_reply)
        clean_reply = re.sub(r'\[Image[s]?:\s*[^\]]+\]', '', clean_reply, flags=re.IGNORECASE)
        clean_reply = re.sub(r'/static/uploads/\S+', '', clean_reply)
        clean_reply = re.sub(r'\n{3,}', '\n\n', clean_reply).strip()

        # Detect sample photos to send
        sample_batch = detect_sample_photos_to_send(
            user_msg=message_text,
            conversation_history=conversation_history,
            bot_reply=clean_reply
        )
        if sample_batch:
            matched_images = sample_batch

        # Strictly cap sample photos to 4 max to prevent chat flooding
        matched_images = matched_images[:4]

        return {
            "reply_text": clean_reply,
            "voice_url": "",
            "order_created": order_created,
            "matched_images": matched_images
        }

    except Exception as e:
        print(f"[GeminiBrain Error]: {e}")
        err_msg = generate_smart_fallback_reply(message_text, customer_name)
        return {
            "reply_text": err_msg,
            "voice_url": "",
            "order_created": None,
            "matched_images": detect_sample_photos_to_send(message_text, conversation_history, err_msg)
        }
