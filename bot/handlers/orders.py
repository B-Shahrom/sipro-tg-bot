from aiogram.types import Message

from ..config import Settings
from ..db import Database
from ..formatting import money, order_status_label, ticket_status_label
from ..keyboards import main_menu
from ..texts import t


async def show_orders(message: Message, db: Database, settings: Settings, lang: str, user_id: int | None = None) -> None:
    user_id = user_id or message.from_user.id
    orders = await db.user_orders(user_id)
    tickets = await db.user_tickets(user_id)
    if not orders and not tickets:
        await message.answer(t("orders_empty", lang), reply_markup=main_menu(lang))
        return
    rows = []
    if orders:
        rows.append(t("orders_title", lang))
        for o in orders:
            rows.append(t("order_line", lang, id=o.id, date=o.created_at[:10],
                          total=money(o.total, settings.currency), status=order_status_label(o.status, lang)))
    if tickets:
        rows.append("\n<b>Обращения в сервис:</b>")
        for tk in tickets:
            rows.append(f"№{tk.id} от {tk.created_at[:10]} — {ticket_status_label(tk.status, lang)}")
    await message.answer("\n".join(rows), reply_markup=main_menu(lang))
