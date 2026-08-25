"""
Unit and Integration Tests for SQLite Backup Service.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.backup_service import (
    perform_sqlite_backup,
    prune_old_backups,
    list_available_backups,
    restore_sqlite_backup
)


class TestSQLiteBackupService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_db_path = self.temp_dir / "test_active.db"
        self.backup_dir = self.temp_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Create active SQLite database in WAL mode with sample tables and rows
        conn = sqlite3.connect(str(self.test_db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                balance REAL DEFAULT 0.0
            );
        """)
        conn.execute("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                package_id TEXT,
                quantity INTEGER,
                price REAL
            );
        """)
        for i in range(50):
            conn.execute(
                "INSERT INTO customers (name, phone, balance) VALUES (?, ?, ?)",
                (f"Customer {i}", f"018165040{i:02d}", 1000.0 + i * 50)
            )
            conn.execute(
                "INSERT INTO orders (customer_id, package_id, quantity, price) VALUES (?, ?, ?, ?)",
                (i + 1, "7", 100, 85.0)
            )
        conn.commit()
        conn.close()

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(str(self.temp_dir), ignore_errors=True)

    def test_01_perform_backup_success(self):
        """TEST 1: Standard online backup succeeds with ok integrity check."""
        res = perform_sqlite_backup(
            source_db_path=self.test_db_path,
            backup_dir=self.backup_dir,
            retention_count=14
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["integrity"], "ok")
        self.assertTrue(Path(res["backup_file"]).exists())
        self.assertTrue(res["backup_size_bytes"] > 0)
        self.assertTrue("rs_ai_backup_" in res["backup_filename"])

    def test_02_backup_data_parity(self):
        """TEST 2: Data inside the backup matches the active source database 100%."""
        res = perform_sqlite_backup(
            source_db_path=self.test_db_path,
            backup_dir=self.backup_dir
        )
        self.assertTrue(res["success"])

        bk_conn = sqlite3.connect(res["backup_file"])
        cur = bk_conn.cursor()
        cur.execute("SELECT COUNT(*) FROM customers")
        cust_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM orders")
        order_count = cur.fetchone()[0]
        bk_conn.close()

        self.assertEqual(cust_count, 50)
        self.assertEqual(order_count, 50)

    def test_03_non_existent_source_fails_gracefully(self):
        """TEST 3: Non-existent source database returns clean error dictionary without throwing unhandled exception."""
        non_existent = self.temp_dir / "does_not_exist.db"
        res = perform_sqlite_backup(
            source_db_path=non_existent,
            backup_dir=self.backup_dir
        )
        self.assertFalse(res["success"])
        self.assertIn("not found", res["error"].lower())

    def test_04_retention_pruning(self):
        """TEST 4: Pruning keeps exactly N backups and safely discards older ones."""
        # Create 5 synthetic backup files
        for i in range(5):
            f = self.backup_dir / f"rs_ai_backup_20260825_10000{i}.db"
            f.write_text(f"dummy content {i}")
            # Set artificial modification times
            os.utime(str(f), (1000000 + i * 100, 1000000 + i * 100))

        # Prune with retention count 3
        pruned = prune_old_backups(self.backup_dir, retention_count=3)
        self.assertEqual(len(pruned), 2)

        remaining = list_available_backups(self.backup_dir)
        self.assertEqual(len(remaining), 3)

    def test_05_list_available_backups(self):
        """TEST 5: List available backups returns structured metadata."""
        perform_sqlite_backup(source_db_path=self.test_db_path, backup_dir=self.backup_dir)
        backups = list_available_backups(self.backup_dir)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0]["size_bytes"] > 0)
        self.assertTrue("modified_at" in backups[0])

    def test_06_restore_backup_integrity_and_data(self):
        """TEST 6: Restore function safely recreates a destroyed database."""
        # Step 1: Create backup
        bk_res = perform_sqlite_backup(source_db_path=self.test_db_path, backup_dir=self.backup_dir)
        bk_file = Path(bk_res["backup_file"])

        # Step 2: Corrupt / wipe active DB
        conn = sqlite3.connect(str(self.test_db_path))
        conn.execute("DELETE FROM customers")
        conn.execute("DELETE FROM orders")
        conn.commit()
        conn.close()

        # Step 3: Restore
        rest_res = restore_sqlite_backup(bk_file, target_db_path=self.test_db_path)
        self.assertTrue(rest_res["success"])

        # Step 4: Verify data restored
        conn = sqlite3.connect(str(self.test_db_path))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM customers")
        c_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM orders")
        o_count = cur.fetchone()[0]
        conn.close()

        self.assertEqual(c_count, 50)
        self.assertEqual(o_count, 50)


if __name__ == "__main__":
    unittest.main()
