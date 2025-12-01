"""SQLite helper functions for storing reminders."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional


class ReminderStore:
    """A tiny wrapper around SQLite for reminder operations."""

    def __init__(self, db_path: Path) -> None:
        # check_same_thread=False позволяет использовать соединение из потоков планировщика
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Создает таблицы при первом запуске бота."""
        with closing(self.connection.cursor()) as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    remind_at TEXT NOT NULL,
                    is_sent INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    mention_target_id INTEGER,
                    mention_target_name TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reminders_due
                ON reminders (is_sent, remind_at);
                """
            )
            # Простейшие миграции для существующих инсталляций
            cur.execute(
                """
                PRAGMA table_info(reminders);
                """
            )
            existing_columns = {row[1] for row in cur.fetchall()}
            if "status" not in existing_columns:
                cur.execute(
                    "ALTER TABLE reminders ADD COLUMN status TEXT NOT NULL DEFAULT 'scheduled'"
                )
            if "mention_target_id" not in existing_columns:
                cur.execute(
                    "ALTER TABLE reminders ADD COLUMN mention_target_id INTEGER"
                )
            if "mention_target_name" not in existing_columns:
                cur.execute(
                    "ALTER TABLE reminders ADD COLUMN mention_target_name TEXT"
                )

            cur.execute(
                """
                UPDATE reminders
                SET status = CASE WHEN is_sent = 1 THEN 'sent' ELSE 'scheduled' END
                WHERE status NOT IN ('scheduled', 'sent')
                   OR (is_sent = 1 AND status != 'sent')
                   OR (is_sent = 0 AND status != 'scheduled')
                """
            )
            self.connection.commit()

    def add_reminder(
        self,
        *,
        chat_id: int,
        creator_id: int,
        text: str,
        remind_at: datetime,
        mention_target_id: Optional[int] = None,
        mention_target_name: Optional[str] = None,
    ) -> int:
        """Сохраняет новое напоминание и возвращает его ID."""

        with closing(self.connection.cursor()) as cur:
            cur.execute(
                """
                INSERT INTO reminders (
                    chat_id,
                    creator_id,
                    text,
                    remind_at,
                    created_at,
                    status,
                    mention_target_id,
                    mention_target_name
                )
                VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?)
                """,
                (
                    chat_id,
                    creator_id,
                    text,
                    remind_at.isoformat(timespec="minutes"),
                    datetime.utcnow().isoformat(timespec="seconds"),
                    mention_target_id,
                    mention_target_name,
                ),
            )
            self.connection.commit()
            return int(cur.lastrowid)

    def due_reminders(self, *, now: datetime, limit: int = 50) -> List[sqlite3.Row]:
        """Возвращает список непросланных напоминаний, срок которых наступил."""

        with closing(self.connection.cursor()) as cur:
            cur.execute(
                """
                SELECT id, chat_id, text, remind_at, mention_target_id, mention_target_name
                FROM reminders
                WHERE status = 'scheduled' AND is_sent = 0 AND remind_at <= ?
                ORDER BY remind_at ASC
                LIMIT ?
                """,
                (now.isoformat(timespec="minutes"), limit),
            )
            return cur.fetchall()

    def mark_sent(self, reminder_ids: Iterable[int]) -> None:
        """Отмечает напоминания как отправленные."""

        ids = list(reminder_ids)
        if not ids:
            return

        with closing(self.connection.cursor()) as cur:
            cur.execute(
                f"""
                UPDATE reminders
                SET is_sent = 1, status = 'sent'
                WHERE id IN ({','.join('?' * len(ids))})
                """,
                ids,
            )
            self.connection.commit()

    def list_reminders(
        self, *, chat_id: int, creator_id: int, limit: int = 20
    ) -> List[sqlite3.Row]:
        """Возвращает последние напоминания пользователя в чате."""

        with closing(self.connection.cursor()) as cur:
            cur.execute(
                """
                SELECT id, text, remind_at, status, mention_target_name
                FROM reminders
                WHERE chat_id = ? AND creator_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (chat_id, creator_id, limit),
            )
            return cur.fetchall()

    def close(self) -> None:
        self.connection.close()
