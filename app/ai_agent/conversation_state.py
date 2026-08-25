"""
RS Graphics AI Agent - Persistent Conversation State Machine (Phase 2)
Handles structured, persistent conversation state tracking for business workflows.
Enforces valid state transitions, quantity/package memory, sample status, and audit logging.
"""

import json
import sqlite3
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone


class SalesStage(str, Enum):
    NEW = "NEW"
    SERVICE_IDENTIFIED = "SERVICE_IDENTIFIED"
    QUANTITY_PENDING = "QUANTITY_PENDING"
    QUANTITY_IDENTIFIED = "QUANTITY_IDENTIFIED"
    MOQ_REJECTED = "MOQ_REJECTED"
    PACKAGE_PENDING = "PACKAGE_PENDING"
    PACKAGE_IDENTIFIED = "PACKAGE_IDENTIFIED"
    PRICE_READY = "PRICE_READY"
    SAMPLE_PERMISSION_PENDING = "SAMPLE_PERMISSION_PENDING"
    SAMPLE_SENT = "SAMPLE_SENT"
    ORDER_INTENT = "ORDER_INTENT"
    ADVANCE_PENDING = "ADVANCE_PENDING"
    ADVANCE_CONFIRMED = "ADVANCE_CONFIRMED"
    CUSTOMER_INFO_PENDING = "CUSTOMER_INFO_PENDING"
    CUSTOMER_INFO_COMPLETE = "CUSTOMER_INFO_COMPLETE"
    DESIGN_PROCESSING = "DESIGN_PROCESSING"
    PROOF_PENDING = "PROOF_PENDING"
    PROOF_SENT = "PROOF_SENT"
    CUSTOMER_CORRECTION = "CUSTOMER_CORRECTION"
    FINAL_APPROVAL_PENDING = "FINAL_APPROVAL_PENDING"
    FINAL_APPROVED = "FINAL_APPROVED"
    PRINTING = "PRINTING"
    COURIER = "COURIER"
    DELIVERED = "DELIVERED"
    OWNER_TAKEOVER = "OWNER_TAKEOVER"
    CLOSED = "CLOSED"


