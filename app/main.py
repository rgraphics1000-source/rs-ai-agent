import os
import json
import csv
import io
import uuid
from typing import Optional
from fastapi import FastAPI, Request, Response, Form, File, UploadFile, Query, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.config import settings
from app.database import (
    init_db, get_db_connection, get_setting, set_setting, get_all_settings
)
from app.ai_agent.gemini_brain import process_customer_message
from app.ai_agent.voice_engine import generate_bangla_voice, list_available_voices
from app.ai_agent.order_engine import list_orders, update_order_status, create_order
from app.channels.facebook import handle_facebook_webhook_event
from app.channels.whatsapp import handle_whatsapp_webhook_event

# Initialize FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="RS Autonomous AI Sales Agent & Order Management Platform"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files and Templates
app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(settings.TEMPLATES_DIR))

# Ensure database tables are created on startup
@app.on_event("startup")
def startup_event():
    init_db()
    print(f"[{settings.PROJECT_NAME}] Database initialized successfully.")

# ==========================================
# 1. FRONTEND DASHBOARD ROUTE
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "shop_name": get_setting("shop_name", settings.SHOP_NAME),
            "version": settings.VERSION
        }
    )

# ==========================================
# 2. OVERVIEW & ANALYTICS STATS API
# ==========================================
@app.get("/api/overview")
async def get_overview_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM orders")
    total_orders = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'Pending'")
    pending_orders = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM orders WHERE status IN ('Confirmed', 'Processing', 'Shipped', 'Delivered')")
    confirmed_orders = cursor.fetchone()[0]

    cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders WHERE status != 'Cancelled'")
    total_revenue = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
    total_products = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM comment_logs")
    total_comments = cursor.fetchone()[0]

    # Recent 5 Orders
    cursor.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 5")
    recent_orders = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "total_orders": total_orders,
        "pending_orders": pending_orders,
        "confirmed_orders": confirmed_orders,
        "total_revenue": round(total_revenue, 2),
        "total_products": total_products,
        "total_comments": total_comments,
        "recent_orders": recent_orders
    }

# ==========================================
# 3. ORDER MANAGEMENT APIS
# ==========================================
@app.get("/api/orders")
async def api_list_orders(status: Optional[str] = None, search: Optional[str] = None):
    orders = list_orders(status=status, search=search)
    return {"orders": orders}

@app.post("/api/orders")
async def api_create_order(
    customer_name: str = Form(...),
    customer_phone: str = Form(...),
    customer_address: str = Form(...),
    items_summary: str = Form(...),
    total_amount: float = Form(...),
    delivery_charge: float = Form(70.0),
    channel: str = Form("manual"),
    notes: Optional[str] = Form("")
):
    items = [{"name": items_summary, "qty": 1, "price": total_amount - delivery_charge}]
    order = create_order(
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_address=customer_address,
        items=items,
        channel=channel,
        notes=notes
    )
    return {"success": True, "order": order}

@app.put("/api/orders/{order_id}/status")
async def api_update_order_status(order_id: int, request: Request):
    body = await request.json()
    new_status = body.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Status is required")
    
    success = update_order_status(order_id, new_status)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid status")
    return {"success": True, "message": f"Order status updated to {new_status}"}

@app.delete("/api/orders/{order_id}")
async def api_delete_order(order_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Order deleted"}

@app.get("/api/orders/export/csv")
async def export_orders_csv():
    orders = list_orders()
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(["Order Code", "Customer Name", "Phone", "Address", "Items", "Subtotal", "Delivery Fee", "Total", "Channel", "Status", "Date"])
    for o in orders:
        writer.writerow([
            o.get("order_code"),
            o.get("customer_name"),
            o.get("customer_phone"),
            o.get("customer_address"),
            o.get("items_summary"),
            o.get("subtotal"),
            o.get("delivery_charge"),
            o.get("total_amount"),
            o.get("channel"),
            o.get("status"),
            o.get("created_at")
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders_export.csv"}
    )

# ==========================================
# 4. PRODUCT CATALOG APIS
# ==========================================
@app.get("/api/products")
async def api_list_products():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products ORDER BY id DESC")
    products = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"products": products}

@app.post("/api/products")
async def api_add_product(
    name: str = Form(...),
    code: str = Form(...),
    price: float = Form(...),
    discount_price: Optional[float] = Form(None),
    stock: int = Form(10),
    category: str = Form("General"),
    description: str = Form(""),
    tags: Optional[str] = Form(""),
    image: Optional[UploadFile] = File(None)
):
    image_url = ""
    if image and image.filename:
        ext = Path(image.filename).suffix
        unique_name = f"prod_{uuid.uuid4().hex[:8]}{ext}"
        save_path = settings.UPLOADS_DIR / unique_name
        contents = await image.read()
        with open(save_path, "wb") as f:
            f.write(contents)
        image_url = f"/static/uploads/{unique_name}"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO products (name, code, price, discount_price, stock, category, description, tags, image_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, code, price, discount_price, stock, category, description, tags, image_url))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Product added successfully"}

@app.delete("/api/products/{product_id}")
async def api_delete_product(product_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Product deleted"}

# ==========================================
# 5. COMMENT AUTOMATION & LOGS APIS
# ==========================================
@app.get("/api/comments/logs")
async def api_comment_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM comment_logs ORDER BY id DESC LIMIT 50")
    logs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"logs": logs}

