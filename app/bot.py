"""Telegram reminder bot built with aiogram 3."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import List

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, KeyboardButton, Message, ReplyKeyboardMarkup

from app.config import Settings
from app.db import ReminderStore


class ReminderForm(StatesGroup):
    """FSM состояния для пошагового создания напоминания."""

    waiting_for_text = State()
    waiting_for_datetime = State()


async def set_bot_commands(bot: Bot) -> None:
    """Регистрирует команды, которые увидит пользователь в меню Telegram."""

    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Начать работу с ботом"),
            BotCommand(command="new", description="Создать напоминание"),
            BotCommand(command="help", description="Как пользоваться ботом"),
        ]
    )


# Примитивная клавиатура для быстрого доступа к созданию напоминания
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="⏰ Новое напоминание")]],
    resize_keyboard=True,
    one_time_keyboard=False,
)


def parse_datetime(user_input: str) -> datetime:
    """Парсит дату и время в формате YYYY-MM-DD HH:MM.

    В продакшене стоило бы поддержать таймзоны и разные форматы,
    но здесь оставляем один четкий шаблон для простоты.
    """

    return datetime.strptime(user_input.strip(), "%Y-%m-%d %H:%M")


async def handle_start(message: Message) -> None:
    """Приветствие и подсказка по дальнейшим действиям."""

    await message.answer(
        (
            "📢 Привет! Я помогу напоминать о важных событиях.\n"
            "Нажми кнопку \"Новое напоминание\" или используй /new, чтобы создать напоминание.\n"
            "Формат даты: YYYY-MM-DD HH:MM (24 часа)."
        ),
        reply_markup=main_keyboard,
    )


async def handle_help(message: Message) -> None:
    """Краткая справка для пользователей и администраторов групп."""

    await message.answer(
        (
            "• /new — создать напоминание для текущего чата (работает и в группах).\n"
            "• Сообщите дату в формате YYYY-MM-DD HH:MM.\n"
            "• Бот должен оставаться в группе, чтобы присылать уведомления."
        )
    )


async def handle_new(message: Message, state: FSMContext) -> None:
    """Запускает процесс создания напоминания."""

    await state.set_state(ReminderForm.waiting_for_text)
    await message.answer(
        "📝 Какое событие нужно напомнить? Опишите его в одном сообщении.",
        reply_markup=main_keyboard,
    )


async def handle_text(message: Message, state: FSMContext) -> None:
    """Сохраняет текст события и просит дату."""

    await state.update_data(text=message.text)
    await state.set_state(ReminderForm.waiting_for_datetime)
    await message.answer(
        (
            "🕐 Когда напомнить?\n"
            "Введите дату и время в формате 2024-12-31 18:30"
        )
    )


async def handle_datetime(
    message: Message, state: FSMContext, store: ReminderStore
) -> None:
    """Пытается распарсить дату и сохранить напоминание."""

    try:
        remind_at = parse_datetime(message.text)
        if remind_at <= datetime.now():
            raise ValueError("Дата должна быть в будущем")
    except ValueError as exc:  # некорректный ввод
        await message.answer(
            f"❌ {exc}. Попробуйте еще раз в формате 2024-12-31 18:30"
        )
        return

    data = await state.get_data()
    text = data.get("text", "Без текста")

    reminder_id = store.add_reminder(
        chat_id=message.chat.id, creator_id=message.from_user.id, text=text, remind_at=remind_at
    )

    await state.clear()
    await message.answer(
        (
            f"✅ Напоминание сохранено (ID: {reminder_id}).\n"
            f"⏰ Напомню {remind_at:%Y-%m-%d %H:%M}."
        ),
        reply_markup=main_keyboard,
    )


async def process_keyboard_shortcut(message: Message, state: FSMContext) -> None:
    """Обрабатывает кнопку "Новое напоминание" как /new."""

    if message.text and "Новое напоминание" in message.text:
        await handle_new(message, state)


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

            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "🔔 Напоминание!\n"
                        f"{text}\n"
                        f"Запланировано на: {remind_at}"
                    ),
                    parse_mode=ParseMode.HTML,
                )
                sent_ids.append(int(row["id"]))
            except Exception as exc:  # noqa: BLE001 — фиксируем ошибку и продолжаем
                # В логах контейнера будет видно, если у бота нет прав или чат недоступен.
                print(f"Failed to deliver reminder {row['id']} to chat {chat_id}: {exc}")

        if sent_ids:
            store.mark_sent(sent_ids)

        await asyncio.sleep(poll_interval)


async def main() -> None:
    """Точка входа: настраивает бота, БД и запускает опрос событий."""

    settings = Settings.from_env()
    store = ReminderStore(settings.database_path)
    bot = Bot(token=settings.bot_token, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем команды и хендлеры
    await set_bot_commands(bot)
    dp.message.register(handle_start, CommandStart())
    dp.message.register(handle_help, Command("help"))
    dp.message.register(handle_new, Command("new"))
    dp.message.register(handle_datetime, ReminderForm.waiting_for_datetime)
    dp.message.register(handle_text, ReminderForm.waiting_for_text)
    dp.message.register(process_keyboard_shortcut, F.text.contains("Новое напоминание"))

    # Запускаем фонового воркера в отдельной задаче
    reminder_task = asyncio.create_task(
        reminder_worker(bot, store, settings.poll_interval_seconds)
    )

    try:
        await dp.start_polling(bot, store=store)
    finally:
        reminder_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminder_task
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
