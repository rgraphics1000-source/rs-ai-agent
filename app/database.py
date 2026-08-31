import os
import re
import sqlite3
import json
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
from app.config import settings

DB_PATH = settings.BASE_DIR / "rs_ai.db"

def normalize_bd_mobile(phone: str) -> str:
    """
    Normalizes a Bangladeshi phone number to canonical 11-digit format (01XXXXXXXXX).
    Handles +8801..., 8801..., 01..., 1... seamlessly.
    """
    if not phone:
        return ""
    digits = re.sub(r"[^\d]", "", str(phone).strip())
    if digits.startswith("880") and len(digits) == 13:
        digits = digits[2:]
    elif digits.startswith("88") and len(digits) == 13:
        digits = digits[2:]
    elif len(digits) == 10 and digits.startswith("1"):
        digits = "0" + digits
    return digits

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
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
        workspace_id INTEGER DEFAULT 1,
        channel TEXT NOT NULL, -- 'facebook', 'whatsapp', 'web_playground'
        sender_id TEXT NOT NULL,
        customer_name TEXT,
        last_message TEXT,
        human_takeover INTEGER DEFAULT 0,
        admin_takeover INTEGER DEFAULT 0,
        ai_enabled INTEGER DEFAULT 1,
        takeover_at TIMESTAMP,
        takeover_by TEXT,
        takeover_reason TEXT,
        conversation_version INTEGER DEFAULT 1,
        page_id TEXT DEFAULT '',
        page_connection_id INTEGER,
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

    # 5. Comment Automation Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS comment_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER DEFAULT 1,
        post_id TEXT,
        comment_id TEXT UNIQUE NOT NULL,
        user_id TEXT,
        user_name TEXT,
        comment_text TEXT,
        public_reply TEXT,
        private_reply TEXT,
        page_id TEXT DEFAULT '',
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

    # 10. Workspaces Table (First-Class Multi-Tenant Concept)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS workspaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT UNIQUE,
        status TEXT DEFAULT 'active', -- 'active', 'inactive'
        shop_name TEXT,
        shop_phone TEXT,
        shop_address TEXT DEFAULT 'ঢাকা, বাংলাদেশ',
        delivery_inside_dhaka REAL DEFAULT 70.0,
        delivery_outside_dhaka REAL DEFAULT 130.0,
        ai_system_prompt TEXT,
        ai_enabled INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 11. Connected Facebook Pages Table (Multi-Page Architecture)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS connected_pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER DEFAULT 1,
        page_id TEXT UNIQUE NOT NULL,
        page_name TEXT NOT NULL,
        page_access_token TEXT NOT NULL,
        page_status TEXT DEFAULT 'connected',
        messenger_enabled INTEGER DEFAULT 1,
        comments_enabled INTEGER DEFAULT 1,
        ai_enabled INTEGER DEFAULT 1,
        ai_system_prompt TEXT,
        shop_name TEXT,
        shop_phone TEXT,
        shop_address TEXT,
        delivery_inside_dhaka REAL DEFAULT 70.0,
        delivery_outside_dhaka REAL DEFAULT 130.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL
    );
    """)

    # 12. WhatsApp Accounts Table (Multi-WhatsApp Account Architecture)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS whatsapp_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER DEFAULT 1,
        connected_page_id INTEGER,
        waba_id TEXT,
        phone_number_id TEXT UNIQUE NOT NULL,
        display_phone_number TEXT,
        access_token TEXT,
        connection_mode TEXT DEFAULT 'business_app_coexistence',
        connection_status TEXT DEFAULT 'connected',
        coexistence_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL,
        FOREIGN KEY (connected_page_id) REFERENCES connected_pages(id) ON DELETE SET NULL
    );
    """)

    # 13. Facebook Media Deliveries Table (Media Idempotency & Delivery State Tracking)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS facebook_media_deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL DEFAULT 1,
        page_id TEXT NOT NULL,
        recipient_id TEXT NOT NULL,
        conversation_id INTEGER,
        batch_id TEXT,
        media_type TEXT NOT NULL DEFAULT 'image',
        media_url TEXT NOT NULL,
        media_filename TEXT,
        media_fingerprint TEXT NOT NULL,
        delivery_key TEXT UNIQUE NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        meta_message_id TEXT,
        attachment_id TEXT,
        attempt_count INTEGER DEFAULT 0,
        last_error TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sent_at TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fb_media_delivery_key ON facebook_media_deliveries(delivery_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fb_media_recipient_status ON facebook_media_deliveries(recipient_id, status)")

    # 14. Processed Webhook Events Table (Persistent Webhook Deduplication)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS processed_webhook_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT NOT NULL,
        event_id TEXT UNIQUE NOT NULL,
        workspace_id INTEGER DEFAULT 1,
        page_id_or_phone_id TEXT,
        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhook_events_id ON processed_webhook_events(event_id)")

    # 15. Google Workspace Connections (OAuth & Drive/Form/Sheet Binding per Workspace)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS google_connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER UNIQUE NOT NULL,
        google_account_email TEXT,
        access_token_encrypted TEXT,
        refresh_token_encrypted TEXT,
        token_expiry TIMESTAMP,
        drive_root_folder_id TEXT,
        master_form_id TEXT,
        master_sheet_id TEXT,
        master_form_name TEXT,
        master_form_url TEXT,
        master_edit_url TEXT,
        master_has_file_upload INTEGER DEFAULT 0,
        master_sheet_url TEXT,
        master_verified_at TIMESTAMP,
        status TEXT DEFAULT 'connected',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_google_conn_ws ON google_connections(workspace_id)")

    # 16. Google Form Templates (Master Form Templates per Workspace)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS google_form_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        form_type TEXT DEFAULT 'id_card',
        master_form_id TEXT NOT NULL,
        description_template TEXT,
        form_url TEXT,
        edit_url TEXT,
        spreadsheet_id TEXT,
        spreadsheet_url TEXT,
        has_file_upload INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gform_templates_ws ON google_form_templates(workspace_id)")

    # 17. Institutions (Profile & Folder Scoping)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS institutions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        code TEXT,
        contact_person TEXT,
        phone TEXT,
        address TEXT,
        drive_folder_id TEXT,
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_institutions_ws ON institutions(workspace_id)")

    # 18. Generated Forms (Cloned Institution Google Forms)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS generated_forms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        template_id INTEGER,
        institution_id INTEGER,
        institution_name TEXT NOT NULL,
        form_id TEXT UNIQUE NOT NULL,
        form_url TEXT NOT NULL,
        responder_uri TEXT,
        edit_url TEXT,
        drive_folder_id TEXT,
        response_destination_id TEXT,
        response_sheet_url TEXT,
        status TEXT DEFAULT 'active',
        submission_count INTEGER DEFAULT 0,
        last_synced_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
        FOREIGN KEY (template_id) REFERENCES google_form_templates(id) ON DELETE SET NULL,
        FOREIGN KEY (institution_id) REFERENCES institutions(id) ON DELETE SET NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gforms_ws ON generated_forms(workspace_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gforms_form_id ON generated_forms(form_id)")

    # 19. Google Form Fields (Dynamic Field Manager per Template / Workspace)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS google_form_fields (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        template_id INTEGER,
        field_key TEXT NOT NULL,
        field_label TEXT NOT NULL,
        field_type TEXT NOT NULL,
        required INTEGER DEFAULT 1,
        sort_order INTEGER DEFAULT 0,
        options_json TEXT DEFAULT '[]',
        active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
        FOREIGN KEY (template_id) REFERENCES google_form_templates(id) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gform_fields_ws ON google_form_fields(workspace_id)")

    # 20. Google Form Submissions (Idempotent Storage for Student Responses)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS google_form_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        generated_form_id INTEGER NOT NULL,
        form_id TEXT NOT NULL,
        response_id TEXT NOT NULL,
        customer_id INTEGER,
        student_name TEXT,
        student_roll TEXT,
        student_class TEXT,
        student_phone TEXT,
        submission_timestamp TIMESTAMP,
        raw_response_json TEXT NOT NULL,
        processed INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
        FOREIGN KEY (generated_form_id) REFERENCES generated_forms(id) ON DELETE CASCADE,
        UNIQUE(form_id, response_id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gform_subs_ws_form ON google_form_submissions(workspace_id, form_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gform_subs_resp_id ON google_form_submissions(form_id, response_id)")

    # 21. Google Uploaded Files (Photos / Documents in Google Drive)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS google_uploaded_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        generated_form_id INTEGER NOT NULL,
        response_id TEXT NOT NULL,
        field_key TEXT,
        file_id TEXT NOT NULL,
        file_name TEXT,
        drive_url TEXT,
        mime_type TEXT,
        thumbnail_url TEXT,
        processed INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
        FOREIGN KEY (generated_form_id) REFERENCES generated_forms(id) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_gupload_files_ws_form ON google_uploaded_files(workspace_id, generated_form_id)")

    # Multi-tenant scoping columns migration for all business tables
    scoped_tables = [
        "products", "orders", "conversations", "comment_logs", 
        "faqs", "ai_training_rules", "saved_media", "connected_pages", "whatsapp_accounts"
    ]
    for tbl in scoped_tables:
        try:
            cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN workspace_id INTEGER DEFAULT 1")
        except Exception:
            pass

    # Auto-migration columns for conversations & comment_logs
    try:
        cursor.execute("ALTER TABLE conversations ADD COLUMN page_id TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE conversations ADD COLUMN page_connection_id INTEGER")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE comment_logs ADD COLUMN page_id TEXT DEFAULT ''")
    except Exception:
        pass

    # Auto-migration columns for conversations (Admin Takeover, AI Control, & Versioning)
    conv_takeover_cols = [
        ("admin_takeover", "INTEGER DEFAULT 0"),
        ("ai_enabled", "INTEGER DEFAULT 1"),
        ("takeover_at", "TIMESTAMP"),
        ("takeover_by", "TEXT"),
        ("takeover_reason", "TEXT"),
        ("conversation_version", "INTEGER DEFAULT 1")
    ]
    for col_name, col_type in conv_takeover_cols:
        try:
            cursor.execute(f"ALTER TABLE conversations ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass

    # Auto-migration columns for google_connections (Master Form Metadata)
    google_conn_cols = [
        ("master_form_name", "TEXT"),
        ("master_form_url", "TEXT"),
        ("master_edit_url", "TEXT"),
        ("master_has_file_upload", "INTEGER DEFAULT 0"),
        ("master_sheet_url", "TEXT"),
        ("master_verified_at", "TIMESTAMP")
    ]
    for col_name, col_type in google_conn_cols:
        try:
            cursor.execute(f"ALTER TABLE google_connections ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass

    # Auto-migration columns for google_form_templates
    gtemplate_cols = [
        ("form_url", "TEXT"),
        ("edit_url", "TEXT"),
        ("spreadsheet_id", "TEXT"),
        ("spreadsheet_url", "TEXT"),
        ("has_file_upload", "INTEGER DEFAULT 0")
    ]
    for col_name, col_type in gtemplate_cols:
        try:
            cursor.execute(f"ALTER TABLE google_form_templates ADD COLUMN {col_name} {col_type}")
        except Exception:
            pass

    # Auto-migration columns for institutions (Mobile Identification)
    inst_cols = [
        ("institution_mobile", "TEXT"),
        ("normalized_mobile", "TEXT")
    ]
    for col_name, col_type in inst_cols:
        try:
            cursor.execute(f"ALTER TABLE institutions ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception:
            pass
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_institutions_mobile ON institutions(workspace_id, normalized_mobile)")
        conn.commit()
    except Exception:
        pass

    # Auto-migration columns for generated_forms (Mobile Identification)
    gform_cols = [
        ("institution_mobile", "TEXT"),
        ("selected_fields", "TEXT")
    ]
    for col_name, col_type in gform_cols:
        try:
            cursor.execute(f"ALTER TABLE generated_forms ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception:
            pass
    # Auto-migration columns for messages
    msg_cols = [
        ("sender_role", "TEXT DEFAULT 'CUSTOMER'"),
        ("direction", "TEXT DEFAULT 'INBOUND'"),
        ("source", "TEXT DEFAULT 'WHATSAPP'"),
        ("processing_status", "TEXT DEFAULT 'RECEIVED'"),
        ("external_message_id", "TEXT"),
        ("turn_version", "INTEGER DEFAULT 1")
    ]
    for col_name, col_type in msg_cols:
        try:
            cursor.execute(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception:
            pass

    # Auto-migration columns for conversations
    conv_cols = [
        ("customer_turn_version", "INTEGER DEFAULT 1"),
        ("last_responded_turn_version", "INTEGER DEFAULT 0"),
        ("is_generating", "INTEGER DEFAULT 0"),
        ("generation_lock_at", "TIMESTAMP")
    ]
    for col_name, col_type in conv_cols:
        try:
            cursor.execute(f"ALTER TABLE conversations ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception:
            pass

    # Auto-migration columns for processed_webhook_events
    pwe_cols = [
        ("direction", "TEXT DEFAULT 'INBOUND'"),
        ("sender_role", "TEXT DEFAULT 'CUSTOMER'")
    ]
    for col_name, col_type in pwe_cols:
        try:
            cursor.execute(f"ALTER TABLE processed_webhook_events ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception:
            pass

    # Migrate conversations table if legacy single-column UNIQUE(sender_id) exists
    try:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='conversations'")
        tbl_sql = cursor.fetchone()
        if tbl_sql and "sender_id TEXT NOT NULL UNIQUE" in tbl_sql[0]:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations_ws_tmp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER DEFAULT 1,
                    channel TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    customer_name TEXT,
                    last_message TEXT,
                    human_takeover INTEGER DEFAULT 0,
                    page_id TEXT DEFAULT '',
                    page_connection_id INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                INSERT INTO conversations_ws_tmp (id, workspace_id, channel, sender_id, customer_name, last_message, human_takeover, page_id, page_connection_id, updated_at)
                SELECT id, COALESCE(workspace_id, 1), channel, sender_id, customer_name, last_message, COALESCE(human_takeover, 0), COALESCE(page_id, ''), page_connection_id, updated_at
                FROM conversations
            """)
            cursor.execute("DROP TABLE conversations")
            cursor.execute("ALTER TABLE conversations_ws_tmp RENAME TO conversations")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conversations_ws_sender ON conversations(workspace_id, sender_id)")
    except Exception as e:
        print(f"[Conversations Schema Migration Error]: {e}")

    # Seed default settings if not exists
    default_settings = {
        "shop_name": settings.SHOP_NAME,
        "shop_phone": settings.SHOP_PHONE,
        "shop_address": settings.SHOP_ADDRESS,
        "delivery_inside_dhaka": str(settings.DELIVERY_FEE_INSIDE_DHAKA),
        "delivery_outside_dhaka": str(settings.DELIVERY_FEE_OUTSIDE_DHAKA),
        "comment_auto_reply": "true",
        "comment_reply_template": "ধন্যবাদ {name} স্যার/ম্যাম! বিস্তারিত তথ্য ও ছবি আপনার ইনবক্সে পাঠানো হয়েছে 🥰",
        "private_message_on_comment": "true",
        "ai_system_prompt": (
            "তুমি একটি অত্যন্ত মিষ্টিভাষী, বিনম্র ও দক্ষ বাংলাদেশি ই-কমার্স সেলস এজেন্ট (Sales Assistant)। "
            "তোমার কাজ হলো কাস্টমারের সাথে সুন্দর করে কথা বলা (যেমন: 'আসসালামু আলাইকুম স্যার/ম্যাম', 'কেমন আছেন?', 'জি অবশ্যই')। "
            "কাস্টমার পুরুষ হলে 'স্যার' এবং মহিলা হলে 'ম্যাম' বলবে। কখনোই 'ভাইয়া' বা 'আপু' বলবে না। "
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

    # Migration: update shop name & phone & address if default
    cursor.execute("UPDATE settings SET value = 'RS Graphics (আরএস গ্রাফিক্স)' WHERE key = 'shop_name' AND (value = 'আমার ই-কমার্স শপ' OR value = '')")
    cursor.execute("UPDATE settings SET value = '01816504097' WHERE key = 'shop_phone' AND (value = '01700000000' OR value = '')")
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'shop_address' AND (value = 'ঢাকা, বাংলাদেশ' OR value = '' OR value IS NULL)", (settings.SHOP_ADDRESS,))
    cursor.execute("UPDATE workspaces SET shop_address = ? WHERE id = 1 AND (shop_address = 'ঢাকা, বাংলাদেশ' OR shop_address = '' OR shop_address IS NULL)", (settings.SHOP_ADDRESS,))
    cursor.execute("UPDATE connected_pages SET shop_address = ? WHERE workspace_id = 1 AND (shop_address = 'ঢাকা, বাংলাদেশ' OR shop_address = '' OR shop_address IS NULL)", (settings.SHOP_ADDRESS,))

    # Migration: update any stale 17-digit config_id to official 16-digit ID
    cursor.execute("UPDATE settings SET value = '1003403176086013' WHERE key = 'meta_embedded_signup_config_id' AND value = '10034031760860138'")
    # Migration: clear unrelated phone number ID 1265595526643418 so only verified target ID is stored
    cursor.execute("UPDATE settings SET value = '' WHERE key = 'whatsapp_phone_number_id' AND value = '1265595526643418'")



    # Safe Automatic Migration for Workspace 1 (RS Graphics)
    cursor.execute("SELECT COUNT(*) FROM workspaces")
    ws_count = cursor.fetchone()[0]
    if ws_count == 0:
        cursor.execute("SELECT value FROM settings WHERE key = 'shop_name'")
        s_name_row = cursor.fetchone()
        ws_name = s_name_row["value"] if (s_name_row and s_name_row["value"]) else "RS Graphics (আরএস গ্রাফিক্স)"

        cursor.execute("SELECT value FROM settings WHERE key = 'shop_phone'")
        s_phone_row = cursor.fetchone()
        ws_phone = s_phone_row["value"] if (s_phone_row and s_phone_row["value"]) else "01816504097"

        cursor.execute("SELECT value FROM settings WHERE key = 'ai_system_prompt'")
        s_prompt_row = cursor.fetchone()
        ws_prompt = s_prompt_row["value"] if (s_prompt_row and s_prompt_row["value"]) else ""

        cursor.execute("""
            INSERT OR IGNORE INTO workspaces (
                id, name, slug, status, shop_name, shop_phone, shop_address,
                delivery_inside_dhaka, delivery_outside_dhaka, ai_system_prompt, ai_enabled
            ) VALUES (
                1, ?, 'rs-graphics', 'active',
                ?, ?, 'ঢাকা, বাংলাদেশ',
                70.0, 130.0, ?, 1
            )
        """, (ws_name, ws_name, ws_phone, ws_prompt))
        print(f"[Auto-Migration] Workspace 1 ('{ws_name}') initialized.")

    # Multi-tenant scoping: ensure all existing records belong to Workspace 1 if unassigned
    for tbl in ["products", "orders", "conversations", "comment_logs", "faqs", "ai_training_rules", "saved_media", "connected_pages", "whatsapp_accounts"]:
        try:
            cursor.execute(f"UPDATE {tbl} SET workspace_id = 1 WHERE workspace_id IS NULL OR workspace_id = 0")
        except Exception:
            pass

    # Safe Idempotent Consistency Check for Facebook Page 1 and WhatsApp Accounts
    ensure_facebook_page_consistency(conn=conn)
    ensure_whatsapp_account_consistency(conn=conn)

    # Scope legacy conversations and comment_logs to primary Page 1
    cursor.execute("SELECT page_id FROM connected_pages ORDER BY id ASC LIMIT 1")
    first_page = cursor.fetchone()
    if first_page and first_page["page_id"]:
        cursor.execute("UPDATE conversations SET page_id = ? WHERE page_id IS NULL OR page_id = ''", (first_page["page_id"],))
        cursor.execute("UPDATE comment_logs SET page_id = ? WHERE page_id IS NULL OR page_id = ''", (first_page["page_id"],))

    # Seed initial AI Training Rules if none exist
    master_rules = [
        ("১. প্রাথমিক সার্ভিস ও কোয়ান্টিটি অনুসন্ধান (প্রথম মেসেজেই দাম নয়)", "কাস্টমার প্রথমে মেসেজ দিলে বা আইডি কার্ড করতে চাইলে সরাসরি প্রথম মেসেজেই দাম বলা যাবে না। প্রথমে নম্রভাবে শুভেচ্ছা জানিয়ে জানতে হবে: 'আসসালামু আলাইকুম। অবশ্যই। আপনি কত পিস ID Card করতে চান এবং কার্ডের সঙ্গে ফিতা ও কভারও নিতে চান কি?'", "instruction", "আইডি কার্ড বানাতে চাই", "Sales Protocol", 1),
        ("২. সর্বনিম্ন অর্ডারের পরিমাণ (MOQ ৩০ পিস)", "আমাদের ID Card, ফিতা ও কভারের Minimum Order Quantity হলো ৩০ পিস। কাস্টমার ৩০ পিসের কম চাইলে বলতে হবে: 'আমাদের ID Card, ফিতা ও কভারের Minimum Order Quantity ৩০ পিস। ৩০ পিস বা তার বেশি হলে আমরা অর্ডার নিচ্ছি।'", "instruction", "কত পিস অর্ডার নেওয়া হয়?", "Pricing & MOQ", 1),
        ("৩. স্যাম্পল ছবি ও প্যাকেজ পাঠানোর ৪-ধাপের নির্দিষ্ট সেলস ফ্লো", "১) কাস্টমার প্রথমে স্যাম্পল বা ছবি দেখতে চাইলে শুধুমাত্র আলাদা আলাদা উপাদানগুলো ক্রমানুসারে পাঠাবে: ১৫টি কার্ডের ছবি + টেক্সট -> ৮টি ফিতার ছবি + টেক্সট -> ৮টি কভারের ছবি -> ফেসবুক রিভিউ ট্রাস্ট লিংক (এই ধাপে প্যাকেজের ছবি দেওয়া নিষিদ্ধ)। ২) স্যাম্পল দেখার পর কাস্টমার যদি 'দাম সহ দিন' বা 'কোনটার দাম কত' বা দাম জানতে চায়, তখন সরাসরি প্যাকেজ না ফেলে অনুমতি চাইবে: 'জি স্যার/ম্যাম, আমাদের কার্ড, ফিতা এবং কভার মিলিয়ে কিছু আকর্ষণীয় রেডি প্যাকেজ করা আছে (যার মধ্যে রেগুলার পাইকারি মূল্য দেওয়া আছে)। আমি কি তাহলে আমাদের রেডি প্যাকেজগুলোর ছবি ও বিস্তারিত পাঠাবো স্যার/ম্যাম?' ৩) কাস্টমার সম্মতি দিলে ১ থেকে ৭ সিরিয়ালে ৭টি রেডি প্যাকেজের ছবি পাঠাবে। ৪) কাস্টমার নিজে থেকে আলাদা কার্ড, ফিতা ও কভারের ছবি পাঠালে বা নাম বললে এজেন্ট স্বয়ংক্রিয়ভাবে ফর্মুলা দিয়ে পার-সেট মোট মূল্য হিসাব করে দেবে।", "instruction", "ছবি দেখান", "Sales Protocol", 1),
        ("৪. কোয়ান্টিটি ভিত্তিক প্রাইসিং ও ভয়েস নোট পাঠানোর শর্ত", "প্যাকেজের ছবি পাঠানোর পর: কাস্টমারের অর্ডার যদি ৮০-৯০ পিস বা ১০০+ পিস হয় তখন 'PTT-20260119-WA0105.mp3' ভয়েস বার্তা পাঠাবে। আর অর্ডার যদি ৫০-৮০ পিস হয় তবে কোনো ভয়েস পাঠাবে না, প্যাকেজের গায়ে উল্লেখিত রেগুলার ফিক্সড রেট হবে। আর যদি ৩০-৪৯ পিস হয়, তবে কোনো ভয়েস পাঠাবে না, বরং টেক্সটে বলবে: 'আমাদের প্রতি প্যাকেজে প্যাকেজের সাথে আরো ১০ টাকা করে বৃদ্ধি হবে। যেহেতু আমাদের এই প্যাকেজগুলোর যে রেট দেওয়া আছে এটা ১০০ প্লাস অর্ডারের ক্ষেত্রে প্রযোজ্য। আপনাদের যেহেতু ১০০ এর অনেক কম যার কারণে আপনাদের প্রতি প্যাকেজে ১০ টাকা করে বেশি দিলে আমরা আপনাদের কাজটা করতে পারবো।'", "instruction", "প্যাকেজের ছবি", "Sales Protocol", 1),
        ("৫. বাল্ক ডিসকাউন্ট ও ধাপে ধাপে দামাদামির পলিসি (১০০+ পিস)", "শুরুতে সবসময় প্যাকেজের নির্ধারিত রেগুলার রেট বলতে হবে। শুরুতেই বা প্রথমে নিজে থেকে কোনো ছাড়ের রেট বা ডিসকাউন্ট বলা যাবে না। কাস্টমার যদি দামাদামি করে বা কমাতে বলে, তবে ধাপে ধাপে দাম কমাতে হবে: ১) ১০০+ পিসের ক্ষেত্রে সবচেয়ে প্রিমিয়াম ৭ নম্বর প্যাকেজ (মেটাল কভার, রেগুলার ৯১ টাকা) প্রথমে ৯১ টাকা বলবে, দামাদামি করলে ধাপে ধাপে কমিয়ে সর্বনিম্ন ৮২ টাকা পর্যন্ত রাখা যাবে (সর্বোচ্চ ৯ টাকা ছাড়)। ২) অন্যান্য প্যাকেজে (প্যাকেজ ১-৬) প্রথমে রেগুলার রেট বলবে, দামাদামি করলে ধাপে ধাপে কমিয়ে প্রতি প্যাকেজে সর্বোচ্চ ৫ টাকা করে ছাড় দেওয়া যাবে। ৩) ৫০-৮০ পিসের ক্ষেত্রে একদম ফিক্সড রেগুলার রেট হবে, দামাদামি করলেও কোনো ছাড় দেওয়া যাবে না (ওনারের অনুমতি ছাড়া নয়)।", "price_policy", "ডিসকাউন্ট বা কম রাখা যাবে?", "Price Policy", 1),
        ("৬. একক আইটেমের মূল্য তালিকা ও কভারের দাম", "১) শুধু আইডি কার্ড (১০০ পিস বা বেশি): ৩৫ টাকা/পিস। জাপানি UV কালার প্রিন্ট প্রিমিয়াম PVC কার্ড। ২) ডিজিটাল সাবলিমেশন ফিতা: ২ সেমি মোটা ফিতা = ২৮ টাকা/পিস; ১.৫ সেমি মোটা ফিতা = ২৫ টাকা/পিস; ২.৫ সেমি = ৩০ টাকা/পিস। ৩) কভার তালিকা ও মূল্য (রিনেম/মডেল অনুযায়ী ফিক্সড): T-014V সফট কভার = ১০ টাকা, DX কভার = ১২ টাকা, T-065V সফট কভার = ১৪ টাকা, Xinding Q-993 কভার = ১৬ টাকা, T-738V হার্ড কভার = ২০ টাকা, T-994V হার্ড কভার = ২০ টাকা, REAP হার্ড কভার = ২০ টাকা, মেটাল কভার = ৩০ টাকা।", "price_policy", "শুধু কার্ড বা কভারের দাম কত?", "Pricing", 1),
        ("৭. কাস্টম কম্বো প্যাকেজ তৈরির হিসাব (ছবি ও আলাদা আইটেম নির্বাচন)", "কোনো কাস্টমার যদি আলাদা কার্ড, আলাদা ফিতা এবং আলাদা কভারের ছবি পাঠায় বা সিলেক্ট করে, তখন সেই আইটেমগুলো দেখে তাকে কাস্টম কম্বো প্যাকেজ হিসাব করে দিতে হবে। হিসাব সূত্র: কার্ডের মূল্য (জাপানি UV প্রিন্ট ৩৫৳) + ফিতার মূল্য (২ সেমি ২৮৳ বা ১.৫ সেমি ২৫৳) + কভারের মূল্য (কভারের মডেল অনুযায়ী ১০৳, ১২৳, ১৪৳, ১৬৳, ২০৳ বা ৩০৳) = প্রতি সেট প্যাকেজের মোট মূল্য (১০০+ পিসের ক্ষেত্রে)। যেমন: কার্ড (৩৫৳) + ২ সেমি ফিতা (২৮৳) + DX কভার (১২৳) = ৭৫ টাকা/পিস। কাস্টমারকে প্রতিটি আইটেমের নাম ও আলাদা মূল্য ভেঙে দেখিয়ে (আইটেমাইজড হিসাব) মোট প্যাকেজ মূল্য ও কাঙ্ক্ষিত পরিমাণের মোট খরচ ভদ্র ও সুন্দরভাবে জানাতে হবে।", "price_policy", "আলাদা ফিতা ও কভারের দাম কত?", "Pricing & Custom Combos", 1),
        ("৮. কাস্টম অর্ডার ও পেমেন্ট পলিসি (Full COD প্রযোজ্য নয়)", "আমাদের ID Card, Ribbon, Cover এবং Package-এর অর্ডারগুলো কাস্টমারের প্রতিষ্ঠানের নাম ও লোগো দিয়ে কাস্টমাইজ করে তৈরি হয়। তাই আমাদের কোনো Full Cash on Delivery (COD) নেই। অর্ডার কনফার্ম করতে Advance Payment বাধ্যতামূলক (সাধারণত ১০,০০০-১২,০০০ টাকার অর্ডারে ১,০০০-১,৫০০ টাকা এবং বেশি মূল্যের অর্ডারে প্রয়োজন অনুযায়ী বাড়বে)। বাকি টাকা ডেলিভারির সময় পরিশোধযোগ্য। কাস্টমার পুরো টাকা কুরিয়ারে দিতে চাইলে বলবে: 'আমাদের পণ্যগুলো Custom Order হওয়ায় Full Cash on Delivery প্রযোজ্য নয়। কারণ আপনার প্রতিষ্ঠানের নাম ও তথ্য অনুযায়ী পণ্যগুলো বিশেষভাবে তৈরি করা হয়। তাই অর্ডার Confirm করার সময় একটি Advance Payment নেওয়া হয় এবং বাকি টাকা Delivery-এর সময় পরিশোধ করা যায়।'", "instruction", "ক্যাশ অন ডেলিভারি হবে?", "Payment & Security", 1),
        ("৯. অর্ডার কনফার্মেশন ও হোয়াটসঅ্যাপে তথ্য সংগ্রহ", "কাস্টমার অর্ডার কনফার্ম করতে চাইলে বলবে: 'অবশ্যই। অর্ডার প্রসেস করার জন্য আপনার প্রতিষ্ঠানের প্রয়োজনীয় তথ্যগুলো আমাদের পাঠাতে হবে। আপনি প্রয়োজনীয় তথ্য ও লোগো আমাদের WhatsApp নম্বর 01816504097-এ পাঠিয়ে দিন। Design আমরা আমাদের পক্ষ থেকেই তৈরি করে দেব।' (কখনোই কাস্টমারের কাছে ডিজাইন ফাইল চাওয়া যাবে না)।", "instruction", "অর্ডার কনফার্ম করতে চাই", "Order Processing", 1),
        ("১০. তথ্য দেওয়ার দুই মাধ্যম ও ভিডিও পলিসি", "কাস্টমার তথ্য কীভাবে দেব জানতে চাইলে বলবে: 'আমাদের তথ্য দেওয়ার ২টি সহজ মাধ্যম রয়েছে স্যার/ম্যাম: ১) WhatsApp: আমাদের অফিসিয়াল হোয়াটসঅ্যাপ নম্বর 01816504097-এ প্রতিষ্ঠানের নাম, লোগো এবং প্রয়োজনীয় তথ্যগুলো সরাসরি পাঠিয়ে দিতে পারেন। ২) Google Form: আপনার প্রতিষ্ঠানের জন্য আমরা একটি কাস্টমাইজড গুগল ফর্ম তৈরি করে দিতে পারব, যাতে সহজে ঘরে বসেই তথ্য ও ছবি আপলোড করতে পারবেন।' কাস্টমার গুগল ফর্মে কীভাবে তথ্য ও ছবি আপলোড করতে হয় জানতে চাইলে 'গুগল ফর্মে আইডি কার্ডের তথ্য ও ছবি আপলোড করার নিয়ম' (Video 1) দেবে। আর তথ্য সাবমিট করার পর জানতে চাইলে যে 'তথ্য কীভাবে সংশোধন বা ঠিক করব?', তখন 'তথ্য ও ছবি সাবমিট করার পরে সংশোধনের নিয়ম' (Video 2) দেবে।", "instruction", "তথ্য কিভাবে দিব", "Data Collection", 1),
        ("১১. ডেলিভারি চার্জ ও হিসাব", "ঢাকার ভেতরে: প্রথম ১ কেজি ৮০ টাকা, অতিরিক্ত প্রতি কেজি ২০ টাকা করে এবং প্রতি ১,০০০ টাকায় ১০ টাকা COD/ফিওডি চার্জ যুক্ত হবে। ঢাকার বাইরে: প্রথম ১ কেজি ১৩০ টাকা, অতিরিক্ত প্রতি কেজি ২০ টাকা করে এবং প্রতি ১,০০০ টাকায় ১০ টাকা COD/ফিওডি চার্জ যুক্ত হবে।", "qa", "ডেলিভারি চার্জ কত?", "Delivery & Payment", 1),
        ("১২. প্রোডাকশন সময় ও ডেলিভারি টাইমলাইন", "কাস্টমার কাজ করতে কতদিন লাগবে জানতে চাইলে বলবে: 'আপনার কাছ থেকে প্রয়োজনীয় সব তথ্য দিয়ে Order Complete করার পর আমাদের কাজ সম্পন্ন করতে ন্যূনতম ৫ থেকে ৬ দিন সময় প্রয়োজন হবে। এরপর আমরা আপনার কাজ প্রস্তুত করে Proof দেখাব। আপনি Proof দেখে Final করলে আমরা Printing করব। Printing হওয়ার দিনই Courier করে দেব, ইনশাআল্লাহ। এরপর Courier-এর মাধ্যমে সাধারণত ২৪ থেকে ৪৮ ঘণ্টার মধ্যে আপনার পণ্য হাতে পৌঁছে যাবে, ইনশাআল্লাহ।'", "qa", "কতদিন সময় লাগবে?", "Timeline", 1),
        ("১৩. এজেন্টের পরিচয় ও ওনার সম্বোধনের নিয়ম", "এজেন্টের নাম 'নাদিম'। ওনারের নাম 'মোহাম্মদ রাশেদুল ইসলাম'। এজেন্ট কখনোই নিজে থেকে ওনারের নাম বলবে না, সর্বদা অত্যন্ত শ্রদ্ধার সাথে 'আমাদের ওনার স্যার' বা 'ওনার স্যার' বলবে। কেউ যদি 'রাশেদ ভাই কোথায়?' বা 'রাশেদ কোথায়?' জানতে চায়, তখন বলবে: 'রাশেদ স্যার আমাদের ওনার স্যার। আপনার বিষয়টি ওনার স্যারকে জানিয়ে দিচ্ছি।'", "instruction", "রাশেদ ভাই কোথায়", "Persona & Etiquette", 1),
        ("১৪. ইউভি প্রিন্ট কোয়ালিটি", "আমরা জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট করি, যা ১০০% ওয়াটারপ্রুফ, প্রিমিয়াম ফিনিশিং এবং দীর্ঘস্থায়ী।", "qa", "কোয়ালিটি কেমন?", "Product Quality", 1),
        ("১৫. ক্রয়মূল্য গোপন রাখা", "কাস্টমারকে কখনো আমাদের নিজস্ব উৎপাদন বা ক্রয়মূল্য বলা যাবে না। সর্বদা নির্ধারিত বিক্রয়মূল্য বলতে হবে।", "instruction", "", "Business Policy", 1),
        ("১৬. হিউম্যান টেকওভার ও এআই নিস্তব্ধতা", "বিজনেস ওনার বা এজেন্ট চ্যাটে কথা বলা শুরু করলে এআই সম্পূর্ণ নীরব থাকবে এবং কোনো স্বয়ংক্রিয় উত্তর দেবে না।", "instruction", "", "System Protocol", 1),
        ("১৭. ভদ্রতা, সংক্ষিপ্ততা ও সম্বোধন", "কাস্টমার পুরুষ হলে 'স্যার' এবং মহিলা হলে 'ম্যাম' সম্বোধন করবে। কখনোই 'ভাইয়া' বা 'আপু' বলবে না। সংক্ষিপ্ত ও টু-দ্য-পয়েন্ট উত্তর দেবে।", "instruction", "", "Tone & Etiquette", 1),
        ("১৮. অজানা বিষয়ের উত্তর বানিয়ে না বলা", "যে তথ্য জানা নেই সে বিষয়ে বানিয়ে কোনো উত্তর দেবে না। বলবে: 'জি স্যার/ম্যাম, এই বিষয়টি জেনে আমাদের টিম আপনাকে খুব দ্রুত জানাচ্ছে।'", "instruction", "", "Anti-Hallucination", 1),
        ("১৯. পারসিস্টেন্ট মিডিয়া অপশন (ভয়েস ও ভিডিও)", "সিস্টেমে সংরক্ষিত ভিডিও ও ভয়েস ক্লিপ স্থায়ীভাবে সংরক্ষিত থাকবে এবং ফাংশন বা রিলোডে হারিয়ে যাবে না। কাস্টমার চাইলে সংশ্লিষ্ট ভিডিও বা ভয়েস পাঠাবে।", "instruction", "", "Media", 1),
        ("২০. প্রিমিয়াম ও সর্বনিম্ন বাজেট প্যাকেজের নিয়ম", "কাস্টমার যদি সবচেয়ে প্রিমিয়াম বা সবচেয়ে ভালো মানের প্যাকেজ চায়, তবে ৭ নম্বর প্যাকেজ (৯১ টাকা, মেটাল কভার) এর ছবি ও বিবরণ দিতে হবে। আর কাস্টমারের বাজেট একবারে কম হলে ১ নম্বর প্যাকেজ (৭০ টাকা, সফট কভার) এর ছবি ও বিবরণ দিতে হবে।", "instruction", "সবচেয়ে প্রিমিয়াম প্যাকেজ কোনটা?", "Sales Protocol", 1)
    ]

    for r_title, r_resp, r_type, r_trig, r_cat, r_active in master_rules:
        cursor.execute("SELECT id FROM ai_training_rules WHERE workspace_id = 1 AND title = ?", (r_title,))
        existing_r = cursor.fetchone()
        if not existing_r:
            cursor.execute("""
                INSERT INTO ai_training_rules (workspace_id, title, response_or_rule, rule_type, question_or_trigger, category, is_active)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (r_title, r_resp, r_type, r_trig, r_cat, r_active))
        else:
            cursor.execute("""
                UPDATE ai_training_rules
                SET response_or_rule = ?, rule_type = ?, question_or_trigger = ?, category = ?, is_active = ?
                WHERE id = ?
            """, (r_resp, r_type, r_trig, r_cat, r_active, existing_r["id"]))

    # Products Table: Ensure workspace scoping without deleting user-added products
    cursor.execute("UPDATE products SET workspace_id = 1 WHERE workspace_id IS NULL OR workspace_id = 0")
    
    # Clean up legacy /forms/d/e/ URLs to use canonical /forms/d/{id}/viewform
    try:
        cursor.execute("""
            UPDATE generated_forms 
            SET form_url = 'https://docs.google.com/forms/d/' || form_id || '/viewform',
                responder_uri = 'https://docs.google.com/forms/d/' || form_id || '/viewform'
            WHERE form_id IS NOT NULL AND form_id != '' AND (form_url LIKE '%/forms/d/e/%' OR responder_uri LIKE '%/forms/d/e/%')
        """)
    except Exception:
        pass

    # Ensure standard product catalog is present
    ensure_default_products(conn=conn)

    # Ensure default saved media (videos, voices) are present
    ensure_default_saved_media(conn=conn)

    conn.commit()
    conn.close()

    # Safe automated local snapshot backup
    try:
        backup_dir = settings.BASE_DIR / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        live_db_path = settings.BASE_DIR / "rs_ai.db"
        if live_db_path.exists():
            import shutil
            shutil.copy2(live_db_path, backup_dir / "rs_ai_backup_live_snapshot.db")
    except Exception as e:
        print(f"[DB Auto-Snapshot Warning]: {e}")

def get_setting(key: str, default: str = "") -> str:
    # 1. Check database settings first (Primary Source of Truth)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row["value"] is not None and str(row["value"]).strip() != "":
            return str(row["value"]).strip()
    except Exception:
        pass

    # 2. Fallback to environment variables if database is empty
    env_val = os.getenv(key.upper()) or os.getenv(key)
    if env_val is not None and str(env_val).strip() != "":
        return str(env_val).strip()

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
    
    # Overlay environment variables ONLY if database value is missing or empty
    env_keys = [
        "META_APP_ID", "META_EMBEDDED_SIGNUP_CONFIG_ID", "FB_PAGE_ACCESS_TOKEN", 
        "FB_VERIFY_TOKEN", "FB_PAGE_ID", "FB_APP_SECRET", "GEMINI_API_KEY", 
        "META_SYSTEM_USER_ACCESS_TOKEN", "WHATSAPP_WABA_ID", "WHATSAPP_PHONE_NUMBER_ID", 
        "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_DISPLAY_PHONE_NUMBER"
    ]
    for ek in env_keys:
        val = os.getenv(ek)
        if val is not None and str(val).strip() != "":
            k = ek.lower()
            if not result.get(k) or str(result.get(k)).strip() == "":
                result[k] = str(val).strip()
            
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

def get_active_training_rules(workspace_id: int = 1) -> list:
    """Returns all active AI training rules, Q&A, and policy guidelines scoped to a workspace."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ai_training_rules WHERE workspace_id = ? AND is_active = 1 ORDER BY category ASC, id ASC", (int(workspace_id or 1),))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_all_training_rules(workspace_id: Optional[int] = None) -> list:
    """Returns all training rules for dashboard management, optionally scoped by workspace."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if workspace_id is not None:
        cursor.execute("SELECT * FROM ai_training_rules WHERE workspace_id = ? ORDER BY id DESC", (int(workspace_id),))
    else:
        cursor.execute("SELECT * FROM ai_training_rules ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def create_training_rule(title: str, response_or_rule: str, rule_type: str = "qa", question_or_trigger: str = "", category: str = "General", is_active: int = 1, workspace_id: int = 1) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO ai_training_rules (title, rule_type, question_or_trigger, response_or_rule, category, is_active, workspace_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (title, rule_type, question_or_trigger, response_or_rule, category, is_active, int(workspace_id or 1)))
    conn.commit()
    rule_id = cursor.lastrowid
    conn.close()
    return rule_id

def update_training_rule(rule_id: int, title: str, response_or_rule: str, rule_type: str = "qa", question_or_trigger: str = "", category: str = "General", is_active: int = 1, workspace_id: Optional[int] = None) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    if workspace_id is not None:
        cursor.execute("""
            UPDATE ai_training_rules
            SET title = ?, rule_type = ?, question_or_trigger = ?, response_or_rule = ?, category = ?, is_active = ?, workspace_id = ?
            WHERE id = ?
        """, (title, rule_type, question_or_trigger, response_or_rule, category, is_active, int(workspace_id), rule_id))
    else:
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
# FAQ HELPERS (WORKSPACE-SCOPED)
# ============================================================

def get_faqs(workspace_id: Optional[int] = None) -> list:
    """Returns FAQs scoped to a workspace or all if None."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if workspace_id is not None:
        cursor.execute("SELECT * FROM faqs WHERE workspace_id = ? ORDER BY id DESC", (int(workspace_id),))
    else:
        cursor.execute("SELECT * FROM faqs ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_all_faqs(workspace_id: Optional[int] = None) -> list:
    """Alias for get_faqs."""
    return get_faqs(workspace_id)

def get_all_products(workspace_id: Optional[int] = None) -> list:
    """Returns active products scoped to a workspace or all if None."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if workspace_id is not None:
        cursor.execute("SELECT * FROM products WHERE workspace_id = ? AND is_active = 1 ORDER BY id ASC", (int(workspace_id),))
    else:
        cursor.execute("SELECT * FROM products WHERE is_active = 1 ORDER BY id ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def create_faq(question: str, answer: str, category: str = "General", workspace_id: int = 1) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO faqs (question, answer, category, workspace_id)
        VALUES (?, ?, ?, ?)
    """, (question, answer, category, int(workspace_id or 1)))
    conn.commit()
    faq_id = cursor.lastrowid
    conn.close()
    return faq_id

def delete_faq(faq_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
    conn.commit()
    conn.close()
    return True

# ============================================================
# QUOTED MESSAGE & MEDIA RESOLUTION HELPERS
# ============================================================

def resolve_quoted_message_media(quoted_mid: str, workspace_id: int = 1) -> dict:
    """Looks up a previously sent or received message by external_message_id or database id to retrieve its media_url, content, and file bytes."""
    if not quoted_mid:
        return {}
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ws_id = int(workspace_id or 1)
        
        cursor.execute("""
            SELECT m.id, m.media_url, m.content, m.message_type, m.external_message_id
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE (m.external_message_id = ? OR m.id = ? OR m.external_message_id LIKE ? OR ? LIKE ('%' || m.external_message_id || '%'))
              AND c.workspace_id = ?
            ORDER BY m.id DESC LIMIT 1
        """, (str(quoted_mid), str(quoted_mid), f"%{quoted_mid}%", str(quoted_mid), ws_id))
        row = cursor.fetchone()
        if not row:
            cursor.execute("""
                SELECT id, media_url, content, message_type, external_message_id
                FROM messages
                WHERE (external_message_id = ? OR id = ? OR external_message_id LIKE ? OR ? LIKE ('%' || external_message_id || '%'))
                ORDER BY m.id DESC LIMIT 1
            """ if "m." not in "" else "", ())
            cursor.execute("""
                SELECT id, media_url, content, message_type, external_message_id
                FROM messages
                WHERE (external_message_id = ? OR id = ? OR external_message_id LIKE ? OR ? LIKE ('%' || external_message_id || '%'))
                ORDER BY id DESC LIMIT 1
            """, (str(quoted_mid), str(quoted_mid), f"%{quoted_mid}%", str(quoted_mid)))
            row = cursor.fetchone()
            
        media_url = ""
        content = ""
        row_id = None
        if row:
            row_id = row["id"]
            media_url = row["media_url"] or ""
            content = row["content"] or ""
        else:
            # Check media_deliveries fallback
            try:
                cursor.execute("""
                    SELECT id, media_url, media_filename, delivery_key
                    FROM media_deliveries
                    WHERE meta_message_id = ? OR attachment_id = ?
                    ORDER BY id DESC LIMIT 1
                """, (str(quoted_mid), str(quoted_mid)))
                md_row = cursor.fetchone()
                if md_row:
                    row_id = md_row["id"]
                    media_url = md_row["media_url"] or md_row["delivery_key"] or ""
                    content = md_row["media_filename"] or ""
            except Exception:
                pass
                
        if not media_url and not content:
            return {}
        local_path = None
        img_bytes = None
        img_mime = "image/jpeg"
        
        if media_url:
            clean_rel = str(media_url).lstrip("/").replace("\\", "/")
            candidates = [
                clean_rel,
                str(media_url)[1:] if str(media_url).startswith("/") else str(media_url),
                f"static/{clean_rel}" if not clean_rel.startswith("static/") else clean_rel,
                os.path.join("static", "uploads", os.path.basename(clean_rel)),
                os.path.join("static", "uploads", "package", os.path.basename(clean_rel)),
                os.path.join("static", "uploads", "id_card", os.path.basename(clean_rel)),
                os.path.join("static", "uploads", "fita", os.path.basename(clean_rel)),
                os.path.join("static", "uploads", "cover", os.path.basename(clean_rel)),
            ]
            for cp in candidates:
                if os.path.exists(cp) and os.path.isfile(cp):
                    local_path = cp
                    break
                
            if local_path and os.path.isfile(local_path):
                try:
                    with open(local_path, "rb") as f:
                        img_bytes = f.read()
                    if local_path.lower().endswith(".png"):
                        img_mime = "image/png"
                    elif local_path.lower().endswith(".webp"):
                        img_mime = "image/webp"
                except Exception as e:
                    print(f"[resolve_quoted_message_media read error]: {e}")
                    
        return {
            "id": row_id,
            "media_url": media_url,
            "filename": os.path.basename(media_url) if media_url else "",
            "content": content,
            "local_path": local_path,
            "image_bytes": img_bytes,
            "image_mime": img_mime
        }
    except Exception as e:
        print(f"[resolve_quoted_message_media error]: {e}")
        return {}
        return {}
    finally:
        if conn:
            conn.close()

# ============================================================
# STANDARD PRODUCT CATALOG HELPERS
# ============================================================

def ensure_default_products(conn=None):
    """Initializes standard product catalog items for Workspace 1 idempotently without deleting user items."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        cursor = conn.cursor()
        defaults = [
            (
                "আইডি কার্ড (জাপানি UV কালার প্রিন্ট PVC)",
                "IDC-UV-35",
                "জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট প্রিমিয়াম পিভিসি আইডি কার্ড। ১০০% ওয়াটারপ্রুফ ও দীর্ঘস্থায়ী ফিনিশিং।",
                35.0,
                35.0,
                1000,
                "আইডি কার্ড",
                "/static/uploads/id_card/IMG-20241009-WA0005.jpg",
                "[]",
                "id card, pvc, uv print, আইডি কার্ড",
                1
            ),
            (
                "ডিজিটাল সাবলিমেশন ফিতা (২ সেমি)",
                "FITA-2CM-28",
                "২ সেন্টিমিটার চওড়া প্রিমিয়াম ডিজিটাল সাবলিমেশন কালার প্রিন্ট ফিতা।",
                28.0,
                28.0,
                1000,
                "ফিতা",
                "/static/uploads/fita/2_CM_4.jpg",
                "[]",
                "fita, ribbon, lanyard, 2cm, ফিতা",
                1
            ),
            (
                "ডিজিটাল সাবলিমেশন ফিতা (১.৫ সেমি)",
                "FITA-1.5CM-25",
                "১.৫ সেন্টিমিটার চওড়া প্রিমিয়াম ডিজিটাল সাবলিমেশন কালার প্রিন্ট ফিতা।",
                25.0,
                25.0,
                1000,
                "ফিতা",
                "/static/uploads/fita/1_5_CM_1.jpg",
                "[]",
                "fita, ribbon, lanyard, 1.5cm, ফিতা",
                1
            ),
            (
                "T-014V সফট কভার",
                "COV-T014V-10",
                "T-014V প্রিমিয়াম সফট আইডি কার্ড কভার (১০ টাকা)।",
                10.0,
                10.0,
                1000,
                "কভার",
                "/static/uploads/cover/T-014V_SOFT_COVER_10_TK_4.png",
                "[]",
                "cover, soft cover, t-014v, কভার",
                1
            ),
            (
                "DX কভার",
                "COV-DX-12",
                "DX প্রিমিয়াম কোয়ালিটি আইডি কার্ড কভার (১২ টাকা)।",
                12.0,
                12.0,
                1000,
                "কভার",
                "/static/uploads/cover/DX_COVER_12_TK_1.jpg",
                "[]",
                "cover, dx cover, কভার",
                1
            ),
            (
                "T-065V সফট কভার",
                "COV-T065V-14",
                "T-065V প্রিমিয়াম সফট আইডি কার্ড কভার (১৪ টাকা)।",
                14.0,
                14.0,
                1000,
                "কভার",
                "/static/uploads/cover/T-065V_SOFT_COVER_14_TK_5.png",
                "[]",
                "cover, soft cover, t-065v, কভার",
                1
            ),
            (
                "Xinding Q-993 কভার",
                "COV-Q993-16",
                "Xinding Q-993 প্রিমিয়াম আইডি কার্ড কভার (১৬ টাকা)।",
                16.0,
                16.0,
                1000,
                "কভার",
                "/static/uploads/cover/Xinding_Q-993_16_TK_8.jpg",
                "[]",
                "cover, xinding, q-993, কভার",
                1
            ),
            (
                "T-738V হার্ড কভার",
                "COV-T738V-20",
                "T-738V প্রিমিয়াম হার্ড আইডি কার্ড কভার (২০ টাকা)।",
                20.0,
                20.0,
                1000,
                "কভার",
                "/static/uploads/cover/T-738V_20_TK_6.jpg",
                "[]",
                "cover, hard cover, t-738v, কভার",
                1
            ),
            (
                "T-994V হার্ড কভার",
                "COV-T994V-20",
                "T-994V প্রিমিয়াম হার্ড আইডি কার্ড কভার (২০ টাকা)।",
                20.0,
                20.0,
                1000,
                "কভার",
                "/static/uploads/cover/T-994V_20_TK_7.jpeg",
                "[]",
                "cover, hard cover, t-994v, কভার",
                1
            ),
            (
                "REAP কভার",
                "COV-REAP-20",
                "REAP প্রিমিয়াম হার্ড আইডি কার্ড কভার (২০ টাকা)।",
                20.0,
                20.0,
                1000,
                "কভার",
                "/static/uploads/cover/REAP_COVER_20_TK_3.jpg",
                "[]",
                "cover, reap cover, কভার",
                1
            ),
            (
                "মেটাল কভার",
                "COV-METAL-30",
                "মেটাল ফ্রেম প্রিমিয়াম লাক্সারি আইডি কার্ড কভার (৩০ টাকা)।",
                30.0,
                30.0,
                1000,
                "কভার",
                "/static/uploads/cover/METAL_COVER_30_TK_2.jpg",
                "[]",
                "cover, metal cover, মেটাল কভার",
                1
            )
        ]
        for name, code, desc, price, d_price, stock, cat, img_url, g_imgs, tags, ws_id in defaults:
            cursor.execute("SELECT id FROM products WHERE (code = ? OR name = ?) AND workspace_id = ?", (code, name, ws_id))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO products (name, code, description, price, discount_price, stock, category, image_url, gallery_images, tags, workspace_id, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (name, code, desc, price, d_price, stock, cat, img_url, g_imgs, tags, ws_id))
        conn.commit()
    except Exception as e:
        print(f"[DB ensure_default_products Error]: {e}")
    finally:
        if should_close and conn:
            conn.close()

# ============================================================
# SAVED MEDIA LIBRARY HELPERS (VOICE NOTES & VIDEOS)
# ============================================================

def ensure_default_saved_media(conn=None):
    """Initializes default saved media idempotently and safely without overwriting user custom media."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True
    try:
        cursor = conn.cursor()
        defaults = [
            (
                "গুগল ফর্মে আইডি কার্ডের তথ্য ও ছবি আপলোড করার নিয়ম",
                "video",
                "/static/uploads/media/google_form_submission_guide.mp4",
                "গুগল ফর্মের মাধ্যমে আইডি কার্ডের তথ্য এবং ছবিগুলো কীভাবে আপলোড দিতে হয় তার পূর্ণাঙ্গ ডেমো ভিডিও।",
                0,
                1
            ),
            (
                "গুগল ফর্মে তথ্য সংশোধন করার নিয়ম",
                "video",
                "/static/uploads/media/google_form_edit_correction_guide.mp4",
                "তথ্য সাবমিট করার পর কোনো ভুল হলে তা কীভাবে এডিট বা সংশোধন করবেন তার নির্দেশিকা ভিডিও।",
                0,
                1
            ),
            (
                "কার্ড ও ফিতা এর কোয়ালিটি কেমন হবে",
                "voice",
                "/static/uploads/media/id_card_and_fita_quality.aac",
                "আমাদের জাপানি UV কালার প্রিন্ট পিভিসি আইডি কার্ড এবং প্রিমিয়াম ডিজিটাল সাবলিমেশন ফিতার কোয়ালিটি ও মান সংক্রান্ত ভয়েস বার্তা।",
                0,
                1
            ),
            (
                "আইডি কার্ড, ফিতা ও কভারের বৈশিষ্ট্য ও কোয়ালিটি",
                "voice",
                "/static/uploads/media/id_card_features_voice_note.mp3",
                "আমাদের জাপানি UV কালার প্রিন্ট পিভিসি আইডি কার্ড, ডিজিটাল সাবলিমেশন ফিতা ও কভারের প্রিমিয়াম বৈশিষ্ট্য সংক্রান্ত ভয়েস বার্তা।",
                0,
                1
            ),
            (
                "প্যাকেজ অফার ও বাল্ক অর্ডার ভয়েস বার্তা",
                "voice",
                "/static/uploads/voice/PTT-20260119-WA0105.mp3",
                "৮০-৯০ বা ১০০+ পিস অর্ডারে প্যাকেজ এবং স্পেশাল অফার সংক্রান্ত ভয়েস বার্তা।",
                0,
                1
            )
        ]
        for title, m_type, f_url, desc, dur, ws_id in defaults:
            cursor.execute("SELECT id FROM saved_media WHERE (file_url = ? OR title = ?) AND workspace_id = ?", (f_url, title, ws_id))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO saved_media (title, media_type, file_url, description, duration_seconds, workspace_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (title, m_type, f_url, desc, dur, ws_id))
        conn.commit()
    except Exception as e:
        print(f"[DB ensure_default_saved_media Error]: {e}")
    finally:
        if should_close and conn:
            conn.close()

def get_saved_media(media_type: str = None, workspace_id: Optional[int] = None) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM saved_media WHERE 1=1"
    params = []
    if media_type:
        query += " AND media_type = ?"
        params.append(media_type)
    if workspace_id is not None:
        query += " AND (workspace_id = ? OR workspace_id = 1)"
        params.append(int(workspace_id))
    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def create_saved_media(title: str, media_type: str, file_url: str, description: str = "", duration_seconds: int = 0, workspace_id: int = 1) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO saved_media (title, media_type, file_url, description, duration_seconds, workspace_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (title, media_type, file_url, description, duration_seconds, int(workspace_id or 1)))
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
    cursor.execute("SELECT sender_id, human_takeover, admin_takeover FROM conversations WHERE id = ?", (conversation_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
        
    sender_id = row["sender_id"]
    current_human = row["human_takeover"] or row["admin_takeover"] or 0
    new_takeover = status if status is not None else (0 if current_human == 1 else 1)
    
    if new_takeover == 1:
        cursor.execute("""
            UPDATE conversations 
            SET human_takeover = 1, admin_takeover = 1, ai_enabled = 0,
                takeover_at = CURRENT_TIMESTAMP, takeover_by = 'admin_toggle', takeover_reason = 'manual_toggle',
                conversation_version = COALESCE(conversation_version, 1) + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (conversation_id,))
        if sender_id:
            add_muted_number(sender_id)
    else:
        cursor.execute("""
            UPDATE conversations 
            SET human_takeover = 0, admin_takeover = 0, ai_enabled = 1,
                takeover_at = NULL, takeover_by = NULL, takeover_reason = NULL,
                conversation_version = COALESCE(conversation_version, 1) + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (conversation_id,))
        if sender_id:
            remove_muted_number(sender_id)
            
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
    
    clean_target = "".join([c for c in phone if c.isdigit()])
    target_last10 = clean_target[-10:] if len(clean_target) >= 10 else clean_target
    
    # Check if already present under any format
    already_present = False
    for existing in current:
        c_exist = "".join([c for c in str(existing) if c.isdigit()])
        e_last10 = c_exist[-10:] if len(c_exist) >= 10 else c_exist
        if clean_target and c_exist and (clean_target == c_exist or (target_last10 and target_last10 == e_last10)):
            already_present = True
            break
            
    if not already_present:
        current.append(phone)
        set_setting("blacklisted_ai_numbers", ", ".join(current))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if target_last10:
            cursor.execute("UPDATE conversations SET human_takeover = 1, admin_takeover = 1, ai_enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE sender_id LIKE ?", (f"%{target_last10}%",))
        else:
            cursor.execute("UPDATE conversations SET human_takeover = 1, admin_takeover = 1, ai_enabled = 0, updated_at = CURRENT_TIMESTAMP WHERE sender_id = ?", (phone,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return current

def remove_muted_number(phone: str) -> list:
    phone = str(phone).strip()
    current = get_muted_numbers()
    clean_target = "".join([c for c in phone if c.isdigit()])
    target_last10 = clean_target[-10:] if len(clean_target) >= 10 else clean_target
    
    def is_match(x):
        if x == phone:
            return True
        c_x = "".join([c for c in str(x) if c.isdigit()])
        x_last10 = c_x[-10:] if len(c_x) >= 10 else c_x
        if clean_target and c_x:
            return clean_target == c_x or (target_last10 and target_last10 == x_last10)
        return False

    updated = [x for x in current if not is_match(x)]
    set_setting("blacklisted_ai_numbers", ", ".join(updated))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if target_last10:
            cursor.execute("UPDATE conversations SET human_takeover = 0, admin_takeover = 0, ai_enabled = 1, updated_at = CURRENT_TIMESTAMP WHERE sender_id LIKE ?", (f"%{target_last10}%",))
        else:
            cursor.execute("UPDATE conversations SET human_takeover = 0, admin_takeover = 0, ai_enabled = 1, updated_at = CURRENT_TIMESTAMP WHERE sender_id = ?", (phone,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return updated

def is_muted_number(phone: str) -> bool:
    """Checks if a phone number or sender ID is in the muted/blacklisted AI numbers list."""
    if not phone:
        return False
    clean_target = "".join([c for c in str(phone) if c.isdigit()])
    if not clean_target:
        return False
    target_last10 = clean_target[-10:] if len(clean_target) >= 10 else clean_target
    current = get_muted_numbers()
    for existing in current:
        c_exist = "".join([c for c in str(existing) if c.isdigit()])
        e_last10 = c_exist[-10:] if len(c_exist) >= 10 else c_exist
        if clean_target and c_exist and (clean_target == c_exist or (target_last10 and target_last10 == e_last10)):
            return True
    return False

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

def get_conversation_state(sender_id: str = None, conversation_id: int = None, workspace_id: int = 1) -> dict:
    """Returns full deterministic state dict for a conversation / customer."""
    default_state = {
        "id": conversation_id,
        "sender_id": sender_id,
        "workspace_id": workspace_id,
        "admin_takeover": False,
        "ai_enabled": True,
        "human_takeover": 0,
        "conversation_version": 1,
        "takeover_at": None,
        "takeover_by": None,
        "takeover_reason": None
    }
    
    # 1. Check Master Switch
    if get_setting("ai_enabled", "true").lower() == "false":
        default_state["ai_enabled"] = False
        default_state["admin_takeover"] = True
        default_state["human_takeover"] = 1
        default_state["takeover_reason"] = "master_switch_disabled"
        return default_state

    # 2. Check Blacklisted / Muted Phone Numbers
    blacklisted = get_setting("blacklisted_ai_numbers", "")
    if blacklisted and sender_id:
        s_raw = str(sender_id).strip()
        clean_sender = "".join([c for c in s_raw if c.isdigit()])
        sender_last10 = clean_sender[-10:] if len(clean_sender) >= 10 else ""
        for bl in blacklisted.replace(",", "\n").split("\n"):
            bl_item = bl.strip()
            if not bl_item:
                continue
            if s_raw == bl_item:
                default_state["ai_enabled"] = False
                default_state["admin_takeover"] = True
                default_state["human_takeover"] = 1
                default_state["takeover_reason"] = "blacklisted_number"
                return default_state
            bl_clean = "".join([c for c in bl_item if c.isdigit()])
            bl_last10 = bl_clean[-10:] if len(bl_clean) >= 10 else ""
            if len(clean_sender) >= 8 and len(bl_clean) >= 8:
                if clean_sender == bl_clean or (sender_last10 and bl_last10 and sender_last10 == bl_last10):
                    default_state["ai_enabled"] = False
                    default_state["admin_takeover"] = True
                    default_state["human_takeover"] = 1
                    default_state["takeover_reason"] = "blacklisted_number"
                    return default_state

    # 3. Query DB conversation record
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if conversation_id:
            cursor.execute("""
                SELECT id, sender_id, workspace_id, human_takeover,
                       COALESCE(admin_takeover, human_takeover, 0) as admin_takeover,
                       COALESCE(ai_enabled, CASE WHEN human_takeover = 1 THEN 0 ELSE 1 END) as ai_enabled,
                       COALESCE(conversation_version, 1) as conversation_version,
                       takeover_at, takeover_by, takeover_reason
                FROM conversations WHERE id = ?
            """, (conversation_id,))
            row = cursor.fetchone()
        elif sender_id:
            ws_id = int(workspace_id or 1)
            clean_s = "".join(c for c in str(sender_id or "") if c.isdigit())
            last10 = clean_s[-10:] if len(clean_s) >= 10 else clean_s
            if last10:
                cursor.execute("""
                    SELECT id, sender_id, workspace_id, human_takeover,
                           COALESCE(admin_takeover, human_takeover, 0) as admin_takeover,
                           COALESCE(ai_enabled, CASE WHEN human_takeover = 1 THEN 0 ELSE 1 END) as ai_enabled,
                           COALESCE(conversation_version, 1) as conversation_version,
                           takeover_at, takeover_by, takeover_reason
                    FROM conversations 
                    WHERE (sender_id = ? OR sender_id LIKE ? OR sender_id LIKE ?)
                      AND (workspace_id = ? OR workspace_id IS NULL)
                    ORDER BY id DESC LIMIT 1
                """, (str(sender_id), f"%{last10}%", f"%{clean_s}%", ws_id))
            else:
                cursor.execute("""
                    SELECT id, sender_id, workspace_id, human_takeover,
                           COALESCE(admin_takeover, human_takeover, 0) as admin_takeover,
                           COALESCE(ai_enabled, CASE WHEN human_takeover = 1 THEN 0 ELSE 1 END) as ai_enabled,
                           COALESCE(conversation_version, 1) as conversation_version,
                           takeover_at, takeover_by, takeover_reason
                    FROM conversations WHERE sender_id = ? AND workspace_id = ?
                    ORDER BY id DESC LIMIT 1
                """, (str(sender_id), ws_id))
            row = cursor.fetchone()
            if not row and last10:
                cursor.execute("""
                    SELECT id, sender_id, workspace_id, human_takeover,
                           COALESCE(admin_takeover, human_takeover, 0) as admin_takeover,
                           COALESCE(ai_enabled, CASE WHEN human_takeover = 1 THEN 0 ELSE 1 END) as ai_enabled,
                           COALESCE(conversation_version, 1) as conversation_version,
                           takeover_at, takeover_by, takeover_reason
                    FROM conversations 
                    WHERE sender_id = ? OR sender_id LIKE ? OR sender_id LIKE ?
                    ORDER BY id DESC LIMIT 1
                """, (str(sender_id), f"%{last10}%", f"%{clean_s}%"))
                row = cursor.fetchone()
        else:
            conn.close()
            return default_state

        conn.close()
        
        if row:
            row_dict = dict(row)
            is_takeover = bool(
                row_dict.get("admin_takeover", 0) == 1 or 
                row_dict.get("human_takeover", 0) == 1 or 
                row_dict.get("ai_enabled", 1) == 0
            )
            default_state["id"] = row_dict.get("id")
            default_state["sender_id"] = row_dict.get("sender_id") or sender_id
            default_state["workspace_id"] = row_dict.get("workspace_id") or workspace_id
            default_state["admin_takeover"] = is_takeover
            default_state["ai_enabled"] = not is_takeover
            default_state["human_takeover"] = 1 if is_takeover else 0
            default_state["conversation_version"] = int(row_dict.get("conversation_version") or 1)
            default_state["takeover_at"] = row_dict.get("takeover_at")
            default_state["takeover_by"] = row_dict.get("takeover_by")
            default_state["takeover_reason"] = row_dict.get("takeover_reason")
    except Exception as e:
        print(f"[DB get_conversation_state Error]: {e}")

    return default_state

def set_admin_takeover(
    sender_id: str = None,
    conversation_id: int = None,
    workspace_id: int = 1,
    takeover_by: str = "main_admin",
    takeover_reason: str = "human_admin_message"
) -> int:
    """
    Deterministically enables ADMIN TAKEOVER for a customer / conversation.
    Increments conversation_version to instantly invalidate any in-flight/pending AI jobs.
    Returns the new conversation_version.
    """
    new_version = 1
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ws_id = int(workspace_id or 1)
        
        target_conv_ids = []
        if conversation_id:
            target_conv_ids = [conversation_id]
        elif sender_id:
            clean_s = "".join(c for c in str(sender_id or "") if c.isdigit())
            last10 = clean_s[-10:] if len(clean_s) >= 10 else clean_s
            if last10:
                cursor.execute("""
                    SELECT id FROM conversations 
                    WHERE (sender_id = ? OR sender_id LIKE ? OR sender_id LIKE ?) 
                      AND (workspace_id = ? OR workspace_id IS NULL)
                """, (str(sender_id), f"%{last10}%", f"%{clean_s}%", ws_id))
            else:
                cursor.execute("SELECT id FROM conversations WHERE sender_id = ? AND (workspace_id = ? OR workspace_id IS NULL)", (str(sender_id), ws_id))
            rows = cursor.fetchall()
            target_conv_ids = [r["id"] for r in rows]
            
        if not target_conv_ids and sender_id:
            cursor.execute("""
                INSERT INTO conversations (
                    workspace_id, channel, sender_id, customer_name, last_message,
                    admin_takeover, human_takeover, ai_enabled, takeover_at, takeover_by, takeover_reason, conversation_version,
                    customer_turn_version, last_responded_turn_version
                )
                VALUES (?, 'whatsapp', ?, 'Customer', '[Admin Takeover]', 1, 1, 0, CURRENT_TIMESTAMP, ?, ?, 2, 1, 1)
            """, (ws_id, str(sender_id), takeover_by, takeover_reason))
            new_version = 2
        else:
            for cid in target_conv_ids:
                cursor.execute("""
                    UPDATE conversations 
                    SET admin_takeover = 1,
                        human_takeover = 1,
                        ai_enabled = 0,
                        takeover_at = CURRENT_TIMESTAMP,
                        takeover_by = ?,
                        takeover_reason = ?,
                        conversation_version = COALESCE(conversation_version, 1) + 1,
                        last_responded_turn_version = COALESCE(customer_turn_version, 1),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (takeover_by, takeover_reason, cid))
                
                cursor.execute("SELECT conversation_version FROM conversations WHERE id = ?", (cid,))
                vrow = cursor.fetchone()
                if vrow and vrow["conversation_version"]:
                    new_version = max(new_version, int(vrow["conversation_version"]))

        conn.commit()
        conn.close()
        
        # Cancel any active/pending debouncer batches for this customer
        if sender_id:
            add_muted_number(str(sender_id))
            try:
                from app.channels.debouncer import message_debouncer
                message_debouncer.cancel_batch("whatsapp", ws_id, str(sender_id))
                message_debouncer.cancel_batch("facebook", ws_id, str(sender_id))
            except Exception:
                pass
            
        print(f"[ADMIN_TAKEOVER] workspace_id={ws_id} conversation_id={conversation_id or sender_id} customer_id={sender_id} takeover_by={takeover_by} conversation_version={new_version}")
        print(f"[ADMIN_TAKEOVER_ENABLED] sender={sender_id} conv_id={conversation_id} new_version={new_version} by={takeover_by} reason={takeover_reason}")
    except Exception as e:
        print(f"[DB set_admin_takeover Error]: {e}")
        
    return new_version

def enable_conversation_ai(
    sender_id: str = None,
    conversation_id: int = None,
    workspace_id: int = 1,
    enabled_by: str = "admin"
) -> int:
    """
    Explicitly re-enables AI auto-response for a customer / conversation.
    Increments conversation_version so any stale pending jobs from past takeover cannot fire.
    Synchronizes last_responded_turn_version = customer_turn_version to prevent backlog triggers.
    Returns the new conversation_version.
    """
    new_version = 1
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ws_id = int(workspace_id or 1)
        
        target_conv_ids = []
        if conversation_id:
            target_conv_ids = [conversation_id]
        elif sender_id:
            cursor.execute("SELECT id FROM conversations WHERE sender_id = ? AND (workspace_id = ? OR workspace_id IS NULL)", (str(sender_id), ws_id))
            rows = cursor.fetchall()
            target_conv_ids = [r["id"] for r in rows]
            
        if not target_conv_ids and sender_id:
            cursor.execute("""
                INSERT INTO conversations (
                    workspace_id, channel, sender_id, customer_name, last_message,
                    admin_takeover, human_takeover, ai_enabled, takeover_at, takeover_by, takeover_reason, conversation_version,
                    customer_turn_version, last_responded_turn_version
                )
                VALUES (?, 'whatsapp', ?, 'Customer', '', 0, 0, 1, NULL, NULL, NULL, 2, 1, 0)
            """, (ws_id, str(sender_id)))
            new_version = 2
        else:
            for cid in target_conv_ids:
                cursor.execute("""
                    UPDATE conversations 
                    SET admin_takeover = 0,
                        human_takeover = 0,
                        ai_enabled = 1,
                        takeover_at = NULL,
                        takeover_by = NULL,
                        takeover_reason = NULL,
                        conversation_version = COALESCE(conversation_version, 1) + 1,
                        last_responded_turn_version = COALESCE(customer_turn_version, 0),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (cid,))
                
                cursor.execute("SELECT conversation_version FROM conversations WHERE id = ?", (cid,))
                vrow = cursor.fetchone()
                if vrow and vrow["conversation_version"]:
                    new_version = max(new_version, int(vrow["conversation_version"]))

        conn.commit()
        conn.close()
        
        if sender_id:
            remove_muted_number(str(sender_id))
            
        print(f"[AI_REENABLED] workspace_id={ws_id} sender={sender_id} conv_id={conversation_id} new_version={new_version} by={enabled_by}")
    except Exception as e:
        print(f"[DB enable_conversation_ai Error]: {e}")
        
    return new_version

def is_conversation_ai_active(sender_id: str = None, conversation_id: int = None, workspace_id: int = 1) -> bool:
    """
    Zero-Reply Safety Guard: Returns True ONLY IF AI is strictly allowed to reply to this customer.
    Returns False if:
    - Master Switch is OFF
    - Phone number is in blacklist/muted
    - admin_takeover == 1 or human_takeover == 1 or ai_enabled == 0 in conversations table
    - Owner/Admin has sent the most recent message in the conversation (human conversation in progress)
    """
    # 1. Master Switch Check
    if get_setting("ai_enabled", "true").lower() == "false":
        return False

    # 2. Blacklisted / Muted Number Check
    if sender_id and is_muted_number(str(sender_id)):
        return False

    # 3. Deterministic DB State Check
    state = get_conversation_state(sender_id=sender_id, conversation_id=conversation_id, workspace_id=workspace_id)
    if state.get("admin_takeover") is True or state.get("ai_enabled") is False or state.get("human_takeover", 0) == 1:
        return False

    # 4. Check if the most recent message was sent by human admin / shop owner
    if sender_id or conversation_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            clean_s = "".join(c for c in str(sender_id or "") if c.isdigit())
            last10 = clean_s[-10:] if len(clean_s) >= 10 else clean_s

            if conversation_id:
                cursor.execute("""
                    SELECT sender_type, sender_role, direction FROM messages
                    WHERE conversation_id = ?
                    ORDER BY id DESC LIMIT 1
                """, (conversation_id,))
            elif last10:
                cursor.execute("""
                    SELECT m.sender_type, m.sender_role, m.direction 
                    FROM messages m
                    JOIN conversations c ON m.conversation_id = c.id
                    WHERE (c.sender_id = ? OR c.sender_id LIKE ? OR c.sender_id LIKE ?)
                    ORDER BY m.id DESC LIMIT 1
                """, (str(sender_id), f"%{last10}%", f"%{clean_s}%"))
            else:
                cursor.execute("""
                    SELECT m.sender_type, m.sender_role, m.direction 
                    FROM messages m
                    JOIN conversations c ON m.conversation_id = c.id
                    WHERE c.sender_id = ?
                    ORDER BY m.id DESC LIMIT 1
                """, (str(sender_id),))
            last_msg = cursor.fetchone()
            conn.close()

            if last_msg:
                s_type = str(last_msg["sender_type"] or "").lower()
                s_role = str(last_msg["sender_role"] or "").upper()
                if s_type == "admin" or s_role == "ADMIN":
                    return False
        except Exception:
            pass

    return True

# ============================================================
# MULTI-PAGE & MULTI-WHATSAPP ARCHITECTURE DATABASE HELPERS
# ============================================================

def get_all_connected_pages() -> list:
    """Returns list of all connected Facebook Pages with their linked WhatsApp status."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT cp.*, wa.phone_number_id as wa_phone_id, wa.display_phone_number as wa_display_phone,
                   wa.connection_status as wa_status, wa.coexistence_active as wa_coexistence
            FROM connected_pages cp
            LEFT JOIN whatsapp_accounts wa ON cp.id = wa.connected_page_id
            ORDER BY cp.id ASC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB get_all_connected_pages Error]: {e}")
        return []

def ensure_facebook_page_consistency(conn=None) -> Optional[dict]:
    """
    Self-healing migration and consistency enforcer for Facebook connected pages.
    Guarantees:
    1. Workspace 1 (RS Graphics) always has a valid, canonical Facebook page with real Meta Page ID 105116472071659.
    2. Legacy placeholder IDs (rs_graphics_page_1, empty, default) are safely migrated to 105116472071659.
    3. Token from settings or environment is safely synced.
    4. Fully idempotent and safe to call concurrently or repeatedly.
    """
    target_page_id = str(
        get_setting("fb_page_id")
        or os.getenv("FB_PAGE_ID")
        or settings.FB_PAGE_ID
        or "105116472071659"
    ).strip()
    target_page_token = str(
        get_setting("fb_page_access_token")
        or os.getenv("FB_PAGE_ACCESS_TOKEN")
        or settings.FB_PAGE_ACCESS_TOKEN
        or ""
    ).strip()
    target_page_name = str(settings.SHOP_NAME or "RS Graphics (আরএস গ্রাফিক্স)").strip()
    target_shop_phone = str(settings.SHOP_PHONE or "01816504097").strip()

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()

        # Step 1: Check if page already exists with target_page_id
        cursor.execute("SELECT * FROM connected_pages WHERE page_id = ?", (target_page_id,))
        exact_match = cursor.fetchone()

        canonical_id = None
        if exact_match:
            canonical_id = exact_match["id"]
            cursor.execute("""
                UPDATE connected_pages SET
                    workspace_id = 1,
                    page_name = COALESCE(NULLIF(page_name, ''), ?),
                    page_access_token = CASE 
                        WHEN LENGTH(?) > 30 THEN ?
                        WHEN page_access_token IS NULL OR page_access_token = '' THEN ?
                        ELSE page_access_token 
                    END,
                    page_status = 'connected',
                    messenger_enabled = 1,
                    comments_enabled = 1,
                    ai_enabled = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (target_page_name, target_page_token, target_page_token, target_page_token, canonical_id))
            # Delete duplicate rows with target_page_id if any
            cursor.execute("DELETE FROM connected_pages WHERE page_id = ? AND id != ?", (target_page_id, canonical_id))
        else:
            # Step 2: Look for candidate row belonging to Workspace 1
            cursor.execute("""
                SELECT * FROM connected_pages 
                WHERE workspace_id = 1 
                   OR page_id IN ('rs_graphics_page_1', '', 'default')
                ORDER BY id ASC
            """)
            w1_candidates = cursor.fetchall()
            if w1_candidates:
                canonical_id = w1_candidates[0]["id"]
                cursor.execute("DELETE FROM connected_pages WHERE page_id = ? AND id != ?", (target_page_id, canonical_id))
                cursor.execute("""
                    UPDATE connected_pages SET
                        workspace_id = 1,
                        page_id = ?,
                        page_name = COALESCE(NULLIF(page_name, ''), ?),
                        page_access_token = CASE 
                            WHEN LENGTH(?) > 30 THEN ?
                            WHEN page_access_token IS NULL OR page_access_token = '' THEN ?
                            ELSE page_access_token 
                        END,
                        page_status = 'connected',
                        messenger_enabled = 1,
                        comments_enabled = 1,
                        ai_enabled = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (target_page_id, target_page_name, target_page_token, target_page_token, target_page_token, canonical_id))
            else:
                # Step 3: Insert canonical row
                cursor.execute("""
                    INSERT OR IGNORE INTO connected_pages (
                        workspace_id, page_id, page_name, page_access_token, page_status,
                        messenger_enabled, comments_enabled, ai_enabled, ai_system_prompt,
                        shop_name, shop_phone, shop_address, delivery_inside_dhaka, delivery_outside_dhaka
                    ) VALUES (1, ?, ?, ?, 'connected', 1, 1, 1, '', ?, ?, 'ঢাকা, বাংলাদেশ', 70.0, 130.0)
                """, (target_page_id, target_page_name, target_page_token, target_page_name, target_shop_phone))
                canonical_id = cursor.lastrowid

        # Update settings table
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'fb_page_id'", (target_page_id,))
        if target_page_token and len(target_page_token) > 30:
            cursor.execute("UPDATE settings SET value = ? WHERE key = 'fb_page_access_token'", (target_page_token,))

        conn.commit()

        cursor.execute("SELECT * FROM connected_pages WHERE id = ?", (canonical_id,))
        final_row = cursor.fetchone()
        return dict(final_row) if final_row else None
    except Exception as e:
        print(f"[ensure_facebook_page_consistency Error]: {e}")
        return None
    finally:
        if close_conn and conn:
            conn.close()

def get_connected_page(page_id_or_id) -> Optional[dict]:
    """Retrieves a single connected page record by page_id (string) or internal id (integer)."""
    if not page_id_or_id:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if str(page_id_or_id).isdigit() and len(str(page_id_or_id)) < 8:
            cursor.execute("SELECT * FROM connected_pages WHERE id = ? OR page_id = ?", (int(page_id_or_id), str(page_id_or_id)))
        else:
            cursor.execute("SELECT * FROM connected_pages WHERE page_id = ?", (str(page_id_or_id),))
        row = cursor.fetchone()
        conn.close()

        if not row and str(page_id_or_id) in ["105116472071659", "rs_graphics_page_1"]:
            return ensure_facebook_page_consistency()

        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_connected_page Error]: {e}")
        return None

def save_connected_page(data: dict) -> int:
    """Inserts or updates a connected Facebook Page record."""
    page_id = str(data.get("page_id", "")).strip()
    page_name = str(data.get("page_name", "")).strip() or "Facebook Page"
    page_token = str(data.get("page_access_token", "")).strip()
    workspace_id = data.get("workspace_id")
    
    if not page_id:
        raise ValueError("page_id is required")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM connected_pages WHERE page_id = ?", (page_id,))
    existing = cursor.fetchone()

    # If existing and no new token passed, preserve existing token
    if existing and not page_token:
        page_token = existing["page_access_token"]
    elif not page_token:
        page_token = get_setting("fb_page_access_token") or os.getenv("FB_PAGE_ACCESS_TOKEN", "")

    if not page_token:
        conn.close()
        raise ValueError("page_access_token is required for connecting a page")

    # If no workspace_id provided, look up or create workspace for this page
    if not workspace_id:
        if existing and existing["workspace_id"]:
            workspace_id = existing["workspace_id"]
        else:
            cursor.execute("SELECT id FROM workspaces WHERE name = ? OR shop_name = ?", (page_name, page_name))
            ws_row = cursor.fetchone()
            if ws_row:
                workspace_id = ws_row["id"]
            else:
                # Create a dedicated workspace for this new Page
                cursor.execute("""
                    INSERT INTO workspaces (name, slug, status, shop_name, shop_phone, shop_address, delivery_inside_dhaka, delivery_outside_dhaka, ai_system_prompt, ai_enabled)
                    VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
                """, (
                    page_name, page_name.lower().replace(" ", "-"),
                    data.get("shop_name", page_name),
                    data.get("shop_phone", ""),
                    data.get("shop_address", "ঢাকা, বাংলাদেশ"),
                    float(data.get("delivery_inside_dhaka", 70.0) or 70.0),
                    float(data.get("delivery_outside_dhaka", 130.0) or 130.0),
                    data.get("ai_system_prompt", ""),
                    int(data.get("ai_enabled", 1))
                ))
                workspace_id = cursor.lastrowid
    
    if existing:
        page_pk = existing["id"]
        cursor.execute("""
            UPDATE connected_pages SET
                workspace_id = COALESCE(?, workspace_id),
                page_name = COALESCE(?, page_name),
                page_access_token = COALESCE(?, page_access_token),
                page_status = COALESCE(?, page_status),
                messenger_enabled = COALESCE(?, messenger_enabled),
                comments_enabled = COALESCE(?, comments_enabled),
                ai_enabled = COALESCE(?, ai_enabled),
                ai_system_prompt = COALESCE(?, ai_system_prompt),
                shop_name = COALESCE(?, shop_name),
                shop_phone = COALESCE(?, shop_phone),
                shop_address = COALESCE(?, shop_address),
                delivery_inside_dhaka = COALESCE(?, delivery_inside_dhaka),
                delivery_outside_dhaka = COALESCE(?, delivery_outside_dhaka),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            workspace_id,
            page_name, page_token,
            data.get("page_status", "connected"),
            data.get("messenger_enabled", 1),
            data.get("comments_enabled", 1),
            data.get("ai_enabled", 1),
            data.get("ai_system_prompt"),
            data.get("shop_name"),
            data.get("shop_phone"),
            data.get("shop_address"),
            data.get("delivery_inside_dhaka"),
            data.get("delivery_outside_dhaka"),
            page_pk
        ))
    else:
        cursor.execute("""
            INSERT INTO connected_pages (
                workspace_id, page_id, page_name, page_access_token, page_status,
                messenger_enabled, comments_enabled, ai_enabled, ai_system_prompt,
                shop_name, shop_phone, shop_address, delivery_inside_dhaka, delivery_outside_dhaka
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            workspace_id,
            page_id, page_name, page_token,
            data.get("page_status", "connected"),
            data.get("messenger_enabled", 1),
            data.get("comments_enabled", 1),
            data.get("ai_enabled", 1),
            data.get("ai_system_prompt", ""),
            data.get("shop_name", page_name),
            data.get("shop_phone", ""),
            data.get("shop_address", "ঢাকা, বাংলাদেশ"),
            data.get("delivery_inside_dhaka", 70.0),
            data.get("delivery_outside_dhaka", 130.0)
        ))
        page_pk = cursor.lastrowid

    conn.commit()
    conn.close()
    return page_pk

def delete_connected_page(page_id: str) -> bool:
    """Disconnects a page and unlinks associated WhatsApp account without deleting conversations."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM connected_pages WHERE page_id = ?", (str(page_id),))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False
        
        page_pk = row["id"]
        cursor.execute("UPDATE whatsapp_accounts SET connected_page_id = NULL WHERE connected_page_id = ?", (page_pk,))
        cursor.execute("DELETE FROM connected_pages WHERE id = ?", (page_pk,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB delete_connected_page Error]: {e}")
        return False

def get_all_whatsapp_accounts() -> list:
    """Returns all configured WhatsApp Business accounts."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wa.*, cp.page_id, cp.page_name, cp.shop_name, w.name as workspace_name
            FROM whatsapp_accounts wa
            LEFT JOIN connected_pages cp ON wa.connected_page_id = cp.id
            LEFT JOIN workspaces w ON wa.workspace_id = w.id
            ORDER BY wa.id ASC
        """)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB get_all_whatsapp_accounts Error]: {e}")
        return []
    finally:
        if conn:
            conn.close()

def ensure_whatsapp_account_consistency(conn=None) -> Optional[dict]:
    """
    Self-healing migration and consistency enforcer for WhatsApp accounts.
    Guarantees:
    1. Workspace 1 (RS Graphics) always has a valid, canonical WhatsApp account with phone_number_id = 4184514263660680.
    2. Zero duplicate rows for phone_number_id = 4184514263660680.
    3. Legacy IDs (418451426636680, 8801816504097_wa, empty) are safely migrated without losing tokens, WABA ID, or conversation data.
    4. Settings table is kept in sync (whatsapp_phone_number_id = 4184514263660680).
    5. Fully idempotent and safe to call concurrently or repeatedly.
    """
    target_wa_phone_id = str(get_setting("whatsapp_phone_number_id") or settings.WHATSAPP_PHONE_NUMBER_ID or "418451426636680").strip()
    target_waba_id = str(get_setting("whatsapp_waba_id") or settings.WHATSAPP_WABA_ID or "271335301757320").strip()
    target_display = str(settings.WHATSAPP_DISPLAY_PHONE_NUMBER or "+8801816504097").strip()
    target_token = str(
        get_setting("whatsapp_access_token")
        or get_setting("meta_system_user_access_token")
        or os.getenv("META_SYSTEM_USER_ACCESS_TOKEN")
        or os.getenv("WHATSAPP_ACCESS_TOKEN")
        or settings.WHATSAPP_ACCESS_TOKEN
        or settings.META_SYSTEM_USER_ACCESS_TOKEN
        or ""
    ).strip()

    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    try:
        cursor = conn.cursor()

        # Step 1: Check if an account already exists with the exact target phone_number_id
        cursor.execute("SELECT * FROM whatsapp_accounts WHERE phone_number_id = ?", (target_wa_phone_id,))
        exact_match = cursor.fetchone()

        canonical_id = None
        if exact_match:
            canonical_id = exact_match["id"]
            # Ensure workspace_id is 1, display and waba_id are populated
            cursor.execute("""
                UPDATE whatsapp_accounts SET
                    workspace_id = 1,
                    display_phone_number = COALESCE(NULLIF(display_phone_number, ''), ?),
                    waba_id = COALESCE(NULLIF(waba_id, ''), ?),
                    access_token = CASE
                        WHEN ? != '' AND ? NOT LIKE 'EAATest%' THEN ?
                        ELSE COALESCE(NULLIF(access_token, ''), ?)
                    END,
                    connection_mode = 'business_app_coexistence',
                    connection_status = 'connected',
                    coexistence_active = 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (target_display, target_waba_id, target_token, target_token, target_token, target_token, canonical_id))
            # Delete any duplicate rows with target_wa_phone_id if any exist
            cursor.execute("DELETE FROM whatsapp_accounts WHERE phone_number_id = ? AND id != ?", (target_wa_phone_id, canonical_id))
        else:
            # Step 2: Look for candidate/legacy rows belonging to Workspace 1
            cursor.execute("""
                SELECT * FROM whatsapp_accounts 
                WHERE workspace_id = 1 
                   OR phone_number_id IN ('418451426636680', '8801816504097_wa', '8801816504097', '')
                   OR display_phone_number LIKE '%01816504097%'
                ORDER BY id ASC
            """)
            w1_candidates = cursor.fetchall()
            if w1_candidates:
                canonical_id = w1_candidates[0]["id"]
                # Delete any other row with target_wa_phone_id before updating
                cursor.execute("DELETE FROM whatsapp_accounts WHERE phone_number_id = ? AND id != ?", (target_wa_phone_id, canonical_id))
                cursor.execute("""
                    UPDATE whatsapp_accounts SET
                        workspace_id = 1,
                        phone_number_id = ?,
                        display_phone_number = COALESCE(NULLIF(display_phone_number, ''), ?),
                        waba_id = COALESCE(NULLIF(waba_id, ''), ?),
                        access_token = CASE
                            WHEN ? != '' AND ? NOT LIKE 'EAATest%' THEN ?
                            ELSE COALESCE(NULLIF(access_token, ''), ?)
                        END,
                        connection_mode = 'business_app_coexistence',
                        connection_status = 'connected',
                        coexistence_active = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (target_wa_phone_id, target_display, target_waba_id, target_token, target_token, target_token, target_token, canonical_id))
            else:
                # Step 3: Insert canonical row
                cursor.execute("SELECT id FROM connected_pages WHERE workspace_id = 1 ORDER BY id ASC LIMIT 1")
                cp_row = cursor.fetchone()
                cp_id = cp_row["id"] if cp_row else 1

                cursor.execute("""
                    INSERT OR IGNORE INTO whatsapp_accounts (
                        workspace_id, connected_page_id, waba_id, phone_number_id, display_phone_number,
                        access_token, connection_mode, connection_status, coexistence_active
                    ) VALUES (1, ?, ?, ?, ?, ?, 'business_app_coexistence', 'connected', 1)
                """, (cp_id, target_waba_id, target_wa_phone_id, target_display, target_token))
                canonical_id = cursor.lastrowid

        # Step 4: Link canonical account to Page 1 if not connected
        cursor.execute("SELECT id FROM connected_pages WHERE workspace_id = 1 ORDER BY id ASC LIMIT 1")
        cp_p1 = cursor.fetchone()
        if cp_p1 and canonical_id:
            cursor.execute("UPDATE whatsapp_accounts SET connected_page_id = ? WHERE id = ? AND (connected_page_id IS NULL OR connected_page_id = '')", (cp_p1["id"], canonical_id))

        # Step 5: Ensure settings table is consistent
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'whatsapp_phone_number_id'", (target_wa_phone_id,))
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'whatsapp_display_phone_number'", (target_display,))
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'whatsapp_waba_id'", (target_waba_id,))

        conn.commit()

        # Step 6: Query and return the canonical account dict
        cursor.execute("""
            SELECT wa.*, cp.page_id, cp.page_name, cp.shop_name, cp.ai_enabled as page_ai_enabled,
                   cp.ai_system_prompt as page_ai_prompt, cp.delivery_inside_dhaka, cp.delivery_outside_dhaka,
                   w.name as workspace_name, w.id as ws_id
            FROM whatsapp_accounts wa
            LEFT JOIN connected_pages cp ON wa.connected_page_id = cp.id
            LEFT JOIN workspaces w ON wa.workspace_id = w.id
            WHERE wa.phone_number_id = ?
        """, (target_wa_phone_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[ensure_whatsapp_account_consistency Error]: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if close_conn and conn:
            conn.close()

def get_whatsapp_account_by_phone_id(phone_number_id: str) -> Optional[dict]:
    """Finds a WhatsApp account record by its Meta phone_number_id."""
    if not phone_number_id:
        return None
    phone_id_str = str(phone_number_id).strip()
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wa.*, cp.page_id, cp.page_name, cp.shop_name, cp.ai_enabled as page_ai_enabled,
                   cp.ai_system_prompt as page_ai_prompt, cp.delivery_inside_dhaka, cp.delivery_outside_dhaka,
                   w.name as workspace_name, w.id as ws_id
            FROM whatsapp_accounts wa
            LEFT JOIN connected_pages cp ON wa.connected_page_id = cp.id
            LEFT JOIN workspaces w ON wa.workspace_id = w.id
            WHERE wa.phone_number_id = ?
        """, (phone_id_str,))
        row = cursor.fetchone()
        if not row and phone_id_str in ["4184514263660680", "418451426636680"]:
            return ensure_whatsapp_account_consistency(conn=conn)
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_whatsapp_account_by_phone_id Error]: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_whatsapp_account_by_page_id(page_id: str) -> Optional[dict]:
    """Finds the WhatsApp account linked to a specific connected Facebook Page."""
    if not page_id:
        return None
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wa.*, cp.page_id, cp.page_name, w.name as workspace_name, w.id as ws_id
            FROM whatsapp_accounts wa
            JOIN connected_pages cp ON wa.connected_page_id = cp.id
            LEFT JOIN workspaces w ON wa.workspace_id = w.id
            WHERE cp.page_id = ?
            ORDER BY wa.id ASC LIMIT 1
        """, (str(page_id),))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_whatsapp_account_by_page_id Error]: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_whatsapp_account_by_workspace_id(workspace_id: int) -> Optional[dict]:
    """Finds the primary WhatsApp account linked to a specific workspace."""
    if not workspace_id:
        return None
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wa.*, cp.page_id, cp.page_name, cp.shop_name, cp.ai_enabled as page_ai_enabled,
                   cp.ai_system_prompt as page_ai_prompt, cp.delivery_inside_dhaka, cp.delivery_outside_dhaka,
                   w.name as workspace_name, w.id as ws_id
            FROM whatsapp_accounts wa
            LEFT JOIN connected_pages cp ON wa.connected_page_id = cp.id
            LEFT JOIN workspaces w ON wa.workspace_id = w.id
            WHERE wa.workspace_id = ?
            ORDER BY wa.id ASC LIMIT 1
        """, (int(workspace_id),))
        row = cursor.fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_whatsapp_account_by_workspace_id Error]: {e}")
        return None
    finally:
        if conn:
            conn.close()

def save_whatsapp_account(data: dict) -> int:
    """Inserts or updates a WhatsApp Business account record."""
    phone_id = str(data.get("phone_number_id", "")).strip()
    if not phone_id:
        raise ValueError("phone_number_id is required")

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM whatsapp_accounts WHERE phone_number_id = ?", (phone_id,))
        existing = cursor.fetchone()

        connected_page_pk = data.get("connected_page_id")
        workspace_id = data.get("workspace_id")
        if not connected_page_pk and data.get("page_id"):
            cursor.execute("SELECT id, workspace_id FROM connected_pages WHERE page_id = ?", (str(data.get("page_id")),))
            cp = cursor.fetchone()
            if cp:
                connected_page_pk = cp["id"]
                if not workspace_id:
                    workspace_id = cp["workspace_id"]

        if not workspace_id:
            workspace_id = 1

        if existing:
            wa_pk = existing["id"]
            cursor.execute("""
                UPDATE whatsapp_accounts SET
                    workspace_id = COALESCE(?, workspace_id),
                    connected_page_id = COALESCE(?, connected_page_id),
                    waba_id = COALESCE(?, waba_id),
                    display_phone_number = COALESCE(?, display_phone_number),
                    access_token = COALESCE(?, access_token),
                    connection_mode = COALESCE(?, connection_mode),
                    connection_status = COALESCE(?, connection_status),
                    coexistence_active = COALESCE(?, coexistence_active),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                workspace_id,
                connected_page_pk,
                data.get("waba_id"),
                data.get("display_phone_number"),
                data.get("access_token"),
                data.get("connection_mode", "business_app_coexistence"),
                data.get("connection_status", "connected"),
                data.get("coexistence_active", 1),
                wa_pk
            ))
        else:
            cursor.execute("""
                INSERT INTO whatsapp_accounts (
                    workspace_id, connected_page_id, waba_id, phone_number_id, display_phone_number,
                    access_token, connection_mode, connection_status, coexistence_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                workspace_id,
                connected_page_pk,
                data.get("waba_id", ""),
                phone_id,
                data.get("display_phone_number", ""),
                data.get("access_token", ""),
                data.get("connection_mode", "business_app_coexistence"),
                data.get("connection_status", "connected"),
                data.get("coexistence_active", 1)
            ))
            wa_pk = cursor.lastrowid

        conn.commit()
        return wa_pk
    finally:
        if conn:
            conn.close()

def delete_whatsapp_account(phone_number_id: str) -> bool:
    """Removes a WhatsApp account connection."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM whatsapp_accounts WHERE phone_number_id = ?", (str(phone_number_id),))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB delete_whatsapp_account Error]: {e}")
        return False
    finally:
        if conn:
            conn.close()

# ============================================================
# WORKSPACE & BUSINESS TENANT HELPERS
# ============================================================

def get_all_workspaces() -> list:
    """Returns list of all registered business workspaces with page & account summaries."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT w.*,
                   (SELECT COUNT(*) FROM connected_pages cp WHERE cp.workspace_id = w.id) as page_count,
                   (SELECT COUNT(*) FROM whatsapp_accounts wa WHERE wa.workspace_id = w.id) as wa_count,
                   (SELECT COUNT(*) FROM products p WHERE p.workspace_id = w.id AND p.is_active = 1) as product_count,
                   (SELECT COUNT(*) FROM orders o WHERE o.workspace_id = w.id) as order_count
            FROM workspaces w
            ORDER BY w.id ASC
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        print(f"[DB get_all_workspaces Error]: {e}")
        return []

def get_workspace(workspace_id: int) -> Optional[dict]:
    """Retrieves a single business workspace by ID."""
    if not workspace_id:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM workspaces WHERE id = ?", (int(workspace_id),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_workspace Error]: {e}")
        return None

def save_workspace(data: dict) -> int:
    """Inserts or updates a business workspace record."""
    ws_id = data.get("id")
    name = str(data.get("name", "")).strip() or "New Business"
    raw_slug = str(data.get("slug", "")).strip() or name.lower().replace(" ", "-")
    status = data.get("status", "active")
    shop_name = data.get("shop_name") or name
    shop_phone = data.get("shop_phone", "")
    shop_address = data.get("shop_address", "ঢাকা, বাংলাদেশ")
    inside_fee = float(data.get("delivery_inside_dhaka", 70.0) or 70.0)
    outside_fee = float(data.get("delivery_outside_dhaka", 130.0) or 130.0)
    ai_prompt = data.get("ai_system_prompt", "")
    ai_enabled = int(data.get("ai_enabled", 1))

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        if ws_id:
            cursor.execute("""
                UPDATE workspaces SET
                    name = ?, slug = ?, status = ?, shop_name = ?, shop_phone = ?,
                    shop_address = ?, delivery_inside_dhaka = ?, delivery_outside_dhaka = ?,
                    ai_system_prompt = ?, ai_enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (name, raw_slug, status, shop_name, shop_phone, shop_address, inside_fee, outside_fee, ai_prompt, ai_enabled, int(ws_id)))
            pk = int(ws_id)
        else:
            # Ensure unique slug
            slug = raw_slug
            counter = 1
            while True:
                cursor.execute("SELECT id FROM workspaces WHERE slug = ?", (slug,))
                if not cursor.fetchone():
                    break
                slug = f"{raw_slug}-{counter}"
                counter += 1

            cursor.execute("""
                INSERT INTO workspaces (
                    name, slug, status, shop_name, shop_phone, shop_address,
                    delivery_inside_dhaka, delivery_outside_dhaka, ai_system_prompt, ai_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, slug, status, shop_name, shop_phone, shop_address, inside_fee, outside_fee, ai_prompt, ai_enabled))
            pk = cursor.lastrowid

        conn.commit()
        return pk
    finally:
        if conn:
            conn.close()

def delete_workspace(workspace_id: int) -> bool:
    """Deletes a secondary workspace safely (Workspace 1 cannot be deleted)."""
    if int(workspace_id) == 1:
        return False # Protected primary workspace
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM workspaces WHERE id = ?", (int(workspace_id),))
        cursor.execute("DELETE FROM products WHERE workspace_id = ?", (int(workspace_id),))
        cursor.execute("DELETE FROM orders WHERE workspace_id = ?", (int(workspace_id),))
        cursor.execute("DELETE FROM conversations WHERE workspace_id = ?", (int(workspace_id),))
        cursor.execute("DELETE FROM ai_training_rules WHERE workspace_id = ?", (int(workspace_id),))
        cursor.execute("DELETE FROM faqs WHERE workspace_id = ?", (int(workspace_id),))
        cursor.execute("DELETE FROM saved_media WHERE workspace_id = ?", (int(workspace_id),))
        cursor.execute("DELETE FROM connected_pages WHERE workspace_id = ?", (int(workspace_id),))
        cursor.execute("DELETE FROM whatsapp_accounts WHERE workspace_id = ?", (int(workspace_id),))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB delete_workspace Error]: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_workspace_by_page_id(page_id: str) -> Optional[dict]:
    """Finds the workspace associated with a specific Facebook Page."""
    if not page_id:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT w.*, cp.page_id, cp.page_name, cp.page_access_token, cp.messenger_enabled, cp.comments_enabled
            FROM workspaces w
            JOIN connected_pages cp ON cp.workspace_id = w.id
            WHERE cp.page_id = ?
            LIMIT 1
        """, (str(page_id),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_workspace_by_page_id Error]: {e}")
        return None

def get_workspace_by_phone_id(phone_number_id: str) -> Optional[dict]:
    """Finds the workspace associated with a specific WhatsApp Business Phone Number ID."""
    if not phone_number_id:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT w.*, wa.phone_number_id, wa.display_phone_number, wa.access_token as wa_access_token,
                   wa.connection_mode, wa.connection_status
            FROM workspaces w
            JOIN whatsapp_accounts wa ON wa.workspace_id = w.id
            WHERE wa.phone_number_id = ?
            LIMIT 1
        """, (str(phone_number_id),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_workspace_by_phone_id Error]: {e}")
        return None

def get_page_ai_config(page_id: str = "", workspace_id: int = None) -> dict:
    """
    Resolves workspace-level AI and shop configuration.
    Strictly uses the workspace's shop details, custom prompt, and delivery fees.
    """
    ws = None
    if workspace_id:
        ws = get_workspace(workspace_id)
    elif page_id:
        ws = get_workspace_by_page_id(page_id)
    
    if not ws:
        ws = get_workspace(1) or {}

    global_settings = get_all_settings(masked=False)

    return {
        "workspace_id": ws.get("id", 1),
        "workspace_name": ws.get("name", "RS Graphics (আরএস গ্রাফিক্স)"),
        "shop_name": ws.get("shop_name") or ws.get("name") or global_settings.get("shop_name", "RS Graphics"),
        "shop_phone": ws.get("shop_phone") or global_settings.get("shop_phone", "01816504097"),
        "shop_address": ws.get("shop_address") or "ঢাকা, বাংলাদেশ",
        "delivery_inside_dhaka": str(ws.get("delivery_inside_dhaka", 70.0)),
        "delivery_outside_dhaka": str(ws.get("delivery_outside_dhaka", 130.0)),
        "ai_system_prompt": ws.get("ai_system_prompt", ""),
        "ai_enabled": bool(ws.get("ai_enabled", 1)),
        "page_id": page_id
    }

# ============================================================
# WEBHOOK DEDUPLICATION & MEDIA DELIVERY IDEMPOTENCY
# ============================================================

def is_webhook_event_processed(channel: str, event_id: str) -> bool:
    """Checks whether a webhook event (by message ID or event ID) has already been processed."""
    if not event_id:
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM processed_webhook_events WHERE channel = ? AND event_id = ?", (channel, str(event_id).strip()))
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        print(f"[DB is_webhook_event_processed Error]: {e}")
        return False

def mark_webhook_event_processed(channel: str, event_id: str, workspace_id: int = 1, page_id_or_phone_id: str = "") -> bool:
    """Records a webhook event ID persistently so duplicate webhooks are ignored."""
    if not event_id:
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO processed_webhook_events (channel, event_id, workspace_id, page_id_or_phone_id)
            VALUES (?, ?, ?, ?)
        """, (channel, str(event_id).strip(), int(workspace_id or 1), str(page_id_or_phone_id or "").strip()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB mark_webhook_event_processed Error]: {e}")
        return False

def record_outbound_ai_message(channel: str, message_id: str, workspace_id: int = 1, page_id_or_phone_id: str = "") -> bool:
    """Records an outgoing AI message ID atomically so incoming echo webhooks are dropped immediately."""
    if not message_id:
        return False
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO processed_webhook_events (channel, event_id, workspace_id, page_id_or_phone_id, direction, sender_role)
            VALUES (?, ?, ?, ?, 'OUTBOUND', 'AI')
        """, (channel, str(message_id).strip(), int(workspace_id or 1), str(page_id_or_phone_id or "").strip()))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB record_outbound_ai_message Error]: {e}")
        return False
    finally:
        if conn:
            conn.close()

def is_outbound_ai_message(channel: str, message_id: str) -> bool:
    """Checks if an event/message ID was sent by our own AI or business account."""
    if not message_id:
        return False
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM processed_webhook_events
            WHERE channel = ? AND event_id = ? AND (direction = 'OUTBOUND' OR sender_role = 'AI')
        """, (channel, str(message_id).strip()))
        row = cursor.fetchone()
        return row is not None
    except Exception as e:
        print(f"[DB is_outbound_ai_message Error]: {e}")
        return False
    finally:
        if conn:
            conn.close()

def claim_webhook_event(channel: str, event_id: str, workspace_id: int = 1, page_id_or_phone_id: str = "", direction: str = "INBOUND", sender_role: str = "CUSTOMER") -> bool:
    """
    Atomically claims a webhook event ID. Returns True ONLY for the first worker that claims it.
    Returns False if the event was already processed or claimed by another worker.
    """
    if not event_id:
        return False
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO processed_webhook_events (channel, event_id, workspace_id, page_id_or_phone_id, direction, sender_role)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (channel, str(event_id).strip(), int(workspace_id or 1), str(page_id_or_phone_id or "").strip(), direction, sender_role))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception as e:
        print(f"[DB claim_webhook_event Error]: {e}")
        return False
    finally:
        if conn:
            conn.close()

def is_own_whatsapp_number(phone_or_id: str) -> bool:
    """Determines if a phone number or ID belongs to our own business WhatsApp account."""
    if not phone_or_id:
        return False
    clean = "".join(c for c in str(phone_or_id) if c.isdigit())
    if not clean:
        return False
    known_own = {
        "4184514263660680", "418451426636680",
        "8801816504097", "01816504097", "1816504097"
    }
    if clean in known_own:
        return True
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT phone_number_id, display_phone_number FROM whatsapp_accounts")
        rows = cursor.fetchall()
        for r in rows:
            p_id = str(r["phone_number_id"] or "").strip()
            d_num = "".join(c for c in str(r["display_phone_number"] or "") if c.isdigit())
            if clean in (p_id, d_num) or (len(clean) >= 10 and (clean in d_num or d_num.endswith(clean))):
                return True
        cursor.execute("SELECT value FROM settings WHERE key IN ('whatsapp_phone_number_id', 'whatsapp_display_phone_number', 'shop_phone')")
        s_rows = cursor.fetchall()
        for sr in s_rows:
            val = "".join(c for c in str(sr["value"] or "") if c.isdigit())
            if val and (clean == val or (len(clean) >= 10 and clean.endswith(val[-10:]))):
                return True
    except Exception as e:
        print(f"[DB is_own_whatsapp_number Error]: {e}")
    finally:
        if conn:
            conn.close()
    return False

_ACTIVE_GENERATION_LOCKS = set()
_GENERATION_LOCK_MUTEX = None

def _get_generation_lock_mutex():
    global _GENERATION_LOCK_MUTEX
    if _GENERATION_LOCK_MUTEX is None:
        import asyncio
        _GENERATION_LOCK_MUTEX = asyncio.Lock()
    return _GENERATION_LOCK_MUTEX

async def acquire_generation_lock(conversation_id: str) -> bool:
    """Acquires an exclusive in-memory generation lock for a conversation. Returns True if acquired, False if already generating."""
    global _ACTIVE_GENERATION_LOCKS
    if not conversation_id:
        return False
    mutex = _get_generation_lock_mutex()
    async with mutex:
        if conversation_id in _ACTIVE_GENERATION_LOCKS:
            print(f"[GENERATION_BLOCKED] conversation_id={conversation_id} reason=already_generating")
            return False
        _ACTIVE_GENERATION_LOCKS.add(conversation_id)
        return True

async def release_generation_lock(conversation_id: str):
    """Releases the exclusive generation lock for a conversation."""
    global _ACTIVE_GENERATION_LOCKS
    if not conversation_id:
        return
    mutex = _get_generation_lock_mutex()
    async with mutex:
        _ACTIVE_GENERATION_LOCKS.discard(conversation_id)

def get_conversation_turn_versions(channel: str, sender_id: str, workspace_id: int = 1) -> dict:
    """Retrieves customer_turn_version and last_responded_turn_version for a conversation."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(customer_turn_version, 1) as customer_turn_version,
                   COALESCE(last_responded_turn_version, 0) as last_responded_turn_version,
                   COALESCE(conversation_version, 1) as conversation_version
            FROM conversations
            WHERE channel = ? AND sender_id = ? AND workspace_id = ?
            ORDER BY id DESC LIMIT 1
        """, (channel, str(sender_id), int(workspace_id or 1)))
        row = cursor.fetchone()
        if row:
            return {
                "customer_turn_version": row["customer_turn_version"],
                "last_responded_turn_version": row["last_responded_turn_version"],
                "conversation_version": row["conversation_version"]
            }
        return {"customer_turn_version": 1, "last_responded_turn_version": 0, "conversation_version": 1}
    except Exception as e:
        print(f"[DB get_conversation_turn_versions Error]: {e}")
        return {"customer_turn_version": 1, "last_responded_turn_version": 0, "conversation_version": 1}
    finally:
        if conn:
            conn.close()

def increment_customer_turn_version(channel: str, sender_id: str, workspace_id: int = 1) -> int:
    """Increments customer_turn_version when a genuine INBOUND CUSTOMER message is recorded."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE conversations
            SET customer_turn_version = COALESCE(customer_turn_version, 1) + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE channel = ? AND sender_id = ? AND workspace_id = ?
        """, (channel, str(sender_id), int(workspace_id or 1)))
        conn.commit()
        cursor.execute("""
            SELECT COALESCE(customer_turn_version, 1) as v
            FROM conversations
            WHERE channel = ? AND sender_id = ? AND workspace_id = ?
            ORDER BY id DESC LIMIT 1
        """, (channel, str(sender_id), int(workspace_id or 1)))
        row = cursor.fetchone()
        return row["v"] if row else 1
    except Exception as e:
        print(f"[DB increment_customer_turn_version Error]: {e}")
        return 1
    finally:
        if conn:
            conn.close()

def mark_turn_responded(channel: str, sender_id: str, turn_version: int, workspace_id: int = 1) -> bool:
    """Sets last_responded_turn_version to prevent repeated generation on the same customer turn."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE conversations
            SET last_responded_turn_version = MAX(COALESCE(last_responded_turn_version, 0), ?),
                updated_at = CURRENT_TIMESTAMP
            WHERE channel = ? AND sender_id = ? AND workspace_id = ?
        """, (int(turn_version), channel, str(sender_id), int(workspace_id or 1)))
        conn.commit()
        return True
    except Exception as e:
        print(f"[DB mark_turn_responded Error]: {e}")
        return False
    finally:
        if conn:
            conn.close()

def get_media_delivery(delivery_key: str) -> Optional[dict]:
    """Fetches a media delivery record by deterministic delivery key."""
    if not delivery_key:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM facebook_media_deliveries WHERE delivery_key = ?", (str(delivery_key).strip(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_media_delivery Error]: {e}")
        return None

def claim_media_delivery(
    delivery_key: str,
    workspace_id: int,
    page_id: str,
    recipient_id: str,
    media_type: str,
    media_url: str,
    media_filename: str,
    media_fingerprint: str,
    batch_id: str = "",
    conversation_id: int = None
) -> Tuple[bool, dict]:
    """
    Atomically claims a media item for delivery.
    Returns:
      (True, record)  -> Worker successfully claimed this media item and MAY proceed to send.
      (False, record) -> Delivery already SENT, UNKNOWN (timeout-blocked), or actively SENDING by another worker.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM facebook_media_deliveries WHERE delivery_key = ?", (delivery_key,))
        existing = cursor.fetchone()
        
        if existing:
            ex_dict = dict(existing)
            status = ex_dict.get("status", "PENDING")
            
            # If already sent in the SAME batch or within 45s (webhook duplicate retry), skip duplicate.
            # If already sent in the SAME batch or within 45s (webhook duplicate retry), skip duplicate.
            # But for a new user turn (>45s later or different batch_id), allow sending!
            if status == "SENT":
                sent_at_str = ex_dict.get("updated_at") or ex_dict.get("created_at")
                existing_batch = ex_dict.get("batch_id")
                is_recent = False
                if sent_at_str:
                    try:
                        sent_dt = datetime.fromisoformat(str(sent_at_str).replace(" ", "T"))
                        if sent_dt.tzinfo is None:
                            sent_dt = sent_dt.replace(tzinfo=timezone.utc)
                        diff = (datetime.now(timezone.utc) - sent_dt).total_seconds()
                        if diff < 45 or (batch_id and existing_batch == batch_id):
                            is_recent = True
                    except Exception:
                        pass
                if is_recent:
                    conn.close()
                    return False, ex_dict
                
            # If UNKNOWN (timed out previously), block immediate retry within 60s
            if status == "UNKNOWN":
                updated_at_str = ex_dict.get("updated_at")
                if updated_at_str:
                    try:
                        updated_dt = datetime.fromisoformat(str(updated_at_str).replace(" ", "T"))
                        if updated_dt.tzinfo is None:
                            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                        diff = (datetime.now(timezone.utc) - updated_dt).total_seconds()
                        if diff < 60:
                            conn.close()
                            return False, ex_dict
                    except Exception:
                        pass
                
            # If currently SENDING, check if lock is fresh (<60s)
            if status == "SENDING":
                updated_at_str = ex_dict.get("updated_at")
                if updated_at_str:
                    try:
                        updated_dt = datetime.fromisoformat(updated_at_str.replace(" ", "T"))
                        if updated_dt.tzinfo is None:
                            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                        diff = (datetime.now(timezone.utc) - updated_dt).total_seconds()
                        if diff < 60:
                            # Another active worker is currently sending this media
                            conn.close()
                            return False, ex_dict
                    except Exception:
                        pass
                        
            # Otherwise claim the item: update to SENDING
            cursor.execute("""
                UPDATE facebook_media_deliveries SET
                    status = 'SENDING',
                    attempt_count = attempt_count + 1,
                    updated_at = CURRENT_TIMESTAMP,
                    batch_id = COALESCE(NULLIF(?, ''), batch_id)
                WHERE delivery_key = ?
            """, (batch_id, delivery_key))
            conn.commit()
            cursor.execute("SELECT * FROM facebook_media_deliveries WHERE delivery_key = ?", (delivery_key,))
            claimed = cursor.fetchone()
            conn.close()
            return True, dict(claimed) if claimed else ex_dict
        else:
            # Insert new record in SENDING state
            cursor.execute("""
                INSERT INTO facebook_media_deliveries (
                    workspace_id, page_id, recipient_id, conversation_id, batch_id,
                    media_type, media_url, media_filename, media_fingerprint, delivery_key,
                    status, attempt_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SENDING', 1, CURRENT_TIMESTAMP)
            """, (
                int(workspace_id or 1),
                str(page_id or "").strip(),
                str(recipient_id or "").strip(),
                conversation_id,
                str(batch_id or "").strip(),
                str(media_type or "image").strip(),
                str(media_url or "").strip(),
                str(media_filename or "").strip(),
                str(media_fingerprint or "").strip(),
                str(delivery_key or "").strip()
            ))
            conn.commit()
            cursor.execute("SELECT * FROM facebook_media_deliveries WHERE delivery_key = ?", (delivery_key,))
            new_row = cursor.fetchone()
            conn.close()
            return True, dict(new_row) if new_row else {}
    except Exception as e:
        print(f"[DB claim_media_delivery Error]: {e}")
        return True, {}

def update_media_delivery_status(
    delivery_key: str,
    status: str,
    meta_message_id: str = None,
    attachment_id: str = None,
    last_error: str = None
) -> bool:
    """Updates the state of a media delivery (SENT, UNKNOWN, FAILED)."""
    if not delivery_key:
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sent_at_clause = ", sent_at = CURRENT_TIMESTAMP" if status == "SENT" else ""
        cursor.execute(f"""
            UPDATE facebook_media_deliveries SET
                status = ?,
                meta_message_id = COALESCE(?, meta_message_id),
                attachment_id = COALESCE(?, attachment_id),
                last_error = ?,
                updated_at = CURRENT_TIMESTAMP
                {sent_at_clause}
            WHERE delivery_key = ?
        """, (status, meta_message_id, attachment_id, last_error, delivery_key))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB update_media_delivery_status Error]: {e}")
        return False


# =========================================================
# Google Integration Database Helpers (Workspace Isolated)
# =========================================================

def get_google_connection(workspace_id: int = 1) -> Optional[dict]:
    """Fetches the Google connection row for the specified workspace."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM google_connections WHERE workspace_id = ?", (int(workspace_id or 1),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_google_connection Error]: {e}")
        return None

def save_google_connection(
    workspace_id: Any = 1,
    google_account_email: str = "",
    access_token_encrypted: str = "",
    refresh_token_encrypted: str = "",
    token_expiry: str = None,
    drive_root_folder_id: str = None,
    master_form_id: str = None,
    master_sheet_id: str = None,
    status: str = "connected"
) -> dict:
    """Inserts or updates the Google connection for a workspace."""
    if isinstance(workspace_id, dict):
        d = workspace_id
        ws_id = int(d.get("workspace_id", 1))
        google_account_email = str(d.get("google_account_email") or d.get("account_email") or "")
        access_token_encrypted = str(d.get("access_token_encrypted") or d.get("access_token") or "")
        refresh_token_encrypted = str(d.get("refresh_token_encrypted") or d.get("refresh_token") or "")
        token_expiry = d.get("token_expiry")
        drive_root_folder_id = d.get("drive_root_folder_id")
        master_form_id = d.get("master_form_id")
        master_sheet_id = d.get("master_sheet_id")
        status = str(d.get("status", "connected"))
    else:
        ws_id = int(workspace_id or 1)
        google_account_email = str(google_account_email or "")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO google_connections (
                workspace_id, google_account_email, access_token_encrypted,
                refresh_token_encrypted, token_expiry, drive_root_folder_id,
                master_form_id, master_sheet_id, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(workspace_id) DO UPDATE SET
                google_account_email = CASE WHEN excluded.google_account_email != '' THEN excluded.google_account_email ELSE google_connections.google_account_email END,
                access_token_encrypted = CASE WHEN excluded.access_token_encrypted != '' THEN excluded.access_token_encrypted ELSE google_connections.access_token_encrypted END,
                refresh_token_encrypted = CASE WHEN excluded.refresh_token_encrypted != '' THEN excluded.refresh_token_encrypted ELSE google_connections.refresh_token_encrypted END,
                token_expiry = COALESCE(excluded.token_expiry, google_connections.token_expiry),
                drive_root_folder_id = COALESCE(excluded.drive_root_folder_id, google_connections.drive_root_folder_id),
                master_form_id = COALESCE(excluded.master_form_id, google_connections.master_form_id),
                master_sheet_id = COALESCE(excluded.master_sheet_id, google_connections.master_sheet_id),
                status = CASE WHEN (excluded.access_token_encrypted != '' OR excluded.refresh_token_encrypted != '' OR google_connections.access_token_encrypted != '' OR google_connections.refresh_token_encrypted != '') THEN 'connected' ELSE excluded.status END,
                updated_at = CURRENT_TIMESTAMP
        """, (
            ws_id,
            google_account_email,
            access_token_encrypted,
            refresh_token_encrypted,
            token_expiry,
            drive_root_folder_id,
            master_form_id,
            master_sheet_id,
            status
        ))
        
        # Backup refresh token & email to settings table
        if refresh_token_encrypted:
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (f"google_refresh_token_ws_{ws_id}", refresh_token_encrypted))
        if google_account_email:
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (f"google_account_email_ws_{ws_id}", google_account_email))
        if master_form_id:
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (f"google_master_form_id_ws_{ws_id}", master_form_id))

        conn.commit()
        cursor.execute("SELECT * FROM google_connections WHERE workspace_id = ?", (ws_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[DB save_google_connection Error]: {e}")
        return {}

def delete_google_connection(workspace_id: int) -> bool:
    """Disconnects and removes Google connection for a workspace."""
    try:
        ws_id = int(workspace_id or 1)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM google_connections WHERE workspace_id = ?", (ws_id,))
        cursor.execute("DELETE FROM settings WHERE key IN (?, ?, ?, ?)", (
            f"google_refresh_token_ws_{ws_id}", f"google_access_token_ws_{ws_id}",
            f"google_account_email_ws_{ws_id}", f"google_master_form_id_ws_{ws_id}"
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB delete_google_connection Error]: {e}")
        return False

def update_google_master_ids(
    workspace_id: int,
    master_form_id: str = None,
    master_sheet_id: str = None,
    drive_root_folder_id: str = None,
    master_form_name: str = None,
    master_form_url: str = None,
    master_edit_url: str = None,
    master_sheet_url: str = None,
    master_has_file_upload: int = None
) -> bool:
    """Updates master form, sheet, or root folder ID and metadata for a workspace."""
    try:
        ws_id = int(workspace_id or 1)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT workspace_id FROM google_connections WHERE workspace_id = ?", (ws_id,))
        if not cursor.fetchone():
            # Check if we have backup email and tokens in settings
            cursor.execute("SELECT value FROM settings WHERE key = ?", (f"google_refresh_token_ws_{ws_id}",))
            r_row = cursor.fetchone()
            b_ref = r_row[0] if r_row else ""
            cursor.execute("SELECT value FROM settings WHERE key = ?", (f"google_account_email_ws_{ws_id}",))
            e_row = cursor.fetchone()
            b_email = e_row[0] if e_row else ""

            cursor.execute("""
                INSERT INTO google_connections (
                    workspace_id, google_account_email, access_token_encrypted, refresh_token_encrypted,
                    status, master_form_id, master_sheet_id, drive_root_folder_id,
                    master_form_name, master_form_url, master_edit_url, master_sheet_url,
                    master_has_file_upload, master_verified_at, updated_at
                ) VALUES (?, ?, '', ?, 'connected', ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (
                ws_id, b_email, b_ref, master_form_id, master_sheet_id, drive_root_folder_id,
                master_form_name, master_form_url, master_edit_url, master_sheet_url,
                master_has_file_upload
            ))
        else:
            cursor.execute("""
                UPDATE google_connections SET
                    master_form_id = COALESCE(?, master_form_id),
                    master_sheet_id = COALESCE(?, master_sheet_id),
                    drive_root_folder_id = COALESCE(?, drive_root_folder_id),
                    master_form_name = COALESCE(?, master_form_name),
                    master_form_url = COALESCE(?, master_form_url),
                    master_edit_url = COALESCE(?, master_edit_url),
                    master_sheet_url = COALESCE(?, master_sheet_url),
                    master_has_file_upload = COALESCE(?, master_has_file_upload),
                    master_verified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE workspace_id = ?
            """, (
                master_form_id, master_sheet_id, drive_root_folder_id,
                master_form_name, master_form_url, master_edit_url,
                master_sheet_url, master_has_file_upload,
                ws_id
            ))
        
        if master_form_id:
            cursor.execute("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (f"google_master_form_id_ws_{ws_id}", master_form_id))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB update_google_master_ids Error]: {e}")
        return False

def save_master_form_template(
    workspace_id: int,
    name: str,
    master_form_id: str,
    form_type: str = "id_card",
    description_template: str = None,
    form_url: str = None,
    edit_url: str = None,
    spreadsheet_id: str = None,
    spreadsheet_url: str = None,
    has_file_upload: int = 1,
    template_id: int = None
) -> dict:
    """Creates or updates a Master Form Template record."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if template_id:
            cursor.execute("""
                UPDATE google_form_templates SET
                    name = ?, form_type = ?, master_form_id = ?,
                    description_template = ?, form_url = ?, edit_url = ?,
                    spreadsheet_id = ?, spreadsheet_url = ?,
                    has_file_upload = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND workspace_id = ?
            """, (
                name, form_type, master_form_id, description_template,
                form_url, edit_url, spreadsheet_id, spreadsheet_url,
                has_file_upload, template_id, int(workspace_id or 1)
            ))
            t_id = template_id
        else:
            cursor.execute("""
                INSERT INTO google_form_templates (
                    workspace_id, name, form_type, master_form_id,
                    description_template, form_url, edit_url,
                    spreadsheet_id, spreadsheet_url, has_file_upload, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                int(workspace_id or 1), name, form_type, master_form_id,
                description_template, form_url, edit_url,
                spreadsheet_id, spreadsheet_url, has_file_upload
            ))
            t_id = cursor.lastrowid
        conn.commit()
        cursor.execute("SELECT * FROM google_form_templates WHERE id = ?", (t_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[DB save_master_form_template Error]: {e}")
        return {}

def get_master_form_templates(workspace_id: int = 1) -> List[dict]:
    """Lists all Master Form Templates for a workspace."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM google_form_templates 
            WHERE workspace_id = ? AND active = 1 
            ORDER BY id DESC
        """, (int(workspace_id or 1),))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB get_master_form_templates Error]: {e}")
        return []

def get_master_form_template_by_id(template_id: int, workspace_id: int = 1) -> Optional[dict]:
    """Fetches a single Master Form Template."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM google_form_templates 
            WHERE id = ? AND workspace_id = ?
        """, (int(template_id), int(workspace_id or 1)))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_master_form_template_by_id Error]: {e}")
        return None

def get_institutions(workspace_id: int = 1) -> List[dict]:
    """Fetches all institutions registered under the workspace."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM institutions WHERE workspace_id = ? ORDER BY id DESC", (int(workspace_id or 1),))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB get_institutions Error]: {e}")
        return []

def get_institution_by_name(workspace_id: int, name: str) -> Optional[dict]:
    """Fetches an institution by name under a specific workspace."""
    if not name:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM institutions WHERE workspace_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?))", (int(workspace_id or 1), name))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_institution_by_name Error]: {e}")
        return None

