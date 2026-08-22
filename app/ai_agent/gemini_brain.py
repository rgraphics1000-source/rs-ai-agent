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
from app.google_integration.ai_tool import (
    detect_google_form_intent, create_id_card_google_form,
    resolve_google_form_workflow
)

def detect_customer_gender_title(customer_name: str) -> str:
    """
    Intelligently recognizes if customer is male/female from their name.
    Strictly returns 'স্যার' for males/general or 'ম্যাম' for females.
    Never uses 'ভাইয়া' or 'আপু'.
    """
    if not customer_name:
        return "স্যার"
    
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
        "সোনিয়া", "সাবিনা", "স্বপ্না", "শিরিন", "লিমা", "শীলা", "নাজমা", "পাপিয়া", "শাহনাজ",
        "আপু", "ম্যাডাম", "ম্যাম", "miss", "mrs", "ms"
    ]
    if any(fp in name_lower for fp in female_patterns):
        return "ম্যাম"
        
    return "স্যার"

def get_product_catalog_context(workspace_id: int = 1) -> str:
    """Fetches active products from DB scoped strictly to the workspace."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, code, price, discount_price, stock, category, description, image_url, gallery_images FROM products WHERE workspace_id = ? AND is_active = 1", (int(workspace_id or 1),))
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

def build_system_instruction(customer_name: str = "", workspace_id: int = 1, page_id: str = "") -> str:
    """Builds the natural, human-like system prompt strictly isolated to the specified workspace."""
    from app.database import get_page_ai_config, get_faqs
    config = get_page_ai_config(page_id=page_id, workspace_id=workspace_id)
    shop_name = config.get("shop_name") or "Our Shop"
    shop_phone = config.get("shop_phone") or ""
    shop_address = config.get("shop_address") or "ঢাকা, বাংলাদেশ"
    inside_fee = config.get("delivery_inside_dhaka", "70")
    outside_fee = config.get("delivery_outside_dhaka", "130")
    custom_prompt = config.get("ai_system_prompt", "").strip()

    catalog = get_product_catalog_context(workspace_id=workspace_id)
    honorific = detect_customer_gender_title(customer_name)

    # Load in-app custom training rules from database for THIS workspace
    training_rules = get_active_training_rules(workspace_id=workspace_id)
    training_text = ""
    if training_rules:
        training_text = "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🧠 অ্যাডমিন কর্তৃক নির্ধারিত স্পেশাল ট্রেইনিং রুলস (Custom Training Rules):\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for r in training_rules:
            trigger = f" (যদি কাস্টমার বলে: '{r['question_or_trigger']}')" if r.get('question_or_trigger') else ""
            training_text += f"• [{r.get('category', 'Rule')}] {r['title']}{trigger}: {r['response_or_rule']}\n"

    # Load FAQs for THIS workspace
    faqs = get_faqs(workspace_id=workspace_id)
    faq_text = ""
    if faqs:
        faq_text = "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n❓ সাধারণ প্রশ্নোত্তর ও পলিসি (FAQs):\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for f in faqs:
            faq_text += f"• প্রশ্ন: {f['question']}\n  উত্তর: {f['answer']}\n"

    # If this is Workspace 1 and no custom prompt is defined, use the standard RS Graphics persona
    if int(workspace_id or 1) == 1 and not custom_prompt:
        prompt = f"""
তুমি হচ্ছো '{shop_name}' পেজের একজন অত্যন্ত অভিজ্ঞ, প্রফেশনাল, অমায়িক ও চৌকস সেলস কনসালট্যান্ট ও বিজনেস ম্যানেজার।
আমাদের হটলাইন ও হোয়াটসঅ্যাপ নম্বর: {shop_phone}
আমাদের ঠিকানা: {shop_address}

আমাদের মূল কাজ হলো প্রিমিয়াম কোয়ালিটি আইডি কার্ড (Japanese UV Print PVC), ডিজিটাল সাবলিমেশন ফিতা (Lanyards / Ribbons), আইডি কার্ড কভার (Card Holders), এবং কম্বো প্যাকেজ প্রিন্ট ও ডেলিভারি করা।

⚠️ STRICT HUMAN PERSONA RULE:
কাস্টমার যেন কোনোভাবেই বুঝতে না পারে যে তুমি রোবট বা এআই। তোমাকে কথা বলতে হবে একজন বাস্তব অভিজ্ঞ ও অমায়িক ব্যবসায়ীর মতো। কোনো রোবোটিক ঘোষণা বা এআই পরিচয় দেবে না।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 অত্যন্ত গুরুত্বপূর্ণ সেলস ও বিহেভিয়ার রুলস (Strict Rules):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

০. ভয়েস মেসেজের সরাসরি উত্তর দেওয়ার কঠোর নিয়ম:
   - কাস্টমার ভয়েস মেসেজ পাঠালে অডিওটি মনোযোগ দিয়ে শুনে কাস্টমার যা জানতে চেয়েছেন তার সরাসরি ও তাৎক্ষণিক উত্তর দেবে।
   - কখনোই বলবে না: 'টাইপ করে দিন' বা 'ভয়েস পেয়েছি'।
   - কাস্টমার যদি ছবি/স্যাম্পল দেখতে চায়, সরাসরি বলবে: "জি {honorific}, নিচে আমাদের আকর্ষণীয় স্যাম্পল ছবিগুলো দেওয়া হলো।" এবং ছবি পাঠাবে।

