from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys
import sqlite3
import tempfile
import unittest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db import ReminderStore
from app.handlers.reminders import parse_datetime


class TestReminderStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "test.db"
        self.store = ReminderStore(db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmpdir.cleanup()

    def test_add_and_due_reminders(self) -> None:
        remind_at = datetime.utcnow() - timedelta(minutes=1)
        reminder_id = self.store.add_reminder(
            chat_id=1,
            creator_id=1,
            text="Test",
            remind_at=remind_at,
        )

        due = self.store.due_reminders(now=datetime.utcnow())
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["id"], reminder_id)

    def test_mark_sent_and_failed(self) -> None:
        remind_at = datetime.utcnow()
        reminder_id = self.store.add_reminder(
            chat_id=1,
            creator_id=1,
            text="Test",
            remind_at=remind_at,
        )

        self.store.mark_failed(reminder_id)
        rows = self.store.list_reminders(chat_id=1, creator_id=1)
        self.assertEqual(rows[0]["status"], "failed")

        self.store.mark_sent([reminder_id])
        rows = self.store.list_reminders(chat_id=1, creator_id=1)
        self.assertEqual(rows[0]["status"], "sent")

    def test_reschedule_and_cancel_complete(self) -> None:
        remind_at = datetime.utcnow() + timedelta(hours=1)
        reminder_id = self.store.add_reminder(
            chat_id=7,
            creator_id=42,
            text="Move me",
            remind_at=remind_at,
        )

        new_time = remind_at + timedelta(hours=1)
        self.assertTrue(
            self.store.reschedule_reminder(
                reminder_id=reminder_id,
                chat_id=7,
                creator_id=42,
                remind_at=new_time,
            )
        )

        rows = self.store.list_reminders(chat_id=7, creator_id=42)
        self.assertEqual(rows[0]["remind_at"], new_time.isoformat(timespec="minutes"))

        self.assertTrue(
            self.store.complete_reminder(
                reminder_id=reminder_id, chat_id=7, creator_id=42
            )
        )
        rows = self.store.list_reminders(chat_id=7, creator_id=42)
        self.assertEqual(rows[0]["status"], "completed")

        # Completed reminders cannot be cancelled
        self.assertFalse(
            self.store.cancel_reminder(
                reminder_id=reminder_id, chat_id=7, creator_id=42
            )
        )

    def test_schema_migration_keeps_existing_rows(self) -> None:
        # create legacy schema without new columns
        with sqlite3.connect(Path(self.tmpdir.name) / "legacy.db") as conn:
            conn.execute(
                """
                CREATE TABLE reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    is_sent INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT INTO reminders (chat_id, creator_id, text, remind_at, is_sent, created_at)
                VALUES (1, 1, 'legacy', ?, 0, ?)
                """,
                (
                    datetime.utcnow().isoformat(timespec="minutes"),
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )

        migrated_store = ReminderStore(Path(self.tmpdir.name) / "legacy.db")
        rows = migrated_store.list_reminders(chat_id=1, creator_id=1)
        self.assertEqual(rows[0]["status"], "scheduled")
        migrated_store.close()


class TestDateParsing(unittest.TestCase):
    def test_parse_datetime_rejects_past(self) -> None:
        past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        with self.assertRaises(ValueError):
            parse_datetime(past)

    def test_parse_datetime_accepts_future(self) -> None:
        future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        parsed = parse_datetime(future, now=datetime.now())
        self.assertIsInstance(parsed, datetime)


if __name__ == "__main__":
    unittest.main()
