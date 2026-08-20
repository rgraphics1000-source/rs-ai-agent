import os
import json
import csv
import io
import uuid
import requests
from typing import Optional, List
from fastapi import FastAPI, Request, Response, Form, File, UploadFile, Query, HTTPException, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, PlainTextResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.config import settings
from app.database import (
    init_db, get_db_connection, get_setting, set_setting, get_all_settings,
    get_all_training_rules, create_training_rule, update_training_rule,
    delete_training_rule, toggle_training_rule, get_saved_media,
    create_saved_media, delete_saved_media, toggle_conversation_ai
)
from app.ai_agent.gemini_brain import process_customer_message
from app.ai_agent.voice_engine import generate_bangla_voice, list_available_voices
from app.ai_agent.order_engine import list_orders, update_order_status, create_order
from datetime import datetime
import time
from app.channels.facebook import (
    send_fb_text_message,
    send_fb_media_message,
    send_fb_audio_message,
    send_fb_video_message,
    handle_facebook_webhook_event
)
from app.channels.whatsapp import (
    send_whatsapp_message,
    send_whatsapp_image,
    send_whatsapp_audio,
    send_whatsapp_video,
    handle_whatsapp_webhook_event
)
from app.channels.omnichat import (
    get_all_conversations, 
    get_conversation_history, 
    record_conversation_message,
    send_whatsapp_media,
    send_whatsapp_audio as send_omnichat_wa_audio,
    send_whatsapp_video
)

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

# Root manifest and favicon
@app.get("/manifest.json")
async def get_manifest():
    return FileResponse(settings.STATIC_DIR / "manifest.json", media_type="application/manifest+json")

@app.get("/favicon.ico")
async def get_favicon():
    return FileResponse(settings.STATIC_DIR / "favicon.ico", media_type="image/x-icon")

# Android APK Download Endpoint
@app.get("/download/app.apk")
@app.get("/download/RS_AI.apk")
async def download_android_apk():
    apk_path = settings.STATIC_DIR / "download" / "RS_AI.apk"
    if not apk_path.exists():
        raise HTTPException(status_code=404, detail="APK build not found")
    return FileResponse(
        path=apk_path,
        filename="RS_AI.apk",
        media_type="application/vnd.android.package-archive"
    )

# ==========================================
# 1. FRONTEND DASHBOARD ROUTE
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "shop_name": get_setting("shop_name", settings.SHOP_NAME),
            "version": settings.VERSION
        }
    )
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

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
    products = []
    for r in cursor.fetchall():
        d = dict(r)
        # Parse gallery images JSON
        try:
            d["gallery_images"] = json.loads(d.get("gallery_images") or "[]")
        except Exception:
            d["gallery_images"] = []
        if not d["gallery_images"] and d.get("image_url"):
            d["gallery_images"] = [d["image_url"]]
        products.append(d)
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
    images: Optional[List[UploadFile]] = File(None),
    image: Optional[UploadFile] = File(None)
):
    all_image_urls = []
    files_to_process = []
    if images:
        files_to_process.extend(images)
    if image and image.filename:
        files_to_process.append(image)

    for file_obj in files_to_process:
        if file_obj and file_obj.filename:
            ext = Path(file_obj.filename).suffix or ".jpg"
            unique_name = f"prod_{uuid.uuid4().hex[:8]}{ext}"
            save_path = settings.UPLOADS_DIR / unique_name
            contents = await file_obj.read()
            with open(save_path, "wb") as f:
                f.write(contents)
            all_image_urls.append(f"/static/uploads/{unique_name}")

    primary_image_url = all_image_urls[0] if all_image_urls else ""
    gallery_images_json = json.dumps(all_image_urls)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO products (name, code, price, discount_price, stock, category, description, tags, image_url, gallery_images)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name, code, price, discount_price, stock, category, description, tags, primary_image_url, gallery_images_json))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Product added successfully", "image_urls": all_image_urls}