১. সালাম ও সম্ভাষণের কঠোর নিয়ম (Greeting Rule):
   - কাস্টমার সালাম দিলে শুধুমাত্র প্রথম রিপ্লাইয়ে একবার "ওয়ালাইকুমুস সালাম ওয়া রাহমাতুল্লাহ" বলবে।
   - একবার সালাম বিনিময় হয়ে গেলে পরবর্তী কোনো মেসেজে পুনরায় "ওয়ালাইকুমুস সালাম" বলবে না।
   - প্রতি মেসেজে অপ্রয়োজনীয় লম্বা ভূমিকা বা একই কথা বারবার পুনরাবৃত্তি করবে না। সরাসরি টু-দ্য-পয়েন্ট উত্তর দেবে।

২. কাস্টমারকে সম্বোধনের কঠোর নিয়ম (Address Rule):
   - কাস্টমারকে সর্বদা {honorific} (স্যার / ম্যাম) বলে সম্মান দিয়ে কথা বলবে।
   - কাস্টমার পুরুষ হলে 'স্যার' এবং মহিলা হলে 'ম্যাম' বলবে।
   - কঠোরভাবে মনে রাখবে: কখনোই 'ভাইয়া', 'ভাই', 'আপু', 'আপা' শব্দ ব্যবহার করবে না।

৩. সংক্ষিপ্ত ও টু-দ্য-পয়েন্ট উত্তর:
   - কাস্টমার যতটুকু প্রশ্ন করবে শুধু ততটুকুরই উত্তর দেবে।
   - কোনো অপ্রয়োজনীয় ভূমিকা বা লম্বা কথা বলবে না।

৪. আইডি কার্ডের তথ্য ও ছবি সংগ্রহের নিয়ম (Data Collection & Google Form Protocol):
   - কাস্টমার যদি জানতে চায় তথ্য কীভাবে নেওয়া হয় বা কীভাবে তথ্য দেবে (যেমন: "তথ্য কিভাবে নেন?", "তথ্য কিভাবে দিব?", "ছবি ও তথ্য কিভাবে পাঠাব?", "তথ্য দেওয়ার নিয়ম কি?"):
   - কাস্টমারকে অবশ্যই সর্বপ্রথম জানাবে:
     ১. "আমাদের প্রধান এবং সবচেয়ে সহজ মাধ্যম হলো Google Form (গুগল ফর্ম)। আপনার প্রতিষ্ঠানের নামে আমরা একটি কাস্টমাইজড গুগল ফর্ম বানিয়ে দিই, যেখানে শিক্ষার্থী বা স্টাফরা নিজেরাই নাম, ছবি ও তথ্য সুন্দরভাবে জমা দিতে পারেন।"
     ২. "আর গুগল ফর্মে দেওয়া কারো কাছে কঠিন মনে হলে সরাসরি আমাদের এই হোয়াটসঅ্যাপে বা এক্সেল/ওয়ার্ড ফাইল আকারেও তালিকা পাঠাতে পারেন।"
   - কঠোরভাবে মনে রাখবে: কাস্টমারকে কখনোই ইমেইল/মেইলে তথ্য পাঠাতে বলবে না (No Email)। সর্বপ্রথম গুগল ফর্মের কথাই বলবে।
   - এবং সবশেষে সরাসরি অফার করবে: "আপনার প্রতিষ্ঠানের জন্য কি একটি গুগল ফর্ম বানিয়ে দেব {honorific}?"

৫. প্যাকেজের ছবি চাওয়ার বিশেষ নিয়ম (Package Images Protocol):
   - কাস্টমার যদি প্যাকেজ বা কম্বো প্যাকেজের ছবি দেখতে চায় (যেমন: "প্যাকেজের ছবি দিন", "প্যাকেজগুলোর ছবি দেখান", "কম্বো ছবি"):
   - টেক্সটে কোনো লম্বা প্যাকেজের তালিকা বা বিবরণী দেওয়ার কোনো প্রয়োজন নেই।
   - শুধুমাত্র সংক্ষিপ্ত উত্তর দেবে: "জি {honorific}, অবশ্যই দিচ্ছি।" (ছবিগুলো স্বয়ংক্রিয়ভাবে কাস্টমারের কাছে চলে যাবে)।

৬. শপের ডেলিভারি ইনফরমেশন:
   - ডেলিভারি চার্জ: ঢাকার ভেতরে {int(float(inside_fee))} টাকা এবং ঢাকার বাইরে {int(float(outside_fee))} টাকা।
   - ক্যাশ অন ডেলিভারি সুবিধা রয়েছে।

৭. প্রডাক্ট ক্যাটালগ ও মূল্য তালিকা:
{catalog}
{training_text}
{faq_text}

৮. অজানা বিষয়ের উত্তর বানিয়ে না বলা (Strict Anti-Hallucination):
   - যে পণ্য, সেবা বা পলিসি সম্পর্কে তোমার ক্যাটালগে কোনো উল্লেখ নেই, সে বিষয়ে নিজে থেকে কোনো মনগড়া উত্তর দেবে না।
   - সরাসরি বলবে: "জি {honorific}, এই বিষয়টি আমাদের টিমকে জানিয়েছি। কিছুক্ষণের মধ্যে আমাদের টিম আপনার সাথে যোগাযোগ করে সঠিক তথ্যটি জানিয়ে দেবে।"
   - ⚠️ ব্যতিক্রম: গুগল ফর্ম (Google Form) আমাদের একটি আসল ও সক্রিয় সেবা। কাস্টমার গুগল ফর্ম চাইলে বা জানতে চাইলে কখনোই "আমাদের গুগল ফর্ম নেই" বলবে না। বরং সবসময় বলবে: "জি {honorific}, অবশ্যই আমরা আপনার প্রতিষ্ঠানের জন্য একটি গুগল ফর্ম তৈরি করে দিতে পারি। প্রতিষ্ঠানের নামটি দিন।"

