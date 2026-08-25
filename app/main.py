import os
import sys
import json
import csv
import io
import uuid
import requests
from typing import Optional, List

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from fastapi import FastAPI, Request, Response, status, Form, File, UploadFile, Query, HTTPException, Depends, BackgroundTasks
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
    create_saved_media, delete_saved_media, toggle_conversation_ai,
    get_muted_contacts_detailed, get_muted_numbers, add_muted_number, remove_muted_number,
    get_all_connected_pages, get_connected_page, save_connected_page, delete_connected_page,
    get_all_whatsapp_accounts, get_whatsapp_account_by_phone_id, get_whatsapp_account_by_page_id,
    get_whatsapp_account_by_workspace_id, save_whatsapp_account, delete_whatsapp_account, get_page_ai_config,
    get_all_workspaces, get_workspace, save_workspace, delete_workspace,
    get_faqs, create_faq, delete_faq, ensure_whatsapp_account_consistency,
    ensure_facebook_page_consistency, enable_conversation_ai, set_admin_takeover,
    get_conversation_state, is_conversation_ai_active
)
from app.ai_agent.gemini_brain import process_customer_message
from app.ai_agent.voice_engine import generate_bangla_voice, list_available_voices
from app.ai_agent.order_engine import list_orders, update_order_status, create_order
from datetime import datetime, timezone
from app.services.cloud_sync_service import sync_cold_start_if_configured
from app.channels.facebook import (
    send_fb_text_message,
    send_fb_media_message,
    send_fb_audio_message,
    send_fb_video_message,
    handle_facebook_webhook_event,
    subscribe_facebook_page_webhooks,
    get_fb_page_details,
    reply_to_fb_comment,
    reply_to_fb_comment_detailed
)
from app.channels.whatsapp import (
    send_whatsapp_message,
    send_whatsapp_message_detailed,
    send_whatsapp_image,
    send_whatsapp_audio,
    send_whatsapp_video,
    handle_whatsapp_webhook_event,
    validate_whatsapp_token_with_meta,
    resolve_whatsapp_token_info,
    clear_token_validation_cache
)
from app.channels.omnichat import (
    get_all_conversations, 
    get_conversation_messages,
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

# Mount Google Integration Router (Forms + Sheets + Drive)
from app.google_integration.routes import router as google_router
app.include_router(google_router)

# Ensure database tables are created on startup and state is restored
@app.on_event("startup")
def startup_event():
    try:
        init_db()
    except Exception as e:
        print(f"[DB Startup Exception]: {e}")
    try:
        sync_cold_start_if_configured()
    except Exception as e:
        print(f"[Cloud Sync Startup Notice]: {e}")
    try:
        ensure_facebook_page_consistency()
    except Exception as e:
        print(f"[FB Consistency Exception]: {e}")
    try:
        ensure_whatsapp_account_consistency()
    except Exception as e:
        print(f"[WA Consistency Exception]: {e}")

    # Run webhook subscription in background daemon thread to ensure instant port binding
    import threading
    def _bg_subscribe():
        try:
            subscribe_facebook_page_webhooks()
        except Exception as e:
            print(f"[Facebook Auto-Subscribe on Startup Exception]: {e}")
    threading.Thread(target=_bg_subscribe, daemon=True).start()

    # Optional self-ping keepalive loop if explicitly configured
    if os.getenv("ENABLE_KEEPALIVE_PING", "false").lower() == "true":
        def _bg_keepalive():
            import time, urllib.request
            time.sleep(180)
            while True:
                try:
                    server_domain = os.getenv("RENDER_EXTERNAL_URL") or "https://rs-ai-agent.onrender.com"
                    url = f"{server_domain.rstrip('/')}/health"
                    req = urllib.request.Request(url, headers={"User-Agent": "RS-AI-Agent-KeepAlive/1.0"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        print(f"[KeepAlive Ping]: HTTP {resp.getcode()} to {url}")
                except Exception as k_err:
                    print(f"[KeepAlive Ping Notice]: {k_err}")
                time.sleep(540)
        threading.Thread(target=_bg_keepalive, daemon=True).start()

    print(f"[{settings.PROJECT_NAME}] Server started successfully on port {os.getenv('PORT', 8000)}.")

# Lightweight Health Check Endpoints
@app.get("/health")
@app.get("/api/health")
async def health_check(response: Response):
    """Health check endpoint checking live database connectivity and system status."""
    db_ok = False
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT 1")
        c.fetchone()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "healthy" if db_ok else "unhealthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "database": "connected" if db_ok else "unavailable",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

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
async def get_overview_stats(workspace_id: Optional[int] = Query(None)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if workspace_id is not None:
        ws_id = int(workspace_id)
        cursor.execute("SELECT COUNT(*) FROM orders WHERE workspace_id = ?", (ws_id,))
        total_orders = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM orders WHERE workspace_id = ? AND status = 'Pending'", (ws_id,))
        pending_orders = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM orders WHERE workspace_id = ? AND status IN ('Confirmed', 'Processing', 'Shipped', 'Delivered')", (ws_id,))
        confirmed_orders = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(total_amount), 0) FROM orders WHERE workspace_id = ? AND status != 'Cancelled'", (ws_id,))
        total_revenue = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM products WHERE workspace_id = ? AND is_active = 1", (ws_id,))
        total_products = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM comment_logs WHERE workspace_id = ?", (ws_id,))
        total_comments = cursor.fetchone()[0]

        cursor.execute("SELECT * FROM orders WHERE workspace_id = ? ORDER BY id DESC LIMIT 5", (ws_id,))
        recent_orders = [dict(r) for r in cursor.fetchall()]
    else:
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
async def api_list_orders(status: Optional[str] = None, search: Optional[str] = None, workspace_id: Optional[int] = Query(None)):
    orders = list_orders(status=status, search=search, workspace_id=workspace_id)
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
    notes: Optional[str] = Form(""),
    workspace_id: int = Form(1)
):
    items = [{"name": items_summary, "qty": 1, "price": total_amount - delivery_charge}]
    order = create_order(
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_address=customer_address,
        items=items,
        channel=channel,
        notes=notes,
        workspace_id=workspace_id
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
async def export_orders_csv(workspace_id: Optional[int] = Query(None)):
    orders = list_orders(workspace_id=workspace_id)
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
async def api_list_products(workspace_id: Optional[int] = Query(None)):
    conn = get_db_connection()
    cursor = conn.cursor()
    if workspace_id is not None:
        cursor.execute("SELECT * FROM products WHERE workspace_id = ? ORDER BY id DESC", (int(workspace_id),))
    else:
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
    workspace_id: int = Form(1),
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
        INSERT INTO products (workspace_id, name, code, price, discount_price, stock, category, description, tags, image_url, gallery_images)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (int(workspace_id or 1), name, code, price, discount_price, stock, category, description, tags, primary_image_url, gallery_images_json))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Product added successfully", "image_urls": all_image_urls}
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
                current_images.append({
                    "url": f"/static/uploads/{unique_name}",
                    "title": f"ভ্যারিয়েশন {len(current_images) + 1}",
                    "price": price
                })

    primary_image_url = ""
    if current_images:
        first_img = current_images[0]
        primary_image_url = first_img["url"] if isinstance(first_img, dict) else str(first_img)
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
async def api_comment_logs(workspace_id: Optional[int] = Query(None)):
    conn = get_db_connection()
    cursor = conn.cursor()
    if workspace_id is not None:
        cursor.execute("SELECT * FROM comment_logs WHERE workspace_id = ? ORDER BY id DESC LIMIT 50", (int(workspace_id),))
    else:
        cursor.execute("SELECT * FROM comment_logs ORDER BY id DESC LIMIT 50")
    logs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"logs": logs}

# ==========================================
# 5.1 TRAIN CONTENT (FAQS & KNOWLEDGE) APIS
# ==========================================
@app.get("/api/faqs")
async def api_list_faqs(workspace_id: Optional[int] = Query(None)):
    faqs = get_faqs(workspace_id=workspace_id)
    return {"faqs": faqs}

@app.post("/api/faqs")
async def api_add_faq(request: Request):
    data = await request.json()
    q = data.get("question")
    a = data.get("answer")
    cat = data.get("category", "General")
    ws_id = int(data.get("workspace_id", 1) or 1)
    if not q or not a:
        raise HTTPException(status_code=400, detail="Question and answer required")
    
    faq_id = create_faq(question=q, answer=a, category=cat, workspace_id=ws_id)
    return {"success": True, "message": "FAQ added", "id": faq_id}

@app.delete("/api/faqs/{faq_id}")
async def api_delete_faq(faq_id: int):
    delete_faq(faq_id)
    return {"success": True, "message": "FAQ deleted"}

# ==========================================
# 5.1.1 AI TRAINING RULES APIS
# ==========================================
@app.get("/api/training/rules")
async def api_get_training_rules(workspace_id: Optional[int] = Query(None)):
    ws_id = int(workspace_id or 1)
    rules = get_all_training_rules(workspace_id=ws_id)
    return {"success": True, "rules": rules}

@app.post("/api/training/synthesize")
async def api_synthesize_training(request: Request):
    """
    Takes raw, unorganized Bengali owner instructions and uses AI to automatically
    extract, organize, categorize, and save clean structured training rules into the database.
    """
    from app.ai_agent.synthesizer import synthesize_training_text_to_rules
    data = await request.json()
    raw_text = data.get("raw_text", "").strip()
    ws_id = int(data.get("workspace_id", 1) or 1)
    if not raw_text:
        raise HTTPException(status_code=400, detail="Raw training text is required")
    
    rules = synthesize_training_text_to_rules(raw_text)
    # Save extracted rules with workspace_id
    for r in rules:
        create_training_rule(
            title=r.get("title", "AI Guideline"),
            response_or_rule=r.get("rule", ""),
            rule_type=r.get("rule_type", "rule"),
            question_or_trigger=r.get("trigger", ""),
            category=r.get("category", "General"),
            workspace_id=ws_id
        )
    return {"success": True, "count": len(rules), "rules": rules}

@app.post("/api/training/rules")
async def api_create_training_rule(request: Request):
    data = await request.json()
    title = data.get("title", "").strip()
    rule = (data.get("response_or_rule") or data.get("rule") or "").strip()
    rule_type = data.get("rule_type", "qa")
    trigger = (data.get("question_or_trigger") or data.get("trigger") or "").strip()
    category = data.get("category", "General").strip()
    is_active = int(data.get("is_active", 1))
    ws_id = int(data.get("workspace_id", 1) or 1)
    if not title or not rule:
        raise HTTPException(status_code=400, detail="Title and Rule text are required")
    rule_id = create_training_rule(title, rule, rule_type, trigger, category, is_active, workspace_id=ws_id)
    return {"success": True, "id": rule_id}

@app.put("/api/training/rules/{rule_id}")
async def api_update_training_rule(rule_id: int, request: Request):
    data = await request.json()
    title = data.get("title", "").strip()
    rule = (data.get("response_or_rule") or data.get("rule") or "").strip()
    rule_type = data.get("rule_type", "qa")
    trigger = (data.get("question_or_trigger") or data.get("trigger") or "").strip()
    category = data.get("category", "General").strip()
    is_active = int(data.get("is_active", 1))
    ws_id = data.get("workspace_id")
    update_training_rule(rule_id, title, rule, rule_type, trigger, category, is_active, workspace_id=ws_id)
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
# 5.1.2 SAVED MEDIA LIBRARY (VOICE & VIDEOS) APIS
# ==========================================
@app.get("/api/saved-media")
async def api_get_saved_media(type: str = None, media_type: str = None, workspace_id: Optional[int] = Query(None)):
    m_type = media_type or type
    ws_id = int(workspace_id or 1)
    media = get_saved_media(media_type=m_type, workspace_id=ws_id)
    return {"success": True, "media": media}

@app.post("/api/saved-media/upload")
async def api_upload_saved_media(
    file: UploadFile = File(None),
    title: str = Form(""),
    media_type: str = Form("voice"),
    description: str = Form(""),
    file_url: str = Form(""),
    workspace_id: int = Form(1)
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
        description=description,
        workspace_id=workspace_id
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
    page_id = conv["page_id"] if "page_id" in conv.keys() else ""
    m_type = med["media_type"]
    m_url = med["file_url"]
    m_title = med["title"]
    
    ws_id = conv["workspace_id"] if "workspace_id" in conv.keys() else 1
    if channel == "whatsapp":
        if m_type in ["voice", "audio"]:
            send_ok = send_whatsapp_audio(sender_id, m_url, page_id=page_id)
        elif m_type == "video":
            send_ok = send_whatsapp_video(sender_id, m_url, caption=m_title, page_id=page_id)
        else:
            send_ok = send_whatsapp_image(sender_id, m_url, caption=m_title, page_id=page_id)
    elif channel == "facebook":
        if m_type in ["voice", "audio"]:
            send_ok = send_fb_audio_message(sender_id, m_url, page_id=page_id, workspace_id=ws_id)
        elif m_type == "video":
            send_ok = send_fb_video_message(sender_id, m_url, page_id=page_id, workspace_id=ws_id)
        else:
            send_ok = send_fb_media_message(sender_id, "image", m_url, page_id=page_id, workspace_id=ws_id)
    else:
        send_ok = True
        
    if not send_ok:
        conn.close()
        return JSONResponse(status_code=500, content={"success": False, "error": "Failed to deliver media to recipient via API"})
        
    cursor.execute("""
        INSERT INTO messages (conversation_id, sender_type, message_type, content, media_url, direction, sender_role)
        VALUES (?, 'admin', ?, ?, ?, 'OUTBOUND', 'ADMIN')
    """, (cid, m_type, f"[{m_type.upper()}] {m_title}", m_url))
    conn.commit()
    conn.close()
    
    new_v = set_admin_takeover(
        conversation_id=cid,
        sender_id=sender_id,
        workspace_id=ws_id,
        takeover_by="admin_ui_media",
        takeover_reason="human_admin_media"
    )
    print(f"[ADMIN_TAKEOVER] workspace_id={ws_id} conversation_id={cid} customer_id={sender_id} source=omnichat_media takeover_by=admin_ui_media conversation_version={new_v}")
    print(f"[ADMIN_MESSAGE] sender_role=ADMIN channel={channel} customer_id={sender_id}")
    return {"success": True}

# ==========================================
# 5.3 OWNER APPROVAL & ESCALATION APIS (Phase 7.1)
# ==========================================
@app.get("/api/admin/approvals")
async def api_get_admin_approvals(
    status: Optional[str] = Query(None),
    workspace_id: Optional[int] = Query(None)
):
    from app.ai_agent.owner_approval import OwnerApprovalEngine
    ws_id = int(workspace_id or 1)
    status_filter = status.upper() if status and status.upper() != "ALL" else None
    approvals = OwnerApprovalEngine.list_approvals(workspace_id=ws_id, status_filter=status_filter)
    return {"success": True, "approvals": approvals}


@app.get("/api/admin/approvals/{approval_id}")
async def api_get_admin_approval_detail(approval_id: str):
    from app.ai_agent.owner_approval import OwnerApprovalEngine
    appr = OwnerApprovalEngine.get_approval_by_id(approval_id)
    if not appr:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return {"success": True, "approval": appr}


@app.post("/api/admin/approvals/{approval_id}/approve")
async def api_approve_admin_approval(approval_id: str, request: Request):
    from app.ai_agent.owner_approval import OwnerApprovalEngine, ApprovalStatus
    # Security check for customer role header
    client_role = request.headers.get("x-user-role", "admin").lower()
    if client_role == "customer":
        raise HTTPException(status_code=403, detail="Unauthorized: Customers cannot resolve approval requests")

    data = {}
    try:
        data = await request.json()
    except Exception:
        pass

    actor = data.get("actor") or "owner_admin"
    reason = data.get("reason") or "Approved by owner via dashboard"

    appr = OwnerApprovalEngine.get_approval_by_id(approval_id)
    if not appr:
        raise HTTPException(status_code=404, detail="Approval request not found")

    req_ws = data.get("workspace_id") or request.headers.get("x-workspace-id")
    if req_ws and int(req_ws) != int(appr.get("workspace_id", 1)):
        raise HTTPException(status_code=403, detail="Cross-workspace approval resolution forbidden")

    if appr["status"] != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=400, detail=f"Approval is already resolved as {appr['status']}")

    success, updated = OwnerApprovalEngine.resolve_approval(
        approval_id=approval_id,
        decision=ApprovalStatus.APPROVED,
        actor=actor,
        approved_value=appr["requested_value"],
        reason=reason
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to resolve approval")

    return {"success": True, "message": "Approval granted successfully", "approval": updated}


@app.post("/api/admin/approvals/{approval_id}/modify")
async def api_modify_admin_approval(approval_id: str, request: Request):
    from app.ai_agent.owner_approval import OwnerApprovalEngine, ApprovalStatus
    # Security check for customer role header
    client_role = request.headers.get("x-user-role", "admin").lower()
    if client_role == "customer":
        raise HTTPException(status_code=403, detail="Unauthorized: Customers cannot resolve approval requests")

    data = await request.json()
    approved_val = data.get("approved_value")
    if approved_val is None:
        raise HTTPException(status_code=400, detail="approved_value is required for modification")
    try:
        approved_val = float(approved_val)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid approved_value format")

    actor = data.get("actor") or "owner_admin"
    reason = data.get("reason") or f"Counter-offered {approved_val} Tk by owner"

    appr = OwnerApprovalEngine.get_approval_by_id(approval_id)
    if not appr:
        raise HTTPException(status_code=404, detail="Approval request not found")

    req_ws = data.get("workspace_id") or request.headers.get("x-workspace-id")
    if req_ws and int(req_ws) != int(appr.get("workspace_id", 1)):
        raise HTTPException(status_code=403, detail="Cross-workspace approval resolution forbidden")

    if appr["status"] != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=400, detail=f"Approval is already resolved as {appr['status']}")

    success, updated = OwnerApprovalEngine.resolve_approval(
        approval_id=approval_id,
        decision=ApprovalStatus.MODIFIED,
        actor=actor,
        approved_value=approved_val,
        reason=reason
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to modify approval")

    return {"success": True, "message": "Approval modified with counter-offer", "approval": updated}


@app.post("/api/admin/approvals/{approval_id}/reject")
async def api_reject_admin_approval(approval_id: str, request: Request):
    from app.ai_agent.owner_approval import OwnerApprovalEngine, ApprovalStatus
    # Security check for customer role header
    client_role = request.headers.get("x-user-role", "admin").lower()
    if client_role == "customer":
        raise HTTPException(status_code=403, detail="Unauthorized: Customers cannot resolve approval requests")

    data = {}
    try:
        data = await request.json()
    except Exception:
        pass

    actor = data.get("actor") or "owner_admin"
    reason = data.get("reason") or "Rejected by owner"

    appr = OwnerApprovalEngine.get_approval_by_id(approval_id)
    if not appr:
        raise HTTPException(status_code=404, detail="Approval request not found")

    req_ws = data.get("workspace_id") or request.headers.get("x-workspace-id")
    if req_ws and int(req_ws) != int(appr.get("workspace_id", 1)):
        raise HTTPException(status_code=403, detail="Cross-workspace approval resolution forbidden")

    if appr["status"] != ApprovalStatus.PENDING.value:
        raise HTTPException(status_code=400, detail=f"Approval is already resolved as {appr['status']}")

    success, updated = OwnerApprovalEngine.resolve_approval(
        approval_id=approval_id,
        decision=ApprovalStatus.REJECTED,
        actor=actor,
        reason=reason
    )
    if not success:
        raise HTTPException(status_code=500, detail="Failed to reject approval")

    return {"success": True, "message": "Approval rejected", "approval": updated}

# ==========================================
# 5.2 OMNICHAT (INBOX) APIS (MULTI-PAGE & WORKSPACE AWARE)
# ==========================================
@app.get("/api/conversations")
@app.get("/api/omnichat/conversations")
async def api_get_all_conversations(
    workspace_id: Optional[int] = Query(None),
    page_id: Optional[str] = Query(None),
    channel: Optional[str] = Query(None)
):
    convs = get_all_conversations(workspace_id=workspace_id, page_id=page_id, channel=channel)
    return {"success": True, "conversations": convs}

@app.get("/api/omnichat/messages/{conversation_id}")
async def api_get_conv_messages(conversation_id: int):
    messages = get_conversation_messages(conversation_id)
    return {"success": True, "messages": messages}

@app.post("/api/omnichat/reply")
@app.post("/api/omnichat/send")
@app.post("/api/conversations/reply")
async def api_admin_send_reply(request: Request):
    """Sends an admin manual reply through the exact Page/account the conversation belongs to."""
    data = await request.json()
    cid = data.get("conversation_id")
    reply_text = (data.get("message") or data.get("content") or "").strip()
    
    if not cid or not reply_text:
        raise HTTPException(status_code=400, detail="conversation_id and message are required")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM conversations WHERE id = ?", (cid,))
    conv = cursor.fetchone()
    
    if not conv:
        conn.close()
        raise HTTPException(status_code=404, detail="Conversation not found")

    channel = conv["channel"]
    sender_id = conv["sender_id"]
    page_id = conv["page_id"] if "page_id" in conv.keys() else ""
    workspace_id = conv["workspace_id"] if "workspace_id" in conv.keys() else 1

    send_ok = False
    if channel == "whatsapp":
        send_ok = send_whatsapp_message(sender_id, reply_text, page_id=page_id, workspace_id=workspace_id)
    elif channel == "facebook":
        send_ok = send_fb_text_message(sender_id, reply_text, page_id=page_id)
    else:
        send_ok = True

    if not send_ok:
        conn.close()
        return JSONResponse(status_code=500, content={"success": False, "error": f"Failed to send manual message via {channel} (Page ID: {page_id or 'default'})"})

    cursor.execute("""
        INSERT INTO messages (conversation_id, sender_type, message_type, content, direction, sender_role)
        VALUES (?, 'admin', 'text', ?, 'OUTBOUND', 'ADMIN')
    """, (cid, reply_text))
    conn.commit()
    conn.close()
    
    new_v = set_admin_takeover(
        conversation_id=cid,
        sender_id=sender_id,
        workspace_id=workspace_id,
        takeover_by="admin_ui",
        takeover_reason="human_admin_reply"
    )
    print(f"[ADMIN_TAKEOVER] workspace_id={workspace_id} conversation_id={cid} customer_id={sender_id} source=omnichat_ui takeover_by=admin_ui conversation_version={new_v}")
    print(f"[ADMIN_MESSAGE] sender_role=ADMIN channel={channel} customer_id={sender_id}")
            
    return {"success": True, "message": "Reply delivered successfully"}

@app.post("/api/omnichat/toggle-ai")
async def api_toggle_chat_ai(request: Request):
    data = await request.json()
    cid = data.get("conversation_id")
    human_takeover = 0
    if cid:
        toggle_conversation_ai(cid)
        try:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT human_takeover, admin_takeover, ai_enabled FROM conversations WHERE id = ?", (cid,))
            row = c.fetchone()
            if row:
                human_takeover = row["human_takeover"]
            conn.close()
        except Exception:
            pass
    return {"success": True, "human_takeover": human_takeover}

@app.post("/api/omnichat/enable-ai")
@app.post("/api/conversations/enable-ai")
async def api_enable_chat_ai(request: Request):
    data = await request.json()
    cid = data.get("conversation_id")
    sender_id = data.get("sender_id")
    workspace_id = data.get("workspace_id", 1)
    new_version = enable_conversation_ai(sender_id=sender_id, conversation_id=cid, workspace_id=workspace_id, enabled_by="admin_ui")
    return {"success": True, "ai_enabled": True, "admin_takeover": False, "conversation_version": new_version}

# ==========================================
# WORKSPACE / BUSINESS MANAGEMENT APIS
# ==========================================
@app.get("/api/workspaces")
async def api_get_workspaces():
    """Lists all registered business workspaces."""
    workspaces = get_all_workspaces()
    return {"success": True, "workspaces": workspaces}

@app.get("/api/workspaces/{workspace_id}")
async def api_get_workspace(workspace_id: int):
    """Fetches details for a specific business workspace."""
    ws = get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"success": True, "workspace": ws}

@app.post("/api/workspaces")
async def api_create_workspace(request: Request):
    """Creates a new business workspace."""
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Workspace name is required")
    ws_id = save_workspace(data)
    return {"success": True, "id": ws_id, "message": "Workspace created successfully"}

@app.put("/api/workspaces/{workspace_id}")
async def api_update_workspace(workspace_id: int, request: Request):
    """Updates an existing business workspace."""
    data = await request.json()
    data["id"] = workspace_id
    save_workspace(data)
    return {"success": True, "message": "Workspace updated successfully"}

@app.delete("/api/workspaces/{workspace_id}")
async def api_delete_workspace(workspace_id: int):
    """Deletes a business workspace (Protected: Workspace 1 cannot be deleted)."""
    if int(workspace_id) == 1:
        raise HTTPException(status_code=400, detail="Cannot delete protected primary Workspace (RS Graphics)")
    ok = delete_workspace(workspace_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to delete workspace")
    return {"success": True, "message": "Workspace deleted successfully"}

@app.get("/api/workspaces/{workspace_id}/ai-config")
async def api_get_workspace_ai_config(workspace_id: int):
    """Gets AI instructions and personality config for a specific workspace."""
    config = get_page_ai_config(workspace_id=workspace_id)
    return {"success": True, "config": config}

@app.post("/api/workspaces/{workspace_id}/ai-config")
async def api_update_workspace_ai_config(workspace_id: int, request: Request):
    """Updates AI instructions and personality config for a specific workspace."""
    data = await request.json()
    ws = get_workspace(workspace_id) or {"id": workspace_id}
    ws["shop_name"] = data.get("shop_name", ws.get("shop_name", ""))
    ws["shop_phone"] = data.get("shop_phone", ws.get("shop_phone", ""))
    ws["shop_address"] = data.get("shop_address", ws.get("shop_address", ""))
    ws["delivery_inside_dhaka"] = data.get("delivery_inside_dhaka", ws.get("delivery_inside_dhaka", 70.0))
    ws["delivery_outside_dhaka"] = data.get("delivery_outside_dhaka", ws.get("delivery_outside_dhaka", 130.0))
    ws["ai_system_prompt"] = data.get("ai_system_prompt", ws.get("ai_system_prompt", ""))
    ai_en = int(data.get("ai_enabled", ws.get("ai_enabled", 1)))
    ws["ai_enabled"] = ai_en
    save_workspace(ws)
    if ai_en == 0:
        from app.channels.debouncer import message_debouncer
        message_debouncer.cancel_workspace_batches(workspace_id)
    return {"success": True, "message": "Workspace AI settings updated successfully"}

# ==========================================
# MULTI-PAGE MANAGEMENT APIS
# ==========================================

@app.get("/api/pages")
async def api_get_connected_pages():
    """Lists all connected Facebook Pages with their linked WhatsApp status (tokens masked)."""
    pages = get_all_connected_pages()
    sanitized = []
    for p in pages:
        p_copy = dict(p)
        raw_tok = str(p_copy.get("page_access_token", "") or "")
        p_copy["page_access_token"] = f"{raw_tok[:6]}...{raw_tok[-4:]}" if len(raw_tok) > 12 else ("********" if raw_tok else "")
        p_copy["has_token"] = bool(raw_tok and len(raw_tok) > 10)
        sanitized.append(p_copy)
    return {"success": True, "pages": sanitized}

@app.post("/api/pages/connect")
async def api_connect_page(request: Request):
    """Adds or updates a connected Facebook Page record."""
    data = await request.json()
    page_id = data.get("page_id", "").strip()
    page_name = data.get("page_name", "").strip() or "Facebook Page"
    page_token = data.get("page_access_token", "").strip()

    if not page_id or not page_token:
        raise HTTPException(status_code=400, detail="page_id and page_access_token are required")

    page_pk = save_connected_page(data)
    
    # Also optionally connect WhatsApp number if provided
    wa_phone_id = data.get("whatsapp_phone_number_id", "").strip()
    if wa_phone_id:
        save_whatsapp_account({
            "connected_page_id": page_pk,
            "waba_id": data.get("whatsapp_waba_id", ""),
            "phone_number_id": wa_phone_id,
            "display_phone_number": data.get("whatsapp_display_phone_number", ""),
            "access_token": data.get("whatsapp_access_token", "") or page_token,
            "connection_status": "connected",
            "coexistence_active": 1
        })

    return {"success": True, "message": f"Page '{page_name}' connected successfully!", "id": page_pk}

@app.post("/api/pages/{page_id}/edit")
async def api_edit_page(page_id: str, request: Request):
    """Updates page-level AI settings, shop name, delivery fees, and prompt."""
    try:
        data = await request.json()
        data["page_id"] = str(page_id).strip()
        page_token = str(data.get("page_access_token") or "").strip()
        page_pk = save_connected_page(data)

        # If a new token was passed, sync settings and auto-subscribe webhooks
        if page_token:
            set_setting("fb_page_access_token", page_token)
            set_setting("fb_page_id", str(page_id).strip())
            try:
                subscribe_facebook_page_webhooks(page_id, page_token)
            except Exception as e:
                print(f"[Auto-Subscribe on Page Edit Exception]: {e}")

        return {"success": True, "message": "Page settings updated successfully", "id": page_pk}
    except Exception as e:
        print(f"[api_edit_page Error]: {e}")
        return {"success": False, "error": str(e), "message": f"Update failed: {e}"}

@app.delete("/api/pages/{page_id}")
async def api_disconnect_page(page_id: str):
    """Disconnects a page connection safely without removing conversation history."""
    ok = delete_connected_page(page_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"success": True, "message": "Page disconnected successfully"}

@app.get("/api/pages/{page_id}/whatsapp")
async def api_get_page_whatsapp(page_id: str):
    """Gets WhatsApp connection status for a specific Page (tokens masked)."""
    wa_acc = get_whatsapp_account_by_page_id(page_id)
    if wa_acc:
        wa_acc = dict(wa_acc)
        raw_tok = str(wa_acc.get("access_token", "") or "")
        wa_acc["access_token"] = f"{raw_tok[:6]}...{raw_tok[-4:]}" if len(raw_tok) > 12 else ("********" if raw_tok else "")
        wa_acc["has_token"] = bool(raw_tok and len(raw_tok) > 10)
    return {"success": True, "whatsapp": wa_acc}

@app.post("/api/pages/{page_id}/whatsapp/connect")
async def api_connect_page_whatsapp(page_id: str, request: Request):
    """Links or saves WhatsApp Business credentials for a specific Page."""
    data = await request.json()
    data["page_id"] = page_id
    wa_pk = save_whatsapp_account(data)
    return {"success": True, "message": "WhatsApp Business connected to page successfully", "id": wa_pk}

@app.post("/api/pages/{page_id}/whatsapp/disconnect")
async def api_disconnect_page_whatsapp(page_id: str):
    """Unlinks WhatsApp Business account from a specific Page."""
    wa_acc = get_whatsapp_account_by_page_id(page_id)
    if wa_acc:
        delete_whatsapp_account(wa_acc["phone_number_id"])
    return {"success": True, "message": "WhatsApp Business disconnected from page"}

@app.post("/api/meta/user-pages")
async def api_fetch_meta_user_pages(request: Request):
    """Fetches user managed Pages via Meta Graph API using user access token for 1-click Page selection."""
    data = await request.json()
    user_token = data.get("user_access_token", "").strip()
    if not user_token:
        raise HTTPException(status_code=400, detail="user_access_token is required")

    try:
        url = "https://graph.facebook.com/v19.0/me/accounts?fields=id,name,access_token,category,tasks"
        r = requests.get(url, params={"access_token": user_token}, timeout=10)
        if r.status_code == 200:
            pages = r.json().get("data", [])
            return {"success": True, "pages": pages}
        else:
            return JSONResponse(status_code=r.status_code, content={"success": False, "error": r.text})
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

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
    if "blacklisted_ai_numbers" not in all_s:
        all_s["blacklisted_ai_numbers"] = get_setting("blacklisted_ai_numbers", "")
    voices = list_available_voices()
    return {"settings": all_s, "voices": voices}

@app.post("/api/settings")
async def api_save_settings(request: Request):
    data = await request.json()
    for k, v in data.items():
        set_setting(k, str(v))
    
    # Immediately cancel any pending in-flight batches if global AI Master switch was turned OFF
    if "ai_enabled" in data:
        val = str(data["ai_enabled"]).lower()
        if val == "false":
            from app.channels.debouncer import message_debouncer
            message_debouncer.cancel_all_batches()
            print("[MASTER_SWITCH_AI_DISABLED] Global AI Master Switch turned OFF. All in-flight debouncer batches cancelled.")
        else:
            print("[MASTER_SWITCH_AI_ENABLED] Global AI Master Switch turned ON.")

    # Sync WhatsApp accounts if credentials updated
    if any(k in data for k in ["whatsapp_access_token", "meta_system_user_access_token", "whatsapp_phone_number_id", "whatsapp_waba_id"]):
        clear_token_validation_cache()
        ensure_whatsapp_account_consistency()

    # Sync Facebook connected pages if credentials updated
    if any(k in data for k in ["fb_page_id", "fb_page_access_token"]):
        ensure_facebook_page_consistency()
        try:
            subscribe_facebook_page_webhooks()
        except Exception as sub_e:
            print(f"[Facebook Auto-Subscribe Settings Exception]: {sub_e}")

    return {"success": True, "message": "Settings updated successfully"}

# Dedicated Facebook Webhook Subscription & Diagnostic Endpoints
@app.get("/api/facebook/status")
async def api_facebook_status():
    """Returns live connection, verification, and webhook subscription status of the Facebook Page."""
    details = get_fb_page_details()
    return {"success": True, "details": details}

@app.post("/api/facebook/subscribe")
async def api_facebook_subscribe():
    """Forces subscription of the Facebook Page to Meta Webhook events (feed, messages)."""
    res = subscribe_facebook_page_webhooks()
    return res

@app.post("/api/facebook/test-comment-reply")
async def api_test_comment_reply(request: Request):
    """Sends a public reply to a specific comment ID for testing."""
    data = await request.json()
    comment_id = data.get("comment_id", "").strip()
    message = data.get("message", "").strip() or "ধন্যবাদ! এটি RS AI Agent-এর একটি স্বয়ংক্রিয় টেস্ট কমেন্ট রিপ্লাই।"
    page_id = data.get("page_id", "").strip() or None
    page_token = data.get("page_access_token", "").strip() or None

    if not comment_id:
        raise HTTPException(status_code=400, detail="comment_id is required")

    success, response_data = reply_to_fb_comment_detailed(comment_id, message, page_token=page_token, page_id=page_id)
    return {
        "success": success,
        "comment_id": comment_id,
        "message": "Comment reply successfully sent to Facebook Graph API!" if success else "Failed to send comment reply to Facebook Graph API.",
        "details": response_data
    }

@app.delete("/api/comment-logs/clear-sample")
async def api_clear_sample_comment_logs():
    """Clears legacy dummy/sample comment logs so the dashboard only shows real activity."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM comment_logs WHERE post_id IN ('post_777', 'post_888') OR user_id IN ('user_123', 'user_456')")
        conn.commit()
        return {"success": True, "message": "Sample comment logs cleared successfully."}
    finally:
        conn.close()

# Dedicated Muted / Blacklisted Contacts Endpoints
@app.get("/api/muted-contacts")
async def api_get_muted_contacts():
    contacts = get_muted_contacts_detailed()
    raw_numbers = get_muted_numbers()
    return {"success": True, "contacts": contacts, "numbers": raw_numbers}

@app.post("/api/muted-contacts/add")
async def api_add_muted_contact(request: Request):
    data = await request.json()
    phone = data.get("phone", "")
    updated_numbers = add_muted_number(phone)
    contacts = get_muted_contacts_detailed()
    return {"success": True, "message": f"{phone} মিউট লিস্টে যুক্ত হয়েছে", "contacts": contacts, "numbers": updated_numbers}

@app.post("/api/muted-contacts/remove")
async def api_remove_muted_contact(request: Request):
    data = await request.json()
    phone = data.get("phone", "")
    updated_numbers = remove_muted_number(phone)
    contacts = get_muted_contacts_detailed()
    return {"success": True, "message": f"{phone} আন-মিউট করা হয়েছে", "contacts": contacts, "numbers": updated_numbers}

# ==========================================
# DIAGNOSTICS & SYSTEM STATUS APIS
# ==========================================
@app.get("/api/diagnostics/meta")
async def api_diagnostics_meta():
    """
    Comprehensive, secure diagnostic endpoint returning Facebook Page and WhatsApp 
    configuration, routing health, and token status with sensitive tokens masked.
    """
    ensure_facebook_page_consistency()
    ensure_whatsapp_account_consistency()

    pages = get_all_connected_pages()
    whatsapp_accounts = get_all_whatsapp_accounts()

    def mask_tok(t):
        if not t:
            return ""
        t_s = str(t).strip()
        if len(t_s) <= 10:
            return "********"
        return f"{t_s[:6]}...{t_s[-4:]}"

    fb_diagnostics = []
    fb_w1_ready = False
    for p in pages:
        p_dict = dict(p)
        token = str(p_dict.get("page_access_token") or "").strip()
        page_id = str(p_dict.get("page_id") or "").strip()
        is_real_token = len(token) > 30 and not token.startswith("EAATest") and not token.startswith("EAA_")
        is_w1 = p_dict.get("workspace_id") == 1 or page_id == "105116472071659"
        
        diag = {
            "id": p_dict.get("id"),
            "workspace_id": p_dict.get("workspace_id"),
            "page_id": page_id,
            "page_name": p_dict.get("page_name"),
            "page_status": p_dict.get("page_status"),
            "token_present": bool(token),
            "token_masked": mask_tok(token),
            "token_length": len(token),
            "is_real_token": is_real_token,
            "page_mapping_valid": page_id not in ["rs_graphics_page_1", "default", ""] and len(page_id) >= 10
        }
        if is_w1 and diag["page_mapping_valid"]:
            fb_w1_ready = True
        fb_diagnostics.append(diag)

    wa_diagnostics = []
    wa_w1_ready = False
    for wa in whatsapp_accounts:
        wa_dict = dict(wa)
        token = str(wa_dict.get("access_token") or "").strip()
        phone_id = str(wa_dict.get("phone_number_id") or "").strip()
        is_real_token = len(token) > 30 and not token.startswith("EAATest") and not token.startswith("TOKEN_")
        is_w1 = wa_dict.get("workspace_id") == 1 or phone_id == "4184514263660680"

        api_test_status = None
        api_test_error = None
        if is_real_token and phone_id:
            try:
                r = requests.get(
                    f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{phone_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"fields": "id,display_phone_number,verified_name,quality_rating"},
                    timeout=3
                )
                if r.status_code == 200:
                    api_test_status = "valid"
                else:
                    err_j = r.json().get("error", {})
                    api_test_status = "error"
                    api_test_error = f"HTTP {r.status_code} ({err_j.get('type')}: {err_j.get('message')})"
            except Exception as ex:
                api_test_status = "unreachable"
                api_test_error = str(ex)

        diag = {
            "id": wa_dict.get("id"),
            "workspace_id": wa_dict.get("workspace_id"),
            "phone_number_id": phone_id,
            "display_phone_number": wa_dict.get("display_phone_number"),
            "waba_id": wa_dict.get("waba_id"),
            "connection_status": wa_dict.get("connection_status"),
            "token_present": bool(token),
            "token_masked": mask_tok(token),
            "token_length": len(token),
            "is_real_token": is_real_token,
            "phone_number_mapping_valid": phone_id == "4184514263660680" or (len(phone_id) >= 15 and phone_id.isdigit()),
            "token_api_check": api_test_status,
            "token_api_error": api_test_error
        }
        if is_w1 and diag["phone_number_mapping_valid"]:
            wa_w1_ready = True
        wa_diagnostics.append(diag)

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "meta_graph_version": settings.META_GRAPH_VERSION,
        "rs_graphics_workspace_1": {
            "canonical_facebook_page_id": "105116472071659",
            "facebook_ready": fb_w1_ready,
            "canonical_whatsapp_phone_id": settings.WHATSAPP_PHONE_NUMBER_ID,
            "canonical_whatsapp_waba_id": settings.WHATSAPP_WABA_ID,
            "whatsapp_ready": wa_w1_ready
        },
        "facebook": {
            "connected_pages_count": len(pages),
            "pages": fb_diagnostics
        },
        "whatsapp": {
            "accounts_count": len(whatsapp_accounts),
            "accounts": wa_diagnostics
        }
    }

@app.get("/api/diagnostics/whatsapp")
@app.get("/api/diagnostic/whatsapp")
async def api_get_diagnostics_whatsapp():
    """
    Dedicated diagnostic endpoint validating WhatsApp Phone Number ID (418451426636680 / 4184514263660680),
    WABA ID (271335301757320), token presence, token source, and live Meta Graph API read access.
    Never exposes raw tokens or full customer numbers.
    """
    ensure_whatsapp_account_consistency()
    
    wa_account = get_whatsapp_account_by_phone_id(settings.WHATSAPP_PHONE_NUMBER_ID)
    phone_id = wa_account.get("phone_number_id", settings.WHATSAPP_PHONE_NUMBER_ID) if wa_account else settings.WHATSAPP_PHONE_NUMBER_ID
    display_phone = wa_account.get("display_phone_number", "+8801816504097") if wa_account else "+8801816504097"
    waba_id = wa_account.get("waba_id", settings.WHATSAPP_WABA_ID) if wa_account else settings.WHATSAPP_WABA_ID

    token_info = resolve_whatsapp_token_info(wa_account=wa_account, workspace_id=1, phone_number_id=phone_id)
    clean_tok = token_info.get("token", "")
    token_source = token_info.get("source", "none")

    token_len = len(clean_tok)
    token_prefix = clean_tok[:6] if token_len > 6 else ""
    token_suffix = clean_tok[-4:] if token_len > 10 else ""

    meta_val = token_info.get("meta_validation") or validate_whatsapp_token_with_meta(token=clean_tok, phone_id=phone_id)
    ready_for_send = bool(token_info.get("is_valid") and meta_val.get("valid") and meta_val.get("phone_number_access"))
    validation_results = token_info.get("candidate_validation_results", [])
    candidate_sources = [c.get("source", "") for c in validation_results]

    return {
        "workspace_id": 1,
        "account_id": wa_account.get("id") if wa_account else 1,
        "phone_number_id": phone_id,
        "display_phone_number": display_phone,
        "waba_id": waba_id,
        "selected_token_source": token_source,
        "selected_token_valid": ready_for_send,
        "token_present": bool(clean_tok),
        "token_valid": ready_for_send,
        "token_preview": f"{token_prefix}...{token_suffix}" if token_len > 10 else "EMPTY/SHORT",
        "token_length": token_len,
        "graph_api_version": settings.META_GRAPH_VERSION,
        "endpoint_url": f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{phone_id}/messages",
        "ready_for_send": ready_for_send,
        "meta_validation": meta_val,
        "candidate_sources": candidate_sources,
        "candidate_validation_results": validation_results,
        "error_message": "" if ready_for_send else (token_info.get("reason") or "No valid WhatsApp Cloud API token is authorized for Phone Number ID 4184514263660680.")
    }

@app.post("/api/diagnostics/whatsapp/clear-cache")
async def api_diagnostics_whatsapp_clear_cache():
    """Explicitly clears the in-memory Meta Graph API validation cache."""
    clear_token_validation_cache()
    return {"success": True, "message": "Token validation cache cleared successfully."}

@app.post("/api/diagnostics/whatsapp/test-send")
async def api_diagnostics_whatsapp_test_send(request: Request):
    """
    Controlled diagnostic endpoint to test WhatsApp Cloud API delivery.
    Matches the proven Postman reference request:
    POST https://graph.facebook.com/v23.0/4184514263660680/messages
    Never exposes raw tokens.
    """
    data = await request.json()
    to_number = data.get("to_number", "").strip()
    message = data.get("message", "RS AI Agent WhatsApp Cloud API test message").strip()
    workspace_id = int(data.get("workspace_id", 1))

    if not to_number:
        raise HTTPException(status_code=400, detail="to_number is required (e.g. 8801929778581)")

    wa_acc = get_whatsapp_account_by_workspace_id(workspace_id)
    phone_id = wa_acc.get("phone_number_id", "4184514263660680") if wa_acc else "4184514263660680"

    result = send_whatsapp_message_detailed(
        to_number=to_number,
        message_text=message,
        phone_id=phone_id,
        workspace_id=workspace_id
    )

    masked_rec = f"{to_number[:5]}****{to_number[-4:]}" if len(to_number) > 8 else "***"
    return {
        "success": result.get("success", False),
        "workspace_id": workspace_id,
        "phone_number_id": phone_id,
        "recipient": masked_rec,
        "endpoint_url": f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{phone_id}/messages",
        "result": result
    }

@app.get("/api/diagnostics/facebook")
async def api_get_diagnostics_facebook():
    """
    Dedicated diagnostic endpoint validating Facebook Page (105116472071659),
    connected_pages mapping, token presence, and live Meta Graph API read access.
    """
    ensure_facebook_page_consistency()
    
    page = get_connected_page("105116472071659")
    token = page.get("page_access_token") if page else get_setting("fb_page_access_token")
    clean_tok = str(token or "").strip().strip('"').strip("'")
    if clean_tok.lower().startswith("bearer "):
        clean_tok = clean_tok[7:].strip()

    token_len = len(clean_tok)
    token_prefix = clean_tok[:6] if token_len > 6 else ""
    token_suffix = clean_tok[-4:] if token_len > 10 else ""

    is_real = len(clean_tok) > 30 and not clean_tok.startswith("EAATest") and not clean_tok.startswith("EAA_")
    
    meta_val = None
    if is_real:
        try:
            r = requests.get(
                f"https://graph.facebook.com/v19.0/105116472071659",
                headers={"Authorization": f"Bearer {clean_tok}"},
                params={"fields": "id,name,category,link"},
                timeout=5
            )
            if r.status_code == 200:
                meta_val = {"valid": True, "data": r.json()}
            else:
                meta_val = {"valid": False, "http_status": r.status_code, "error": r.json().get("error", {})}
        except Exception as ex:
            meta_val = {"valid": False, "error": str(ex)}

    return {
        "workspace_id": 1,
        "page_id": "105116472071659",
        "page_name": page.get("page_name", "RS Graphics (আরএস গ্রাফিক্স)") if page else "RS Graphics (আরএস গ্রাফিক্স)",
        "token_present": bool(clean_tok),
        "token_prefix": token_prefix,
        "token_suffix": token_suffix,
        "token_length": token_len,
        "is_real_token": is_real,
        "meta_graph_version": "v19.0",
        "endpoint_url": "https://graph.facebook.com/v19.0/me/messages",
        "ready_for_send": bool(meta_val and meta_val.get("valid")),
        "meta_validation": meta_val
    }

@app.get("/api/diagnostics")
async def api_get_diagnostics():
    """Safe admin diagnostic endpoint returning masked configuration for debugging."""
    workspaces = get_all_workspaces()
    pages = get_all_connected_pages()
    whatsapp_accounts = get_all_whatsapp_accounts()
    
    masked_pages = []
    for p in pages:
        p_dict = dict(p)
        tok = str(p_dict.get("page_access_token") or "")
        p_dict["page_access_token"] = f"{tok[:6]}...{tok[-4:]}" if len(tok) > 10 else ("********" if tok else "")
        masked_pages.append(p_dict)

    masked_wa = []
    for wa in whatsapp_accounts:
        wa_dict = dict(wa)
        tok = str(wa_dict.get("access_token") or "")
        wa_dict["access_token"] = f"{tok[:6]}...{tok[-4:]}" if len(tok) > 10 else ("********" if tok else "")
        masked_wa.append(wa_dict)

    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "workspaces": workspaces,
        "connected_pages": masked_pages,
        "whatsapp_accounts": masked_wa,
        "meta_cloud_settings": {
            "whatsapp_waba_id": get_setting("whatsapp_waba_id", settings.WHATSAPP_WABA_ID),
            "whatsapp_phone_number_id": get_setting("whatsapp_phone_number_id", settings.WHATSAPP_PHONE_NUMBER_ID),
            "whatsapp_display_phone_number": get_setting("whatsapp_display_phone_number", settings.WHATSAPP_DISPLAY_PHONE_NUMBER),
            "meta_app_id": get_setting("meta_app_id", settings.META_APP_ID),
            "has_whatsapp_access_token": bool(get_setting("whatsapp_access_token") or settings.WHATSAPP_ACCESS_TOKEN or get_setting("meta_system_user_access_token"))
        }
    }

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
            token_url = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/oauth/access_token"
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
            url = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{effective_waba}/phone_numbers?fields=id,display_phone_number,verified_name,quality_rating,status,code_verification_status"
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
        set_setting("whatsapp_connected_at", datetime.now(timezone.utc).isoformat())
        if matched_display_name:
            set_setting("whatsapp_verified_name", matched_display_name)
        if access_token:
            set_setting("whatsapp_access_token", str(access_token))

        # Subscribe app to webhooks
        try:
            sub_url = f"https://graph.facebook.com/{settings.META_GRAPH_VERSION}/{effective_waba}/subscribed_apps"
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
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(content={"status": "INVALID_JSON"}, status_code=400)
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
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(content={"status": "INVALID_JSON"}, status_code=400)
    background_tasks.add_task(handle_whatsapp_webhook_event, data)
    return JSONResponse(content={"status": "EVENT_RECEIVED"})