def get_institution_by_mobile(workspace_id: int, mobile: str) -> Optional[dict]:
    """Fetches an institution by normalized mobile number under a specific workspace."""
    if not mobile:
        return None
    canonical = normalize_bd_mobile(mobile)
    if not canonical:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM institutions 
            WHERE workspace_id = ? AND (normalized_mobile = ? OR phone = ? OR institution_mobile = ?)
            ORDER BY id DESC LIMIT 1
        """, (int(workspace_id or 1), canonical, canonical, canonical))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_institution_by_mobile Error]: {e}")
        return None

def save_institution(
    workspace_id: int,
    name: str,
    phone: str = None,
    institution_mobile: str = None,
    code: str = None,
    contact_person: str = None,
    address: str = None,
    drive_folder_id: str = None,
    active: int = 1,
    institution_id: int = None
) -> dict:
    """Creates or updates an institution record with canonical mobile normalization."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        raw_phone = institution_mobile or phone or ""
        norm_phone = normalize_bd_mobile(raw_phone)
        
        # Check by id, or by mobile, or by name within workspace
        existing = None
        if institution_id:
            cursor.execute("SELECT * FROM institutions WHERE id = ? AND workspace_id = ?", (int(institution_id), int(workspace_id or 1)))
            existing = cursor.fetchone()
        if not existing and norm_phone:
            cursor.execute("""
                SELECT * FROM institutions 
                WHERE workspace_id = ? AND (normalized_mobile = ? OR phone = ? OR institution_mobile = ?)
                LIMIT 1
            """, (int(workspace_id or 1), norm_phone, norm_phone, norm_phone))
            existing = cursor.fetchone()
        if not existing and name:
            cursor.execute("SELECT * FROM institutions WHERE workspace_id = ? AND LOWER(TRIM(name)) = LOWER(TRIM(?)) LIMIT 1", (int(workspace_id or 1), name))
            existing = cursor.fetchone()

        if existing:
            cursor.execute("""
                UPDATE institutions SET
                    name = COALESCE(?, name),
                    code = COALESCE(?, code),
                    contact_person = COALESCE(?, contact_person),
                    phone = COALESCE(?, phone),
                    institution_mobile = COALESCE(?, institution_mobile),
                    normalized_mobile = COALESCE(?, normalized_mobile),
                    address = COALESCE(?, address),
                    drive_folder_id = COALESCE(?, drive_folder_id),
                    active = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                name, code, contact_person, norm_phone or raw_phone,
                norm_phone or raw_phone, norm_phone,
                address, drive_folder_id, active, existing["id"]
            ))
            inst_id = existing["id"]
        else:
            cursor.execute("""
                INSERT INTO institutions (
                    workspace_id, name, code, contact_person, phone, institution_mobile, normalized_mobile, address, drive_folder_id, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                int(workspace_id or 1), name, code, contact_person,
                norm_phone or raw_phone, norm_phone or raw_phone, norm_phone,
                address, drive_folder_id, active
            ))
            inst_id = cursor.lastrowid
        conn.commit()
        cursor.execute("SELECT * FROM institutions WHERE id = ?", (inst_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[DB save_institution Error]: {e}")
        return {}

def get_generated_forms(workspace_id: int = 1) -> List[dict]:
    """Fetches all generated forms for a workspace with institution mobile and stats."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT gf.*, 
                   COALESCE(gf.institution_mobile, inst.normalized_mobile, inst.phone) as institution_phone, 
                   inst.contact_person
            FROM generated_forms gf
            LEFT JOIN institutions inst ON gf.institution_id = inst.id
            WHERE gf.workspace_id = ?
            ORDER BY gf.id DESC
        """, (int(workspace_id or 1),))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB get_generated_forms Error]: {e}")
        return []

