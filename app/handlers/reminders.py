"""Handlers responsible for reminder creation and management."""
from __future__ import annotations

import contextlib
import html
from datetime import datetime
import logging
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db import ReminderStore
from app.keyboards import main_keyboard

logger = logging.getLogger(__name__)


class ReminderForm(StatesGroup):
    """FSM состояния для пошагового создания напоминания."""

    waiting_for_text = State()
    waiting_for_datetime = State()
    waiting_for_mention = State()


def parse_datetime(user_input: str) -> datetime:
    """Парсит дату и время в формате YYYY-MM-DD HH:MM."""

    return datetime.strptime(user_input.strip(), "%Y-%m-%d %H:%M")


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


async def handle_list_shortcut(
    message: Message, state: FSMContext, store: ReminderStore
) -> None:
    """Обрабатывает кнопку "Мои напоминания" и очищает состояние."""

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
    except ValueError as exc:
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

    await message.answer("🗒 Ваши напоминания:")

    for row in reminders:
        mention = (
            f" (упомянуть: {html.escape(row['mention_target_name'])})"
            if row["mention_target_name"]
            else ""
        )
        remind_at = row["remind_at"]
        if isinstance(remind_at, str):
            with contextlib.suppress(ValueError):
                remind_at_dt = datetime.fromisoformat(remind_at)
                remind_at = remind_at_dt.strftime("%Y-%m-%d %H:%M")

        status = row["status"]
        status_icon = {
            "scheduled": "🟢",
            "sent": "📨",
            "completed": "✅",
            "cancelled": "🚫",
            "failed": "⚠️",
        }.get(status, "ℹ️")

        text = (
            f"{status_icon} #{row['id']} — {html.escape(row['text'])}\n"
            f"⏰ {remind_at}{mention}"
        )

        keyboard = _build_reminder_keyboard(row["id"], status)
        await message.answer(text, reply_markup=keyboard, parse_mode=None)


def _parse_id_arg(message: Message) -> tuple[bool, int | None]:
    """Пытается вытащить ID напоминания из команды."""

    if not message.text:
        return False, None

    parts = message.text.split()
    if len(parts) < 2:
        return False, None
    try:
        return True, int(parts[1])
    except ValueError:
        return False, None


async def handle_cancel(message: Message, store: ReminderStore) -> None:
    """Отменяет запрошенное напоминание."""

    ok, reminder_id = _parse_id_arg(message)
    if not ok or reminder_id is None:
        await message.answer("Использование: /cancel <id>", parse_mode=None)
        return

    success = store.cancel_reminder(
        reminder_id=reminder_id, chat_id=message.chat.id, creator_id=message.from_user.id
    )
    if success:
        await message.answer(f"Напоминание #{reminder_id} отменено.")
    else:
        await message.answer("Не удалось отменить: проверьте ID и статус напоминания.")


async def handle_done(message: Message, store: ReminderStore) -> None:
    """Помечает напоминание выполненным."""

    ok, reminder_id = _parse_id_arg(message)
    if not ok or reminder_id is None:
        await message.answer("Использование: /done <id>", parse_mode=None)
        return

    success = store.complete_reminder(
        reminder_id=reminder_id, chat_id=message.chat.id, creator_id=message.from_user.id
    )
    if success:
        await message.answer(f"Напоминание #{reminder_id} отмечено как выполненное.")
    else:
        await message.answer("Не удалось обновить напоминание. Проверьте ID и статус.")


async def handle_move(message: Message, store: ReminderStore) -> None:
    """Переносит напоминание на новую дату."""

    if not message.text:
        await message.answer("Использование: /move <id> YYYY-MM-DD HH:MM", parse_mode=None)
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование: /move <id> YYYY-MM-DD HH:MM", parse_mode=None)
        return

    try:
        reminder_id = int(parts[1])
        new_datetime = parse_datetime(parts[2])
        if new_datetime <= datetime.now():
            raise ValueError("Дата должна быть в будущем")
    except ValueError as exc:
        await message.answer(f"Ошибка: {exc}. Формат даты: 2024-12-31 18:30")
        return

    success = store.reschedule_reminder(
        reminder_id=reminder_id,
        chat_id=message.chat.id,
        creator_id=message.from_user.id,
        remind_at=new_datetime,
    )
    if success:
        await message.answer(
            f"Напоминание #{reminder_id} перенесено на {new_datetime:%Y-%m-%d %H:%M}."
        )
    else:
        await message.answer("Не удалось перенести напоминание. Проверьте ID и статус.")


async def process_keyboard_shortcut(
    message: Message, state: FSMContext, store: ReminderStore
) -> None:
    """Обрабатывает кнопку "Новое напоминание" как /new."""

    if not message.text:
        return

    if "Новое напоминание" in message.text:
        await handle_new(message, state)
    if "Мои напоминания" in message.text:
        await handle_list(message, store)


def _build_reminder_keyboard(reminder_id: int, status: str):
    """Создает компактные кнопки действий для напоминания."""

    if status not in {"scheduled", "sent"}:
        return None

    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Выполнено",
        callback_data=f"reminder:done:{reminder_id}",
    )
    builder.button(
        text="🚫 Отменить",
        callback_data=f"reminder:cancel:{reminder_id}",
    )
    builder.button(
        text="🗓 Перенести",
        switch_inline_query_current_chat=f"/move {reminder_id} ",
    )
    builder.adjust(2, 1)
    return builder.as_markup()


async def handle_reminder_action(
    callback: CallbackQuery, store: ReminderStore
) -> None:
    """Обрабатывает нажатия кнопок «Выполнено» и «Отменить»."""

    if not callback.data or callback.message is None:
        await callback.answer("Что-то пошло не так.", show_alert=True)
        return

    try:
        _, action, reminder_id_str = callback.data.split(":", maxsplit=2)
        reminder_id = int(reminder_id_str)
    except ValueError:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id

    if action == "done":
        success = store.complete_reminder(
            reminder_id=reminder_id, chat_id=chat_id, creator_id=user_id
        )
        success_message = "Напоминание отмечено выполненным."
        new_status_label = "✅ Статус: выполнено"
    elif action == "cancel":
        success = store.cancel_reminder(
            reminder_id=reminder_id, chat_id=chat_id, creator_id=user_id
        )
        success_message = "Напоминание отменено."
        new_status_label = "🚫 Статус: отменено"
    else:
        await callback.answer("Неизвестное действие.", show_alert=True)
        return

    if not success:
        await callback.answer(
            "Не удалось обновить напоминание. Проверьте его статус.", show_alert=True
        )
        return

    base_text = callback.message.text or callback.message.html_text or ""
    await callback.message.edit_text(
        f"{base_text}\n\n{new_status_label}",
        reply_markup=None,
        parse_mode=None,
    )
    await callback.answer(success_message)
