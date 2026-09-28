from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User

from .config import Settings
from .db import Database


class CustomerMiddleware(BaseMiddleware):
    """Registers the customer on every update and injects `lang` and `customer` into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        if user is None or user.is_bot:
            return await handler(event, data)
        db: Database = data["db"]
        settings: Settings = data["settings"]
        await db.upsert_user(user.id, user.username, user.full_name, settings.languages[0])
        customer = await db.get_user(user.id)
        lang = customer["lang"] if customer["lang"] in settings.languages else settings.languages[0]
        data["customer"] = customer
        data["lang"] = lang
        return await handler(event, data)
