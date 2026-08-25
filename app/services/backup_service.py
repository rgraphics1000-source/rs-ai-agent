"""
Production Automated SQLite Backup Service for RS Graphics AI Agent.

Guarantees:
1. Online Consistent Backup: Uses SQLite Online Backup API (sqlite3.Connection.backup)
   which produces consistent, point-in-time snapshots even under active WAL write traffic.
2. Zero Reader/Writer Disruption: Performs incremental page backups without locking or corrupting WAL transactions.
3. Automated Pruning & Retention: Retains the latest N backups (default: 14) and cleans older files safely.
4. Integrity Verification: Runs PRAGMA integrity_check on the generated backup immediately after creation.
5. Platform Agnostic: Runs seamlessly on Windows, Linux, macOS, and Docker/Render containers.
6. Safe Restore Support: Provides pre-validated online restoration.
"""

import os
import sys
import time
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from app.config import settings

logger = logging.getLogger("RS_Backup_Service")

DEFAULT_BACKUP_DIR = settings.BASE_DIR / "backups"
DEFAULT_DB_PATH = settings.BASE_DIR / "rs_ai.db"
DEFAULT_RETENTION_COUNT = 14  # Keep last 14 daily/scheduled backups


def get_default_backup_dir() -> Path:
    """Returns and ensures the canonical backup directory exists."""
    backup_dir = DEFAULT_BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def perform_sqlite_backup(
    source_db_path: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    retention_count: int = DEFAULT_RETENTION_COUNT
) -> Dict[str, Any]:
    """
    Creates an atomic, consistent point-in-time backup of the SQLite database
    using SQLite's native Online Backup API.

    Returns:
        Dict containing backup status, file path, size, integrity check, and timestamp.
    """
    src_path = Path(source_db_path or DEFAULT_DB_PATH).resolve()
    target_dir = Path(backup_dir or get_default_backup_dir()).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    if not src_path.exists() or not src_path.is_file():
        return {
            "success": False,
            "error": f"Source database file not found: {src_path}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"rs_ai_backup_{timestamp_str}.db"
    dest_path = target_dir / backup_filename

    source_conn = None
    dest_conn = None
    try:
        source_conn = sqlite3.connect(str(src_path), timeout=30.0)
        dest_conn = sqlite3.connect(str(dest_path))

        # Perform online backup incrementally (100 pages per step to yield to active writers)
        source_conn.backup(dest_conn, pages=100, sleep=0.01)
        dest_conn.commit()

        # Close destination connection to flush all data to disk
        dest_conn.close()
        dest_conn = None

        source_conn.close()
        source_conn = None

        # Verify integrity of the generated backup
        verify_conn = sqlite3.connect(str(dest_path))
        v_cur = verify_conn.cursor()
        v_cur.execute("PRAGMA integrity_check")
        integrity_res = v_cur.fetchone()[0]
        verify_conn.close()

        if integrity_res != "ok":
            if dest_path.exists():
                dest_path.unlink()
            return {
                "success": False,
                "error": f"Integrity check failed on backup: {integrity_res}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        backup_size = dest_path.stat().st_size

        # Prune old backups beyond retention count
        pruned = prune_old_backups(target_dir, retention_count=retention_count)

        return {
            "success": True,
            "backup_file": str(dest_path),
            "backup_filename": backup_filename,
            "backup_size_bytes": backup_size,
            "integrity": "ok",
            "pruned_files_count": len(pruned),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        if dest_conn:
            try:
                dest_conn.close()
            except Exception:
                pass
        if source_conn:
            try:
                source_conn.close()
            except Exception:
                pass
        if dest_path.exists():
            try:
                dest_path.unlink()
            except Exception:
                pass
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


def prune_old_backups(backup_dir: Optional[Path] = None, retention_count: int = DEFAULT_RETENTION_COUNT) -> List[str]:
    """
    Removes backup files exceeding retention_count, keeping the most recent ones.
    Only deletes files matching 'rs_ai_backup_*.db'. Never touches active databases.
    """
    target_dir = Path(backup_dir or get_default_backup_dir()).resolve()
    if not target_dir.exists():
        return []

    backup_files = sorted(
        [f for f in target_dir.glob("rs_ai_backup_*.db") if f.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    pruned = []
    if len(backup_files) > retention_count:
        files_to_remove = backup_files[retention_count:]
        for f in files_to_remove:
            try:
                f_name = f.name
                f.unlink()
                pruned.append(f_name)
            except Exception as e:
                logger.warning(f"Could not prune backup file {f.name}: {e}")

    return pruned


def list_available_backups(backup_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Lists all available backup files with metadata and integrity status."""
    target_dir = Path(backup_dir or get_default_backup_dir()).resolve()
    if not target_dir.exists():
        return []

    files = sorted(
        [f for f in target_dir.glob("rs_ai_backup_*.db") if f.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    results = []
    for f in files:
        results.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": f.stat().st_size,
            "modified_at": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()
        })
    return results


def restore_sqlite_backup(backup_file_path: Path, target_db_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Restores the target SQLite database from a specified backup file.
    Validates backup integrity before performing restore.
    """
    bk_path = Path(backup_file_path).resolve()
    dest_path = Path(target_db_path or DEFAULT_DB_PATH).resolve()

    if not bk_path.exists() or not bk_path.is_file():
        return {"success": False, "error": f"Backup file not found: {bk_path}"}

    # Verify backup integrity first
    try:
        chk_conn = sqlite3.connect(str(bk_path))
        c = chk_conn.cursor()
        c.execute("PRAGMA integrity_check")
        status = c.fetchone()[0]
        chk_conn.close()
        if status != "ok":
            return {"success": False, "error": f"Backup failed integrity verification: {status}"}
    except Exception as e:
        return {"success": False, "error": f"Unable to verify backup integrity: {e}"}

    # Perform online restoration
    try:
        src_conn = sqlite3.connect(str(bk_path))
        dest_conn = sqlite3.connect(str(dest_path), timeout=30.0)
        src_conn.backup(dest_conn, pages=100, sleep=0.01)
        dest_conn.commit()
        dest_conn.close()
        src_conn.close()

        return {
            "success": True,
            "restored_from": str(bk_path),
            "target_db": str(dest_path),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        return {"success": False, "error": f"Restore operation failed: {e}"}


if __name__ == "__main__":
    print("[RS Backup Service] Executing manual backup...")
    res = perform_sqlite_backup()
    print(f"Result: {res}")
