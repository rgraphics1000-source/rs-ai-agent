"""
Phase 7.1 Automated Test Suite: Owner Approval Dashboard & Resolution UI

Tests:
1. Pending approval appears in dashboard API
2. Approval details load correctly via API
3. Approve changes status to APPROVED
4. Modify changes status to MODIFIED and sets custom value
5. Reject changes status to REJECTED
6. Customer role blocked with 403 Forbidden
7. Customer cannot resolve approval
8. Double approve is prevented (already resolved)
9. Concurrent / duplicate resolution safety
10. Audit log created for dashboard action
11. Approved exception remains conversation-scoped
12. Pricing Engine permanent rule unchanged
13. Response Validator remains mandatory
14. Human takeover enforces silence
15. Non-existent approval ID returns 404
"""

import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, ensure_default_saved_media, get_db_connection, set_admin_takeover, enable_conversation_ai
from app.ai_agent.owner_approval import (
    OwnerApprovalEngine, ApprovalStatus, ApprovalRequestType
)
from app.ai_agent.pricing_engine import PACKAGE_CATALOG, calculate_package_price
from app.ai_agent.response_validator import ResponseValidator
from app.ai_agent.orchestrator import MasterOrchestrator


class TestOwnerApprovalDashboard(unittest.TestCase):

    def setUp(self):
        init_db()
        ensure_default_saved_media()
        self.client = TestClient(app)
        self.ws_id = 1
        self.test_sender = f"dash_appr_{self._testMethodName}"
        self.conv_id = f"conv_1_{self.test_sender}"

        # Clean up database records for this test sender
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("DELETE FROM owner_approvals WHERE customer_id = ?", (self.test_sender,))
        conn.commit()
        conn.close()

    def test_01_pending_approval_appears_in_dashboard(self):
        """TEST 1: Pending approval appears in GET /api/admin/approvals."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            quantity=100,
            reason="Customer wants 78 Tk",
            workspace_id=self.ws_id
        )

        response = self.client.get(f"/api/admin/approvals?workspace_id={self.ws_id}&status=PENDING")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        ids = [a["approval_id"] for a in data["approvals"]]
        self.assertIn(appr["approval_id"], ids)
        print("[PASSED] Test 01: Pending approval appears in dashboard API.")

    def test_02_approval_details_load_correctly(self):
        """TEST 2: GET /api/admin/approvals/{approval_id} loads full detail."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            quantity=100,
            reason="Package 7 discount request",
            workspace_id=self.ws_id
        )

        response = self.client.get(f"/api/admin/approvals/{appr['approval_id']}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["approval"]["customer_id"], self.test_sender)
        self.assertEqual(float(data["approval"]["requested_value"]), 78.0)
        self.assertEqual(float(data["approval"]["authorized_value"]), 82.0)
        print("[PASSED] Test 02: Approval details load correctly via API.")

    def test_03_approve_changes_status(self):
        """TEST 3: POST /api/admin/approvals/{id}/approve changes status to APPROVED."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            quantity=100,
            workspace_id=self.ws_id
        )

        res = self.client.post(
            f"/api/admin/approvals/{appr['approval_id']}/approve",
            json={"actor": "super_admin_1", "reason": "VIP customer approved"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["approval"]["status"], "APPROVED")
        self.assertEqual(float(data["approval"]["approved_value"]), 78.0)
        self.assertEqual(data["approval"]["resolved_by"], "super_admin_1")
        print("[PASSED] Test 03: Approve changes status to APPROVED.")

    def test_04_modify_changes_status_and_value(self):
        """TEST 4: POST /api/admin/approvals/{id}/modify changes status to MODIFIED with counter-offer."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=75.0,
            authorized_value=82.0,
            package_id="7",
            quantity=100,
            workspace_id=self.ws_id
        )

        res = self.client.post(
            f"/api/admin/approvals/{appr['approval_id']}/modify",
            json={"approved_value": 80.0, "actor": "owner_admin", "reason": "Counter-offer 80 Tk"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["approval"]["status"], "MODIFIED")
        self.assertEqual(float(data["approval"]["approved_value"]), 80.0)
        print("[PASSED] Test 04: Modify counter-offer changes status to MODIFIED.")

    def test_05_reject_changes_status(self):
        """TEST 5: POST /api/admin/approvals/{id}/reject changes status to REJECTED."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=65.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )

        res = self.client.post(
            f"/api/admin/approvals/{appr['approval_id']}/reject",
            json={"actor": "owner_admin", "reason": "Margin below minimum"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["approval"]["status"], "REJECTED")
        self.assertIsNone(data["approval"]["approved_value"])
        print("[PASSED] Test 05: Reject changes status to REJECTED.")

    def test_06_customer_role_blocked(self):
        """TEST 6: Customer role header receives 403 Forbidden."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )

        res = self.client.post(
            f"/api/admin/approvals/{appr['approval_id']}/approve",
            headers={"x-user-role": "customer"},
            json={"actor": "customer_attacker"}
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("Unauthorized", res.json()["detail"])
        print("[PASSED] Test 06: Customer role blocked with 403 Forbidden.")

    def test_07_customer_cannot_resolve_approval(self):
        """TEST 7: Direct modify attempt by customer role is blocked."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )

        res = self.client.post(
            f"/api/admin/approvals/{appr['approval_id']}/modify",
            headers={"x-user-role": "customer"},
            json={"approved_value": 70.0}
        )
        self.assertEqual(res.status_code, 403)
        print("[PASSED] Test 07: Customer cannot resolve approval.")

    def test_08_double_approve_is_prevented(self):
        """TEST 8: Second approve on already resolved approval returns 400."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )

        # 1st approve -> 200 OK
        res1 = self.client.post(f"/api/admin/approvals/{appr['approval_id']}/approve", json={})
        self.assertEqual(res1.status_code, 200)

        # 2nd approve -> 400 Already resolved
        res2 = self.client.post(f"/api/admin/approvals/{appr['approval_id']}/approve", json={})
        self.assertEqual(res2.status_code, 400)
        self.assertIn("already resolved", res2.json()["detail"].lower())
        print("[PASSED] Test 08: Double approve is prevented (idempotent guard).")

    def test_09_concurrent_resolution_safe(self):
        """TEST 9: Conflicting second action (e.g. reject after approve) is rejected."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )

        # Admin A approves
        resA = self.client.post(f"/api/admin/approvals/{appr['approval_id']}/approve", json={"actor": "admin_A"})
        self.assertEqual(resA.status_code, 200)

        # Admin B attempts to reject
        resB = self.client.post(f"/api/admin/approvals/{appr['approval_id']}/reject", json={"actor": "admin_B"})
        self.assertEqual(resB.status_code, 400)
        print("[PASSED] Test 09: Concurrent conflicting resolution rejected.")

    def test_10_audit_log_created_for_dashboard_action(self):
        """TEST 10: Resolving via dashboard endpoint creates audit log."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )

        self.client.post(
            f"/api/admin/approvals/{appr['approval_id']}/modify",
            json={"approved_value": 79.5, "actor": "manager_audit_test", "reason": "Phone confirmation"}
        )

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM owner_approval_audits WHERE approval_id = ? ORDER BY id DESC LIMIT 1", (appr["approval_id"],))
        audit = c.fetchone()
        conn.close()

        self.assertIsNotNone(audit)
        self.assertEqual(audit["new_status"], "MODIFIED")
        self.assertEqual(audit["actor"], "manager_audit_test")
        self.assertEqual(float(audit["new_value"]), 79.5)
        print("[PASSED] Test 10: Audit trail created for dashboard action.")

    def test_11_approved_exception_remains_conversation_scoped(self):
        """TEST 11: Exception approved via API applies only to target customer."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=78.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )
        self.client.post(f"/api/admin/approvals/{appr['approval_id']}/approve", json={})

        other_user = f"other_user_{self._testMethodName}"
        exc = OwnerApprovalEngine.get_active_approved_exception(other_user, self.ws_id, package_id="7")
        self.assertIsNone(exc)
        print("[PASSED] Test 11: Approved exception remains strictly conversation-scoped.")

    def test_12_pricing_engine_permanent_rule_unchanged(self):
        """TEST 12: Resolving exception does not modify global Package Catalog."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=75.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )
        self.client.post(f"/api/admin/approvals/{appr['approval_id']}/approve", json={})

        self.assertEqual(PACKAGE_CATALOG["7"]["regular_price"], 91.0)
        self.assertEqual(PACKAGE_CATALOG["7"]["min_price"], 82.0)
        print("[PASSED] Test 12: Pricing Engine permanent rules unmutated.")

    def test_13_response_validator_remains_mandatory(self):
        """TEST 13: ResponseValidator verifies approved exception."""
        appr = OwnerApprovalEngine.create_or_get_pending_approval(
            customer_id=self.test_sender,
            conversation_id=self.conv_id,
            request_type=ApprovalRequestType.PRICE_EXCEPTION,
            requested_value=80.0,
            authorized_value=82.0,
            package_id="7",
            workspace_id=self.ws_id
        )
        self.client.post(
            f"/api/admin/approvals/{appr['approval_id']}/modify",
            json={"approved_value": 80.0}
        )

        draft = {
            "reply_text": "প্যাকেজ ৭ এর জন্য ৮০ টাকা রাখা যাবে।",
            "matched_images": [],
            "media_sequence": [],
            "voice_url": "",
            "video_url": "",
            "order_created": None
        }
        res = ResponseValidator.validate_and_sanitize(
            draft_response=draft,
            customer_message="প্যাকেজ ৭ ৮০ টাকা",
            sender_id=self.test_sender,
            workspace_id=self.ws_id
        )
        self.assertIn("৮০ টাকা", res["reply_text"])
        print("[PASSED] Test 13: Response Validator enforces verified exception.")

    def test_14_human_takeover_enforces_silence(self):
        """TEST 14: If takeover active, AI notification blocked."""
        set_admin_takeover(sender_id=self.test_sender, workspace_id=self.ws_id, takeover_by="admin", takeover_reason="test")
        try:
            decision = MasterOrchestrator.execute_decision(
                customer_message="প্যাকেজ ৭ ৮০ টাকা",
                sender_id=self.test_sender,
                workspace_id=self.ws_id
            )
            self.assertTrue(decision["is_blocked"])
            self.assertEqual(decision["reply_text"], "")
        finally:
            enable_conversation_ai(sender_id=self.test_sender, workspace_id=self.ws_id)
        print("[PASSED] Test 14: Human takeover enforces silence.")

    def test_15_non_existent_approval_returns_404(self):
        """TEST 15: Invalid approval ID returns 404."""
        res = self.client.get("/api/admin/approvals/non_existent_id_12345")
        self.assertEqual(res.status_code, 404)
        print("[PASSED] Test 15: Non-existent approval ID returns 404.")


if __name__ == "__main__":
    unittest.main()
