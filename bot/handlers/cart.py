from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..db import Database
from ..formatting import cart_text, esc, normalize_phone, order_summary
from ..keyboards import CartCb, cancel_kb, cart_kb, choices_kb, main_menu, order_status_kb, phone_kb
from ..services import customer_header, to_managers
from ..texts import all_variants, t

router = Router(name="cart")


class Checkout(StatesGroup):
    name = State()
    phone = State()
    delivery = State()
    address = State()
    comment = State()
    confirm = State()


async def show_cart(message: Message, db: Database, settings: Settings, lang: str, user_id: int | None = None) -> None:
    lines = await db.cart(user_id or message.from_user.id)
    if not lines:
        await message.answer(t("cart_empty", lang), reply_markup=main_menu(lang))
        return
    await message.answer(
        cart_text(lines, settings.currency, lang),
        reply_markup=cart_kb([(li.sku, li.name) for li in lines], lang),
    )


@router.callback_query(CartCb.filter())
async def on_cart(call: CallbackQuery, callback_data: CartCb, state: FSMContext, db: Database,
                  settings: Settings, lang: str):
    user_id = call.from_user.id
    if callback_data.action == "del":
        await db.cart_remove(user_id, callback_data.sku)
    elif callback_data.action == "clear":
        await db.cart_clear(user_id)
        await call.message.edit_text(t("cart_cleared", lang))
        await call.answer()
        return
    elif callback_data.action == "checkout":
        if not await db.cart(user_id):
            await call.answer(t("cart_empty", lang), show_alert=True)
            return
        await call.answer()
        await state.set_state(Checkout.name)
        await call.message.answer(t("checkout_name", lang), reply_markup=cancel_kb(lang))
        return

    lines = await db.cart(user_id)
    if lines:
        await call.message.edit_text(
            cart_text(lines, settings.currency, lang),
            reply_markup=cart_kb([(li.sku, li.name) for li in lines], lang),
        )
    else:
        await call.message.edit_text(t("cart_empty", lang))
    await call.answer()


@router.message(Checkout.name, F.text)
async def checkout_name(message: Message, state: FSMContext, lang: str):
    await state.update_data(name=message.text.strip()[:100])
    await state.set_state(Checkout.phone)
    await message.answer(t("checkout_phone", lang), reply_markup=phone_kb(lang))


@router.message(Checkout.phone, F.contact | F.text)
async def checkout_phone(message: Message, state: FSMContext, db: Database, lang: str):
    raw = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw)
    if message.contact and message.contact.user_id != message.from_user.id:
        phone = None
    if not phone:
        await message.answer(t("checkout_bad_phone", lang), reply_markup=phone_kb(lang))
        return
    await db.set_phone(message.from_user.id, phone)
    await state.update_data(phone=phone)
    await state.set_state(Checkout.delivery)
    await message.answer(
        t("checkout_delivery", lang), reply_markup=choices_kb([t("btn_pickup", lang), t("btn_delivery", lang)], lang)
    )


@router.message(Checkout.delivery, F.text.in_(all_variants("btn_pickup")))
async def checkout_pickup(message: Message, state: FSMContext, lang: str):
    await state.update_data(delivery=t("pickup", lang))
    await state.set_state(Checkout.comment)
    await message.answer(t("checkout_comment", lang), reply_markup=cancel_kb(lang, skip=True))


@router.message(Checkout.delivery, F.text)
async def checkout_delivery(message: Message, state: FSMContext, lang: str):
    if message.text in all_variants("btn_delivery"):
        await state.set_state(Checkout.address)
        await message.answer(t("checkout_address", lang), reply_markup=cancel_kb(lang))
        return
    # Typed an address directly.
    await checkout_address(message, state, lang)


@router.message(Checkout.address, F.text)
async def checkout_address(message: Message, state: FSMContext, lang: str):
    await state.update_data(delivery=f"Доставка: {message.text.strip()[:300]}")
    await state.set_state(Checkout.comment)
    await message.answer(t("checkout_comment", lang), reply_markup=cancel_kb(lang, skip=True))


@router.message(Checkout.comment, F.text)
async def checkout_comment(message: Message, state: FSMContext, db: Database, settings: Settings, lang: str):
    comment = "" if message.text in all_variants("btn_skip") else message.text.strip()[:500]
    await state.update_data(comment=comment)
    data = await state.get_data()
    lines = await db.cart(message.from_user.id)
    if not lines:
        await state.clear()
        await message.answer(t("cart_empty", lang), reply_markup=main_menu(lang))
        return
    summary = cart_text(lines, settings.currency, lang) + (
        f"\n\nИмя: {esc(data['name'])}\nТелефон: {esc(data['phone'])}\nПолучение: {esc(data['delivery'])}"
        + (f"\nКомментарий: {esc(comment)}" if comment else "")
    )
    await state.set_state(Checkout.confirm)
    await message.answer(t("checkout_confirm", lang, summary=summary),
                         reply_markup=choices_kb([t("btn_confirm", lang)], lang))


@router.message(Checkout.confirm, F.text.in_(all_variants("btn_confirm")))
async def checkout_confirm(message: Message, state: FSMContext, bot: Bot, db: Database, settings: Settings, lang: str):
    data = await state.get_data()
    await state.clear()
    order = await db.create_order_from_cart(
        message.from_user.id, data["name"], data["phone"], data.get("delivery", ""), data.get("comment", "")
    )
    if not order:
        await message.answer(t("cart_empty", lang), reply_markup=main_menu(lang))
        return
    await message.answer(t("checkout_done", lang, id=order.id), reply_markup=main_menu(lang))
    await to_managers(
        bot, db, settings.manager_chat_id, order.user_id,
        f"🛒 <b>Новый заказ</b>\n{await customer_header(db, order.user_id)}\n\n{order_summary(order, settings.currency)}",
        reply_markup=order_status_kb(order.id),
    )


@router.message(StateFilter(Checkout))
async def checkout_unexpected(message: Message, lang: str):
    await message.answer(t("answer_above", lang))
