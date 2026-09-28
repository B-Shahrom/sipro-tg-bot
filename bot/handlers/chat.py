"""Free-form chat: goes to the AI assistant, or to managers while a live chat (handoff) is active."""

import logging

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from ..ai.assistant import Assistant, AssistantUnavailable
from ..ai.tools import ToolContext
from ..config import Settings
from ..db import Database
from ..formatting import esc
from ..keyboards import back_to_ai_kb
from ..services import customer_header, forward_to_managers, send_html, start_handoff, to_managers
from ..texts import t

log = logging.getLogger(__name__)
router = Router(name="chat")


async def ask_assistant(
    message: Message, user_id: int, text: str, db: Database, settings: Settings,
    assistant: Assistant, lang: str, customer,
) -> None:
    """Answer `text` from customer `user_id` with the AI; replies go to `message.chat`."""
    bot = message.bot
    chat_id = message.chat.id

    if customer["handoff"]:
        await to_managers(bot, db, settings.manager_chat_id, user_id,
                          f"💬 {await customer_header(db, user_id)}\n\n{esc(text)}")
        await message.answer(t("handoff_active_hint", lang))
        return

    if not await db.take_ai_quota(user_id, settings.ai_daily_limit):
        await message.answer(t("ai_limit", lang))
        return

    async def on_handoff(reason: str, summary: str) -> None:
        await start_handoff(bot, db, settings.manager_chat_id, user_id, reason, summary)

    ctx = ToolContext(db=db, user_id=user_id, currency=settings.currency, on_handoff=on_handoff)
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
            reply = await assistant.reply(ctx, lang, text)
    except AssistantUnavailable:
        if not ctx.handed_off:
            await start_handoff(bot, db, settings.manager_chat_id, user_id, "Ассистент недоступен (ошибка API)", text[:500])
        await message.answer(t("ai_unavailable", lang), reply_markup=back_to_ai_kb(lang))
        return

    markup = back_to_ai_kb(lang) if reply.handed_off else None
    if reply.refused:
        await message.answer(t("ai_refusal", lang), reply_markup=markup)
    elif reply.text:
        await send_html(bot, chat_id, reply.text, reply_markup=markup)
    elif reply.handed_off:
        await message.answer(t("handoff_started", lang), reply_markup=markup)
    else:
        await message.answer(t("unknown_error", lang))


@router.message(StateFilter(None), F.text)
async def on_text(message: Message, db: Database, settings: Settings, assistant: Assistant, lang: str, customer):
    if customer["handoff"]:
        await forward_to_managers(message.bot, db, settings.manager_chat_id, message)
        return
    await ask_assistant(message, message.from_user.id, message.text, db, settings, assistant, lang, customer)


@router.message(StateFilter(None))
async def on_other(message: Message, db: Database, settings: Settings, lang: str, customer):
    if customer["handoff"]:
        await forward_to_managers(message.bot, db, settings.manager_chat_id, message)
        return
    await message.answer(t("unsupported_message", lang))
