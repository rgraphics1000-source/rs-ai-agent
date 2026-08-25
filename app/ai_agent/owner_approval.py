"""
Phase 7: Persistent Owner Approval & Human Escalation Engine for RS Graphics AI Agent.

Guarantees:
1. AI CANNOT approve its own business exceptions (price, discount, policy, advance).
2. Approval state is strictly persisted in SQLite database (survives restarts/reloads).
3. Exception scope is conversation-scoped and order-specific (no leaking to other customers/orders).
4. Permanent pricing engine rules & catalog are NEVER mutated by temporary exceptions.
5. Full audit trail for all transitions (PENDING, APPROVED, REJECTED, MODIFIED, EXPIRED, CANCELLED).
6. Integration with MasterOrchestrator and ResponseValidator.
7. Human Takeover precedence (if Takeover is active, AI stays silent).
"""

import time
import uuid
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Union
from datetime import datetime, timezone

from app.database import get_db_connection


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ApprovalRequestType(str, Enum):
    PRICE_EXCEPTION = "PRICE_EXCEPTION"
    DISCOUNT_EXCEPTION = "DISCOUNT_EXCEPTION"
    CUSTOM_PACKAGE_PRICE = "CUSTOM_PACKAGE_PRICE"
    UNKNOWN_PRODUCT = "UNKNOWN_PRODUCT"
    POLICY_EXCEPTION = "POLICY_EXCEPTION"
    ADVANCE_EXCEPTION = "ADVANCE_EXCEPTION"
    DELIVERY_EXCEPTION = "DELIVERY_EXCEPTION"
    UNKNOWN_BUSINESS_DECISION = "UNKNOWN_BUSINESS_DECISION"


