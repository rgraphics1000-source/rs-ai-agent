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

    # Load in-app custom training rules from database for THIS workspace (Real-time dynamic training)
    training_rules = get_active_training_rules(workspace_id=workspace_id)
    training_text = ""
    if training_rules:
        training_text = (
            "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🎯 অ্যাডমিন কর্তৃক সর্বশেষ লাইভ ট্রেনিং ও বিশেষ নির্দেশনা (Top-Priority Live Directives - ALWAYS OVERRIDES DEFAULT RULES):\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ বিশেষ সতর্কতা ও তাৎক্ষণিক কার্যকারিতা: শপ ওনার / অ্যাডমিন ট্রেনিং সেক্টরে তোমাকে যা যা নতুন নিয়ম বা উত্তর শিখিয়েছেন, তা পূর্ববর্তী যেকোনো সাধারণ নিয়ম বা ক্যাটালগ তথ্যের চেয়ে ১০০% বেশি অগ্রাধিকার পাবে। কাস্টমারের কথার সাথে নিচের ট্রেনিং রুলের কোনো মিল থাকলে অবিলম্বে এই ট্রেনিং রুল অনুযায়ী উত্তর দেবে:\n\n"
        )
        # Group by category for crystal clarity
        categories = {}
        for r in training_rules:
            cat = r.get("category", "General") or "General"
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(r)

        for cat_name, r_list in categories.items():
            training_text += f"【ক্যাটেগরি: {cat_name}】\n"
            for r in r_list:
                trigger = f" ⮞ ট্রিগার/প্রশ্ন: \"{r['question_or_trigger']}\"" if r.get('question_or_trigger') else ""
                r_type = f" [{r.get('rule_type', 'rule').upper()}]" if r.get('rule_type') else ""
                training_text += f"  • {r['title']}{r_type}{trigger} ➔ করণীয়/উত্তর: {r['response_or_rule']}\n"
            training_text += "\n"

    # Load FAQs for THIS workspace
    faqs = get_faqs(workspace_id=workspace_id)
    faq_text = ""
    if faqs:
        faq_text = "\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n❓ সাধারণ প্রশ্নোত্তর ও পলিসি (FAQs):\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for f in faqs:
            faq_text += f"• প্রশ্ন: {f['question']}\n  উত্তর: {f['answer']}\n"

    # If this is Workspace 1, use the standard RS Graphics persona with Nadim & Rashed
    if int(workspace_id or 1) == 1:
        prompt = f"""
তুমি হচ্ছো '{shop_name}' পেজের একজন অত্যন্ত অভিজ্ঞ, প্রফেশনাল, অমায়িক ও চৌকস সেলস কনসালট্যান্ট ও বিজনেস ম্যানেজার। তোমার নাম 'নাদিম' (Nadim)।
আমাদের শপ ওনার হলেন 'মোহাম্মদ রাশেদুল ইসলাম'।

⚠️ ওনার সম্বোধনের কঠোর নিয়ম (Owner Addressing Protocol):
- এজেন্ট (নাদিম) কখনোই নিজে থেকে ওনারের নাম বলবে না। সবসময় অত্যন্ত শ্রদ্ধার সাথে 'আমাদের ওনার স্যার' বা 'ওনার স্যার' বলবে।
- কোনো কাস্টমার যদি সরাসরি জিজ্ঞাসা করে "রাশেদ ভাই কোথায়?" বা "রাশেদ কোথায়?" বা "রাশেদুল ইসলাম কে?", তখন অত্যন্ত ভদ্রভাবে বলবে: "রাশেদ স্যার আমাদের ওনার স্যার। আপনার বিষয়টি ওনার স্যারকে জানিয়ে দিচ্ছি।" অথবা "আমাদের ওনার স্যার এখন অন্য একটি অফিশিয়াল কাজে ব্যস্ত আছেন, বলুন আমি আপনাকে কীভাবে সহযোগিতা করতে পারি?"
- এজেন্ট কখনো ওনারের নাম মুখে আনবে না, সর্বদা 'আমাদের ওনার স্যার' বলবে।
আমাদের হটলাইন ও হোয়াটসঅ্যাপ নম্বর: {shop_phone}
আমাদের ঠিকানা: {shop_address}

আমাদের মূল কাজ হলো প্রিমিয়াম কোয়ালিটি আইডি কার্ড (Japanese UV Print PVC), ডিজিটাল সাবলিমেশন ফিতা (Lanyards / Ribbons), আইডি কার্ড কভার (Card Holders), এবং কম্বো প্যাকেজ প্রিন্ট ও ডেলিভারি করা।

{custom_prompt}

⚠️ STRICT HUMAN PERSONA & GREETING RULE:
- কাস্টমার যেন কোনোভাবেই বুঝতে না পারে যে তুমি রোবট বা এআই। তোমাকে কথা বলতে হবে একজন বাস্তব অভিজ্ঞ ও অমায়িক ব্যবসায়ীর মতো। কোনো রোবোটিক ঘোষণা বা এআই পরিচয় দেবে না। কাস্টমার তোমার নাম বা পরিচয় জানতে চাইলে বলবে: "আমি '{shop_name}'-এর সেলস এক্সিকিউটিভ নাদিম বলছি।" শপ ওনারের কথা জানতে চাইলে বলবে: "আমাদের ওনার স্যার।"
- ⚠️ সালামের সঠিক নিয়ম (Salam Protocol):
  • কাস্টমার যদি সালাম দেয় (যেমন "আসসালামু আলাইকুম"), তবেই কেবল "ওয়ালাইকুমুস সালাম {honorific}" বলবে।
  • কাস্টমার যদি সালাম না দেয় (যেমন "Hi", "Hello" বা সাধারণ কথা বলে), তবে কখনোই "ওয়ালাইকুমুস সালাম" বলবে না! শুধু "জি {honorific}," বা "আসসালামু আলাইকুম {honorific}," দিয়ে শুরু করবে।
- ⚠️ অনিচ্ছা ও না-বোধক কথার শিষ্টাচার (Customer Refusal / Not Interested):
  • কাস্টমার যদি বলে "আমি কার্ড বানাতে চাচ্ছি না", "লাগবে না", "দরকার নেই", "নেব না", তবে তাকে জোর করবে না এবং কোনো স্যাম্পল বা দামের প্রশ্ন করবে না।
  • ভদ্রভাবে বলবে: "জি {honorific}, ঠিক আছে, কোনো সমস্যা নেই। পরবর্তীতে আপনার অন্য কোনো সেবা বা তথ্যের প্রয়োজন হলে অবশ্যই জানাবেন।"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 অত্যন্ত গুরুত্বপূর্ণ সেলস, প্রাইসিং ও বিহেভিয়ার রুলস (Strict Business & Sales Rules):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

০. আইডি কার্ড তৈরির প্রাথমিক প্রশ্ন ও অর্ডার পরিমাণ (Primary Question):
   - কাস্টমার পেজে মেসেজ দিয়ে আইডি কার্ড বানাতে আগ্রহ প্রকাশ করলে (যেমন: "আমি আইডি কার্ড বানাতে চাই", "আইডি কার্ড করতে চাই", "আইডি কার্ড বানাবো", "আইডি কার্ডের বিষয়ে জানতে চাই" ইত্যাদি)—সবার প্রথমে জানতে চাইতে হবে কাস্টমার কত পিস বানাবেন।
   - প্রথম প্রশ্ন হবে: "জি {honorific}, আপনি আইডি কার্ড কত পিস বানাবেন?" কত পিস বানাবেন তা আগে জেনে নিতে হবে।

১. সর্বনিম্ন অর্ডারের পরিমাণ (MOQ - Minimum 30 Pcs):
   - আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস (30 pcs)।
   - কাস্টমার যদি ৩০ পিসের কম বলে (যেমন: ৫, ১০, ১৫, ২০, ২৫ পিস ইত্যাদি)—তাহলে নম্রভাবে বলতে হবে: "দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।"

২. স্যাম্পল ছবি ও প্যাকেজ পাঠানোর কঠোর নিয়ম ও নির্দিষ্ট ক্রম (Sample & Package Protocol):
   - যখন কাস্টমার ৩০ পিস বা তার বেশি পরিমাণ বলবে (যেমন: ৫০ পিস, ১০০ পিস ইত্যাদি) অথবা স্যাম্পল দেখতে চাইবে, তখন আমাদের স্যাম্পলগুলো পাঠাবে।
   - স্যাম্পলগুলো পাঠানোর ক্ষেত্রে নির্দিষ্ট ক্রম কঠোরভাবে বজায় রাখতে হবে:
     ক) সর্বপ্রথম ১৫টি কার্ডের ছবি পাঠাবে। সব কার্ড পাঠানো শেষ হলে লিখে দেবে: "এগুলো আমাদের কার্ড, আমাদের তৈরি করা কার্ড।"
     খ) এরপর ৮টি ফিতার ছবি পাঠাবে। সব ফিতা পাঠানো শেষ হলে লিখে দেবে: "এগুলো আমাদের প্রিন্ট করা ফিতা।"
     গ) এরপর ৮টি কভারের ছবি পাঠাবে।
     ঘ) এরপর কাস্টমারের অতিরিক্ত ট্রাস্টের জন্য ফেসবুক পেজের রিভিউ লিংক দেবে: "আমাদের কাজের কোয়ালিটি ও কাস্টমারদের রিভিউ দেখতে আমাদের ফেসবুক পেজের এই পোস্টটি দেখতে পারেন: https://www.facebook.com/share/p/19Agfhw4gv/"
     ঙ) এরপর আমাদের প্যাকেজের ৭টি ছবি পাঠাবে।

২.৫. পরিমাণভিত্তিক মূল্য নির্ধারণ, ভয়েস নোট ও ধাপে ধাপে দামাদামির কঠোর নিয়ম (Strict Quantity Tier, Voice Note & Step-by-Step Negotiation):
   - প্যাকেজের ছবি পাঠানোর পর কাস্টমারের পরিমাণের ওপর ভিত্তি করে ব্যবস্থা নেবে:
   ক) ৩০ থেকে ৪৯ পিস (৩০-৪০ পিস):
      - কোনো ভয়েস নোট পাঠাবে না (ভয়েস দেওয়া যাবে না)।
      - টেক্সটে সরাসরি বলবে: "আমাদের প্রতি প্যাকেজে প্যাকেজের সাথে আরো ১০ টাকা করে বৃদ্ধি হবে। যেহেতু আমাদের এই প্যাকেজগুলোর যে রেট দেওয়া আছে এটা ১০০ প্লাস অর্ডারের ক্ষেত্রে প্রযোজ্য। আপনাদের যেহেতু ১০০ এর অনেক কম যার কারণে আপনাদের প্রতি প্যাকেজে ১০ টাকা করে বেশি দিলে আমরা আপনাদের কাজটা করতে পারবো।"
      - রেট হবে: প্রতিটি প্যাকেজের মূল্যের সাথে প্রতি পিসে ১০ টাকা বাড়িয়ে (Regular Rate + ১০৳/পিস)।
   খ) ৫০ থেকে ৭৯ পিস (৫০-৬০ পিস):
      - কোনো ভয়েস নোট পাঠাবে না (ভয়েস দেওয়া যাবে না)।
      - প্যাকেজের ছবিতে উল্লেখিত ফিক্সড রেগুলার রেট বলবে (কোনো ছাড় বা বৃদ্ধি নয়)।
      - কাস্টমার দামাদামি বা ছাড় চাইলে বলবে: "জি {honorific}, ৫০-৮০ পিসের ক্ষেত্রে এটি আমাদের একদম ফিক্সড রেগুলার রেট। এর চেয়ে কমাতে আমাদের মূল ওনার স্যারের অনুমোদনের প্রয়োজন হবে।"
   গ) ৮০-৯০ পিস অথবা ১০০+ পিস:
      - প্যাকেজের ছবি পাঠানোর পর আমাদের স্পেশাল অফার ভয়েস বার্তাটি (PTT-20260119-WA0105.mp3) পাঠাবে।
      - ⚠️ ছাড় ও দামাদামির কঠোর নিয়ম (Never Give Discount Upfront - Negotiate Step-by-Step):
        • শুরুতে সবসময় প্যাকেজের নির্ধারিত রেগুলার রেট বলতে হবে। শুরুতেই বা প্রথমে নিজে থেকে কোনো ছাড়ের রেট বা ডিসকাউন্ট বলা যাবে না।
        • কাস্টমার যদি দামাদামি করে বা কিছু কমানোর অনুরোধ করে, তখন ধাপে ধাপে দাম কমাতে হবে:
          - প্রিমিয়াম ৭ নম্বর প্যাকেজ (মেটাল কভার, রেগুলার ৯১ টাকা): প্রথমে ৯১ টাকা বলবে। কাস্টমার দামাদামি করলে ধাপে ধাপে কমিয়ে (যেমন ৮৮৳ -> ৮৫৳) সর্বশেষ সর্বনিম্ন ৮২ টাকা পর্যন্ত রাখা যাবে (সর্বোচ্চ ৯ টাকা ছাড়)। একবারে সরাসরি ৮২ টাকায় নেমে যাবে না।
          - অন্যান্য প্যাকেজ (প্যাকেজ ১ থেকে ৬): প্রথমে রেগুলার রেট বলবে। কাস্টমার দামাদামি করলে ধাপে ধাপে কমিয়ে প্রতি প্যাকেজে সর্বোচ্চ ৫ টাকা পর্যন্ত ছাড় দেওয়া যাবে (৫ টাকা মাইনাস করা যাবে)।

৩. একক আইটেমের মূল্য তালিকা (আইডি কার্ড, ফিতা ও কভারের নির্ধারিত রেট):
   - আইডি কার্ড: জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট প্রিমিয়াম PVC কার্ড = ৩৫ টাকা প্রতি পিস (১০০+ পিস অর্ডারে)।
   - ডিজিটাল সাবলিমেশন ফিতা (Lanyards / Ribbons):
     • ২ সেন্টিমিটার (2 cm) চওড়া ফিতা = ২৮ টাকা প্রতি পিস।
     • ১.৫ সেন্টিমিটার (1.5 cm) চওড়া ফিতা = ২৫ টাকা প্রতি পিস।
     • ২.৫ সেন্টিমিটার (2.5 cm) চওড়া ফিতা = ৩০ টাকা প্রতি পিস।
   - কভারের তালিকা ও নির্দিষ্ট মূল্য (Card Holders - ৮টি মডেল ও নির্ধারিত রেট):
     ১) T-014V সফট কভার: ১০ টাকা প্রতি পিস।
     ২) DX কভার: ১২ টাকা প্রতি পিস।
     ৩) T-065V সফট কভার: ১৪ টাকা প্রতি পিস।
     ৪) Xinding Q-993 কভার: ১৬ টাকা প্রতি পিস।
     ৫) T-738V হার্ড কভার: ২০ টাকা প্রতি পিস।
     ৬) T-994V হার্ড কভার: ২০ টাকা প্রতি পিস।
     ৭) REAP হার্ড কভার: ২০ টাকা প্রতি পিস।
     ৮) মেটাল কভার (Metal Frame Premium): ৩০ টাকা প্রতি পিস।

৩.৫. কাস্টম কম্বো প্যাকেজ তৈরির হিসাব ও ছবি দেখে প্যাকেজ বানানোর নিয়ম (Dynamic Custom Combo Package Creation):
   - কাস্টমার যদি আলাদা আলাদা কার্ড, ফিতা ও কভারের ছবি পাঠায় বা পছন্দের কথা বলে, তবে সেই ছবি/বিবরণ দেখে প্রতিটি আইটেম নির্ভুলভাবে শনাক্ত করবে।
   - হিসাব সূত্র (Package Calculation Formula):
     `প্রতি সেট প্যাকেজ মূল্য = কার্ড (৩৫৳) + ফিতা (২৫৳ বা ২৮৳) + কভার (১০৳/১২৳/১৪৳/১৬৳/২০৳/৩০৳)`
   - উদাহরণ হিসাব:
     • কার্ড (৩৫৳) + ২ সেমি ফিতা (২৮৳) + DX কভার (১২৳) = ৭৫ টাকা/পিস (১০০+ পিসের ক্ষেত্রে)।
     • কার্ড (৩৫৳) + ১.৫ সেমি ফিতা (২৫৳) + T-014V সফট কভার (১০৳) = ৭০ টাকা/পিস।
     • কার্ড (৩৫৳) + ২ সেমি ফিতা (২৮৳) + T-065V সফট কভার (১৪৳) = ৭৭ টাকা/পিস।
     • কার্ড (৩৫৳) + ২ সেমি ফিতা (২৮৳) + Xinding Q-993 কভার (১৬৳) = ৭৯ টাকা/পিস।
     • কার্ড (৩৫৳) + ২ সেমি ফিতা (২৮৳) + T-738V / T-994V / Reap কভার (২০৳) = ৮৩ টাকা/পিস।
     • কার্ড (৩৫৳) + ২ সেমি ফিতা (২৮৳) + মেটাল কভার (৩০৳) = ৯৩ টাকা/পিস (বা প্যাকেজ ৭ অনুযায়ী ৯১-৯৩৳)।
   - কাস্টমারকে প্রতিটি আইটেমের নাম ও আলাদা মূল্য স্পষ্টভাবে ভেঙে দেখিয়ে (আইটেমাইজড ব্রেকডাউন) মোট প্যাকেজ মূল্য ও কাঙ্ক্ষিত পরিমাণের মোট বাজেট অমায়িক ও প্রফেশনালভাবে বুঝিয়ে দেবে।
   - পরিমাণের টায়ার নীতি প্রযোজ্য থাকবে: ৫০–৭৯ পিসে রেগুলার ফিক্সড রেট, ৩০–৪৯ পিসে প্যাকেজ প্রতি +১০৳ বৃদ্ধি, এবং ৮০+ বা ১০০+ পিসে রেগুলার রেট থেকে শুরু করে দামাদামি করলে ধাপে ধাপে স্বল্প ছাড় দেওয়া যাবে।

৩.৬. নির্দিষ্ট প্রোডাক্টের ছবি বা রিপ্লাই দিয়ে দাম জানতে চাওয়ার নিয়ম (Specific Product Image / Reply Price Directives):
   - কাস্টমার যদি কোনো প্রোডাক্টের ছবির রিপ্লাই দিয়ে (Quoted Reply) অথবা সরাসরি কোনো ফিতা/কভার/কার্ডের ছবি দিয়ে জানতে চায়: "এই প্রোডাক্টটির দাম কত", "এই ফিতার দাম কত", "এই কভার টা কত করে", "এইটার দাম কত", "কত করে", "ভাইয়া বলেন", "???" ইত্যাদি:
     • ⚠️ কঠোর নিয়ম: কাস্টমার যে নির্দিষ্ট প্রোডাক্টটির দাম জানতে চেয়েছেন, শুধুমাত্র এবং হুবহু সেই নির্দিষ্ট প্রোডাক্টটির সঠিক নাম ও একক রেগুলার মূল্য সরাসরি ও স্পষ্টভাবে বলবে। কোনো অবস্থাতেই অপ্রাসঙ্গিক অন্য প্রোডাক্ট বা অন্য প্যাকেজের লম্বা তালিকা দেবে না।
     • প্রোডাক্ট আইডেন্টিফিকেশন ও রেট চার্ট:
       - T-014V সফট কভার: ১০ টাকা প্রতি পিস।
       - DX কভার: ১২ টাকা প্রতি পিস।
       - T-065V সফট কভার: ১৪ টাকা প্রতি পিস।
       - Xinding Q-993 কভার: ১৬ টাকা প্রতি পিস।
       - T-738V হার্ড কভার: ২০ টাকা প্রতি পিস।
       - T-994V হার্ড কভার: ২০ টাকা প্রতি পিস।
       - REAP হার্ড কভার: ২০ টাকা প্রতি পিস।
       - মেটাল কভার (Metal Frame): ৩০ টাকা প্রতি পিস।
       - ডিজিটাল সাবলিমেশন ফিতা (২ সেমি): ২৮ টাকা প্রতি পিস।
       - ডিজিটাল সাবলিমেশন ফিতা (১.৫ সেমি): ২৫ টাকা প্রতি পিস।
       - জাপানি মেশিনের UV কালার প্রিন্ট PVC আইডি কার্ড: ৩৫ টাকা প্রতি পিস।
     • রেসপন্স উদাহরণ:
       - কাস্টমার T-014V কভারের ছবি দিয়ে বা রিপ্লাই দিয়ে বললে ("এই কভার টা কত করে" / "ভাইয়া বলেন" / "???"):
         "জি {honorific}, এটি আমাদের T-014V সফট কভার। এর রেগুলার মূল্য প্রতি পিস ১০ টাকা।"
       - কাস্টমার ফিতার ছবি দিয়ে বা রিপ্লাই দিয়ে বললে ("এই ফিতার দাম কত"):
         "জি {honorific}, এটি আমাদের ২ সেন্টিমিটার প্রিমিয়াম ডিজিটাল সাবলিমেশন ফিতা। এর রেগুলার মূল্য প্রতি পিস ২৮ টাকা (১.৫ সেমি হলে ২৫ টাকা)।"
       - কাস্টমার কার্ডের ছবি দিয়ে বা রিপ্লাই দিয়ে বললে ("এই কার্ডের দাম কত"):
         "জি {honorific}, এটি আমাদের জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট প্রিমিয়াম PVC আইডি কার্ড। এর রেগুলার মূল্য প্রতি পিস ৩৫ টাকা (১০০+ পিস অর্ডারের ক্ষেত্রে)।"

৪. কাস্টম অর্ডার, পেমেন্ট পলিসি ও অ্যাডভান্স পেমেন্ট (Full COD প্রযোজ্য নয়):
   - আমাদের আইডি কার্ড, ফিতা ও কভার কাস্টমারের নিজস্ব প্রতিষ্ঠানের তথ্য ও লোগো দিয়ে তৈরি করা 'কাস্টম অর্ডার' (Custom Product)।
   - কাস্টম অর্ডারে কোনো Full Cash on Delivery (COD) প্রযোজ্য নয়।
   - অর্ডার কনফার্ম করতে Advance Payment বাধ্যতামূলক (১০,০০০-১২,০০০ টাকার অর্ডারে ১,০০০-১,৫০০ টাকা Advance, বেশি মূল্যের অর্ডারে প্রয়োজন অনুযায়ী বাড়বে)। বাকি টাকা ডেলিভারির সময় পরিশোধযোগ্য।
   - কাস্টমার যদি পুরো টাকা কুরিয়ারে দিতে চায় বা অ্যাডভান্স দিতে না চায়, তাহলে বলবে: "আমাদের পণ্যগুলো Custom Order হওয়ায় Full Cash on Delivery প্রযোজ্য নয়। কারণ আপনার প্রতিষ্ঠানের নাম ও তথ্য অনুযায়ী পণ্যগুলো বিশেষভাবে তৈরি করা হয়। তাই অর্ডার Confirm করার সময় একটি Advance Payment নেওয়া হয় এবং বাকি টাকা Delivery-এর সময় পরিশোধ করা যায়।" (ওনার স্যারের অনুমতি ছাড়া অ্যাডভান্স বাদ দেওয়া যাবে না)।

৫. তথ্য পাঠানোর দুই মাধ্যম ও অর্ডার কনফার্মেশন (WhatsApp + Google Form):
   - কাস্টমার যদি তথ্য কীভাবে দেব বা কীভাবে পাঠাতে হবে জানতে চায়, তবে সরাসরি ২টি সহজ মাধ্যমের কথা বলবে:
     "আমাদের তথ্য দেওয়ার ২টি সহজ মাধ্যম রয়েছে {honorific}:
     ১) WhatsApp: আমাদের অফিসিয়াল হোয়াটসঅ্যাপ নম্বর 01816504097-এ প্রতিষ্ঠানের নাম, লোগো এবং প্রয়োজনীয় তথ্যগুলো (বা ওয়ার্ড/এক্সেল ফাইল) সরাসরি পাঠিয়ে দিতে পারেন।
     ২) Google Form: আপনার প্রতিষ্ঠানের জন্য আমরা একটি কাস্টমাইজড গুগল ফর্ম তৈরি করে দিতে পারব, যাতে ঘরে বসেই ছাত্র-ছাত্রী বা স্টাফরা তথ্য ও ছবি সুন্দরভাবে জমা দিতে পারবেন।"
   - ⚠️ কঠোরভাবে মনে রাখবে: কাস্টমারের কাছে কখনোই ডিজাইন ফাইল (Design File) চাওয়া যাবে না। ডিজাইন আমাদের টিমই তৈরি করবে।

৬. গুগল ফর্ম ও ভিডিও পাঠানোর নিয়ম (Google Form Video & Edit Correction Video):
   - কাস্টমার গুগল ফর্ম চাইলে বলবে: "জি {honorific}, আপনার জন্য Google Form প্রস্তুত করে আমরা পাঠিয়ে দেব।" (এআই নিজে থেকে সরাসরি কোনো ফর্ম পাঠাবে না, ওনার/টিম পাঠাবেন)।
   - কাস্টমার যদি গুগল ফর্মে কীভাবে তথ্য ও ছবি দিতে হয় তা জানতে চায় বা দেখতে চায়, তখন 'গুগল ফর্মে আইডি কার্ডের তথ্য ও ছবি আপলোড করার নিয়ম' ভিডিওটি (Video 1: /static/uploads/media/google_form_submission_guide.mp4) দেবে।
   - আর কাস্টমার যদি তথ্য সাবমিট করার পর জানতে চায় যে 'তথ্য কীভাবে সংশোধন বা ঠিক করব?', তখন 'তথ্য ও ছবি সাবমিট করার পরে সংশোধনের নিয়ম' ভিডিওটি (Video 2: /static/uploads/media/google_form_edit_correction_guide.mp4) দেবে।

৭. ডেলিভারি চার্জ ও হিসাব:
   - ঢাকার ভেতরে: প্রথম ১ কেজিতে ৮০ টাকা। পরবর্তী প্রতি কেজিতে ২০ টাকা করে বাড়বে। প্রতি ১০০০ টাকায় ১০ টাকা COD/ফিওডি চার্জ যুক্ত হবে।
   - ঢাকার বাইরে: প্রথম ১ কেজিতে ১৩০ টাকা। পরবর্তী প্রতি কেজিতে ২০ টাকা করে বাড়বে। প্রতি ১০০০ টাকায় ১০ টাকা COD/ফিওডি চার্জ যুক্ত হবে।

৮. প্রোডাকশন সময় ও ডেলিভারি টাইমলাইন:
   - কাস্টমার ডেলিভারি সময় বা কতদিন লাগবে জানতে চাইলে বলবে: "আপনার কাছ থেকে প্রয়োজনীয় সব তথ্য দিয়ে Order Complete করার পর আমাদের কাজ সম্পন্ন করতে ন্যূনতম ৫ থেকে ৬ দিন সময় প্রয়োজন হবে। এরপর আমরা আপনার কাজ প্রস্তুত করে Proof দেখাব। আপনি Proof দেখে Final করলে আমরা Printing করব। Printing হওয়ার দিনই Courier করে দেব, ইনশাআল্লাহ। এরপর Courier-এর মাধ্যমে সাধারণত ২৪ থেকে ৪৮ ঘণ্টার মধ্যে আপনার পণ্য হাতে পৌঁছে যাবে, ইনশাআল্লাহ।"

৯. ভিডিও ও ভয়েস ডেমো পাঠানোর নিয়ম (Persistent Media Directives):
   - কাস্টমার যদি আমাদের আইডি কার্ড বা ফিতার কোয়ালিটি / বৈশিষ্ট্য / মান কেমন হবে জানতে চায় (যেমন: "কোয়ালিটি কেমন", "কোয়ালিটি কেমন হবে", "মান কেমন", "কার্ড ও ফিতার কোয়ালিটি কেমন হবে", "কোয়ালিটি সম্পর্কে জানতে চাই"):
     • বলবে: "জি {honorific}, আমাদের কার্ড ও ফিতার কোয়ালিটি ও বৈশিষ্ট্য কেমন হবে সে সম্পর্কে বিস্তারিত জানতে নিচের ভয়েস বার্তাটি শুনুন।"
     • এবং সাথে সাথে 'কার্ড ও ফিতা এর কোয়ালিটি কেমন হবে' ভয়েস ক্লিপটি (`/static/uploads/media/id_card_and_fita_quality.aac`) কাস্টমারকে পাঠিয়ে দেবে।
   - কাস্টমার গুগল ফর্মে কীভাবে তথ্য ও ছবি আপলোড করতে হয় জানতে চাইলে "Google Form পূরণ করার ভিডিও" (Video 1: `/static/uploads/media/google_form_submission_guide.mp4`) দেবে।
   - তথ্য সংশোধন করতে চাইলে "তথ্য সংশোধনের ভিডিও" (Video 2: `/static/uploads/media/google_form_edit_correction_guide.mp4`) দেবে।
   - প্যাকেজের ছবি পাঠানোর পর ৮০+ পিস অর্ডারে স্পেশাল অফার ভয়েস ক্লিপ (`/static/uploads/voice/PTT-20260119-WA0105.mp3`) দেবে।

৯. ভয়েস মেসেজের সরাসরি উত্তর দেওয়ার কঠোর নিয়ম:
   - কাস্টমার ভয়েস মেসেজ পাঠালে অডিওটি মনোযোগ দিয়ে শুনে কাস্টমার যা জানতে চেয়েছেন তার সরাসরি ও তাৎক্ষণিক উত্তর দেবে। কখনোই বলবে না: 'টাইপ করে দিন' বা 'ভয়েস পেয়েছি'।
   - কাস্টমার যদি ছবি/স্যাম্পল দেখতে চায়, সরাসরি বলবে: "জি {honorific}, নিচে আমাদের আকর্ষণীয় স্যাম্পল ছবিগুলো দেওয়া হলো।" এবং ছবি পাঠাবে।

১০. সালাম ও সম্ভাষণের কঠোর নিয়ম (Greeting Rule):
   - কাস্টমার সালাম দিলে শুধুমাত্র প্রথম রিপ্লাইয়ে একবার "ওয়ালাইকুমুস সালাম ওয়া রাহমাতুল্লাহ" বলবে।
   - একবার সালাম বিনিময় হয়ে গেলে পরবর্তী কোনো মেসেজে পুনরায় "ওয়ালাইকুমুস সালাম" বলবে না।
   - প্রতি মেসেজে অপ্রয়োজনীয় লম্বা ভূমিকা বা একই কথা বারবার পুনরাবৃত্তি করবে না। সরাসরি টু-দ্য-পয়েন্ট উত্তর দেবে।

১১. কাস্টমারকে সম্বোধনের কঠোর নিয়ম (Address Rule):
   - কাস্টমারকে সর্বদা {honorific} (স্যার / ম্যাম) বলে সম্মান দিয়ে কথা বলবে।
   - কাস্টমার পুরুষ হলে 'স্যার' এবং মহিলা হলে 'ম্যাম' বলবে।
   - কঠোরভাবে মনে রাখবে: কখনোই 'ভাইয়া', 'ভাই', 'আপু', 'আপা' শব্দ ব্যবহার করবে না।

১২. প্যাকেজের ছবি চাওয়ার বিশেষ নিয়ম (Package Images Protocol):
   - কাস্টমার যদি প্যাকেজ বা কম্বো প্যাকেজের ছবি দেখতে চায় (যেমন: "প্যাকেজের ছবি দিন", "প্যাকেজগুলোর ছবি দেখান", "কম্বো ছবি"):
   - টেক্সটে কোনো লম্বা প্যাকেজের তালিকা বা বিবরণী দেওয়ার কোনো প্রয়োজন নেই। শুধুমাত্র সংক্ষিপ্ত উত্তর দেবে: "জি {honorific}, অবশ্যই দিচ্ছি।" (ছবিগুলো স্বয়ংক্রিয়ভাবে কাস্টমারের কাছে চলে যাবে)।

১৩. অজানা বিষয়ের উত্তর বানিয়ে না বলা (Strict Anti-Hallucination):
   - যে পণ্য, সেবা বা পলিসি সম্পর্কে তোমার ক্যাটালগে কোনো উল্লেখ নেই, সে বিষয়ে নিজে থেকে কোনো মনগড়া উত্তর দেবে না।
   - সরাসরি বলবে: "জি {honorific}, এই বিষয়টি আমাদের টিমকে জানিয়েছি। কিছুক্ষণের মধ্যে আমাদের টিম আপনার সাথে যোগাযোগ করে সঠিক তথ্যটি জানিয়ে দেবে।"

১৪. আইডি কার্ড সংশোধন ও ম্যানুয়াল কারেকশন সংক্রান্ত নিয়ম:
   - এআই নিজে কোনো ফটোশপ এডিট বা আইডি কার্ড কারেকশন করতে পারে না। কাস্টমার কার্ডের নাম, ছবি বা কোনো তথ্যের কারেকশন চাইলে কখনোই বলবে না "আমি ঠিক করে দিচ্ছি" বা "সংশোধন হয়ে গেছে"। সরাসরি বলবে: "জি {honorific}, আপনার সংশোধনের বিষয়টি আমাদের মূল টিমকে জানিয়েছি। আমাদের ডিজাইন টিম এটি দেখে আপনাকে মেসেজ দেবে।"

১৫. স্মৃতিশক্তি ও পূর্ববর্তী কথোপকথন মনে রাখা (পূর্ববর্তী চ্যাট হিস্ট্রি ও পরিচিত তথ্য পুনরায় জিজ্ঞাসা না করা):
   - চ্যাট হিস্ট্রিতে বা পূর্ববর্তী আলাপে কাস্টমার বা মূল অ্যাডমিন ইতিপূর্বে যেসব তথ্যের উত্তর দিয়ে দিয়েছেন (যেমন: প্রতিষ্ঠানের নাম, মোবাইল নম্বর), সেই একই কথা বা প্রশ্ন কখনোই পুনরায় জিজ্ঞাসা করবে না।

১৬. অপ্রয়োজনীয় প্রশ্ন ও ফিলার বাক্য পরিহার করা (No Unnecessary Questions & No Filler):
   - কাস্টমারের অনুরোধ স্পষ্ট হলে সরাসরি কাজটি সম্পন্ন করবে বা উত্তর দেবে।
   - কথোপকথন দীর্ঘায়িত করার জন্য কখনোই "আর কিছু লাগবে?", "আর কোনো সাহায্য লাগবে?", "আপনি কি নিশ্চিত?", "কিছু পরিবর্তন করতে চান?" এমন অপ্রয়োজনীয় প্রশ্ন বা বাক্য যোগ করবে না।

১৭. স্ক্রিনশট ও ছবির নিখুঁত পর্যবেক্ষণ (Screenshot & Image Understanding):
   - কাস্টমারের পাঠানো স্ক্রিনশট ও ছবির প্রতিটি দৃশ্যমান টেক্সট, নাম, মোবাইল নম্বর, প্রতিষ্ঠানের নাম, ভুলত্রুটি বা সংশোধন নির্দেশ মনোযোগ সহকারে পড়বে। ছবিতে যা নেই বা স্পষ্ট নয়, তা নিজে থেকে আন্দাজে বানিয়ে বলবে না।

১৮. পূর্ববর্তী প্রসঙ্গের ধারাবাহিকতা রক্ষা (Context Continuity):
   - কাস্টমার যদি ছোট কোনো মেসেজ দেয় (যেমন: "ওটা", "হ্যাঁ", "এইটাই", "আগেরটার মতো", "ওই কার্ডটা", "আগের নামটাই থাকবে"), তবে পূর্ববর্তী কথোপকথন দেখে রেফারেন্স বুঝে সরাসরি প্রাসঙ্গিক উত্তর দেবে।

১৯. প্রডাক্ট ক্যাটালগ ও মূল্য তালিকা:
{catalog}
{training_text}
{faq_text}
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

def extract_order_quantity_number(text: str) -> Optional[int]:
    """
    Extracts order quantity integer from text supporting Bengali & English digits/words.
    Strictly ignores phone numbers, prices (টাকা/tk/৳), dates, and non-quantity digits.
    """
    if not text:
        return None
        
    # Ignore if text is or contains a phone number (e.g., 01929778281, 01816504097, +8801...)
    cleaned_digits_only = re.sub(r'\D', '', text)
    if len(cleaned_digits_only) >= 10:
        return None
    if re.search(r'(?:\+?880?1|01)[3-9]\d{8}', text):
        return None

    bengali_digits = {'০': '0', '১': '1', '২': '2', '৩': '3', '৪': '4', '৫': '5', '৬': '6', '৭': '7', '৮': '8', '৯': '9'}
    cleaned = ''
    for ch in text:
        cleaned += bengali_digits.get(ch, ch)
    cleaned_lower = cleaned.lower().strip()
    
    # Ignore if talking about money/prices without explicit quantity words
    if any(k in cleaned_lower for k in ["টাকা", "টাকার", "tk", "taka", "৳", "রেট", "মূল্য", "খরচ"]) and not any(k in cleaned_lower for k in ["পিস", "pcs", "টা", "টি", "কপি", "বানাবো"]):
        return None

    # Range pattern: e.g. "2-3 শত", "2-3 sho", "2-3শ", "200-300 পিস", "৫০-১০০ পিস"
    m_range_hundreds = re.search(r'(\d+)\s*[-/toথেকে]+\s*(\d+)\s*(?:শত|শ|sho|শো)', cleaned_lower)
    if m_range_hundreds:
        try:
            return int(m_range_hundreds.group(1)) * 100
        except Exception:
            pass

    m_range = re.search(r'(\d+)\s*[-/toথেকে]+\s*(\d+)\s*(?:পিস|পিসেস|টা|টি|pcs|pc|pieces|piece|কপি)?', cleaned_lower)
    if m_range:
        try:
            val = int(m_range.group(1))
            if 1 <= val <= 50000:
                return val
        except Exception:
            pass

    # Hundred multipliers: e.g. "5 শ", "5শ", "5 শত", "২ শত", "৩ শ", "5 sho"
    m_hundred = re.search(r'(\d+)\s*(?:শত|শ|sho|শো)\s*(?:পিস|পিসেস|টা|টি|pcs|pc|pieces|piece|কপি)?', cleaned_lower)
    if m_hundred:
        try:
            return int(m_hundred.group(1)) * 100
        except Exception:
            pass

    # Word based numbers in bengali
    bengali_words = [
        ('এক হাজার', 1000), ('হাজার', 1000), ('পাঁচশত', 500), ('পাঁচশ', 500),
        ('চারশত', 400), ('চারশ', 400),
        ('তিনশত', 300), ('তিনশ', 300), ('দুইশত', 200), ('দুইশ', 200),
        ('একশত', 100), ('একশ', 100), ('নব্বই', 90), ('আশি', 80), ('সত্তর', 70),
        ('ষাট', 60), ('পঞ্চাশ', 50), ('পঁঞ্চাশ', 50), ('চল্লিশ', 40),
        ('ত্রিশ', 30), ('তিরিশ', 30), ('পঁচিশ', 25), ('পচিশ', 25),
        ('বিশ', 20), ('কুড়ি', 20), ('পনেরো', 15), ('পনের', 15), ('দশ', 10), ('পাঁচ', 5)
    ]
    for word, val in bengali_words:
        if re.search(r'(?:^|\s)' + re.escape(word) + r'(?:\s|$|টা|টি|পিস|টি|পিসেস|pcs|ta|ti|কপি)', cleaned_lower):
            return val

    # Match explicit quantity units: e.g. "50 পিস", "100 pcs", "30 টা", "80 টি", "100 জন", "50 কপি"
    m_unit = re.search(r'(\d+)\s*(?:পিস|পিসেস|টা|টি|pcs|pc|pieces|piece|জন|কপি|set|সেট)', cleaned_lower)
    if m_unit:
        try:
            val = int(m_unit.group(1))
            if 1 <= val <= 50000:
                return val
        except Exception:
            pass

    # Match standalone digit only if it's a small standalone number (e.g. "50", "100", "30", "500") and NOT a phone or price
    if re.fullmatch(r'\d{1,5}', cleaned_lower):
        val = int(cleaned_lower)
        if 1 <= val <= 20000:
            return val

    return None

def get_id_card_sample_images(workspace_id: int = 1) -> list:
    """Returns all 15 ID card sample images."""
    images = []
    img_dir = settings.STATIC_DIR / "uploads" / "id_card"
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.*")):
            if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                url = f"/static/uploads/id_card/{f.name}"
                if url not in images:
                    images.append(url)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image_url, gallery_images FROM products WHERE workspace_id = ? AND is_active = 1 AND (category LIKE '%কার্ড%' OR category LIKE '%আইডি%' OR code LIKE '%IDC%')", (int(workspace_id or 1),))
        for p in cursor.fetchall():
            if p["image_url"] and p["image_url"] not in images:
                images.append(p["image_url"])
            try:
                for gu in json.loads(p["gallery_images"] or "[]"):
                    u = gu.get("url") if isinstance(gu, dict) else gu
                    if u and u not in images:
                        images.append(u)
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    return images

def get_fita_sample_images(workspace_id: int = 1) -> list:
    """Returns all 8 Fita sample images."""
    images = []
    img_dir = settings.STATIC_DIR / "uploads" / "fita"
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.*")):
            if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                url = f"/static/uploads/fita/{f.name}"
                if url not in images:
                    images.append(url)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image_url, gallery_images FROM products WHERE workspace_id = ? AND is_active = 1 AND (category LIKE '%ফিতা%' OR category LIKE '%ল্যানিয়ার্ড%' OR code LIKE '%LAN%')", (int(workspace_id or 1),))
        for p in cursor.fetchall():
            if p["image_url"] and p["image_url"] not in images:
                images.append(p["image_url"])
            try:
                for gu in json.loads(p["gallery_images"] or "[]"):
                    u = gu.get("url") if isinstance(gu, dict) else gu
                    if u and u not in images:
                        images.append(u)
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    return images

def get_cover_sample_images(workspace_id: int = 1) -> list:
    """Returns all 8 Cover sample images."""
    images = []
    img_dir = settings.STATIC_DIR / "uploads" / "cover"
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.*")):
            if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                url = f"/static/uploads/cover/{f.name}"
                if url not in images:
                    images.append(url)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image_url, gallery_images FROM products WHERE workspace_id = ? AND is_active = 1 AND (category LIKE '%কভার%' OR category LIKE '%হোল্ডার%' OR code LIKE '%COV%')", (int(workspace_id or 1),))
        for p in cursor.fetchall():
            if p["image_url"] and p["image_url"] not in images:
                images.append(p["image_url"])
            try:
                for gu in json.loads(p["gallery_images"] or "[]"):
                    u = gu.get("url") if isinstance(gu, dict) else gu
                    if u and u not in images:
                        images.append(u)
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    return images

def get_package_sample_images(workspace_id: int = 1) -> list:
    """Returns all 7 Package sample images."""
    images = []
    img_dir = settings.STATIC_DIR / "uploads" / "package"
    if img_dir.exists():
        for f in sorted(img_dir.glob("*.*")):
            if f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
                url = f"/static/uploads/package/{f.name}"
                if url not in images:
                    images.append(url)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT image_url, gallery_images FROM products WHERE workspace_id = ? AND is_active = 1 AND (category LIKE '%প্যাকেজ%' OR category LIKE '%কম্বো%' OR code LIKE '%PKG%' OR code LIKE '%COMBO%')", (int(workspace_id or 1),))
        for p in cursor.fetchall():
            if p["image_url"] and p["image_url"] not in images:
                images.append(p["image_url"])
            try:
                for gu in json.loads(p["gallery_images"] or "[]"):
                    u = gu.get("url") if isinstance(gu, dict) else gu
                    if u and u not in images:
                        images.append(u)
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    return images

REVIEW_FACEBOOK_POST_URL = "https://www.facebook.com/share/p/19Agfhw4gv/"
VOICE_PACKAGE_SPECIAL_OFFER = "/static/uploads/voice/PTT-20260119-WA0105.mp3"

def build_full_sample_sequence(quantity: int = None, customer_name: str = "Customer", workspace_id: int = 1) -> list:
    """
    Returns the complete phased sample sequence according to strict training:
    1. Initial Cards (15 photos)
    2. Text: "এগুলো আমাদের কার্ড, আমাদের তৈরি করা কার্ড।"
    3. Fita (8 photos)
    4. Text: "এগুলো আমাদের প্রিন্ট করা ফিতা।"
    5. Covers (8 photos)
    6. Voice Note (Special Offer voice note PTT-20260119-WA0105.mp3 if quantity >= 80 or not specified)
    7. Review Link: "আমাদের কাজের কোয়ালিটি ও সম্মানিত কাস্টমারদের রিভিউ দেখতে আমাদের ফেসবুক পেজের এই পোস্টটি দেখতে পারেন: https://www.facebook.com/share/p/19Agfhw4gv/"
    8. Package sample photos (7 photos)
    9. Concluding question / tier text based on quantity.
    """
    honorific = detect_customer_gender_title(customer_name)
    seq = []
    
    # 1. Cards (15 photos) + Text
    id_card_imgs = get_id_card_sample_images(workspace_id=workspace_id)
    if id_card_imgs:
        seq.append({"type": "images", "category": "id_card", "urls": id_card_imgs})
        seq.append({"type": "text", "text": f"এগুলো আমাদের কার্ড, আমাদের তৈরি করা কার্ড।"})

    # 2. Fita (8 photos) + Text
    fita_imgs = get_fita_sample_images(workspace_id=workspace_id)
    if fita_imgs:
        seq.append({"type": "images", "category": "fita", "urls": fita_imgs})
        seq.append({"type": "text", "text": f"এগুলো আমাদের প্রিন্ট করা ফিতা।"})

    # 3. Covers (8 photos)
    cover_imgs = get_cover_sample_images(workspace_id=workspace_id)
    if cover_imgs:
        seq.append({"type": "images", "category": "cover", "urls": cover_imgs})

    # 4. Review Link for customer trust
    seq.append({
        "type": "text",
        "text": f"আমাদের কাজের কোয়ালিটি ও সম্মানিত কাস্টমারদের রিভিউ দেখতে আমাদের ফেসবুক পেজের এই পোস্টটি দেখতে পারেন:\n{REVIEW_FACEBOOK_POST_URL}"
    })

    # 5. Packages (7 photos)
    pkg_imgs = get_package_sample_images(workspace_id=workspace_id)
    if pkg_imgs:
        seq.append({"type": "images", "category": "package", "urls": pkg_imgs})

    # 6. Voice Note (Special Offer immediately after the 7 packages)
    if quantity is None or quantity >= 80:
        seq.append({
            "type": "voice",
            "url": VOICE_PACKAGE_SPECIAL_OFFER,
            "text": f"প্যাকেজের বিস্তারিত ও স্পেশাল অফার সংক্রান্ত ভয়েস বার্তাটি শুনুন {honorific}।"
        })

    # 7. Post-package Voice Note / Tier explanation
    if quantity is not None:
        if 30 <= quantity < 50:
            seq.append({
                "type": "text",
                "text": f"আমাদের প্যাকেজগুলোর রেট ১০০+ অর্ডারের ক্ষেত্রে প্রযোজ্য। আপনাদের যেহেতু ১০০ এর কম ({quantity} পিস), তাই প্রতি প্যাকেজে ১০ টাকা করে বেশি হবে। আপনার কোন প্যাকেজটি পছন্দ জানাবেন {honorific}।"
            })
        elif 50 <= quantity < 80:
            seq.append({
                "type": "text",
                "text": f"প্যাকেজের ছবিতে উল্লেখিত রেগুলার মূল্যে আমরা আপনার কাজটি নিখুঁতভাবে তৈরি করে দেব। আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন {honorific}।"
            })
        else:
            seq.append({
                "type": "text",
                "text": f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন {honorific}।"
            })
    else:
        seq.append({
            "type": "text",
            "text": f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন {honorific}।"
        })
        
    return seq

def evaluate_id_card_workflow(
    message_text: str = "",
    conversation_history: list = None,
    customer_name: str = "Customer",
    workspace_id: int = 1
) -> Optional[dict]:
    """
    Strictly evaluates ID Card Inquiry, MOQ restriction (30 pcs), Review Link, Packages, and Phased Sample Delivery.
    """
    if int(workspace_id or 1) != 1:
        return None

    msg = (message_text or "").strip().lower()
    if not msg:
        return None

    honorific = detect_customer_gender_title(customer_name)
    
    # 0. Check phone numbers, WhatsApp references, complaints, or questions about sending media
    if any(k in msg for k in ["নাম্বার", "নম্বর", "নাম্বার দিতে", "দিতে বলেছিলেন", "এগুলো কেন", "দিচ্ছেন কেন", "whatsapp", "হোয়াটসঅ্যাপ"]):
        return None
        
    msg_without_system_tags = re.sub(r'\[কাস্টমার পূর্ববর্তী.*?\]', '', msg)
    cleaned_digits = re.sub(r'\D', '', msg_without_system_tags)
    if len(cleaned_digits) >= 10 and (re.search(r'01[3-9]\d{8}', msg_without_system_tags) or re.search(r'8801[3-9]\d{8}', msg_without_system_tags) or len(msg_without_system_tags.strip().split()) <= 2):
        return None

    # 0.1 Check cancellation / refusal / not interested
    refusal_phrases = [
        "চাচ্ছি না", "চাই না", "লাগবে না", "আর লাগবে না", "দরকার নেই", "দরকার নাই",
        "বানাতে চাচ্ছি না", "বানাব না", "বানাবো না", "করব না", "করবো না",
        "লাগবে না তো", "লাগবে না আমার", "নিব না", "নেব না", "দরকার নাই তো",
        "stop", "cancel", "not interested"
    ]
    is_refusing = any(rp in msg for rp in refusal_phrases) or (len(msg.split()) == 1 and msg.strip() in ["না", "no"])
    if is_refusing:
        return {
            "reply_text": f"জি {honorific}, ঠিক আছে, কোনো সমস্যা নেই। পরবর্তীতে আপনার অন্য কোনো সার্ভিস বা তথ্যের প্রয়োজন হলে অবশ্যই জানাবেন।",
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "customer_not_interested"
        }

    # Check if customer is asking about an individual item's price (ribbon, card, cover)
    is_package_photo_quoted = any(k in msg for k in ["package", "wa0002", "wa0003", "wa0006", "wa0057", "wa0023", "wa0045", "wa0081", "প্যাকেজ"])
    is_specific_item_inquiry = not is_package_photo_quoted and any(k in msg for k in [
        "এই ফিতা", "এই কভার", "এই কার্ড", "এই প্রোডাক্ট", "এইটার দাম", "এটার দাম",
        "কভার টা কত", "কভার কত", "ফিতা কত", "কার্ড কত", "কত করে", "ফিতার দাম", "কভারের দাম",
        "এই ফিতার দাম", "এই কভারের দাম", "এই কার্ডের দাম", "প্রোডাক্টটির দাম", "প্রোডাক্টের দাম",
        "ভাইয়া বলেন", "ভাইয়া বলেন", "বলেন", "???", "??"
    ])
    if is_specific_item_inquiry:
        return None

    # Check if customer is asking about card/fita quality or features
    is_asking_quality = any(k in msg for k in [
        "কোয়ালিটি কেমন হবে", "কোয়ালিটি কেমন হবে", "কোয়ালিটি কেমন", "কোয়ালিটি কেমন", "মান কেমন",
        "কোয়ালিটি সম্পর্কে", "কোয়ালিটি সম্পর্কে", "কোয়ালিটি সম্পরকে", "কোয়ালিটি সম্পরকে",
        "কোয়ালিটি জানতে চাই", "কোয়ালিটি জানতে চাই", "কোয়ালিটি", "কোয়ালিটি",
        "কার্ড ও ফিতার কোয়ালিটি", "কার্ড ও ফিতা এর কোয়ালিটি", "কার্ড ও ফিতা এর কোয়ালিটি"
    ]) and not any(k in msg for k in ["প্যাকেজ", "প্যাকেজের", "দাম কত", "কত করে", "খরচ কত"])
    if is_asking_quality:
        return {
            "reply_text": f"জি {honorific}, আমাদের কার্ড ও ফিতার কোয়ালিটি ও বৈশিষ্ট্য কেমন হবে সে সম্পর্কে বিস্তারিত জানতে নিচের ভয়েস বার্তাটি শুনুন:",
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "/static/uploads/media/id_card_and_fita_quality.aac",
            "video_url": "",
            "order_created": None,
            "response_source": "id_card_quality_voice_dispatch"
        }

    # Check history context for bot questions and prior quantity
    last_bot_msg = ""
    history_qty = None
    if conversation_history:
        for m in reversed(conversation_history):
            sender_val = str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower()
            if sender_val in ("bot", "assistant", "seller") and not last_bot_msg:
                last_bot_msg = (m.get("content") or m.get("text") or "").lower()
            elif sender_val in ("user", "customer") and history_qty is None:
                history_qty = extract_order_quantity_number((m.get("content") or m.get("text") or "").lower())

    bot_asked_quantity = any(k in last_bot_msg for k in [
        "কত পিস বানাবেন", "কত পিস", "কতগুলো বানাবেন", "কত পিস প্রয়োজন", "কত পিস লাগবে", "পরিমাণ কত"
    ])

    qty = extract_order_quantity_number(msg)
    if qty is None and history_qty is not None:
        effective_qty = history_qty
    else:
        effective_qty = qty
    
    # Check if message is ID card related (and not negative)
    is_id_card_inquiry = any(k in msg for k in [
        "আইডি কার্ড", "আইডি কাড", "id card", "আইডিকার্ড", "আইডি", "কার্ড বানাতে", "কার্ড করতে", 
        "কার্ড বানাবো", "কার্ড লাগবে", "কার্ডের দাম", "কার্ডের খরচ", "কার্ডের স্যাম্পল"
    ]) and not any(k in msg for k in ["চাচ্ছি না", "চাই না", "বানাব না", "বানাবো না", "করব না", "করবো না", "লাগবে না", "নেব না", "নিব না", "দরকার নাই", "দরকার নেই"])

    # Case A: Initial ID card inquiry without quantity stated
    if is_id_card_inquiry and qty is None:
        gave_salam = any(k in msg for k in ["সালাম", "salam", "আসসালামু", "assalamu", "slm"])
        greeting = f"ওয়ালাইকুমুস সালাম {honorific}।" if gave_salam else f"জি {honorific},"
        return {
            "reply_text": f"{greeting} অবশ্যই। আপনি আমাদের কাছ থেকে আইডি কার্ড, ফিতা এবং কভারের ফুল প্যাকেজ নিতে পারবেন। আপনার কত পিস প্রয়োজন জানাবেন প্লিজ?",
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "id_card_ask_quantity"
        }

    # Case B: Answering quantity
    is_asking_question = any(k in msg for k in ["?", "কত", "কেন", "কি", "কী", "দাম", "চার্জ", "সময়", "কেমন", "ডেলিভারি", "কোথায়"])
    is_answering_quantity = (
        qty is not None and not is_asking_question and (
            bot_asked_quantity or 
            any(k in msg for k in ["পিস", "টা", "টি", "pcs", "কপি", "বানাবো", "বানাতে চাই"]) or
            re.fullmatch(r'\d{1,5}', msg.strip())
        )
    )
    
    if qty is not None and is_answering_quantity:
        if qty < 30:
            return {
                "reply_text": f"দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।",
                "media_sequence": [],
                "matched_images": [],
                "voice_url": "",
                "video_url": "",
                "order_created": None,
                "response_source": "id_card_moq_under_30"
            }
        else:
            # Check if package samples were already sent in recent conversation history!
            already_sent_packages = False
            if conversation_history:
                recent_bot_msgs = [
                    m.get("content", "") for m in conversation_history[-6:]
                    if str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower() in ("bot", "assistant")
                ]
                already_sent_packages = any(
                    any(ext in bm for ext in ["pakage", "package", "pkg", "/uploads/package"]) or
                    "প্যাকেজগুলো পাঠানো হলো" in bm or "প্যাকেজের ছবি" in bm
                    for bm in recent_bot_msgs
                )

            if already_sent_packages:
                if 30 <= qty < 50:
                    tier_text = f"জি {honorific}, আমাদের প্যাকেজগুলোর রেট ১০০+ অর্ডারের ক্ষেত্রে প্রযোজ্য। আপনার যেহেতু ১০০ এর কম ({qty} পিস), তাই প্রতি প্যাকেজে ১০ টাকা করে বেশি হবে। আপনার কোন প্যাকেজটি পছন্দ জানাবেন প্লিজ।"
                elif 50 <= qty < 80:
                    tier_text = f"জি {honorific}, প্যাকেজের ছবিতে উল্লেখিত রেগুলার মূল্যে আমরা আপনার কাজটি নিখুঁতভাবে তৈরি করে দেব। আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন প্লিজ।"
                else:
                    tier_text = f"জি {honorific}, আপনার {qty} পিস অর্ডারের জন্য স্পেশাল প্যাকেজ প্রযোজ্য হবে। আপনার কোন প্যাকেজটি পছন্দ জানাবেন প্লিজ।"
                return {
                    "reply_text": tier_text,
                    "media_sequence": [],
                    "matched_images": [],
                    "voice_url": "",
                    "video_url": "",
                    "order_created": None,
                    "response_source": "id_card_tier_text_reply"
                }

            seq = build_full_sample_sequence(quantity=qty, customer_name=customer_name, workspace_id=workspace_id)
            pkg_imgs = get_package_sample_images(workspace_id)
            voice_to_send = VOICE_PACKAGE_SPECIAL_OFFER if qty >= 80 else ""
            return {
                "reply_text": f"জি {honorific}, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।",
                "media_sequence": seq,
                "matched_images": pkg_imgs,
                "voice_url": voice_to_send,
                "video_url": "",
                "order_created": None,
                "response_source": "id_card_sample_dispatch"
            }

    # Case C: Asking specifically for packages or samples
    is_package_request = any(k in msg for k in [
        "প্যাকেজ", "প্যাকেজের ছবি", "প্যাকেজ দেখান", "প্যাকেজ পাঠান", "প্যাকেজের তালিকা",
        "কম্বো", "কম্বো প্যাকেজ", "package", "combo", "পেকেজ", "স্যাম্পল", "স্যাম্পল দেখান", "স্যাম্পল পাঠান", "স্যাম্পল দিন"
    ]) and not any(k in msg for k in ["এটি", "এটা", "এইটা", "এই প্যাকেজ", "পছন্দ", "নির্বাচন"])
    if is_package_request:
        seq = build_full_sample_sequence(quantity=effective_qty, customer_name=customer_name, workspace_id=workspace_id)
        pkg_imgs = get_package_sample_images(workspace_id=workspace_id)
        voice_to_send = VOICE_PACKAGE_SPECIAL_OFFER if (effective_qty is None or effective_qty >= 80) else ""

        return {
            "reply_text": f"জি {honorific}, তাহলে আমি আপনাকে আমাদের স্যাম্পলগুলো পাঠিয়ে দিচ্ছি।",
            "media_sequence": seq,
            "matched_images": pkg_imgs,
            "voice_url": voice_to_send,
            "video_url": "",
            "order_created": None,
            "response_source": "package_sample_dispatch"
        }

    # Case D: Customer quotes / selects a package photo (e.g. replies with ".", ",", "এটি", "এইটা", "এই প্যাকেজটি", "প্যাকেজ ৩", etc.)
    is_package_selection = (
        any(k in msg for k in [
            "[কাস্টমার পূর্ববর্তী এই ছবির রিপ্লাই দিয়েছেন:", "প্যাকেজের রিপ্লাই", "package", "wa0002", "wa0003",
            "wa0006", "wa0057", "wa0023", "wa0045", "wa0081"
        ]) or
        (
            any(k in last_bot_msg for k in ["কোন প্যাকেজ", "প্যাকেজটি পছন্দ", "প্যাকেজের ছবি", "প্যাকেজ পছন্দ", "প্যাকেজগুলো পাঠানো হলো", "পছন্দ হয় জানাবেন", "পছন্দ হয়েছে"]) and
            any(k in msg for k in [
                "এটি", "এটা", "এইটা", "এই প্যাকেজ", "এই প্যাকেজটি", "এই প্যাকেজটা", "প্যাকেজ", "পছন্দ",
                "এটি পছন্দ", "এটা পছন্দ", "এইটা পছন্দ", "এটি ভালো", "এটা দেন", "এটি দেন", "এইটা দেন",
                "প্যাকেজ ১", "প্যাকেজ ২", "প্যাকেজ ৩", "প্যাকেজ ৪", "প্যাকেজ ৫", "প্যাকেজ ৬", "প্যাকেজ ৭",
                "১", "২", "৩", "৪", "৫", "৬", "৭", "1", "2", "3", "4", "5", "6", "7", ".", ","
            ])
        )
    )

    if is_package_selection and not is_refusing:
        tier_note = ""
        if effective_qty is not None and 30 <= effective_qty < 50:
            tier_note = f"\n(যেহেতু আপনাদের পরিমাণ {effective_qty} পিস—১০০ এর কম, তাই প্যাকেজের রেগুলার মূল্যের সাথে প্রতি পিসে ১০ টাকা যোগ হবে।)\n"
            
        ack_text = (
            f"জি {honorific}, চমৎকার পছন্দ! আপনি আমাদের এই আকর্ষণীয় প্যাকেজটি নির্বাচন করেছেন।{tier_note}\n\n"
            f"আপনার অর্ডারটি চূড়ান্ত করতে অনুগ্রহ করে নিচের তথ্যগুলো দিন:\n"
            f"১. প্রতিষ্ঠানের নাম:\n"
            f"২. পূর্ণাঙ্গ ঠিকানা:\n"
            f"৩. যোগাযোগের মোবাইল নম্বর:\n\n"
            f"তথ্যগুলো দিলে আমরা সাথে সাথে ছবি ও তথ্য আপলোড করার জন্য একটি ডেডিকেটেড গুগল ফর্ম লিংক পাঠিয়ে দেব {honorific}।"
        )
        return {
            "reply_text": ack_text,
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "id_card_package_selection_acknowledged"
        }

    is_sample_request = any(k in msg for k in [
        "স্যাম্পল দেখান", "স্যাম্পল পাঠান", "স্যাম্পল দেন", "স্যাম্পল দিন", "স্যাম্পল দেখতে চাই",
        "ছবি দেখান", "ছবি পাঠান", "ছবি দেন", "ছবি দিন", "ছবি দেখতে চাই",
        "পিক দেখান", "পিক পাঠান", "পিক দেন", "ফটো দেখান", "ফটো পাঠান"
    ])
    if is_sample_request:
        if any(k in msg for k in ["ফিতা", "রিবন", "ল্যানিয়ার্ড", "fita", "lanyard"]):
            fita_imgs = get_fita_sample_images(workspace_id=workspace_id)
            return {
                "reply_text": f"জি {honorific}, নিচে আমাদের ফিতার স্যাম্পল ছবিগুলো দেওয়া হলো:",
                "media_sequence": [
                    {"type": "images", "category": "fita", "urls": fita_imgs},
                    {"type": "text", "text": "এগুলো আমাদের প্রিন্ট করা ফিতা।"}
                ],
                "matched_images": fita_imgs,
                "voice_url": "",
                "video_url": "",
                "order_created": None,
                "response_source": "fita_sample_dispatch"
            }
        elif any(k in msg for k in ["কভার", "হোল্ডার", "cover", "holder"]):
            cover_imgs = get_cover_sample_images(workspace_id=workspace_id)
            return {
                "reply_text": f"জি {honorific}, নিচে আমাদের কভারের স্যাম্পল ছবিগুলো দেওয়া হলো:",
                "media_sequence": [
                    {"type": "images", "category": "cover", "urls": cover_imgs}
                ],
                "matched_images": cover_imgs,
                "voice_url": "",
                "video_url": "",
                "order_created": None,
                "response_source": "cover_sample_dispatch"
            }
        elif any(k in msg for k in ["কার্ড", "আইডি", "card", "id"]):
            card_imgs = get_id_card_sample_images(workspace_id=workspace_id)
            return {
                "reply_text": f"জি {honorific}, নিচে আমাদের কার্ডের স্যাম্পল ছবিগুলো দেওয়া হলো:",
                "media_sequence": [
                    {"type": "images", "category": "id_card", "urls": card_imgs},
                    {"type": "text", "text": "এগুলো আমাদের কার্ড, আমাদের তৈরি করা কার্ড।"}
                ],
                "matched_images": card_imgs,
                "voice_url": "",
                "video_url": "",
                "order_created": None,
                "response_source": "id_card_sample_dispatch"
            }
        else:
            # General sample request -> Send package samples only!
            pkg_imgs = get_package_sample_images(workspace_id=workspace_id)
            seq = [
                {
                    "type": "text",
                    "text": f"আমাদের কাজের কোয়ালিটি ও সম্মানিত কাস্টমারদের রিভিউ দেখতে আমাদের ফেসবুক পেজের এই পোস্টটি দেখতে পারেন:\n{REVIEW_FACEBOOK_POST_URL}"
                },
                {"type": "images", "category": "package", "urls": pkg_imgs},
                {"type": "text", "text": f"আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন {honorific}।"}
            ]
            return {
                "reply_text": f"জি {honorific}, নিচে আমাদের আকর্ষণীয় প্যাকেজ স্যাম্পলগুলো দেওয়া হলো:",
                "media_sequence": seq,
                "matched_images": pkg_imgs,
                "voice_url": "",
                "video_url": "",
                "order_created": None,
                "response_source": "package_sample_dispatch"
            }

    return None

def get_category_batch_images(category_or_code: str, requested_count: int = None, workspace_id: int = 1) -> list:
    """
    Returns sample gallery images for a specific product category within a workspace.
    """
    cat_lower = (category_or_code or "").strip().lower()
    
    if int(workspace_id or 1) == 1:
        if cat_lower in ["fita", "lanyard", "ribbon", "fita-02", "lan-15", "lan-20", "ফিতা", "রিবন", "ল্যানিয়ার্ড"]:
            imgs = get_fita_sample_images(workspace_id=workspace_id)
            return imgs[:requested_count] if requested_count and requested_count > 0 else imgs
        elif cat_lower in ["cov", "cover", "holder", "cov-01", "cov-03", "কভার", "হোল্ডার"]:
            imgs = get_cover_sample_images(workspace_id=workspace_id)
            return imgs[:requested_count] if requested_count and requested_count > 0 else imgs
        elif cat_lower in ["idc", "card", "id card", "idc-01", "আইডি", "কার্ড", "পিভিসি"]:
            imgs = get_id_card_sample_images(workspace_id=workspace_id)
            return imgs[:requested_count] if requested_count and requested_count > 0 else imgs
        elif cat_lower in ["pkg", "package", "combo", "pkg-combo", "প্যাকেজ", "পেকেজ", "কম্বো"]:
            imgs = get_package_sample_images(workspace_id=workspace_id)
            return imgs[:requested_count] if requested_count and requested_count > 0 else imgs

    return []

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
    Strict detection for sending sample photos. ONLY sends if customer EXPLICITLY requested photos in user_msg.
    Never sends photos if user is just asking questions, sending phone number, or discussing price.
    """
    msg = (user_msg or "").strip().lower()
    
    # 1. Stop / Cancellation check
    stop_phrases = [
        "লাগবে না", "আর লাগবে না", "থামুন", "আর দিয়েন না", "আর পাঠাবেন না", 
        "ছবি লাগবে না", "ফটো লাগবে না", "আর না", "চাই না", "আর দিও না",
        "stop", "no more", "don't send", "dont send"
    ]
    if any(sp in msg for sp in stop_phrases):
        return []

    # Ignore phone numbers and common non-photo messages
    cleaned_digits = re.sub(r'\D', '', msg)
    if len(cleaned_digits) >= 10:
        return []
    if any(k in msg for k in ["নাম্বার", "নম্বর", "whatsapp", "কেন দিচ্ছেন", "এগুলো কেন", "দাম কত", "কত করে", "খরচ কত"]):
        return []

    # 2. Check if photos are requested explicitly in user message OR agreed to when bot specifically offered
    is_explicit_photo_req = any(k in msg for k in [
        "ছবি দেখতে চাই", "ছবি দেখান", "ছবি পাঠান", "ছবি পাঠাও", "ছবি দেখাও", "ছবি দেন", "ছবি দিন",
        "স্যাম্পল দেখান", "স্যাম্পল পাঠান", "স্যাম্পল দেন", "স্যাম্পল দিন", "স্যাম্পল দেখতে চাই",
        "পিক দেখান", "পিক দেন", "পিক পাঠান", "পিকচার দেখান", "পিকচার পাঠান", "ফটো দেখান", "ফটো পাঠান", "ফটো দেন",
        "সব ছবি", "সবগুলো ছবি", "সব প্যাকেজ", "সবগুলো প্যাকেজ", "প্যাকেজের ছবি",
        "show photo", "send photo", "show sample", "send sample", "show pic", "send pic", "show image", "send image"
    ]) or (any(k in msg for k in ["ছবি", "স্যাম্পল", "ফটো", "পিক", "পিকচার"]) and any(a in msg for a in ["দেখান", "পাঠান", "দিন", "দেন", "দেখবো", "show", "send"]))

    last_bot_msg = ""
    if conversation_history:
        for m in reversed(conversation_history):
            sender_val = str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower()
            if sender_val in ("bot", "assistant", "seller"):
                last_bot_msg = (m.get("content") or m.get("text") or "").lower()
                break

    bot_offered_photos_last_turn = any(k in last_bot_msg for k in [
        "ছবি দেখতে চান", "স্যাম্পল দেখতে চান", "ছবি পাঠাব", "স্যাম্পল পাঠাব", "ছবি দেব", "পিকচার দেখতে চান", "স্যাম্পল দেব", "ছবি পাঠাবো", "স্যাম্পল ছবিগুলো দিতে সুবিধা হতো", "স্যাম্পল ছবিগুলো দিতে"
    ])

    agreement_keywords = [
        "হ্যাঁ", "পাঠান", "দেখান", "জি", "হুম", "পাঠাও", "দেখাও", "দিলে ভালো", "দিলে ভালো হয়", "সবই লাগবে", "সব লাগবে", "সবকিছু লাগবে", "কম্বো", "প্যাকেজ",
        "yes", "sure", "ok", "okay", "send", "show", "ha", "ji", "achha", "yep", "yeah", "সেন্ড করুন"
    ]
    is_agreeing_to_photo = any(k == msg or msg.startswith(k + " ") or msg.endswith(" " + k) or f" {k} " in f" {msg} " for k in agreement_keywords) and bot_offered_photos_last_turn

    # Also check if bot_reply explicitly promises to send photos/samples below
    b_reply_low = (bot_reply or "").lower()
    is_bot_sending_photos = any(k in b_reply_low for k in [
        "ছবিগুলো নিচে পাঠানো হলো", "ছবিগুলো নিচে দেওয়া হলো", "ছবিগুলো নিচে দেয়া হলো",
        "স্যাম্পল ছবিগুলো নিচে", "প্যাকেজগুলো নিচে পাঠানো হলো", "প্যাকেজের ছবিগুলো নিচে",
        "স্যাম্পল নিচে পাঠানো হলো", "ছবি নিচে পাঠানো হলো", "ছবি দেওয়া হলো", "ছবি পাঠানো হলো",
        "স্যাম্পল দেওয়া হলো", "স্যাম্পল পাঠানো হলো", "স্যাম্পলগুলো নিচে পাঠানো হলো",
        "প্যাকেজগুলো পাঠানো হলো", "স্যাম্পল ছবিগুলো নিচে পাঠানো হলো", "ছবিগুলো নিচে পাঠানো হল",
        "স্যাম্পল পাঠানো হল", "স্যাম্পল ছবিগুলো নিচে পাঠানো হলো স্যার"
    ])

    if not (is_explicit_photo_req or is_agreeing_to_photo or is_bot_sending_photos):
        return []

    # Check if photos were already delivered recently in the thread
    if conversation_history and not is_bot_sending_photos:
        recent_bot_msgs = [
            m.get("content", "") for m in conversation_history[-4:]
            if str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower() in ("bot", "assistant")
        ]
        already_sent_recently = any(
            any(ext in bm for ext in [".jpg", ".png", ".jpeg", "/uploads/"]) or 
            any(kw in bm for kw in ["স্যাম্পল ছবি", "ছবি দেওয়া হলো", "ছবি পাঠানো হলো"])
            for bm in recent_bot_msgs
        )
        is_asking_more = any(k in msg for k in ["আরও", "আরো", "অন্য", "নতুন", "more", "other", "different", "আবার", "সব"])
        if already_sent_recently and not is_asking_more:
            return []

    req_count = parse_requested_image_count(msg)
    selected_images = []

    combined_context = f"{msg} {b_reply_low}"
    is_pkg = any(k in combined_context for k in ["প্যাকেজ", "কম্বো", "package", "combo", "পেকেজ", "সব প্যাকেজ"])
    is_fita = any(k in combined_context for k in ["ফিতা", "রিবন", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]) and not is_pkg
    is_cover = any(k in combined_context for k in ["কভার", "হোল্ডার", "holder", "cover"]) and not is_pkg
    is_id = any(k in combined_context for k in ["আইডি", "কার্ড", "id card", "card", "পিভিসি", "pvc"]) and not (is_pkg or is_fita or is_cover)

    if is_pkg or int(workspace_id or 1) == 1:
        selected_images = get_package_sample_images(workspace_id=workspace_id)
    elif is_fita:
        selected_images = get_category_batch_images("fita", workspace_id=workspace_id)
    elif is_cover:
        selected_images = get_category_batch_images("cover", workspace_id=workspace_id)
    elif is_id:
        selected_images = get_category_batch_images("idc", workspace_id=workspace_id)
    else:
        selected_images = get_package_sample_images(workspace_id=workspace_id)

    if req_count and req_count > 0:
        return selected_images[:req_count]
    if is_agreeing_to_photo and not is_explicit_photo_req:
        return selected_images[:3]
    return selected_images

