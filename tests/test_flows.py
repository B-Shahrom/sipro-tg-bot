"""End-to-end: real aiogram dispatcher and handlers, fake Telegram API session and fake Claude."""

import itertools
from datetime import datetime
from types import SimpleNamespace as NS

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import (
    AnswerCallbackQuery,
    CopyMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, MessageId, Update, User

from bot.__main__ import build_dispatcher
from bot.ai.assistant import Assistant
from bot.config import get_settings
from bot.keyboards import CartCb, CategoryCb, OrderStatusCb, ProductCb

CUSTOMER = 1000
MANAGERS = get_settings().manager_chat_id


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._ids = itertools.count(5000)

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=next(self._ids), date=datetime.now(),
                           chat=Chat(id=method.chat_id, type="private" if method.chat_id > 0 else "supergroup"),
                           text=method.text)
        if isinstance(method, CopyMessage):
            return MessageId(message_id=next(self._ids))
        if isinstance(method, (EditMessageText, EditMessageReplyMarkup, AnswerCallbackQuery)):
            return True
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""

    async def close(self):
        pass

    def sent(self, chat_id=None) -> list[SendMessage]:
        return [c for c in self.calls if isinstance(c, SendMessage) and (chat_id is None or c.chat_id == chat_id)]

    def texts(self) -> list[str]:
        out = []
        for c in self.calls:
            if isinstance(c, (SendMessage, EditMessageText)):
                out.append(c.text)
        return out


class ScriptedAssistant(Assistant):
    def __init__(self, settings, db):
        super().__init__(settings, db)
        self.script = []

    async def _create(self, system, messages):
        return self.script.pop(0)


def resp(stop, *blocks):
    return NS(stop_reason=stop, content=list(blocks), model="claude-opus-5",
              usage=NS(input_tokens=1, cache_read_input_tokens=0, output_tokens=1))


class Harness:
    def __init__(self, db):
        self.settings = get_settings()
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.db = db
        self.assistant = ScriptedAssistant(self.settings, db)
        self.dp = build_dispatcher()
        self._update_ids = itertools.count(1)
        self._msg_ids = itertools.count(1)
        self.user = User(id=CUSTOMER, is_bot=False, first_name="Анна", username="anna")
        self.manager = User(id=1, is_bot=False, first_name="Менеджер")

    async def feed(self, **kwargs):
        update = Update(update_id=next(self._update_ids), **kwargs)
        await self.dp.feed_update(self.bot, update, db=self.db, settings=self.settings, assistant=self.assistant)

    def message(self, text=None, user=None, chat_id=CUSTOMER, **extra) -> Message:
        chat = Chat(id=chat_id, type="private" if chat_id > 0 else "supergroup")
        return Message(message_id=next(self._msg_ids), date=datetime.now(), chat=chat,
                       from_user=user or self.user, text=text, **extra)

    async def say(self, text, **extra):
        await self.feed(message=self.message(text, **extra))

    async def click(self, data: str):
        msg = self.message("кнопки", user=None)
        msg = msg.model_copy(update={"from_user": User(id=self.bot.id, is_bot=True, first_name="bot")})
        await self.feed(callback_query=CallbackQuery(id="cb", from_user=self.user, chat_instance="x",
                                                     message=msg, data=data))


@pytest.fixture
async def h(db):
    # Each test needs fresh routers; aiogram routers can only be attached to one dispatcher.
    import importlib

    import bot.__main__ as main_mod
    from bot.handlers import admin, builder, cart, catalog, chat, common, handoff, managers, service
    for mod in (chat, catalog, cart, service, builder, handoff, common, managers, admin):
        importlib.reload(mod)
    importlib.reload(main_mod)
    globals()["build_dispatcher"] = main_mod.build_dispatcher
    harness = Harness(db)
    yield harness
    await harness.bot.session.close()


async def test_start_and_catalog(h):
    await h.say("/start")
    assert "ассистент магазина" in h.session.texts()[-1]

    await h.say("🛍 Каталог")
    last = h.session.sent(CUSTOMER)[-1]
    assert last.text == "Выберите категорию:"
    buttons = [b.text for row in last.reply_markup.inline_keyboard for b in row]
    assert any(b.startswith("Видеокарты") for b in buttons)

    await h.click(CategoryCb(idx=0).pack())
    assert "стр. 1/" in h.session.texts()[-1]


async def test_free_text_goes_to_ai(h):
    h.assistant.script = [resp("end_turn", NS(type="text", text="Рекомендую <code>MON-27-QHD-180</code>."))]
    await h.say("нужен монитор для игр")
    assert h.session.sent(CUSTOMER)[-1].text == "Рекомендую <code>MON-27-QHD-180</code>."


