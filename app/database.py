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

    # 7. Shop & Automation Settings Table
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

    # Seed FAQs if none exist
    cursor.execute("DELETE FROM faqs")
    sample_faqs = [
        ("ন্যূনতম কত পিস অর্ডার নেওয়া হয়?", "আমাদের ন্যূনতম অর্ডার পরিমাণ (MOQ) ২০ পিস। ২০ পিসের কম অর্ডার নেওয়া হচ্ছে না।", "Order MOQ"),
        ("আইডি কার্ডের কোয়ালিটি কেমন?", "আমরা জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট করি, যা ১০০% ওয়াটারপ্রুফ, প্রিমিয়াম ফিনিশিং এবং দীর্ঘস্থায়ী।", "Quality"),
        ("ডেলিভারি চার্জ কত?", "ঢাকার ভেতরে ডেলিভারি চার্জ ৭০ টাকা এবং ঢাকার বাইরে ১৩০ টাকা।", "Delivery"),
        ("ডেলিভারি হতে কত দিন সময় লাগে?", "ডিজাইন ফাইনাল হওয়ার পর ২-৩ কার্যদিবসের মধ্যে সারা বাংলাদেশে কুরিয়ারে ডেলিভারি সম্পন্ন হয়।", "Delivery"),
        ("ক্যাশ অন ডেলিভারি দেওয়া যাবে?", "জি অবশ্যই! সারা বাংলাদেশে ক্যাশ অন ডেলিভারি (Cash on Delivery) সুবিধা রয়েছে।", "Payment")
    ]
    cursor.executemany("INSERT INTO faqs (question, answer, category) VALUES (?, ?, ?)", sample_faqs)

    # Seed Real Products if none exist
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] == 0:
        id_card_imgs = [f'/static/uploads/id_card/{f.name}' for f in (settings.UPLOADS_DIR / 'id_card').glob('*.jpg')] if (settings.UPLOADS_DIR / 'id_card').exists() else []
        fita_imgs = [f'/static/uploads/fita/{f.name}' for f in (settings.UPLOADS_DIR / 'fita').glob('*.jpg')] if (settings.UPLOADS_DIR / 'fita').exists() else []
        cover_imgs = [f'/static/uploads/cover/{f.name}' for f in (settings.UPLOADS_DIR / 'cover').glob('*.jpg')] if (settings.UPLOADS_DIR / 'cover').exists() else []
        pkg_imgs = [f'/static/uploads/pakage/{f.name}' for f in (settings.UPLOADS_DIR / 'pakage').glob('*.jpg')] if (settings.UPLOADS_DIR / 'pakage').exists() else []

        real_products = [
            (
                'আইডি কার্ড (জাপানি মেশিনের UV PRINT)',
                'IDC-01',
                'জাপানি মেশিনের অরজিনাল হাই-কোয়ালিটি UV কালার প্রিন্ট, ১০০% ওয়াটারপ্রুফ এবং প্রিমিয়াম ফ্লেক্সিবল PVC ফিনিশিং।',
                35.0, 30.0, 1000, 'আইডি কার্ড',
                id_card_imgs[0] if id_card_imgs else '',
                json.dumps(id_card_imgs),
                'id card, uv print, pvc card'
            ),
            (
                'ডিজিটাল সাবলিমেশন ফিতা (Lanyards / Ribbons)',
                'FITA-02',
                'ডিজিটাল মাল্টিকালর সাবলিমেশন প্রিন্ট, প্রিমিয়াম সাটিন ফেব্রিক ও হেভি ডিউটি হুক। স্কুল, কলেজ ও মাদ্রাসার কাস্টমাইজড নাম ও লোগো সহ প্রস্তুত করা হয়।',
                25.0, 20.0, 1000, 'ফিতা ও লেইনিয়ার্ড',
                fita_imgs[0] if fita_imgs else '',
                json.dumps(fita_imgs),
                'fita, lanyard, ribbon'
            ),
            (
                'আইডি কার্ড হোল্ডার ও কভার (Card Holders)',
                'COV-03',
                'স্বচ্ছ প্লাস্টিক কভার, কালারফুল বর্ডার ও প্রিমিয়াম হার্ড প্লাস্টিক ডাবল সাইডেড হোল্ডার।',
                15.0, 12.0, 1000, 'কভার ও হোল্ডার',
                cover_imgs[0] if cover_imgs else '',
                json.dumps(cover_imgs),
                'holder, cover, card holder'
            ),
            (
                'আইডি কার্ড সম্পূর্ণ কম্বো প্যাকেজ (কার্ড + ফিতা + কভার)',
                'PKG-COMBO',
                'জাপানি মেশিনের UV প্রিন্ট কার্ড + ডিজিটাল প্রিন্ট ফিতা (১.৫/২ সেমি) + কভার। প্যাকেজ ০১ (৭০৳), প্যাকেজ ০২ (৭০৳), প্যাকেজ ০৩ (৮৩৳), প্যাকেজ ০৭ (৯১৳) ইত্যাদি। (১০০+ অর্ডারে স্পেশাল রেট)',
                85.0, 70.0, 1000, 'প্যাকেজ সমূহ',
                pkg_imgs[0] if pkg_imgs else '',
                json.dumps(pkg_imgs),
                'package, combo, full set'
            )
        ]
        cursor.executemany("""
            INSERT INTO products (name, code, description, price, discount_price, stock, category, image_url, gallery_images, tags, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, real_products)

    # Clean up old demo products if present
    cursor.execute("DELETE FROM products WHERE code IN ('PJ-101', 'TP-202', 'CB-303')")
    
    conn.commit()
    conn.close()

def get_setting(key: str, default: str = "") -> str:
    # 1. First check environment variables (Render Environment)
    env_val = os.getenv(key.upper()) or os.getenv(key)
    if env_val is not None and str(env_val).strip() != "":
        val = str(env_val).strip()
        if key.lower() == "whatsapp_phone_number_id" and val == "1265595526643418":
            pass # Ignore unrelated ID
        else:
            return val

    # 2. Then check database settings
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row["value"] is not None and str(row["value"]).strip() != "":
        val = str(row["value"]).strip()
        if key.lower() == "whatsapp_phone_number_id" and val == "1265595526643418":
            return default
        return val
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
            if ek == "WHATSAPP_PHONE_NUMBER_ID" and str(val).strip() == "1265595526643418":
                continue
            result[ek.lower()] = str(val).strip()

    if result.get("whatsapp_phone_number_id") == "1265595526643418":
        result["whatsapp_phone_number_id"] = ""
            
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