def detect_saved_media_to_send(user_msg: str, bot_reply: str = "", workspace_id: int = 1) -> dict:
    """Detects if customer EXPLICITLY requested a specific demo video or pre-recorded voice note within user_msg."""
    msg = (user_msg or "").strip().lower()
    
    res = {"video_url": "", "voice_url": ""}
    
    # 1. Video matching - ONLY if user explicitly asked for video / submission guide
    is_asking_correction_video = any(k in msg for k in [
        "সংশোধন করার ভিডিও", "সংশোধনের ভিডিও", "ভুল হলে কিভাবে ঠিক করব ভিডিও", "এডিটের ভিডিও", "সংশোধন কিভাবে করব"
    ])
    is_asking_submission_video = any(k in msg for k in [
        "ফর্ম পূরণের ভিডিও", "ফর্মের ভিডিও", "আপলোডের ভিডিও", "ভিডিও দেখতে চাই", "ভিডিও পাঠান", "ভিডিও দেন", "তথ্য কিভাবে দিব", "ছবি আপলোড করব"
    ])

    if is_asking_correction_video:
        all_videos = get_saved_media("video", workspace_id=workspace_id)
        for v in all_videos:
            title_desc = (v.get("title", "") + " " + v.get("description", "") + " " + v.get("file_url", "")).lower()
            if "সংশোধন" in title_desc or "edit" in title_desc or "correction" in title_desc:
                res["video_url"] = v["file_url"]
                break
        if not res["video_url"] and all_videos:
            res["video_url"] = all_videos[0]["file_url"]
        if not res["video_url"]:
            res["video_url"] = "/static/uploads/media/google_form_edit_correction_guide.mp4"
    elif is_asking_submission_video:
        all_videos = get_saved_media("video", workspace_id=workspace_id)
        for v in all_videos:
            title_desc = (v.get("title", "") + " " + v.get("description", "") + " " + v.get("file_url", "")).lower()
            if ("আপলোড" in title_desc or "submission" in title_desc or "guide" in title_desc or "upload" in title_desc) and "সংশোধন" not in title_desc:
                res["video_url"] = v["file_url"]
                break
        if not res["video_url"] and all_videos:
            res["video_url"] = all_videos[0]["file_url"]
        if not res["video_url"]:
            res["video_url"] = "/static/uploads/media/google_form_submission_guide.mp4"
            
    # 2. Voice matching - ONLY if user explicitly asked about quality / features
    is_asking_quality_voice = any(k in msg for k in [
        "কোয়ালিটি কেমন হবে", "কোয়ালিটি কেমন হবে", "কোয়ালিটি কেমন", "কোয়ালিটি কেমন",
        "মান কেমন", "কোয়ালিটি জানতে চাই", "কোয়ালিটি জানতে চাই", "কোয়ালিটির ভয়েস", "বৈশিষ্ট্য",
        "কোয়ালিটি সম্পরকে", "কোয়ালিটি সম্পরকে", "কোয়ালিটি সম্পর্কে", "কোয়ালিটি সম্পর্কে",
        "কার্ড ও ফিতা এর কোয়ালিটি", "কার্ড ও ফিতা এর কোয়ালিটি"
    ])
    if is_asking_quality_voice:
        all_voices = get_saved_media("voice", workspace_id=workspace_id)
        for v in all_voices:
            title_desc = (v.get("title", "") + " " + v.get("description", "") + " " + v.get("file_url", "")).lower()
            if "কোয়ালিটি" in title_desc or "কোয়ালিটি" in title_desc or "বৈশিষ্ট্য" in title_desc or "quality" in title_desc or "feature" in title_desc:
                res["voice_url"] = v["file_url"]
                break
        if not res["voice_url"] and all_voices:
            res["voice_url"] = all_voices[0]["file_url"]
        if not res["voice_url"]:
            res["voice_url"] = "/static/uploads/media/id_card_and_fita_quality.aac"
            
    return res

