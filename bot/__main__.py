"""Run the bot:            python -m bot
Import a catalog CSV:    python -m bot import data/catalog_sample.csv"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats
from pydantic import ValidationError

from .ai.assistant import Assistant
from .config import get_settings
from .db import Database
from .handlers import admin, builder, cart, catalog, chat, common, handoff, managers, service, utils
from .middlewares import CustomerMiddleware

log = logging.getLogger("bot")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(utils.router)
    dp.include_router(admin.router)
    dp.include_router(managers.router)
    # Customer-facing routers, in priority order. `chat` is the catch-all and must be last.
    for module in (common, catalog, cart, service, builder, handoff, chat):
        r = module.router
        r.message.filter(F.chat.type == "private")
        r.callback_query.filter(F.message.chat.type == "private")
        r.message.middleware(CustomerMiddleware())
        r.callback_query.middleware(CustomerMiddleware())
        dp.include_router(r)
    return dp


async def run_bot() -> None:
    settings = get_settings()
    db = Database(settings.db_path)
    await db.connect()
    assistant = Assistant(settings, db)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="reset", description="Начать диалог заново"),
        BotCommand(command="help", description="Помощь"),
    ]
    if len(settings.languages) > 1:
        commands.append(BotCommand(command="language", description="Язык / Til / Language"))
    await bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())

    if await db.count_products() == 0:
        log.warning("Catalog is empty. Import one: python -m bot import data/catalog_sample.csv (or /import in Telegram)")
    log.info("Starting bot (model=%s, effort=%s)", settings.claude_model, settings.claude_effort)
    try:
        await build_dispatcher().start_polling(bot, db=db, settings=settings, assistant=assistant)
    finally:
        await db.close()
        await bot.session.close()


async def import_catalog(path: Path) -> None:
    settings = get_settings()
    db = Database(settings.db_path)
    await db.connect()
    try:
        imported, deactivated, errors = await db.import_catalog_csv(path.read_text(encoding="utf-8"))
        print(f"Imported: {imported}, hidden (not in file): {deactivated}")
        for e in errors:
            print("  error:", e)
    finally:
        await db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m bot")
    sub = parser.add_subparsers(dest="cmd")
    imp = sub.add_parser("import", help="import catalog CSV")
    imp.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        get_settings()
    except ValidationError as e:
        print("Configuration error in .env:", file=sys.stderr)
        for err in e.errors():
            field = ".".join(str(p) for p in err["loc"]).upper()
            print(f"  {field}: {err['msg']}", file=sys.stderr)
        sys.exit(1)
    if args.cmd == "import":
        asyncio.run(import_catalog(args.path))
    else:
        asyncio.run(run_bot())


if __name__ == "__main__":
    main()
