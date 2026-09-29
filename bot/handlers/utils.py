"""Setup helpers: find Telegram ids for ADMIN_IDS / MANAGER_CHAT_ID.

- /id                      your id (and the chat id in groups)
- /id as a reply           also the id of that message's author (or of the customer, for bot relay posts)
- forward a message to the bot in private (admins, or anyone while ADMIN_IDS is empty)
                           the id of the original sender
"""

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import (
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    User,
)

from ..config import Settings
from ..db import Database
from ..formatting import esc

router = Router(name="utils")


def _user_line(user: User) -> str:
    username = f" (@{esc(user.username)})" if user.username else ""
    kind = "бот" if user.is_bot else "пользователь"
    return f"{kind} {esc(user.full_name)}{username}: <code>{user.id}</code>"


def describe_origin(origin) -> str:
    if isinstance(origin, MessageOriginUser):
        return "Автор пересланного сообщения — " + _user_line(origin.sender_user)
    if isinstance(origin, MessageOriginHiddenUser):
        return (
            f"Автор пересланного сообщения: {esc(origin.sender_user_name)} — <b>id скрыт</b> "
            "его настройками приватности (Пересылка сообщений). Попросите человека отправить боту /id."
        )
    if isinstance(origin, MessageOriginChat):
        return f"Переслано от имени группы {esc(origin.sender_chat.title or '')}: <code>{origin.sender_chat.id}</code>"
    if isinstance(origin, MessageOriginChannel):
        return f"Переслано из канала {esc(origin.chat.title or '')}: <code>{origin.chat.id}</code>"
    return "Не удалось определить автора пересланного сообщения."


async def describe_author(message: Message, db: Database) -> str:
    if message.forward_origin:
        return describe_origin(message.forward_origin)
    if message.from_user and message.from_user.is_bot:
        customer_id = await db.relay_target(message.message_id)
        if customer_id:
            return f"Клиент из этого сообщения бота: <code>{customer_id}</code>"
    if message.from_user:
        return "Автор сообщения — " + _user_line(message.from_user)
    if message.sender_chat:
        return f"Сообщение от имени чата {esc(message.sender_chat.title or '')}: <code>{message.sender_chat.id}</code>"
    return "Не удалось определить автора сообщения."


@router.message(Command("id"))
async def cmd_id(message: Message, db: Database):
    lines = [f"Ваш user id: <code>{message.from_user.id}</code>  → ADMIN_IDS"]
    if message.chat.type != "private":
        lines.append(f"ID этого чата: <code>{message.chat.id}</code>  → MANAGER_CHAT_ID")
    if message.reply_to_message:
        lines.append(await describe_author(message.reply_to_message, db))
    await message.answer("\n".join(lines))


class CanLookUpIds(BaseFilter):
    """Admins, or anyone during first setup (ADMIN_IDS empty). Customers' forwards go to the assistant as usual."""

    async def __call__(self, message: Message, settings: Settings) -> bool:
        return not settings.admin_ids or message.from_user.id in settings.admin_ids


@router.message(F.chat.type == "private", F.forward_origin, CanLookUpIds())
async def on_forward(message: Message):
    hint = "\n\n<i>Этот id можно вписать в ADMIN_IDS.</i>" if isinstance(message.forward_origin, MessageOriginUser) else ""
    await message.answer(describe_origin(message.forward_origin) + hint)
