import os
import json
import re
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel

from app.database import get_db_connection
from app.nikash_integration.nikash_tools import (
    get_nikash_sales_summary,
    get_nikash_customer_ledger,
    get_nikash_inventory_stock,
    parse_financial_sms_ai,
    record_nikash_expense_ai
)

nikash_router = APIRouter(prefix="/api/nikash", tags=["Nikash AI ERP Integration"])

# ==========================================
# PYDANTIC MODELS
# ==========================================
class CopilotChatRequest(BaseModel):
    message: str
    workspace_id: Optional[int] = 1
    context: Optional[Dict[str, Any]] = None

class ProductSyncItem(BaseModel):
    id: Optional[Any] = None
    name: str
    code: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    price: Optional[float] = None
    sellPrice: Optional[float] = None
    buyPrice: Optional[float] = None
    discount_price: Optional[float] = None
    stock: Optional[int] = 10
    category: Optional[str] = "General"
    brand: Optional[str] = ""
    size: Optional[str] = ""
    color: Optional[str] = ""
    description: Optional[str] = ""
    image_url: Optional[str] = None
    imageUrl: Optional[str] = None

class ProductSyncRequest(BaseModel):
    products: List[ProductSyncItem]
    workspace_id: Optional[int] = 1

class SmsParseRequest(BaseModel):
    sms_text: str
    sender: Optional[str] = ""

class ExpenseCreateRequest(BaseModel):
    title: str
    amount: float
    category: Optional[str] = "General"
    payment_method: Optional[str] = "Cash"
    notes: Optional[str] = ""
    workspace_id: Optional[int] = 1