def get_generated_form_by_id(form_id: str) -> Optional[dict]:
    """Fetches a generated form by its Google Form ID."""
    if not form_id:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM generated_forms WHERE form_id = ?", (str(form_id).strip(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_generated_form_by_id Error]: {e}")
        return None

def get_generated_forms_by_mobile(workspace_id: int, mobile: str) -> List[dict]:
    """Fetches all generated forms matching an institution mobile number for a workspace."""
    if not mobile:
        return []
    canonical = normalize_bd_mobile(mobile)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT gf.*, 
                   COALESCE(gf.institution_mobile, inst.normalized_mobile, inst.phone) as institution_phone, 
                   inst.contact_person
            FROM generated_forms gf
            LEFT JOIN institutions inst ON gf.institution_id = inst.id
            WHERE gf.workspace_id = ? AND (
                gf.institution_mobile = ? OR 
                inst.normalized_mobile = ? OR 
                inst.phone = ?
            )
            ORDER BY gf.id DESC
        """, (int(workspace_id or 1), canonical, canonical, canonical))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB get_generated_forms_by_mobile Error]: {e}")
        return []

def search_institutions_and_forms_by_mobile(workspace_id: int, mobile: str) -> dict:
    """
    Search workspace-isolated institution and its generated Google Forms by mobile number.
    """
    canonical = normalize_bd_mobile(mobile)
    if not canonical:
        return {"institution": None, "forms": [], "count": 0}
    
    inst = get_institution_by_mobile(workspace_id=workspace_id, mobile=canonical)
    forms = get_generated_forms_by_mobile(workspace_id=workspace_id, mobile=canonical)
    return {
        "institution": inst,
        "forms": forms,
        "count": len(forms)
    }

def get_generated_form_by_institution(workspace_id: int, institution_name: str, institution_mobile: str = None) -> Optional[dict]:
    """Checks if a form already exists for an institution name / mobile under the workspace."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if institution_mobile:
            canonical = normalize_bd_mobile(institution_mobile)
            cursor.execute("""
                SELECT * FROM generated_forms 
                WHERE workspace_id = ? AND (
                    institution_mobile = ? OR 
                    (LOWER(TRIM(institution_name)) = LOWER(TRIM(?)) AND institution_mobile = ?)
                )
                ORDER BY id DESC LIMIT 1
            """, (int(workspace_id or 1), canonical, institution_name, canonical))
            row = cursor.fetchone()
            if row:
                conn.close()
                return dict(row)

        if institution_name:
            cursor.execute("""
                SELECT * FROM generated_forms 
                WHERE workspace_id = ? AND LOWER(TRIM(institution_name)) = LOWER(TRIM(?))
                ORDER BY id DESC LIMIT 1
            """, (int(workspace_id or 1), institution_name))
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None
            
        conn.close()
        return None
    except Exception as e:
        print(f"[DB get_generated_form_by_institution Error]: {e}")
        return None

