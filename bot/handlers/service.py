"""Warranty / repair request form."""

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ..config import Settings
from ..db import Database
from ..formatting import normalize_phone, ticket_summary
from ..keyboards import cancel_kb, main_menu, phone_kb, ticket_status_kb
from ..services import customer_header, to_managers
from ..texts import all_variants, t

router = Router(name="service")


class ServiceForm(StatesGroup):
    order_ref = State()
    product = State()
    problem = State()
    phone = State()


async def start(message: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(ServiceForm.order_ref)
    await message.answer(t("service_intro", lang), reply_markup=cancel_kb(lang, skip=True))


@router.message(ServiceForm.order_ref, F.text)
async def step_order(message: Message, state: FSMContext, lang: str):
    ref = "" if message.text in all_variants("btn_skip") else message.text.strip()[:50]
    await state.update_data(order_ref=ref)
    await state.set_state(ServiceForm.product)
    await message.answer(t("service_product", lang), reply_markup=cancel_kb(lang))


@router.message(ServiceForm.product, F.text)
async def step_product(message: Message, state: FSMContext, lang: str):
    await state.update_data(product=message.text.strip()[:200])
    await state.set_state(ServiceForm.problem)
    await message.answer(t("service_problem", lang), reply_markup=cancel_kb(lang))


@router.message(ServiceForm.problem, F.text)
async def step_problem(message: Message, state: FSMContext, lang: str, customer):
    await state.update_data(problem=message.text.strip()[:2000])
    await state.set_state(ServiceForm.phone)
    await message.answer(t("service_phone", lang), reply_markup=phone_kb(lang))


@router.message(ServiceForm.phone, F.contact | F.text)
async def step_phone(message: Message, state: FSMContext, bot: Bot, db: Database, settings: Settings, lang: str):
    raw = message.contact.phone_number if message.contact else message.text
    phone = normalize_phone(raw)
    if not phone:
        await message.answer(t("checkout_bad_phone", lang), reply_markup=phone_kb(lang))
        return
    await db.set_phone(message.from_user.id, phone)
    data = await state.get_data()
    await state.clear()
    ticket = await db.create_ticket(message.from_user.id, data["order_ref"], data["product"], data["problem"], phone)
    await message.answer(t("service_done", lang, id=ticket.id), reply_markup=main_menu(lang))
    await to_managers(
        bot, db, settings.manager_chat_id, ticket.user_id,
        f"🛠 <b>Обращение в сервис</b>\n{await customer_header(db, ticket.user_id)}\n\n{ticket_summary(ticket)}",
        reply_markup=ticket_status_kb(ticket.id),
    )


@router.message(StateFilter(ServiceForm))
async def unexpected(message: Message, lang: str):
    await message.answer(t("answer_above", lang))