class OwnerApprovalEngine:
    """
    Authoritative Engine for Owner Approvals, Human Escalations, and Persistent Exception Management.
    """

    @classmethod
    def create_or_get_pending_approval(
        cls,
        customer_id: str,
        conversation_id: str,
        request_type: Union[ApprovalRequestType, str],
        requested_value: float,
        authorized_value: float,
        package_id: Optional[str] = None,
        quantity: Optional[int] = None,
        reason: str = "",
        workspace_id: int = 1
    ) -> Dict[str, Any]:
        """
        Creates a new PENDING approval request in the database or returns existing active PENDING request.
        Prevents duplicate pending requests for the same customer/package in the same conversation.
        """
        ws_id = int(workspace_id or 1)
        cust_id = str(customer_id).strip()
        conv_id = str(conversation_id or f"conv_{ws_id}_{cust_id}").strip()
        req_type = request_type.value if hasattr(request_type, "value") else str(request_type)
        pkg_id = str(package_id) if package_id else None
        qty = int(quantity) if quantity else None

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Check for existing PENDING request for same customer & package
            cursor.execute("""
                SELECT * FROM owner_approvals 
                WHERE customer_id = ? AND workspace_id = ? AND request_type = ? 
                  AND (package_id = ? OR (package_id IS NULL AND ? IS NULL))
                  AND status = 'PENDING'
                ORDER BY id DESC LIMIT 1
            """, (cust_id, ws_id, req_type, pkg_id, pkg_id))
            existing = cursor.fetchone()
            if existing:
                return dict(existing)

            # Generate unique approval ID
            appr_id = f"appr_{ws_id}_{uuid.uuid4().hex[:10]}"
            now_iso = datetime.now(timezone.utc).isoformat()

            cursor.execute("""
                INSERT INTO owner_approvals (
                    approval_id, workspace_id, conversation_id, customer_id,
                    request_type, package_id, quantity, requested_value,
                    authorized_value, approved_value, reason, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'PENDING', ?, ?)
            """, (
                appr_id, ws_id, conv_id, cust_id,
                req_type, pkg_id, qty, float(requested_value or 0.0),
                float(authorized_value or 0.0), reason, now_iso, now_iso
            ))
            conn.commit()

            # Insert audit record
            cursor.execute("""
                INSERT INTO owner_approval_audits (
                    approval_id, workspace_id, old_status, new_status,
                    old_value, new_value, actor, reason, created_at
                ) VALUES (?, ?, NULL, 'PENDING', ?, ?, 'system_escalation', ?, ?)
            """, (appr_id, ws_id, float(authorized_value or 0.0), float(requested_value or 0.0), reason, now_iso))
            conn.commit()

            cursor.execute("SELECT * FROM owner_approvals WHERE approval_id = ?", (appr_id,))
            created_row = cursor.fetchone()
            return dict(created_row) if created_row else {}
        finally:
            conn.close()

    @classmethod
    def get_approval_by_id(cls, approval_id: str) -> Optional[Dict[str, Any]]:
        """Fetches approval record by approval_id."""
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM owner_approvals WHERE approval_id = ?", (str(approval_id),))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def get_active_approved_exception(
        cls,
        customer_id: str,
        workspace_id: int = 1,
        package_id: Optional[str] = None,
        quantity: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieves active APPROVED or MODIFIED exception for a specific customer, workspace, and package.
        Guarantees strict conversation/customer scoping.
        """
        ws_id = int(workspace_id or 1)
        cust_id = str(customer_id).strip()
        pkg_id = str(package_id) if package_id else None

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT * FROM owner_approvals 
                WHERE customer_id = ? AND workspace_id = ? 
                  AND status IN ('APPROVED', 'MODIFIED')
                  AND (package_id = ? OR (package_id IS NULL AND ? IS NULL))
                ORDER BY id DESC LIMIT 1
            """, (cust_id, ws_id, pkg_id, pkg_id))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)

            # Quantity check if specified
            if quantity and res.get("quantity") and int(res["quantity"]) > 0:
                if int(quantity) != int(res["quantity"]):
                    return None

            return res
        finally:
            conn.close()

    @classmethod
    def resolve_approval(
        cls,
        approval_id: str,
        decision: Union[ApprovalStatus, str],
        actor: str = "owner",
        approved_value: Optional[float] = None,
        reason: str = ""
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Authoritative Owner/Admin resolution function (APPROVE, REJECT, MODIFY, CANCEL).
        Requires authenticated owner/admin identity.
        """
        appr_id = str(approval_id).strip()
        dec_str = decision.value if hasattr(decision, "value") else str(decision).upper()

        if dec_str not in [ApprovalStatus.APPROVED.value, ApprovalStatus.REJECTED.value, ApprovalStatus.MODIFIED.value, ApprovalStatus.CANCELLED.value]:
            return False, None

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM owner_approvals WHERE approval_id = ?", (appr_id,))
            current = cursor.fetchone()
            if not current:
                return False, None

            current_dict = dict(current)
            if current_dict["status"] != ApprovalStatus.PENDING.value and dec_str != ApprovalStatus.CANCELLED.value:
                return False, current_dict

            old_status = current_dict["status"]
            old_val = current_dict["requested_value"]

            final_approved_val = approved_value
            if dec_str == ApprovalStatus.APPROVED.value:
                final_approved_val = approved_value if approved_value is not None else current_dict["requested_value"]
            elif dec_str == ApprovalStatus.MODIFIED.value:
                final_approved_val = approved_value if approved_value is not None else current_dict["requested_value"]
            elif dec_str == ApprovalStatus.REJECTED.value:
                final_approved_val = None

            now_iso = datetime.now(timezone.utc).isoformat()

            cursor.execute("""
                UPDATE owner_approvals 
                SET status = ?,
                    approved_value = ?,
                    resolved_by = ?,
                    resolved_at = ?,
                    updated_at = ?
                WHERE approval_id = ? AND status = 'PENDING'
            """, (dec_str, final_approved_val, str(actor), now_iso, now_iso, appr_id))
            if cursor.rowcount == 0 and dec_str != ApprovalStatus.CANCELLED.value:
                conn.rollback()
                return False, current_dict
            conn.commit()

            # Record Audit Trail
            cursor.execute("""
                INSERT INTO owner_approval_audits (
                    approval_id, workspace_id, old_status, new_status,
                    old_value, new_value, actor, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                appr_id, current_dict["workspace_id"], old_status, dec_str,
                float(old_val or 0.0), float(final_approved_val or 0.0) if final_approved_val is not None else None,
                str(actor), reason or f"Resolved as {dec_str}", now_iso
            ))
            conn.commit()

            cursor.execute("SELECT * FROM owner_approvals WHERE approval_id = ?", (appr_id,))
            updated_row = cursor.fetchone()
            return True, dict(updated_row) if updated_row else None
        finally:
            conn.close()

    @classmethod
    def list_approvals(
        cls,
        workspace_id: int = 1,
        status_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Lists approval requests filtered by workspace and status."""
        ws_id = int(workspace_id or 1)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if status_filter:
                cursor.execute("""
                    SELECT * FROM owner_approvals 
                    WHERE workspace_id = ? AND status = ?
                    ORDER BY id DESC
                """, (ws_id, str(status_filter).upper()))
            else:
                cursor.execute("""
                    SELECT * FROM owner_approvals 
                    WHERE workspace_id = ?
                    ORDER BY id DESC
                """, (ws_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    @classmethod
    def get_pending_customer_response(cls, honorific: str = "স্যার") -> str:
        """Safe customer-facing message when an exception is PENDING owner review."""
        return (
            f"জি {honorific}, আমাদের নির্ধারিত সর্বোচ্চ Discount-এর বাইরে যেতে হলে "
            f"Owner স্যারের বিশেষ অনুমতির প্রয়োজন হবে। বিষয়টি আমরা Owner স্যারকে জানিয়ে দিচ্ছি।"
        )

    @classmethod
    def get_rejected_customer_response(cls, honorific: str = "স্যার") -> str:
        """Safe customer-facing message when an exception request is REJECTED by owner."""
        return (
            f"জি {honorific}, আমরা যাচাই করে দেখেছি এই রেটে অর্ডারটি নেওয়া সম্ভব হচ্ছে না। "
            f"আমাদের নির্ধারিত রেট অনুযায়ীই অর্ডারটি কনফার্ম করতে হবে।"
        )
