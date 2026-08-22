from typing import Optional
from app.database import get_db_connection

def get_all_conversations(workspace_id: Optional[int] = None, page_id: str = None, channel: str = None) -> list:
    """Returns all active conversations sorted by updated_at with linked Page & Workspace info."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT c.id, c.channel, c.sender_id, c.customer_name, c.last_message, c.human_takeover, c.updated_at, c.page_id, c.workspace_id,
                   COALESCE(cp.page_name, cp.shop_name, w.name, 'RS Graphics') as page_name,
                   w.name as workspace_name
            FROM conversations c
            LEFT JOIN connected_pages cp ON c.page_id = cp.page_id
            LEFT JOIN workspaces w ON c.workspace_id = w.id
            WHERE 1=1
        """
        params = []
        if workspace_id:
            query += " AND c.workspace_id = ?"
            params.append(int(workspace_id))
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
            SELECT id, conversation_id, sender_type, message_type, content, media_url,
                   direction, sender_role, source, external_message_id, turn_version, created_at
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

def record_conversation_message(
    channel: str,
    sender_id: str,
    customer_name: str,
    sender_type: str,
    content: str = "",
    media_url: str = "",
    page_id: str = "",
    workspace_id: int = 1,
    external_message_id: str = "",
    direction: str = None,
    sender_role: str = None,
    source: str = None
):
    """Saves incoming and outgoing messages to conversations & messages table scoped strictly to workspace."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ws_id = int(workspace_id or 1)
        normalized_sender_type = str(sender_type or "user").strip().lower()
        
        if normalized_sender_type in ["admin", "owner", "main_admin", "seller"]:
            normalized_sender_type = "admin"
            actual_sender_role = sender_role or "ADMIN"
            actual_direction = direction or "OUTBOUND"
        elif normalized_sender_type in ["bot", "assistant", "ai"]:
            normalized_sender_type = "bot"
            actual_sender_role = sender_role or "AI"
            actual_direction = direction or "OUTBOUND"
        elif normalized_sender_type in ["system"]:
            normalized_sender_type = "system"
            actual_sender_role = sender_role or "SYSTEM"
            actual_direction = direction or "OUTBOUND"
        else:
            normalized_sender_type = "user"
            actual_sender_role = sender_role or "CUSTOMER"
            actual_direction = direction or "INBOUND"
            
        is_admin_msg = (actual_sender_role == "ADMIN" or normalized_sender_type == "admin")
        is_customer_msg = (actual_sender_role == "CUSTOMER" and actual_direction == "INBOUND")
        actual_source = source or channel.upper()
        
        # Check if conversation exists scoped to this workspace
        cursor.execute("""
            SELECT id, customer_name, page_id, workspace_id, conversation_version, customer_turn_version
            FROM conversations
            WHERE sender_id = ? AND workspace_id = ?
            ORDER BY id DESC LIMIT 1
        """, (sender_id, ws_id))
        row = cursor.fetchone()
        
        preview_text = content if content else ("[Image]" if media_url else "")
        current_turn_version = 1

        if row:
            conv_id = row["id"]
            cust_name = row["customer_name"] if row["customer_name"] and row["customer_name"] not in ["Facebook User", "Customer", ""] else customer_name
            if is_admin_msg:
                cursor.execute("""
                    UPDATE conversations 
                    SET last_message = ?, customer_name = ?, page_id = COALESCE(NULLIF(?, ''), page_id),
                        admin_takeover = 1, human_takeover = 1, ai_enabled = 0,
                        takeover_at = CURRENT_TIMESTAMP, takeover_by = 'main_admin', takeover_reason = 'human_admin_message',
                        conversation_version = COALESCE(conversation_version, 1) + 1,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (preview_text, cust_name, str(page_id) if page_id else None, conv_id))
                current_turn_version = row["customer_turn_version"] or 1
            elif is_customer_msg:
                cursor.execute("""
                    UPDATE conversations 
                    SET last_message = ?, customer_name = ?, page_id = COALESCE(NULLIF(?, ''), page_id),
                        customer_turn_version = COALESCE(customer_turn_version, 1) + 1,
                        updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (preview_text, cust_name, str(page_id) if page_id else None, conv_id))
                current_turn_version = (row["customer_turn_version"] or 1) + 1
            else:
                cursor.execute("""
                    UPDATE conversations 
                    SET last_message = ?, customer_name = ?, page_id = COALESCE(NULLIF(?, ''), page_id), updated_at = CURRENT_TIMESTAMP 
                    WHERE id = ?
                """, (preview_text, cust_name, str(page_id) if page_id else None, conv_id))
                current_turn_version = row["customer_turn_version"] or 1
        else:
            if is_admin_msg:
                cursor.execute("""
                    INSERT INTO conversations (
                        workspace_id, channel, sender_id, customer_name, last_message, page_id,
                        admin_takeover, human_takeover, ai_enabled, takeover_at, takeover_by, takeover_reason, conversation_version,
                        customer_turn_version, last_responded_turn_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, 1, 0, CURRENT_TIMESTAMP, 'main_admin', 'human_admin_message', 2, 1, 0)
                """, (ws_id, channel, sender_id, customer_name, preview_text, str(page_id) if page_id else ""))
                current_turn_version = 1
            elif is_customer_msg:
                cursor.execute("""
                    INSERT INTO conversations (
                        workspace_id, channel, sender_id, customer_name, last_message, page_id,
                        customer_turn_version, last_responded_turn_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, 0)
                """, (ws_id, channel, sender_id, customer_name, preview_text, str(page_id) if page_id else ""))
                current_turn_version = 1
            else:
                cursor.execute("""
                    INSERT INTO conversations (workspace_id, channel, sender_id, customer_name, last_message, page_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (ws_id, channel, sender_id, customer_name, preview_text, str(page_id) if page_id else ""))
                current_turn_version = 1
            conv_id = cursor.lastrowid
            
        # Insert message with full role, direction, source, and processing status
        msg_type = "image" if media_url else "text"
        proc_status = "RECEIVED" if is_customer_msg else "PROCESSED"
        cursor.execute("""
            INSERT INTO messages (
                conversation_id, sender_type, message_type, content, media_url,
                sender_role, direction, source, processing_status, external_message_id, turn_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            conv_id, normalized_sender_type, msg_type, content, media_url,
            actual_sender_role, actual_direction, actual_source, proc_status,
            str(external_message_id or ""), current_turn_version
        ))
        
        conn.commit()
        
        # If admin message, also add to muted numbers & cancel pending batches
        if is_admin_msg and sender_id:
            from app.database import add_muted_number
            add_muted_number(str(sender_id))
            try:
                from app.channels.debouncer import message_debouncer
                message_debouncer.cancel_batch(channel, ws_id, sender_id)
            except Exception:
                pass
                
        return conv_id
    except Exception as e:
        print(f"[Omnichat Record Error]: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_conversation_history(channel: str = "all", sender_id: str = "", limit: int = 8, page_id: str = "", workspace_id: int = 1) -> list:
    """Fetches recent conversation messages for Gemini AI context scoped strictly to workspace."""
    # Handle single string positional argument as sender_id for convenience
    if sender_id == "" and channel:
        sender_id = channel
        channel = "all"
        
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        ws_id = int(workspace_id or 1)
        
        cursor.execute("""
            SELECT m.sender_type, m.content, m.media_url, m.created_at,
                   m.direction, m.sender_role, m.source, m.external_message_id, m.turn_version
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            WHERE c.sender_id = ? AND c.workspace_id = ?
            ORDER BY m.id DESC LIMIT ?
        """, (sender_id, ws_id, limit))
            
        rows = cursor.fetchall()
        history = [dict(r) for r in reversed(rows)]
        return history
    except Exception as e:
        print(f"[Omnichat History Error]: {e}")
        return []
    finally:
        if conn:
            conn.close()



