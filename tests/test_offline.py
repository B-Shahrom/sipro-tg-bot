"""Rule-based assistant: price parsing, compatibility rules, configurator, intents."""

import pytest

from bot.config import get_settings
from bot.offline import faq
from bot.offline.compat import check, confirmations
from bot.offline.configurator import configure, min_budget
from bot.offline.engine import OfflineAssistant, parse_prices
from bot.offline.specs import CASE, GPU, RAM, STORAGE, Part


@pytest.mark.parametrize("text, expected", [
    ("монитор до 25000", (None, 25000)),
    ("мышь до 5к", (None, 5000)),
    ("пк за 100 тысяч", (None, 100000)),
    ("видеокарта до 30 000", (None, 30000)),
    ("от 10000 до 20000", (10000, 20000)),
    ("около 30к", (24000, 36000)),
    ("видеокарта rtx 4070", (None, None)),     # model number, not a price
    ("монитор 4к", (None, None)),              # resolution, not 4000
    ("ssd 1 тб до 7000", (None, 7000)),
    ("бп 550 вт", (None, None)),
])
def test_parse_prices(text, expected):
    lo, hi, _ = parse_prices(text)
    assert (lo, hi) == expected


async def skus(db, *codes):
    return await db.products_by_skus(list(codes))


async def test_compat_rules(db):
    assert check(await skus(db, "CPU-R7-7800X3D", "MB-B650M-A")) == []
    assert "сокет" in confirmations(await skus(db, "CPU-R7-7800X3D", "MB-B650M-A"))[0]

    wrong_socket = check(await skus(db, "CPU-R7-7800X3D", "MB-Z790-P"))
    assert wrong_socket and wrong_socket[0].level == "error" and "AM5" in wrong_socket[0].text

    ddr4_on_ddr5 = check(await skus(db, "MB-B650M-A", "RAM-D4-16-3200"))
    assert ddr4_on_ddr5 and "DDR4" in ddr4_on_ddr5[0].text

    long_gpu = check(await skus(db, "GPU-4080S-16", "CASE-ITX-NR200P"))
    assert any("348" in i.text for i in long_gpu)

    weak_psu = check(await skus(db, "GPU-4080S-16", "PSU-550-BRONZE"))
    assert any(i.level == "error" and "850" in i.text for i in weak_psu)

    sfx_case = check(await skus(db, "CASE-ITX-NR200P", "PSU-750-GOLD"))
    assert any("SFX" in i.text for i in sfx_case)

    atx_board_in_matx_case = check(await skus(db, "MB-B650-TUF", "CASE-MATX-AIR"))
    assert any("ATX" in i.text for i in atx_board_in_matx_case)

    # A full build without a cooler for a boxless CPU gets a reminder; a pair question doesn't.
    assert check(await skus(db, "CPU-R7-7800X3D", "MB-B650M-A")) == []
    full = check(await skus(db, "CPU-R7-7800X3D", "MB-B650M-A", "RAM-D5-32-6000", "CASE-ATX-4000D"))
    assert any("кулер" in i.text.lower() for i in full)


@pytest.mark.parametrize("purpose, budget", [
    ("gaming", 60000), ("gaming", 100000), ("gaming", 180000), ("work", 70000), ("office", 40000),
    ("creator", 250000),
])
async def test_configurator_builds_are_compatible_and_within_budget(db, purpose, budget):
    build = await configure(db, purpose, budget)
    assert build and build.parts
    assert build.total <= budget
    assert [i for i in check(build.parts) if i.level == "error"] == []
    cats = {p.category for p in build.parts}
    assert {"Процессоры", "Материнские платы", RAM, STORAGE, "Блоки питания", CASE} <= cats
    if purpose in ("gaming", "creator"):
        assert GPU in cats
    if purpose == "office":
        assert GPU not in cats
    assert all(p.stock > 0 for p in build.parts)


async def test_configurator_balance_and_scaling(db):
    build = await configure(db, "gaming", 100000)
    parts = {p.category: Part(p) for p in build.parts}
    assert parts[RAM].capacity_gb >= 32  # the budget is well above the minimum, so no 16 GB
    assert parts["Процессоры"].price >= 0.25 * parts[GPU].price  # no weak CPU with a big GPU


