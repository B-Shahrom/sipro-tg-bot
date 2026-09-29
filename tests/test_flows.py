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
    DeleteMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    MessageId,
    MessageOriginHiddenUser,
    MessageOriginUser,
    PhotoSize,
    Update,
    User,
)

from bot.__main__ import build_dispatcher
from bot.ai.assistant import Assistant
from bot.config import get_settings
from bot.keyboards import BuildCb, CartCb, CategoryCb, OrderStatusCb, ProductCb, QuickCb
from bot.offline.engine import OfflineAssistant

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
        if isinstance(method, SendPhoto):
            return Message(message_id=next(self._ids), date=datetime.now(), chat=Chat(id=method.chat_id, type="private"),
                           photo=[PhotoSize(file_id=f"FILE-{next(self._ids)}", file_unique_id="u", width=800,
                                            height=800)], caption=method.caption)
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
        self.enabled = True  # tests script the AI instead of calling the API
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
        self.offline = OfflineAssistant(db, self.settings)
        self.dp = build_dispatcher()
        self._update_ids = itertools.count(1)
        self._msg_ids = itertools.count(1)
        self.user = User(id=CUSTOMER, is_bot=False, first_name="Анна", username="anna")
        self.manager = User(id=1, is_bot=False, first_name="Менеджер")

    async def feed(self, **kwargs):
        update = Update(update_id=next(self._update_ids), **kwargs)
        await self.dp.feed_update(self.bot, update, db=self.db, settings=self.settings, assistant=self.assistant,
                                  offline=self.offline)

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
    from bot.handlers import admin, builder, cart, catalog, chat, common, handoff, managers, service, utils
    for mod in (chat, catalog, cart, service, builder, handoff, common, managers, admin, utils):
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
    assert "Товаров в каталоге: 124" in h.session.sent(1)[-1].text
    h.assistant.script = [resp("end_turn", NS(type="text", text="не админ"))]
    await h.say("/stats")  # regular customer: falls through to the assistant
    assert h.session.sent(CUSTOMER)[-1].text == "не админ"


async def test_id_command(h):
    await h.say("/id")
    assert str(CUSTOMER) in h.session.sent(CUSTOMER)[-1].text
    await h.say("/id", user=h.manager, chat_id=MANAGERS)
    assert str(MANAGERS) in h.session.sent(MANAGERS)[-1].text


async def test_forward_shows_original_sender_id_to_admin(h):
    admin = User(id=1, is_bot=False, first_name="Admin")
    owner = User(id=777, is_bot=False, first_name="Store", last_name="Owner", username="owner")
    await h.say("привет", user=admin, chat_id=1,
                forward_origin=MessageOriginUser(date=datetime.now(), sender_user=owner))
    reply = h.session.sent(1)[-1].text
    assert "<code>777</code>" in reply and "@owner" in reply and "ADMIN_IDS" in reply

    await h.say("привет", user=admin, chat_id=1,
                forward_origin=MessageOriginHiddenUser(date=datetime.now(), sender_user_name="Секретный"))
    assert "id скрыт" in h.session.sent(1)[-1].text


async def test_customer_forward_goes_to_assistant(h):
    h.assistant.script = [resp("end_turn", NS(type="text", text="ответ ассистента"))]
    other = User(id=555, is_bot=False, first_name="X")
    await h.say("что это за видеокарта?", forward_origin=MessageOriginUser(date=datetime.now(), sender_user=other))
    assert h.session.sent(CUSTOMER)[-1].text == "ответ ассистента"


async def test_id_reply_in_group_shows_author_and_relayed_customer(h):
    colleague = User(id=888, is_bot=False, first_name="Коллега")
    target = h.message("hi", user=colleague, chat_id=MANAGERS)
    await h.say("/id", user=h.manager, chat_id=MANAGERS, reply_to_message=target)
    assert "<code>888</code>" in h.session.sent(MANAGERS)[-1].text

    await h.db.remember_relay(4242, CUSTOMER)
    bot_post = Message(message_id=4242, date=datetime.now(), chat=Chat(id=MANAGERS, type="supergroup"),
                       from_user=User(id=42, is_bot=True, first_name="bot"), text="заказ")
    await h.say("/id", user=h.manager, chat_id=MANAGERS, reply_to_message=bot_post)
    assert f"<code>{CUSTOMER}</code>" in h.session.sent(MANAGERS)[-1].text



# ---------------------------------------------------------------- AI off / failing → rule-based assistant

async def test_no_ai_key_uses_rule_based_search(h):
    h.assistant.enabled = False
    await h.say("монитор для игр до 25000")
    reply = h.session.sent(CUSTOMER)[-1]
    assert "мониторы до 25 000" in reply.text
    buttons = [b.callback_data for row in reply.reply_markup.inline_keyboard for b in row]
    assert any(cb.startswith("prod:MON-") for cb in buttons)