# Allowed state transitions map
VALID_TRANSITIONS: Dict[str, List[str]] = {
    SalesStage.NEW: [
        SalesStage.SERVICE_IDENTIFIED,
        SalesStage.QUANTITY_PENDING,
        SalesStage.QUANTITY_IDENTIFIED,
        SalesStage.MOQ_REJECTED,
        SalesStage.PACKAGE_PENDING,
        SalesStage.PACKAGE_IDENTIFIED,
        SalesStage.PRICE_READY,
        SalesStage.SAMPLE_PERMISSION_PENDING,
        SalesStage.SAMPLE_SENT,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.SERVICE_IDENTIFIED: [
        SalesStage.QUANTITY_PENDING,
        SalesStage.QUANTITY_IDENTIFIED,
        SalesStage.MOQ_REJECTED,
        SalesStage.PACKAGE_PENDING,
        SalesStage.PACKAGE_IDENTIFIED,
        SalesStage.SAMPLE_PERMISSION_PENDING,
        SalesStage.SAMPLE_SENT,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.QUANTITY_PENDING: [
        SalesStage.QUANTITY_IDENTIFIED,
        SalesStage.MOQ_REJECTED,
        SalesStage.PACKAGE_PENDING,
        SalesStage.PACKAGE_IDENTIFIED,
        SalesStage.SAMPLE_PERMISSION_PENDING,
        SalesStage.SAMPLE_SENT,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.QUANTITY_IDENTIFIED: [
        SalesStage.QUANTITY_IDENTIFIED,  # Quantity revision
        SalesStage.MOQ_REJECTED,
        SalesStage.PACKAGE_PENDING,
        SalesStage.PACKAGE_IDENTIFIED,
        SalesStage.PRICE_READY,
        SalesStage.SAMPLE_PERMISSION_PENDING,
        SalesStage.SAMPLE_SENT,
        SalesStage.ORDER_INTENT,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.MOQ_REJECTED: [
        SalesStage.QUANTITY_IDENTIFIED,  # Customer revised quantity to >= 30
        SalesStage.PACKAGE_PENDING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.PACKAGE_PENDING: [
        SalesStage.QUANTITY_IDENTIFIED,
        SalesStage.PACKAGE_IDENTIFIED,
        SalesStage.PRICE_READY,
        SalesStage.SAMPLE_PERMISSION_PENDING,
        SalesStage.SAMPLE_SENT,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.PACKAGE_IDENTIFIED: [
        SalesStage.PACKAGE_IDENTIFIED,  # Package change
        SalesStage.QUANTITY_IDENTIFIED, # Quantity change
        SalesStage.PRICE_READY,
        SalesStage.SAMPLE_PERMISSION_PENDING,
        SalesStage.SAMPLE_SENT,
        SalesStage.ORDER_INTENT,
        SalesStage.ADVANCE_PENDING,
        SalesStage.CUSTOMER_INFO_PENDING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.PRICE_READY: [
        SalesStage.QUANTITY_IDENTIFIED,
        SalesStage.PACKAGE_IDENTIFIED,
        SalesStage.SAMPLE_PERMISSION_PENDING,
        SalesStage.SAMPLE_SENT,
        SalesStage.ORDER_INTENT,
        SalesStage.ADVANCE_PENDING,
        SalesStage.CUSTOMER_INFO_PENDING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.SAMPLE_PERMISSION_PENDING: [
        SalesStage.QUANTITY_IDENTIFIED,
        SalesStage.MOQ_REJECTED,
        SalesStage.SAMPLE_SENT,
        SalesStage.PACKAGE_IDENTIFIED,
        SalesStage.ORDER_INTENT,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.SAMPLE_SENT: [
        SalesStage.QUANTITY_IDENTIFIED,
        SalesStage.PACKAGE_IDENTIFIED,
        SalesStage.PRICE_READY,
        SalesStage.ORDER_INTENT,
        SalesStage.ADVANCE_PENDING,
        SalesStage.CUSTOMER_INFO_PENDING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.ORDER_INTENT: [
        SalesStage.ADVANCE_PENDING,
        SalesStage.ADVANCE_CONFIRMED,
        SalesStage.CUSTOMER_INFO_PENDING,
        SalesStage.CUSTOMER_INFO_COMPLETE,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.ADVANCE_PENDING: [
        SalesStage.ADVANCE_CONFIRMED,
        SalesStage.CUSTOMER_INFO_PENDING,
        SalesStage.CUSTOMER_INFO_COMPLETE,
        SalesStage.DESIGN_PROCESSING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.ADVANCE_CONFIRMED: [
        SalesStage.CUSTOMER_INFO_PENDING,
        SalesStage.CUSTOMER_INFO_COMPLETE,
        SalesStage.DESIGN_PROCESSING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.CUSTOMER_INFO_PENDING: [
        SalesStage.CUSTOMER_INFO_COMPLETE,
        SalesStage.DESIGN_PROCESSING,
        SalesStage.PROOF_PENDING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.CUSTOMER_INFO_COMPLETE: [
        SalesStage.DESIGN_PROCESSING,
        SalesStage.PROOF_PENDING,
        SalesStage.PROOF_SENT,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.DESIGN_PROCESSING: [
        SalesStage.PROOF_PENDING,
        SalesStage.PROOF_SENT,
        SalesStage.CUSTOMER_CORRECTION,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.PROOF_PENDING: [
        SalesStage.PROOF_SENT,
        SalesStage.CUSTOMER_CORRECTION,
        SalesStage.FINAL_APPROVAL_PENDING,
        SalesStage.FINAL_APPROVED,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.PROOF_SENT: [
        SalesStage.CUSTOMER_CORRECTION,
        SalesStage.FINAL_APPROVAL_PENDING,
        SalesStage.FINAL_APPROVED,
        SalesStage.PRINTING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.CUSTOMER_CORRECTION: [
        SalesStage.DESIGN_PROCESSING,
        SalesStage.PROOF_PENDING,
        SalesStage.PROOF_SENT,
        SalesStage.FINAL_APPROVED,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.FINAL_APPROVAL_PENDING: [
        SalesStage.FINAL_APPROVED,
        SalesStage.CUSTOMER_CORRECTION,
        SalesStage.PRINTING,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.FINAL_APPROVED: [
        SalesStage.PRINTING,
        SalesStage.COURIER,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.PRINTING: [
        SalesStage.COURIER,
        SalesStage.DELIVERED,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.COURIER: [
        SalesStage.DELIVERED,
        SalesStage.OWNER_TAKEOVER,
        SalesStage.CLOSED,
    ],
    SalesStage.DELIVERED: [
        SalesStage.CLOSED,
        SalesStage.NEW,  # Repeat customer starting new order
        SalesStage.OWNER_TAKEOVER,
    ],
    SalesStage.OWNER_TAKEOVER: [
        # When human takeover is removed, can resume to any relevant stage
        stage for stage in SalesStage
    ],
    SalesStage.CLOSED: [
        SalesStage.NEW,
        SalesStage.SERVICE_IDENTIFIED,
        SalesStage.OWNER_TAKEOVER,
    ]
}

ALLOWED_STATE_FIELDS = {
    "service_type",
    "quantity",
    "quantity_source",
    "package_id",
    "package_source",
    "sample_permission",
    "sample_sent",
    "sample_sent_at",
    "sample_version",
    "price_context",
    "quoted_price",
    "discount_amount",
    "advance_required",
    "advance_amount",
    "advance_status",
    "customer_info_status",
    "google_form_status",
    "proof_status",
    "customer_approval_status",
    "printing_status",
    "courier_status",
    "human_takeover",
    "last_customer_intent",
    "current_sales_stage",
    "conversation_id",
    "memory_context",
    "current_topic",
    "previous_topic",
    "pending_question",
    "questions_asked",
    "facts_confirmed",
    "media_dispatched",
    "selected_product",
}


def _get_db_connection():
    from app.database import get_db_connection
    return get_db_connection()


def get_or_create_conversation_state(
    sender_id: str,
    workspace_id: int = 1,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retrieves the persistent conversation state for a customer.
    If none exists, initializes and returns a default state.
    """
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    conv_id = str(conversation_id or f"conv_{ws_id}_{s_id}").strip()

    conn = _get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT * FROM conversation_states
            WHERE sender_id = ? AND workspace_id = ?
            ORDER BY id DESC LIMIT 1
        """, (s_id, ws_id))
        row = cursor.fetchone()
        if row:
            return dict(row)

        # Initialize default state
        cursor.execute("""
            INSERT INTO conversation_states (
                workspace_id, conversation_id, sender_id, service_type,
                current_sales_stage, sample_permission, sample_sent,
                advance_required, advance_status, customer_info_status,
                google_form_status, proof_status, customer_approval_status,
                printing_status, courier_status, human_takeover, state_version
            ) VALUES (
                ?, ?, ?, 'id_card',
                'NEW', 'pending', 0,
                1, 'not_required', 'pending',
                'not_requested', 'not_started', 'pending',
                'pending', 'pending', 0, 1
            )
        """, (ws_id, conv_id, s_id))
        conn.commit()
        new_id = cursor.lastrowid

        # Log audit entry
        cursor.execute("""
            INSERT INTO conversation_state_audits (
                workspace_id, conversation_id, sender_id,
                previous_stage, new_stage, changed_fields, reason
            ) VALUES (?, ?, ?, NULL, 'NEW', ?, 'initial_creation')
        """, (ws_id, conv_id, s_id, json.dumps({"status": "initialized"})))
        conn.commit()

        cursor.execute("SELECT * FROM conversation_states WHERE id = ?", (new_id,))
        created_row = cursor.fetchone()
        return dict(created_row) if created_row else {}
    finally:
        conn.close()


def get_structured_conversation_state(
    sender_id: str,
    workspace_id: int = 1,
    conversation_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Returns a clean snapshot dictionary of the current conversation state.
    """
    return get_or_create_conversation_state(sender_id, workspace_id, conversation_id)

get_conversation_state = get_structured_conversation_state


def update_conversation_state(
    sender_id: str,
    updates: Dict[str, Any],
    reason: str = "state_update",
    workspace_id: int = 1,
    conversation_id: Optional[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Controlled atomic state updater.
    Validates allowed fields, checks state transitions, increments state_version,
    updates timestamp, and creates audit log.
    """
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    if not updates:
        return True, get_conversation_state(s_id, ws_id, conversation_id)

    # Filter disallowed fields
    clean_updates = {k: v for k, v in updates.items() if k in ALLOWED_STATE_FIELDS}
    if not clean_updates:
        return False, get_conversation_state(s_id, ws_id, conversation_id)

    current_state = get_or_create_conversation_state(s_id, ws_id, conversation_id)
    conv_id = str(conversation_id or current_state.get("conversation_id") or f"conv_{ws_id}_{s_id}").strip()
    previous_stage = current_state.get("current_sales_stage", SalesStage.NEW)

    # Monotonic Sample State Guard: Once samples are sent, NEVER regress back to pending
    current_sample_sent = bool(
        current_state.get("sample_sent") in (1, "1", True) or
        current_state.get("sample_permission") == "granted" or
        current_state.get("current_sales_stage") in (
            SalesStage.SAMPLE_SENT,
            SalesStage.PACKAGE_IDENTIFIED,
            SalesStage.PRICE_READY,
            SalesStage.ORDER_INTENT,
            SalesStage.ADVANCE_PENDING,
            SalesStage.ADVANCE_CONFIRMED,
            SalesStage.CUSTOMER_INFO_PENDING,
            SalesStage.CUSTOMER_INFO_COMPLETE,
            SalesStage.DESIGN_PROCESSING,
            SalesStage.PROOF_PENDING,
            SalesStage.PROOF_SENT,
            SalesStage.CUSTOMER_CORRECTION,
            SalesStage.FINAL_APPROVAL_PENDING,
            SalesStage.FINAL_APPROVED,
            SalesStage.PRINTING,
            SalesStage.COURIER,
            SalesStage.DELIVERED
        )
    )
    if current_sample_sent:
        if clean_updates.get("sample_permission") == "pending":
            clean_updates.pop("sample_permission")
        if clean_updates.get("sample_sent") in (0, "0", False):
            clean_updates.pop("sample_sent")
        if clean_updates.get("current_sales_stage") == SalesStage.SAMPLE_PERMISSION_PENDING:
            clean_updates.pop("current_sales_stage")

    new_stage = clean_updates.get("current_sales_stage", previous_stage)

    # Validate stage transition if stage is changing
    if new_stage != previous_stage:
        try:
            target_enum = SalesStage(new_stage)
            current_enum = SalesStage(previous_stage)
            allowed_targets = VALID_TRANSITIONS.get(current_enum, [])
            if target_enum not in allowed_targets and target_enum != SalesStage.OWNER_TAKEOVER:
                print(f"[State Machine Transition Warning]: Transition from {previous_stage} to {new_stage} not standard. Reason: {reason}")
        except Exception as ex:
            print(f"[State Machine Enum Error]: Invalid stage name {new_stage}: {ex}")

    conn = _get_db_connection()
    cursor = conn.cursor()
    try:
        # Build dynamic SQL update
        set_clauses = []
        params = []
        for k, v in clean_updates.items():
            set_clauses.append(f"{k} = ?")
            params.append(v)

        set_clauses.append("state_version = COALESCE(state_version, 1) + 1")
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")

        params.extend([s_id, ws_id])
        sql = f"""
            UPDATE conversation_states
            SET {', '.join(set_clauses)}
            WHERE sender_id = ? AND workspace_id = ?
        """
        cursor.execute(sql, tuple(params))
        conn.commit()

        # Audit log
        cursor.execute("""
            INSERT INTO conversation_state_audits (
                workspace_id, conversation_id, sender_id,
                previous_stage, new_stage, changed_fields, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            ws_id, conv_id, s_id,
            previous_stage, new_stage,
            json.dumps(clean_updates, default=str),
            reason
        ))
        conn.commit()

        cursor.execute("""
            SELECT * FROM conversation_states
            WHERE sender_id = ? AND workspace_id = ?
            ORDER BY id DESC LIMIT 1
        """, (s_id, ws_id))
        updated_row = cursor.fetchone()
        return True, dict(updated_row) if updated_row else {}
    except Exception as e:
        print(f"[State Machine Update Error]: {e}")
        return False, current_state
    finally:
        conn.close()


def transition_state(
    sender_id: str,
    new_stage: str,
    reason: str = "stage_transition",
    workspace_id: int = 1,
    conversation_id: Optional[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Dedicated transition helper to move conversation to a new stage.
    """
    return update_conversation_state(
        sender_id=sender_id,
        updates={"current_sales_stage": str(new_stage)},
        reason=reason,
        workspace_id=workspace_id,
        conversation_id=conversation_id
    )


def sync_human_takeover_state(
    sender_id: str,
    workspace_id: int = 1,
    is_takeover: bool = True,
    reason: str = "human_admin_message"
) -> Dict[str, Any]:
    """
    Synchronizes human takeover with the conversation state machine.
    """
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    if is_takeover:
        _, state = update_conversation_state(
            sender_id=s_id,
            updates={
                "human_takeover": 1,
                "current_sales_stage": SalesStage.OWNER_TAKEOVER
            },
            reason=f"admin_takeover_active: {reason}",
            workspace_id=ws_id
        )
    else:
        _, state = update_conversation_state(
            sender_id=s_id,
            updates={
                "human_takeover": 0,
            },
            reason=f"admin_takeover_released: {reason}",
            workspace_id=ws_id
        )
    return state


def get_state_audit_history(
    sender_id: str,
    workspace_id: int = 1,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """
    Fetches the chronological audit history of state transitions for this customer.
    """
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    conn = _get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT * FROM conversation_state_audits
            WHERE sender_id = ? AND workspace_id = ?
            ORDER BY id ASC LIMIT ?
        """, (s_id, ws_id, limit))
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ============================================================
# PHASE 9 CONVERSATION MEMORY & REPETITION GUARDS
# ============================================================

def record_question_asked(sender_id: str, question_code: str, workspace_id: int = 1) -> bool:
    """Records a question asked by the agent to prevent repeated prompts."""
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    state = get_structured_conversation_state(s_id, ws_id)
    raw_questions = state.get("questions_asked") or "[]"
    try:
        q_list = json.loads(raw_questions) if isinstance(raw_questions, str) else list(raw_questions)
    except Exception:
        q_list = []
    if question_code not in q_list:
        q_list.append(question_code)
        update_conversation_state(
            sender_id=s_id,
            updates={
                "questions_asked": json.dumps(q_list),
                "pending_question": question_code
            },
            reason="record_question_asked",
            workspace_id=ws_id
        )
    return True


def record_fact_confirmed(sender_id: str, fact_key: str, fact_value: Any, workspace_id: int = 1) -> bool:
    """Records a verified customer fact (e.g. quantity, product, design presence)."""
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    state = get_structured_conversation_state(s_id, ws_id)
    raw_facts = state.get("facts_confirmed") or "{}"
    try:
        facts = json.loads(raw_facts) if isinstance(raw_facts, str) else dict(raw_facts)
    except Exception:
        facts = {}
    facts[fact_key] = fact_value
    updates = {"facts_confirmed": json.dumps(facts, default=str)}
    if fact_key == "quantity" and isinstance(fact_value, (int, float)):
        updates["quantity"] = int(fact_value)
    elif fact_key == "package_id":
        updates["package_id"] = str(fact_value)
    elif fact_key == "topic":
        updates["current_topic"] = str(fact_value)
    update_conversation_state(
        sender_id=s_id,
        updates=updates,
        reason=f"record_fact_{fact_key}",
        workspace_id=ws_id
    )
    return True


def record_media_dispatched(sender_id: str, media_type: str, media_items: List[str], workspace_id: int = 1) -> bool:
    """Records a dispatched media batch in persistent memory."""
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    state = get_structured_conversation_state(s_id, ws_id)
    raw_media = state.get("media_dispatched") or "[]"
    try:
        media_list = json.loads(raw_media) if isinstance(raw_media, str) else list(raw_media)
    except Exception:
        media_list = []

    media_entry = {
        "media_type": media_type,
        "items": [str(x) for x in media_items],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    media_list.append(media_entry)
    updates = {"media_dispatched": json.dumps(media_list)}
    if media_type in ("samples", "sample_batch", "package_samples"):
        updates["sample_sent"] = 1
        updates["sample_permission"] = "granted"
    update_conversation_state(
        sender_id=s_id,
        updates=updates,
        reason="record_media_dispatched",
        workspace_id=ws_id
    )
    return True


def is_question_already_answered(sender_id: str, question_code: str, workspace_id: int = 1) -> bool:
    """Checks whether a specific question has already been answered by the customer."""
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    state = get_structured_conversation_state(s_id, ws_id)
    if question_code == "QUANTITY_PROMPT":
        return state.get("quantity") is not None and int(state.get("quantity") or 0) > 0
    if question_code == "SAMPLE_PERMISSION_PROMPT":
        return bool(state.get("sample_sent") in (1, "1", True) or state.get("sample_permission") == "granted")
    if question_code == "PACKAGE_SELECTION_PROMPT":
        return bool(state.get("package_id"))
    raw_facts = state.get("facts_confirmed") or "{}"
    try:
        facts = json.loads(raw_facts) if isinstance(raw_facts, str) else dict(raw_facts)
        return question_code in facts
    except Exception:
        return False


def is_media_already_sent(sender_id: str, media_type: str = "samples", workspace_id: int = 1) -> bool:
    """Checks whether a specific media type (e.g. sample photos) was already sent."""
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    state = get_structured_conversation_state(s_id, ws_id)
    if media_type in ("samples", "sample_batch", "package_samples"):
        if state.get("sample_sent") in (1, "1", True) or state.get("sample_permission") == "granted":
            return True
    raw_media = state.get("media_dispatched") or "[]"
    try:
        media_list = json.loads(raw_media) if isinstance(raw_media, str) else list(raw_media)
        return any(m.get("media_type") == media_type for m in media_list if isinstance(m, dict))
    except Exception:
        return False


def get_conversation_memory(sender_id: str, workspace_id: int = 1) -> Dict[str, Any]:
    """Returns a structured memory dict for prompt and decision building."""
    s_id = str(sender_id).strip()
    ws_id = int(workspace_id or 1)
    state = get_structured_conversation_state(s_id, ws_id)
    try:
        facts = json.loads(state.get("facts_confirmed") or "{}")
    except Exception:
        facts = {}
    try:
        questions = json.loads(state.get("questions_asked") or "[]")
    except Exception:
        questions = []
    try:
        media = json.loads(state.get("media_dispatched") or "[]")
    except Exception:
        media = []
    return {
        "sender_id": s_id,
        "workspace_id": ws_id,
        "current_topic": state.get("current_topic") or "id_card",
        "previous_topic": state.get("previous_topic"),
        "pending_question": state.get("pending_question"),
        "sales_stage": state.get("current_sales_stage", SalesStage.NEW),
        "quantity": state.get("quantity"),
        "package_id": state.get("package_id"),
        "sample_sent": bool(state.get("sample_sent") in (1, "1", True) or state.get("sample_permission") == "granted"),
        "facts_confirmed": facts,
        "questions_asked": questions,
        "media_dispatched": media,
        "human_takeover": bool(state.get("human_takeover") in (1, "1", True))
    }
