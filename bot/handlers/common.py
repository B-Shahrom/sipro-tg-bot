"""/start, language, reset, store info, cancel, and the main-menu buttons (which always leave any form)."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..ai.assistant import Assistant
from ..config import Settings
from ..db import Database
from ..formatting import esc
from ..keyboards import LangCb, languages_kb, main_menu
from ..texts import all_variants, t
from . import builder, cart, catalog, handoff, orders, service

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database, settings: Settings, lang: str, customer):
    await state.clear()
    if customer["handoff"]:
        await db.set_handoff(message.from_user.id, False)
    await message.answer(
        t("welcome", lang, name=esc(message.from_user.first_name or ""), store=esc(settings.store_name)),
        reply_markup=main_menu(lang),
    )
    if len(settings.languages) > 1:
        await message.answer(t("choose_language", lang), reply_markup=languages_kb(settings.languages))


@router.message(Command("language"))
async def cmd_language(message: Message, settings: Settings, lang: str):
    await message.answer(t("choose_language", lang), reply_markup=languages_kb(settings.languages))


@router.callback_query(LangCb.filter())
async def on_language(call: CallbackQuery, callback_data: LangCb, db: Database, settings: Settings):
    if callback_data.code not in settings.languages:
        await call.answer()
        return
    await db.set_lang(call.from_user.id, callback_data.code)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(t("language_set", callback_data.code), reply_markup=main_menu(callback_data.code))
    await call.answer()


@router.message(Command("reset"))
async def cmd_reset(message: Message, state: FSMContext, db: Database, lang: str):
    await state.clear()
    await db.clear_history(message.from_user.id)
    await message.answer(t("dialog_reset", lang), reply_markup=main_menu(lang))


@router.message(Command("help"))
async def cmd_help(message: Message, lang: str, settings: Settings):
    await message.answer(
        t("welcome", lang, name=esc(message.from_user.first_name or ""), store=esc(settings.store_name))
        + "\n\n/reset — начать диалог с ассистентом заново\n/language — сменить язык",
        reply_markup=main_menu(lang),
    )


@router.message(F.text.in_(all_variants("btn_cancel")))
async def on_cancel(message: Message, state: FSMContext, lang: str):
    was_checkout = (await state.get_state() or "").startswith("Checkout")
    await state.clear()
    await message.answer(t("checkout_cancelled" if was_checkout else "cancelled", lang), reply_markup=main_menu(lang))


# ---- main menu: every button clears any unfinished form first ----

@router.message(F.text.in_(all_variants("btn_catalog")))
async def menu_catalog(message: Message, state: FSMContext, db: Database, lang: str):
    await state.clear()
    await catalog.show_categories(message, db, lang)


@router.message(F.text.in_(all_variants("btn_builder")))
async def menu_builder(message: Message, state: FSMContext, lang: str):
    await state.clear()
    await builder.start(message, state, lang)


@router.message(F.text.in_(all_variants("btn_cart")))
async def menu_cart(message: Message, state: FSMContext, db: Database, settings: Settings, lang: str):
    await state.clear()
    await cart.show_cart(message, db, settings, lang)


@router.message(F.text.in_(all_variants("btn_orders")))
async def menu_orders(message: Message, state: FSMContext, db: Database, settings: Settings, lang: str):
    await state.clear()
    await orders.show_orders(message, db, settings, lang)


@router.message(F.text.in_(all_variants("btn_service")))
async def menu_service(message: Message, state: FSMContext, lang: str):
    await state.clear()
    await service.start(message, state, lang)


@router.message(F.text.in_(all_variants("btn_info")))
async def menu_info(message: Message, state: FSMContext, assistant: Assistant, lang: str):
    await state.clear()
    await message.answer(esc(assistant.store_info()), reply_markup=main_menu(lang))


@router.message(F.text.in_(all_variants("btn_manager")))
async def menu_manager(message: Message, state: FSMContext, db: Database, settings: Settings, lang: str):
    await state.clear()
    await handoff.request_manager(message, db, settings, lang)
