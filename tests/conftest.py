import os
from pathlib import Path

import pytest_asyncio

os.environ.setdefault("BOT_TOKEN", "42:TEST")
os.environ.setdefault("MANAGER_CHAT_ID", "-100500")
os.environ.setdefault("ADMIN_IDS", "1")

from bot.db import Database  # noqa: E402

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "data" / "catalog_sample.csv"


@pytest_asyncio.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    await database.import_catalog_csv(SAMPLE_CSV.read_text(encoding="utf-8"))
    yield database
    await database.close()
