import re
import json
import uuid
from datetime import datetime
from app.database import get_db_connection, get_setting

# Regular expression to extract Bangladeshi mobile numbers (e.g., 01712345678, +8801812345678, 01912-345678)
BD_PHONE_REGEX = r"(?:\+88\s?)?01[3-9]\d{2}[-\s]?\d{6}"

def extract_phone_number(text: str) -> str:
    """Finds and formats a valid Bangladeshi 11-digit mobile number."""
    if not text:
        return ""
    matches = re.findall(BD_PHONE_REGEX, text)
    if matches:
        # Standardize to 11 digits (01XXXXXXXXX)
        clean = re.sub(r"[^\d]", "", matches[0])
        if clean.startswith("880"):
            clean = clean[2:]
        if len(clean) == 11 and clean.startswith("01"):
            return clean
    return ""

def is_dhaka_address(address: str) -> bool:
    """Checks if the address is inside Dhaka or outside Dhaka."""
    if not address:
        return True
    dhaka_keywords = [
        "dhaka", "ঢাকা", "dhanmondi", "ধানমন্ডি", "mirpur", "মিরপুর", "uttara", "উত্তরা",
        "gulshan", "গুলশান", "banani", "বনানী", "mohammadpur", "মোহাম্মদপুর", "badda", "বাড্ডা",
        "motijheel", "মতিঝিল", "jatrabari", "যাত্রাবাড়ী", "khilgaon", "খিলগাঁও", "rampura", "রামপুরা",
        "basundhara", "বসুন্ধরা", "malibagh", "মালিবাগ", "farmgate", "ফার্মগেট", "wari", "ওয়ারী"
    ]
    addr_lower = address.lower()
    return any(k in addr_lower for k in dhaka_keywords)

def calculate_order_totals(items: list, address: str) -> tuple[float, float, float]:
    """Calculates subtotal, delivery charge, and total amount."""
    subtotal = 0.0
    for item in items:
        price = float(item.get("price", 0))
        qty = int(item.get("qty", 1))
        subtotal += price * qty

    inside_fee = float(get_setting("delivery_inside_dhaka", "70"))
    outside_fee = float(get_setting("delivery_outside_dhaka", "130"))

    delivery_charge = inside_fee if is_dhaka_address(address) else outside_fee
    total_amount = subtotal + delivery_charge
    return subtotal, delivery_charge, total_amount

def create_order(
    customer_name: str,
    customer_phone: str,
    customer_address: str,
    items: list,
    channel: str = "facebook",
    sender_id: str = "",
    notes: str = ""
) -> dict:
    """Creates and saves a new customer order into SQLite database."""
    subtotal, delivery_charge, total_amount = calculate_order_totals(items, customer_address)
    
    # Generate Unique Order Code (e.g., PW-260819-4821)
    timestamp = datetime.now().strftime("%y%m%d")
    random_id = uuid.uuid4().hex[:4].upper()
    order_code = f"PW-{timestamp}-{random_id}"

    items_summary_list = []
    for itm in items:
        name = itm.get("name", "Product")
        qty = itm.get("qty", 1)
        price = itm.get("price", 0)
        size = f" ({itm['size']})" if itm.get("size") else ""
        color = f" [{itm['color']}]" if itm.get("color") else ""
        items_summary_list.append(f"{name}{size}{color} x {qty} = {price*qty}৳")
    
    items_summary = ", ".join(items_summary_list) if items_summary_list else "1x Product"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO orders (
            order_code, customer_name, customer_phone, customer_address,
            items_summary, items_json, subtotal, delivery_charge, total_amount,
            channel, sender_id, status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_code,
        customer_name,
        customer_phone,
        customer_address,
        items_summary,
        json.dumps(items, ensure_ascii=False),
        subtotal,
        delivery_charge,
        total_amount,
        channel,
        sender_id,
        "Pending",
        notes
    ))
    order_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "id": order_id,
        "order_code": order_code,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_address": customer_address,
        "items_summary": items_summary,
        "subtotal": subtotal,
        "delivery_charge": delivery_charge,
        "total_amount": total_amount,
        "status": "Pending"
    }

def update_order_status(order_id: int, new_status: str) -> bool:
    """Updates order status: Pending -> Confirmed -> Shipped -> Delivered -> Cancelled."""
    valid_statuses = ["Pending", "Confirmed", "Processing", "Shipped", "Delivered", "Cancelled"]
    if new_status not in valid_statuses:
        return False

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    conn.close()
    return True

def list_orders(status: str = None, search: str = None) -> list:
    """Fetches orders with optional filtering."""
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM orders WHERE 1=1"
    params = []

    if status and status != "All":
        query += " AND status = ?"
        params.append(status)

    if search:
        query += " AND (order_code LIKE ? OR customer_name LIKE ? OR customer_phone LIKE ? OR customer_address LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term, term])

    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
