from app.database import get_db_connection

def record_conversation_message(channel: str, sender_id: str, customer_name: str, sender_type: str, content: str, media_url: str = ""):
    """Saves incoming and outgoing messages to conversations & messages table."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if conversation exists
        cursor.execute("SELECT id, customer_name FROM conversations WHERE sender_id = ?", (sender_id,))
        row = cursor.fetchone()
        
        preview_text = content if content else ("[Image]" if media_url else "")

        if row:
            conv_id = row["id"]
            cust_name = row["customer_name"] if row["customer_name"] and row["customer_name"] not in ["Facebook User", "Customer", ""] else customer_name
            cursor.execute("""
                UPDATE conversations 
                SET last_message = ?, customer_name = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (preview_text, cust_name, conv_id))
        else:
            cursor.execute("""
                INSERT INTO conversations (channel, sender_id, customer_name, last_message)
                VALUES (?, ?, ?, ?)
            """, (channel, sender_id, customer_name, preview_text))
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

def get_conversation_history(channel: str, sender_id: str, limit: int = 8) -> list:
    """Fetches recent conversation messages for Gemini AI context."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
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
