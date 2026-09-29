"""Admin commands: catalog import/export, stats, store-info reload. Work in private chat or the managers' group."""

from aiogram import Bot, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import BufferedInputFile, Message

from ..ai.assistant import Assistant
from ..config import Settings
from ..db import Database
from ..formatting import esc


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message, settings: Settings) -> bool:
        return message.from_user is not None and message.from_user.id in settings.admin_ids


router = Router(name="admin")
router.message.filter(IsAdmin())

MAX_CSV_BYTES = 10 * 1024 * 1024


@router.message(Command("import"))
async def cmd_import(message: Message, bot: Bot, db: Database):
    doc = message.document or (message.reply_to_message.document if message.reply_to_message else None)
    if not doc:
        await message.answer(
            "Отправьте CSV-файл каталога с подписью <code>/import</code> (или ответьте <code>/import</code> на файл).\n"
            "Колонки: <code>sku, category, name, brand, price, stock, specs, description, image_url</code>.\n"
            "Товары, которых нет в файле, будут скрыты из каталога. Текущий каталог: /export"
        )
        return
    if doc.file_size and doc.file_size > MAX_CSV_BYTES:
        await message.answer("Файл слишком большой (максимум 10 МБ).")
        return
    buf = await bot.download(doc)
    raw = buf.read()
    try:
        data = raw.decode("utf-8")
    except UnicodeDecodeError:
        data = raw.decode("cp1251")  # Excel on Russian-locale Windows
    imported, deactivated, errors = await db.import_catalog_csv(data)
    lines = [f"✅ Загружено товаров: {imported}", f"Скрыто (нет в файле): {deactivated}"]
    if errors:
        lines.append(f"\n⚠️ Ошибки ({len(errors)}):\n" + "\n".join(esc(e) for e in errors[:20]))
    await message.answer("\n".join(lines))


@router.message(Command("export"))
async def cmd_export(message: Message, db: Database):
    data = await db.export_catalog_csv()
    await message.answer_document(BufferedInputFile(data.encode("utf-8-sig"), filename="catalog.csv"))


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, assistant: Assistant):
    active = await db.orders_by_status(("new", "confirmed", "paid", "shipped"), limit=1000)
    if not assistant.enabled:
        ai = "выключен (нет ключа API или AI_ENABLED=false) — работает резервный режим"
    elif assistant.available:
        ai = f"работает ({esc(assistant.settings.claude_model)})"
    else:
        ai = f"временно недоступен: {esc(assistant.last_error)} — работает резервный режим"
    await message.answer(
        f"Клиентов: {await db.count_users()}\n"
        f"Товаров в каталоге: {await db.count_products()}\n"
        f"Активных заказов: {len(active)} (новых: {sum(o.status == 'new' for o in active)})\n"
        f"ИИ-ассистент: {ai}"
    )


@router.message(Command("reload"))
async def cmd_reload(message: Message, assistant: Assistant):
    assistant.reload_store_info()
    await message.answer("Информация о магазине перечитана из файла.")

