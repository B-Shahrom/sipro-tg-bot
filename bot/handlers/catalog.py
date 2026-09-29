import math

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..ai.assistant import Assistant
from ..config import Settings
from ..db import Database
from ..formatting import esc, money, product_card
from ..keyboards import CategoryCb, ProductCb, product_kb
from ..offline.engine import OfflineAssistant
from ..services import photo_source, send_product
from ..texts import t
from . import chat

router = Router(name="catalog")
PAGE_SIZE = 8


async def show_categories(message: Message, db: Database, lang: str, edit: bool = False) -> None:
    cats = await db.categories()
    if not cats:
        await message.answer(t("catalog_empty", lang))
        return
    kb = InlineKeyboardBuilder()
    for idx, (name, count) in enumerate(cats):
        kb.button(text=f"{name} ({count})", callback_data=CategoryCb(idx=idx))
    kb.adjust(2)
    if edit:
        await message.edit_text(t("catalog_title", lang), reply_markup=kb.as_markup())
    else:
        await message.answer(t("catalog_title", lang), reply_markup=kb.as_markup())


@router.callback_query(CategoryCb.filter())
async def on_category(call: CallbackQuery, callback_data: CategoryCb, db: Database, settings: Settings, lang: str):
    if callback_data.idx < 0:
        await show_categories(call.message, db, lang, edit=not call.message.photo)
        await call.answer()
        return
    cats = await db.categories()
    if callback_data.idx >= len(cats):
        await show_categories(call.message, db, lang, edit=True)
        await call.answer()
        return
    category = cats[callback_data.idx][0]
    page = max(callback_data.page, 0)
    products, total = await db.products_in_category(category, page * PAGE_SIZE, PAGE_SIZE)
    pages = max(1, math.ceil(total / PAGE_SIZE))

    kb = InlineKeyboardBuilder()
    for p in products:
        mark = "" if p.stock > 0 else "⏳ "
        kb.button(text=f"{mark}{p.name[:45]} — {money(p.price, settings.currency)}",
                  callback_data=ProductCb(sku=p.sku, action=f"view{callback_data.idx}.{page}"))
    nav = []
    if page > 0:
        nav.append(("◀️", CategoryCb(idx=callback_data.idx, page=page - 1)))
    nav.append((t("btn_back", lang), CategoryCb(idx=-1)))
    if page + 1 < pages:
        nav.append(("▶️", CategoryCb(idx=callback_data.idx, page=page + 1)))
    for text, cb in nav:
        kb.button(text=text, callback_data=cb)
    kb.adjust(*([1] * len(products)), len(nav))

    text = t("category_title", lang, category=esc(category), total=total, page=page + 1, pages=pages)
    if call.message.photo:
        # Coming back from a photo card: replace it with the list.
        await call.message.answer(text, reply_markup=kb.as_markup())
        await _delete_quietly(call.message)
    else:
        try:
            await call.message.edit_text(text, reply_markup=kb.as_markup())
        except TelegramBadRequest:
            await call.message.answer(text, reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(ProductCb.filter())
async def on_product(
    call: CallbackQuery, callback_data: ProductCb, state: FSMContext, db: Database, settings: Settings,
    assistant: Assistant, offline: OfflineAssistant, lang: str, customer,
):
    p = await db.get_product(callback_data.sku)
    if not p or not p.active:
        await call.answer(t("product_not_found", lang), show_alert=True)
        return

    if callback_data.action == "add":
        await db.cart_add(call.from_user.id, p.sku, 1)
        await call.answer(t("added_to_cart", lang, name=p.name[:150]), show_alert=False)
        return

    if callback_data.action == "ask":
        await call.answer()
        await chat.ask_assistant(
            call.message, call.from_user.id, t("ask_about_product", lang, name=p.name, sku=p.sku),
            db, settings, assistant, lang, customer, offline, state,
            offline_reply=lambda: offline.describe(p.sku),
        )
        return

    # view<idx>.<page>: product card with a way back to the same list page
    back = None
    if callback_data.action.startswith("view") and "." in callback_data.action:
        idx, page = callback_data.action[4:].split(".", 1)
        back = CategoryCb(idx=int(idx), page=int(page))
    kb = product_kb(p.sku, lang, back)
    # Opened from a catalog list (`back` set): the card replaces the list. Opened from an assistant reply
    # (search results, a build): keep that reply and send the card as a new message.
    if photo_source(p, settings.media_dir) is not None:
        await send_product(call.message, p, db, settings.media_dir, product_card(p, settings.currency, lang, 1024), kb)
        if back:
            await _delete_quietly(call.message)
    else:
        card = product_card(p, settings.currency, lang)
        edited = False
        if back:
            try:
                await call.message.edit_text(card, reply_markup=kb)
                edited = True
            except TelegramBadRequest:
                pass
        if not edited:
            await call.message.answer(card, reply_markup=kb)
    await call.answer()


async def _delete_quietly(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
