"""SQLite storage: catalog, carts, orders, service tickets, dialog history, manager relay."""

import csv
import io
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT,
    full_name     TEXT,
    lang          TEXT NOT NULL DEFAULT 'ru',
    phone         TEXT,
    handoff       INTEGER NOT NULL DEFAULT 0,
    ai_day        TEXT,
    ai_count      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products (
    sku          TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    name         TEXT NOT NULL,
    brand        TEXT NOT NULL DEFAULT '',
    price        REAL NOT NULL,
    stock        INTEGER NOT NULL DEFAULT 0,
    specs        TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    image_url    TEXT NOT NULL DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    search_text  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category, active);

CREATE TABLE IF NOT EXISTS cart_items (
    user_id  INTEGER NOT NULL,
    sku      TEXT NOT NULL,
    qty      INTEGER NOT NULL,
    PRIMARY KEY (user_id, sku)
);

CREATE TABLE IF NOT EXISTS orders (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    customer_name  TEXT NOT NULL,
    phone          TEXT NOT NULL,
    delivery       TEXT NOT NULL DEFAULT '',
    comment        TEXT NOT NULL DEFAULT '',
    total          REAL NOT NULL,
    status         TEXT NOT NULL DEFAULT 'new',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);

CREATE TABLE IF NOT EXISTS order_items (
    order_id  INTEGER NOT NULL,
    sku       TEXT NOT NULL,
    name      TEXT NOT NULL,
    price     REAL NOT NULL,
    qty       INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    order_ref   TEXT NOT NULL DEFAULT '',
    product     TEXT NOT NULL,
    problem     TEXT NOT NULL,
    phone       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new',
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id, id);