def save_generated_form(
    workspace_id: int,
    institution_name: str,
    form_id: str,
    form_url: str,
    institution_mobile: str = None,
    responder_uri: str = None,
    edit_url: str = None,
    template_id: int = None,
    institution_id: int = None,
    drive_folder_id: str = None,
    response_destination_id: str = None,
    response_sheet_url: str = None,
    selected_fields: str = None,
    status: str = "active"
) -> dict:
    """Saves or updates a cloned Google Form metadata record with institution mobile identifier."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        norm_mobile = normalize_bd_mobile(institution_mobile) if institution_mobile else None
        cursor.execute("""
            INSERT INTO generated_forms (
                workspace_id, template_id, institution_id, institution_name, institution_mobile,
                form_id, form_url, responder_uri, edit_url, drive_folder_id,
                response_destination_id, response_sheet_url, selected_fields, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(form_id) DO UPDATE SET
                institution_name = excluded.institution_name,
                institution_mobile = COALESCE(excluded.institution_mobile, institution_mobile),
                form_url = excluded.form_url,
                responder_uri = COALESCE(excluded.responder_uri, responder_uri),
                edit_url = COALESCE(excluded.edit_url, edit_url),
                drive_folder_id = COALESCE(excluded.drive_folder_id, drive_folder_id),
                response_destination_id = COALESCE(excluded.response_destination_id, response_destination_id),
                response_sheet_url = COALESCE(excluded.response_sheet_url, response_sheet_url),
                selected_fields = COALESCE(excluded.selected_fields, selected_fields),
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
        """, (
            int(workspace_id or 1),
            int(template_id) if template_id and str(template_id).isdigit() else None,
            int(institution_id) if institution_id and str(institution_id).isdigit() else None,
            str(institution_name or "").strip(),
            norm_mobile,
            str(form_id).strip(),
            str(form_url).strip() if form_url else "",
            str(responder_uri).strip() if responder_uri is not None else None,
            str(edit_url).strip() if edit_url is not None else None,
            str(drive_folder_id).strip() if drive_folder_id is not None else None,
            str(response_destination_id).strip() if response_destination_id is not None else None,
            str(response_sheet_url).strip() if response_sheet_url is not None else None,
            str(selected_fields) if selected_fields is not None else None,
            str(status or "active")
        ))
        conn.commit()
        cursor.execute("SELECT * FROM generated_forms WHERE form_id = ?", (str(form_id).strip(),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[DB save_generated_form Error]: {e}")
        return {}

def update_generated_form_stats(form_id: str, submission_count: int, last_synced_at: str = None) -> bool:
    """Updates the submission counter and sync timestamp for a generated form."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE generated_forms SET
                submission_count = ?,
                last_synced_at = COALESCE(?, CURRENT_TIMESTAMP),
                updated_at = CURRENT_TIMESTAMP
            WHERE form_id = ?
        """, (int(submission_count), last_synced_at, str(form_id).strip()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB update_generated_form_stats Error]: {e}")
        return False

def get_google_form_fields(workspace_id: int = 1, template_id: int = None) -> List[dict]:
    """Fetches configured form fields for a workspace / template, seeding defaults if none exist."""
    seed_default_form_fields_if_needed(workspace_id=workspace_id, template_id=template_id)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if template_id:
            cursor.execute("""
                SELECT * FROM google_form_fields 
                WHERE workspace_id = ? AND (template_id = ? OR template_id IS NULL)
                ORDER BY sort_order ASC, id ASC
            """, (int(workspace_id or 1), int(template_id)))
        else:
            cursor.execute("""
                SELECT * FROM google_form_fields 
                WHERE workspace_id = ? 
                ORDER BY sort_order ASC, id ASC
            """, (int(workspace_id or 1),))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB get_google_form_fields Error]: {e}")
        return []

def seed_default_form_fields_if_needed(workspace_id: int = 1, template_id: int = None):
    """Seeds standard ID Card form questions if the workspace has no fields configured."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM google_form_fields WHERE workspace_id = ?", (int(workspace_id or 1),))
        count = cursor.fetchone()["cnt"]
        if count == 0:
            default_fields = [
                ("student_name", "শিক্ষার্থীর নাম (Student Name)", "short_answer", 1, 1, "[]"),
                ("father_name", "পিতার নাম (Father's Name)", "short_answer", 1, 2, "[]"),
                ("mother_name", "মাতার নাম (Mother's Name)", "short_answer", 0, 3, "[]"),
                ("student_class", "শ্রেণি / জামাত (Class)", "short_answer", 1, 4, "[]"),
                ("student_section", "শাখা (Section)", "short_answer", 0, 5, "[]"),
                ("student_roll", "রোল নম্বর (Roll No)", "short_answer", 1, 6, "[]"),
                ("student_id", "আইডি নম্বর (Student ID)", "short_answer", 0, 7, "[]"),
                ("date_of_birth", "জন্মতারিখ (Date of Birth)", "date", 0, 8, "[]"),
                ("blood_group", "রক্তের গ্রুপ (Blood Group)", "dropdown", 0, 9, json.dumps(["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"], ensure_ascii=False)),
                ("guardian_phone", "অভিভাবকের মোবাইল নম্বর (Phone)", "short_answer", 1, 10, "[]"),
                ("address", "পূর্ণাঙ্গ ঠিকানা (Address)", "paragraph", 1, 11, "[]"),
                ("student_photo", "শিক্ষার্থীর পাসপোর্ট সাইজ ছবি আপলোড (Photo Upload)", "file_upload", 1, 12, "[]")
            ]
            for key, label, ftype, req, order, opts in default_fields:
                cursor.execute("""
                    INSERT INTO google_form_fields (
                        workspace_id, template_id, field_key, field_label, field_type, required, sort_order, options_json, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """, (int(workspace_id or 1), template_id, key, label, ftype, req, order, opts))
            conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB seed_default_form_fields_if_needed Error]: {e}")

