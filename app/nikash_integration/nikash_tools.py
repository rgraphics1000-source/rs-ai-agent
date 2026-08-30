import os
import re
import json
import sqlite3
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
from app.database import get_db_connection

# ==========================================
# 1. NIKASH ERP DATABASE & STORAGE SCHEMA
# ==========================================
def init_nikash_erp_tables():
    """Initializes tables for NIKASH accounting, customer ledger, and synced transactions if not already present."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # NIKASH Customers Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nikash_customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER DEFAULT 1,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        address TEXT,
        total_spent REAL DEFAULT 0.0,
        due_amount REAL DEFAULT 0.0,
        last_purchase_date TIMESTAMP,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # NIKASH Expenses Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nikash_expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER DEFAULT 1,
        title TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'Cash',
        notes TEXT,
        expense_date DATE DEFAULT (DATE('now')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # NIKASH Synced Financial SMS Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nikash_sms_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER DEFAULT 1,
        sender TEXT,
        raw_sms TEXT NOT NULL,
        service_type TEXT, -- 'bkash', 'nagad', 'rocket', 'bank', 'unknown'
        transaction_type TEXT, -- 'cash_in', 'send_money', 'payment', 'received', 'fee'
        amount REAL DEFAULT 0.0,
        trx_id TEXT,
        fee REAL DEFAULT 0.0,
        current_balance REAL DEFAULT 0.0,
        sender_or_acc TEXT,
        parsed_status TEXT DEFAULT 'success',
        synced_to_accounts INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # NIKASH Synced Orders Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS nikash_synced_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER UNIQUE,
        workspace_id INTEGER DEFAULT 1,
        synced_to_nikash_pos INTEGER DEFAULT 0,
        synced_at TIMESTAMP,
        notes TEXT,
        FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()

# Auto-initialize on load
init_nikash_erp_tables()

# ==========================================
# 2. ERP QUERY & REPORTING TOOLS
# ==========================================

def get_nikash_sales_summary(
    date_filter: str = "today",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    workspace_id: int = 1
) -> Dict[str, Any]:
    """
    Retrieves detailed sales figures, total orders, average order value, and top items.
    date_filter options: 'today', 'yesterday', 'this_week', 'this_month', 'all' or custom range.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    week_start_str = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    month_start_str = date.today().replace(day=1).isoformat()

    where_clause = "WHERE 1=1"
    params = []

    if date_filter == "today":
        where_clause += " AND DATE(created_at) = DATE(?)"
        params.append(today_str)
        period_label = f"আজকের হিসাব ({today_str})"
    elif date_filter == "yesterday":
        where_clause += " AND DATE(created_at) = DATE(?)"
        params.append(yesterday_str)
        period_label = f"গতকালের হিসাব ({yesterday_str})"
    elif date_filter == "this_week":
        where_clause += " AND DATE(created_at) >= DATE(?)"
        params.append(week_start_str)
        period_label = f"চলতি সপ্তাহের হিসাব (থেকে {week_start_str})"
    elif date_filter == "this_month":
        where_clause += " AND DATE(created_at) >= DATE(?)"
        params.append(month_start_str)
        period_label = f"চলতি মাসের হিসাব (থেকে {month_start_str})"
    elif start_date and end_date:
        where_clause += " AND DATE(created_at) BETWEEN DATE(?) AND DATE(?)"
        params.extend([start_date, end_date])
        period_label = f"তারিখ অনুযায়ী হিসাব ({start_date} থেকে {end_date})"
    else:
        period_label = "সার্বিক হিসাব (All Time)"

    # Query total sales and orders
    cursor.execute(f"""
        SELECT 
            COUNT(id) as total_orders,
            COALESCE(SUM(total_amount), 0.0) as total_revenue,
            COALESCE(SUM(subtotal), 0.0) as total_subtotal,
            COALESCE(SUM(delivery_charge), 0.0) as total_delivery_charges,
            COALESCE(AVG(total_amount), 0.0) as avg_order_value
        FROM orders
        {where_clause}
    """, params)
    summary_row = cursor.fetchone()

    # Query orders by status
    cursor.execute(f"""
        SELECT status, COUNT(id) as count, COALESCE(SUM(total_amount), 0.0) as amount
        FROM orders
        {where_clause}
        GROUP BY status
    """, params)
    status_breakdown = [dict(r) for r in cursor.fetchall()]

    # Query latest 5 orders
    cursor.execute(f"""
        SELECT order_code, customer_name, customer_phone, total_amount, status, created_at
        FROM orders
        {where_clause}
        ORDER BY id DESC LIMIT 5
    """, params)
    recent_orders = [dict(r) for r in cursor.fetchall()]

    conn.close()

    total_revenue = float(summary_row["total_revenue"]) if summary_row else 0.0
    total_orders = int(summary_row["total_orders"]) if summary_row else 0
    avg_value = float(summary_row["avg_order_value"]) if summary_row else 0.0

    return {
        "success": True,
        "period": period_label,
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "average_order_value": round(avg_value, 2),
        "status_breakdown": status_breakdown,
        "recent_orders": recent_orders,
        "formatted_summary": (
            f"📊 **নিকাশ সেলস রিপোর্ট - {period_label}**:\n"
            f"• মোট বিক্রয়: **{total_revenue:,.2f} ৳**\n"
            f"• মোট অর্ডার সংখ্যা: **{total_orders} টি**\n"
            f"• গড়ে প্রতি অর্ডারের পরিমাণ: **{avg_value:,.2f} ৳**"
        )
    }

