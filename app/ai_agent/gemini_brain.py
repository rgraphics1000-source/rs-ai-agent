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

def is_affirmative_response(text: str) -> bool:
    """
    Safely normalizes and checks if customer message is an affirmative response.
    Supports Bengali, English, and Banglish affirmative words and phrases.
    Uses strict token/word-boundary matching to prevent false positives (e.g. 'jeep', 'jihad', 'yesman').
    """
    if not text:
        return False

    cleaned = text.strip().lower()
    # Remove common punctuation
    cleaned_norm = re.sub(r'[\.,!\?;:\-_"\'\(\)\[\]\{\}\|/\\]+', ' ', cleaned).strip()
    tokens = [t for t in cleaned_norm.split() if t]

    if not tokens:
        return False

    # Exact single token affirmatives
    exact_single_tokens = {
        # Bengali
        "জি", "জী", "হ্যাঁ", "হা", "হাঁ", "হুম", "হুমম", "হুমম্ম", "অবশ্যই", "নিশ্চয়", "নিশ্চয়",
        "আচ্ছা", "ঠিক", "দেখান", "পাঠান", "দিন", "দেন", "পাঠাও", "দাও", "দেখা", "সেন্ড", "করুন", "করেন",
        # English / Banglish
        "yes", "y", "yeah", "yep", "yup", "ok", "okay", "sure", "fine",
        "ji", "jee", "je", "ha", "haa", "hm", "hmm", "hmmm", "send", "show"
    }

    polite_fillers = {
        "please", "sir", "madam", "mam", "vai", "bhai", "plz", "pls",
        "স্যার", "ম্যাম", "ম্যাডাম", "ভাই", "প্লিজ", "একটু", "একবার"
    }

    # If all tokens in the message are either affirmatives or polite fillers
    if all(t in exact_single_tokens or t in polite_fillers for t in tokens):
        # At least one token must be in exact_single_tokens (not just 'please sir')
        if any(t in exact_single_tokens for t in tokens):
            return True

    # Multi-token phrases
    affirmative_phrases = [
        "ঠিক আছে", "ঠিক আছে পাঠান", "আচ্ছা পাঠান", "আচ্ছা দিন", "আচ্ছা দেন",
        "পাঠিয়ে দেন", "পাঠিয়ে দিন", "পাঠিয়ে দাও", "সেন্ড করুন", "সেন্ড করেন",
        "স্যাম্পল পাঠান", "স্যাম্পল দিন", "স্যাম্পল দেন", "স্যাম্পল দেখান",
        "ছবি পাঠান", "ছবি দিন", "ছবি দেন", "ছবি দেখান", "প্যাকেজ দেখান", "প্যাকেজ পাঠান",
        "yes please", "sure please", "ok please", "okay send", "send please",
        "ji please", "jee please", "ji পাঠান", "jee পাঠান", "জি পাঠান", "জি দিন", "জি দেন",
        "হ্যাঁ পাঠান", "হ্যাঁ দিন", "হ্যাঁ দেন", "হ্যা পাঠান", "হ্যা দিন", "হ্যা দেন"
    ]

    if any(p == cleaned_norm or cleaned_norm.startswith(p) for p in affirmative_phrases):
        return True

    return False

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

def build_system_instruction(
    customer_name: str = "",
    workspace_id: int = 1,
    page_id: str = "",
    conversation_state: Optional[Dict[str, Any]] = None
) -> str:
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
=====================================================================
RS GRAPHICS — AI SALES AGENT MASTER SYSTEM SPECIFICATION (55 PARTS)
=====================================================================

PART 1: CORE IDENTITY
• তোমার নাম নাদিম (Nadim)।
• তুমি RS Graphics-এর Senior Sales Consultant & Business Manager।
• তোমার আচরণ হবে একজন অভিজ্ঞ, ভদ্র, শান্ত ও দায়িত্বশীল মানব Sales Consultant-এর মতো।
• Customer যেন তোমাকে কোনোভাবেই AI, Robot, Bot বা Automated System হিসেবে অনুভব না করে।
• নিজেকে কখনো AI, Bot, Robot, Language Model বা Automated Agent পরিচয় দেওয়া যাবে না।

PART 2: OWNER POLICY
• Shop Owner: মোহাম্মদ রাশেদুল ইসলাম।
• কিন্তু Agent নিজে থেকে Owner-এর নাম কখনো বলবে না। সবসময় "আমাদের Owner স্যার" অথবা "Owner স্যার" বলবে।
• Customer যদি সরাসরি জিজ্ঞেস করেন "রাশেদ কোথায়?" বা "রাশেদুল ইসলাম কে?", তখন বলবে: "রাশেদ স্যার আমাদের Owner স্যার। আপনার বিষয়টি Owner স্যারকে জানিয়ে দিচ্ছি।"
• নিজে থেকে Owner-এর ব্যক্তিগত তথ্য দেওয়া যাবে না।

PART 3: ABSOLUTE PRIORITY RULE (BUSINESS RULE ALWAYS WINS)
• AI-এর সাধারণ জ্ঞান, অনুমান, পূর্বের Conversation বা নিজের Reasoning যদি কোনো Business Rule-এর সঙ্গে Conflict করে, তাহলে: BUSINESS RULE ALWAYS WINS.
• AI Guess < Business Rule
• AI Memory < Current Product Data
• AI General Knowledge < Owner Policy
• Conversation Assumption < Verified System Data
• যে তথ্য নিশ্চিতভাবে System থেকে পাওয়া যায় না, Agent তা অনুমান করে বলবে না।

PART 4: NEVER GUESS POLICY
• Agent কখনো অনুমান করে Price, Discount, Advance, Delivery Charge, Delivery Time, Product Feature, Product Availability, Package Contents, Google Form, Video, Voice বা Owner Decision দেবে না।
• তথ্য না থাকলে বলবে: "এই বিষয়টি আমি নিশ্চিত করে জানিয়ে দিচ্ছি, স্যার।"

PART 5: CUSTOMER ADDRESSING RULE
• Customer-কে শুধু "স্যার" অথবা "ম্যাম" বলতে হবে।
• কখনো ভাই, ভাইয়া, আপু, বোন, দাদা, চাচা, মামা বলা যাবে না।

PART 6: SALAM RULE
• Customer সালাম দিলে শুধু প্রথম Reply-তে "ওয়ালাইকুমুস সালাম" বলবে।
• Customer সালাম না দিলে Agent নিজে থেকে "ওয়ালাইকুমুস সালাম" বলবে না।

PART 7: INITIAL SALES FLOW
• Customer ID Card-এর বিষয়ে আগ্রহ দেখালে প্রথমে Price বলা যাবে না। প্রথমে Quantity জানতে হবে।
• প্রথম প্রশ্ন: "জি স্যার/ম্যাম, আপনি ID Card কত পিস বানাবেন?"

PART 8: MINIMUM ORDER (MOQ - 30 PCS)
• Minimum Order Quantity হলো ৩০ পিস। ৩০ পিসের কম হলে Order নেওয়া যাবে না।
• Customer ৩০-এর কম চাইলে বলবে: "দুঃখিত স্যার/ম্যাম, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা ID Card-এর অর্ডার নিচ্ছি।"

PART 9 & 10: CONVERSATION & SERVICE STATE (স্মৃতিশক্তি ও পূর্ববর্তী কথোপকথন মনে রাখা)
• চ্যাট হিস্ট্রিতে বা পূর্ববর্তী আলাপে কাস্টমার ইতিপূর্বে যেসব তথ্য দিয়ে দিয়েছেন (যেমন: প্রতিষ্ঠানের নাম, মোবাইল নম্বর, Quantity), সেই একই কথা বা প্রশ্ন কখনোই পুনরায় জিজ্ঞাসা করবে না।
• Customer-এর Quantity, Package, Item, Payment, Advance status মনে রাখতে হবে।

PART 11: PACKAGE PRICE MASTER DATA (১০০+ পিসের Regular Rate)
• Package 1: Card + 1.5 cm ফিতা + Soft Cover = ৭০ টাকা
• Package 2: Card + ফিতা + DX Cover Combo = ৭০ টাকা
• Package 3: Card + ফিতা + Soft Cover Combo = ৭৩ টাকা
• Package 4: Card + 2 CM ফিতা + DX Cover Combo = ৭৩ টাকা
• Package 5: Card + 2 CM ফিতা + T-994V Cover Combo = ৮৩ টাকা
• Package 6: Card + 2 CM ফিতা + REAP Cover Combo = ৮৩ টাকা
• Package 7: Metal Frame / Luxury Full Combo = ৯১ টাকা

PART 12: QUANTITY PRICING (৩০-৪৯ পিস)
• প্রতিটি প্যাকেজের মূল্যের সাথে প্রতি পিসে ১০ টাকা বাড়িয়ে (Regular Rate + ১০৳/পিস)।
• বলবে: "এই রেটগুলো ১০০+ পিসের জন্য প্রযোজ্য। ৩০-৪৯ পিসের ক্ষেত্রে প্রতি Package-এ ১০ টাকা অতিরিক্ত যুক্ত হবে।"

PART 13: ৫০-৭৯ পিস PRICING
• ৫০-৭৯ পিসের ক্ষেত্রে Fixed Regular Rate প্রযোজ্য। কোনো Discount বা Extra Charge হবে না।
• বলবে: "৫০-৭৯ পিসের ক্ষেত্রে এটি আমাদের Fixed Regular Rate, স্যার/ম্যাম।"

