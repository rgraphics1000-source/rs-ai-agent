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
        "fb_page_access_token": settings.FB_PAGE_ACCESS_TOKEN,
        "fb_verify_token": settings.FB_VERIFY_TOKEN,
        "voice_enabled": "true",
        "voice_type": "bn-BD-NabanitaNeural" # Bangla female natural voice
    }

    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

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

    # Clean up old demo products if present
    cursor.execute("DELETE FROM products WHERE code IN ('PJ-101', 'TP-202', 'CB-303')")
    
    conn.commit()
    conn.close()

def get_setting(key: str, default: str = "") -> str:
    # 1. First check environment variables (Render Environment)
    env_val = os.getenv(key.upper()) or os.getenv(key)
    if env_val:
        return env_val

    # 2. Then check database settings
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row["value"]:
        return row["value"]
    return default

def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings() -> dict:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    
    result = {row["key"]: row["value"] for row in rows}
    
    # Overlay environment variables if present
    env_keys = ["FB_PAGE_ACCESS_TOKEN", "GEMINI_API_KEY", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"]
    for ek in env_keys:
        val = os.getenv(ek)
        if val:
            result[ek.lower()] = val
            
    return result