# ==========================================
# 1. COPILOT CHAT ENDPOINT (Conversational AI)
# ==========================================
@nikash_router.post("/copilot/chat")
async def nikash_copilot_chat(payload: CopilotChatRequest):
    """
    Intelligent conversational assistant for NIKASH accounting, sales, inventory, and SMS.
    Understands Bangla natural language queries and automatically executes the right tool.
    """
    raw_prompt = payload.message.strip()
    if not raw_prompt:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    prompt_lower = raw_prompt.lower()
    ws_id = payload.workspace_id or 1

    # 1. Sales & Revenue queries
    if any(w in prompt_lower for w in ["বিক্রি", "সেলস", "sales", "revenue", "আজকের হিসাব", "গতকালের হিসাব", "কত বিক্রি"]):
        date_filter = "today"
        if "গতকাল" in prompt_lower or "yesterday" in prompt_lower:
            date_filter = "yesterday"
        elif "সপ্তাহ" in prompt_lower or "week" in prompt_lower:
            date_filter = "this_week"
        elif "মাস" in prompt_lower or "month" in prompt_lower:
            date_filter = "this_month"
        elif "সব" in prompt_lower or "all" in prompt_lower:
            date_filter = "all"

        summary = get_nikash_sales_summary(date_filter=date_filter, workspace_id=ws_id)
        return {
            "success": True,
            "intent": "sales_summary",
            "reply": summary["formatted_summary"],
            "data": summary
        }

    # 2. Customer Ledger / Due balance queries
    if any(w in prompt_lower for w in ["বকেয়া", "বাকি", "due", "লেজার", "ledger", "কাস্টমার", "customer"]):
        # Extract potential name or phone
        # Clean query by removing common keywords
        clean_q = re.sub(r"(বকেয়া|বাকি|কত|হিসাব|লেজার|কাস্টমার|এর|সাহেব|ভাই|জানাও|দেখাও)", "", raw_prompt, flags=re.IGNORECASE).strip()
        if clean_q:
            ledger = get_nikash_customer_ledger(clean_q, workspace_id=ws_id)
            return {
                "success": True,
                "intent": "customer_ledger",
                "reply": ledger["formatted_summary"] if ledger.get("found") else ledger["message"],
                "data": ledger
            }

    # 3. Inventory / Stock queries
    if any(w in prompt_lower for w in ["স্টক", "stock", "মজুদ", "ইনভেন্টরি", "inventory", "কয়টা আছে", "কত পিস"]):
        clean_prod = re.sub(r"(স্টক|ইনভেন্টরি|কয়টা আছে|কত পিস|মজুদ|আছে কি|দেখাও|জানাও)", "", raw_prompt, flags=re.IGNORECASE).strip()
        stock_data = get_nikash_inventory_stock(product_query=clean_prod or None, workspace_id=ws_id)
        return {
            "success": True,
            "intent": "inventory_stock",
            "reply": stock_data["formatted_summary"],
            "data": stock_data
        }

    # 4. Financial SMS parsing queries
    if any(w in prompt_lower for w in ["trxid", "bkash", "nagad", "rocket", "টাকা জমা", "ক্যাশ ইন", "cash in", "send money"]):
        sms_res = parse_financial_sms_ai(raw_prompt)
        return {
            "success": True,
            "intent": "sms_parsing",
            "reply": sms_res["formatted_summary"] if sms_res.get("success") else "এসএমএস পার্স করা সম্ভব হয়নি।",
            "data": sms_res
        }

    # 5. Gemini AI Brain Fallback for General / Strategic Business Intelligence
    try:
        from app.config import settings
        from google import genai
        
        api_key = settings.GEMINI_API_KEY
        if api_key:
            client = genai.Client(api_key=api_key)
            sales_info = get_nikash_sales_summary("today", workspace_id=ws_id)
            stock_info = get_nikash_inventory_stock(None, workspace_id=ws_id)

            from app.ai_agent.gemini_brain import get_product_catalog_context
            catalog_text = get_product_catalog_context(workspace_id=ws_id)
            
            sys_prompt = f"""
            তুমি 'নিকাশ এআই' (Nikash AI Business & Sales Copilot), একটি প্রফেশনাল অ্যাকাউন্টিং, পিওএস ও সেলস সহকারী।
            তুমি সবসময় অত্যন্ত বিনয়ী ও স্পষ্ট বাংলায় ব্যবসায়িক দিকনির্দেশনা, হিসাব ও প্রোডাক্ট সেলস উত্তর প্রদান করবে।
            দোকানের বর্তমান তথ্য:
            - আজকের বিক্রয়: {sales_info.get('total_revenue', 0)} ৳ ({sales_info.get('total_orders', 0)} টি অর্ডার)
            - লো স্টক প্রোডাক্ট সংখ্যা: {stock_info.get('low_stock_count', 0)} টি

            {catalog_text}

            সেলস ও প্রোডাক্ট গাইডলাইন:
            - দোকানের যেকোনো প্রোডাক্ট (আইডি কার্ড, ফিতা, কভার, মগ, টি-শার্ট ইত্যাদি) সম্পর্কে জানতে চাইলে ক্যাটালগের বিক্রয় মূল্য (Sell Price) অনুযায়ী তথ্য দেবে।
            - কাস্টমারকে মিষ্টি ভাষায় অর্ডার কনফার্ম করার জন্য প্রয়োজনীয় তথ্য পাঠানোর অনুরোধ জানাবে।
            """
            
            response = client.models.generate_content(
                model=getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash",
                contents=raw_prompt,
                config={"system_instruction": sys_prompt}
            )
            ai_reply = response.text or "দুঃখিত, কোনো উত্তর প্রস্তুত করা যায়নি।"
            return {
                "success": True,
                "intent": "general_copilot",
                "reply": ai_reply,
                "data": {}
            }
    except Exception as e:
        print(f"[Copilot Gemini Exception]: {e}")

    # Default Rule-based Friendly Response
    return {
        "success": True,
        "intent": "general_help",
        "reply": (
            "🤖 **নিকাশ এআই কো-পাইলট সচল আছে!**\n"
            "আপনি আমাকে নিচের যেকোনো তথ্য জানতে চাইতে পারেন:\n"
            "• *'আজকের মোট সেলস ও বিক্রি কত?'*\n"
            "• *'রহিমের বকেয়া বাকি কত আছে?'*\n"
            "• *'কোন কোন প্রডাক্টের স্টক কম আছে?'*\n"
            "• *'বিকাশ/নগদ এসএমএস ট্রানজেকশন ভেরিফাই করো'* ইত্যাদি।"
        ),
        "data": {}
    }

# ==========================================
# 2. INVENTORY & PRODUCT SYNC
# ==========================================
@nikash_router.post("/sync/products")
async def sync_nikash_products(payload: ProductSyncRequest):
    """Syncs product items from NIKASH ERP / POS into AI Agent catalog."""
    conn = get_db_connection()
    cursor = conn.cursor()
    synced_count = 0
    ws_id = payload.workspace_id or 1

    for p in payload.products:
        p_name = (p.name or "").strip()
        if not p_name:
            continue
        
        p_code = str(p.sku or p.code or p.barcode or p.id or f"PROD-{abs(hash(p_name)) % 100000}").strip()
        sell_price = p.sellPrice if p.sellPrice is not None else (p.price if p.price is not None else 0.0)
        disc_price = p.discount_price if p.discount_price is not None else sell_price
        img_url = p.imageUrl or p.image_url
        
        # Build rich description including size, color, brand
        desc_parts = []
        if p.brand: desc_parts.append(f"ব্র্যান্ড: {p.brand}")
        if p.size: desc_parts.append(f"সাইজ: {p.size}")
        if p.color: desc_parts.append(f"কালার: {p.color}")
        if p.description: desc_parts.append(p.description)
        full_desc = " | ".join(desc_parts) if desc_parts else "নিকাশ ইআরপি প্রোডাক্ট"

        stock_qty = p.stock if p.stock is not None else 100

        cursor.execute("""
            INSERT INTO products (
                name, code, price, discount_price, stock, category, description, image_url, workspace_id, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(code) DO UPDATE SET
                name = excluded.name,
                price = excluded.price,
                discount_price = excluded.discount_price,
                stock = excluded.stock,
                category = excluded.category,
                description = excluded.description,
                image_url = COALESCE(excluded.image_url, products.image_url),
                workspace_id = excluded.workspace_id,
                is_active = 1,
                is_active = 1
        """, (
            p_name, p_code, float(sell_price), float(disc_price), int(stock_qty), p.category or "General", full_desc, img_url, ws_id
        ))
        synced_count += 1

    conn.commit()
    conn.close()

    return {
        "success": True,
        "synced_count": synced_count,
        "message": f"{synced_count} টি প্রোডাক্ট সফলভাবে নিকাশ এআই ব্রেইনে সিঙ্ক হয়েছে।"
    }

