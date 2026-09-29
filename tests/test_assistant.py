import json
from types import SimpleNamespace as NS

import anthropic
import httpx2 as httpx
import pytest

from bot.ai.assistant import Assistant, AssistantUnavailable
from bot.ai.tools import TOOLS, ToolContext, execute_tool
from bot.config import get_settings


def usage():
    return NS(input_tokens=10, cache_read_input_tokens=0, output_tokens=5)


def resp(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, content=list(blocks), usage=usage(), model="claude-opus-5")


def text(s):
    return NS(type="text", text=s)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


class FakeAssistant(Assistant):
    def __init__(self, settings, db, responses):
        super().__init__(settings, db)
        self.enabled = True
        self.responses = list(responses)
        self.requests = []

    async def _create(self, system, messages):
        self.requests.append([dict(m) for m in messages])
        return self.responses.pop(0)


def make_ctx(db, user_id=100):
    handoffs = []

    async def on_handoff(reason, summary):
        handoffs.append((reason, summary))

    return ToolContext(db=db, user_id=user_id, currency="₽", on_handoff=on_handoff), handoffs


async def test_tool_loop_adds_to_cart_and_persists_turn(db):
    await db.upsert_user(100, None, "T", "ru")
    assistant = FakeAssistant(get_settings(), db, [
        resp("tool_use", NS(type="thinking", thinking="", signature="s"),
             tool_use("t1", "search_products", {"query": "RTX 4060"})),
        resp("tool_use", tool_use("t2", "add_to_cart", {"items": [{"sku": "GPU-4060-8", "qty": 1}]})),
        resp("end_turn", text("Добавил <b>RTX 4060</b> в корзину.")),
    ])
    ctx, _ = make_ctx(db)
    reply = await assistant.reply(ctx, "ru", "добавь 4060")

    assert reply.text == "Добавил <b>RTX 4060</b> в корзину."
    assert [(li.sku, li.qty) for li in await db.cart(100)] == [("GPU-4060-8", 1)]
    # Within the turn, the thinking block is replayed; in stored history it is dropped.
    second_request = assistant.requests[1]
    assert [b.type for b in second_request[1]["content"]] == ["thinking", "tool_use"]
    history = await db.get_history(100, 50)
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant", "user", "assistant"]
    assert history[1]["content"] == [{"type": "tool_use", "id": "t1", "name": "search_products",
                                      "input": {"query": "RTX 4060"}}]
    result = json.loads(history[2]["content"][0]["content"])
    assert result["results"][0]["sku"] == "GPU-4060-8"


async def test_next_turn_sends_history(db):
    await db.upsert_user(100, None, "T", "ru")
    assistant = FakeAssistant(get_settings(), db, [resp("end_turn", text("Привет!")), resp("end_turn", text("Да"))])
    ctx, _ = make_ctx(db)
    await assistant.reply(ctx, "ru", "привет")
    await assistant.reply(ctx, "ru", "ещё вопрос")
    sent = assistant.requests[1]
    assert sent[0] == {"role": "user", "content": "привет"}
    assert sent[-1] == {"role": "user", "content": "ещё вопрос"}


async def test_refusal_is_not_persisted(db):
    await db.upsert_user(100, None, "T", "ru")
    assistant = FakeAssistant(get_settings(), db, [resp("refusal")])
    ctx, _ = make_ctx(db)
    reply = await assistant.reply(ctx, "ru", "что-то плохое")
    assert reply.refused and reply.text == ""
    assert await db.get_history(100, 50) == []


async def test_handoff_tool(db):
    await db.upsert_user(100, None, "T", "ru")
    assistant = FakeAssistant(get_settings(), db, [
        resp("tool_use", tool_use("h", "handoff_to_manager", {"reason": "скидка", "summary": "хочет скидку"})),
        resp("end_turn", text("Передал менеджеру.")),
    ])
    ctx, handoffs = make_ctx(db)
    reply = await assistant.reply(ctx, "ru", "дайте скидку")
    assert reply.handed_off
    assert handoffs == [("скидка", "хочет скидку")]


async def test_fallback_marker_replay():
    from bot.ai.assistant import _for_replay

    content = [text("partial"), NS(type="thinking"), tool_use("x", "view_cart", {}), NS(type="fallback"),
               text("final"), tool_use("y", "view_cart", {})]
    kept = _for_replay(content)
    assert [(b.type, getattr(b, "text", getattr(b, "id", None))) for b in kept] == [
        ("text", "partial"), ("text", "final"), ("tool_use", "y")]


async def test_api_error_raises_unavailable(db):
    await db.upsert_user(100, None, "T", "ru")

    class Failing(Assistant):
        enabled = True

        async def _create(self, system, messages):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.APIConnectionError(request=request)

    ctx, _ = make_ctx(db)
    with pytest.raises(AssistantUnavailable):
        await Failing(get_settings(), db).reply(ctx, "ru", "привет")


async def test_tools_are_scoped_and_validated(db):
    ctx, _ = make_ctx(db, user_id=1)
    await db.cart_add(2, "SSD-1TB-NV3", 1)  # another customer's cart
    result, is_error = await execute_tool("view_cart", {}, ctx)
    assert not is_error and json.loads(result)["items"] == []

    result, is_error = await execute_tool("get_product", {"sku": "NOPE"}, ctx)
    assert is_error

    result, is_error = await execute_tool("add_to_cart", {"items": [{"sku": "NOPE", "qty": 1}]}, ctx)
    assert not is_error and json.loads(result)["problems"]

    result, is_error = await execute_tool("drop_tables", {}, ctx)
    assert is_error


def test_tool_definitions_are_sorted_and_unique():
    names = [tool["name"] for tool in TOOLS]
    assert names == sorted(names) and len(set(names)) == len(names)


def test_system_prompt_renders(db):
    assistant = Assistant(get_settings(), db)
    prompt = assistant.system_prompt("ru")
    assert "Russian" in prompt and "SIPRO" in prompt and "Гарантия" in prompt
    assert prompt is assistant.system_prompt("ru")  # stable for prompt caching
