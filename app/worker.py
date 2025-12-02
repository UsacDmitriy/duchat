"""Background worker that dispatches due reminders."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import List

from aiogram import Bot
from aiogram.enums import ParseMode

from app.db import ReminderStore

logger = logging.getLogger(__name__)


async def reminder_worker(bot: Bot, store: ReminderStore, poll_interval: int) -> None:
    """Фоновый цикл, который ищет просроченные напоминания и отправляет их."""

    while True:
        now = datetime.now()
        due = store.due_reminders(now=now)
        sent_ids: List[int] = []

        for row in due:
            text = row["text"]
            remind_at = row["remind_at"]
            chat_id = row["chat_id"]
            mention_target_id = row["mention_target_id"]
            mention_target_name = row["mention_target_name"] or "пользователь"

            mention_block = ""
            if mention_target_id:
                mention_block = f"<a href=\"tg://user?id={mention_target_id}\">{mention_target_name}</a>, "
            elif row["mention_target_name"]:
                mention_block = f"{mention_target_name}, "

            logger.info(
                "Sending reminder %s to chat %s (remind_at=%s)",
                row["id"],
                chat_id,
                remind_at,
            )
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "🔔 Напоминание!\n"
                        f"{mention_block}{text}\n"
                        f"Запланировано на: {remind_at}"
                    ),
                    parse_mode=ParseMode.HTML,
                )
                sent_ids.append(int(row["id"]))
            except Exception as exc:  # noqa: BLE001 — фиксируем ошибку и продолжаем
                logger.warning(
                    "Failed to deliver reminder %s to chat %s: %s",
                    row["id"],
                    chat_id,
                    exc,
                    exc_info=True,
                )
                store.mark_failed(int(row["id"]))

        if sent_ids:
            store.mark_sent(sent_ids)

        await asyncio.sleep(poll_interval)