# ==========================================
# 3. ONLINE ORDERS TO NIKASH POS
# ==========================================
@nikash_router.get("/orders/pending")
async def get_pending_ai_orders(workspace_id: int = Query(1)):
    """Retrieves orders created by AI on Facebook Messenger/WhatsApp ready to be synced to NIKASH POS."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            o.id, o.order_code, o.customer_name, o.customer_phone, o.customer_address,
            o.items_summary, o.items_json, o.subtotal, o.delivery_charge, o.total_amount,
            o.channel, o.status, o.created_at,
            COALESCE(s.synced_to_nikash_pos, 0) as synced_to_pos
        FROM orders o
        LEFT JOIN nikash_synced_orders s ON o.id = s.order_id
        WHERE COALESCE(s.synced_to_nikash_pos, 0) = 0
        ORDER BY o.id DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    orders = [dict(r) for r in rows]
    return {
        "success": True,
        "total_pending": len(orders),
        "orders": orders
    }

@nikash_router.post("/orders/{order_id}/sync-status")
async def update_order_sync_status(order_id: int, request: Request):
    """Marks an online AI order as synced into NIKASH POS."""
    data = await request.json()
    synced = 1 if data.get("synced", True) else 0

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO nikash_synced_orders (order_id, synced_to_nikash_pos, synced_at, notes)
        VALUES (?, ?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(order_id) DO UPDATE SET
            synced_to_nikash_pos = excluded.synced_to_nikash_pos,
            synced_at = CURRENT_TIMESTAMP
    """, (order_id, synced, data.get("notes", "Synced from NIKASH UI")))
    conn.commit()
    conn.close()

    return {"success": True, "message": f"Order {order_id} sync status updated"}

# ==========================================
# 4. FINANCIAL SMS PARSER API
# ==========================================
@nikash_router.post("/sms/parse")
async def api_parse_sms(payload: SmsParseRequest):
    """API endpoint to parse raw incoming financial SMS (bKash/Nagad/Rocket/Bank)."""
    res = parse_financial_sms_ai(payload.sms_text, sender=payload.sender or "")
    return res

# ==========================================
# 5. EXPENSE RECORDING API
# ==========================================
@nikash_router.post("/expenses")
async def api_record_expense(payload: ExpenseCreateRequest):
    """API endpoint to record operational expenses."""
    res = record_nikash_expense_ai(
        title=payload.title,
        amount=payload.amount,
        category=payload.category or "General",
        payment_method=payload.payment_method or "Cash",
        notes=payload.notes or "",
        workspace_id=payload.workspace_id or 1
    )
    return res

# ==========================================
# 6. DASHBOARD AGGREGATED STATS API
# ==========================================
@nikash_router.get("/dashboard/stats")
async def get_nikash_dashboard_stats(workspace_id: int = Query(1)):
    """Returns aggregated high-level business stats for NIKASH AI Dashboard."""
    sales = get_nikash_sales_summary("today", workspace_id=workspace_id)
    stocks = get_nikash_inventory_stock(None, workspace_id=workspace_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(id) as count FROM orders WHERE status = 'Pending'")
    pending_orders_row = cursor.fetchone()
    
    cursor.execute("SELECT COUNT(id) as count FROM nikash_sms_logs WHERE DATE(created_at) = DATE('now')")
    sms_today_row = cursor.fetchone()
    conn.close()

    return {
        "success": True,
        "today_revenue": sales.get("total_revenue", 0.0),
        "today_orders": sales.get("total_orders", 0),
        "pending_online_orders": pending_orders_row["count"] if pending_orders_row else 0,
        "low_stock_items": stocks.get("low_stock_count", 0),
        "sms_parsed_today": sms_today_row["count"] if sms_today_row else 0
    }