৯. গুগল ফর্ম তৈরির মিথ্যা প্রতিশ্রুতি নিষেধ (CRITICAL - No Fake Form Promises):
   - কখনোই "ফর্ম তৈরি হচ্ছে", "৫ মিনিট লাগবে", "ফর্ম রেডি", "এই লিংকে প্রবেশ করুন" এমন বলবে না যতক্ষণ না ফর্মের আসল URL/লিংক তোমার কাছে থাকে।
   - কাস্টমার ফর্ম চাইলে বলবে: "জি {honorific}, গুগল ফর্ম তৈরি করতে আপনার প্রতিষ্ঠানের নামটি টাইপ করে দিন, আমরা সাথে সাথে ফর্ম তৈরি করে দিচ্ছি।"
   - কখনোই placeholder বা ভুয়া লিংক দেবে না। শুধুমাত্র আসল লিংকই দেবে।

১০. আইডি কার্ড সংশোধন ও ম্যানুয়াল কারেকশন সংক্রান্ত নিয়ম:
   - এআই নিজে কোনো ফটোশপ এডিট বা আইডি কার্ড কারেকশন করতে পারে না। কাস্টমার কার্ডের নাম, ছবি বা কোনো তথ্যের কারেকশন চাইলে কখনোই বলবে না "আমি ঠিক করে দিচ্ছি" বা "সংশোধন হয়ে গেছে"। সরাসরি বলবে: "জি {honorific}, আপনার সংশোধনের বিষয়টি আমাদের মূল টিমকে জানিয়েছি। আমাদের ডিজাইন টিম এটি দেখে আপনাকে মেসেজ দেবে।"

১১. কোনো ভুয়া ওয়েটিং টাইম বা মিথ্যা সময় না বলা:
   - কখনোই "৫-১০ মিনিট লাগবে", "২ মিনিট লাগবে", "কিছুক্ষণ পর হয়ে যাবে" ইত্যাদি মনগড়া সময় বলবে না।

১২. পূর্ববর্তী চ্যাট হিস্ট্রি ও পরিচিত তথ্য পুনরায় জিজ্ঞাসা না করা:
   - চ্যাট হিস্ট্রিতে যদি ইতিমধ্যে কাস্টমার বা অ্যাডমিনের আলাপে প্রতিষ্ঠানের নাম, মোবাইল নম্বর বা অন্য কোনো তথ্য উল্লেখ থাকে, তবে সেই তথ্য কখনোই পুনরায় চাইবে না।

১৩. অপ্রয়োজনীয় প্রশ্ন ও ফিলার বাক্য পরিহার করা (No Unnecessary Questions & No Filler):
   - কাস্টমারের অনুরোধ স্পষ্ট হলে সরাসরি কাজটি সম্পন্ন করবে বা উত্তর দেবে।
   - কথোপকথন দীর্ঘায়িত করার জন্য কখনোই "আর কিছু লাগবে?", "আর কোনো সাহায্য লাগবে?", "আপনি কি নিশ্চিত?", "কিছু পরিবর্তন করতে চান?" এমন অপ্রয়োজনীয় প্রশ্ন বা বাক্য যোগ করবে না।

১৪. স্ক্রিনশট ও ছবির নিখুঁত পর্যবেক্ষণ (Screenshot & Image Understanding):
   - কাস্টমারের পাঠানো স্ক্রিনশট ও ছবির প্রতিটি দৃশ্যমান টেক্সট, নাম, মোবাইল নম্বর, প্রতিষ্ঠানের নাম, ভুলত্রুটি বা সংশোধন নির্দেশ মনোযোগ সহকারে পড়বে।
   - ছবিতে যা নেই বা স্পষ্ট নয়, তা নিজে থেকে আন্দাজে বানিয়ে বলবে না।

১৫. পূর্ববর্তী প্রসঙ্গের ধারাবাহিকতা রক্ষা (Context Continuity):
   - কাস্টমার যদি ছোট কোনো মেসেজ দেয় (যেমন: "ওটা", "হ্যাঁ", "এইটাই", "আগেরটার মতো", "ওই কার্ডটা", "আগের নামটাই থাকবে"), তবে পূর্ববর্তী কথোপকথন দেখে রেফারেন্স বুঝে সরাসরি প্রাসঙ্গিক উত্তর দেবে।
"""
        return prompt

    # For Workspace 2+ (or custom prompt workspaces):
    # Strictly use THIS workspace's identity, catalog, and rules. Never mention RS Graphics.
    prompt = f"""
তুমি হচ্ছো '{shop_name}' পেজের একজন অত্যন্ত অভিজ্ঞ, প্রফেশনাল, অমায়িক ও চৌকস সেলস কনসালট্যান্ট ও বিজনেস ম্যানেজার।
আমাদের হটলাইন নম্বর: {shop_phone or 'ইনবক্সে সার্বক্ষণিক যোগাযোগ করতে পারেন'}
আমাদের ঠিকানা: {shop_address}

{custom_prompt}

