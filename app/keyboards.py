"""Reply keyboard definitions."""
from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="⏰ Новое напоминание"),
            KeyboardButton(text="🗒 Мои напоминания"),
        ],
        [KeyboardButton(text="↩️ Вернуться в меню")],
    ],
    resize_keyboard=True,
    one_time_keyboard=False,
)