def save_google_form_field(
    workspace_id: int,
    field_key: str,
    field_label: str,
    field_type: str,
    required: int = 1,
    sort_order: int = 0,
    options_json: str = "[]",
    template_id: int = None,
    field_id: int = None
) -> dict:
    """Inserts or updates a form field."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if field_id:
            cursor.execute("""
                UPDATE google_form_fields SET
                    field_key = ?, field_label = ?, field_type = ?,
                    required = ?, sort_order = ?, options_json = ?
                WHERE id = ? AND workspace_id = ?
            """, (field_key, field_label, field_type, required, sort_order, options_json, field_id, int(workspace_id or 1)))
            f_id = field_id
        else:
            cursor.execute("""
                INSERT INTO google_form_fields (
                    workspace_id, template_id, field_key, field_label, field_type, required, sort_order, options_json, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (int(workspace_id or 1), template_id, field_key, field_label, field_type, required, sort_order, options_json))
            f_id = cursor.lastrowid
        conn.commit()
        cursor.execute("SELECT * FROM google_form_fields WHERE id = ?", (f_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[DB save_google_form_field Error]: {e}")
        return {}

def delete_google_form_field(field_id: int, workspace_id: int = 1) -> bool:
    """Deletes a form field."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM google_form_fields WHERE id = ? AND workspace_id = ?", (field_id, int(workspace_id or 1)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB delete_google_form_field Error]: {e}")
        return False

def save_form_submission(
    workspace_id: int,
    generated_form_id: int,
    form_id: str,
    response_id: str,
    raw_response_json: str,
    student_name: str = None,
    student_roll: str = None,
    student_class: str = None,
    student_phone: str = None,
    submission_timestamp: str = None,
    customer_id: int = None
) -> Tuple[bool, dict]:
    """
    Saves a form submission with idempotent deduplication.
    Returns (is_new, record_dict).
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM google_form_submissions 
            WHERE form_id = ? AND response_id = ?
        """, (str(form_id).strip(), str(response_id).strip()))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return False, dict(existing)

        cursor.execute("""
            INSERT INTO google_form_submissions (
                workspace_id, generated_form_id, form_id, response_id, customer_id,
                student_name, student_roll, student_class, student_phone,
                submission_timestamp, raw_response_json, processed, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, 1, CURRENT_TIMESTAMP)
        """, (
            int(workspace_id or 1),
            int(generated_form_id),
            str(form_id).strip(),
            str(response_id).strip(),
            customer_id,
            student_name,
            student_roll,
            student_class,
            student_phone,
            submission_timestamp,
            raw_response_json
        ))
        sub_id = cursor.lastrowid
        conn.commit()
        cursor.execute("SELECT * FROM google_form_submissions WHERE id = ?", (sub_id,))
        row = cursor.fetchone()
        conn.close()
        return True, dict(row) if row else {}
    except Exception as e:
        print(f"[DB save_form_submission Error]: {e}")
        return False, {}

def get_form_submissions(form_id: str, workspace_id: int = 1) -> List[dict]:
    """Fetches all submissions for a generated form with uploaded photo URLs."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.*, uf.drive_url as photo_drive_url, uf.thumbnail_url as photo_thumbnail_url, uf.file_name as photo_file_name
            FROM google_form_submissions s
            LEFT JOIN google_uploaded_files uf ON s.generated_form_id = uf.generated_form_id AND s.response_id = uf.response_id
            WHERE s.workspace_id = ? AND s.form_id = ?
            ORDER BY s.id DESC
        """, (int(workspace_id or 1), str(form_id).strip()))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[DB get_form_submissions Error]: {e}")
        return []

def save_uploaded_file(
    workspace_id: int,
    generated_form_id: int,
    response_id: str,
    file_id: str,
    file_name: str = None,
    drive_url: str = None,
    mime_type: str = None,
    thumbnail_url: str = None,
    field_key: str = "student_photo"
) -> dict:
    """Saves metadata for a photo uploaded through the form."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO google_uploaded_files (
                workspace_id, generated_form_id, response_id, field_key,
                file_id, file_name, drive_url, mime_type, thumbnail_url, processed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            int(workspace_id or 1),
            int(generated_form_id),
            str(response_id).strip(),
            field_key,
            str(file_id).strip(),
            file_name,
            drive_url,
            mime_type,
            thumbnail_url
        ))
        conn.commit()
        u_id = cursor.lastrowid
        cursor.execute("SELECT * FROM google_uploaded_files WHERE id = ?", (u_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[DB save_uploaded_file Error]: {e}")
        return {}