async def test_checkout_notifies_managers_and_status_updates_customer(h):
    await h.click(ProductCb(sku="GPU-4060-8", action="add").pack())
    await h.say("🛒 Корзина")
    assert "RTX 4060" in h.session.sent(CUSTOMER)[-1].text

    await h.click(CartCb(action="checkout").pack())
    await h.say("Анна")
    await h.say("+7 900 123-45-67")
    await h.say("🏬 Самовывоз")
    await h.say("Пропустить")
    assert "Проверьте заказ" in h.session.sent(CUSTOMER)[-1].text
    await h.say("✅ Подтвердить")

    assert "принят" in h.session.sent(CUSTOMER)[-1].text
    manager_post = h.session.sent(MANAGERS)[-1]
    assert "Новый заказ" in manager_post.text and "+79001234567" in manager_post.text
    order = (await h.db.user_orders(CUSTOMER))[0]
    assert order.total == 32990 and await h.db.cart(CUSTOMER) == []

    # Manager presses "shipped" in the group; the customer is notified.
    group_msg = h.message("заказ", user=h.manager, chat_id=MANAGERS)
    await h.feed(callback_query=CallbackQuery(
        id="cb2", from_user=h.manager, chat_instance="y", message=group_msg,
        data=OrderStatusCb(order_id=order.id, status="shipped").pack()))
    assert (await h.db.get_order(order.id)).status == "shipped"
    assert "Отправлен" in h.session.sent(CUSTOMER)[-1].text


async def test_menu_button_leaves_checkout_form(h):
    await h.click(ProductCb(sku="GPU-4060-8", action="add").pack())
    await h.click(CartCb(action="checkout").pack())
    await h.say("🛍 Каталог")
    assert h.session.sent(CUSTOMER)[-1].text == "Выберите категорию:"
    h.assistant.script = [resp("end_turn", NS(type="text", text="ок"))]
    await h.say("вопрос")  # not captured as the checkout name anymore
    assert h.session.sent(CUSTOMER)[-1].text == "ок"


async def test_live_chat_with_manager(h):
    await h.say("/start")
    await h.say("👨‍💼 Менеджер")
    intro = h.session.sent(MANAGERS)[-1]
    assert "просит менеджера" in intro.text

    # While handed off, customer messages go to managers, not to the AI (script is empty: would raise).
    await h.say("когда будет 4090?")
    relayed = h.session.sent(MANAGERS)[-1]
    assert "когда будет 4090?" in relayed.text

    # A manager replies to the relayed message; the customer receives it.
    relay_msg_id = (await h.db.conn.execute_fetchall("SELECT max(chat_message_id) FROM relay"))[0][0]
    replied_to = Message(message_id=relay_msg_id, date=datetime.now(), chat=Chat(id=MANAGERS, type="supergroup"),
                         text="x")
    await h.say("Будет в пятницу", user=h.manager, chat_id=MANAGERS, reply_to_message=replied_to)
    to_customer = h.session.sent(CUSTOMER)[-1]
    assert "Менеджер" in to_customer.text and "Будет в пятницу" in to_customer.text

    # /close returns the customer to the assistant.
    await h.say("/close", user=h.manager, chat_id=MANAGERS, reply_to_message=replied_to)
    assert not (await h.db.get_user(CUSTOMER))["handoff"]


async def test_ai_handoff_tool_switches_to_live_chat(h):
    h.assistant.script = [
        resp("tool_use", NS(type="tool_use", id="h1", name="handoff_to_manager",
                            input={"reason": "скидка", "summary": "Хочет скидку на сборку"})),
        resp("end_turn", NS(type="text", text="Передал ваш запрос менеджеру.")),
    ]
    await h.say("сделайте скидку")
    assert "Хочет скидку" in h.session.sent(MANAGERS)[-1].text
    assert (await h.db.get_user(CUSTOMER))["handoff"]
    assert h.session.sent(CUSTOMER)[-1].reply_markup is not None  # "back to assistant" button


async def test_warranty_request(h):
    await h.say("🛠 Гарантия и ремонт")
    await h.say("Пропустить")
    await h.say("RTX 4060")
    await h.say("Артефакты на экране")
    await h.say("+7 900 000 00 00")
    assert "Обращение" in h.session.sent(CUSTOMER)[-1].text
    assert "Артефакты" in h.session.sent(MANAGERS)[-1].text


async def test_pc_builder_sends_prompt_to_ai(h):
    h.assistant.script = [resp("end_turn", NS(type="text", text="Вот сборка"))]
    await h.say("🧩 Собрать ПК")
    await h.say("🎮 Игры")
    await h.say("100000")
    await h.say("Пропустить")
    assert h.session.sent(CUSTOMER)[-1].text == "Вот сборка"
    history = await h.db.get_history(CUSTOMER, 10)
    assert "Бюджет: до 100 000 ₽" in history[0]["content"]


async def test_admin_stats_only_for_admins(h):
    await h.say("/stats", user=User(id=1, is_bot=False, first_name="Admin"), chat_id=1)
    assert "Товаров в каталоге: 40" in h.session.sent(1)[-1].text
    h.assistant.script = [resp("end_turn", NS(type="text", text="не админ"))]
    await h.say("/stats")  # regular customer: falls through to the assistant
    assert h.session.sent(CUSTOMER)[-1].text == "не админ"