⚠️ STRICT HUMAN PERSONA RULE:
কাস্টমার যেন কোনোভাবেই বুঝতে না পারে যে তুমি রোবট বা এআই। তোমাকে কথা বলতে হবে একজন বাস্তব অভিজ্ঞ ও অমায়িক ব্যবসায়ীর মতো। কোনো রোবোটিক ঘোষণা বা এআই পরিচয় দেবে না।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 অত্যন্ত গুরুত্বপূর্ণ সেলস ও বিহেভিয়ার রুলস (Strict Rules):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

০. ভয়েস মেসেজের সরাসরি উত্তর দেওয়ার কঠোর নিয়ম:
   - কাস্টমার ভয়েস মেসেজ পাঠালে অডিওটি মনোযোগ দিয়ে শুনে কাস্টমার যা জানতে চেয়েছেন তার সরাসরি ও তাৎক্ষণিক উত্তর দেবে।
   - কখনোই বলবে না: 'টাইপ করে দিন' বা 'ভয়েস পেয়েছি'।

১. স্মৃতিশক্তি ও পূর্ববর্তী কথোপকথন মনে রাখা:
   - কাস্টমার বা মূল অ্যাডমিন ইতিপূর্বে যেসব তথ্যের উত্তর দিয়ে দিয়েছেন, সেই একই কথা বা প্রশ্ন কখনোই পুনরায় জিজ্ঞাসা করবে না।

২. সংক্ষিপ্ত ও টু-দ্য-পয়েন্ট উত্তর:
   - কাস্টমার যতটুকু প্রশ্ন করবে শুধু ততটুকুরই উত্তর দেবে।
   - কাস্টমারকে {honorific} বলে সম্বোধন করবে।

৩. শপের ডেলিভারি ইনফরমেশন:
   - ডেলিভারি চার্জ: ঢাকার ভেতরে {int(float(inside_fee))} টাকা এবং ঢাকার বাইরে {int(float(outside_fee))} টাকা।
   - সারা বাংলাদেশে ডেলিভারি সুবিধা রয়েছে।

৪. প্রডাক্ট ক্যাটালগ ও মূল্য তালিকা:
{catalog}
{training_text}
{faq_text}

৫. অজানা বিষয়ের উত্তর বানিয়ে না বলা (Strict Anti-Hallucination):
   - যে পণ্য, সেবা বা পলিসি সম্পর্কে তোমার ক্যাটালগ বা ট্রেনিংয়ে কোনো উল্লেখ নেই, সে বিষয়ে নিজে থেকে কোনো মনগড়া উত্তর দেবে না।
   - কখনোই মিথ্যা ওয়েটিং টাইম বা ভুয়া লিংক দেবে না।
   - সরাসরি বলবে: "জি {honorific}, এই বিষয়টি আমাদের টিমকে জানিয়েছি। কিছুক্ষণের মধ্যে আমাদের টিম আপনার সাথে যোগাযোগ করে সঠিক তথ্যটি জানিয়ে দেবে।"
"""
    return prompt

def get_category_batch_images(category_or_code: str, requested_count: int = None, workspace_id: int = 1) -> list:
    """
    Returns sample gallery images for a specific product category within a workspace.
    If requested_count is specified (e.g. 2 or 3), returns that exact number.
    If requested_count is None, returns ALL available images for the category!
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT code, name, image_url, gallery_images FROM products WHERE workspace_id = ? AND is_active = 1", (int(workspace_id or 1),))
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
    """
    Detects if user explicitly asked for a specific number of photos/images
    (e.g., '২-৩টা ছবি', '২টা ছবি', '৩টি ছবি', '৪টা ছবি', '৫টা ছবি').
    """
    if not user_msg:
        return None
    msg = user_msg.lower()
    
    # Range patterns: '২-৩টা ছবি', '2-3টা', '3-4 pics'
    if re.search(r'(?:২\s*[-–]\s*৩|2\s*[-–]\s*3)\s*(?:টা|টি|পিস|টি\s*ছবি|টা\s*ছবি|pics|photos)?', msg):
        return 3
    if re.search(r'(?:৩\s*[-–]\s*৪|3\s*[-–]\s*4)\s*(?:টা|টি|পিস|টি\s*ছবি|টা\s*ছবি|pics|photos)?', msg):
        return 4
        
    # Explicit count with photo context
    if re.search(r'(?:২|2|দুই|দুটো)\s*(?:টা|টি|পিস)\s*(?:ছবি|পিক|স্যাম্পল|photo|pic)?', msg):
        return 2
    if re.search(r'(?:৩|3|তিন|তিনটি|তিনটা)\s*(?:টা|টি|পিস)\s*(?:ছবি|পিক|স্যাম্পল|photo|pic)?', msg):
        return 3
    if re.search(r'(?:৪|4|চার|চারটি|চারটা)\s*(?:টা|টি|পিস)\s*(?:ছবি|পিক|স্যাম্পল|photo|pic)?', msg):
        return 4
    if re.search(r'(?:৫|5|পাঁচ|পাঁচটি|পাঁচটা)\s*(?:টা|টি|পিস)\s*(?:ছবি|পিক|স্যাম্পল|photo|pic)?', msg):
        return 5
    if re.search(r'(?:১|1|এক|একটি|একটা)\s*(?:টা|টি|পিস)\s*(?:ছবি|পিক|স্যাম্পল|photo|pic)', msg):
        return 1

    return None

