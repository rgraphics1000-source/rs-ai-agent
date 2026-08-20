import os
import json
import re
import base64
from pathlib import Path
from typing import Optional, List, Dict, Any
from google import genai
from google.genai import types

from app.config import settings
from app.database import (
    get_db_connection, get_setting, set_setting, get_all_settings, 
    get_active_training_rules, get_saved_media
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
    """Fetches active products from DB to feed into Gemini prompt with individual variation prices."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, code, price, discount_price, stock, category, description, image_url, gallery_images FROM products WHERE is_active = 1")
    products = cursor.fetchall()
    conn.close()

    if not products:
        return "বর্তমানে কোনো প্রডাক্ট ডাটাবেজে যুক্ত নেই।"

    lines = ["📦 আমাদের স্টোরের বর্তমান প্রডাক্ট ক্যাটালগ ও প্রতিটি ছবির আলাদা মূল্য তালিকা:"]
    for p in products:
        price = p["discount_price"] if p["discount_price"] and p["discount_price"] < p["price"] else p["price"]
        old_price = f" (আগের দাম: {p['price']}৳)" if p["discount_price"] and p["discount_price"] < p["price"] else ""
        stock_status = f"স্টক: {p['stock']} টি" if p['stock'] > 0 else "স্টক আউট"
        
        lines.append(f"\n• [{p['code']}] {p['name']} (বেস রেট: {price}৳{old_price} | {stock_status}):\n  বিবরণ: {p['description']}")
        
        try:
            raw_gallery = json.loads(p["gallery_images"] or "[]")
            if raw_gallery:
                for idx, item in enumerate(raw_gallery):
                    if isinstance(item, dict):
                        v_title = item.get("title", f"ভ্যারিয়েশন {idx+1}")
                        v_price = item.get("price") or price
                        v_url = item.get("url", "")
                        lines.append(f"  - {v_title}: {v_price}৳ [Image: {v_url}]")
                    elif isinstance(item, str) and item.strip():
                        lines.append(f"  - ছবি {idx+1}: [Image: {item.strip()}]")
        except Exception:
            pass
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

০. ভয়েস মেসেজের সরাসরি উত্তর দেওয়ার কঠোর নিয়ম (Voice Message Direct Answering):
   - কাস্টমার ভয়েস মেসেজ পাঠালে অডিওটি মনোযোগ দিয়ে শুনে কাস্টমার যা জানতে চেয়েছেন তার সরাসরি ও তাৎক্ষণিক উত্তর দেবে।
   - 🚫 সম্পূর্ণ নিষিদ্ধ বাক্য (STRICTLY FORBIDDEN):
     • কখনোই বলবে না: "টাইপ করে দিলে ভালো হয়", "টাইপ করে দিন", "ভয়েস বুঝতে পারছি না", "টেক্সট করে জানান"। এ ধরনের কথা বলা সম্পূর্ণ নিষেধ! ভয়েস শুনে সাথে সাথে সরাসরি উত্তর দেবে।
     • কখনোই বলবে না: "আপনার ভয়েস মেসেজটি পেয়েছি", "ভয়েস মেসেজের জন্য ধন্যবাদ"। কোনো রোবোটিক রিসিভ ঘোষণা দেবে না!
     • কাস্টমার যদি ভয়েসে বা টেক্সটে ছবি/স্যাম্পল দেখতে চায়, অনুমতি চাইতে যাবে না (যেমন: "আমি কি আমাদের কিছু স্যাম্পল ছবি পাঠাবো?"—এ কথা কখনোই বলবে না)। সরাসরি বলবে: "জি {honorific}, নিচে আমাদের আকর্ষণীয় স্যাম্পল ছবিগুলো দেওয়া হলো।" এবং সকল ছবি সেন্ড করবে।

১. স্মৃতিশক্তি ও পূর্ববর্তী কথোপকথন মনে রাখা (Strict Multi-Turn Memory):
   - কাস্টমার চ্যাটের যেকোনো পর্যায়ে আগে যা যা বলেছেন (যেমন: কাস্টমারের নাম, মোবাইল নম্বর, ঠিকানা, কত পিস পণ্য লাগবে বা কোন প্যাকেজ পছন্দ করেছেন), তা এআই-কে সম্পূর্ণ মনে রাখতে হবে।
   - ⚠️ STRICT NO-REPETITION RULE: কাস্টমার যেসব তথ্যের উত্তর ইতিপূর্বে দিয়ে দিয়েছেন, সেই একই কথা বা প্রশ্ন (যেমন: "কত পিস লাগবে?", "ফোন নম্বর দিন", "আপনার নাম কী?") কখনোই পুনরায় কাস্টমারকে জিজ্ঞাসা করবে না!
   - কাস্টমারের পূর্বের বক্তব্যের সূত্র ধরেই স্বাভাবিকভাবে কথা এগিয়ে নেবে।

২. সংক্ষিপ্ত ও টু-দ্য-পয়েন্ট উত্তর (Strict Conciseness Rule):
   - কাস্টমার যতটুকু প্রশ্ন করবে শুধু ততটুকুরই উত্তর দেবে। কোনো অপ্রয়োজনীয় বড় রচনা বা দীর্ঘ প্যারাগ্রাফ লিখবে না।
   - কাস্টমারের নাম ও সম্মান অনুযায়ী সম্বোধন করবে: {honorific}।
   - ⚠️ কখনোই রূঢ় বা কর্কশ ভাষা ব্যবহার করবে না। সবসময় বিনম্র, আন্তরিক ও প্রফেশনাল থাকবে।
   - প্রতি মেসেজে বারবার "আসসালামু আলাইকুম" বা অযথা ভূমিকা টানবে না। চ্যাটের শুরুতে শুধু একবার সালাম বা সাধারণ সম্ভাষণ হতে পারে।

৩. গোপনীয়তা ও মূল্য নির্ধারণ নীতি (Pricing & Individual Photo Rates):
   - ⚠️ কখনোই আমাদের কেনা দাম / নিজস্ব উৎপাদন খরচ বলবে না। সর্বদা বিক্রয়মূল্য (সেল প্রাইস) বলবে।
   - শুরুতেই আগ বাড়িয়ে অতিরিক্ত ডিসকাউন্টের কথা বলবে না। প্রথমে মূল নিয়মিত দাম বলবে।
   - প্রতিটি প্যাকেজ ও ভ্যারিয়েশনের নির্দিষ্ট মূল্য রয়েছে:
     • প্যাকেজ ০১: ৭০৳ (UV কার্ড + ১.৫ সেমি ফিতা + স্বচ্ছ প্লাস্টিক কভার)
     • প্যাকেজ ০২: ৭০৳ (UV কার্ড + ১.৫ সেমি ফিতা + কালারফুল কভার)
     • প্যাকেজ ০৩: ৮৩৳ (UV কার্ড + ২ সেমি ফিতা + প্রিমিয়াম হার্ড প্লাস্টিক কভার)
     • প্যাকেজ ০৭: ৯১৳ (UV কার্ড + ২ সেমি ফিতা + মেটাল লক প্রিমিয়াম কভার সেট)
     • সিঙ্গেল আইডি কার্ড (শুধু কার্ড): ৩৫ টাকা (অফার মূল্য ৩০ টাকা)
   - যদি কাস্টমার ৫০ বা ১০০+ পিস বানাতে চায় অথবা সরাসরি ডিসকাউন্ট চায় ("কিছু কম রাখা যাবে কি?"), তখন স্পেশাল হোলসেল রেট অফার করবে।

৪. কোয়ান্টিটি ও প্যাকেজ রুল (MOQ & Quantity Tier):
   - কাস্টমার দাম জিজ্ঞাসা করলে যদি পূর্বে কোয়ান্টিটি না বলে থাকে, তখন জিজ্ঞাসা করবে:
     👉 "জি {honorific}, কত পিস বানাবেন জানাবেন প্লিজ?"
   - আমাদের ন্যূনতম অর্ডার পরিমাণ (MOQ) হলো ২০ পিস। ২০ পিসের কম অর্ডার নেওয়া হয় না।

৫. স্যাম্পল ছবি ও ক্যাটাগরি প্রটোকল (Strict Category Matching & Image Delivery):
   - কাস্টমার যে জিনিসের ছবি চাইবে, ঠিক সেই জিনিসের ছবিই পাঠাতে হবে:
     • কাস্টমার "প্যাকেজ / কম্বো" চাইলে প্যাকেজের ছবি দিতে হবে (কখনোই ফিতার ছবি দেবে না)।
     • কাস্টমার "ফিতা / লেইনিয়ার্ড" চাইলে শুধু ফিতার ছবি দিতে হবে।
     • কাস্টমার "কভার / হোল্ডার" চাইলে শুধু কভারের ছবি দিতে হবে।
     • কাস্টমার "আইডি কার্ড" চাইলে শুধু আইডি কার্ডের ছবি দিতে হবে।
   - কাস্টমার যদি বলে "২-৩টা ছবি দিন", তখন ২-৩টি ছবি পাঠানো হবে। যদি কাস্টমার বলে "সবগুলো ছবি দিন" বা কোনো সংখ্যা উল্লেখ না করে সরাসরি ছবি চায়, তবে সকল স্যাম্পল ছবি পাঠানো হবে।
   - টেক্সটে কোনো মার্কডাউন ইমেজ ট্যাগ যেমন `![Alt](/static/...)` লিখবে না। আসল ছবিগুলো সিস্টেম স্বয়ংক্রিয়ভাবে কাস্টমারের কাছে পৌঁছে দেবে।

৬. ডেমো ভিডিও ও প্রি-রেকর্ড করা ভয়েস নোট প্রটোকল (Demo Videos & Voice Clips):
   - কাস্টমার যদি আইডি কার্ড প্রিন্টিং বা প্রোডাক্টের ডেমো ভিডিও দেখতে চায় ("ভিডিও দেন", "ভিডিও দেখতে চাই"), তবে জানাবে যে ভিডিওটি নিচে পাঠানো হলো।
   - সিস্টেম স্বয়ংক্রিয়ভাবে আমাদের লাইব্রেরি থেকে ভিডিও ফাইল কাস্টমারকে পাঠিয়ে দেবে।

৭. শপের ডেলিভারি ইনফরমেশন:
   - ডেলিভারি চার্জ: ঢাকার ভেতরে {int(float(inside_fee))} টাকা এবং ঢাকার বাইরে {int(float(outside_fee))} টাকা।
   - ক্যাশ অন ডেলিভারি সুবিধা রয়েছে। সারা বাংলাদেশে কুরিয়ারে ২-৩ কার্যদিবসে ডেলিভারি সম্পন্ন হয়।

৮. প্রডাক্ট ক্যাটালগ ও মূল্য তালিকা:
{catalog}
{training_text}

৯. অর্ডার কনফার্মেশন:
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
    {{"name": "আইডি কার্ড কম্বো প্যাকেজ", "code": "PKG-COMBO", "qty": 100, "price": 70}}
  ],
  "notes": ""
}}
```

১০. অজানা বিষয়ের উত্তর বানিয়ে না বলা (Strict Anti-Hallucination):
   - যে পণ্য, সেবা বা পলিসি সম্পর্কে তোমার ক্যাটালগে কোনো উল্লেখ নেই, সে বিষয়ে নিজে থেকে কোনো মনগড়া উত্তর দেবে না।
   - সরাসরি ও বিনয়ের সাথে বলবে:
     👉 "জি {honorific}, এই বিষয়টি আমাদের টিমকে জানিয়েছি। কিছুক্ষণের মধ্যে আমাদের টিম আপনার সাথে যোগাযোগ করে সঠিক তথ্যটি জানিয়ে দেবে। অনুগ্রহ করে একটু সময় দিন।"
"""
    return prompt

def get_category_batch_images(category_or_code: str, requested_count: int = None) -> list:
    """
    Returns sample gallery images for a specific product category.
    If requested_count is specified (e.g. 2 or 3), returns that exact number.
    If requested_count is None, returns ALL available images for the category!
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code, name, image_url, gallery_images FROM products WHERE is_active = 1")
    products = cursor.fetchall()
    conn.close()

    images = []
    for p in products:
        p_code = p["code"]
        p_name = p["name"]
        if category_or_code and (category_or_code.lower() in p_code.lower() or category_or_code.lower() in p_name.lower()):
            try:
                g_imgs = json.loads(p["gallery_images"] or "[]")
                for gu in g_imgs:
                    img_url = gu.get("url") if isinstance(gu, dict) else gu
                    if img_url and img_url not in images:
                        images.append(img_url)
            except Exception:
                pass
            if p["image_url"] and p["image_url"] not in images:
                images.append(p["image_url"])

    if requested_count and requested_count > 0:
        return images[:requested_count]
    return images

def parse_requested_image_count(user_msg: str) -> Optional[int]:
    """Detects if user asked for a specific number of images (e.g., '২টি ছবি', '৩টা ছবি', '৪-৫টি ছবি')."""
    msg = (user_msg or "").lower()
    
    if any(k in msg for k in ["২-৩", "২টি", "২ টা", "২টা", "দুটো", "দুইটা", "দুই টি", "2টা", "2টি", "2"]):
        if "২-৩" in msg or "2-3" in msg:
            return 3
        return 2
    if any(k in msg for k in ["৩-৪", "৩টি", "৩ টা", "৩টা", "তিনটি", "তিনটা", "3টা", "3টি", "3"]):
        if "৩-৪" in msg or "3-4" in msg:
            return 4
        return 3
    if any(k in msg for k in ["৪টি", "৪ টা", "৪টা", "চারটি", "চারটা", "4টা", "4টি", "4"]):
        return 4
    if any(k in msg for k in ["৫টি", "৫ টা", "৫টা", "পাঁচটি", "পাঁচটা", "5টা", "5টি", "5"]):
        return 5
    if any(k in msg for k in ["১টি", "১ টা", "১টা", "একটা", "একটি", "1টা", "1টি"]):
        return 1
    return None

def detect_sample_photos_to_send(user_msg: str, conversation_history: list = None, bot_reply: str = "") -> list:
    """
    Robust detection for sending category sample photos with full category support.
    Extracts all requested photos across Package, ID Card, Ribbon, and Cover.
    """
    msg = (user_msg or "").strip().lower()
    reply = (bot_reply or "").strip().lower()
    hist_text = " ".join([m.get("content", "") for m in (conversation_history or [])[-3:]]).lower()

    # 1. Stop / Cancellation check
    stop_phrases = [
        "লাগবে না", "আর লাগবে না", "থামুন", "আর দিয়েন না", "আর পাঠাবেন না", 
        "ছবি লাগবে না", "ফটো লাগবে না", "আর না", "চাই না", "আর দিও না",
        "stop", "no more", "don't send", "dont send"
    ]
    msg_words = msg.split()
    is_stopping = any(sp in msg for sp in stop_phrases) or (len(msg_words) == 1 and msg_words[0] in ["না", "no"])
    if is_stopping:
        return []

    # 2. Check if photos are requested in user message, bot reply, or history
    is_asking_photo = any(k in msg for k in [
        "ছবি", "স্যাম্পল", "ফটো", "পিক", "পিকচার", "ফটোগ্রাফ", "দেখতে চাই", "দেখবো", "দেখান", "পাঠান", "পাঠাও", "দেখাও",
        "photo", "photos", "picture", "pictures", "sample", "samples", "pic", "pics", "image", "images", "সবগুলো"
    ])

    agreement_keywords = [
        "হ্যাঁ", "পাঠান", "দেখান", "জি", "হুম", "পাঠাও", "দেখাও", "দিলে ভালো", "দিলে ভালো হয়",
        "yes", "sure", "ok", "okay", "send", "show", "ha", "ji", "achha", "yep", "yeah", "সেন্ড করুন"
    ]
    is_agreeing = any(k in msg for k in agreement_keywords)
    
    bot_claims_photos = any(k in reply for k in [
        "পাঠিয়ে দেওয়া হলো", "পাঠানো হলো", "ছবি দেওয়া হলো", "স্যাম্পল ছবি", "নিচে দেখুন", 
        "পাঠিয়েছি", "ছবি পাঠাচ্ছি", "ছবি দেখতে চেয়েছেন", "স্যাম্পল পাঠাচ্ছি", "ছবিগুলো দেওয়া হলো"
    ])

    # If incoming was an audio voice note, always evaluate if bot detected photo request
    should_send = is_asking_photo or is_agreeing or bot_claims_photos
    if not should_send:
        return []

    req_count = parse_requested_image_count(msg) or parse_requested_image_count(reply)

    # Search across user message first, then bot reply, then history
    target_scope = f"{msg} {reply}"
    
    selected_images = []

    is_pkg = any(k in target_scope for k in ["প্যাকেজ", "কম্বো", "package", "combo", "পেকেজ", "সেট"])
    is_fita = any(k in target_scope for k in ["ফিতা", "রিবন", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"])
    is_cover = any(k in target_scope for k in ["কভার", "হোল্ডার", "holder", "cover"])
    is_id = any(k in target_scope for k in ["আইডি", "কার্ড", "id card", "card", "পিভিসি", "pvc"])

    # If specific category found in target_scope:
    if is_pkg:
        for u in get_category_batch_images("PKG-COMBO"):
            if u not in selected_images:
                selected_images.append(u)

    if is_fita:
        for u in get_category_batch_images("FITA-02"):
            if u not in selected_images:
                selected_images.append(u)

    if is_cover:
        for u in get_category_batch_images("COV-03"):
            if u not in selected_images:
                selected_images.append(u)

    if is_id and not is_pkg:
        # Only add stand-alone ID cards if package wasn't the only requested item
        for u in get_category_batch_images("IDC-01"):
            if u not in selected_images:
                selected_images.append(u)

    # Fallback to history if still empty
    if not selected_images:
        if any(k in hist_text for k in ["প্যাকেজ", "কম্বো", "package", "combo", "পেকেজ"]):
            selected_images = get_category_batch_images("PKG-COMBO")
        elif any(k in hist_text for k in ["ফিতা", "রিবন", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]):
            selected_images = get_category_batch_images("FITA-02")
        elif any(k in hist_text for k in ["কভার", "হোল্ডার", "holder", "cover"]):
            selected_images = get_category_batch_images("COV-03")
        else:
            selected_images = get_category_batch_images("PKG-COMBO")

    if req_count and req_count > 0:
        return selected_images[:req_count]
    return selected_images

def detect_saved_media_to_send(user_msg: str, bot_reply: str = "") -> dict:
    """Detects if customer requested a demo video or pre-recorded voice note."""
    msg = (user_msg or "").strip().lower()
    reply = (bot_reply or "").strip().lower()
    
    res = {"video_url": "", "voice_url": ""}
    
    # Check for video requests
    is_asking_video = any(k in msg for k in ["ভিডিও", "ভিডিও দেন", "ভিডিও দেখতে চাই", "ভিডিও পাঠান", "ডেমো ভিডিও", "প্রিন্টিং ভিডিও", "video", "demo video"])
    if is_asking_video:
        videos = get_saved_media("video")
        if videos:
            res["video_url"] = videos[0]["file_url"]
            
    # Check for voice requests
    is_asking_voice = any(k in msg for k in ["ভয়েস", "ভয়েস দেন", "অডিও", "রেকর্ডিং", "ভয়েসে বলেন", "voice", "audio"])
    if is_asking_voice:
        voices = get_saved_media("voice")
        if voices:
            res["voice_url"] = voices[0]["file_url"]
            
    return res

def generate_smart_fallback_reply(user_msg: str, customer_name: str = "") -> str:
    """Generates an intelligent context-aware reply if Gemini API is unreachable or rate-limited."""
    msg = (user_msg or "").strip().lower()
    honorific = detect_customer_gender_title(customer_name)

    if any(k in msg for k in ["লাগবে না", "আর লাগবে না", "না", "stop", "no"]):
        return f"জি {honorific}, ঠিক আছে। আপনার আর কোনো তথ্য বা অর্ডার সংক্রান্ত সহযোগিতা প্রয়োজন হলে জানাবেন প্লিজ।"
    
    if any(k in msg for k in ["প্যাকেজ", "কম্বো", "package", "combo"]):
        return f"জি {honorific}, আমাদের প্যাকেজ রেট: প্যাকেজ ০১ (৭০৳), প্যাকেজ ০২ (৭০৳), প্যাকেজ ০৩ (৮৩৳), প্যাকেজ ০৭ (৯১৳)। নিচে প্যাকেজের ছবি দেওয়া হলো।"

    if any(k in msg for k in ["ফিতা", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
        return f"জি {honorific}, নিচে আমাদের ডিজিটাল সাবলিমেশন ফিতার কিছু স্যাম্পল ছবি দেওয়া হলো। আপনার কত পিস ফিতা প্রয়োজন জানাবেন প্লিজ?"

    if any(k in msg for k in ["আইডি", "কার্ড", "id card"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
        return f"জি {honorific}, নিচে আমাদের জাপানি UV প্রিন্ট আইডি কার্ডের স্যাম্পল ছবিগুলো দেওয়া হলো। আপনার কত পিস আইডি কার্ড প্রয়োজন জানাবেন প্লিজ?"

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
        matched_imgs = detect_sample_photos_to_send(message_text, conversation_history, fallback_reply)
        media_found = detect_saved_media_to_send(message_text, fallback_reply)
        return {
            "reply_text": fallback_reply,
            "voice_url": media_found.get("voice_url", ""),
            "video_url": media_found.get("video_url", ""),
            "order_created": None,
            "matched_images": matched_imgs
        }

    try:
        client = genai.Client(api_key=api_key)
        contents = []
        
        # Add conversation history (up to last 15 turns for deep memory)
        if conversation_history:
            history_text = "[পূর্ববর্তী চ্যাট হিস্ট্রি - এটি সম্পূর্ণ মনে রেখে কথা বলবে]:\n"
            for msg in conversation_history[-15:]:
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
            detected_audio_mime = audio_mime or "audio/ogg"
            if audio_bytes.startswith(b"RIFF"):
                detected_audio_mime = "audio/wav"
            elif audio_bytes.startswith(b"OggS"):
                detected_audio_mime = "audio/ogg"
            elif audio_bytes.startswith(b"\xff\xfb") or audio_bytes.startswith(b"\xff\xf3") or audio_bytes.startswith(b"ID3"):
                detected_audio_mime = "audio/mp3"
            elif b"ftyp" in audio_bytes[:20] or b"M4A" in audio_bytes[:20]:
                detected_audio_mime = "audio/mp4"

            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=detected_audio_mime))
            message_text = "কাস্টমার একটি ভয়েস অডিও বার্তা পাঠিয়েছেন। অডিওটি মনোযোগ দিয়ে শুনুন এবং কাস্টমার যা বলেছেন/চেয়েছেন (যেমন পণ্যের দাম, ছবি, বিবরণ বা অর্ডার) তার সরাসরি সঠিক ও সংক্ষিপ্ত উত্তর দিন। কখনোই কাস্টমারকে 'টাইপ করে দিন' বা 'ভয়েস পেয়েছি' বলবেন না।"

        if message_text:
            contents.append(f"কাস্টমারের বার্তা ({customer_name}): {message_text}")

        # Prioritize high-quota active working models
        candidate_models = [
            "gemini-2.5-flash",
            "gemini-flash-latest",
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash"
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
                        temperature=0.5
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

        # Detect sample photos to send
        sample_batch = detect_sample_photos_to_send(
            user_msg=message_text,
            conversation_history=conversation_history,
            bot_reply=clean_reply
        )
        if sample_batch:
            matched_images = sample_batch

        # Clean robotic voice acknowledgement and asking for type
        clean_reply = re.sub(r'^(জি\s+)?(ভাইয়া|আপু|স্যার|ম্যাম)?[,\s]*আপনার\s+ভয়েস\s+(মেসেজটি|বার্তাটি)?\s*(পেয়েছি|শুনেছি)[।,\.\s]*', '', clean_reply, flags=re.IGNORECASE)
        clean_reply = re.sub(r'আপনার\s+ভয়েস\s+(মেসেজটি|বার্তাটি)?\s*(পেয়েছি|শুনেছি)[।,\.\s]*', '', clean_reply, flags=re.IGNORECASE)
        clean_reply = re.sub(r'ভয়েস\s+মেসেজের\s+জন্য\s+ধন্যবাদ[।,\.\s]*', '', clean_reply, flags=re.IGNORECASE)
        clean_reply = re.sub(r'(একটু\s+)?টাইপ\s+করে\s+(দিলে|দিতেন|দিন)[^\n।]*', '', clean_reply, flags=re.IGNORECASE)

        # If sample images are being sent, eliminate redundant question 'আমি কি স্যাম্পল পাঠাবো?'
        if matched_images:
            clean_reply = re.sub(r'আমি\s+কি\s+(আমাদের\s+)?(কিছু\s+)?স্যাম্পল\s+(ছবি\s+)?পাঠাবো\??', '', clean_reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'কিছু\s+স্যাম্পল\s+ছবি\s+পাঠাবো\??', '', clean_reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'ছবি\s+পাঠাবো\s+কি\??', '', clean_reply, flags=re.IGNORECASE)
            clean_reply = re.sub(r'আমি\s+কি\s+ছবি\s+পাঠাতে\s+পারি\??', '', clean_reply, flags=re.IGNORECASE)

        clean_reply = re.sub(r'\n{3,}', '\n\n', clean_reply).strip()

        # If clean_reply became too brief after cleaning, provide polite human greeting
        if not clean_reply or len(clean_reply) < 6:
            honorific = detect_customer_gender_title(customer_name)
            if matched_images:
                clean_reply = f"জি {honorific}, নিচে আমাদের আকর্ষণীয় স্যাম্পল ছবিগুলো পাঠানো হলো। আপনার কত পিস প্রয়োজন জানাবেন প্লিজ।"
            else:
                clean_reply = f"জি {honorific}, আমাদের প্রডাক্ট ও অর্ডার সম্পর্কে যেকোনো তথ্য প্রয়োজন হলে জানাবেন প্লিজ।"

        # Detect demo videos and pre-recorded voice clips
        media_found = detect_saved_media_to_send(user_msg=message_text, bot_reply=clean_reply)
        matched_video_url = media_found.get("video_url", "")
        matched_voice_url = media_found.get("voice_url", "")

        return {
            "reply_text": clean_reply,
            "voice_url": matched_voice_url or (generate_bangla_voice(clean_reply) if generate_voice_reply else ""),
            "video_url": matched_video_url,
            "order_created": order_created,
            "matched_images": matched_images
        }

    except Exception as e:
        print(f"[GeminiBrain Error]: {e}")
        err_msg = generate_smart_fallback_reply(message_text, customer_name)
        return {
            "reply_text": err_msg,
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "matched_images": detect_sample_photos_to_send(message_text, conversation_history, err_msg)
        }
