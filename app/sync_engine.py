"""Bidirectional sync engine with SQLite mapping."""
from __future__ import annotations
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .adapters.apple_reminders import AppleRemindersAdapter
from .adapters.zectrix import ZectrixAdapter
from .models import AppleReminder, SyncDelta, ZectrixTodo

logger = logging.getLogger(__name__)


class SyncDB:
    """SQLite wrapper for sync records."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        sql = Path(__file__).parent.parent / "db" / "schema.sql"
        with open(sql) as f:
            schema = f.read()
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(schema)

    def conn(self):
        return sqlite3.connect(self.db_path)

    def get_by_source_id(self, source: str, source_id: str) -> tuple | None:
        with self.conn() as conn:
            row = conn.execute(
                "SELECT * FROM sync_records WHERE source=? AND source_id=?",
                (source, source_id)
            ).fetchone()
        return row

    def get_by_dest_id(self, dest_id: str) -> tuple | None:
        with self.conn() as conn:
            row = conn.execute(
                "SELECT * FROM sync_records WHERE dest_id=?",
                (dest_id,)
            ).fetchone()
        return row

    def upsert(self, source: str, source_id: str, dest_id: str, title: str):
        with self.conn() as conn:
            now = datetime.utcnow().isoformat()
            conn.execute("""
                INSERT INTO sync_records (uuid, source, source_id, dest_id, title, synced_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, source_id) DO UPDATE SET
                    dest_id=excluded.dest_id, title=excluded.title, synced_at=excluded.synced_at
            """, (str(uuid.uuid4()), source, source_id, str(dest_id), title, now))

    def delete_by_source(self, source: str, source_id: str):
        with self.conn() as conn:
            conn.execute(
                "DELETE FROM sync_records WHERE source=? AND source_id=?",
                (source, source_id)
            )

    def delete_by_dest(self, dest_id: str):
        with self.conn() as conn:
            conn.execute("DELETE FROM sync_records WHERE dest_id=?", (str(dest_id),))

    def get_all_by_source(self, source: str) -> list[tuple]:
        with self.conn() as conn:
            return conn.execute(
                "SELECT * FROM sync_records WHERE source=?",
                (source,)
            ).fetchall()


class SyncEngine:
    """Bidirectional sync between Apple Reminders and Zectrix."""

    def __init__(self, db: SyncDB,
                 apple: AppleRemindersAdapter,
                 zectrix: ZectrixAdapter,
                 dry_run: bool = False):
        self.db = db
        self.apple = apple
        self.zectrix = zectrix
        self.dry_run = dry_run

    def _sync_apple_to_zectrix(self, delta: SyncDelta):
        """Push Apple items to Zectrix."""
        apple_items = self.apple.list_reminders()
        existing = {r.id for r in apple_items}
        synced = {row[2] for row in self.db.get_all_by_source("apple")}

        for item in apple_items:
            existing_sync = self.db.get_by_source_id("apple", item.id)
            if not existing_sync:
                if not self.dry_run:
                    created = self.zectrix.create_todo(
                        title=item.title,
                        due_date=item.due_date,
                        due_time=item.due_time,
                        priority=item.priority,
                    )
                    zid = created.get("id") or created.get("todoId")
                    self.db.upsert("apple", item.id, str(zid), item.title)
                    logger.info("[DRY-RUN] Apple->Zectrix: %s (zid=%s)", item.title, zid)
                else:
                    logger.info("[DRY-RUN] Apple->Zectrix: %s", item.title)

        # Items in sync table that no longer exist in Apple → delete from Zectrix
        for row in self.db.get_all_by_source("apple"):
            source_id = row[2]
            if source_id not in existing:
                dest_id = row[3]
                if not self.dry_run:
                    try:
                        self.zectrix.delete_todo(int(dest_id))
                        self.db.delete_by_source("apple", source_id)
                        logger.info("Deleted from Zectrix (apple missing): zid=%s", dest_id)
                    except Exception as e:
                        logger.error("Failed to delete zid=%s: %s", dest_id, e)
                else:
                    logger.info("[DRY-RUN] Zectrix delete (apple gone): zid=%s", dest_id)

    def _sync_zectrix_to_apple(self, delta: SyncDelta):
        """Push Zectrix items to Apple."""
        z_items = self.zectrix.list_todos()
        z_ids = {str(t["id"]) for t in z_items}
        synced = {str(row[3]) for row in self.db.get_all_by_source("zectrix")}

        for t in z_items:
            existing = self.db.get_by_source_id("zectrix", str(t["id"]))
            if not existing:
                if not self.dry_run:
                    created = self.apple.create_reminder(
                        title=t["title"],
                        due_date=t.get("dueDate"),
                        due_time=t.get("dueTime"),
                    )
                    self.db.upsert("zectrix", str(t["id"]), created.id, t["title"])
                    logger.info("Apple<-Zectrix: %s (apple_id=%s)", t["title"], created.id)
                else:
                    logger.info("[DRY-RUN] Apple<-Zectrix: %s", t["title"])

        # Zectrix items that no longer exist → delete from Apple
        for row in self.db.get_all_by_source("zectrix"):
            source_id = row[2]  # Zectrix todo ID
            if source_id not in z_ids:
                if not self.dry_run:
                    try:
                        self.apple.delete_reminder(row[3])  # row[3]=Apple UUID
                        self.db.delete_by_source("zectrix", source_id)
                        logger.info("Deleted from Apple (zectrix gone): apple_id=%s", row[3])
                    except Exception as e:
                        logger.error("Failed to delete apple_id=%s: %s", source_id, e)
                else:
                    logger.info("[DRY-RUN] Apple delete (zectrix gone): apple_id=%s", source_id)

    def sync(self) -> SyncDelta:
        delta = SyncDelta()

        # Phase 1: Apple → Zectrix
        self._sync_apple_to_zectrix(delta)

        # Phase 2: Zectrix → Apple
        self._sync_zectrix_to_apple(delta)

        return delta