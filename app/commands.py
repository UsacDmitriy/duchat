"""Telegram bot command registration."""
from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand


async def set_bot_commands(bot: Bot) -> None:
    """Регистрирует команды, которые увидит пользователь в меню Telegram."""

    await bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Начать работу с ботом"),
            BotCommand(command="new", description="Создать напоминание"),
            BotCommand(command="list", description="Список моих напоминаний"),
            BotCommand(command="cancel", description="Отменить напоминание по ID"),
            BotCommand(command="done", description="Отметить напоминание как выполненное"),
            BotCommand(command="move", description="Перенести напоминание на другую дату"),
            BotCommand(command="help", description="Как пользоваться ботом"),
        ]
    )
