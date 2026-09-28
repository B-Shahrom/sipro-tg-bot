"""Claude-powered customer assistant: one customer message in, one reply out, with catalog tools in between."""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import anthropic

from ..config import Settings
from ..db import Database
from ..texts import LANGUAGE_PROMPT_NAMES
from .prompts import SYSTEM_PROMPT
from .tools import TOOLS, ToolContext, execute_tool

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AssistantUnavailable(Exception):
    """The Claude API could not produce a reply (network, auth, rate limit, overload)."""


@dataclass
class Reply:
    text: str
    handed_off: bool = False
    refused: bool = False


def _for_replay(content: list) -> list:
    """Blocks of an assistant response to send back within the same turn.

    After a server-side fallback, blocks before the last `fallback` marker came from the declined attempt; only
    their text is valid context. The marker itself is dropped.
    """
    last = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    return [b for i, b in enumerate(content) if b.type != "fallback" and (i > last or b.type == "text")]


def _for_storage(content: list) -> list[dict]:
    """Minimal, model-independent copy of an assistant message for the persisted dialog history.

    Thinking blocks are dropped: they are only needed inside the turn that produced them, and never replaying
    them keeps stored history valid across model changes.
    """
    out = []
    for b in content:
        if b.type == "text" and b.text:
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


class Assistant:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        # api_key=None lets the SDK resolve credentials from the environment.
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=120.0, max_retries=3)
        self._locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._system_cache: dict[str, str] = {}

    def store_info(self) -> str:
        path: Path = self.settings.store_info_path
        return path.read_text(encoding="utf-8") if path.exists() else "(no store information provided)"

    def system_prompt(self, lang: str) -> str:
        # Built once per language and never changed at runtime, so the prompt-cache prefix stays stable.
        if lang not in self._system_cache:
            self._system_cache[lang] = SYSTEM_PROMPT.format(
                store_name=self.settings.store_name,
                currency=self.settings.currency,
                language=LANGUAGE_PROMPT_NAMES.get(lang, "Russian"),
                store_info=self.store_info(),
            )
        return self._system_cache[lang]

    def reload_store_info(self) -> None:
        self._system_cache.clear()

    async def _create(self, system: str, messages: list):
        kwargs = dict(
            model=self.settings.claude_model,
            max_tokens=16000,
            system=system,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": self.settings.claude_effort},
            cache_control={"type": "ephemeral"},
        )
        if self.settings.claude_fallbacks:
            return await self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return await self.client.messages.create(**kwargs)

    async def reply(self, ctx: ToolContext, lang: str, text: str) -> Reply:
        async with self._locks[ctx.user_id]:
            return await self._reply(ctx, lang, text)

    async def _reply(self, ctx: ToolContext, lang: str, text: str) -> Reply:
        history = await self.db.get_history(ctx.user_id, self.settings.history_limit)
        turn: list[dict] = [{"role": "user", "content": text}]  # what gets persisted
        live: list[dict] = [{"role": "user", "content": text}]  # what gets sent (keeps thinking blocks)
        system = self.system_prompt(lang)

        response = None
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = await self._create(system, history + live)
            except anthropic.AuthenticationError as e:
                log.error("Anthropic auth failed: %s", e.message)
                raise AssistantUnavailable from e
            except anthropic.RateLimitError as e:
                log.warning("Anthropic rate limited: %s", e.message)
                raise AssistantUnavailable from e
            except anthropic.BadRequestError as e:
                log.error("Anthropic bad request: %s", e.message)
                raise AssistantUnavailable from e
            except anthropic.APIStatusError as e:
                log.error("Anthropic API error %s: %s", e.status_code, e.message)
                raise AssistantUnavailable from e
            except anthropic.APIConnectionError as e:
                log.error("Anthropic connection error: %s", e)
                raise AssistantUnavailable from e

            usage = response.usage
            log.info(
                "claude user=%s model=%s stop=%s in=%s cache_read=%s out=%s",
                ctx.user_id, response.model, response.stop_reason, usage.input_tokens,
                usage.cache_read_input_tokens, usage.output_tokens,
            )

            if response.stop_reason == "refusal":
                # Don't persist a refused turn, so it can't poison later requests.
                return Reply(text="", refused=True, handed_off=ctx.handed_off)

            if response.stop_reason != "tool_use":
                break

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            results = []
            for block in tool_uses:
                result, is_error = await execute_tool(block.name, block.input, ctx)
                log.info("tool user=%s %s(%s) error=%s", ctx.user_id, block.name, block.input, is_error)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result, "is_error": is_error}
                )
            live.append({"role": "assistant", "content": _for_replay(response.content)})
            live.append({"role": "user", "content": results})
            turn.append({"role": "assistant", "content": _for_storage(response.content)})
            turn.append({"role": "user", "content": results})
        else:
            log.warning("user=%s hit MAX_TOOL_ROUNDS", ctx.user_id)

        final = [b for b in response.content if b.type == "text" and b.text] if response else []
        reply_text = "\n\n".join(b.text for b in final).strip()
        if not reply_text or response.stop_reason == "tool_use":
            # Out of tool rounds or empty answer: don't persist a dangling tool exchange.
            return Reply(text="", handed_off=ctx.handed_off)

        turn.append({"role": "assistant", "content": [{"type": "text", "text": reply_text}]})
        for message in turn:
            await self.db.add_history(ctx.user_id, message["role"], message["content"])
        return Reply(text=reply_text, handed_off=ctx.handed_off)
