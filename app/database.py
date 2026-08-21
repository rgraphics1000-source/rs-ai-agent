import os
import sqlite3
import json
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone
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
        workspace_id INTEGER DEFAULT 1,
        channel TEXT NOT NULL, -- 'facebook', 'whatsapp', 'web_playground'
        sender_id TEXT NOT NULL,
        customer_name TEXT,
        last_message TEXT,
        human_takeover INTEGER DEFAULT 0,
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
        "shop_address": "ঢাকা, বাংলাদেশ",
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

    # Migration: update shop name & phone if default
    cursor.execute("UPDATE settings SET value = 'RS Graphics (আরএস গ্রাফিক্স)' WHERE key = 'shop_name' AND (value = 'আমার ই-কমার্স শপ' OR value = '')")
    cursor.execute("UPDATE settings SET value = '01816504097' WHERE key = 'shop_phone' AND (value = '01700000000' OR value = '')")

    # Migration: update any stale 17-digit config_id to official 16-digit ID
    cursor.execute("UPDATE settings SET value = '1003403176086013' WHERE key = 'meta_embedded_signup_config_id' AND value = '10034031760860138'")
    # Migration: clear unrelated phone number ID 1265595526643418 so only verified target ID is stored
    cursor.execute("UPDATE settings SET value = '' WHERE key = 'whatsapp_phone_number_id' AND value = '1265595526643418'")

    # Migration: update sample photos and honorific training rules
    cursor.execute(
        "UPDATE ai_training_rules SET title = ?, response_or_rule = ? WHERE id = 25 OR title LIKE '%ভাইয়া%' OR title LIKE '%আপু%' OR title LIKE '%সম্বোধন%'",
        ("কাস্টমারের নাম দেখে স্যার/ম্যাম সম্বোধন", "কাস্টমার পুরুষ হলে 'স্যার' এবং মহিলা হলে 'ম্যাম' সম্বোধন করবে। কখনোই 'ভাইয়া' বা 'আপু' বলবে না।")
    )
    cursor.execute(
        "UPDATE ai_training_rules SET response_or_rule = ? WHERE title LIKE '%স্যাম্পল%'",
        ("কাস্টমার ছবি বা স্যাম্পল দেখতে চাইলে কালবিলম্ব না করে সরাসরি বলবে জি স্যার/ম্যাম, অবশ্যই দিচ্ছি। নিচে আমাদের আকর্ষণীয় স্যাম্পল ছবিগুলো পাঠানো হলো। এবং সাথে সাথে সবগুলো স্যাম্পল ছবি পাঠাবে।",)
    )
    cursor.execute("""
        INSERT OR REPLACE INTO ai_training_rules (id, workspace_id, title, category, question_or_trigger, response_or_rule, is_active)
        VALUES (
            120, 1, 'প্যাকেজের ছবি চাওয়ার নিয়ম', 'Protocol', 'প্যাকেজের ছবি',
            'কাস্টমার প্যাকেজ বা কম্বো প্যাকেজের ছবি চাইলে টেক্সটে কোনো লম্বা প্যাকেজ লিস্ট দেবে না। শুধুমাত্র বলবে ''জি স্যার/ম্যাম, অবশ্যই দিচ্ছি।'' এবং প্যাকেজের ৭টি ছবি পাঠাবে। সব ছবি পাঠানো শেষ হলে স্বয়ংক্রিয়ভাবে বলবে ''আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন স্যার/ম্যাম।''',
            1
        )
    """)

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

    # Automatically purge demo/test workspaces created during previous test sessions
    try:
        cursor.execute("DELETE FROM workspaces WHERE id != 1 AND (name LIKE '%SmartTech%' OR name LIKE '%Test Shop%' OR name LIKE '%Audit Shop%' OR name LIKE '%Smart Accessories%' OR name LIKE '%Page 2%')")
        cursor.execute("DELETE FROM ai_training_rules WHERE workspace_id != 1 OR title LIKE 'Unique RS Rule%' OR title LIKE 'Unique Gadget Rule%'")
        cursor.execute("DELETE FROM products WHERE workspace_id != 1")
        cursor.execute("DELETE FROM faqs WHERE workspace_id != 1")
        cursor.execute("DELETE FROM saved_media WHERE workspace_id != 1")
        cursor.execute("DELETE FROM connected_pages WHERE workspace_id != 1 AND (page_name LIKE '%SmartTech%' OR page_name LIKE '%Test%' OR page_name LIKE '%Audit%')")
        cursor.execute("DELETE FROM whatsapp_accounts WHERE workspace_id != 1 AND (display_phone_number LIKE '%0002%' OR phone_number_id LIKE '%202%')")
    except Exception as e:
        print(f"[Purge Demo Workspaces Warning]: {e}")

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
        ("ন্যূনতম অর্ডার পরিমাণ (MOQ)", "আমাদের ন্যূনতম অর্ডার পরিমাণ ২০ পিস। ২০ পিসের কম কোনো অর্ডার নেওয়া হচ্ছে না।", "instruction", "কত পিস অর্ডার নেওয়া হয়?", "Pricing & MOQ", 1),
        ("ক্যাশ অন ডেলিভারি ও ডেলিভারি চার্জ", "ঢাকার ভেতরে ডেলিভারি চার্জ ৭০ টাকা এবং ঢাকার বাইরে ১৩০ টাকা। সারা বাংলাদেশে ক্যাশ অন ডেলিভারি সুবিধা রয়েছে।", "qa", "ডেলিভারি চার্জ কত?", "Delivery & Payment", 1),
        ("ইউভি প্রিন্ট কোয়ালিটি", "আমরা জাপানি মেশিনের অরজিনাল UV কালার প্রিন্ট করি, যা ১০০% ওয়াটারপ্রুফ, প্রিমিয়াম ফিনিশিং এবং দীর্ঘস্থায়ী।", "qa", "কোয়ালিটি কেমন?", "Product Quality", 1),
        ("ডিসকাউন্ট পলিসি ও বাল্ক অর্ডার", "প্রথমে নিয়মিত বিক্রয়মূল্য বলবে। কাস্টমার ৫০ বা ১০০+ পিস চাইলে বা দাম বেশি বললে স্পেশাল হোলসেল রেট অফার করবে।", "price_policy", "ডিসকাউন্ট বা কম রাখা যাবে?", "Price Policy", 1),
        ("ক্রয়মূল্য গোপন রাখা", "কাস্টমারকে কখনো আমাদের নিজস্ব উৎপাদন বা ক্রয়মূল্য বলা যাবে না। সর্বদা নির্ধারিত বিক্রয়মূল্য বলতে হবে।", "instruction", "", "Business Policy", 1),
        ("ছবি ও স্যাম্পল পাঠানোর নিয়ম", "কাস্টমার ছবি বা স্যাম্পল দেখতে চাইলে কালবিলম্ব না করে সরাসরি বলবে জি স্যার/ম্যাম, অবশ্যই দিচ্ছি। নিচে আমাদের আকর্ষণীয় স্যাম্পল ছবিগুলো পাঠানো হলো। এবং সাথে সাথে সবগুলো স্যাম্পল ছবি পাঠাবে।", "instruction", "ছবি দেখান", "Sales Protocol", 1),
        ("প্যাকেজের ছবি চাওয়ার নিয়ম", "কাস্টমার প্যাকেজ বা কম্বো প্যাকেজের ছবি চাইলে টেক্সটে কোনো লম্বা প্যাকেজ লিস্ট দেবে না। শুধুমাত্র বলবে 'জি স্যার/ম্যাম, অবশ্যই দিচ্ছি।' এবং প্যাকেজের ৭টি ছবি পাঠাবে। সব ছবি পাঠানো শেষ হলে স্বয়ংক্রিয়ভাবে বলবে 'আপনার কোন প্যাকেজটি পছন্দ হয় জানাবেন স্যার/ম্যাম।'", "instruction", "প্যাকেজের ছবি", "Sales Protocol", 1),
        ("গ্রুপভিত্তিক বা একসাথে ছবি ফরওয়ার্ড করা", "একটা একটা করে ছবি পাঠিয়ে কাস্টমারকে বিরক্ত করা যাবে না। একই ক্যাটাগরির সব ছবি একবারে সুন্দরভাবে পাঠাতে হবে।", "instruction", "", "Sales Protocol", 1),
        ("হিউম্যান টেকওভার ও এআই নিস্তব্ধতা", "বিজনেস ওনার বা এজেন্ট চ্যাটে কথা বলা শুরু করলে এআই সম্পূর্ণ নীরব থাকবে এবং কোনো স্বয়ংক্রিয় উত্তর দেবে না।", "instruction", "", "System Protocol", 1),
        ("ভদ্রতা ও নম্র ভাষা প্রয়োগ", "যেকোনো পরিস্থিতিতে কাস্টমারের সাথে অত্যন্ত নম্র, প্রফেশনাল ও সম্মানজনক ভাষা বজায় রাখতে হবে।", "instruction", "", "Tone & Etiquette", 1),
        ("কাস্টমারের নাম দেখে স্যার/ম্যাম সম্বোধন", "কাস্টমার পুরুষ হলে 'স্যার' এবং মহিলা হলে 'ম্যাম' সম্বোধন করবে। কখনোই 'ভাইয়া' বা 'আপু' বলবে না।", "instruction", "", "Tone & Etiquette", 1),
        ("সংক্ষিপ্ত ও টু-দ্য-পয়েন্ট উত্তর", "কাস্টমার যতটুকু প্রশ্ন করবে শুধু ততটুকুর উত্তর দেবে। অতিরিক্ত বড় কথা বা অপ্রয়োজনীয় ব্যাখ্যা দেবে না।", "instruction", "", "Communication", 1),
        ("মানবসদৃশ কথোপকথন ও পরিচয় গোপন", "কাস্টমার যেন কোনোভাবেই বুঝতে না পারে তুমি এআই বা রোবট। একজন বাস্তব অভিজ্ঞ ও অমায়িক ব্যবসায়ীর মতো কথা বলবে।", "instruction", "", "Persona", 1),
        ("অজানা বিষয়ের উত্তর বানিয়ে না বলা", "যে তথ্য জানা নেই সে বিষয়ে বানিয়ে কোনো উত্তর দেবে না। বলবে: 'জি স্যার/ম্যাম, এই বিষয়টি জেনে আমাদের টিম আপনাকে খুব দ্রুত জানাচ্ছে।'", "instruction", "", "Anti-Hallucination", 1),
        ("পূর্ববর্তী ওনার চ্যাট হিস্ট্রিতে নম্র আচরণ", "যেসব কাস্টমারের সাথে ওনার আগে কথা বলেছেন, তাদের সাথে নিজে থেকে কোনো আগ বাড়িয়ে সেলস অফার না দিয়ে প্রয়োজনে বলবে: আপনার মেসেজটি পেয়েছি, আমাদের প্রতিনিধি দ্রুতই যোগাযোগ করছেন।", "instruction", "", "Customer Handling", 1),
        ("মিডিয়া অপশন সংযোজন (ভয়েস ও ভিডিও)", "কাস্টমার ভিডিও বা ভয়েস চাইলে সিস্টেমে সংরক্ষিত প্রিমিয়াম ডেমো ভিডিও ও ভয়েস ক্লিপ পাঠাবে।", "instruction", "", "Media", 1)
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
            INSERT INTO products (name, code, description, price, discount_price, stock, category, image_url, gallery_images, tags, is_active, workspace_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
        """, real_products)
    else:
        # Update existing PKG-COMBO with exact structured variation prices
        cursor.execute("UPDATE products SET gallery_images = ?, description = ?, workspace_id = 1 WHERE code = 'PKG-COMBO'", (
            json.dumps(pkg_variations),
            'জাপানি UV প্রিন্ট কার্ড + ডিজিটাল প্রিন্ট ফিতা + কভার। প্যাকেজ ০১ (৭০৳), প্যাকেজ ০২ (৭০৳), প্যাকেজ ০৩ (৮৩৳), প্যাকেজ ০৭ (৯১৳), প্যাকেজ ০৪ (৭৫৳), প্যাকেজ ০৫ (৮০৳), প্যাকেজ ০৬ (৮৫৳)। (১০০+ অর্ডারে স্পেশাল রেট)'
        ))
        if id_card_imgs:
            cursor.execute("UPDATE products SET gallery_images = ?, workspace_id = 1 WHERE code = 'IDC-01'", (json.dumps(id_card_imgs),))
        if fita_imgs:
            cursor.execute("UPDATE products SET gallery_images = ?, workspace_id = 1 WHERE code = 'FITA-02'", (json.dumps(fita_imgs),))
        if cover_imgs:
            cursor.execute("UPDATE products SET gallery_images = ?, workspace_id = 1 WHERE code = 'COV-03'", (json.dumps(cover_imgs),))

    # Ensure all primary products belong to Workspace 1
    cursor.execute("UPDATE products SET workspace_id = 1 WHERE workspace_id IS NULL OR workspace_id = 0")

    # Clean up old demo products if present
    cursor.execute("DELETE FROM products WHERE code IN ('PJ-101', 'TP-202', 'CB-303')")
    
    conn.commit()
    conn.close()

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
# SAVED MEDIA LIBRARY HELPERS (VOICE NOTES & VIDEOS)
# ============================================================

def get_saved_media(media_type: str = None, workspace_id: Optional[int] = None) -> list:
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM saved_media WHERE 1=1"
    params = []
    if media_type:
        query += " AND media_type = ?"
        params.append(media_type)
    if workspace_id is not None:
        query += " AND workspace_id = ?"
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
    
    if not page_id or not page_token:
        raise ValueError("page_id and page_access_token are required")

    conn = get_db_connection()
    cursor = conn.cursor()

    # If no workspace_id provided, look up or create workspace for this page
    if not workspace_id:
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
    
    cursor.execute("SELECT id FROM connected_pages WHERE page_id = ?", (page_id,))
    existing = cursor.fetchone()
    
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
            
            # If already sent, skip immediately
            if status == "SENT":
                conn.close()
                return False, ex_dict
                
            # If UNKNOWN (timed out previously), block immediate duplicate retry
            if status == "UNKNOWN":
                conn.close()
                return False, ex_dict
                
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
    workspace_id: int,
    google_account_email: str,
    access_token_encrypted: str = "",
    refresh_token_encrypted: str = "",
    token_expiry: str = None,
    drive_root_folder_id: str = None,
    master_form_id: str = None,
    master_sheet_id: str = None,
    status: str = "connected"
) -> dict:
    """Inserts or updates the Google connection for a workspace."""
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
                google_account_email = excluded.google_account_email,
                access_token_encrypted = CASE WHEN excluded.access_token_encrypted != '' THEN excluded.access_token_encrypted ELSE access_token_encrypted END,
                refresh_token_encrypted = CASE WHEN excluded.refresh_token_encrypted != '' THEN excluded.refresh_token_encrypted ELSE refresh_token_encrypted END,
                token_expiry = COALESCE(excluded.token_expiry, token_expiry),
                drive_root_folder_id = COALESCE(excluded.drive_root_folder_id, drive_root_folder_id),
                master_form_id = COALESCE(excluded.master_form_id, master_form_id),
                master_sheet_id = COALESCE(excluded.master_sheet_id, master_sheet_id),
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
        """, (
            int(workspace_id or 1),
            google_account_email,
            access_token_encrypted,
            refresh_token_encrypted,
            token_expiry,
            drive_root_folder_id,
            master_form_id,
            master_sheet_id,
            status
        ))
        conn.commit()
        cursor.execute("SELECT * FROM google_connections WHERE workspace_id = ?", (int(workspace_id or 1),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception as e:
        print(f"[DB save_google_connection Error]: {e}")
        return {}

def delete_google_connection(workspace_id: int) -> bool:
    """Disconnects and removes Google connection for a workspace."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM google_connections WHERE workspace_id = ?", (int(workspace_id or 1),))
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
        conn = get_db_connection()
        cursor = conn.cursor()
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
            int(workspace_id or 1)
        ))
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

def save_institution(
    workspace_id: int,
    name: str,
    code: str = None,
    contact_person: str = None,
    phone: str = None,
    address: str = None,
    drive_folder_id: str = None,
    active: int = 1
) -> dict:
    """Creates or updates an institution record."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        existing = get_institution_by_name(workspace_id, name)
        if existing:
            cursor.execute("""
                UPDATE institutions SET
                    code = COALESCE(?, code),
                    contact_person = COALESCE(?, contact_person),
                    phone = COALESCE(?, phone),
                    address = COALESCE(?, address),
                    drive_folder_id = COALESCE(?, drive_folder_id),
                    active = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (code, contact_person, phone, address, drive_folder_id, active, existing["id"]))
            inst_id = existing["id"]
        else:
            cursor.execute("""
                INSERT INTO institutions (
                    workspace_id, name, code, contact_person, phone, address, drive_folder_id, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (int(workspace_id or 1), name, code, contact_person, phone, address, drive_folder_id, active))
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
    """Fetches all generated forms for a workspace."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT gf.*, inst.phone as institution_phone, inst.contact_person
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

def get_generated_form_by_institution(workspace_id: int, institution_name: str) -> Optional[dict]:
    """Checks if a form already exists for an institution under the workspace."""
    if not institution_name:
        return None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM generated_forms 
            WHERE workspace_id = ? AND LOWER(TRIM(institution_name)) = LOWER(TRIM(?))
            ORDER BY id DESC LIMIT 1
        """, (int(workspace_id or 1), institution_name))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"[DB get_generated_form_by_institution Error]: {e}")
        return None

def save_generated_form(
    workspace_id: int,
    institution_name: str,
    form_id: str,
    form_url: str,
    responder_uri: str = None,
    edit_url: str = None,
    template_id: int = None,
    institution_id: int = None,
    drive_folder_id: str = None,
    response_destination_id: str = None,
    response_sheet_url: str = None,
    status: str = "active"
) -> dict:
    """Saves or updates a cloned Google Form metadata record."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO generated_forms (
                workspace_id, template_id, institution_id, institution_name,
                form_id, form_url, responder_uri, edit_url, drive_folder_id,
                response_destination_id, response_sheet_url, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(form_id) DO UPDATE SET
                institution_name = excluded.institution_name,
                form_url = excluded.form_url,
                responder_uri = COALESCE(excluded.responder_uri, responder_uri),
                edit_url = COALESCE(excluded.edit_url, edit_url),
                drive_folder_id = COALESCE(excluded.drive_folder_id, drive_folder_id),
                response_destination_id = COALESCE(excluded.response_destination_id, response_destination_id),
                response_sheet_url = COALESCE(excluded.response_sheet_url, response_sheet_url),
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
        """, (
            int(workspace_id or 1),
            template_id,
            institution_id,
            institution_name,
            str(form_id).strip(),
            str(form_url).strip(),
            responder_uri,
            edit_url,
            drive_folder_id,
            response_destination_id,
            response_sheet_url,
            status
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