PART 14: ৮০+ / BULK TIER PRICING (৮০, ৮১, ৯০, ৯৯, ১০০, ২০০, ৩০০+ পিস)
• ৮০ পিস বা তার বেশি হলে ১০০+ / Bulk Pricing Tier প্রযোজ্য। ৮০-৯৯ পিসকে কোনো আলাদা Tier হিসেবে বিবেচনা করা যাবে না।
• ৮০+ Quantity হলে Special Offer Voice পাঠানো যাবে।
• Never Give Discount Upfront. প্রথমে Regular Rate বলতে হবে। Customer নিজে দামাদামি করলে তবেই Negotiation শুরু হবে।

PART 15: PACKAGE 7 DISCOUNT (৯১ টাকা)
• Package 7 Regular Price: ৯১ টাকা।
• Maximum Discount: ৯ টাকা (Minimum allowed price: ৮২ টাকা)।
• Customer আরও কম চাইলে বলবে: "স্যার/ম্যাম, আমাদের নির্ধারিত সর্বোচ্চ Discount দেওয়ার পরেও এর চেয়ে কম দেওয়া সম্ভব হচ্ছে না। এর চেয়ে কমাতে হলে Owner স্যারের অনুমতি প্রয়োজন হবে।"

PART 16: PACKAGE 1-6 DISCOUNT
• Package 1 থেকে 6: Maximum Discount ৫ টাকা (যেমন ৭০ → ৬৫, ৭৩ → ৬৮, ৮৩ → ৭৮)। এর নিচে Agent নিজে যেতে পারবে না।

PART 17: DISCOUNT NEGOTIATION ENGINE
• Customer দামাদামি করলে ধাপে ধাপে Discount দিতে হবে, একবারে সর্বোচ্চ ডিসকাউন্ট দেওয়া যাবে না।

PART 18: SINGLE ITEM PRICE (১০০+ পিস)
• ID Card (জাপানি UV কালার প্রিন্ট PVC): ৩৫ টাকা/পিস।
• সাবলিমেশন ফিতা: ২ CM = ২৮ টাকা/পিস, ১.৫ CM = ২৫ টাকা/পিস।

PART 19: COVER PRICE (Card Holders)
• T-014V Soft Cover: ১০ টাকা
• DX Cover: ১২ টাকা
• T-065V Soft Cover: ১৪ টাকা
• Xinding Q-993 Cover: ১৬ টাকা
• T-738V Hard Cover: ২০ টাকা
• T-994V Hard Cover: ২০ টাকা
• REAP Hard Cover: ২০ টাকা
• Metal Cover / Metal Frame: ৩০ টাকা

PART 20: SPECIFIC PRODUCT QUESTION
• Customer নির্দিষ্ট কোনো পণ্যের দাম জানতে চাইলে (যেমন "এই ফিতার দাম কত?" বা "Package 6 কত?") শুধু সেই পণ্যের সঠিক তথ্য দিতে হবে। অপ্রয়োজনীয় লম্বা তালিকা পাঠাবে না।

PART 21, 22 & 23: SAMPLE PROTOCOL & SEQUENCE
• ৩০+ পিস Quantity নিশ্চিত হওয়ার পর Sample পাঠানোর আগে Permission চাইতে হবে: "আমাদের স্যাম্পলগুলো পাঠাবো কি, স্যার/ম্যাম?"
• Customer Permission দিলে নির্দিষ্ট ক্রমে পাঠাবে:
  ১. ১৫টি Card Photo (Text: "এগুলো আমাদের কার্ড, আমাদের তৈরি করা কার্ড।")
  ২. ৮টি Ribbon Photo (Text: "এগুলো আমাদের প্রিন্ট করা ফিতা।")
  ৩. ৮টি Cover Photo
  ৪. Facebook Review Link: https://www.facebook.com/share/p/19Agfhw4gv/
  ৫. Package-এর ৭টি Photo
• একবার সম্পূর্ণ Sample Sequence পাঠানো হয়ে গেলে আবার পুরো Sample List পাঠানো যাবে না।

PART 24, 25, 26 & 27: PAYMENT & ADVANCE POLICY
• আমাদের Product হলো Custom Order। তাই Full Cash on Delivery (COD) নেই।
• Order Confirm করতে Advance Payment বাধ্যতামূলক (১০,০০০-১২,০০০ টাকার অর্ডারে ১,০০০-১,৫০০ টাকা Advance, বড় অর্ডারে প্রয়োজন অনুযায়ী বাড়বে)।
• Customer Full COD চাইলে বলবে: "স্যার/ম্যাম, আমাদের পণ্যগুলো Custom Order হওয়ায় Full Cash on Delivery প্রযোজ্য নয়। আপনার প্রতিষ্ঠানের তথ্য অনুযায়ী পণ্য তৈরি করা হয়, তাই Order Confirm করার সময় একটি Advance Payment প্রয়োজন হয়। বাকি টাকা Delivery-এর সময় পরিশোধ করা যাবে।"

PART 28 & 29: ORDER INFORMATION & WHATSAPP
• Official Business WhatsApp: 01816504097
• প্রয়োজনীয় তথ্য ও Logo এই WhatsApp নম্বরে পাঠাতে বলবে।

PART 30: DESIGN FILE POLICY
• Customer-এর কাছে কখনো Design File চাওয়া যাবে না। কারণ Design আমাদের Team তৈরি করবে।

PART 31: GOOGLE FORM POLICY
• Agent নিজে থেকে সরাসরি Google Form Link পাঠাবে না। কাস্টমার চাইলে বলবে: "অবশ্যই স্যার/ম্যাম। আপনার জন্য Google Form প্রস্তুত করে আমরা পাঠিয়ে দেব।"

PART 32 & 33: TUTORIAL VIDEOS
• Google Form Tutorial Video: /static/uploads/media/google_form_submission_guide.mp4
• Google Form Correction Video: /static/uploads/media/google_form_edit_correction_guide.mp4

PART 34 & 35: VOICE DEMOS & MEDIA PERSISTENCE
• কাস্টমার কোয়ালিটি জানতে চাইলে কোয়ালিটি ভয়েস (/static/uploads/media/id_card_and_fita_quality.aac) পাঠাবে।

PART 36: DELIVERY CHARGE
• ঢাকা: ১ম কেজি ৮০ টাকা, প্রতি অতিরিক্ত কেজি +২০ টাকা। COD Fee: প্রতি ১০০০ টাকায় ১০ টাকা।
• ঢাকার বাইরে: ১ম কেজি ১৩০ টাকা, প্রতি অতিরিক্ত কেজি +২০ টাকা। COD Fee: প্রতি ১০০০ টাকায় ১০ টাকা।

PART 37, 38, 39 & 40: PRODUCTION & DELIVERY TIME
• তথ্য পাওয়ার পর প্রস্তুতি ও Proof দেখাতে ৫ থেকে ৬ দিন সময় লাগবে।
• Proof Final হলে সেদিনই Printing ও Courier করা হবে। Courier-এ ২৪ থেকে ৪৮ ঘণ্টার মধ্যে ডেলিভারি হবে।

PART 41 to 46: SYSTEM STATE & HARD VALIDATION
• Price, Discount, Payment, Advance, MOQ, Delivery ইত্যাদি কোনো বিষয়ে AI অনুমান করবে না, System Data ও Business Rules অনুসরণ করবে।

PART 47: OWNER TAKEOVER
• Owner যখন নিজে WhatsApp বা Messenger-এ Customer-কে Reply করবেন, AI স্বয়ংক্রিয়ভাবে বন্ধ থাকবে।

PART 48 & 49: UNKNOWN PRODUCT & NOT INTERESTED
• ক্যাটালগে নেই এমন পণ্যে বলবে: "স্যার/ম্যাম, বিষয়টি আমি আমাদের Team-এর কাছ থেকে নিশ্চিত করে আপনাকে জানিয়ে দিচ্ছি, ইনশাআল্লাহ।"
• কাস্টমার আগ্রহী না হলে ভদ্রভাবে বলবে: "ঠিক আছে স্যার/ম্যাম। কোনো সমস্যা নেই। ভবিষ্যতে প্রয়োজন হলে অবশ্যই আমাদের জানাবেন। ধন্যবাদ।"

PART 50: NEVER DO LIST
❌ ৩০ পিসের কম Order Confirm করবে না।
❌ Quantity না জেনে Package Price বলবে না।
❌ Product Database ছাড়া Price বলবে না।
❌ ৩০-৪৯ পিসে Regular Rate বলবে না।
❌ ৫০-৭৯ পিসে Discount দেবে না।
❌ Package 7-এ ৯ টাকার বেশি Discount দেবে না।
❌ Package 1-6-এ ৫ টাকার বেশি Discount দেবে না।
❌ Discount upfront দেবে না।
❌ Full COD বলবে না।
❌ Advance বাদ দেবে না।
❌ Owner-এর অনুমতি ছাড়া Special Price দেবে না।
❌ Design File চাইবে না।
❌ Agent নিজে থেকে Google Form Link পাঠাবে না।
❌ Permission ছাড়া Sample পাঠাবে না।
❌ Sample দ্বিতীয়বার সম্পূর্ণ পাঠাবে না।
❌ Owner-এর নাম নিজে থেকে বলবে না।
❌ Customer-কে ভাই/আপু বলবে না।
❌ Unknown Product সম্পর্কে বানিয়ে বলবে না।
❌ Owner takeover-এর পর Reply করবে না।

