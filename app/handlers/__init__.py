"""Handler registration helpers for the bot dispatcher."""
from __future__ import annotations

from aiogram import Dispatcher, F
from aiogram.filters import Command, CommandStart, StateFilter

from app.handlers import common, reminders


def register_handlers(dp: Dispatcher) -> None:
    """Attach all message handlers to the dispatcher."""

    dp.message.register(common.handle_start, CommandStart())
    dp.message.register(common.handle_help, Command("help"))
    dp.message.register(common.handle_back_to_menu, F.text.contains("Вернуться в меню"), StateFilter("*"))

    dp.message.register(reminders.handle_new, Command("new"))
    dp.message.register(reminders.handle_list_from_any_state, Command("list"), StateFilter("*"))
    dp.message.register(reminders.handle_cancel, Command("cancel"))
    dp.message.register(reminders.handle_done, Command("done"))
    dp.message.register(reminders.handle_move, Command("move"))
    dp.message.register(
        reminders.handle_list_from_any_state,
        F.text.contains("Мои напоминания"),
        StateFilter("*"),
    )
    dp.message.register(
        reminders.handle_list_shortcut, F.text.contains("Мои напоминания"), StateFilter("*")
    )
    dp.message.register(reminders.handle_datetime, StateFilter(reminders.ReminderForm.waiting_for_datetime))
    dp.message.register(reminders.handle_mention, StateFilter(reminders.ReminderForm.waiting_for_mention))
    dp.message.register(reminders.handle_text, StateFilter(reminders.ReminderForm.waiting_for_text))
    dp.message.register(
        reminders.process_keyboard_shortcut,
        F.text.in_(["⏰ Новое напоминание", "📋 Мои напоминания"]),
    )

    dp.callback_query.register(
        reminders.handle_reminder_action, F.data.startswith("reminder:")
    )

    # Backup registration for users invoking /list when FSM is not active
    dp.message.register(reminders.handle_list, Command("list"))
