"""Configuration utilities for the reminder bot."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@dataclass
class Settings:
    """Application settings loaded from environment variables.

    Attributes:
        bot_token: Telegram bot token from BotFather.
        database_path: Path to the SQLite database file.
        poll_interval_seconds: How often (in seconds) to poll for due reminders.
    """

    bot_token: str
    database_path: Path
    poll_interval_seconds: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables with sensible defaults."""

        # Поддерживаем локальную разработку с помощью файла .env
        dotenv_path = find_dotenv(usecwd=True)
        if dotenv_path:
            load_dotenv(dotenv_path=dotenv_path)

        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError(
                "Environment variable TELEGRAM_BOT_TOKEN is required to start the bot. "
                "Set it in your shell or in a .env file (see .env.example)."
            )

        db_path = Path(os.environ.get("REMINDER_DB_PATH", "reminders.db"))
        poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))

        return cls(bot_token=token, database_path=db_path, poll_interval_seconds=poll_interval)