# ==========================================
# 5.1 TRAIN CONTENT (FAQS & KNOWLEDGE) APIS
# ==========================================
@app.get("/api/faqs")
async def api_list_faqs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM faqs ORDER BY id DESC")
    faqs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"faqs": faqs}

@app.post("/api/faqs")
async def api_add_faq(request: Request):
    data = await request.json()
    q = data.get("question")
    a = data.get("answer")
    cat = data.get("category", "General")
    if not q or not a:
        raise HTTPException(status_code=400, detail="Question and answer required")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO faqs (question, answer, category) VALUES (?, ?, ?)", (q, a, cat))
    conn.commit()
    conn.close()
    return {"success": True, "message": "FAQ added"}

@app.delete("/api/faqs/{faq_id}")
async def api_delete_faq(faq_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM faqs WHERE id = ?", (faq_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "FAQ deleted"}

# ==========================================
# 5.2 OMNICHAT (INBOX) APIS
# ==========================================
@app.get("/api/omnichat/conversations")
async def api_omnichat_conversations():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
    convs = [dict(r) for r in cursor.fetchall()]
    
    # If no conversations in DB, provide demo customer thread
    if not convs:
        cursor.execute("""
            INSERT INTO conversations (channel, sender_id, customer_name, last_message)
            VALUES ('facebook', 'fb_user_101', 'রাহুল হাসান', 'পাঞ্জাবির দাম কত এবং কী কী সাইজ আছে?')
        """)
        cid = cursor.lastrowid
        cursor.execute("""
            INSERT INTO messages (conversation_id, sender_type, content)
            VALUES (?, 'user', 'পাঞ্জাবির দাম কত এবং কী কী সাইজ আছে?')
        """, (cid,))
        cursor.execute("""
            INSERT INTO messages (conversation_id, sender_type, content)
            VALUES (?, 'bot', 'আসসালামু আলাইকুম ভাইয়া! 😊 আমাদের সুতি পাঞ্জাবিটির দাম ১২৫০ টাকা। সাইজ পাবেন ৪০, ৪২, ৪৪।')
        """, (cid,))
        conn.commit()
        cursor.execute("SELECT * FROM conversations ORDER BY updated_at DESC")
        convs = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {"conversations": convs}

@app.get("/api/omnichat/messages/{conversation_id}")
async def api_omnichat_messages(conversation_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,))
    messages = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"messages": messages}

@app.post("/api/omnichat/send")
async def api_omnichat_send(request: Request):
    data = await request.json()
    cid = data.get("conversation_id")
    content = data.get("content")
    if not cid or not content:
        raise HTTPException(status_code=400, detail="Missing conversation_id or content")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (conversation_id, sender_type, content)
        VALUES (?, 'admin', ?)
    """, (cid, content))
    cursor.execute("UPDATE conversations SET last_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (content, cid))
    conn.commit()
    conn.close()
    return {"success": True}

# ==========================================
# 6. SETTINGS & AI CONFIG APIS
# ==========================================
@app.get("/api/settings")
async def api_get_settings():
    all_s = get_all_settings()
    voices = list_available_voices()
    return {"settings": all_s, "voices": voices}

@app.post("/api/settings")
async def api_save_settings(request: Request):
    data = await request.json()
    for k, v in data.items():
        set_setting(k, str(v))
    return {"success": True, "message": "Settings updated successfully"}

# ==========================================
# 7. INTERACTIVE AI PLAYGROUND (LIVE CHAT & VOICE TEST)
# ==========================================
@app.post("/api/test/chat")
async def api_test_chat(
    message: Optional[str] = Form(""),
    generate_voice: bool = Form(False),
    image: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None)
):
    image_bytes = None
    image_mime = "image/jpeg"
    if image and image.filename:
        image_bytes = await image.read()
        image_mime = image.content_type or "image/jpeg"

    audio_bytes = None
    audio_mime = "audio/mp3"
    if audio and audio.filename:
        audio_bytes = await audio.read()
        audio_mime = audio.content_type or "audio/mp3"
        generate_voice = True

    res = await process_customer_message(
        message_text=message or "",
        image_bytes=image_bytes,
        image_mime=image_mime,
        audio_bytes=audio_bytes,
        audio_mime=audio_mime,
        channel="web_playground",
        sender_id="tester",
        generate_voice_reply=generate_voice
    )

    return res

# ==========================================
# 8. FACEBOOK & WHATSAPP WEBHOOK ENDPOINTS
# ==========================================
@app.get("/webhook/facebook")
async def facebook_verify(request: Request):
    """Handshake verification for Meta Webhook."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    expected_token = get_setting("fb_verify_token", settings.FB_VERIFY_TOKEN)
    if mode == "subscribe" and token == expected_token:
        print("[Facebook Webhook] Verified successfully.")
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)

@app.post("/webhook/facebook")
async def facebook_events(request: Request):
    data = await request.json()
    await handle_facebook_webhook_event(data)
    return JSONResponse(content={"status": "ok"})

@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """Handshake verification for WhatsApp Webhook."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    expected_token = get_setting("whatsapp_verify_token", settings.WHATSAPP_VERIFY_TOKEN)
    if mode == "subscribe" and token == expected_token:
        print("[WhatsApp Webhook] Verified successfully.")
        return Response(content=challenge, media_type="text/plain")
    return Response(content="Verification failed", status_code=403)

@app.post("/webhook/whatsapp")
async def whatsapp_events(request: Request):
    data = await request.json()
    await handle_whatsapp_webhook_event(data)
    return JSONResponse(content={"status": "ok"})
