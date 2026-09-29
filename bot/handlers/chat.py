"""Free-form chat. Order of preference:
1. live chat with a manager (handoff) — messages go to the managers' group;
2. the AI assistant, when configured and responding;
3. the rule-based assistant (bot/offline) — when there's no API key, the API is down or slow, or the customer
   used up the daily AI quota.
"""

import logging
from typing import Awaitable, Callable

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.chat_action import ChatActionSender

from ..ai.assistant import Assistant, AssistantUnavailable
from ..ai.tools import ToolContext
from ..config import Settings
from ..db import Database
from ..formatting import esc
from ..keyboards import BuildCb, QuickCb, back_to_ai_kb, offline_reply_kb, product_kb
from ..offline.engine import OfflineAssistant, OfflineReply
from ..services import customer_header, forward_to_managers, send_html, send_product, start_handoff, to_managers
from ..texts import t
from . import builder, cart, catalog, handoff, orders, service

log = logging.getLogger(__name__)
router = Router(name="chat")

# Last rule-based build per customer, for the "add the whole build to cart" button.
LAST_BUILDS: dict[int, list[str]] = {}
_MAX_BUILDS = 5000

OfflineFactory = Callable[[], Awaitable[OfflineReply | None]]


async def ask_assistant(
    message: Message, user_id: int, text: str, db: Database, settings: Settings,
    assistant: Assistant, lang: str, customer, offline: OfflineAssistant, state: FSMContext | None = None,
    offline_reply: OfflineFactory | None = None,
) -> None:
    """Answer `text` from customer `user_id`; replies go to `message.chat`.

    offline_reply: how to answer without AI (defaults to the rule-based assistant reading `text`).
    """
    bot = message.bot

    if customer["handoff"]:
        await to_managers(bot, db, settings.manager_chat_id, user_id,
                          f"💬 {await customer_header(db, user_id)}\n\n{esc(text)}")
        await message.answer(t("handoff_active_hint", lang))
        return

    if assistant.available and await db.take_ai_quota(user_id, settings.ai_daily_limit):
        if await _answer_with_ai(message, user_id, text, db, settings, assistant, lang):
            return

    reply = await (offline_reply() if offline_reply else offline.reply(user_id, text, degraded=assistant.enabled))
    if reply is None:
        reply = await offline.reply(user_id, text, degraded=assistant.enabled)
    await render_offline(message, user_id, reply, db, settings, lang, state)


async def _answer_with_ai(message: Message, user_id: int, text: str, db: Database, settings: Settings,
                          assistant: Assistant, lang: str) -> bool:
    """True if the AI handled the message; False to fall back to the rule-based assistant."""
    bot = message.bot

    async def on_handoff(reason: str, summary: str) -> None:
        await start_handoff(bot, db, settings.manager_chat_id, user_id, reason, summary)

    ctx = ToolContext(db=db, user_id=user_id, currency=settings.currency, on_handoff=on_handoff)
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=message.chat.id):
            reply = await assistant.reply(ctx, lang, text)
    except AssistantUnavailable as e:
        if assistant.record_failure(str(e) or "unknown error"):
            await _alert_managers(bot, settings, t("ai_down_alert", "ru", reason=esc(str(e) or "ошибка")))
        if ctx.handed_off:
            await message.answer(t("handoff_started", lang), reply_markup=back_to_ai_kb(lang))
            return True
        return False

    if assistant.record_success():
        await _alert_managers(bot, settings, t("ai_up_alert", "ru"))
    markup = back_to_ai_kb(lang) if reply.handed_off else None
    if reply.refused:
        await message.answer(t("ai_refusal", lang), reply_markup=markup)
    elif reply.text:
        await send_html(bot, message.chat.id, reply.text, reply_markup=markup)
    elif reply.handed_off:
        await message.answer(t("handoff_started", lang), reply_markup=markup)
    else:
        return False  # empty answer: let the rule-based assistant try
    return True


async def _alert_managers(bot: Bot, settings: Settings, text: str) -> None:
    try:
        await bot.send_message(settings.manager_chat_id, text)
    except Exception:  # noqa: BLE001 — an alert must never break a customer reply
        log.warning("could not alert managers: %s", text)


async def render_offline(message: Message, user_id: int, reply: OfflineReply, db: Database, settings: Settings,
                         lang: str, state: FSMContext | None) -> None:
    if reply.action == "handoff":
        await start_handoff(message.bot, db, settings.manager_chat_id, user_id, reply.text)
        await message.answer(f"{reply.text}\n\n{t('handoff_started', lang)}", reply_markup=back_to_ai_kb(lang))
        return
    if reply.action == "builder" and state is not None:
        await message.answer(reply.text)
        await builder.start(message, state, lang)
        return
    if reply.action == "cart":
        await cart.show_cart(message, db, settings, lang, user_id=user_id)
        return
    if reply.action == "orders":
        await message.answer(reply.text)
        await orders.show_orders(message, db, settings, lang, user_id=user_id)
        return
    if reply.action == "show_product" and reply.products:
        from ..formatting import product_card

        p = reply.products[0]
        await send_product(message, p, db, settings.media_dir, product_card(p, settings.currency, lang, 1024),
                           product_kb(p.sku, lang))
        return

    if reply.build:
        if len(LAST_BUILDS) > _MAX_BUILDS:
            LAST_BUILDS.clear()
        LAST_BUILDS[user_id] = [p.sku for p in reply.build.parts]
    markup = offline_reply_kb(reply.products, settings.currency, lang, with_build=bool(reply.build),
                              quick=reply.quick)
    await send_html(message.bot, message.chat.id, reply.text, reply_markup=markup)


@router.message(StateFilter(None), F.text)
async def on_text(message: Message, state: FSMContext, db: Database, settings: Settings, assistant: Assistant,
                  offline: OfflineAssistant, lang: str, customer):
    if customer["handoff"]:
        await forward_to_managers(message.bot, db, settings.manager_chat_id, message)
        return
    await ask_assistant(message, message.from_user.id, message.text, db, settings, assistant, lang, customer,
                        offline, state)


@router.message(StateFilter(None))
async def on_other(message: Message, db: Database, settings: Settings, lang: str, customer):
    if customer["handoff"]:
        await forward_to_managers(message.bot, db, settings.manager_chat_id, message)
        return
    await message.answer(t("unsupported_message", lang))


@router.callback_query(BuildCb.filter())
async def on_build(call: CallbackQuery, db: Database, lang: str):
    skus = LAST_BUILDS.get(call.from_user.id)
    if not skus:
        await call.answer(t("build_expired", lang), show_alert=True)
        return
    added = 0
    for sku in skus:
        p = await db.get_product(sku)
        if p and p.active:
            await db.cart_add(call.from_user.id, sku, 1)
            added += 1
    LAST_BUILDS.pop(call.from_user.id, None)
    await call.answer(t("build_added", lang, count=added), show_alert=True)


@router.callback_query(QuickCb.filter())
async def on_quick(call: CallbackQuery, callback_data: QuickCb, state: FSMContext, db: Database, settings: Settings,
                   lang: str):
    await call.answer()
    await state.clear()
    user_id = call.from_user.id
    action = callback_data.action
    if action == "catalog":
        await catalog.show_categories(call.message, db, lang)
    elif action == "builder":
        await builder.start(call.message, state, lang)
    elif action == "manager":
        await handoff.request_manager(call.message, db, settings, lang, user_id=user_id)
    elif action == "service":
        await service.start(call.message, state, lang)
    elif action == "cart":
        await cart.show_cart(call.message, db, settings, lang, user_id=user_id)
