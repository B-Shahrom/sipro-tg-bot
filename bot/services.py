"""Messaging to the managers' group and the live-chat (handoff) relay."""

import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message

from .db import Database
from .formatting import esc, split_message, strip_html, user_link

log = logging.getLogger(__name__)


async def send_html(bot: Bot, chat_id: int, text: str, **kwargs) -> Message:
    """Send HTML text, split to fit Telegram limits. Falls back to plain text if the HTML is malformed."""
    parts = split_message(text)
    sent = None
    for i, part in enumerate(parts):
        extra = kwargs if i == len(parts) - 1 else {}
        try:
            sent = await bot.send_message(chat_id, part, **extra)
        except TelegramBadRequest as e:
            if "parse" not in str(e).lower() and "entities" not in str(e).lower():
                raise
            sent = await bot.send_message(chat_id, strip_html(part), parse_mode=None, **extra)
    return sent


async def to_managers(
    bot: Bot, db: Database, manager_chat_id: int, user_id: int, text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Post to the managers' group. Managers can reply to the post to answer the customer."""
    sent = await send_html(bot, manager_chat_id, text, reply_markup=reply_markup)
    await db.remember_relay(sent.message_id, user_id)
    return sent


async def customer_header(db: Database, user_id: int) -> str:
    user = await db.get_user(user_id)
    if not user:
        return f"<code>{user_id}</code>"
    phone = f" · {esc(user['phone'])}" if user["phone"] else ""
    return f"{user_link(user_id, user['full_name'], user['username'])}{phone} · <code>#u{user_id}</code>"


async def start_handoff(
    bot: Bot, db: Database, manager_chat_id: int, user_id: int, reason: str, summary: str = ""
) -> None:
    await db.set_handoff(user_id, True)
    history = await db.get_history(user_id, 8)
    recent = []
    for m in history:
        if isinstance(m["content"], str):
            recent.append(f"👤 {esc(m['content'][:300])}")
        else:
            texts = [b["text"] for b in m["content"] if b.get("type") == "text"]
            if m["role"] == "assistant" and texts:
                recent.append(f"🤖 {esc(' '.join(texts)[:300])}")
    lines = [
        "🙋 <b>Клиент просит менеджера</b>",
        await customer_header(db, user_id),
        f"<b>Причина:</b> {esc(reason)}" if reason else "",
        f"<b>Суть:</b> {esc(summary)}" if summary else "",
    ]
    if recent:
        lines.append("\n<b>Последние сообщения:</b>\n" + "\n".join(recent[-6:]))
    lines.append("\n<i>Ответьте на это сообщение (reply), чтобы написать клиенту. /close в ответе — вернуть клиента ассистенту.</i>")
    await to_managers(bot, db, manager_chat_id, user_id, "\n".join(line for line in lines if line))


async def forward_to_managers(bot: Bot, db: Database, manager_chat_id: int, message: Message) -> None:
    """Relay a customer message (any content type) to the managers' group during a live chat."""
    user_id = message.from_user.id
    header_text = f"💬 {await customer_header(db, user_id)}"
    if message.text:
        await to_managers(bot, db, manager_chat_id, user_id, f"{header_text}\n\n{esc(message.text)}")
        return
    header = await to_managers(bot, db, manager_chat_id, user_id, header_text)
    try:
        copied = await message.copy_to(manager_chat_id, reply_to_message_id=header.message_id)
        await db.remember_relay(copied.message_id, user_id)
    except TelegramBadRequest:
        log.exception("could not copy message from %s", user_id)


def photo_source(p, media_dir: Path) -> str | FSInputFile | None:
    """Telegram file_id (fastest), URL, or a local file under media_dir."""
    if p.image_file_id:
        return p.image_file_id
    if not p.image_url:
        return None
    if p.image_url.startswith(("http://", "https://")):
        return p.image_url
    path = (media_dir / p.image_url).resolve()
    if path.is_file() and path.is_relative_to(media_dir.resolve()):
        return FSInputFile(path)
    return None


async def send_product(message: Message, p, db: Database, media_dir: Path, caption: str, reply_markup=None) -> Message:
    """Send a product card as a photo when an image is available, caching Telegram's file_id for next time."""
    source = photo_source(p, media_dir)
    if source is not None:
        try:
            sent = await message.answer_photo(source, caption=caption, reply_markup=reply_markup)
            if not p.image_file_id and sent.photo:
                await db.set_image_file_id(p.sku, sent.photo[-1].file_id)
            return sent
        except TelegramBadRequest:
            log.warning("could not send image for %s (%s)", p.sku, p.image_url)
            if p.image_file_id:
                await db.set_image_file_id(p.sku, "")
    return await message.answer(caption, reply_markup=reply_markup)
