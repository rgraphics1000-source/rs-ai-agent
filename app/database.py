import os
import sqlite3
import json
from datetime import datetime
from app.config import settings

DB_PATH = settings.BASE_DIR / "rs_ai.db"

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the SQLite database with all necessary tables."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Products Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        code TEXT UNIQUE,
        description TEXT,
        price REAL NOT NULL,
        discount_price REAL,
        stock INTEGER DEFAULT 10,
        category TEXT DEFAULT 'General',
        image_url TEXT,
        gallery_images TEXT DEFAULT '[]',
        tags TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Auto-migration for existing databases
    try:
        cursor.execute("ALTER TABLE products ADD COLUMN gallery_images TEXT DEFAULT '[]'")
        conn.commit()
    except Exception:
        pass

    # 2. Orders Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_code TEXT UNIQUE NOT NULL,
        customer_name TEXT NOT NULL,
        customer_phone TEXT NOT NULL,
        customer_address TEXT NOT NULL,
        items_summary TEXT NOT NULL,
        items_json TEXT,
        subtotal REAL NOT NULL,
        delivery_charge REAL NOT NULL,
        total_amount REAL NOT NULL,
        channel TEXT DEFAULT 'facebook', -- 'facebook', 'whatsapp', 'web'
        sender_id TEXT,
        status TEXT DEFAULT 'Pending', -- 'Pending', 'Confirmed', 'Processing', 'Shipped', 'Delivered', 'Cancelled'
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Conversations Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT NOT NULL, -- 'facebook', 'whatsapp', 'web_playground'
        sender_id TEXT NOT NULL UNIQUE,
        customer_name TEXT,
        last_message TEXT,
        human_takeover INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. Messages Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER,
        sender_type TEXT NOT NULL, -- 'user', 'bot', 'admin'
        message_type TEXT DEFAULT 'text', -- 'text', 'image', 'audio'
        content TEXT,
        media_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    );
    """)

    # 5. Comment Logs Table (Facebook Posts)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comment_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id TEXT,
        comment_id TEXT UNIQUE NOT NULL,
        user_id TEXT,
        user_name TEXT,
        comment_text TEXT,
        public_reply TEXT,
        private_reply TEXT,
        replied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 6. Train Content FAQs & Knowledge Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS faqs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 7. AI Training & Knowledge Base Rules Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_training_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        rule_type TEXT DEFAULT 'qa', -- 'qa', 'instruction', 'price_policy', 'objection_handling'
        question_or_trigger TEXT,
        response_or_rule TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 8. Saved Media Library (Voice Notes & Product Videos)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS saved_media (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        media_type TEXT NOT NULL, -- 'voice', 'video', 'image', 'document'
        file_url TEXT NOT NULL,
        description TEXT,
        duration_seconds INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 9. Shop & Automation Settings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)

    # Seed default settings if not exists
    default_settings = {
        "shop_name": settings.SHOP_NAME,
        "shop_phone": settings.SHOP_PHONE,
        "shop_address": "ঢাকা, বাংলাদেশ",
        "delivery_inside_dhaka": str(settings.DELIVERY_FEE_INSIDE_DHAKA),
        "delivery_outside_dhaka": str(settings.DELIVERY_FEE_OUTSIDE_DHAKA),
        "comment_auto_reply": "true",
        "comment_reply_template": "ধন্যবাদ {name} আপু/ভাইয়া! বিস্তারিত তথ্য ও ছবি আপনার ইনবক্সে পাঠানো হয়েছে 🥰",
        "private_message_on_comment": "true",
        "ai_system_prompt": (
            "তুমি একটি অত্যন্ত মিষ্টিভাষী, বিনম্র ও দক্ষ বাংলাদেশি ই-কমার্স সেলস এজেন্ট (Sales Assistant)। "
            "তোমার কাজ হলো কাস্টমারের সাথে সুন্দর করে কথা বলা (যেমন: 'আসসালামু আলাইকুম আপু/ভাইয়া', 'কেমন আছেন?', 'জি অবশ্যই')। "
            "কাস্টমারকে প্রডাক্ট পছন্দ করতে সাহায্য করবে, দাম ও স্টক জানাবে এবং অর্ডার করতে চাইলে বিনয়ের সাথে নাম, মোবাইল নম্বর (১১ ডিজিট) ও সম্পূর্ণ ডেলিভারি ঠিকানা সংগ্রহ করবে। "
            "ঢাকার ভেতরে ডেলিভারি চার্জ {delivery_inside} টাকা এবং ঢাকার বাইরে {delivery_outside} টাকা। "
            "সব প্রয়োজনীয় তথ্য পাওয়ার সাথে সাথে কাস্টমারকে অর্ডারের সামারি দিয়ে কনফার্ম করবে।"
        ),
        "gemini_api_key": settings.GEMINI_API_KEY,
        "meta_app_id": settings.META_APP_ID,
        "meta_embedded_signup_config_id": settings.META_EMBEDDED_SIGNUP_CONFIG_ID,
        "fb_page_access_token": settings.FB_PAGE_ACCESS_TOKEN,
        "fb_verify_token": settings.FB_VERIFY_TOKEN,
        "whatsapp_waba_id": settings.WHATSAPP_WABA_ID,
        "whatsapp_phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID,
        "meta_system_user_access_token": settings.META_SYSTEM_USER_ACCESS_TOKEN,
        "whatsapp_access_token": settings.WHATSAPP_ACCESS_TOKEN,
        "whatsapp_verify_token": settings.WHATSAPP_VERIFY_TOKEN,
        "whatsapp_display_phone_number": settings.WHATSAPP_DISPLAY_PHONE_NUMBER,
        "whatsapp_connection_mode": "business_app_coexistence",
        "whatsapp_connection_status": "connected" if (settings.META_SYSTEM_USER_ACCESS_TOKEN or settings.WHATSAPP_ACCESS_TOKEN) else "not_connected",
        "voice_enabled": "true",
        "voice_type": "bn-BD-NabanitaNeural" # Bangla female natural voice
    }

    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    # Migration: update any stale 17-digit config_id to official 16-digit ID
    cursor.execute("UPDATE settings SET value = '1003403176086013' WHERE key = 'meta_embedded_signup_config_id' AND value = '10034031760860138'")
    # Migration: clear unrelated phone number ID 1265595526643418 so only verified target ID is stored
    cursor.execute("UPDATE settings SET value = '' WHERE key = 'whatsapp_phone_number_id' AND value = '1265595526643418'")

    # Seed initial AI Training Rules if none exist
    cursor.execute("SELECT COUNT(*) FROM ai_training_rules")
    if cursor.fetchone()[0] == 0:
        initial_rules = [
            ("ন্যূনতম অর্ডার পরিমাণ (MOQ)", "আমাদের ন্যূনতম অর্ডার পরিমাণ ২০ পিস। ২০ পিসের কম কোনো অর্ডার নেওয়া হচ্ছে না।", "instruction", "কত পিস অর্ডার নেওয়া হয়?", "Pricing & MOQ", 1),
            ("ক্যাশ অন ডেলিভারি ও ডেলিভারি চার্জ", "ঢাকার ভেতরে ডেলিভারি চার্জ ৭০ টাকা এবং ঢাকার বাইরে ১৩০ টাকা। সারা বাংলাদেশে ক্যাশ অন ডেলিভারি সুবিধা রয়েছে।", "qa", "ডেলিভারি চার্জ কত?", "Delivery & Payment", 1),
            ("ইউভি প্রিন্ট কোয়ালিটি", "আমরা জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট করি, যা ১০০% ওয়াটারপ্রুফ, প্রিমিয়াম ফিনিশিং এবং দীর্ঘস্থায়ী।", "qa", "কোয়ালিটি কেমন?", "Product Quality", 1),
            ("ডিসকাউন্ট পলিসি", "প্রথমে নিয়মিত বিক্রয়মূল্য বলবে। কাস্টমার ৫০ বা ১০০+ পিস চাইলে বা দাম বেশি বললে স্পেশাল হোলসেল রেট অফার করবে।", "price_policy", "ডিসকাউন্ট বা কম রাখা যাবে?", "Price Policy", 1),
            ("ক্রয়মূল্য গোপন রাখা", "কাস্টমারকে কখনো আমাদের নিজস্ব উৎপাদন বা ক্রয়মূল্য বলা যাবে না। সর্বদা সেল প্রাইস বলতে হবে।", "instruction", "", "Business Policy", 1),
            ("স্যাম্পল ছবি পাঠানোর নিয়ম", "কাস্টমার ছবি বা স্যাম্পল দেখতে চাইলে সরাসরি ছবি না দিয়ে আগে অনুমতি চাইবে 'আমি কি আমাদের কিছু স্যাম্পল ছবি পাঠাবো?' কাস্টমার সম্মতি দিলে সম্পূর্ণ স্যাম্পল পাঠাবে।", "instruction", "", "Sales Rule", 1)
        ]
        cursor.executemany("""
            INSERT INTO ai_training_rules (title, response_or_rule, rule_type, question_or_trigger, category, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, initial_rules)

    # Seed/Update Real Products with Individual Variation Prices
    pkg_variations = [
        {"url": "/static/uploads/pakage/IMG-20260113-WA0002.jpg", "title": "প্যাকেজ ০১ (UV কার্ড + ১.৫ সেমি ফিতা + স্বচ্ছ প্লাস্টিক কভার)", "price": 70, "code": "PKG-01"},
        {"url": "/static/uploads/pakage/IMG-20260113-WA0003.jpg", "title": "প্যাকেজ ০২ (UV কার্ড + ১.৫ সেমি ফিতা + কালারফুল কভার)", "price": 70, "code": "PKG-02"},
        {"url": "/static/uploads/pakage/IMG-20260113-WA0006.jpg", "title": "প্যাকেজ ০৩ (UV কার্ড + ২ সেমি ফিতা + প্রিমিয়াম হার্ড প্লাস্টিক কভার)", "price": 83, "code": "PKG-03"},
        {"url": "/static/uploads/pakage/IMG-20260114-WA0057.jpg", "title": "প্যাকেজ ০৭ (UV কার্ড + ২ সেমি ফিতা + মেটাল লক প্রিমিয়াম কভার সেট)", "price": 91, "code": "PKG-07"},
        {"url": "/static/uploads/pakage/IMG-20260117-WA0023.jpg", "title": "প্যাকেজ ০৪ (স্পেশাল ফিতা ও কভার কম্বো)", "price": 75, "code": "PKG-04"},
        {"url": "/static/uploads/pakage/IMG-20260118-WA0045.jpg", "title": "প্যাকেজ ০৫ (ডাবল সাইডেড কার্ড ও ফিতা সেট)", "price": 80, "code": "PKG-05"},
        {"url": "/static/uploads/pakage/IMG-20260121-WA0081.jpg", "title": "প্যাকেজ ০৬ (ডিলাক্স মেটাল প্যাকেজ)", "price": 85, "code": "PKG-06"}
    ]

    id_card_imgs = [
        {"url": f'/static/uploads/id_card/{f.name}', "title": "জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট PVC আইডি কার্ড", "price": 30}
        for f in (settings.UPLOADS_DIR / 'id_card').glob('*.jpg')
    ] if (settings.UPLOADS_DIR / 'id_card').exists() else []

    fita_imgs = [
        {"url": f'/static/uploads/fita/{f.name}', "title": "ডিজিটাল মাল্টিকালর সাবলিমেশন ফিতা (১.৫ ও ২ সেমি)", "price": 20}
        for f in (settings.UPLOADS_DIR / 'fita').glob('*.jpg')
    ] if (settings.UPLOADS_DIR / 'fita').exists() else []

    cover_imgs = [
        {"url": f'/static/uploads/cover/{f.name}', "title": "আইডি কার্ড কভার ও প্লাস্টিক/হার্ড হোল্ডার", "price": 12}
        for f in (settings.UPLOADS_DIR / 'cover').glob('*.jpg')
    ] if (settings.UPLOADS_DIR / 'cover').exists() else []

    cursor.execute("SELECT COUNT(*) FROM products WHERE code = 'PKG-COMBO'")
    if cursor.fetchone()[0] == 0:
        real_products = [
            (
                'আইডি কার্ড (জাপানি মেশিনের UV PRINT)',
                'IDC-01',
                'জাপানি মেশিনের অরজিনাল হাই-কোয়ালিটি UV কালার প্রিন্ট, ১০০% ওয়াটারপ্রুফ এবং প্রিমিয়াম ফ্লেক্সিবল PVC ফিনিশিং। রেগুলার ৩৫ টাকা, অফার মূল্য ৩০ টাকা।',
                35.0, 30.0, 1000, 'আইডি কার্ড',
                id_card_imgs[0]["url"] if id_card_imgs else '',
                json.dumps(id_card_imgs),
                'id card, uv print, pvc card'
            ),
            (
                'ডিজিটাল সাবলিমেশন ফিতা (Lanyards / Ribbons)',
                'FITA-02',
                'ডিজিটাল মাল্টিকালর সাবলিমেশন প্রিন্ট, প্রিমিয়াম সাটিন ফেব্রিক ও হেভি ডিউটি হুক। ১.৫ সেমি ২০৳, ২ সেমি ৩০৳।',
                25.0, 20.0, 1000, 'ফিতা ও লেইনিয়ার্ড',
                fita_imgs[0]["url"] if fita_imgs else '',
                json.dumps(fita_imgs),
                'fita, lanyard, ribbon'
            ),
            (
                'আইডি কার্ড হোল্ডার ও কভার (Card Holders)',
                'COV-03',
                'স্বচ্ছ প্লাস্টিক কভার (১০৳), কালারফুল বর্ডার (১২৳) ও প্রিমিয়াম হার্ড প্লাস্টিক ডাবল সাইডেড হোল্ডার (১৫৳)।',
                15.0, 12.0, 1000, 'কভার ও হোল্ডার',
                cover_imgs[0]["url"] if cover_imgs else '',
                json.dumps(cover_imgs),
                'holder, cover, card holder'
            ),
            (
                'আইডি কার্ড সম্পূর্ণ কম্বো প্যাকেজ (কার্ড + ফিতা + কভার)',
                'PKG-COMBO',
                'জাপানি UV প্রিন্ট কার্ড + ডিজিটাল প্রিন্ট ফিতা + কভার। প্যাকেজ ০১ (৭০৳), প্যাকেজ ০২ (৭০৳), প্যাকেজ ০৩ (৮৩৳), প্যাকেজ ০৭ (৯১৳), প্যাকেজ ০৪ (৭৫৳), প্যাকেজ ০৫ (৮০৳), প্যাকেজ ০৬ (৮৫৳)। (১০০+ অর্ডারে স্পেশাল রেট)',
                85.0, 70.0, 1000, 'প্যাকেজ সমূহ',
                pkg_variations[0]["url"],
                json.dumps(pkg_variations),
                'package, combo, full set'
            )
        ]
        cursor.executemany("""
            INSERT INTO products (name, code, description, price, discount_price, stock, category, image_url, gallery_images, tags, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, real_products)
    else:
        # Update existing PKG-COMBO with exact structured variation prices
        cursor.execute("UPDATE products SET gallery_images = ?, description = ? WHERE code = 'PKG-COMBO'", (
            json.dumps(pkg_variations),
            'জাপানি UV প্রিন্ট কার্ড + ডিজিটাল প্রিন্ট ফিতা + কভার। প্যাকেজ ০১ (৭০৳), প্যাকেজ ০২ (৭০৳), প্যাকেজ ০৩ (৮৩৳), প্যাকেজ ০৭ (৯১৳), প্যাকেজ ০৪ (৭৫৳), প্যাকেজ ০৫ (৮০৳), প্যাকেজ ০৬ (৮৫৳)। (১০০+ অর্ডারে স্পেশাল রেট)'
        ))
        if id_card_imgs:
            cursor.execute("UPDATE products SET gallery_images = ? WHERE code = 'IDC-01'", (json.dumps(id_card_imgs),))
        if fita_imgs:
            cursor.execute("UPDATE products SET gallery_images = ? WHERE code = 'FITA-02'", (json.dumps(fita_imgs),))
        if cover_imgs:
            cursor.execute("UPDATE products SET gallery_images = ? WHERE code = 'COV-03'", (json.dumps(cover_imgs),))

    # Clean up old demo products if present
    cursor.execute("DELETE FROM products WHERE code IN ('PJ-101', 'TP-202', 'CB-303')")
    
    conn.commit()
    conn.close()

def get_setting(key: str, default: str = "") -> str:
    # 1. First check environment variables (Render Environment)
    env_val = os.getenv(key.upper()) or os.getenv(key)
    if env_val is not None and str(env_val).strip() != "":
        return str(env_val).strip()

    # 2. Then check database settings
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row["value"] is not None and str(row["value"]).strip() != "":
        return str(row["value"]).strip()
    return default

def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings(masked: bool = False) -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    
    result = {row["key"]: row["value"] for row in rows}
    
    # Overlay environment variables if present
    env_keys = [
        "META_APP_ID", "META_EMBEDDED_SIGNUP_CONFIG_ID", "FB_PAGE_ACCESS_TOKEN", 
        "FB_VERIFY_TOKEN", "FB_PAGE_ID", "FB_APP_SECRET", "GEMINI_API_KEY", 
        "META_SYSTEM_USER_ACCESS_TOKEN", "WHATSAPP_WABA_ID", "WHATSAPP_PHONE_NUMBER_ID", 
        "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_DISPLAY_PHONE_NUMBER"
    ]
    for ek in env_keys:
        val = os.getenv(ek)
        if val is not None and str(val).strip() != "":
            result[ek.lower()] = str(val).strip()
            
    # Calculate connection statuses
    has_wa_token = bool(
        (result.get("meta_system_user_access_token") and len(str(result.get("meta_system_user_access_token")).strip()) > 10)
        or (result.get("whatsapp_access_token") and len(str(result.get("whatsapp_access_token")).strip()) > 10)
    )
    has_fb_token = bool(result.get("fb_page_access_token") and len(str(result.get("fb_page_access_token")).strip()) > 10)
    
    result["whatsapp_token_configured"] = has_wa_token
    result["fb_token_configured"] = has_fb_token
    
    if not result.get("whatsapp_connection_status") or result.get("whatsapp_connection_status") == "not_connected":
        result["whatsapp_connection_status"] = "connected" if has_wa_token else "not_connected"
        
    if not result.get("whatsapp_connection_mode"):
        result["whatsapp_connection_mode"] = "business_app_coexistence"

    if masked:
        if has_fb_token:
            raw = str(result["fb_page_access_token"]).strip()
            result["fb_page_access_token"] = f"{raw[:6]}...{raw[-4:]}" if len(raw) > 12 else "********"
        if result.get("meta_system_user_access_token") and len(str(result.get("meta_system_user_access_token")).strip()) > 10:
            raw = str(result["meta_system_user_access_token"]).strip()
            result["meta_system_user_access_token"] = f"{raw[:6]}...{raw[-4:]}" if len(raw) > 12 else "********"
        if result.get("whatsapp_access_token") and len(str(result.get("whatsapp_access_token")).strip()) > 10:
            raw = str(result["whatsapp_access_token"]).strip()
            result["whatsapp_access_token"] = f"{raw[:6]}...{raw[-4:]}" if len(raw) > 12 else "********"
        if result.get("gemini_api_key"):
            raw = str(result["gemini_api_key"]).strip()
            result["gemini_api_key"] = f"{raw[:6]}...{raw[-4:]}" if len(raw) > 12 else "********"

    return result

# ============================================================
# AI TRAINING & KNOWLEDGE BASE HELPERS
# ============================================================

def get_active_training_rules() -> list:
    """Returns all active AI training rules, Q&A, and policy guidelines."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ai_training_rules WHERE is_active = 1 ORDER BY category ASC, id ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_all_training_rules() -> list:
    """Returns all training rules for dashboard management."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ai_training_rules ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def create_training_rule(title: str, response_or_rule: str, rule_type: str = "qa", question_or_trigger: str = "", category: str = "General", is_active: int = 1) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ai_training_rules (title, rule_type, question_or_trigger, response_or_rule, category, is_active)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (title, rule_type, question_or_trigger, response_or_rule, category, is_active))
    conn.commit()
    rule_id = cursor.lastrowid
    conn.close()
    return rule_id

def update_training_rule(rule_id: int, title: str, response_or_rule: str, rule_type: str = "qa", question_or_trigger: str = "", category: str = "General", is_active: int = 1) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE ai_training_rules
        SET title = ?, rule_type = ?, question_or_trigger = ?, response_or_rule = ?, category = ?, is_active = ?
        WHERE id = ?
    """, (title, rule_type, question_or_trigger, response_or_rule, category, is_active, rule_id))
    conn.commit()
    conn.close()
    return True