@app.post("/api/products/{product_id}/edit")
async def api_edit_product(
    product_id: int,
    name: str = Form(...),
    code: str = Form(...),
    price: float = Form(...),
    discount_price: Optional[float] = Form(None),
    stock: int = Form(10),
    category: str = Form("General"),
    description: str = Form(""),
    tags: Optional[str] = Form(""),
    existing_images: Optional[str] = Form("[]"),
    images: Optional[List[UploadFile]] = File(None)
):
    try:
        current_images = json.loads(existing_images) if existing_images else []
    except Exception:
        current_images = []

    if images:
        for file_obj in images:
            if file_obj and file_obj.filename:
                ext = Path(file_obj.filename).suffix or ".jpg"
                unique_name = f"prod_{uuid.uuid4().hex[:8]}{ext}"
                save_path = settings.UPLOADS_DIR / unique_name
                contents = await file_obj.read()
                with open(save_path, "wb") as f:
                    f.write(contents)
                current_images.append(f"/static/uploads/{unique_name}")

    primary_image_url = current_images[0] if current_images else ""
    gallery_images_json = json.dumps(current_images)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE products 
        SET name = ?, code = ?, price = ?, discount_price = ?, stock = ?, category = ?, description = ?, tags = ?, image_url = ?, gallery_images = ?
        WHERE id = ?
    """, (name, code, price, discount_price, stock, category, description, tags, primary_image_url, gallery_images_json, product_id))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Product updated successfully"}

@app.delete("/api/products/{product_id}")
@app.post("/api/products/{product_id}/delete")
async def api_delete_product(product_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Product deleted"}

@app.post("/api/products/batch-restore")
async def api_batch_restore_products(request: Request):
    data = await request.json()
    products = data.get("products", [])
    conn = get_db_connection()
    cursor = conn.cursor()
    for p in products:
        code = p.get("code")
        if not code:
            continue
        cursor.execute("SELECT id FROM products WHERE code = ?", (code,))
        if not cursor.fetchone():
            g_imgs = p.get("gallery_images")
            g_json = json.dumps(g_imgs) if isinstance(g_imgs, list) else str(g_imgs or "[]")
            cursor.execute("""
                INSERT INTO products (name, code, price, discount_price, stock, category, description, tags, image_url, gallery_images)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                p.get("name"), code, p.get("price"), p.get("discount_price"),
                p.get("stock", 10), p.get("category", "General"), p.get("description", ""),
                p.get("tags", ""), p.get("image_url", ""), g_json
            ))
    conn.commit()
    conn.close()
    return {"success": True}

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
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (cid,))
    conv = cursor.fetchone()
    
    if not conv:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found")

    channel = conv["channel"]
    sender_id = conv["sender_id"]
    
    send_ok = False
    error_detail = ""

    # Dispatch to real channel first
    if channel == "facebook":
        send_ok = send_fb_text_message(sender_id, content)
        if not send_ok:
            error_detail = "Failed to send message via Facebook Messenger API. Check Facebook Page Access Token."
    elif channel == "whatsapp":
        send_ok = send_whatsapp_message(sender_id, content)
        if not send_ok:
            error_detail = "Failed to send message via WhatsApp Cloud API. Check WhatsApp Phone Number ID and Access Token."
    else:
        send_ok = True

    if not send_ok:
        conn.close()
        return JSONResponse(
            status_code=500, 
            content={
                "success": False, 
                "error": error_detail or "Failed to deliver message to recipient"
            }
        )

    # Only record message in database after confirmed Meta delivery
    cursor.execute("""
        INSERT INTO messages (conversation_id, sender_type, content)
        VALUES (?, 'admin', ?)
    """, (cid, content))
    cursor.execute("UPDATE conversations SET last_message = ?, human_takeover = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (content, cid))
    conn.commit()
    conn.close()

    return {"success": True}

@app.post("/api/omnichat/toggle-ai")
async def api_omnichat_toggle_ai(request: Request):
    """Toggles AI auto-reply on/off for a specific customer conversation."""
    data = await request.json()
    cid = data.get("conversation_id")
    status = data.get("status") # None, 0, or 1
    if not cid:
        raise HTTPException(status_code=400, detail="Missing conversation_id")

    toggle_conversation_ai(cid, status)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, human_takeover FROM conversations WHERE id = ?", (cid,))
    row = cursor.fetchone()
    conn.close()
    return {"success": True, "human_takeover": row["human_takeover"] if row else 0}

# ==========================================
# 5.5 AI TRAINING & KNOWLEDGE BASE APIS
# ==========================================
@app.get("/api/training/rules")
async def api_get_training_rules():
    rules = get_all_training_rules()
    return {"rules": rules}

@app.post("/api/training/synthesize")
async def api_synthesize_training(request: Request):
    """
    Takes raw, unorganized Bengali owner instructions and uses AI to automatically
    extract, organize, categorize, and save clean structured training rules into the database.
    """
    from app.ai_agent.synthesizer import synthesize_training_text_to_rules
    data = await request.json()
    raw_text = data.get("raw_text", "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="Raw training text is required")
    
    rules = synthesize_training_text_to_rules(raw_text)
    return {"success": True, "count": len(rules), "rules": rules}

@app.post("/api/training/rules")
async def api_create_training_rule(request: Request):
    data = await request.json()
    title = data.get("title", "").strip()
    rule = data.get("response_or_rule", "").strip()
    rule_type = data.get("rule_type", "qa")
    trigger = data.get("question_or_trigger", "").strip()
    category = data.get("category", "General").strip()
    is_active = int(data.get("is_active", 1))
    if not title or not rule:
        raise HTTPException(status_code=400, detail="Title and Rule text are required")
    rule_id = create_training_rule(title, rule, rule_type, trigger, category, is_active)
    return {"success": True, "id": rule_id}

@app.put("/api/training/rules/{rule_id}")
async def api_update_training_rule(rule_id: int, request: Request):
    data = await request.json()
    title = data.get("title", "").strip()
    rule = data.get("response_or_rule", "").strip()
    rule_type = data.get("rule_type", "qa")
    trigger = data.get("question_or_trigger", "").strip()
    category = data.get("category", "General").strip()
    is_active = int(data.get("is_active", 1))
    update_training_rule(rule_id, title, rule, rule_type, trigger, category, is_active)
    return {"success": True}

@app.delete("/api/training/rules/{rule_id}")
async def api_delete_training_rule(rule_id: int):
    delete_training_rule(rule_id)
    return {"success": True}

@app.post("/api/training/rules/{rule_id}/toggle")
async def api_toggle_training_rule(rule_id: int):
    toggle_training_rule(rule_id)
    return {"success": True}

# ==========================================
# 5.6 SAVED MEDIA LIBRARY APIS (VOICE & VIDEO)
# ==========================================
@app.get("/api/saved-media")
async def api_get_saved_media(type: str = None):
    media = get_saved_media(type)
    return {"media": media}

@app.post("/api/saved-media/upload")
async def api_upload_saved_media(
    file: UploadFile = File(None),
    title: str = Form(""),
    media_type: str = Form("voice"),
    description: str = Form(""),
    file_url: str = Form("")
):
    target_url = file_url
    if file and file.filename:
        media_dir = settings.UPLOADS_DIR / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        clean_fname = f"{int(time.time())}_{file.filename.replace(' ', '_')}"
        save_path = media_dir / clean_fname
        contents = await file.read()
        with open(save_path, "wb") as f:
            f.write(contents)
        target_url = f"/static/uploads/media/{clean_fname}"

    if not target_url:
        raise HTTPException(status_code=400, detail="File or file_url is required")
    
    media_id = create_saved_media(
        title=title or "Saved Media",
        media_type=media_type,
        file_url=target_url,
        description=description
    )
    return {"success": True, "id": media_id, "file_url": target_url}

@app.delete("/api/saved-media/{media_id}")
async def api_delete_saved_media(media_id: int):
    delete_saved_media(media_id)
    return {"success": True}

@app.post("/api/saved-media/send")
async def api_send_saved_media(request: Request):
    data = await request.json()
    cid = data.get("conversation_id")
    media_id = data.get("media_id")
    if not cid or not media_id:
        raise HTTPException(status_code=400, detail="Missing conversation_id or media_id")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (cid,))
    conv = cursor.fetchone()
    cursor.execute("SELECT * FROM saved_media WHERE id = ?", (media_id,))
    med = cursor.fetchone()
    
    if not conv or not med:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation or Media not found")
    
    channel = conv["channel"]
    sender_id = conv["sender_id"]
    m_type = med["media_type"]
    m_url = med["file_url"]
    m_title = med["title"]
    
    send_ok = False
    if channel == "whatsapp":
        if m_type in ["voice", "audio"]:
            send_ok = send_whatsapp_audio(sender_id, m_url)
        elif m_type == "video":
            send_ok = send_whatsapp_video(sender_id, m_url, caption=m_title)
        else:
            send_ok = send_whatsapp_image(sender_id, m_url, caption=m_title)
    elif channel == "facebook":
        if m_type in ["voice", "audio"]:
            send_ok = send_fb_audio_message(sender_id, m_url)
        elif m_type == "video":
            send_ok = send_fb_video_message(sender_id, m_url)
        else:
            send_fb_media_message(sender_id, "image", m_url)
            send_ok = True
    else:
        send_ok = True
        
    if not send_ok:
        conn.close()
        return JSONResponse(status_code=500, content={"success": False, "error": "Failed to deliver media to recipient via API"})
        
    cursor.execute("""
        INSERT INTO messages (conversation_id, sender_type, message_type, content, media_url)
        VALUES (?, 'admin', ?, ?, ?)
    """, (cid, m_type, f"[{m_type.upper()}] {m_title}", m_url))
    cursor.execute("UPDATE conversations SET last_message = ?, human_takeover = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (f"[{m_type.upper()}] {m_title}", cid))
    conn.commit()
    conn.close()
    return {"success": True}

# PWA Web App Manifest Endpoint
@app.get("/manifest.json")
async def get_pwa_manifest():
    return JSONResponse(content={
        "name": "RS AI Autonomous Sales Platform",
        "short_name": "RS AI Agent",
        "description": "Autonomous AI Sales Agent & Multi-Channel Order Platform",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0f19",
        "theme_color": "#4f46e5",
        "icons": [
            {
                "src": "/static/uploads/id_card/IMG-20241009-WA0005.jpg",
                "sizes": "192x192",
                "type": "image/jpeg"
            },
            {
                "src": "/static/uploads/id_card/IMG-20241009-WA0005.jpg",
                "sizes": "512x512",
                "type": "image/jpeg"
            }
        ]
    })

# ==========================================
# 6. SETTINGS & AI CONFIG APIS
# ==========================================
@app.get("/api/settings")
async def api_get_settings():
    all_s = get_all_settings(masked=True)
    voices = list_available_voices()
    return {"settings": all_s, "voices": voices}

@app.post("/api/settings")
async def api_save_settings(request: Request):
    data = await request.json()
    for k, v in data.items():
        set_setting(k, str(v))
    return {"success": True, "message": "Settings updated successfully"}

@app.get("/api/whatsapp/embedded-config")
async def api_whatsapp_embedded_config():
    """Returns configuration for Meta Embedded Signup."""
    app_id = get_setting("meta_app_id", settings.META_APP_ID)
    raw_config_id = get_setting("meta_embedded_signup_config_id", settings.META_EMBEDDED_SIGNUP_CONFIG_ID)
    config_id = "1003403176086013" if raw_config_id in ["10034031760860138", ""] else raw_config_id
    
    waba_id = get_setting("whatsapp_waba_id", settings.WHATSAPP_WABA_ID)
    saved_phone_id = get_setting("whatsapp_phone_number_id", "")
    saved_phone_num = get_setting("whatsapp_display_phone_number", "+8801816504097")
    saved_status = get_setting("whatsapp_connection_status", "not_connected")
    
    # Target phone 01816504097 validation
    is_target_verified = (
        saved_status == "connected" 
        and saved_phone_id != "" 
        and saved_phone_id != "1265595526643418"
        and normalize_whatsapp_phone_number(saved_phone_num) == "8801816504097"
    )
    
    return {
        "app_id": app_id,
        "config_id": config_id,
        "version": "v19.0",
        "waba_id": waba_id,
        "phone_number_id": saved_phone_id if is_target_verified else "",
        "display_phone_number": "+8801816504097",
        "target_normalized": "8801816504097",
        "connection_mode": "business_app_coexistence",
        "connection_status": "connected" if is_target_verified else "not_connected",
        "coexistence_active": is_target_verified,
        "is_configured": bool(config_id and config_id.strip())
    }

@app.post("/api/whatsapp/embedded-signup")
async def api_whatsapp_embedded_signup(request: Request):
    """Processes the WhatsApp Business App Coexistence Embedded Signup result."""
    data = await request.json()
    code = data.get("code")
    waba_id = data.get("waba_id")
    phone_number_id = data.get("phone_number_id")
    display_phone_number = data.get("display_phone_number") or "+8801816504097"
    access_token = data.get("access_token")

    TARGET_NORMALIZED_PHONE = "8801816504097"
    UNRELATED_PHONE_NUMBER_ID = "1265595526643418"

    print("[WhatsApp Embedded Signup] Started processing callback")
    print(f"[WhatsApp Embedded Signup] Authorization code received: {'YES' if code else 'NO'}")
    print(f"[WhatsApp Embedded Signup] WABA ID received: {waba_id or 'None'}")
    print(f"[WhatsApp Embedded Signup] Phone Number ID received: {phone_number_id or 'None'}")
    print(f"[WhatsApp Embedded Signup] Display Phone: {display_phone_number or 'None'}")

    # 1. Token Exchange if code & secret available
    app_id = get_setting("meta_app_id", settings.META_APP_ID)
    app_secret = get_setting("fb_app_secret", settings.FB_APP_SECRET)

    if code and app_secret and app_id:
        try:
            token_url = "https://graph.facebook.com/v19.0/oauth/access_token"
            params = {
                "client_id": app_id,
                "client_secret": app_secret,
                "code": code
            }
            resp = requests.get(token_url, params=params, timeout=10)
            if resp.status_code == 200:
                tdata = resp.json()
                access_token = tdata.get("access_token") or access_token
                print("[WhatsApp Embedded Signup] Token exchange: SUCCESS")
            else:
                print(f"[WhatsApp Embedded Signup] Token exchange response code: {resp.status_code}")
        except Exception as e:
            print(f"[WhatsApp Embedded Signup] Token Exchange Error: {e}")

    effective_token = (
        access_token 
        or get_setting("meta_system_user_access_token") 
        or settings.META_SYSTEM_USER_ACCESS_TOKEN 
        or get_setting("whatsapp_access_token") 
        or settings.WHATSAPP_ACCESS_TOKEN
    )
    effective_waba = waba_id or get_setting("whatsapp_waba_id", settings.WHATSAPP_WABA_ID)

    matched_phone_id = None
    matched_display_name = ""
    matched_phone_str = "+8801816504097"

    # 2. Query Meta Graph API for WABA phone numbers to find target 01816504097
    if effective_waba and effective_token:
        try:
            url = f"https://graph.facebook.com/v19.0/{effective_waba}/phone_numbers?fields=id,display_phone_number,verified_name,quality_rating,status,code_verification_status"
            resp = requests.get(url, headers={"Authorization": f"Bearer {effective_token}"}, timeout=10)
            if resp.status_code == 200:
                pdata = resp.json().get("data", [])
                print(f"[WhatsApp Embedded Signup] WABA phone numbers discovered: {len(pdata)}")
                for item in pdata:
                    p_id = item.get("id")
                    p_num = item.get("display_phone_number", "")
                    p_norm = normalize_whatsapp_phone_number(p_num)
                    print(f"[WA MATCH] ID={p_id}, Phone={p_num}, Norm={p_norm}")
                    if p_norm == TARGET_NORMALIZED_PHONE:
                        matched_phone_id = p_id
                        matched_display_name = item.get("verified_name", "")
                        matched_phone_str = p_num
                        print(f"[WA MATCH] -> EXACT TARGET MATCH for 01816504097: {matched_phone_id}")
                        break
                    elif p_id == UNRELATED_PHONE_NUMBER_ID:
                        print(f"[WA MATCH] -> Explicitly ignoring unrelated ID {p_id} ({p_num})")
        except Exception as q_err:
            print(f"[WhatsApp Embedded Signup] Query phone numbers error: {q_err}")

    # 3. If direct phone_number_id was sent from postMessage and matches target
    if not matched_phone_id and phone_number_id and phone_number_id != UNRELATED_PHONE_NUMBER_ID:
        if normalize_whatsapp_phone_number(display_phone_number) == TARGET_NORMALIZED_PHONE:
            matched_phone_id = phone_number_id

    # 4. Save and return verified state
    if matched_phone_id:
        set_setting("whatsapp_waba_id", str(effective_waba))
        set_setting("whatsapp_phone_number_id", str(matched_phone_id))
        set_setting("whatsapp_display_phone_number", str(matched_phone_str))
        set_setting("whatsapp_normalized_phone_number", TARGET_NORMALIZED_PHONE)
        set_setting("whatsapp_connection_mode", "business_app_coexistence")
        set_setting("whatsapp_coexistence_active", "true")
        set_setting("whatsapp_connection_status", "connected")
        set_setting("whatsapp_connected_at", datetime.utcnow().isoformat())
        if matched_display_name:
            set_setting("whatsapp_verified_name", matched_display_name)
        if access_token:
            set_setting("whatsapp_access_token", str(access_token))

        # Subscribe app to webhooks
        try:
            sub_url = f"https://graph.facebook.com/v19.0/{effective_waba}/subscribed_apps"
            requests.post(sub_url, headers={"Authorization": f"Bearer {effective_token}"}, timeout=10)
        except Exception:
            pass

        return {
            "success": True,
            "message": "WhatsApp Business App (+8801816504097) successfully connected in Coexistence Mode!",
            "connection_mode": "business_app_coexistence",
            "connection_status": "connected",
            "waba_id": str(effective_waba),
            "phone_number_id": str(matched_phone_id),
            "display_phone_number": str(matched_phone_str),
            "coexistence_active": True
        }
    else:
        # Target number was not found yet
        set_setting("whatsapp_connection_status", "not_connected")
        set_setting("whatsapp_connection_mode", "business_app_coexistence")
        set_setting("whatsapp_coexistence_active", "false")
        return {
            "success": False,
            "error": "target_number_not_verified",
            "message": "Target number +8801816504097 is not yet verified in Meta. Please enter +880 1816504097 in the Meta popup and enter the 6-digit OTP sent to your WhatsApp Business mobile app.",
            "connection_status": "not_connected"
        }

@app.post("/api/whatsapp/disconnect")
async def api_whatsapp_disconnect():
    set_setting("whatsapp_connection_status", "disconnected")
    set_setting("whatsapp_connection_mode", "disconnected")
    set_setting("whatsapp_coexistence_active", "false")
    return {"success": True, "message": "WhatsApp Business connection status reset."}

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
    challenge = params.get("hub.challenge", "")

    expected_token = get_setting("fb_verify_token", settings.FB_VERIFY_TOKEN)
    valid_tokens = {expected_token, settings.FB_VERIFY_TOKEN, "rs_secure_verify_token_2026", "presswayy_secure_verify_token_2026"}

    if mode == "subscribe" and (token in valid_tokens or token == "rs_secure_verify_token_2026"):
        print(f"[Facebook Webhook] Handshake verified successfully with challenge: {challenge}")
        return PlainTextResponse(content=str(challenge))
    
    print(f"[Facebook Webhook] Verification failed. Received token: {token}, Expected: {valid_tokens}")
    return PlainTextResponse(content="Verification failed", status_code=403)

@app.post("/webhook/facebook")
async def facebook_events(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    background_tasks.add_task(handle_facebook_webhook_event, data)
    return JSONResponse(content={"status": "EVENT_RECEIVED"})

@app.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    """Handshake verification for WhatsApp Webhook."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    expected_token = get_setting("whatsapp_verify_token", settings.WHATSAPP_VERIFY_TOKEN)
    valid_tokens = {expected_token, settings.WHATSAPP_VERIFY_TOKEN, "rs_whatsapp_token_2026", "presswayy_whatsapp_token_2026"}

    if mode == "subscribe" and (token in valid_tokens or token == "rs_whatsapp_token_2026"):
        print(f"[WhatsApp Webhook] Handshake verified successfully with challenge: {challenge}")
        return PlainTextResponse(content=str(challenge))
    
    print(f"[WhatsApp Webhook] Verification failed. Received token: {token}, Expected: {valid_tokens}")
    return PlainTextResponse(content="Verification failed", status_code=403)

@app.post("/webhook/whatsapp")
async def whatsapp_events(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    background_tasks.add_task(handle_whatsapp_webhook_event, data)
    return JSONResponse(content={"status": "EVENT_RECEIVED"})
