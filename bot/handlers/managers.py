"""Managers' group: reply to customers, close live chats, change order and service-request statuses."""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..db import ORDER_STATUSES, Database
from ..formatting import esc, money, order_status_label, order_summary, ticket_status_label
from ..keyboards import OrderStatusCb, TicketStatusCb, main_menu, order_status_kb
from ..texts import t

log = logging.getLogger(__name__)


class ManagerChat(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, settings: Settings) -> bool:
        chat = event.chat if isinstance(event, Message) else event.message.chat
        return chat.id == settings.manager_chat_id


router = Router(name="managers")
router.message.filter(ManagerChat())
router.callback_query.filter(ManagerChat())

HELP = (
    "<b>Команды менеджера</b>\n"
    "• Ответьте (reply) на сообщение бота о клиенте — ответ уйдёт клиенту.\n"
    "• <code>/close</code> в ответе на сообщение клиента — завершить живой чат, клиент вернётся к ассистенту.\n"
    "• <code>/orders</code> — активные заказы.\n"
    "• <code>/order 12</code> — заказ №12 с кнопками статуса.\n"
    "• <code>/status 12 shipped</code> — сменить статус (" + ", ".join(ORDER_STATUSES) + ").\n"
    "Админам: <code>/import</code> (с CSV-файлом), <code>/export</code>, <code>/stats</code>, <code>/reload</code>."
)


@router.message(Command("help", "start"))
async def cmd_help(message: Message):
    await message.answer(HELP)


@router.message(Command("orders"))
async def cmd_orders(message: Message, db: Database, settings: Settings):
    orders = await db.orders_by_status(("new", "confirmed", "paid", "shipped"))
    if not orders:
        await message.answer("Активных заказов нет.")
        return
    rows = ["<b>Активные заказы:</b>"]
    for o in orders:
        rows.append(f"№{o.id} · {o.created_at[:16]} · {esc(o.customer_name)} · {money(o.total, settings.currency)} · "
                    f"{order_status_label(o.status, 'ru')}")
    rows.append("\nПодробнее: /order N")
    await message.answer("\n".join(rows))


@router.message(Command("order"))
async def cmd_order(message: Message, command: CommandObject, db: Database, settings: Settings):
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: /order 12")
        return
    order = await db.get_order(int(command.args.strip()))
    if not order:
        await message.answer("Заказ не найден.")
        return
    sent = await message.answer(order_summary(order, settings.currency), reply_markup=order_status_kb(order.id))
    await db.remember_relay(sent.message_id, order.user_id)


@router.message(Command("status"))
async def cmd_status(message: Message, command: CommandObject, bot: Bot, db: Database, settings: Settings):
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[0].isdigit() or parts[1] not in ORDER_STATUSES:
        await message.answer(f"Использование: /status 12 shipped\nСтатусы: {', '.join(ORDER_STATUSES)}")
        return
    order = await _update_order(bot, db, int(parts[0]), parts[1])
    await message.answer(f"Заказ №{parts[0]}: {order_status_label(parts[1], 'ru')}" if order else "Заказ не найден.")


@router.callback_query(OrderStatusCb.filter())
async def on_order_status(call: CallbackQuery, callback_data: OrderStatusCb, bot: Bot, db: Database, settings: Settings):
    order = await _update_order(bot, db, callback_data.order_id, callback_data.status)
    if not order:
        await call.answer("Заказ не найден", show_alert=True)
        return
    who = esc(call.from_user.full_name)
    try:
        await call.message.edit_text(
            f"{call.message.html_text}\n\n➡️ {order_status_label(order.status, 'ru')} — {who}",
            reply_markup=None if order.status in ("done", "cancelled") else order_status_kb(order.id),
        )
    except TelegramBadRequest:
        pass
    await call.answer("Статус обновлён, клиент уведомлён")


@router.callback_query(TicketStatusCb.filter())
async def on_ticket_status(call: CallbackQuery, callback_data: TicketStatusCb, bot: Bot, db: Database):
    ticket = await db.set_ticket_status(callback_data.ticket_id, callback_data.status)
    if not ticket:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    user = await db.get_user(ticket.user_id)
    lang = user["lang"] if user else "ru"
    await _notify(bot, ticket.user_id, t("ticket_status_changed", lang, id=ticket.id,
                                         status=ticket_status_label(ticket.status, lang)))
    try:
        await call.message.edit_text(
            f"{call.message.html_text}\n\n➡️ {ticket_status_label(ticket.status, 'ru')} — {esc(call.from_user.full_name)}",
            reply_markup=None if ticket.status in ("done", "rejected") else call.message.reply_markup,
        )
    except TelegramBadRequest:
        pass
    await call.answer("Статус обновлён, клиент уведомлён")


@router.message(Command("close"), F.reply_to_message)
async def cmd_close(message: Message, bot: Bot, db: Database):
    user_id = await db.relay_target(message.reply_to_message.message_id)
    if not user_id:
        await message.reply("Не нашёл клиента для этого сообщения.")
        return
    await db.set_handoff(user_id, False)
    user = await db.get_user(user_id)
    lang = user["lang"] if user else "ru"
    await _notify(bot, user_id, t("handoff_ended", lang), reply_markup=main_menu(lang))
    await message.reply(f"Чат с клиентом <code>#u{user_id}</code> закрыт, клиент вернулся к ассистенту.")


@router.message(F.reply_to_message, ~F.text.startswith("/"))
async def relay_reply(message: Message, bot: Bot, db: Database):
    user_id = await db.relay_target(message.reply_to_message.message_id)
    if not user_id:
        return  # managers talking among themselves
    user = await db.get_user(user_id)
    lang = user["lang"] if user else "ru"
    prefix = t("manager_reply_prefix", lang)
    try:
        if message.text:
            sent_text = f"{prefix}\n{message.html_text}"
            await bot.send_message(user_id, sent_text)
        else:
            await bot.send_message(user_id, prefix)
            await message.copy_to(user_id)
    except (TelegramForbiddenError, TelegramBadRequest) as e:
        await message.reply(f"❌ Не доставлено: {esc(str(e))}")
        return
    await db.remember_relay(message.message_id, user_id)


async def _update_order(bot: Bot, db: Database, order_id: int, status: str):
    if not await db.get_order(order_id):
        return None
    order = await db.set_order_status(order_id, status)
    user = await db.get_user(order.user_id)
    lang = user["lang"] if user else "ru"
    await _notify(bot, order.user_id, t("order_status_changed", lang, id=order.id,
                                        status=order_status_label(order.status, lang)))
    return order


async def _notify(bot: Bot, user_id: int, text: str, **kwargs) -> None:
    try:
        await bot.send_message(user_id, text, **kwargs)
    except (TelegramForbiddenError, TelegramBadRequest):
        log.warning("could not notify user %s", user_id)
