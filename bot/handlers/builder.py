"""Guided PC build: purpose → budget → wishes, then the AI assistant assembles the build from the catalog."""

import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from ..ai.assistant import Assistant
from ..config import Settings
from ..db import Database
from ..formatting import money
from ..keyboards import cancel_kb, choices_kb
from ..texts import all_variants, t
from . import chat

router = Router(name="builder")

PURPOSES = ("purpose_gaming", "purpose_work", "purpose_creator", "purpose_office")


class Builder(StatesGroup):
    purpose = State()
    budget = State()
    prefs = State()


async def start(message: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(Builder.purpose)
    await message.answer(t("builder_purpose", lang), reply_markup=choices_kb([t(p, lang) for p in PURPOSES], lang))


@router.message(Builder.purpose, F.text)
async def step_purpose(message: Message, state: FSMContext, db: Database, settings: Settings, lang: str):
    await state.update_data(purpose=message.text.strip()[:200])
    await state.set_state(Builder.budget)
    presets = await budget_presets(db)
    labels = [money(v, settings.currency) for v in presets]
    await message.answer(t("builder_budget", lang), reply_markup=choices_kb(labels, lang, per_row=2))


@router.message(Builder.budget, F.text)
async def step_budget(message: Message, state: FSMContext, lang: str):
    digits = re.sub(r"[^\d]", "", message.text)
    if not digits:
        await message.answer(t("builder_bad_budget", lang))
        return
    await state.update_data(budget=int(digits))
    await state.set_state(Builder.prefs)
    await message.answer(t("builder_prefs", lang), reply_markup=cancel_kb(lang, skip=True))


@router.message(Builder.prefs, F.text)
async def step_prefs(
    message: Message, state: FSMContext, db: Database, settings: Settings, assistant: Assistant, lang: str, customer
):
    data = await state.get_data()
    await state.clear()
    prefs = t("no_prefs", lang) if message.text in all_variants("btn_skip") else message.text.strip()[:500]
    prompt = t("builder_prompt", lang, purpose=data["purpose"], budget=money(data["budget"], settings.currency), prefs=prefs)
    await chat.ask_assistant(message, message.from_user.id, prompt, db, settings, assistant, lang, customer)


@router.message(StateFilter(Builder))
async def unexpected(message: Message, lang: str):
    await message.answer(t("answer_above", lang))


async def budget_presets(db: Database) -> list[int]:
    """Budget buttons scaled to the catalog's price level (currency-agnostic)."""
    pcs = await db.search_products(category="Готовые ПК", limit=100)
    prices = sorted(p.price for p in pcs)
    if len(prices) < 4:
        return []  # customer types the budget
    picks = [prices[int(len(prices) * q)] for q in (0.1, 0.35, 0.65, 0.95)]
    return sorted({_round_nice(p) for p in picks})


def _round_nice(value: float) -> int:
    magnitude = 10 ** max(len(str(int(value))) - 2, 0)
    return int(round(value / magnitude) * magnitude)
