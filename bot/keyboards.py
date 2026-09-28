from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .texts import LANGUAGE_NAMES, t


class CategoryCb(CallbackData, prefix="cat"):
    idx: int
    page: int = 0


class ProductCb(CallbackData, prefix="prod"):
    sku: str
    action: str  # view | add | ask


class CartCb(CallbackData, prefix="cart"):
    action: str  # checkout | clear | del
    sku: str = ""


class LangCb(CallbackData, prefix="lang"):
    code: str


class OrderStatusCb(CallbackData, prefix="ost"):
    order_id: int
    status: str


class TicketStatusCb(CallbackData, prefix="tst"):
    ticket_id: int
    status: str


class HandoffCb(CallbackData, prefix="hand"):
    action: str  # back_to_ai


def main_menu(lang: str) -> ReplyKeyboardMarkup:
    b = lambda key: KeyboardButton(text=t(key, lang))  # noqa: E731
    return ReplyKeyboardMarkup(
        keyboard=[
            [b("btn_catalog"), b("btn_builder")],
            [b("btn_cart"), b("btn_orders")],
            [b("btn_service"), b("btn_info")],
            [b("btn_manager")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Задайте вопрос…",
    )


def cancel_kb(lang: str, skip: bool = False) -> ReplyKeyboardMarkup:
    row = [KeyboardButton(text=t("btn_skip", lang))] if skip else []
    return ReplyKeyboardMarkup(
        keyboard=[row, [KeyboardButton(text=t("btn_cancel", lang))]] if row else [[KeyboardButton(text=t("btn_cancel", lang))]],
        resize_keyboard=True,
    )


def phone_kb(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_send_phone", lang), request_contact=True)],
            [KeyboardButton(text=t("btn_cancel", lang))],
        ],
        resize_keyboard=True,
    )


def choices_kb(labels: list[str], lang: str, per_row: int = 2) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=label) for label in labels[i:i + per_row]] for i in range(0, len(labels), per_row)]
    rows.append([KeyboardButton(text=t("btn_cancel", lang))])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def languages_kb(codes: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code in codes:
        kb.button(text=LANGUAGE_NAMES.get(code, code), callback_data=LangCb(code=code))
    kb.adjust(2)
    return kb.as_markup()


def product_kb(sku: str, lang: str, back: CategoryCb | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn_add_to_cart", lang), callback_data=ProductCb(sku=sku, action="add"))
    kb.button(text=t("btn_ask_ai", lang), callback_data=ProductCb(sku=sku, action="ask"))
    if back:
        kb.button(text=t("btn_back", lang), callback_data=back)
    kb.adjust(2, 1)
    return kb.as_markup()


def cart_kb(skus_names: list[tuple[str, str]], lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for sku, name in skus_names:
        kb.button(text=f"✖️ {name[:40]}", callback_data=CartCb(action="del", sku=sku))
    kb.button(text=t("btn_checkout", lang), callback_data=CartCb(action="checkout"))
    kb.button(text=t("btn_clear_cart", lang), callback_data=CartCb(action="clear"))
    kb.adjust(*([1] * len(skus_names)), 2)
    return kb.as_markup()


def order_status_kb(order_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for status, label in (
        ("confirmed", "👍 Подтвердить"),
        ("paid", "💳 Оплачен"),
        ("shipped", "🚚 Отправлен"),
        ("done", "✔️ Выполнен"),
        ("cancelled", "❌ Отменить"),
    ):
        kb.button(text=label, callback_data=OrderStatusCb(order_id=order_id, status=status))
    kb.adjust(3, 2)
    return kb.as_markup()


def ticket_status_kb(ticket_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for status, label in (("in_progress", "🔧 В работу"), ("done", "✔️ Готово"), ("rejected", "❌ Отклонить")):
        kb.button(text=label, callback_data=TicketStatusCb(ticket_id=ticket_id, status=status))
    kb.adjust(3)
    return kb.as_markup()


def back_to_ai_kb(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=t("btn_back_to_ai", lang), callback_data=HandoffCb(action="back_to_ai"))
    return kb.as_markup()