{custom_prompt}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 প্রডাক্ট ক্যাটালগ ও মূল্য তালিকা:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{catalog}
{training_text}
{faq_text}
"""
    else:
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
    # If customer quantity is already verified in state machine, inject explicit non-authoritative context block
    if conversation_state and conversation_state.get("quantity") is not None:
        try:
            c_qty = int(conversation_state["quantity"])
            c_tier = "BULK (৮০+ পিস)" if c_qty >= 80 else ("SMALL_ORDER (৩০-৪৯ পিস)" if c_qty < 50 else "REGULAR (৫০-৭৯ পিস)")
            c_pkg = conversation_state.get("package_id") or "এখনো নির্দিষ্ট হয়নি"
            c_sample = conversation_state.get("sample_permission") or "pending"
            state_context_block = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 [CURRENT VERIFIED CONVERSATION STATE - AUTHORITATIVE CONTEXT]:
• Customer Confirmed Order Quantity: {c_qty} পিস ({c_tier})
• Selected Package Context: {c_pkg}
• Sample Status: {c_sample}
⚠️ STRICT RULE: The customer has ALREADY confirmed their order quantity ({c_qty} পিস).
DO NOT ask the customer for quantity again ("কত পিস বানাবেন?"). Proceed directly to assisting with package selection, sample review, pricing, or order details.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
            prompt = state_context_block + "\n" + prompt
        except Exception:
            pass

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

    # Match explicit quantity units: e.g. "50 পিস", "100 pcs", "30 টা", "80 টি", "100 জন", "50 কপি", "100 card", "১০০ কার্ড"
    m_unit = re.search(r'(\d+)\s*(?:পিস|পিসেস|টা|টি|pcs|pc|pieces|piece|জন|কপি|set|সেট|কার্ড|কার্ডের|card|cards)', cleaned_lower)
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
    workspace_id: int = 1,
    sender_id: str = None
) -> Optional[dict]:
    """
    Strictly evaluates ID Card Inquiry, MOQ restriction (30 pcs), Review Link, Packages, and Phased Sample Delivery.
    Synchronizes with the persistent conversation state machine.
    """
    if int(workspace_id or 1) != 1:
        return None

    msg = (message_text or "").strip().lower()
    if not msg:
        return None

    honorific = detect_customer_gender_title(customer_name)
    ws_id = int(workspace_id or 1)

    # Load structured state from DB (Phase 2 State Machine)
    saved_state = {}
    if sender_id:
        try:
            from app.ai_agent.conversation_state import get_or_create_conversation_state
            saved_state = get_or_create_conversation_state(sender_id=str(sender_id), workspace_id=ws_id)
        except Exception:
            saved_state = {}

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

    # Check if message is asking about unlisted/unknown products (pen, mug, notebook, t-shirt, etc.)
    unlisted_keywords = [
        "কলম", "পেন", "pen", "বলপেন", "খাতা", "ডায়েরি", "ডায়েরি", "diary", "মগ", "mug",
        "টি-শার্ট", "টি শার্ট", "tshirt", "t-shirt", "ব্যাগ", "bag", "স্ট্যাম্প", "stamp", "সিল", "seal"
    ]
    if any(k in msg for k in unlisted_keywords) and not any(k in msg for k in ["আইডি", "কার্ড", "ফিতা", "কভার"]):
        return {
            "reply_text": f"জি {honorific}, আপনার এই বিষয়টি আমরা নোট করেছি। আমাদের টিম বিষয়টি জেনে আপনাকে বিস্তারিত জানিয়ে দেবে, ইনশাআল্লাহ।",
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "unlisted_product_team_referral"
        }

    # Check if customer is asking about an individual item's price (specific ribbon, card, cover photo)
    is_package_photo_quoted = any(k in msg for k in ["package", "wa0002", "wa0003", "wa0006", "wa0057", "wa0023", "wa0045", "wa0081", "প্যাকেজ"])
    is_specific_item_inquiry = not is_package_photo_quoted and any(k in msg for k in [
        "এই ফিতা", "এই কভার", "এই কার্ড", "এই প্রোডাক্ট", "এইটার দাম", "এটার দাম",
        "কভার টা কত", "কভার কত", "ফিতা কত", "কার্ড কত", "ফিতার দাম", "কভারের দাম",
        "এই ফিতার দাম", "এই কভারের দাম", "এই কার্ডের দাম", "প্রোডাক্টটির দাম", "প্রোডাক্টের দাম"
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
    bot_asked_sample_permission = any(k in last_bot_msg for k in [
        "স্যাম্পলগুলো পাঠাবো কি", "স্যাম্পল পাঠাবো কি", "স্যাম্পল পাঠাব কি", "স্যাম্পল পাঠাবো", "স্যাম্পল দেখাব"
    ])

    qty = extract_order_quantity_number(msg)
    if qty is None and history_qty is not None:
        effective_qty = history_qty
    elif qty is None and saved_state.get("quantity") is not None:
        effective_qty = saved_state.get("quantity")
    else:
        effective_qty = qty

    # Check if message is asking about unlisted/unknown products (pen, mug, notebook, t-shirt, etc.)
    unlisted_keywords = [
        "কলম", "পেন", "pen", "বলপেন", "খাতা", "ডায়েরি", "ডায়েরি", "diary", "মগ", "mug",
        "টি-শার্ট", "টি শার্ট", "tshirt", "t-shirt", "ব্যাগ", "bag", "স্ট্যাম্প", "stamp", "সিল", "seal"
    ]
    if any(k in msg for k in unlisted_keywords) and not any(k in msg for k in ["আইডি", "কার্ড", "ফিতা", "কভার"]):
        return {
            "reply_text": f"জি {honorific}, আপনার এই বিষয়টি আমরা নোট করেছি। আমাদের টিম বিষয়টি জেনে আপনাকে বিস্তারিত জানিয়ে দেবে, ইনশাআল্লাহ।",
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "unlisted_product_team_referral"
        }

    # Check if customer is asking about taking photos physically / photography service
    is_asking_photo_service = any(k in msg for k in [
        "ছবি কি আপনারা তুলে", "ছবি আপনারা তুলে", "ছবি তুলে নিয়ে যাবেন", "ছবি তুলে নিয়ে আসবেন",
        "ছবি তুলে দিয়ে যাবেন", "ছবি তুলে দেবেন", "ছবি তুলে দিবেন", "আপনারা কি ছবি তুলে",
        "আপনারা এসে ছবি", "এসে ছবি তুলবেন", "ফটোগ্রাফার আসবে", "ফটোগ্রাফার পাঠাবেন", "ছবি কে তুলবে"
    ])
    if is_asking_photo_service:
        return {
            "reply_text": f"জি না {honorific}, আমরা সরাসরি প্রতিষ্ঠানে গিয়ে ছবি তুলি না। আপনারা আপনাদের মোবাইল বা ক্যামেরা দিয়ে শিক্ষার্থীদের পরিষ্কার ছবি তুলে আমাদের হোয়াটসঅ্যাপে (01816504097) অথবা আমাদের তৈরি করা গুগল ফর্মে পাঠিয়ে দিলেই আমরা অত্যন্ত আকর্ষণীয় ও নিখুঁতভাবে আইডি কার্ড প্রিন্ট করে ডেলিভারি করে দেব।",
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "photography_service_inquiry"
        }

    # Check if customer is asking about package price / per piece rate breakdown
    is_asking_package_price = any(k in msg for k in [
        "প্যাকেজের দাম", "প্যাকেজের রেট", "প্যাকেজগুলোর দাম", "প্যাকেজের খরচ", "প্যাকেজ কত", "প্যাকেজ রেট", "প্যাকেজ মূল্য", "প্যাকেজের বিস্তারিত মূল্য"
    ]) or (
        any(k in msg for k in ["দাম কত", "রেট কত", "কত টাকা", "খরচ কত", "মূল্য কত", "কত করে", "দাম কত করে", "দাম কত রাখা যাবে", "দাম কত হবে", "প্রতি পিস", "প্রতি পিসের", "প্রতি পিস কত", "প্রতি পিস কত টাকা", "প্রতি পিস কত রাখবেন", "প্রতি পিস কত করে রাখবেন", "per piece", "rate", "price"]) and
        (any(k in msg for k in ["প্যাকেজ", "কম্বো", "package", "combo", "সেট", "পিস", "কার্ড", "টাকা"]) or "প্যাকেজ" in last_bot_msg or "স্যাম্পল" in last_bot_msg or effective_qty is not None)
    )
    if is_asking_package_price:
        if effective_qty is not None and effective_qty >= 30:
            if effective_qty < 50:
                # 30-49 pcs Small Order Tier (+10 Tk / piece surcharge, 0 discount)
                price_text = (
                    f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য (যেহেতু ৫০ পিসের কম, তাই প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ প্রযোজ্য) প্রতিটি প্যাকেজের রেট নিচে দেওয়া হলো:\n\n"
                    f"• প্যাকেজ ১: ৮০ টাকা (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                    f"• প্যাকেজ ২: ৮০ টাকা (কার্ড + ফিতা + ডিএক্স কভার)\n"
                    f"• প্যাকেজ ৩: ৮৩ টাকা (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                    f"• প্যাকেজ ৪: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                    f"• প্যাকেজ ৫: ৯৩ টাকা (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                    f"• প্যাকেজ ৬: ৯৩ টাকা (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                    f"• প্যাকেজ ৭: ১০১ টাকা (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                    f"(নোট: ৩০-৪৯ পিস অর্ডারের ক্ষেত্রে ফিক্সড রেট প্রযোজ্য, কোনো ডিসকাউন্ট প্রযোজ্য নয়।)\n\n"
                    f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                )
            elif effective_qty < 80:
                # 50-79 pcs Regular Tier (Fixed Regular Price, 0 discount)
                price_text = (
                    f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্রতিটি প্যাকেজের ফিক্সড রেগুলার মূল্য নিচে দেওয়া হলো:\n\n"
                    f"• প্যাকেজ ১: ৭০ টাকা (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                    f"• প্যাকেজ ২: ৭০ টাকা (কার্ড + ফিতা + ডিএক্স কভার)\n"
                    f"• প্যাকেজ ৩: ৭৩ টাকা (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                    f"• প্যাকেজ ৪: ৭৩ টাকা (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                    f"• প্যাকেজ ৫: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                    f"• প্যাকেজ ৬: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                    f"• প্যাকেজ ৭: ৯১ টাকা (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                    f"(নোট: ৫০-৭৯ পিস অর্ডারের ক্ষেত্রে ফিক্সড রেগুলার রেট প্রযোজ্য, কোনো ডিসকাউন্ট প্রযোজ্য নয়।)\n\n"
                    f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                )
            else:
                # 80+ pcs Bulk Tier (Regular price upfront)
                price_text = (
                    f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্রতিটি প্যাকেজের রেগুলার মূল্য নিচে দেওয়া হলো:\n\n"
                    f"• প্যাকেজ ১: ৭০ টাকা (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                    f"• প্যাকেজ ২: ৭০ টাকা (কার্ড + ফিতা + ডিএক্স কভার)\n"
                    f"• প্যাকেজ ৩: ৭৩ টাকা (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                    f"• প্যাকেজ ৪: ৭৩ টাকা (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                    f"• প্যাকেজ ৫: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                    f"• প্যাকেজ ৬: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                    f"• প্যাকেজ ৭: ৯১ টাকা (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                    f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                )
        else:
            price_text = (
                f"জি {honorific}, প্রতিটি প্যাকেজের ছবির সাথে দাম লেখা আছে, তারপরও আপনাদের সুবিধার জন্য প্রতিটি প্যাকেজের বিস্তারিত মূল্য নিচে দেওয়া হলো:\n\n"
                f"• প্যাকেজ ১: ৭০ টাকা\n"
                f"• প্যাকেজ ২: ৭০ টাকা\n"
                f"• প্যাকেজ ৩: ৭৩ টাকা\n"
                f"• প্যাকেজ ৪: ৭৩ টাকা\n"
                f"• প্যাকেজ ৫: ৮৩ টাকা\n"
                f"• প্যাকেজ ৬: ৮৩ টাকা\n"
                f"• প্যাকেজ ৭: ৯১ টাকা\n\n"
                f"(নোট: উল্লেখিত প্যাকেজ রেট ১০০+ পিস অর্ডারের ক্ষেত্রে প্রযোজ্য। ৫০-৭৯ পিসের ক্ষেত্রে ফিক্সড রেগুলার রেট এবং ৩০-৪৯ পিসের ক্ষেত্রে প্রতি প্যাকেজে ১০ টাকা বেশি হবে।)\n\n"
                f"আপনার কত পিস আইডি কার্ড প্রয়োজন এবং কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
            )
        return {
            "reply_text": price_text,
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "id_card_package_pricing_breakdown"
        }

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
            if sender_id:
                try:
                    from app.ai_agent.conversation_state import update_conversation_state, SalesStage
                    update_conversation_state(
                        sender_id=str(sender_id),
                        updates={"quantity": qty, "quantity_source": "customer_message", "current_sales_stage": SalesStage.MOQ_REJECTED},
                        reason="moq_under_30",
                        workspace_id=ws_id
                    )
                except Exception:
                    pass
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
            if sender_id:
                try:
                    from app.ai_agent.conversation_state import update_conversation_state, SalesStage
                    update_conversation_state(
                        sender_id=str(sender_id),
                        updates={"quantity": qty, "quantity_source": "customer_message", "current_sales_stage": SalesStage.QUANTITY_IDENTIFIED},
                        reason="customer_provided_quantity",
                        workspace_id=ws_id
                    )
                except Exception:
                    pass

            # Check if user explicitly asked for samples in this same message
            user_explicit_sample_req = any(k in msg for k in [
                "স্যাম্পল", "ছবি", "প্যাকেজ", "পাঠান", "দেখান", "দিন", "দেন", "পাঠিয়ে দেন", "পাঠিয়ে দিন", "দেখতে চাই"
            ])
            if user_explicit_sample_req:
                if sender_id:
                    try:
                        from app.ai_agent.conversation_state import update_conversation_state, SalesStage
                        from datetime import datetime
                        update_conversation_state(
                            sender_id=str(sender_id),
                            updates={
                                "sample_permission": "granted",
                                "sample_sent": 1,
                                "sample_sent_at": datetime.now().isoformat(),
                                "current_sales_stage": SalesStage.SAMPLE_SENT
                            },
                            reason="sample_sequence_dispatched",
                            workspace_id=ws_id
                        )
                    except Exception:
                        pass
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

            # Check if package samples were already sent in conversation history!
            already_sent_packages = False
            if conversation_history:
                recent_bot_msgs = [
                    (m.get("content", "") or m.get("text", "") or "").lower() for m in conversation_history[-15:]
                    if str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower() in ("bot", "assistant", "seller", "ai")
                ]
                recent_bot_media = [
                    str(m.get("media_url") or "").lower() for m in conversation_history[-15:]
                    if str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower() in ("bot", "assistant", "seller", "ai")
                ]
                already_sent_packages = any(
                    any(ext in bm for ext in [
                        "pakage", "package", "pkg", "/uploads/package", "প্যাকেজ", "স্যাম্পলগুলো পাঠিয়ে দিচ্ছি",
                        "পছন্দ হয় জানাবেন", "পছন্দ হয়েছে জানাবেন", "এগুলো আমাদের কার্ড", "এগুলো আমাদের প্রিন্ট করা ফিতা",
                        "প্যাকেজগুলো পাঠানো হলো", "প্যাকেজের ছবি"
                    ])
                    for bm in recent_bot_msgs
                ) or any("package" in m or "sample" in m or "/uploads/" in m for m in recent_bot_media)

            is_asking_again = any(k in msg for k in ["আবার", "আসেনি", "পাইনি", "পাই নাই", "আসে নাই", "পুনরায়", "আবারও", "আবার পাঠান", "ছবি আসেনি"])
            if already_sent_packages and not is_asking_again:
                if 30 <= qty < 50:
                    tier_text = f"জি {honorific}, আমাদের প্যাকেজগুলোর রেট ১০০+ অর্ডারের ক্ষেত্রে প্রযোজ্য। আপনার যেহেতু ১০০ এর কম ({qty} পিস), তাই প্রতি প্যাকেজে ১০ টাকা করে বেশি হবে। আপনার কোন প্যাকেজটি পছন্দ জানাবেন প্লিজ।"
                elif 50 <= qty < 80:
                    tier_text = f"জি {honorific}, প্যাকেজের ছবিতে উল্লেখিত রেগুলার মূল্যে ({qty} পিসের জন্য) আমরা আপনার কাজটি নিখুঁতভাবে তৈরি করে দেব। আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন প্লিজ।"
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

            # If stating quantity (e.g. 50, 100, 500, 1000 pcs), ask permission before sending samples
            if sender_id:
                try:
                    from app.ai_agent.conversation_state import update_conversation_state, SalesStage
                    update_conversation_state(
                        sender_id=str(sender_id),
                        updates={"sample_permission": "pending", "current_sales_stage": SalesStage.SAMPLE_PERMISSION_PENDING},
                        reason="asked_sample_permission",
                        workspace_id=ws_id
                    )
                except Exception:
                    pass
            return {
                "reply_text": f"জি {honorific}, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?",
                "media_sequence": [],
                "matched_images": [],
                "voice_url": "",
                "video_url": "",
                "order_created": None,
                "response_source": "id_card_ask_sample_permission"
            }

    # Check if customer points out that samples were already sent (e.g. "স্যাম্পলগুলো তো পাঠিয়েছেন", "ছবি তো দিয়েছেন")
    is_pointing_out_already_sent = any(k in msg for k in [
        "তো পাঠিয়েছেন", "তো পাঠিয়েছেন", "তো পাঠাইছেন", "তো দিয়েছেন", "তো দিয়েছেন", "তো দিছেন",
        "আগেই দিয়েছেন", "আগেই দিয়েছেন", "আগেই পাঠিয়েছেন", "আগেই পাঠিয়েছেন", "আগেই পেয়েছি", "আগেই পাইছি",
        "আগে দিয়েছেন", "আগে দিয়েছেন", "আগে পাঠাইছেন", "আগে পাঠিয়েছেন", "আগে পাইছি", "আগে পেয়েছি",
        "তো পাইছি", "তো পেয়েছি", "তো দিলেন", "তো দিলেনই", "আগে দিছেন"
    ]) and any(k in msg for k in ["স্যাম্পল", "ছবি", "প্যাকেজ", "পিক", "কার্ড", "ফিতা", "কভার"])

    if is_pointing_out_already_sent:
        return {
            "reply_text": f"জি {honorific}, আন্তরিকভাবে দুঃখিত। পূর্বের পাঠানো স্যাম্পল ও প্যাকেজগুলো দেখে আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন প্লিজ, অথবা আপনার আর কোনো কিছু জানার থাকলে বলুন {honorific}।",
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "samples_already_sent_acknowledged"
        }

    # --- Detect if customer is inquiring about / confirming a specific package price ---
    # e.g. "প্যাকেজ ৬, ১০০+ অর্ডারে কত??" or "প্যাকেজ ৩ এর দাম কত"
    _specific_pkg_num = any(k in msg for k in [
        "প্যাকেজ ১", "প্যাকেজ ২", "প্যাকেজ ৩", "প্যাকেজ ৪", "প্যাকেজ ৫", "প্যাকেজ ৬", "প্যাকেজ ৭",
        "package 1", "package 2", "package 3", "package 4", "package 5", "package 6", "package 7"
    ])
    _has_price_terms = any(k in msg for k in [
        "টাকা", "তাকা", "taka", "tk", "রেট", "rate", "দাম", "মূল্য", "খরচ", "কম্বো", "অর্ডারে", "কত"
    ])
    is_specific_package_price_inquiry = _specific_pkg_num and _has_price_terms

    if is_specific_package_price_inquiry:
        pkg_num_map = {
            "প্যাকেজ ১": ("১", "৭০"), "প্যাকেজ ২": ("২", "৭০"), "প্যাকেজ ৩": ("৩", "৭৩"),
            "প্যাকেজ ৪": ("৪", "৭৩"), "প্যাকেজ ৫": ("৫", "৮৩"), "প্যাকেজ ৬": ("৬", "৮৩"),
            "প্যাকেজ ৭": ("৭", "৯১"),
            "package 1": ("১", "৭০"), "package 2": ("২", "৭০"), "package 3": ("৩", "৭৩"),
            "package 4": ("৪", "৭৩"), "package 5": ("৫", "৮৩"), "package 6": ("৬", "৮৩"),
            "package 7": ("৭", "৯১")
        }
        detected_pkg = None
        for pkg_key, (p_num, p_price) in pkg_num_map.items():
            if pkg_key in msg:
                detected_pkg = (p_num, p_price)
                break
        if detected_pkg:
            p_num, p_price = detected_pkg
            if effective_qty is not None and effective_qty >= 30:
                if effective_qty >= 80:
                    confirm_text = f"জি {honorific}, প্যাকেজ {p_num} এর রেগুলার মূল্য প্রতি সেট {p_price} টাকা। এটি কি আপনার অর্ডারের জন্য কনফার্ম করব জানাবেন প্লিজ।"
                elif effective_qty >= 50:
                    confirm_text = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য প্যাকেজ {p_num} এর ফিক্সড রেগুলার মূল্য প্রতি সেট {p_price} টাকা। এটি কি কনফার্ম করব জানাবেন প্লিজ।"
                else:
                    small_price = int(p_price) + 10
                    confirm_text = f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য (৩০-৪৯ পিস টিয়ারে) প্যাকেজ {p_num} এর মূল্য প্রতি সেট {small_price} টাকা। এটি কি কনফার্ম করব জানাবেন প্লিজ।"
            else:
                confirm_text = f"জি {honorific}, প্যাকেজ {p_num} এর মূল্য ১০০+ পিস অর্ডারে প্রতি সেট {p_price} টাকা। আপনার কত পিস প্রয়োজন {honorific}?"
        else:
            if effective_qty is not None and effective_qty >= 30:
                confirm_text = f"জি {honorific}, আপনার উল্লেখিত প্যাকেজের তথ্য সঠিক। এটি কি আপনার অর্ডারের জন্য কনফার্ম করব জানাবেন প্লিজ {honorific}?"
            else:
                confirm_text = f"জি {honorific}, আপনার উল্লেখিত প্যাকেজের তথ্য সঠিক। আপনার কত পিস প্রয়োজন {honorific}?"
        return {
            "reply_text": confirm_text,
            "media_sequence": [],
            "matched_images": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "response_source": "specific_package_price_confirmed"
        }

    # --- Global check: Were packages/samples already sent in recent conversation? ---
    _global_already_sent = False
    if conversation_history:
        _recent_bot = [
            (m.get("content", "") or m.get("text", "") or "").lower() for m in conversation_history[-15:]
            if str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower() in ("bot", "assistant", "seller", "ai")
        ]
        _recent_media = [
            str(m.get("media_url") or "").lower() for m in conversation_history[-15:]
            if str(m.get("sender") or m.get("sender_type") or m.get("role") or "").lower() in ("bot", "assistant", "seller", "ai")
        ]
        _global_already_sent = any(
            any(ext in bm for ext in [
                "pakage", "package", "pkg", "/uploads/package", "প্যাকেজ", "স্যাম্পলগুলো পাঠিয়ে দিচ্ছি",
                "পছন্দ হয় জানাবেন", "পছন্দ হয়েছে জানাবেন", "এগুলো আমাদের কার্ড", "এগুলো আমাদের প্রিন্ট করা ফিতা",
                "প্যাকেজগুলো পাঠানো হলো", "প্যাকেজের ছবি"
            ])
            for bm in _recent_bot
        ) or any("package" in m or "sample" in m or "/uploads/" in m for m in _recent_media)

    is_explicitly_asking_again = any(k in msg for k in ["আবার", "আসেনি", "পাইনি", "পাই নাই", "আসে নাই", "পুনরায়", "আবারও", "আবার পাঠান", "ছবি আসেনি"])

    # Case C: Confirming to send samples, or asking specifically for packages/samples
    is_sample_confirmation = bot_asked_sample_permission and is_affirmative_response(msg) and not any(k in msg for k in ["তো পাঠিয়েছেন", "তো দিয়েছেন", "আগেই", "আগে"])

    is_package_request = not is_pointing_out_already_sent and (
        is_sample_confirmation or (
            any(k in msg for k in [
                "প্যাকেজের ছবি", "প্যাকেজ দেখান", "প্যাকেজ পাঠান", "প্যাকেজের তালিকা",
                "কম্বো প্যাকেজ দেখান", "কম্বো প্যাকেজ পাঠান",
                "স্যাম্পল দেখান", "স্যাম্পল পাঠান", "স্যাম্পল দিন", "স্যাম্পল দেন", "স্যাম্পল দেখতে চাই", "স্যাম্পল দেখতে",
                "ছবি পাঠান", "ছবি দিন", "ছবি দেন", "ছবি দেখান", "ছবি দেখাও", "ছবি পাঠাও", "ছবি দেখতে চাই",
                "আবার পাঠান", "আবার দিন", "আবার দেন", "আবার দেখান", "ছবি আসেনি", "ছবিগুলো আসেনি", "ছবি পাই নাই", "ছবি পাইনি",
                "আচ্ছা দিন", "আচ্ছা পাঠান", "আচ্ছা দেন", "পাঠিয়ে দিন", "পাঠিয়ে দেন", "পাঠিয়ে দাও"
            ]) and not any(k in msg for k in ["এটি", "এটা", "এইটা", "এই প্যাকেজ", "পছন্দ", "নির্বাচন", "তো পাঠিয়েছেন", "তো দিয়েছেন", "আগেই", "আগে"])
        )
    )

    # CRITICAL: If packages already sent and NOT explicitly asking for re-send, BLOCK dispatch
    if is_package_request and _global_already_sent and not is_explicitly_asking_again and not is_sample_confirmation:
        is_package_request = False

    if is_package_request:
        if sender_id:
            try:
                from app.ai_agent.conversation_state import update_conversation_state, SalesStage
                from datetime import datetime
                update_conversation_state(
                    sender_id=str(sender_id),
                    updates={
                        "sample_permission": "granted",
                        "sample_sent": 1,
                        "sample_sent_at": datetime.now().isoformat(),
                        "current_sales_stage": SalesStage.SAMPLE_SENT
                    },
                    reason="sample_sequence_dispatched",
                    workspace_id=ws_id
                )
            except Exception:
                pass
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
        # Detect package number if explicitly mentioned
        selected_pkg = None
        for p_idx in ["১", "২", "৩", "৪", "৫", "৬", "৭", "1", "2", "3", "4", "5", "6", "7"]:
            if f"প্যাকেজ {p_idx}" in msg or f"package {p_idx}" in msg or msg.strip() == p_idx or f"প্যাকেজ {p_idx} দেন" in msg:
                selected_pkg = p_idx
                break

        if sender_id:
            try:
                from app.ai_agent.conversation_state import update_conversation_state, SalesStage
                update_conversation_state(
                    sender_id=str(sender_id),
                    updates={
                        "package_id": selected_pkg or "selected",
                        "package_source": "customer_selection",
                        "current_sales_stage": SalesStage.PACKAGE_IDENTIFIED,
                        "quoted_price": None  # Stale quote reset
                    },
                    reason="customer_selected_package",
                    workspace_id=ws_id
                )
            except Exception:
                pass

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
        "ছবি দিয়েন", "ছবি দিয়েন", "ছবি পাঠিয়েন", "ছবি পাঠিয়েন", "ছবি দিবেন", "ছবি পাঠাবেন",
        "স্যাম্পল দেখান", "স্যাম্পল পাঠান", "স্যাম্পল দেন", "স্যাম্পল দিন", "স্যাম্পল দিয়েন", "স্যাম্পল দিয়েন", "স্যাম্পল দেখতে চাই",
        "পিক দেখান", "পিক দেন", "পিক পাঠান", "পিকচার দেখান", "পিকচার পাঠান", "ফটো দেখান", "ফটো পাঠান", "ফটো দেন",
        "সব ছবি", "সবগুলো ছবি", "সব প্যাকেজ", "সবগুলো প্যাকেজ", "প্যাকেজের ছবি",
        "show photo", "send photo", "show sample", "send sample", "show pic", "send pic", "show image", "send image"
    ]) or (
        any(k in msg for k in ["ছবি", "স্যাম্পল", "ফটো", "পিক", "পিকচার"]) and
        any(a in msg for a in ["দেখান", "পাঠান", "দিন", "দেন", "দিয়েন", "দিয়েন", "পাঠিয়েন", "পাঠিয়েন", "দিবেন", "পাঠাবেন", "দেখবো", "show", "send", "তো"])
    ) or (
        any(k in msg for k in ["কভারের ছবি", "ফিতার ছবি", "কার্ডের ছবি", "প্যাকেজের ছবি", "কভারের স্যাম্পল", "ফিতার স্যাম্পল", "কার্ডের স্যাম্পল"])
    )

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
        "নিচে ছবিগুলো দেওয়া হলো", "নিচে ছবিগুলো দেয়া হলো", "নিচে ছবিগুলো পাঠানো হলো",
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
        is_asking_more = any(k in msg for k in ["আরও", "আরো", "অন্য", "নতুন", "more", "other", "different", "আবার", "সব", "আরদুইটা", "আর"])
        if already_sent_recently and not is_asking_more:
            return []

    req_count = parse_requested_image_count(msg)
    selected_images = []

    user_has_cover = any(k in msg for k in ["কভার", "হোল্ডার", "holder", "cover"])
    user_has_fita = any(k in msg for k in ["ফিতা", "রিবন", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"])
    user_has_id = any(k in msg for k in ["আইডি", "কার্ড", "id card", "card", "পিভিসি", "pvc"])
    user_has_pkg = any(k in msg for k in ["প্যাকেজ", "কম্বো", "package", "combo", "পেকেজ", "সব প্যাকেজ"])

    bot_has_cover = any(k in b_reply_low for k in ["কভার", "হোল্ডার", "holder", "cover"])
    bot_has_fita = any(k in b_reply_low for k in ["ফিতা", "রিবন", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"])
    bot_has_id = any(k in b_reply_low for k in ["আইডি", "কার্ড", "id card", "card", "পিভিসি", "pvc"])
    bot_has_pkg = any(k in b_reply_low for k in ["প্যাকেজ", "কম্বো", "package", "combo", "পেকেজ", "সব প্যাকেজ"])

    if user_has_cover or (not (user_has_fita or user_has_id or user_has_pkg) and bot_has_cover):
        selected_images = get_category_batch_images("cover", workspace_id=workspace_id)
    elif user_has_fita or (not (user_has_cover or user_has_id or user_has_pkg) and bot_has_fita):
        selected_images = get_category_batch_images("fita", workspace_id=workspace_id)
    elif user_has_id or (not (user_has_cover or user_has_fita or user_has_pkg) and bot_has_id):
        selected_images = get_category_batch_images("idc", workspace_id=workspace_id)
    else:
        selected_images = get_package_sample_images(workspace_id=workspace_id)

    if req_count and req_count > 0:
        return selected_images[:req_count]
    if is_agreeing_to_photo and not is_explicit_photo_req:
        return selected_images[:3]
    return selected_images

def detect_saved_media_to_send(
    user_msg: str,
    bot_reply: str = "",
    workspace_id: int = 1,
    conversation_history: list = None,
    conversation_state: dict = None
) -> dict:
    """Detects if customer EXPLICITLY requested a specific demo video or pre-recorded voice note using Intent-Based Media Router."""
    try:
        from app.ai_agent.media_router import detect_saved_media_to_send as mr_detect
        return mr_detect(
            user_msg=user_msg,
            bot_reply=bot_reply,
            workspace_id=workspace_id,
            conversation_history=conversation_history,
            conversation_state=conversation_state
        )
    except Exception as e:
        print(f"[MediaRouter Delegation Error]: {e}")
        return {"video_url": "", "voice_url": ""}

def generate_smart_fallback_reply(
    user_msg: str,
    customer_name: str = "",
    workspace_id: int = 1,
    page_id: str = "",
    conversation_state: Optional[Dict[str, Any]] = None
) -> str:
    """Generates an intelligent context-aware reply strictly isolated to the workspace if Gemini API is unreachable."""
    msg = (user_msg or "").strip().lower()
    honorific = detect_customer_gender_title(customer_name)
    from app.database import get_page_ai_config
    config = get_page_ai_config(page_id=page_id, workspace_id=workspace_id)
    shop_name = config.get("shop_name") or "Our Shop"
    inside_fee = int(float(config.get("delivery_inside_dhaka", 80.0)))
    outside_fee = int(float(config.get("delivery_outside_dhaka", 130.0)))

    refusal_phrases = [
        "চাচ্ছি না", "চাই না", "লাগবে না", "আর লাগবে না", "দরকার নেই", "দরকার নাই",
        "বানাতে চাচ্ছি না", "বানাব না", "বানাবো না", "করব না", "করবো না",
        "লাগবে না তো", "লাগবে না আমার", "নিব না", "নেব না", "দরকার নাই তো",
        "stop", "cancel", "not interested"
    ]
    if any(k in msg for k in refusal_phrases) or (len(msg.split()) == 1 and msg.strip() in ["না", "no"]):
        return f"জি {honorific}, ঠিক আছে। আপনার আর কোনো তথ্য বা অর্ডার সংক্রান্ত সহযোগিতা প্রয়োজন হলে জানাবেন প্লিজ।"

    if any(k in msg for k in ["ডেলিভারি", "কুরিয়ার", "delivery"]):
        return f"জি {honorific}, ডেলিভারি চার্জ ঢাকার ভেতরে {inside_fee} টাকা এবং ঢাকার বাইরে {outside_fee} টাকা (প্রতি কেজিতে ২০ টাকা এবং প্রতি হাজারে ১০ টাকা COD চার্জ প্রযোজ্য)।"

    if any(k in msg for k in ["সময়", "কতদিন", "কয়দিন", "time", "duration"]):
        return f"জি {honorific}, তথ্য দেওয়ার পর কাজ ও ডিজাইন করতে ৫-৬ দিন সময় লাগবে। প্রুফ অনুমোদনের পর প্রিন্ট করে ২৪-৪৮ ঘণ্টার মধ্যে কুরিয়ারে ডেলিভারি পেয়ে যাবেন।"

    if any(k in msg for k in ["কোয়ালিটি", "কোয়ালিটি", "মান কেমন", "কোয়ালিটি কেমন", "কোয়ালিটি কেমন হবে", "কোয়ালিটি কেমন হবে", "বৈশিষ্ট্য", "quality"]):
        return f"জি {honorific}, আমাদের কার্ড ও ফিতার কোয়ালিটি ও বৈশিষ্ট্য কেমন হবে সে সম্পর্কে বিস্তারিত জানতে নিচের ভয়েস বার্তাটি শুনুন:"

    # Workspace 1 (RS Graphics) specific fallbacks
    if int(workspace_id or 1) == 1:
        # Specific item price queries in fallback (Must precede general price queries)
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

        # Check photo taking / photography service in fallback
        if any(k in msg for k in ["ছবি কি আপনারা তুলে", "ছবি আপনারা তুলে", "ছবি তুলে নিয়ে যাবেন", "ছবি তুলে নিয়ে আসবেন", "ছবি তুলে দিয়ে যাবেন", "ছবি তুলে দেবেন", "ছবি তুলে দিবেন", "আপনারা কি ছবি তুলে", "আপনারা এসে ছবি", "এসে ছবি তুলবেন", "ফটোগ্রাফার"]):
            return f"জি না {honorific}, আমরা সরাসরি প্রতিষ্ঠানে গিয়ে ছবি তুলি না। আপনারা আপনাদের মোবাইল বা ক্যামেরা দিয়ে শিক্ষার্থীদের পরিষ্কার ছবি তুলে আমাদের হোয়াটসঅ্যাপে (01816504097) অথবা আমাদের তৈরি করা গুগল ফর্মে পাঠিয়ে দিলেই আমরা অত্যন্ত আকর্ষণীয় ও নিখুঁতভাবে আইডি কার্ড প্রিন্ট করে ডেলিভারি করে দেব।"

        # Check unlisted products in fallback
        unlisted_keywords = [
            "কলম", "পেন", "pen", "বলপেন", "খাতা", "ডায়েরি", "ডায়েরি", "diary", "মগ", "mug",
            "টি-শার্ট", "টি শার্ট", "tshirt", "t-shirt", "ব্যাগ", "bag", "স্ট্যাম্প", "stamp", "সিল", "seal"
        ]
        if any(k in msg for k in unlisted_keywords) and not any(k in msg for k in ["আইডি", "কার্ড", "ফিতা", "কভার"]):
            return f"জি {honorific}, আপনার এই বিষয়টি আমরা নোট করেছি। আমাদের টিম বিষয়টি জেনে আপনাকে বিস্তারিত জানিয়ে দেবে, ইনশাআল্লাহ।"

        # Check package price / per piece rate in fallback
        if any(k in msg for k in ["প্যাকেজের দাম", "প্যাকেজের রেট", "প্যাকেজগুলোর দাম", "প্যাকেজ কত", "প্যাকেজের খরচ", "প্যাকেজের বিস্তারিত মূল্য", "প্রতি পিস", "প্রতি পিস কত", "প্রতি পিস কত টাকা", "প্রতি পিস কত রাখবেন", "প্রতি পিস কত করে", "দাম কত", "রেট কত"]):
            state_qty = conversation_state.get("quantity") if conversation_state else None
            qty = extract_order_quantity_number(msg)
            effective_fallback_qty = qty if qty is not None else state_qty
            if effective_fallback_qty and effective_fallback_qty >= 30:
                if effective_fallback_qty < 50:
                    return (
                        f"জি {honorific}, আপনার {effective_fallback_qty} পিস অর্ডারের জন্য (৩০-৪৯ পিস টিয়ারে প্রতি সেটে ১০ টাকা অতিরিক্ত চার্জ প্রযোজ্য) প্রতিটি প্যাকেজের মূল্য নিচে দেওয়া হলো:\n\n"
                        f"• প্যাকেজ ১: ৮০ টাকা (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                        f"• প্যাকেজ ২: ৮০ টাকা (কার্ড + ফিতা + ডিএক্স কভার)\n"
                        f"• প্যাকেজ ৩: ৮৩ টাকা (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                        f"• প্যাকেজ ৪: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                        f"• প্যাকেজ ৫: ৯৩ টাকা (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                        f"• প্যাকেজ ৬: ৯৩ টাকা (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                        f"• প্যাকেজ ৭: ১০১ টাকা (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                        f"(নোট: ৩০-৪৯ পিস অর্ডারের ক্ষেত্রে ফিক্সড রেট প্রযোজ্য, কোনো ডিসকাউন্ট প্রযোজ্য নয়।)\n\n"
                        f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                    )
                elif effective_fallback_qty < 80:
                    return (
                        f"জি {honorific}, আপনার {effective_fallback_qty} পিস অর্ডারের জন্য প্রতিটি প্যাকেজের ফিক্সড রেগুলার মূল্য নিচে দেওয়া হলো:\n\n"
                        f"• প্যাকেজ ১: ৭০ টাকা (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                        f"• প্যাকেজ ২: ৭০ টাকা (কার্ড + ফিতা + ডিএক্স কভার)\n"
                        f"• প্যাকেজ ৩: ৭৩ টাকা (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                        f"• প্যাকেজ ৪: ৭৩ টাকা (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                        f"• প্যাকেজ ৫: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                        f"• প্যাকেজ ৬: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                        f"• প্যাকেজ ৭: ৯১ টাকা (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                        f"(নোট: ৫০-৭৯ পিস অর্ডারের ক্ষেত্রে ফিক্সড রেগুলার রেট প্রযোজ্য, কোনো ডিসকাউন্ট প্রযোজ্য নয়।)\n\n"
                        f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                    )
                else:
                    return (
                        f"জি {honorific}, আপনার {effective_fallback_qty} পিস অর্ডারের জন্য প্রতিটি প্যাকেজের রেগুলার মূল্য নিচে দেওয়া হলো:\n\n"
                        f"• প্যাকেজ ১: ৭০ টাকা (কার্ড + ১.৫ সেমি ফিতা + সফট কভার)\n"
                        f"• প্যাকেজ ২: ৭০ টাকা (কার্ড + ফিতা + ডিএক্স কভার)\n"
                        f"• প্যাকেজ ৩: ৭৩ টাকা (কার্ড + ফিতা + সফট কভার কম্বো)\n"
                        f"• প্যাকেজ ৪: ৭৩ টাকা (কার্ড + ২ সেমি ফিতা + ডিএক্স কভার কম্বো)\n"
                        f"• প্যাকেজ ৫: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + T-994V কভার কম্বো)\n"
                        f"• প্যাকেজ ৬: ৮৩ টাকা (কার্ড + ২ সেমি ফিতা + REAP কভার কম্বো)\n"
                        f"• প্যাকেজ ৭: ৯১ টাকা (মেটাল ফ্রেম / লাক্সারি ফুল কম্বো)\n\n"
                        f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
                    )
            return (
                f"জি {honorific}, প্রতিটি প্যাকেজের ছবির সাথে দাম লেখা আছে, তারপরও আপনাদের সুবিধার জন্য প্রতিটি প্যাকেজের বিস্তারিত মূল্য নিচে দেওয়া হলো:\n\n"
                f"• প্যাকেজ ১: ৭০ টাকা\n"
                f"• প্যাকেজ ২: ৭০ টাকা\n"
                f"• প্যাকেজ ৩: ৭৩ টাকা\n"
                f"• প্যাকেজ ৪: ৭৩ টাকা\n"
                f"• প্যাকেজ ৫: ৮৩ টাকা\n"
                f"• প্যাকেজ ৬: ৮৩ টাকা\n"
                f"• প্যাকেজ ৭: ৯১ টাকা\n\n"
                f"(নোট: উল্লেখিত প্যাকেজ রেট ১০০+ পিস অর্ডারের ক্ষেত্রে প্রযোজ্য। ৫০-৭৯ পিসের ক্ষেত্রে ফিক্সড রেগুলার রেট এবং ৩০-৪৯ পিসের ক্ষেত্রে প্রতি প্যাকেজে ১০ টাকা বেশি হবে।)\n\n"
                f"আপনার কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ {honorific}।"
            )

        qty = extract_order_quantity_number(msg)
        state_qty = conversation_state.get("quantity") if conversation_state else None
        effective_qty = qty if qty is not None else state_qty

        if effective_qty is not None:
            if effective_qty < 30:
                return f"দুঃখিত {honorific}, আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা আইডি কার্ডের অর্ডার নিচ্ছি।"
            else:
                if any(k in msg for k in ["প্যাকেজ", "দাম", "রেট", "মূল্য", "খরচ", "কত"]):
                    if effective_qty >= 80:
                        return f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য আমাদের রেগুলার প্যাকেজ রেট প্রযোজ্য হবে। কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ।"
                    elif effective_qty >= 50:
                        return f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য ফিক্সড রেগুলার প্যাকেজ রেট প্রযোজ্য হবে। কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ।"
                    else:
                        return f"জি {honorific}, আপনার {effective_qty} পিস অর্ডারের জন্য (৩০-৪৯ পিস টিয়ারে) রেগুলার রেটের চেয়ে প্রতি সেটে ১০ টাকা বেশি হবে। কোন প্যাকেজটি পছন্দ হয়েছে জানাবেন প্লিজ।"
                return f"জি {honorific}, অবশ্যই। আমাদের স্যাম্পলগুলো পাঠাবো কি?"

        # Conversational Greetings & Pleasantries in fallback
        if any(k in msg for k in ["আসসালামু আলাইকুম", "সালাম", "assalamu", "salam"]):
            return f"ওয়ালাইকুমুস সালাম {honorific}! আরএস গ্রাফিক্সের পক্ষ থেকে আপনাকে স্বাগতম। আপনাকে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ।"

        if any(k in msg for k in ["ভালো আছেন", "কেমন আছেন", "ভাল আছেন", "valo achen", "kemon achen"]):
            return f"আলহামদুলিল্লাহ {honorific}, আমি ভালো আছি। আপনি কেমন আছেন? আপনাকে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ।"

        if any(k in msg for k in ["কি কর", "কি করো", "কি করেন", "ki kor", "ki koro", "কি করছো"]):
            return f"জি {honorific}, আমি আরএস গ্রাফিক্সের সেলস সহকারী নাদিম। আপনাদের সেবায় প্রস্তুত আছি। আইডি কার্ড, ফিতা বা প্রিন্টিং সংক্রান্ত যেকোনো তথ্যে সহযোগিতা করতে পারি।"

        if any(k in msg for k in ["আপনি কে", "কে আপনি", "আপনার নাম", "নাম কি", "নাম কী", "who are you"]):
            return f"জি {honorific}, আমার নাম নাদিম। আমি আরএস গ্রাফিক্সের সেলস সহকারী হিসেবে দায়িত্ব পালন করছি।"

        if any(k in msg for k in ["মালিক", "ওনার", "owner"]):
            return f"জি {honorific}, বিষয়টি আমাদের টিমকে জানাচ্ছি। আমাদের টিম আপনাকে বিস্তারিত জানিয়ে দেবে।"

        if any(k in msg for k in ["hi", "hello", "হাই", "হ্যালো", "hey"]):
            return f"জি {honorific}, আরএস গ্রাফিক্সের পক্ষ থেকে আপনাকে স্বাগতম। আপনাকে কীভাবে সহযোগিতা করতে পারি জানাবেন প্লিজ।"

        if any(k in msg for k in ["ভয়েস", "ভয়েস", "voice", "audio"]):
            return f"জি {honorific}, আপনার ভয়েস বার্তাটি পেয়েছি। আপনার আইডি কার্ড, ফিতা বা প্রিন্টিং সংক্রান্ত যেকোনো প্রশ্ন থাকলে বলুন, আমি বিস্তারিত জানিয়ে সহযোগিতা করছি।"

        if any(k in msg for k in ["বানানো দরকার", "কিছু বানানো", "বানাতে চাই", "প্রিন্ট করতে চাই"]):
            return f"জি {honorific}, অবশ্যই বানাতে পারবেন! আপনি কত পিস আইডি কার্ড বা ফিতা করতে চান এবং কার্ডের সঙ্গে ফিতা ও কভারও নিতে চান কি?"

        if any(k in msg for k in ["প্রিমিয়াম", "প্রিমিয়াম", "প্যাকেজ ৭", "প্যাকেজ 7", "সবচেয়ে ভালো"]):
            return f"জি {honorific}, আমাদের সবচেয়ে প্রিমিয়াম প্যাকেজ হলো 'প্যাকেজ ৭'। এতে থাকছে ডিজিটাল সাটিন মাল্টিকালার ফিতা, ১০০% ওয়াটারপ্রুফ এইচডি কার্ড ও মেটাল ফ্রেম কভার (প্রতি সেট ৯১ টাকা)।"

        if any(k in msg for k in ["আইডি কার্ড", "আইডি কাড", "id card", "আইডিকার্ড", "কার্ড বানাতে", "কার্ড করতে", "কার্ড বানাবো"]):
            return f"জি {honorific}, আপনি আইডি কার্ড কত পিস বানাবেন?"

        if any(k in msg for k in ["প্যাকেজ", "কম্বো", "package", "combo"]):
            return f"জি {honorific}, আপনি কত পিস আইডি কার্ড বানাবেন জানাবেন প্লিজ?"

        if any(k in msg for k in ["ফিতা", "ল্যানিয়ার্ড", "ribbon", "lanyard", "fita"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
            return f"জি {honorific}, নিচে আমাদের ডিজিটাল সাবলিমেশন ফিতার কিছু স্যাম্পল ছবি দেওয়া হলো। আপনার কত পিস ফিতা প্রয়োজন জানাবেন প্লিজ?"

        if any(k in msg for k in ["আইডি", "কার্ড", "id card"]) and any(k in msg for k in ["ছবি", "স্যাম্পল", "photo", "picture"]):
            return f"জি {honorific}, নিচে আমাদের জাপানি UV প্রিন্ট আইডি কার্ডের স্যাম্পল ছবিগুলো দেওয়া হলো। আপনার কত পিস আইডি কার্ড প্রয়োজন জানাবেন প্লিজ?"

        if any(k in msg for k in ["দাম", "রেট", "মূল্য", "price", "cost"]):
            return f"জি {honorific}, আপনি আইডি কার্ড কত পিস বানাবেন জানাবেন প্লিজ? আমাদের সর্বনিম্ন অর্ডারের পরিমাণ হলো ৩০ পিস।"

        return f"জি {honorific}, আপনার আইডি কার্ড, ফিতা বা প্রিন্টিং সংক্রান্ত যেকোনো প্রশ্ন থাকলে আমাকে জানাতে পারেন, আমি বিস্তারিত জানিয়ে সহযোগিতা করছি।"

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

    # 0. Load persistent conversation state for context and safety guards
    saved_state = {}
    if sender_id:
        try:
            from app.ai_agent.conversation_state import get_structured_conversation_state
            saved_state = get_structured_conversation_state(str(sender_id), ws_id)
        except Exception:
            saved_state = {}

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

    # 1. HIGHEST-PRIORITY: Deterministic Google Form Creation Workflow (Only for text messages)
    if not audio_bytes:
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
                    "voice_url": workflow_res.get("voice_url", ""),
                    "video_url": workflow_res.get("video_url", ""),
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
                workspace_id=ws_id,
                sender_id=sender_id
            )
            if id_flow_res:
                return id_flow_res
        except Exception as e:
            print(f"[ID Card Workflow Early Resolution Warning]: {e}")

    # Check if API key is provided
    if not api_key:
        fallback_reply = generate_smart_fallback_reply(message_text, customer_name, workspace_id=ws_id, page_id=page_id, conversation_state=saved_state)
        matched_imgs = detect_sample_photos_to_send(message_text, conversation_history, fallback_reply, workspace_id=ws_id)
        media_found = detect_saved_media_to_send(message_text, fallback_reply, workspace_id=ws_id, conversation_state=saved_state)
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
            detected_audio_mime = audio_mime or "audio/mp4"
            if audio_bytes.startswith(b"RIFF"):
                detected_audio_mime = "audio/wav"
            elif audio_bytes.startswith(b"OggS"):
                detected_audio_mime = "audio/ogg"
            elif audio_bytes.startswith(b"\xff\xfb") or audio_bytes.startswith(b"\xff\xf3") or audio_bytes.startswith(b"ID3"):
                detected_audio_mime = "audio/mp3"
            elif audio_bytes.startswith(b"\xff\xf1") or audio_bytes.startswith(b"\xff\xf9"):
                detected_audio_mime = "audio/aac"
            elif audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
                detected_audio_mime = "audio/webm"
            elif audio_bytes.startswith(b"fLaC"):
                detected_audio_mime = "audio/flac"
            elif b"ftyp" in audio_bytes[:20] or b"M4A" in audio_bytes[:20] or audio_bytes.startswith(b"\x00\x00\x00"):
                detected_audio_mime = "audio/mp4"

            contents.append(types.Part.from_bytes(data=audio_bytes, mime_type=detected_audio_mime))
            message_text = "কাস্টমার একটি ভয়েস অডিও বার্তা পাঠিয়েছেন। অডিওটি মনোযোগ দিয়ে শুনে কাস্টমার যা বলেছেন বা জানতে চেয়েছেন, ঠিক তার সরাসরি ও সঠিক উত্তর দিন। কখনোই কাস্টমারকে 'টাইপ করে দিন' বা 'ভয়েস পেয়েছি' বলবেন না।"

        if message_text:
            contents.append(f"কাস্টমারের বার্তা ({customer_name}): {message_text}")

        # Prioritize high-quota active working models
        candidate_models = [
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash"
        ]

        response = None
        system_instruction = build_system_instruction(
            customer_name=customer_name,
            workspace_id=ws_id,
            page_id=page_id,
            conversation_state=saved_state
        )

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

        raw_text = response.text if response and response.text else generate_smart_fallback_reply(
            message_text,
            customer_name,
            workspace_id=ws_id,
            page_id=page_id,
            conversation_state=saved_state
        )

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

        # Detect demo videos and pre-recorded voice clips via Intent-Based Media Router
        media_found = detect_saved_media_to_send(
            user_msg=message_text,
            bot_reply=clean_reply,
            workspace_id=ws_id,
            conversation_history=conversation_history
        )
        matched_video_url = media_found.get("video_url", "")
        matched_voice_url = media_found.get("voice_url", "")

        draft_out = {
            "reply_text": clean_reply,
            "voice_url": matched_voice_url or (generate_bangla_voice(clean_reply) if generate_voice_reply else ""),
            "video_url": matched_video_url,
            "order_created": order_created,
            "matched_images": matched_images
        }
        try:
            from app.ai_agent.response_validator import ResponseValidator
            return ResponseValidator.validate_and_sanitize(
                draft_response=draft_out,
                customer_message=message_text,
                conversation_history=conversation_history,
                sender_id=sender_id,
                customer_name=customer_name,
                workspace_id=ws_id,
                channel=channel
            )
        except Exception as v_err:
            print(f"[Response Validator Error]: {v_err}")
            return draft_out

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
                draft_wf = {
                    "reply_text": workflow_res["reply"],
                    "voice_url": "",
                    "video_url": "",
                    "order_created": None,
                    "matched_images": []
                }
                try:
                    from app.ai_agent.response_validator import ResponseValidator
                    return ResponseValidator.validate_and_sanitize(
                        draft_response=draft_wf,
                        customer_message=message_text,
                        conversation_history=conversation_history,
                        sender_id=sender_id,
                        customer_name=customer_name,
                        workspace_id=ws_id,
                        channel=channel
                    )
                except Exception:
                    return draft_wf
        except Exception:
            pass

        err_msg = generate_smart_fallback_reply(message_text, customer_name, workspace_id=ws_id, page_id=page_id)
        draft_fb = {
            "reply_text": err_msg,
            "voice_url": "",
            "video_url": "",
            "order_created": None,
            "matched_images": detect_sample_photos_to_send(message_text, conversation_history, err_msg, workspace_id=ws_id)
        }
        try:
            from app.ai_agent.response_validator import ResponseValidator
            return ResponseValidator.validate_and_sanitize(
                draft_response=draft_fb,
                customer_message=message_text,
                conversation_history=conversation_history,
                sender_id=sender_id,
                customer_name=customer_name,
                workspace_id=ws_id,
                channel=channel
            )
        except Exception:
            return draft_fb
