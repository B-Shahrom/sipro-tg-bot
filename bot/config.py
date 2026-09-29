from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    anthropic_api_key: str | None = None

    # Group chat where managers receive orders, service requests and live-chat handoffs.
    manager_chat_id: int
    # Telegram user ids allowed to run admin commands (/import, /export, /stats).
    admin_ids: Annotated[list[int], NoDecode] = []

    # Languages offered to customers. The first one is the default.
    languages: Annotated[list[str], NoDecode] = ["ru"]

    store_name: str = "SIPRO"
    currency: str = "₽"
    db_path: Path = ROOT_DIR / "data" / "bot.db"
    store_info_path: Path = ROOT_DIR / "data" / "store_info.md"

    claude_model: str = "claude-opus-5"
    claude_effort: str = "medium"
    # Server-side refusal fallbacks (Claude API only; disable for Bedrock/Vertex/Foundry proxies).
    claude_fallbacks: bool = True
    # How many past messages of a customer's dialog are sent to the model.
    history_limit: int = 30
    # Max AI replies per customer per day (0 = unlimited). Protects the API budget from abuse.
    ai_daily_limit: int = 150

    @field_validator("admin_ids", "languages", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _numeric_admin_ids(cls, v):
        v = cls._split_csv(v)  # "before" validators run in reverse order, so split here too
        for item in v:
            if not str(item).lstrip("-").isdigit():
                raise ValueError(
                    f"{item!r} is not a numeric Telegram user id. Use numbers like 123456789, not @usernames. "
                    "Send /id to your bot (or message @userinfobot) to find yours."
                )
        return v

    @field_validator("manager_chat_id", mode="before")
    @classmethod
    def _numeric_chat_id(cls, v):
        if isinstance(v, str) and not v.strip().lstrip("-").isdigit():
            raise ValueError(
                f"{v!r} is not a numeric chat id. Add the bot to the managers' group and send /id there; "
                "the group id looks like -1001234567890."
            )
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
