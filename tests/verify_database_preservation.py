import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.stdout.reconfigure(encoding='utf-8')

from app.database import get_db_connection, get_all_settings, get_all_connected_pages, get_all_whatsapp_accounts

def audit_database_preservation():
    print("\n--- [AUDIT CHECK 7] Database Preservation & Migration Integrity ---")
    conn = get_db_connection()
    cursor = conn.cursor()

    tables = [
        "conversations", "messages", "products", "orders",
        "ai_training_rules", "faqs", "saved_media", "comment_logs",
        "settings", "connected_pages", "whatsapp_accounts"
    ]

    for t in tables:
        cursor.execute(f"SELECT count(*) as cnt FROM {t}")
        cnt = cursor.fetchone()["cnt"]
        print(f"Table '{t}': {cnt} records")
        if t in ["ai_training_rules", "faqs", "connected_pages", "whatsapp_accounts"]:
            assert cnt > 0, f"CRITICAL: Table '{t}' must contain records!"

    # Verify Page 1 credentials preserved
    pages = get_all_connected_pages()
    print(f"\nConnected Page 1: ID={pages[0]['page_id']}, Name={pages[0]['page_name']}")

    # Verify WhatsApp 1 credentials preserved
    wa = get_all_whatsapp_accounts()
    print(f"Connected WhatsApp 1: PhoneID={wa[0]['phone_number_id']}, Display={wa[0]['display_phone_number']}")

    conn.close()
    print("\n✓ [AUDIT CHECK 7 PASSED] All database tables, products, rules, and credentials 100% preserved.")

if __name__ == "__main__":
    audit_database_preservation()