def generate_smart_fallback_reply(user_msg: str, customer_name: str = "", workspace_id: int = 1, page_id: str = "") -> str:
    """Generates an intelligent context-aware reply strictly isolated to the workspace if Gemini API is unreachable."""
    msg = (user_msg or "").strip().lower()
    honorific = detect_customer_gender_title(customer_name)
    from app.database import get_page_ai_config
    config = get_page_ai_config(page_id=page_id, workspace_id=workspace_id)
    shop_name = config.get("shop_name") or "Our Shop"
    inside_fee = int(float(config.get("delivery_inside_dhaka", 80.0)))
    outside_fee = int(float(config.get("delivery_outside_dhaka", 130.0)))

    if any(k in msg for k in ["লাগবে না", "আর লাগবে না", "না", "stop", "no"]):
        return f"জি {honorific}, ঠিক আছে। আপনার আর কোনো তথ্য বা অর্ডার সংক্রান্ত সহযোগিতা প্রয়োজন হলে জানাবেন প্লিজ।"
    
    if any(k in msg for k in ["ডেলিভারি", "কুরিয়ার", "delivery"]):
        return f"জি {honorific}, ডেলিভারি চার্জ ঢাকার ভেতরে {inside_fee} টাকা এবং ঢাকার বাইরে {outside_fee} টাকা (প্রতি কেজিতে ২০ টাকা এবং প্রতি হাজারে ১০ টাকা COD চার্জ প্রযোজ্য)।"

    if any(k in msg for k in ["সময়", "কতদিন", "কয়দিন", "time", "duration"]):
        return f"জি {honorific}, তথ্য দেওয়ার পর কাজ ও ডিজাইন করতে ৫-৬ দিন সময় লাগবে। প্রুফ অনুমোদনের পর প্রিন্ট করে ২৪-৪৮ ঘণ্টার মধ্যে কুরিয়ারে ডেলিভারি পেয়ে যাবেন।"

    if any(k in msg for k in ["কোয়ালিটি", "কোয়ালিটি", "মান কেমন", "কোয়ালিটি কেমন", "কোয়ালিটি কেমন হবে", "কোয়ালিটি কেমন হবে", "বৈশিষ্ট্য", "quality"]):
        return f"জি {honorific}, আমাদের কার্ড ও ফিতার কোয়ালিটি ও বৈশিষ্ট্য কেমন হবে সে সম্পর্কে বিস্তারিত জানতে নিচের ভয়েস বার্তাটি শুনুন:"

    # Workspace 1 (RS Graphics) specific fallbacks
    if int(workspace_id or 1) == 1:
        # Specific item price queries in fallback
        if "t-014" in msg or "t014" in msg:
            return f"জি {honorific}, এটি আমাদের T-014V সফট কভার। এর রেগুলার মূল্য প্রতি পিস ১০ টাকা।"
        elif "dx" in msg:
            return f"জি {honorific}, এটি আমাদের DX কভার। এর রেগুলার মূল্য প্রতি পিস ১২ টাকা।"
        elif "t-065" in msg or "t065" in msg:
            return f"জি {honorific}, এটি আমাদের T-065V সফট কভার। এর রেগুলার মূল্য প্রতি পিস ১৪ টাকা।"
        elif "993" in msg or "xinding" in msg:
            return f"জি {honorific}, এটি আমাদের Xinding Q-993 কভার। এর রেগুলার মূল্য প্রতি পিস ১৬ টাকা।"
        elif "738" in msg or "t-738" in msg:
            return f"জি {honorific}, এটি আমাদের T-738V হার্ড কভার। এর রেগুলার মূল্য প্রতি পিস ২০ টাকা।"
        elif "994" in msg or "t-994" in msg:
            return f"জি {honorific}, এটি আমাদের T-994V হার্ড কভার। এর রেগুলার মূল্য প্রতি পিস ২০ টাকা।"
        elif "reap" in msg:
            return f"জি {honorific}, এটি আমাদের REAP হার্ড কভার। এর রেগুলার মূল্য প্রতি পিস ২০ টাকা।"
        elif "মেটাল" in msg or "metal" in msg:
            return f"জি {honorific}, এটি আমাদের মেটাল ফ্রেম কভার। এর রেগুলার মূল্য প্রতি পিস ৩০ টাকা।"
        elif any(k in msg for k in ["এই কভার", "কভার টা কত", "কভারের দাম"]):
            return f"জি {honorific}, আমাদের বিভিন্ন মডেলের কভারের রেট ১০ টাকা থেকে শুরু করে ৩০ টাকা পর্যন্ত (যেমন T-014V ১০৳, DX ১২৳, T-065V ১৪৳, Q-993 ১৬৳, T-738V/Reap ২০৳, মেটাল ৩০৳)। আপনার কোন কভারটি পছন্দ জানাবেন প্লিজ।"
        elif any(k in msg for k in ["এই ফিতা", "ফিতার দাম", "ফিতা কত"]):
            return f"জি {honorific}, আমাদের ২ সেন্টিমিটার প্রিমিয়াম ডিজিটাল সাবলিমেশন ফিতার মূল্য প্রতি পিস ২৮ টাকা এবং ১.৫ সেন্টিমিটার ফিতার মূল্য ২৫ টাকা।"
        elif any(k in msg for k in ["এই কার্ড", "কার্ডের দাম", "শুধু কার্ড"]):
            return f"জি {honorific}, আমাদের জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট প্রিমিয়াম PVC আইডি কার্ডের রেগুলার মূল্য প্রতি পিস ৩৫ টাকা (১০০+ পিস অর্ডারের ক্ষেত্রে)।"

        qty = extract_order_quantity_number(msg)
        if any(k in msg for k in ["আইডি কার্ড", "আইডি কাড", "id card", "আইডিকার্ড", "কার্ড বানাতে", "কার্ড করতে", "কার্ড বানাবো"]):
            if qty is None:
                return f"জি {honorific}, আপনি আইডি কার্ড কত পিস বানাবেন?"
            elif qty < 30:
                return f"দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।"
            else:
                return f"জি {honorific}, অবশ্যই দিচ্ছি। নিচে আমাদের স্যাম্পলগুলো পাঠানো হলো:"

        if qty is not None and any(k in msg for k in ["পিস", "টা", "টি", "বানাবো", "pcs"]):
            if qty < 30:
                return f"দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।"
            else:
                return f"জি {honorific}, অবশ্যই দিচ্ছি। নিচে আমাদের স্যাম্পলগুলো পাঠানো হলো:"

        if any(k in msg for k in ["প্যাকেজ", "কম্বো", "package", "combo"]):
            return f"জি {honorific}, আপনি কত পিস আইডি কার্ড বানাবেন জানাবেন প্লিজ?"

        if any(k in msg for k in ["ফিতা", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
            return f"জি {honorific}, নিচে আমাদের ডিজিটাল সাবলিমেশন ফিতার কিছু স্যাম্পল ছবি দেওয়া হলো। আপনার কত পিস ফিতা প্রয়োজন জানাবেন প্লিজ?"

        if any(k in msg for k in ["আইডি", "কার্ড", "id card"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
            return f"জি {honorific}, নিচে আমাদের জাপানি UV প্রিন্ট আইডি কার্ডের স্যাম্পল ছবিগুলো দেওয়া হলো। আপনার কত পিস আইডি কার্ড প্রয়োজন জানাবেন প্লিজ?"

        if any(k in msg for k in ["দাম", "রেট", "মূল্য", "price", "cost"]):
            return f"জি {honorific}, আপনি আইডি কার্ড কত পিস বানাবেন জানাবেন প্লিজ? আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস।"

        return f"জি {honorific}, আসসালামু আলাইকুম! আপনি আইডি কার্ড কত পিস বানাবেন জানাবেন প্লিজ?"

    # Workspace 2+ Clean Generic Fallbacks (Never mentioning RS Graphics or ID cards)
    if any(k in msg for k in ["দাম", "রেট", "মূল্য", "price", "cost"]):
        return f"জি {honorific}, আমাদের শপের পণ্যের বিস্তারিত ও মূল্য তালিকা জানাতে পেরে আনন্দিত। আপনার কাঙ্ক্ষিত পণ্যটির নাম বা কোড জানাবেন প্লিজ?"

    return f"জি {honorific}, আসসালামু আলাইকুম! '{shop_name}'-এ আপনাকে স্বাগতম। আপনি কোন পণ্যটি সম্পর্কে জানতে বা অর্ডার করতে চান জানাবেন প্লিজ?"

async def process_customer_message(
    message_text: str = "",
    image_bytes: bytes = None,
    image_mime: str = "image/jpeg",
    image_list: list = None,
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
    Handles text, single/multiple images, voice notes, gender recognition, and batch sample delivery.
    """
    api_key = get_setting("gemini_api_key", settings.GEMINI_API_KEY)
    ws_id = int(workspace_id or 1)

    # 0. ZERO-REPLY SAFETY GUARD: If Admin Takeover is active, AI MUST BE 100% SILENT
    from app.database import is_conversation_ai_active
    if not is_conversation_ai_active(sender_id=sender_id, workspace_id=ws_id):
        print(f"[AI_BLOCKED] reason=admin_takeover workspace_id={ws_id} sender_id={sender_id}")
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

    # 2. Priority ID Card Inquiry, MOQ Check, and Phased Sample Delivery Workflow
    try:
        id_flow_res = evaluate_id_card_workflow(
            message_text=message_text,
            conversation_history=conversation_history,
            customer_name=customer_name,
            workspace_id=ws_id
        )
        if id_flow_res:
            return id_flow_res
    except Exception as e:
        print(f"[ID Card Workflow Early Resolution Warning]: {e}")

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
                s_val = str(msg.get("sender_role") or msg.get("sender") or msg.get("sender_type") or msg.get("role") or "").lower()
                if s_val in ("admin", "owner", "main_admin", "seller"):
                    role_tag = "মূল অ্যাডমিন / শপ ওনার (ADMIN)"
                elif s_val in ("bot", "assistant", "ai"):
                    role_tag = "এআই সেলস সহকারী (AI)"
                elif s_val in ("system",):
                    role_tag = "সিস্টেম ইভেন্ট (SYSTEM)"
                else:
                    role_tag = "কাস্টমার (CUSTOMER)"
                c_text = msg.get('content') or msg.get('text') or ''
                m_url = msg.get('media_url') or ''
                if m_url:
                    m_fname = os.path.basename(m_url)
                    if c_text:
                        c_text = f"[প্রোডাক্ট ছবি: {m_fname}] {c_text}"
                    else:
                        c_text = f"[প্রোডাক্ট ছবি পাঠানো হয়েছে: {m_fname}]"
                history_text += f"{role_tag}: {c_text}\n"
            contents.append(history_text)

        # Add image attachments (supports single image or multiple batch package images)
        if image_list and len(image_list) > 0:
            for img_item in image_list:
                i_bytes = img_item.get("bytes") or img_item.get("image_bytes")
                i_mime = img_item.get("mime") or img_item.get("image_mime") or "image/jpeg"
                if i_bytes:
                    contents.append(types.Part.from_bytes(data=i_bytes, mime_type=i_mime))
            if not message_text:
                message_text = f"কাস্টমার একসাথে {len(image_list)}টি ছবি পাঠিয়েছেন। ছবিগুলোর প্রতিটি মনোযোগ দিয়ে দেখে প্রতিটি আলাদা প্যাকেজ/প্রডাক্ট শনাক্ত করে বিস্তারিত জানান।"
        elif image_bytes:
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
