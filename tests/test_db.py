from bot.formatting import normalize_phone, split_message, strip_html


async def test_import_and_categories(db):
    cats = dict(await db.categories())
    assert cats["Видеокарты"] == 4
    assert await db.count_products() == 40


async def test_reimport_hides_missing_and_reports_errors(db):
    csv = "sku,category,name,price,stock\nGPU-4060-8,Видеокарты,RTX 4060,30000,1\nBAD,Видеокарты,Broken,abc,1\n"
    imported, deactivated, errors = await db.import_catalog_csv(csv)
    assert imported == 1
    assert deactivated == 39
    assert len(errors) == 1 and "line 3" in errors[0]
    assert (await db.get_product("GPU-4060-8")).price == 30000
    assert not (await db.get_product("CPU-R5-7600")).active


async def test_import_requires_columns(db):
    imported, _, errors = await db.import_catalog_csv("sku,name\nx,y\n")
    assert imported == 0 and "missing columns" in errors[0]


async def test_search_is_case_insensitive_for_cyrillic(db):
    results = await db.search_products("готовые пк")
    assert {p.sku for p in results} >= {"PC-GAME-4060", "PC-OFFICE-5600G"}
    am5 = await db.search_products("am5 ddr5", category="Материнские платы")
    assert {p.sku for p in am5} == {"MB-B650M-A", "MB-B650-TUF"}
    cheap = await db.search_products(category="Мониторы", max_price=20000)
    assert [p.sku for p in cheap] == ["MON-24-IPS-165"]


async def test_cart_to_order(db):
    await db.cart_add(7, "GPU-4060-8", 1)
    await db.cart_add(7, "GPU-4060-8", 1)
    await db.cart_add(7, "SSD-1TB-NV3", 1)
    lines = await db.cart(7)
    assert {(li.sku, li.qty) for li in lines} == {("GPU-4060-8", 2), ("SSD-1TB-NV3", 1)}

    order = await db.create_order_from_cart(7, "Иван", "+79001234567", "Самовывоз", "")
    assert order.total == 32990 * 2 + 6490
    assert order.status == "new"
    assert await db.cart(7) == []
    assert [o.id for o in await db.user_orders(7)] == [order.id]
    assert (await db.set_order_status(order.id, "shipped")).status == "shipped"
    assert await db.create_order_from_cart(7, "Иван", "+7", "", "") is None


async def test_history_window_starts_at_customer_message(db):
    await db.upsert_user(5, None, "Test", "ru")
    await db.add_history(5, "user", "привет")
    await db.add_history(5, "assistant", [{"type": "tool_use", "id": "t1", "name": "view_cart", "input": {}}])
    await db.add_history(5, "user", [{"type": "tool_result", "tool_use_id": "t1", "content": "{}"}])
    await db.add_history(5, "assistant", [{"type": "text", "text": "Корзина пуста"}])
    await db.add_history(5, "user", "а мониторы?")
    await db.add_history(5, "assistant", [{"type": "text", "text": "Есть"}])
    # A window of 4 would start at the tool_result; it must be advanced to the next real user message.
    window = await db.get_history(5, 4)
    assert window[0] == {"role": "user", "content": "а мониторы?"}
    assert len(await db.get_history(5, 100)) == 6


async def test_ai_quota(db):
    await db.upsert_user(9, None, "Q", "ru")
    assert await db.take_ai_quota(9, 2)
    assert await db.take_ai_quota(9, 2)
    assert not await db.take_ai_quota(9, 2)
    assert await db.take_ai_quota(9, 0)  # unlimited


def test_phone_and_text_helpers():
    assert normalize_phone("+7 (900) 123-45-67") == "+79001234567"
    assert normalize_phone("8 900 123 45 67") == "89001234567"
    assert normalize_phone("hello") is None
    assert normalize_phone("123") is None
    assert strip_html("<b>A</b> &amp; B") == "A & B"
    parts = split_message("a" * 5000 + "\nb", limit=4096)
    assert all(len(p) <= 4096 for p in parts) and "".join(parts).replace("\n", "") == "a" * 5000 + "b"


def test_config_rejects_usernames_in_admin_ids(monkeypatch):
    import pytest
    from pydantic import ValidationError

    from bot.config import Settings

    monkeypatch.setenv("ADMIN_IDS", "123, 456")
    assert Settings().admin_ids == [123, 456]
    monkeypatch.setenv("ADMIN_IDS", "@B_Shahrom")
    with pytest.raises(ValidationError, match="not a numeric Telegram user id"):
        Settings()