async def test_ai_failure_falls_back_and_alerts_managers_once(h):
    from bot.ai.assistant import AssistantUnavailable

    calls = {"n": 0}

    async def broken(system, messages):
        calls["n"] += 1
        raise AssistantUnavailable("no connection to the API")

    h.assistant._create = broken
    await h.say("где вы находитесь?")
    assert "Адрес" in h.session.sent(CUSTOMER)[-1].text
    alerts = [m for m in h.session.sent(MANAGERS) if "недоступен" in m.text]
    assert len(alerts) == 1

    # While the circuit breaker is open the AI is skipped entirely: fast answers, no repeated alerts.
    await h.say("есть доставка?")
    assert "Доставка" in h.session.sent(CUSTOMER)[-1].text
    assert calls["n"] == 1
    assert len([m for m in h.session.sent(MANAGERS) if "недоступен" in m.text]) == 1

    # Recovery: next successful AI reply tells the managers.
    h.assistant._down_until = 0
    h.assistant._create = ScriptedAssistant._create.__get__(h.assistant)
    h.assistant.script = [resp("end_turn", NS(type="text", text="Я снова тут"))]
    await h.say("привет")
    assert h.session.sent(CUSTOMER)[-1].text == "Я снова тут"
    assert "снова работает" in h.session.sent(MANAGERS)[-1].text


async def test_ai_timeout_falls_back(h):
    import asyncio

    h.settings = h.settings.model_copy(update={"ai_timeout": 0.05})
    h.assistant.settings = h.settings

    async def slow(system, messages):
        await asyncio.sleep(1)

    h.assistant._create = slow
    await h.say("можно в рассрочку?")
    assert "Оплата" in h.session.sent(CUSTOMER)[-1].text


async def test_offline_build_and_add_whole_build_to_cart(h):
    h.assistant.enabled = False
    await h.say("собрать пк для игр за 100000")
    reply = h.session.sent(CUSTOMER)[-1]
    assert "Сборка для игр" in reply.text
    await h.click(BuildCb(action="add").pack())
    cart = await h.db.cart(CUSTOMER)
    assert len(cart) >= 7 and sum(li.subtotal for li in cart) <= 100000


async def test_offline_builder_form(h):
    h.assistant.enabled = False
    await h.say("🧩 Собрать ПК")
    await h.say("🎮 Игры")
    await h.say("150000")
    await h.say("белый")
    reply = h.session.sent(CUSTOMER)[-1]
    assert "Сборка для игр" in reply.text and "White" in reply.text


async def test_offline_handoff_and_quick_buttons(h):
    h.assistant.enabled = False
    await h.say("позовите менеджера")
    assert (await h.db.get_user(CUSTOMER))["handoff"]
    assert "просит менеджера" in h.session.sent(MANAGERS)[-1].text
    await h.db.set_handoff(CUSTOMER, False)

    await h.click(QuickCb(action="catalog").pack())
    assert h.session.sent(CUSTOMER)[-1].text == "Выберите категорию:"


async def test_product_card_uses_local_image_and_caches_file_id(h):
    await h.click(ProductCb(sku="GPU-4060-8", action="view0.0").pack())
    photos = [c for c in h.session.calls if isinstance(c, SendPhoto)]
    assert photos and "RTX 4060" in photos[-1].caption and len(photos[-1].caption) <= 1024
    cached = (await h.db.get_product("GPU-4060-8")).image_file_id
    assert cached.startswith("FILE-")
    await h.click(ProductCb(sku="GPU-4060-8", action="view0.0").pack())
    assert [c for c in h.session.calls if isinstance(c, SendPhoto)][-1].photo == cached  # re-uses Telegram's copy


async def test_ask_about_product_offline(h):
    h.assistant.enabled = False
    await h.click(ProductCb(sku="CPU-R7-7800X3D", action="ask").pack())
    reply = h.session.sent(CUSTOMER)[-1]
    assert "Сокет AM5" in reply.text
    buttons = [b.callback_data for row in reply.reply_markup.inline_keyboard for b in row]
    assert any(cb.startswith("prod:MB-") for cb in buttons)


async def test_cart_warns_about_incompatible_parts(h):
    await h.db.cart_add(CUSTOMER, "CPU-R7-7800X3D", 1)
    await h.db.cart_add(CUSTOMER, "MB-Z790-P", 1)
    await h.say("🛒 Корзина")
    text = h.session.sent(CUSTOMER)[-1].text
    assert "Проверка совместимости" in text and "❌" in text and "AM5" in text


async def test_ai_quota_exhausted_uses_rule_based(h):
    h.settings = h.settings.model_copy(update={"ai_daily_limit": 1})
    h.assistant.script = [resp("end_turn", NS(type="text", text="ответ ИИ"))]
    await h.say("привет")
    assert h.session.sent(CUSTOMER)[-1].text == "ответ ИИ"
    await h.say("где вы находитесь?")  # quota used up → rule-based, not an error
    assert "Адрес" in h.session.sent(CUSTOMER)[-1].text


async def test_opening_product_from_assistant_reply_keeps_the_reply(h):
    h.assistant.enabled = False
    await h.say("собрать пк для игр за 100000")
    await h.click(ProductCb(sku="GPU-4060-8", action="view").pack())
    assert not [c for c in h.session.calls if isinstance(c, DeleteMessage)]
    await h.click(ProductCb(sku="GPU-4060-8", action="view0.0").pack())  # from a catalog list: list is replaced
    assert [c for c in h.session.calls if isinstance(c, DeleteMessage)]