def get_nikash_customer_ledger(
    query: str,
    workspace_id: int = 1
) -> Dict[str, Any]:
    """
    Searches customer database by Name or Phone to return due balance, total purchases, and order history.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    clean_query = query.strip()
    clean_phone = re.sub(r"[^\d]", "", clean_query)
    
    # Try exact phone match or fuzzy name match in orders and nikash_customers
    cursor.execute("""
        SELECT * FROM nikash_customers
        WHERE phone LIKE ? OR name LIKE ?
        ORDER BY id DESC LIMIT 1
    """, (f"%{clean_phone if len(clean_phone) >= 6 else clean_query}%", f"%{clean_query}%"))
    customer = cursor.fetchone()

    # Also search customer's orders
    phone_filter = clean_phone if len(clean_phone) >= 6 else ""
    cursor.execute("""
        SELECT order_code, customer_name, customer_phone, customer_address, total_amount, status, created_at
        FROM orders
        WHERE (customer_phone LIKE ? OR customer_name LIKE ?)
        ORDER BY id DESC LIMIT 10
    """, (f"%{phone_filter}%" if phone_filter else f"%{clean_query}%", f"%{clean_query}%"))
    orders = [dict(r) for r in cursor.fetchall()]

    conn.close()

    if not customer and not orders:
        return {
            "success": False,
            "found": False,
            "message": f"'{query}' নামে বা নম্বরে কোনো কাস্টমার রেকর্ড পাওয়া যায়নি।"
        }

    c_name = customer["name"] if customer else (orders[0]["customer_name"] if orders else "কাস্টমার")
    c_phone = customer["phone"] if customer else (orders[0]["customer_phone"] if orders else "নম্বর নেই")
    c_due = float(customer["due_amount"]) if customer else 0.0
    c_total = float(customer["total_spent"]) if customer else sum(float(o["total_amount"]) for o in orders)

    return {
        "success": True,
        "found": True,
        "customer": {
            "name": c_name,
            "phone": c_phone,
            "due_amount": c_due,
            "total_spent": c_total,
            "total_orders": len(orders),
            "recent_orders": orders
        },
        "formatted_summary": (
            f"👤 **কাস্টমার লেজার বিবরণ**:\n"
            f"• নাম: **{c_name}**\n"
            f"• মোবাইল: `{c_phone}`\n"
            f"• বর্তমান বকেয়া: **{c_due:,.2f} ৳**\n"
            f"• মোট ক্রয়: **{c_total:,.2f} ৳** ({len(orders)} টি অর্ডার)"
        )
    }

def get_nikash_inventory_stock(
    product_query: Optional[str] = None,
    workspace_id: int = 1
) -> Dict[str, Any]:
    """
    Checks real-time inventory stock of products in NIKASH. Returns low stock alerts if stock <= 5.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if product_query and product_query.strip():
        q = f"%{product_query.strip()}%"
        cursor.execute("""
            SELECT id, name, code, price, discount_price, stock, category, is_active
            FROM products
            WHERE is_active = 1 AND (name LIKE ? OR code LIKE ? OR category LIKE ?)
            ORDER BY stock ASC
        """, (q, q, q))
    else:
        cursor.execute("""
            SELECT id, name, code, price, discount_price, stock, category, is_active
            FROM products
            WHERE is_active = 1
            ORDER BY stock ASC LIMIT 25
        """)

    rows = cursor.fetchall()
    conn.close()

    items = [dict(r) for r in rows]
    low_stock = [i for i in items if int(i.get("stock") or 0) <= 5]

    return {
        "success": True,
        "total_found": len(items),
        "low_stock_count": len(low_stock),
        "products": items,
        "low_stock_products": low_stock,
        "formatted_summary": (
            f"📦 **স্টক ইনভেন্টরি স্টেটাস**:\n"
            + "\n".join([f"• [{p['code']}] {p['name']}: **{p['stock']} টি** স্টকে আছে (মূল্য: {p['price']}৳)" for p in items[:8]])
            + (f"\n⚠️ **সতর্কতা:** {len(low_stock)} টি প্রোডাক্টের স্টক ৫ বা তার চেয়ে কম!" if low_stock else "")
        )
    }

# ==========================================
# 3. FINANCIAL SMS PARSER (bKash, Nagad, Rocket, Banks)
# ==========================================

