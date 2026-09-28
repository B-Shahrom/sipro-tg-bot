"""Customer side of the live chat with managers."""

from aiogram import Bot, Router
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..db import Database
from ..keyboards import HandoffCb, back_to_ai_kb, main_menu
from ..services import start_handoff
from ..texts import t

router = Router(name="handoff")


async def request_manager(message: Message, db: Database, settings: Settings, lang: str) -> None:
    user_id = message.from_user.id
    await start_handoff(message.bot, db, settings.manager_chat_id, user_id, "Клиент нажал «Менеджер»")
    await message.answer(t("handoff_started", lang), reply_markup=back_to_ai_kb(lang))


@router.callback_query(HandoffCb.filter())
async def on_back_to_ai(call: CallbackQuery, bot: Bot, db: Database, settings: Settings, lang: str):
    await db.set_handoff(call.from_user.id, False)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(t("handoff_ended", lang), reply_markup=main_menu(lang))
    await bot.send_message(settings.manager_chat_id, f"ℹ️ Клиент <code>#u{call.from_user.id}</code> вернулся к ассистенту.")
    await call.answer()
