import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db_connection
from app.nikash_integration.nikash_tools import (
    get_nikash_sales_summary,
    get_nikash_customer_ledger,
    get_nikash_inventory_stock,
    parse_financial_sms_ai,
    record_nikash_expense_ai
)

class TestNikashIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        conn = get_db_connection()
        cursor = conn.cursor()

        # Seed test product
        cursor.execute("""
            INSERT INTO products (name, code, price, discount_price, stock, category, is_active)
            VALUES ('NIKASH Test T-Shirt', 'TEST-TS-01', 500, 450, 3, 'Apparel', 1)
            ON CONFLICT(code) DO UPDATE SET stock = 3, price = 500
        """)

        # Seed test order
        cursor.execute("""
            INSERT INTO orders (
                order_code, customer_name, customer_phone, customer_address, items_summary, subtotal, delivery_charge, total_amount, channel, status
            ) VALUES (
                'ORD-NIKASH-999', 'Rahim Ahmed', '01711223344', 'Dhanmondi, Dhaka', '1x NIKASH Test T-Shirt', 450, 70, 520, 'facebook', 'Pending'
            )
            ON CONFLICT(order_code) DO NOTHING
        """)

        conn.commit()
        conn.close()

    def test_sales_summary_tool(self):
        res = get_nikash_sales_summary(date_filter="all")
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["total_revenue"], 520.0)
        self.assertGreaterEqual(res["total_orders"], 1)
        self.assertIn("নিকাশ সেলস রিপোর্ট", res["formatted_summary"])

    def test_customer_ledger_tool(self):
        res = get_nikash_customer_ledger(query="01711223344")
        self.assertTrue(res["success"])
        self.assertTrue(res["found"])
        self.assertIn("Rahim Ahmed", res["customer"]["name"])

    def test_inventory_stock_tool(self):
        res = get_nikash_inventory_stock("TEST-TS-01")
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["total_found"], 1)
        self.assertGreaterEqual(res["low_stock_count"], 1)

    def test_financial_sms_parser_bkash(self):
        bkash_sms = "You have received Tk 1,200.00 from 01812345678. Fee Tk 0.00. Balance Tk 4,500.00. TrxID 9K38DF829 at 29/08/2026 07:30"
        res = parse_financial_sms_ai(bkash_sms, sender="bKash")
        self.assertTrue(res["success"])
        self.assertEqual(res["data"]["service"], "bKash")
        self.assertEqual(res["data"]["amount"], 1200.0)
        self.assertEqual(res["data"]["trx_id"], "9K38DF829")
        self.assertEqual(res["data"]["type"], "cash_in")

    def test_financial_sms_parser_nagad(self):
        nagad_sms = "Money Transfer (Inward) Amount: Tk 2,500.00 Sender: 01911223344 TxnID: 71AF9920 Fee: Tk 0.00 Balance: Tk 10,200.00"
        res = parse_financial_sms_ai(nagad_sms, sender="NAGAD")
        self.assertTrue(res["success"])
        self.assertEqual(res["data"]["service"], "Nagad")
        self.assertEqual(res["data"]["amount"], 2500.0)
        self.assertEqual(res["data"]["trx_id"], "71AF9920")

    def test_copilot_chat_sales_query(self):
        resp = self.client.post("/api/nikash/copilot/chat", json={
            "message": "আজকের মোট বিক্রি এবং সেলস রিপোর্ট দেখাও"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["intent"], "sales_summary")
        self.assertIn("নিকাশ সেলস রিপোর্ট", data["reply"])

    def test_copilot_chat_stock_query(self):
        resp = self.client.post("/api/nikash/copilot/chat", json={
            "message": "টি-শার্টের স্টক কয়টা আছে?"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["intent"], "inventory_stock")

    def test_pending_orders_endpoint(self):
        resp = self.client.get("/api/nikash/orders/pending")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["total_pending"], 1)

    def test_dashboard_stats_endpoint(self):
        resp = self.client.get("/api/nikash/dashboard/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("today_revenue", data)
        self.assertIn("pending_online_orders", data)

if __name__ == "__main__":
    unittest.main()
