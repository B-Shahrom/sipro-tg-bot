"""Setup helpers that work in any chat, for anyone."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="utils")


@router.message(Command("id"))
async def cmd_id(message: Message):
    lines = [f"Ваш user id: <code>{message.from_user.id}</code>  → ADMIN_IDS"]
    if message.chat.type != "private":
        lines.append(f"ID этого чата: <code>{message.chat.id}</code>  → MANAGER_CHAT_ID")
    await message.answer("\n".join(lines))
