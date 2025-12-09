"""Telegram reminder bot built with aiogram 3."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.commands import set_bot_commands
from app.config import Settings
from app.db import ReminderStore
from app.handlers import register_handlers
from app.worker import reminder_worker


async def main() -> None:
    """Точка входа: настраивает бота, БД и запускает опрос событий."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    settings = Settings.from_env()
    store = ReminderStore(settings.database_path)
    dp = Dispatcher(storage=MemoryStorage())

    reminder_task: asyncio.Task | None = None

    async with Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    ) as bot:
        await set_bot_commands(bot)
        register_handlers(dp)

        reminder_task = asyncio.create_task(
            reminder_worker(bot, store, settings.poll_interval_seconds)
        )
        logging.info(
            "🚀 Бот запущен. Слушаем обновления, воркер проверяет напоминания каждые %s сек."
            " База: %s",
            settings.poll_interval_seconds,
            settings.database_path,
        )

        try:
            await dp.start_polling(bot, store=store)
        finally:
            if reminder_task:
                reminder_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reminder_task
            store.close()


if __name__ == "__main__":
    asyncio.run(main())
