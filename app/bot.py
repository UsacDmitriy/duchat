"""Telegram reminder bot built with aiogram 3."""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
import logging
from typing import List

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
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
    waiting_for_mention = State()


async def set_bot_commands(bot: Bot) -> None:
    """Регистрирует команды, которые увидит пользователь в меню Telegram."""

    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Начать работу с ботом"),
            BotCommand(command="new", description="Создать напоминание"),
            BotCommand(command="list", description="Список моих напоминаний"),
            BotCommand(command="help", description="Как пользоваться ботом"),
        ]
    )


# Примитивная клавиатура для быстрого доступа к созданию напоминания
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
            "• /list — посмотреть последние напоминания, созданные вами.\n"
            "• Сообщите дату в формате YYYY-MM-DD HH:MM.\n"
            "• Бот должен оставаться в группе, чтобы присылать уведомления."
        )
    )


async def handle_back_to_menu(message: Message, state: FSMContext) -> None:
    """Сбрасывает текущее состояние и возвращает пользователя в меню."""

    await state.clear()
    await message.answer(
        "Возвращаю в главное меню. Что сделать?",
        reply_markup=main_keyboard,
    )


async def handle_new(message: Message, state: FSMContext) -> None:
    """Запускает процесс создания напоминания."""

    await state.set_state(ReminderForm.waiting_for_text)
    await message.answer(
        "📝 Какое событие нужно напомнить? Опишите его в одном сообщении.",
        reply_markup=main_keyboard,
    )


async def handle_list_from_any_state(
    message: Message, state: FSMContext, store: ReminderStore
) -> None:
    """Показывает список напоминаний, предварительно очищая состояние FSM."""

    await state.clear()
    await handle_list(message, store)


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
    await state.update_data(remind_at=remind_at)
    await state.set_state(ReminderForm.waiting_for_mention)
    await message.answer(
        (
            "Кого упомянуть в уведомлении?\n"
            "Пришлите @username или имя. Если никого не нужно упоминать — отправьте '-'"
        )
    )


def _extract_mention_data(message: Message) -> tuple[None | int, None | str]:
    """Пытается вытащить пользователя из сущностей или текста."""

    if not message.text:
        return None, None

    if message.entities:
        for entity in message.entities:
            if entity.type in {"text_mention", "mention"}:
                if entity.type == "text_mention" and entity.user:
                    return entity.user.id, entity.user.full_name
                if entity.type == "mention":
                    username = message.text[entity.offset : entity.offset + entity.length]
                    return None, username

    cleaned = message.text.strip()
    if cleaned in {"-", "—", ""}:
        return None, None
    return None, cleaned


async def handle_mention(
    message: Message, state: FSMContext, store: ReminderStore
) -> None:
    """Финальный шаг создания напоминания с учетом упоминания."""

    mention_id, mention_name = _extract_mention_data(message)

    data = await state.get_data()
    text = data.get("text", "Без текста")
    remind_at: datetime = data["remind_at"]

    reminder_id = store.add_reminder(
        chat_id=message.chat.id,
        creator_id=message.from_user.id,
        text=text,
        remind_at=remind_at,
        mention_target_id=mention_id,
        mention_target_name=mention_name,
    )

    await state.clear()
    mention_note = f" Укажу {mention_name}" if mention_name else ""
    await message.answer(
        (
            f"✅ Напоминание сохранено (ID: {reminder_id}).{mention_note}\n"
            f"⏰ Напомню {remind_at:%Y-%m-%d %H:%M}."
        ),
        reply_markup=main_keyboard,
    )


async def handle_list(message: Message, store: ReminderStore) -> None:
    """Показывает список напоминаний пользователя."""

    reminders = store.list_reminders(
        chat_id=message.chat.id, creator_id=message.from_user.id, limit=20
    )
    if not reminders:
        await message.answer("У вас пока нет напоминаний в этом чате.")
        return

    lines = ["🗒 Ваши напоминания:"]
    for row in reminders:
        mention = f" (упомянуть: {row['mention_target_name']})" if row["mention_target_name"] else ""
        lines.append(
            (
                f"• #{row['id']} [{row['status']}] {row['text']}\n"
                f"  ⏰ {row['remind_at']}{mention}"
            )
        )

    await message.answer("\n".join(lines))


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
            mention_target_id = row["mention_target_id"]
            mention_target_name = row["mention_target_name"] or "пользователь"

            mention_block = ""
            if mention_target_id:
                mention_block = f"<a href=\"tg://user?id={mention_target_id}\">{mention_target_name}</a>, "
            elif row["mention_target_name"]:
                mention_block = f"{mention_target_name}, "

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
                # В логах контейнера будет видно, если у бота нет прав или чат недоступен.
                print(f"Failed to deliver reminder {row['id']} to chat {chat_id}: {exc}")

        if sent_ids:
            store.mark_sent(sent_ids)

        await asyncio.sleep(poll_interval)


async def main() -> None:
    """Точка входа: настраивает бота, БД и запускает опрос событий."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    settings = Settings.from_env()
    store = ReminderStore(settings.database_path)
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрируем команды и хендлеры
    await set_bot_commands(bot)
    dp.message.register(handle_start, CommandStart())
    dp.message.register(handle_help, Command("help"))
    dp.message.register(handle_new, Command("new"))
    dp.message.register(handle_list_from_any_state, Command("list"), state="*")
    dp.message.register(
        handle_list_from_any_state, F.text.contains("Мои напоминания"), state="*"
    )
    dp.message.register(
        handle_back_to_menu, F.text.contains("Вернуться в меню"), state="*"
    )
    dp.message.register(handle_datetime, ReminderForm.waiting_for_datetime)
    dp.message.register(handle_mention, ReminderForm.waiting_for_mention)
    dp.message.register(handle_text, ReminderForm.waiting_for_text)
    dp.message.register(process_keyboard_shortcut, F.text.contains("Новое напоминание"))

    # Запускаем фонового воркера в отдельной задаче
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
        reminder_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reminder_task
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