CREATE TABLE IF NOT EXISTS relay (
    chat_message_id  INTEGER PRIMARY KEY,
    user_id          INTEGER NOT NULL
);
"""

ORDER_STATUSES = ("new", "confirmed", "paid", "shipped", "done", "cancelled")
TICKET_STATUSES = ("new", "in_progress", "done", "rejected")
CSV_FIELDS = ("sku", "category", "name", "brand", "price", "stock", "specs", "description", "image_url")


@dataclass
class Product:
    sku: str
    category: str
    name: str
    brand: str
    price: float
    stock: int
    specs: str
    description: str
    image_url: str
    active: bool


@dataclass
class CartLine:
    sku: str
    name: str
    price: float
    qty: int
    stock: int

    @property
    def subtotal(self) -> float:
        return self.price * self.qty


@dataclass
class Order:
    id: int
    user_id: int
    customer_name: str
    phone: str
    delivery: str
    comment: str
    total: float
    status: str
    created_at: str
    items: list[CartLine]


@dataclass
class Ticket:
    id: int
    user_id: int
    order_ref: str
    product: str
    problem: str
    phone: str
    status: str
    created_at: str


def _search_text(*parts: str) -> str:
    return " ".join(p for p in parts if p).lower()


def _row_to_product(row: aiosqlite.Row) -> Product:
    return Product(
        sku=row["sku"],
        category=row["category"],
        name=row["name"],
        brand=row["brand"],
        price=row["price"],
        stock=row["stock"],
        specs=row["specs"],
        description=row["description"],
        image_url=row["image_url"],
        active=bool(row["active"]),
    )


class Database:
    def __init__(self, path: Path | str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if isinstance(self.path, Path):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA journal_mode=WAL")
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    # ---------- users ----------

    async def upsert_user(self, user_id: int, username: str | None, full_name: str, default_lang: str) -> None:
        await self.conn.execute(
            """INSERT INTO users (id, username, full_name, lang) VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET username = excluded.username, full_name = excluded.full_name""",
            (user_id, username, full_name, default_lang),
        )
        await self.conn.commit()

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            return await cur.fetchone()

    async def set_lang(self, user_id: int, lang: str) -> None:
        await self.conn.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, user_id))
        await self.conn.commit()

    async def set_phone(self, user_id: int, phone: str) -> None:
        await self.conn.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, user_id))
        await self.conn.commit()

    async def set_handoff(self, user_id: int, on: bool) -> None:
        await self.conn.execute("UPDATE users SET handoff = ? WHERE id = ?", (int(on), user_id))
        await self.conn.commit()

    async def take_ai_quota(self, user_id: int, daily_limit: int) -> bool:
        """Count one AI reply for today. Returns False if the daily limit is exhausted."""
        today = date.today().isoformat()
        user = await self.get_user(user_id)
        count = user["ai_count"] if user and user["ai_day"] == today else 0
        if daily_limit and count >= daily_limit:
            return False
        await self.conn.execute("UPDATE users SET ai_day = ?, ai_count = ? WHERE id = ?", (today, count + 1, user_id))
        await self.conn.commit()
        return True

    async def count_users(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) FROM users") as cur:
            return (await cur.fetchone())[0]

    # ---------- catalog ----------

    async def categories(self) -> list[tuple[str, int]]:
        async with self.conn.execute(
            "SELECT category, COUNT(*) FROM products WHERE active = 1 GROUP BY category ORDER BY category"
        ) as cur:
            return [(r[0], r[1]) for r in await cur.fetchall()]

    async def products_in_category(self, category: str, offset: int, limit: int) -> tuple[list[Product], int]:
        async with self.conn.execute(
            "SELECT COUNT(*) FROM products WHERE active = 1 AND category = ?", (category,)
        ) as cur:
            total = (await cur.fetchone())[0]
        async with self.conn.execute(
            """SELECT * FROM products WHERE active = 1 AND category = ?
               ORDER BY stock > 0 DESC, price LIMIT ? OFFSET ?""",
            (category, limit, offset),
        ) as cur:
            return [_row_to_product(r) for r in await cur.fetchall()], total

    async def get_product(self, sku: str) -> Product | None:
        async with self.conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)) as cur:
            row = await cur.fetchone()
        return _row_to_product(row) if row else None

    async def search_products(
        self,
        query: str = "",
        category: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        in_stock_only: bool = False,
        limit: int = 10,
    ) -> list[Product]:
        sql = ["SELECT * FROM products WHERE active = 1"]
        args: list = []
        # Every word must match somewhere in name/brand/category/specs/description.
        for word in query.lower().split():
            sql.append("AND search_text LIKE ?")
            args.append(f"%{word}%")
        if category:
            sql.append("AND category = ?")
            args.append(category)
        if min_price is not None:
            sql.append("AND price >= ?")
            args.append(min_price)
        if max_price is not None:
            sql.append("AND price <= ?")
            args.append(max_price)
        if in_stock_only:
            sql.append("AND stock > 0")
        sql.append("ORDER BY stock > 0 DESC, price LIMIT ?")
        args.append(limit)
        async with self.conn.execute(" ".join(sql), args) as cur:
            return [_row_to_product(r) for r in await cur.fetchall()]

    async def import_catalog_csv(self, data: str, deactivate_missing: bool = True) -> tuple[int, int, list[str]]:
        """Upsert products from CSV text. Returns (imported, deactivated, errors)."""
        reader = csv.DictReader(io.StringIO(data.lstrip("﻿")))
        missing = {"sku", "category", "name", "price"} - set(reader.fieldnames or [])
        if missing:
            return 0, 0, [f"missing columns: {', '.join(sorted(missing))}"]

        rows, errors = [], []
        for line_no, row in enumerate(reader, start=2):
            try:
                sku = (row.get("sku") or "").strip()
                name = (row.get("name") or "").strip()
                category = (row.get("category") or "").strip()
                if not sku or not name or not category:
                    raise ValueError("sku, name and category are required")
                price = float(str(row.get("price") or "").replace(" ", "").replace(",", "."))
                stock = int(float(row.get("stock") or 0))
            except ValueError as e:
                errors.append(f"line {line_no}: {e}")
                continue
            brand = (row.get("brand") or "").strip()
            specs = (row.get("specs") or "").strip()
            description = (row.get("description") or "").strip()
            rows.append((
                sku, category, name, brand, price, stock, specs, description,
                (row.get("image_url") or "").strip(),
                _search_text(sku, category, name, brand, specs, description),
            ))

        if not rows:
            return 0, 0, errors or ["no rows"]

        await self.conn.executemany(
            """INSERT INTO products (sku, category, name, brand, price, stock, specs, description, image_url, search_text, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
               ON CONFLICT(sku) DO UPDATE SET
                 category = excluded.category, name = excluded.name, brand = excluded.brand,
                 price = excluded.price, stock = excluded.stock, specs = excluded.specs,
                 description = excluded.description, image_url = excluded.image_url,
                 search_text = excluded.search_text, active = 1""",
            rows,
        )
        deactivated = 0
        if deactivate_missing:
            skus = [r[0] for r in rows]
            placeholders = ",".join("?" * len(skus))
            cur = await self.conn.execute(
                f"UPDATE products SET active = 0 WHERE active = 1 AND sku NOT IN ({placeholders})", skus
            )
            deactivated = cur.rowcount
        await self.conn.commit()
        return len(rows), deactivated, errors

    async def export_catalog_csv(self) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(CSV_FIELDS)
        async with self.conn.execute(
            f"SELECT {', '.join(CSV_FIELDS)} FROM products WHERE active = 1 ORDER BY category, name"
        ) as cur:
            async for row in cur:
                writer.writerow(list(row))
        return out.getvalue()

    async def count_products(self) -> int:
        async with self.conn.execute("SELECT COUNT(*) FROM products WHERE active = 1") as cur:
            return (await cur.fetchone())[0]

    # ---------- cart ----------

    async def cart_add(self, user_id: int, sku: str, qty: int = 1) -> None:
        await self.conn.execute(
            """INSERT INTO cart_items (user_id, sku, qty) VALUES (?, ?, ?)
               ON CONFLICT(user_id, sku) DO UPDATE SET qty = qty + excluded.qty""",
            (user_id, sku, qty),
        )
        await self.conn.execute("DELETE FROM cart_items WHERE user_id = ? AND qty <= 0", (user_id,))
        await self.conn.commit()

    async def cart_remove(self, user_id: int, sku: str) -> None:
        await self.conn.execute("DELETE FROM cart_items WHERE user_id = ? AND sku = ?", (user_id, sku))
        await self.conn.commit()

    async def cart_clear(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    async def cart(self, user_id: int) -> list[CartLine]:
        async with self.conn.execute(
            """SELECT p.sku, p.name, p.price, c.qty, p.stock FROM cart_items c
               JOIN products p ON p.sku = c.sku AND p.active = 1
               WHERE c.user_id = ? ORDER BY p.category, p.name""",
            (user_id,),
        ) as cur:
            return [CartLine(r[0], r[1], r[2], r[3], r[4]) for r in await cur.fetchall()]

    # ---------- orders ----------

    async def create_order_from_cart(
        self, user_id: int, customer_name: str, phone: str, delivery: str, comment: str
    ) -> Order | None:
        lines = await self.cart(user_id)
        if not lines:
            return None
        total = sum(line.subtotal for line in lines)
        cur = await self.conn.execute(
            "INSERT INTO orders (user_id, customer_name, phone, delivery, comment, total) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, customer_name, phone, delivery, comment, total),
        )
        order_id = cur.lastrowid
        await self.conn.executemany(
            "INSERT INTO order_items (order_id, sku, name, price, qty) VALUES (?, ?, ?, ?, ?)",
            [(order_id, line.sku, line.name, line.price, line.qty) for line in lines],
        )
        await self.conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
        await self.conn.commit()
        return await self.get_order(order_id)

    async def get_order(self, order_id: int) -> Order | None:
        async with self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        async with self.conn.execute(
            "SELECT sku, name, price, qty FROM order_items WHERE order_id = ?", (order_id,)
        ) as cur:
            items = [CartLine(r[0], r[1], r[2], r[3], 0) for r in await cur.fetchall()]
        return Order(
            id=row["id"], user_id=row["user_id"], customer_name=row["customer_name"], phone=row["phone"],
            delivery=row["delivery"], comment=row["comment"], total=row["total"], status=row["status"],
            created_at=row["created_at"], items=items,
        )

    async def user_orders(self, user_id: int, limit: int = 10) -> list[Order]:
        async with self.conn.execute(
            "SELECT id FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ) as cur:
            ids = [r[0] for r in await cur.fetchall()]
        return [await self.get_order(i) for i in ids]

    async def orders_by_status(self, statuses: tuple[str, ...], limit: int = 20) -> list[Order]:
        placeholders = ",".join("?" * len(statuses))
        async with self.conn.execute(
            f"SELECT id FROM orders WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT ?", (*statuses, limit)
        ) as cur:
            ids = [r[0] for r in await cur.fetchall()]
        return [await self.get_order(i) for i in ids]

    async def set_order_status(self, order_id: int, status: str) -> Order | None:
        if status not in ORDER_STATUSES:
            raise ValueError(status)
        await self.conn.execute(
            "UPDATE orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, order_id)
        )
        await self.conn.commit()
        return await self.get_order(order_id)

    # ---------- service tickets ----------

    async def create_ticket(self, user_id: int, order_ref: str, product: str, problem: str, phone: str) -> Ticket:
        cur = await self.conn.execute(
            "INSERT INTO tickets (user_id, order_ref, product, problem, phone) VALUES (?, ?, ?, ?, ?)",
            (user_id, order_ref, product, problem, phone),
        )
        await self.conn.commit()
        return await self.get_ticket(cur.lastrowid)

    async def get_ticket(self, ticket_id: int) -> Ticket | None:
        async with self.conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)) as cur:
            row = await cur.fetchone()
        return Ticket(**dict(row)) if row else None

    async def user_tickets(self, user_id: int, limit: int = 5) -> list[Ticket]:
        async with self.conn.execute(
            "SELECT * FROM tickets WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ) as cur:
            return [Ticket(**dict(r)) for r in await cur.fetchall()]

    async def set_ticket_status(self, ticket_id: int, status: str) -> Ticket | None:
        if status not in TICKET_STATUSES:
            raise ValueError(status)
        await self.conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        await self.conn.commit()
        return await self.get_ticket(ticket_id)

    # ---------- AI dialog history ----------

    async def add_history(self, user_id: int, role: str, content: str | list) -> None:
        await self.conn.execute(
            "INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, json.dumps(content, ensure_ascii=False)),
        )
        await self.conn.commit()

    async def get_history(self, user_id: int, limit: int) -> list[dict]:
        async with self.conn.execute(
            "SELECT role, content FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
        ) as cur:
            rows = list(reversed(await cur.fetchall()))
        messages = [{"role": r["role"], "content": json.loads(r["content"])} for r in rows]
        # The window must start at a real customer message, not mid tool-call exchange.
        while messages and not (messages[0]["role"] == "user" and isinstance(messages[0]["content"], str)):
            messages.pop(0)
        return messages

    async def clear_history(self, user_id: int) -> None:
        await self.conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
        await self.conn.commit()

    # ---------- manager relay ----------

    async def remember_relay(self, chat_message_id: int, user_id: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO relay (chat_message_id, user_id) VALUES (?, ?)", (chat_message_id, user_id)
        )
        await self.conn.commit()

    async def relay_target(self, chat_message_id: int) -> int | None:
        async with self.conn.execute("SELECT user_id FROM relay WHERE chat_message_id = ?", (chat_message_id,)) as cur:
            row = await cur.fetchone()
        return row[0] if row else None