def delete_training_rule(rule_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ai_training_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    return True

def toggle_training_rule(rule_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE ai_training_rules SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    return True

# ============================================================
# SAVED MEDIA LIBRARY HELPERS (VOICE NOTES & VIDEOS)
# ============================================================

def get_saved_media(media_type: str = None) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    if media_type:
        cursor.execute("SELECT * FROM saved_media WHERE media_type = ? ORDER BY id DESC", (media_type,))
    else:
        cursor.execute("SELECT * FROM saved_media ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def create_saved_media(title: str, media_type: str, file_url: str, description: str = "", duration_seconds: int = 0) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO saved_media (title, media_type, file_url, description, duration_seconds)
        VALUES (?, ?, ?, ?, ?)
    """, (title, media_type, file_url, description, duration_seconds))
    conn.commit()
    media_id = cursor.lastrowid
    conn.close()
    return media_id

def delete_saved_media(media_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_media WHERE id = ?", (media_id,))
    conn.commit()
    conn.close()
    return True

# ============================================================
# PER-CUSTOMER AI PAUSE / HUMAN TAKEOVER HELPERS
# ============================================================

def toggle_conversation_ai(conversation_id: int, status: int = None) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    if status is not None:
        cursor.execute("UPDATE conversations SET human_takeover = ? WHERE id = ?", (status, conversation_id))
    else:
        cursor.execute("UPDATE conversations SET human_takeover = CASE WHEN human_takeover = 1 THEN 0 ELSE 1 END WHERE id = ?", (conversation_id,))
    conn.commit()
    conn.close()
    return True

def get_muted_numbers() -> list:
    raw = get_setting("blacklisted_ai_numbers", "")
    items = [x.strip() for x in raw.replace("\n", ",").split(",") if x.strip()] if raw else []
    
    # Also fetch any active conversations where human_takeover == 1
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT sender_id FROM conversations WHERE human_takeover = 1")
        for row in cursor.fetchall():
            s_id = row["sender_id"]
            if s_id and s_id not in items:
                items.append(s_id)
        conn.close()
    except Exception:
        pass

    seen = set()
    res = []
    for it in items:
        clean = "".join([c for c in it if c.isdigit()]) or it
        if clean not in seen:
            seen.add(clean)
            res.append(it)
    return res

def add_muted_number(phone: str) -> list:
    phone = str(phone).strip()
    if not phone:
        return get_muted_numbers()
    current = get_muted_numbers()
    if phone not in current:
        current.append(phone)
        set_setting("blacklisted_ai_numbers", ", ".join(current))
    
    clean_target = "".join([c for c in phone if c.isdigit()])
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if clean_target:
            cursor.execute("UPDATE conversations SET human_takeover = 1 WHERE sender_id LIKE ?", (f"%{clean_target}%",))
        else:
            cursor.execute("UPDATE conversations SET human_takeover = 1 WHERE sender_id = ?", (phone,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return current

def remove_muted_number(phone: str) -> list:
    phone = str(phone).strip()
    current = get_muted_numbers()
    clean_target = "".join([c for c in phone if c.isdigit()])
    
    def is_match(x):
        if x == phone:
            return True
        c_x = "".join([c for c in str(x) if c.isdigit()])
        if clean_target and c_x:
            return clean_target in c_x or c_x in clean_target
        return False

    updated = [x for x in current if not is_match(x)]
    set_setting("blacklisted_ai_numbers", ", ".join(updated))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if clean_target:
            cursor.execute("UPDATE conversations SET human_takeover = 0 WHERE sender_id LIKE ?", (f"%{clean_target}%",))
        else:
            cursor.execute("UPDATE conversations SET human_takeover = 0 WHERE sender_id = ?", (phone,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return updated

def get_muted_contacts_detailed() -> list:
    muted_list = get_muted_numbers()
    if not muted_list:
        return []
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    detailed = []
    for raw_phone in muted_list:
        clean_num = "".join([c for c in raw_phone if c.isdigit()])
        customer_name = "কাস্টমার"
        if clean_num:
            cursor.execute("SELECT customer_name FROM conversations WHERE sender_id LIKE ? AND customer_name IS NOT NULL LIMIT 1", (f"%{clean_num}%",))
            crow = cursor.fetchone()
            if crow and crow["customer_name"]:
                customer_name = crow["customer_name"]
            else:
                cursor.execute("SELECT customer_name FROM orders WHERE customer_phone LIKE ? AND customer_name IS NOT NULL LIMIT 1", (f"%{clean_num}%",))
                orow = cursor.fetchone()
                if orow and orow["customer_name"]:
                    customer_name = orow["customer_name"]
        
        detailed.append({
            "phone": raw_phone,
            "name": customer_name,
            "is_muted": True
        })
    conn.close()
    return detailed

def is_conversation_ai_active(sender_id: str = None, conversation_id: int = None) -> bool:
    """Returns True if AI is allowed to auto-reply to this customer."""
    # 1. Check Master Switch
    if get_setting("ai_enabled", "true").lower() == "false":
        return False

    # 2. Check Blacklisted / Muted Phone Numbers
    blacklisted = get_setting("blacklisted_ai_numbers", "")
    if blacklisted and sender_id:
        clean_sender = "".join([c for c in str(sender_id) if c.isdigit()])
        for bl in blacklisted.replace(",", "\n").split("\n"):
            bl_clean = "".join([c for c in bl.strip() if c.isdigit()])
            if bl_clean and (bl_clean in clean_sender or clean_sender in bl_clean):
                return False

    conn = get_db_connection()
    cursor = conn.cursor()
    if conversation_id:
        cursor.execute("SELECT human_takeover FROM conversations WHERE id = ?", (conversation_id,))
    elif sender_id:
        cursor.execute("SELECT human_takeover FROM conversations WHERE sender_id = ? ORDER BY id DESC LIMIT 1", (sender_id,))
    else:
        conn.close()
        return True

    row = cursor.fetchone()
    conn.close()
    if row and row["human_takeover"] == 1:
        return False
    return True
