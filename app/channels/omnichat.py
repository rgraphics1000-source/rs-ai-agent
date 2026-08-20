from app.database import get_db_connection

def get_all_conversations(page_id: str = None, channel: str = None) -> list:
    """Returns all active conversations sorted by updated_at with linked Page info."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT c.id, c.channel, c.sender_id, c.customer_name, c.last_message, c.human_takeover, c.updated_at, c.page_id,
                   COALESCE(cp.page_name, cp.shop_name, 'RS Graphics') as page_name
            FROM conversations c
            LEFT JOIN connected_pages cp ON c.page_id = cp.page_id
            WHERE 1=1
        """
        params = []
        if page_id:
            query += " AND c.page_id = ?"
            params.append(str(page_id))
        if channel:
            query += " AND c.channel = ?"
            params.append(str(channel))
            
        query += " ORDER BY c.updated_at DESC"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[Omnichat Get All Error]: {e}")
        return []

def get_conversation_messages(conversation_id: int) -> list:
    """Returns all messages for a specific conversation."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, conversation_id, sender_type, message_type, content, media_url, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
        """, (conversation_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[Omnichat Get Messages Error]: {e}")
        return []

def send_whatsapp_media(to_number: str, media_url: str, phone_id: str = None, page_id: str = None) -> bool:
    """Sends image attachment via WhatsApp using specific account."""
    from app.channels.whatsapp import send_whatsapp_image
    return send_whatsapp_image(to_number, media_url, phone_id=phone_id, page_id=page_id)

def send_whatsapp_audio(to_number: str, audio_url: str, phone_id: str = None, page_id: str = None) -> bool:
    """Sends voice note via WhatsApp using specific account."""
    from app.channels.whatsapp import send_whatsapp_audio as wa_send_audio
    return wa_send_audio(to_number, audio_url, phone_id=phone_id, page_id=page_id)

def send_whatsapp_video(to_number: str, video_url: str, phone_id: str = None, page_id: str = None) -> bool:
    """Sends video via WhatsApp using specific account."""
    from app.channels.whatsapp import send_whatsapp_video as wa_send_video
    return wa_send_video(to_number, video_url, phone_id=phone_id, page_id=page_id)

def record_conversation_message(channel: str, sender_id: str, customer_name: str, sender_type: str, content: str, media_url: str = "", page_id: str = ""):
    """Saves incoming and outgoing messages to conversations & messages table scoped by page_id."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if conversation exists scoped to this page
        if page_id:
            cursor.execute("SELECT id, customer_name, page_id FROM conversations WHERE sender_id = ? AND (page_id = ? OR page_id = '' OR page_id IS NULL) ORDER BY id DESC LIMIT 1", (sender_id, str(page_id)))
        else:
            cursor.execute("SELECT id, customer_name, page_id FROM conversations WHERE sender_id = ? ORDER BY id DESC LIMIT 1", (sender_id,))
        row = cursor.fetchone()
        
        preview_text = content if content else ("[Image]" if media_url else "")

        if row:
            conv_id = row["id"]
            cust_name = row["customer_name"] if row["customer_name"] and row["customer_name"] not in ["Facebook User", "Customer", ""] else customer_name
            cursor.execute("""
                UPDATE conversations 
                SET last_message = ?, customer_name = ?, page_id = COALESCE(NULLIF(?, ''), page_id), updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (preview_text, cust_name, str(page_id) if page_id else None, conv_id))
        else:
            cursor.execute("""
                INSERT INTO conversations (channel, sender_id, customer_name, last_message, page_id)
                VALUES (?, ?, ?, ?, ?)
            """, (channel, sender_id, customer_name, preview_text, str(page_id) if page_id else ""))
            conv_id = cursor.lastrowid
            
        # Insert message
        msg_type = "image" if media_url else "text"
        cursor.execute("""
            INSERT INTO messages (conversation_id, sender_type, message_type, content, media_url)
            VALUES (?, ?, ?, ?, ?)
        """, (conv_id, sender_type, msg_type, content, media_url))
        
        conn.commit()
        conn.close()
        return conv_id
    except Exception as e:
        print(f"[Omnichat Record Error]: {e}")
        return None

def get_conversation_history(channel: str, sender_id: str, limit: int = 8, page_id: str = "") -> list:
    """Fetches recent conversation messages for Gemini AI context scoped to page."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if page_id:
            cursor.execute("""
                SELECT m.sender_type, m.content, m.media_url, m.created_at
                FROM messages m
                JOIN conversations c ON m.conversation_id = c.id
                WHERE c.sender_id = ? AND (c.page_id = ? OR c.page_id = '' OR c.page_id IS NULL)
                ORDER BY m.id DESC LIMIT ?
            """, (sender_id, str(page_id), limit))
        else:
            cursor.execute("""
                SELECT m.sender_type, m.content, m.media_url, m.created_at
                FROM messages m
                JOIN conversations c ON m.conversation_id = c.id
                WHERE c.sender_id = ?
                ORDER BY m.id DESC LIMIT ?
            """, (sender_id, limit))
            
        rows = cursor.fetchall()
        conn.close()
        history = [dict(r) for r in reversed(rows)]
        return history
    except Exception as e:
        print(f"[Omnichat History Error]: {e}")
        return []