def parse_financial_sms_ai(sms_text: str, sender: str = "") -> Dict[str, Any]:
    """
    Parses Bengali & English financial SMS from bKash, Nagad, Rocket, Upay, and major Banks.
    Extracts transaction type, amount, TrxID, Fee, and Balance.
    """
    if not sms_text or not sms_text.strip():
        return {"success": False, "error": "Empty SMS text"}

    text = sms_text.strip()
    result = {
        "service": "unknown",
        "type": "general",
        "amount": 0.0,
        "fee": 0.0,
        "trx_id": "",
        "balance": 0.0,
        "counterpart": "",
        "raw": text
    }

    # 1. Identify Service Provider
    text_lower = text.lower()
    if "bkash" in text_lower or "b-kash" in text_lower or sender.lower() == "bkash":
        result["service"] = "bKash"
    elif "nagad" in text_lower or sender.lower() == "nagad":
        result["service"] = "Nagad"
    elif "rocket" in text_lower or "dbbl" in text_lower or sender.lower() in ["rocket", "16216"]:
        result["service"] = "Rocket"
    elif "upay" in text_lower or sender.lower() == "upay":
        result["service"] = "Upay"
    elif any(b in text_lower for b in ["islami bank", "city bank", "ebl", "brac bank", "dbbl", "scb", "bank"]):
        result["service"] = "Bank"

    # 2. Extract Amount (Tk, Tk., BDT, ৳)
    amount_match = re.search(r"(?:Tk|Tk\.|BDT|৳|Amount:?\s*Tk\.?)\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if amount_match:
        try:
            result["amount"] = float(amount_match.group(1).replace(",", ""))
        except Exception:
            pass

    # 3. Extract TrxID / Transaction ID
    trx_match = re.search(r"(?:TrxID|TxnID|Transaction ID|Trx ID|Ref:?)\s*[:#]?\s*([A-Za-z0-9]+)", text, re.IGNORECASE)
    if trx_match:
        result["trx_id"] = trx_match.group(1).strip()

    # 4. Extract Fee
    fee_match = re.search(r"(?:Fee|Charge)\s*[:]?\s*(?:Tk|BDT|৳)?\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if fee_match:
        try:
            result["fee"] = float(fee_match.group(1).replace(",", ""))
        except Exception:
            pass

    # 5. Extract Current Balance
    bal_match = re.search(r"(?:Balance|Bal|Available Balance)\s*[:]?\s*(?:Tk|BDT|৳)?\s*([\d,]+(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if bal_match:
        try:
            result["balance"] = float(bal_match.group(1).replace(",", ""))
        except Exception:
            pass

    # 6. Extract Transaction Type
    if re.search(r"received|cash in|credited|deposit|inward", text, re.IGNORECASE):
        result["type"] = "cash_in"
    elif re.search(r"send money|transferred|debited|withdrawn|payment|paid", text, re.IGNORECASE):
        result["type"] = "cash_out"
    
    # 7. Extract Counterpart (from/to number or merchant)
    from_match = re.search(r"(?:from|to)\s+([\d\+A-Za-z\s]+?)(?:\.|\s+at|\s+Fee|\s+Balance|\s+TrxID|$)", text, re.IGNORECASE)
    if from_match:
        result["counterpart"] = from_match.group(1).strip()

    # Save to SQLite SMS Log
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO nikash_sms_logs (
                sender, raw_sms, service_type, transaction_type, amount, trx_id, fee, current_balance, sender_or_acc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            sender or result["service"],
            text,
            result["service"],
            result["type"],
            result["amount"],
            result["trx_id"],
            result["fee"],
            result["balance"],
            result["counterpart"]
        ))
        conn.commit()
        conn.close()
    except Exception as db_e:
        print(f"[NIKASH SMS Log Error]: {db_e}")

    return {
        "success": True,
        "data": result,
        "formatted_summary": (
            f"📱 **আর্থিক এসএমএস পার্সিং সফল ({result['service']})**:\n"
            f"• লেনদেনের ধরন: **{'টাকা জমা (Cash In)' if result['type'] == 'cash_in' else 'টাকা প্রদান (Payment/Out)'}**\n"
            f"• পরিমাণ: **{result['amount']:,.2f} ৳**\n"
            f"• TrxID: `{result['trx_id'] or 'পাওয়া যায়নি'}`\n"
            f"• বর্তমান ব্যালেন্স: **{result['balance']:,.2f} ৳**"
        )
    }

# ==========================================
# 4. EXPENSE RECORDING TOOL
# ==========================================

def record_nikash_expense_ai(
    title: str,
    amount: float,
    category: str = "General",
    payment_method: str = "Cash",
    notes: str = "",
    workspace_id: int = 1
) -> Dict[str, Any]:
    """Records an operational expense directly into NIKASH."""
    if amount <= 0:
        return {"success": False, "error": "খরচের পরিমাণ ০ থেকে বেশি হতে হবে।"}

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO nikash_expenses (
            workspace_id, title, category, amount, payment_method, notes
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (int(workspace_id or 1), title.strip(), category.strip(), float(amount), payment_method.strip(), notes.strip()))
    expense_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "success": True,
        "expense_id": expense_id,
        "title": title,
        "amount": amount,
        "category": category,
        "formatted_summary": f"✅ **খরচ সফলভাবে এন্ট্রি হয়েছে!**\n• খাত: **{title}** ({category})\n• পরিমাণ: **{amount:,.2f} ৳** (পদ্ধতি: {payment_method})"
    }