async def test_configurator_preferences(db):
    white = await configure(db, "gaming", 180000, "хочу белый корпус")
    assert "бел" in Part(next(p for p in white.parts if p.category == CASE)).color
    compact = await configure(db, "gaming", 150000, "компактный")
    case = Part(next(p for p in compact.parts if p.category == CASE))
    assert case.case_boards == {"MINI-ITX"}
    assert check(compact.parts) == []
    intel = await configure(db, "work", 70000, "intel")
    assert next(p for p in intel.parts if p.category == "Процессоры").brand == "Intel"


async def test_configurator_budget_too_low(db):
    build = await configure(db, "gaming", 20000)
    assert build is None or not build.parts
    assert 40000 < await min_budget(db, "gaming") < 60000


def test_store_info_sections_hide_comments():
    path = get_settings().store_info_path
    intro, sections = faq.load_sections(path)
    assert "ДЕМО" not in intro and "Адрес" in sections and "Гарантия" in sections
    assert "<!--" not in faq.clean_store_info(path)


@pytest.fixture
def engine(db):
    return OfflineAssistant(db, get_settings())


@pytest.mark.parametrize("text, expect", [
    ("где вы находитесь?", "Адрес"),
    ("до скольки работаете в воскресенье", "Часы работы"),
    ("есть доставка?", "Доставка"),
    ("можно в рассрочку?", "Оплата"),
    ("сколько стоит сборка?", "Сборка ПК"),
])
async def test_engine_faq(engine, text, expect):
    reply = await engine.reply(1, text)
    assert expect in reply.text


async def test_engine_intents(engine, db):
    assert (await engine.reply(1, "позовите менеджера")).action == "handoff"
    assert (await engine.reply(1, "а скидку сделаете?")).action == "handoff"
    assert (await engine.reply(1, "где мой заказ")).action == "orders"
    assert (await engine.reply(1, "корзина")).action == "cart"
    assert (await engine.reply(1, "нужен компьютер для офиса")).action == "builder"  # no budget → the form
    assert "service" in (await engine.reply(1, "видеокарта сломалась, артефакты")).quick
    unknown = await engine.reply(1, "абырвалг", degraded=True)
    assert "упрощённом режиме" in unknown.text and "manager" in unknown.quick


async def test_engine_search(engine):
    monitors = await engine.reply(1, "нужен монитор для игр до 25000")
    assert monitors.products and all(p.category == "Мониторы" and p.price <= 25000 for p in monitors.products)
    assert all(int(Part(p).s["частота"].split()[0]) >= 144 for p in monitors.products)

    intel = await engine.reply(1, "процессор intel до 20к")
    assert intel.products and all(p.brand == "Intel" for p in intel.products)

    two = await engine.reply(1, "видеокарта rtx 4070")
    assert {p.sku for p in two.products} == {"GPU-4070S-12", "GPU-4070TIS-16"}  # ambiguous → both

    exact = await engine.reply(1, "GPU-4060-8")
    assert exact.action == "show_product" and exact.products[0].sku == "GPU-4060-8"

    wireless = await engine.reply(1, "беспроводная мышь")
    assert wireless.products and all("беспровод" in p.specs for p in wireless.products)


async def test_engine_compat_questions(engine):
    ok = await engine.reply(1, "подойдет ли 7800x3d к b650m-a?")
    assert ok.text.startswith("✅")
    too_long = await engine.reply(1, "влезет ли 4080 super в NR200P")
    assert "❌" in too_long.text and "348" in too_long.text


async def test_engine_build_from_text(engine):
    reply = await engine.reply(1, "собрать пк для игр за 100 тысяч")
    assert reply.build and reply.build.total <= 100000
    assert "Совместимость проверена" in reply.text

    too_cheap = await engine.reply(1, "собери пк для игр за 20000")
    assert not too_cheap.build and "Минимальный бюджет" in too_cheap.text


async def test_engine_order_lookup(engine, db):
    await db.cart_add(1, "SSD-1TB-NV3", 1)
    order = await db.create_order_from_cart(1, "Иван", "+7900", "Самовывоз", "")
    mine = await engine.reply(1, f"статус заказа №{order.id}")
    assert f"№{order.id}" in mine.text and "Kingston" in mine.text
    other = await engine.reply(2, f"статус заказа №{order.id}")
    assert other.action == "orders" and "Kingston" not in other.text  # someone else's order stays private


async def test_describe_product_suggests_compatible_parts(engine):
    cpu = await engine.describe("CPU-R7-7800X3D")
    cats = {p.category for p in cpu.products}
    assert "Материнские платы" in cats and "Охлаждение" in cats  # boxless CPU → coolers suggested
    assert all(Part(p).socket == "AM5" for p in cpu.products if p.category == "Материнские платы")