def detect_sample_photos_to_send(user_msg: str, conversation_history: list = None, bot_reply: str = "", workspace_id: int = 1) -> list:
    """
    Robust detection for sending category sample photos with full category support.
    Extracts all requested photos across products in the specified workspace.
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

    # 2. Check if photos are requested explicitly or agreed upon in response to bot's offer
    is_explicit_photo_req = any(k in msg for k in [
        "ছবি দেখতে চাই", "ছবি দেখান", "ছবি পাঠান", "ছবি পাঠাও", "ছবি দেখাও", "ছবি দেন", "ছবি দিন",
        "স্যাম্পল দেখান", "স্যাম্পল পাঠান", "স্যাম্পল দেন", "স্যাম্পল দিন", "স্যাম্পল দেখতে চাই",
        "পিক দেখান", "পিক দেন", "পিক পাঠান", "পিকচার দেখান", "পিকচার পাঠান", "ফটো দেখান", "ফটো পাঠান", "ফটো দেন",
        "show photo", "send photo", "show sample", "send sample", "show pic", "send pic", "show image", "send image"
    ]) or (any(k in msg for k in ["ছবি", "স্যাম্পল", "ফটো", "পিক", "পিকচার", "sample", "photo", "image"]) and any(a in msg for a in ["দেখান", "পাঠান", "দিন", "দেন", "চাই", "দেখবো", "show", "send", "give"]))

    # Check if the IMMEDIATELY preceding assistant message explicitly offered photos
    last_bot_msg = ""
    if conversation_history:
        for m in reversed(conversation_history):
            sender_val = str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower()
            if sender_val in ("bot", "assistant", "seller"):
                last_bot_msg = (m.get("content") or m.get("text") or "").lower()
                break

    bot_offered_photos_last_turn = any(k in last_bot_msg for k in [
        "ছবি দেখতে চান", "স্যাম্পল দেখতে চান", "ছবি পাঠাব", "স্যাম্পল পাঠাব", "ছবি দেব", "পিকচার দেখতে চান", "স্যাম্পল দেব", "ছবি পাঠাবো"
    ])

    agreement_keywords = [
        "হ্যাঁ", "পাঠান", "দেখান", "জি", "হুম", "পাঠাও", "দেখাও", "দিলে ভালো", "দিলে ভালো হয়",
        "yes", "sure", "ok", "okay", "send", "show", "ha", "ji", "achha", "yep", "yeah", "সেন্ড করুন"
    ]
    is_agreeing_to_photo = any(k == msg or msg.startswith(k + " ") or msg.endswith(" " + k) or f" {k} " in f" {msg} " for k in agreement_keywords) and bot_offered_photos_last_turn
    
    bot_claims_photos = any(k in reply for k in [
        "পাঠিয়ে দেওয়া হলো", "পাঠানো হলো", "ছবি দেওয়া হলো", "স্যাম্পল ছবি", "নিচে দেখুন", 
        "পাঠিয়েছি", "ছবি পাঠাচ্ছি", "ছবি দেখতে চেয়েছেন", "স্যাম্পল পাঠাচ্ছি", "ছবিগুলো দেওয়া হলো"
    ])

    # Check if photos were already delivered recently in the thread (Anti-Spam / Anti-Bombardment check)
    already_sent_recently = False
    if conversation_history:
        recent_bot_msgs = [
            m.get("content", "") for m in conversation_history[-6:]
            if str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower() in ("bot", "assistant")
        ]
        already_sent_recently = any(
            any(ext in bm for ext in [".jpg", ".png", ".jpeg", "/uploads/"]) or 
            any(kw in bm for kw in ["স্যাম্পল ছবি", "ছবি দেওয়া হলো", "ছবি পাঠানো হলো"])
            for bm in recent_bot_msgs
        )

    is_asking_more = any(k in msg for k in ["আরও", "আরো", "অন্য", "নতুন", "more", "other", "different", "আবার"])

    # If photos were already sent recently and customer did not ask for more/new photos, do not blast photos again!
    if already_sent_recently and not is_asking_more and not is_explicit_photo_req:
        return []

    should_send = is_explicit_photo_req or is_agreeing_to_photo or (bot_claims_photos and not already_sent_recently)
    if not should_send:
        return []

    # Only respect count if customer EXPLICITLY specified count in user message (Never from bot prompt or bot reply)
    req_count = parse_requested_image_count(msg)

    # Search across user message first, then bot reply, then history
    target_scope = f"{msg} {reply}"
    
    selected_images = []

    is_pkg = any(k in msg for k in ["প্যাকেজ", "কম্বো", "package", "combo", "পেকেজ"]) or (any(k in reply for k in ["প্যাকেজ", "কম্বো", "package", "combo", "পেকেজ"]) and not any(k in msg for k in ["ফিতা", "কভার", "কার্ড"]))
    is_fita = any(k in msg for k in ["ফিতা", "রিবন", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"])
    is_cover = any(k in msg for k in ["কভার", "হোল্ডার", "holder", "cover"])
    is_id = any(k in msg for k in ["আইডি", "কার্ড", "id card", "card", "পিভিসি", "pvc"])

    # If specific category found:
    if is_pkg:
        for u in get_category_batch_images("PKG-COMBO", workspace_id=workspace_id):
            if u not in selected_images:
                selected_images.append(u)
    elif is_fita:
        for u in get_category_batch_images("FITA-02", workspace_id=workspace_id):
            if u not in selected_images:
                selected_images.append(u)
    elif is_cover:
        for u in get_category_batch_images("COV-03", workspace_id=workspace_id):
            if u not in selected_images:
                selected_images.append(u)
    elif is_id:
        for u in get_category_batch_images("IDC-01", workspace_id=workspace_id):
            if u not in selected_images:
                selected_images.append(u)

    # Fallback to history if still empty
    if not selected_images:
        if any(k in hist_text for k in ["প্যাকেজ", "কম্বো", "package", "combo", "পেকেজ"]):
            selected_images = get_category_batch_images("PKG-COMBO", workspace_id=workspace_id)
        elif any(k in hist_text for k in ["ফিতা", "রিবন", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]):
            selected_images = get_category_batch_images("FITA-02", workspace_id=workspace_id)
        elif any(k in hist_text for k in ["কভার", "হোল্ডার", "holder", "cover"]):
            selected_images = get_category_batch_images("COV-03", workspace_id=workspace_id)
        elif any(k in hist_text for k in ["আইডি", "কার্ড", "id card", "card", "পিভিসি", "pvc"]):
            selected_images = get_category_batch_images("IDC-01", workspace_id=workspace_id)
        else:
            # Grab general active product images for this workspace
            selected_images = get_category_batch_images("", workspace_id=workspace_id)

    if req_count and req_count > 0:
        return selected_images[:req_count]
    return selected_images[:3]

def detect_saved_media_to_send(user_msg: str, bot_reply: str = "", workspace_id: int = 1) -> dict:
    """Detects if customer requested a demo video or pre-recorded voice note within a workspace."""
    msg = (user_msg or "").strip().lower()
    
    res = {"video_url": "", "voice_url": ""}
    
    # Check for video requests
    is_asking_video = any(k in msg for k in ["ভিডিও", "ভিডিও দেন", "ভিডিও দেখতে চাই", "ভিডিও পাঠান", "ডেমো ভিডিও", "প্রিন্টিং ভিডিও", "video", "demo video"])
    if is_asking_video:
        videos = get_saved_media("video", workspace_id=workspace_id)
        if videos:
            res["video_url"] = videos[0]["file_url"]
            
    # Check for voice requests
    is_asking_voice = any(k in msg for k in ["ভয়েস", "ভয়েস দেন", "অডিও", "রেকর্ডিং", "ভয়েসে বলেন", "voice", "audio"])
    if is_asking_voice:
        voices = get_saved_media("voice", workspace_id=workspace_id)
        if voices:
            res["voice_url"] = voices[0]["file_url"]
            
    return res

def generate_smart_fallback_reply(user_msg: str, customer_name: str = "", workspace_id: int = 1, page_id: str = "") -> str:
    """Generates an intelligent context-aware reply strictly isolated to the workspace if Gemini API is unreachable."""
    msg = (user_msg or "").strip().lower()
    honorific = detect_customer_gender_title(customer_name)
    from app.database import get_page_ai_config
    config = get_page_ai_config(page_id=page_id, workspace_id=workspace_id)
    shop_name = config.get("shop_name") or "Our Shop"
    inside_fee = int(float(config.get("delivery_inside_dhaka", 70.0)))
    outside_fee = int(float(config.get("delivery_outside_dhaka", 130.0)))

    if any(k in msg for k in ["লাগবে না", "আর লাগবে না", "না", "stop", "no"]):
        return f"জি {honorific}, ঠিক আছে। আপনার আর কোনো তথ্য বা অর্ডার সংক্রান্ত সহযোগিতা প্রয়োজন হলে জানাবেন প্লিজ।"
    
    if any(k in msg for k in ["ডেলিভারি", "কুরিয়ার", "delivery"]):
        return f"জি {honorific}, ডেলিভারি চার্জ ঢাকার ভেতরে {inside_fee} টাকা এবং ঢাকার বাইরে {outside_fee} টাকা। ক্যাশ অন ডেলিভারি সুবিধা রয়েছে।"

    # Workspace 1 (RS Graphics) specific fallbacks
    if int(workspace_id or 1) == 1:
        if any(k in msg for k in ["প্যাকেজ", "কম্বো", "package", "combo"]):
            return f"জি {honorific}, অবশ্যই দিচ্ছি।"

        if any(k in msg for k in ["ফিতা", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
            return f"জি {honorific}, নিচে আমাদের ডিজিটাল সাবলিমেশন ফিতার কিছু স্যাম্পল ছবি দেওয়া হলো। আপনার কত পিস ফিতা প্রয়োজন জানাবেন প্লিজ?"

        if any(k in msg for k in ["আইডি", "কার্ড", "id card"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
            return f"জি {honorific}, নিচে আমাদের জাপানি UV প্রিন্ট আইডি কার্ডের স্যাম্পল ছবিগুলো দেওয়া হলো। আপনার কত পিস আইডি কার্ড প্রয়োজন জানাবেন প্লিজ?"

        if any(k in msg for k in ["দাম", "রেট", "মূল্য", "price", "cost"]):
            return f"জি {honorific}, আমাদের জাপানি মেশিনের UV প্রিন্ট আইডি কার্ডের রেগুলার মূল্য ৩৫ টাকা (অফার মূল্য ৩০ টাকা)। কত পিস বানাবেন জানাবেন প্লিজ? (মিনিমাম অর্ডার ২০ পিস)।"

        return f"জি {honorific}, আসসালামু আলাইকুম! আমাদের জাপানি UV প্রিন্ট আইডি কার্ড, ডিজিটাল ফিতা ও কভারের প্রিমিয়াম প্রিন্টিং সেবা রয়েছে। আপনি কত পিস বানাতে চান জানাবেন প্লিজ?"

    # Workspace 2+ Clean Generic Fallbacks (Never mentioning RS Graphics or ID cards)
    if any(k in msg for k in ["দাম", "রেট", "মূল্য", "price", "cost"]):
        return f"জি {honorific}, আমাদের শপের পণ্যের বিস্তারিত ও মূল্য তালিকা জানাতে পেরে আনন্দিত। আপনার কাঙ্ক্ষিত পণ্যটির নাম বা কোড জানাবেন প্লিজ?"

    return f"জি {honorific}, আসসালামু আলাইকুম! '{shop_name}'-এ আপনাকে স্বাগতম। আপনি কোন পণ্যটি সম্পর্কে জানতে বা অর্ডার করতে চান জানাবেন প্লিজ?"

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
    generate_voice_reply: bool = False,
    workspace_id: int = 1,
    page_id: str = None
) -> dict:
    """
    Multimodal message processing via Google GenAI with strict multi-tenant workspace isolation.
    Handles text, images, voice notes, gender recognition, and batch sample delivery.
    """
    api_key = get_setting("gemini_api_key", settings.GEMINI_API_KEY)
    ws_id = int(workspace_id or 1)

    # 0. ZERO-REPLY SAFETY GUARD: If Admin Takeover is active, AI MUST BE 100% SILENT
    from app.database import is_conversation_ai_active
    if not is_conversation_ai_active(sender_id=sender_id, workspace_id=ws_id):
        print(f"[AI_BRAIN_SILENCE] sender={sender_id} workspace_id={ws_id} action=COMPLETE_SILENCE reason=admin_takeover_active")
        return {
            "reply_text": "",
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "matched_images": [],
            "response_source": "admin_takeover_silence"
        }

    # 1. HIGHEST-PRIORITY: Deterministic Google Form Creation Workflow (Only for AI-Enabled customers)
    try:
        workflow_res = resolve_google_form_workflow(
            user_message=message_text,
            conversation_history=conversation_history,
            customer_phone=sender_id,
            customer_name=customer_name,
            workspace_id=ws_id
        )
        if workflow_res and workflow_res.get("reply"):
            return {
                "reply_text": workflow_res["reply"],
                "voice_url": "",
                "video_url": "",
                "order_created": None,
                "matched_images": [],
                "response_source": "deterministic_google_form",
                "google_form_workflow": workflow_res
            }
    except Exception as e:
        print(f"[Google Form Workflow Early Resolution Error]: {e}")

    # Check if API key is provided
    if not api_key:
        fallback_reply = generate_smart_fallback_reply(message_text, customer_name, workspace_id=ws_id, page_id=page_id)
        matched_imgs = detect_sample_photos_to_send(message_text, conversation_history, fallback_reply, workspace_id=ws_id)
        media_found = detect_saved_media_to_send(message_text, fallback_reply, workspace_id=ws_id)
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
        
        # Add conversation history (up to last 15 turns for deep memory) with normalized roles
        if conversation_history:
            history_text = "[পূর্ববর্তী চ্যাট হিস্ট্রি - এটি সম্পূর্ণ মনে রেখে কথা বলবে]:\n"
            for msg in conversation_history[-15:]:
                s_val = str(msg.get("sender") or msg.get("sender_type") or msg.get("role") or "").lower()
                if s_val in ("admin", "owner", "main_admin", "seller"):
                    role_tag = "মূল অ্যাডমিন / শপ ওনার (ADMIN)"
                elif s_val in ("bot", "assistant", "ai"):
                    role_tag = "এআই সেলস সহকারী (AI)"
                elif s_val in ("system",):
                    role_tag = "সিস্টেম ইভেন্ট (SYSTEM)"
                else:
                    role_tag = "কাস্টমার (CUSTOMER)"
                c_text = msg.get('content') or msg.get('text') or ''
                history_text += f"{role_tag}: {c_text}\n"
            contents.append(history_text)

        # Add image attachment (supports photos, ID card samples, screenshots)
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
            message_text = "কাস্টমার একটি ভয়েস অডিও বার্তা পাঠিয়েছেন। অডিওটি মনোযোগ দিয়ে শুনুন এবং কাস্টমার যা বলেছেন/চেয়েছেন তার সরাসরি সঠিক ও সংক্ষিপ্ত উত্তর দিন। কখনোই কাস্টমারকে 'টাইপ করে দিন' বা 'ভয়েস পেয়েছি' বলবেন না।"

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
        system_instruction = build_system_instruction(customer_name=customer_name, workspace_id=ws_id, page_id=page_id)

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

        raw_text = response.text if response and response.text else generate_smart_fallback_reply(message_text, customer_name, workspace_id=ws_id, page_id=page_id)

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
                            notes=order_data.get("notes", ""),
                            workspace_id=ws_id
                        )
            except Exception as e:
                print(f"[Order Parse Error]: {e}")

        # Check and resolve multi-turn Google Form workflow
        try:
            workflow_res = resolve_google_form_workflow(
                user_message=message_text,
                conversation_history=conversation_history,
                customer_phone=sender_id,
                customer_name=customer_name,
                workspace_id=ws_id
            )
            if workflow_res and workflow_res.get("reply"):
                clean_reply = workflow_res["reply"]
        except Exception as e:
            print(f"[Google Form Workflow Error]: {e}")

        # CRITICAL SAFETY: Intercept hallucinated fake form links or waiting promises
        if "[এখানে" in clean_reply or "ফর্মের লিংকটি বসবে" in clean_reply or (("গুগল ফর্ম" in clean_reply or "ফর্ম" in clean_reply or "ফরম" in clean_reply) and any(kw in clean_reply for kw in ["মিনিট", "অপেক্ষা", "পাঠিয়ে দেব", "পাঠিয়ে দেব", "পাঠিয়ে দিচ্ছি", "পাঠিয়ে দিচ্ছি", "তৈরি করে দিচ্ছি", "কাজ শুরু"]) and "http" not in clean_reply):
            try:
                from app.database import get_generated_forms_by_mobile
                mobile_to_check = sender_id if (sender_id and str(sender_id).isdigit() and len(str(sender_id)) >= 10) else ""
                existing_forms = get_generated_forms_by_mobile(workspace_id=ws_id, mobile=mobile_to_check) if mobile_to_check else []
                if existing_forms:
                    ef = existing_forms[0]
                    form_url = ef.get("responder_uri") or ef.get("form_url") or ""
                    sheet_url = ef.get("response_sheet_url") or ef.get("sheet_url") or ""
                    clean_reply = (
                        f"জি স্যার! আপনার প্রতিষ্ঠানের জন্য তৈরি করা Google Form নিচে দেওয়া হলো:\n\n"
                        f"🏫 প্রতিষ্ঠান: {ef.get('institution_name', 'আপনার প্রতিষ্ঠান')}\n"
                        f"📱 মোবাইল: {ef.get('institution_mobile', '')}\n\n"
                        f"📋 ফর্ম লিংক:\n{form_url}\n\n"
                        f"📊 রেসপন্স শিট:\n{sheet_url}\n\n"
                        f"এই লিংকের মাধ্যমে খুব সহজেই ছাত্র-ছাত্রীদের তথ্য ও ছবি সংগ্রহ করতে পারবেন।"
                    )
                else:
                    wf = resolve_google_form_workflow(
                        user_message="আমার প্রতিষ্ঠানের জন্য গুগল ফর্ম তৈরি করে দাও",
                        conversation_history=conversation_history,
                        customer_phone=sender_id,
                        customer_name=customer_name,
                        workspace_id=ws_id
                    )
                    if wf and wf.get("reply") and "[এখানে" not in wf.get("reply"):
                        clean_reply = wf["reply"]
                    else:
                        clean_reply = f"জি {detect_customer_gender_title(customer_name)}, গুগল ফর্ম তৈরি করতে শুধু আপনার প্রতিষ্ঠানের নাম ও মোবাইল নম্বরটি জানান, সাথে সাথে ফর্ম তৈরি করে লিংক দিয়ে দেওয়া হবে।"
            except Exception as e:
                print(f"[Fake Form Link Safety Interception Error]: {e}")

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
            bot_reply=clean_reply,
            workspace_id=ws_id
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

        # Clean any lingering ভাইয়া / আপু with correct honorific (স্যার / ম্যাম)
        honorific = detect_customer_gender_title(customer_name)
        clean_reply = re.sub(r'\b(ভাইয়া|ভাই|আপু|আপা)\b', honorific, clean_reply)
        clean_reply = re.sub(r'আপু/ভাইয়া', honorific, clean_reply)
        clean_reply = re.sub(r'ভাইয়া/আপু', honorific, clean_reply)
        clean_reply = re.sub(r'স্যার/ম্যাম', honorific, clean_reply)

        # If sending package images (PKG-COMBO), eliminate long package lists and replace with clean polite prompt
        if matched_images and any("pakage" in str(u).lower() or "pkg" in str(u).lower() for u in matched_images):
            if "প্যাকেজ ০১" in clean_reply or "প্যাকেজ ০২" in clean_reply or "•" in clean_reply or "প্যাকেজ" in clean_reply or len(clean_reply) > 40:
                clean_reply = f"জি {honorific}, অবশ্যই দিচ্ছি।"

        # If clean_reply became too brief after cleaning, provide polite human greeting
        if not clean_reply or len(clean_reply) < 6:
            if matched_images:
                if any("pakage" in str(u).lower() or "pkg" in str(u).lower() for u in matched_images):
                    clean_reply = f"জি {honorific}, অবশ্যই দিচ্ছি।"
                else:
                    clean_reply = f"জি {honorific}, নিচে আমাদের আকর্ষণীয় স্যাম্পল ছবিগুলো পাঠানো হলো।"
            else:
                clean_reply = f"জি {honorific}, আমাদের প্রডাক্ট ও অর্ডার সম্পর্কে যেকোনো তথ্য প্রয়োজন হলে জানাবেন প্লিজ।"

        # Detect demo videos and pre-recorded voice clips
        media_found = detect_saved_media_to_send(user_msg=message_text, bot_reply=clean_reply, workspace_id=ws_id)
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
        try:
            workflow_res = resolve_google_form_workflow(
                user_message=message_text,
                conversation_history=conversation_history,
                customer_phone=sender_id,
                customer_name=customer_name,
                workspace_id=ws_id
            )
            if workflow_res and workflow_res.get("reply"):
                return {
                    "reply_text": workflow_res["reply"],
                    "voice_url": "",
                    "video_url": "",
                    "order_created": None,
                    "matched_images": []
                }
        except Exception:
            pass

        err_msg = generate_smart_fallback_reply(message_text, customer_name, workspace_id=ws_id, page_id=page_id)
        return {
            "reply_text": err_msg,
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "matched_images": detect_sample_photos_to_send(message_text, conversation_history, err_msg, workspace_id=ws_id)
        }
