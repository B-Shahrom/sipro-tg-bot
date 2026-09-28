"""Tools the assistant can call. Every tool is scoped to the customer of the current conversation:
the customer id comes from ToolContext, never from model input."""

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..db import Database, Product
from ..formatting import money

log = logging.getLogger(__name__)

TOOLS = [
    {
        "name": "search_products",
        "description": (
            "Search the store catalog. Returns matching active products with SKU, category, name, brand, price, "
            "stock and specs. All words in `query` must match (name, brand, category, specs or description), so use "
            "short key terms like 'RTX 4070', 'AM5', 'DDR5 32', '27 IPS 165'. Leave `query` empty to list a category "
            "or price range. Call list_categories first if unsure of the exact category name."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Key words to match. May be empty."},
                "category": {"type": "string", "description": "Exact category name from list_categories."},
                "min_price": {"type": "number"},
                "max_price": {"type": "number"},
                "in_stock_only": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "description": "Default 10."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_categories",
        "description": "List catalog categories with the number of products in each.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_product",
        "description": "Get the full details of one product by SKU, including description.",
        "input_schema": {
            "type": "object",
            "properties": {"sku": {"type": "string"}},
            "required": ["sku"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_to_cart",
        "description": (
            "Add products to the customer's cart. Only call after the customer has confirmed they want these items. "
            "Returns the updated cart."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sku": {"type": "string"},
                            "qty": {"type": "integer", "minimum": 1, "maximum": 50},
                        },
                        "required": ["sku", "qty"],
                        "additionalProperties": False,
                    },
                    "minItems": 1,
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
    {
        "name": "view_cart",
        "description": "Show the customer's current cart and total.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_my_orders",
        "description": "List the customer's recent orders and service (warranty/repair) requests with their statuses.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "handoff_to_manager",
        "description": (
            "Transfer the conversation to a human manager. The customer's next messages go to store staff instead of "
            "you. Use when the customer asks for a person, for negotiations/discounts, complaints, returns, problems "
            "with a placed order, bulk/corporate orders, or anything you cannot resolve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short reason, e.g. 'wants a discount on a build'."},
                "summary": {
                    "type": "string",
                    "description": "2-4 sentence summary for the manager: what the customer needs, products/SKUs discussed, budget.",
                },
            },
            "required": ["reason", "summary"],
            "additionalProperties": False,
        },
    },
]

# Stable order keeps the prompt-cache prefix identical across requests.
TOOLS.sort(key=lambda tool: tool["name"])


@dataclass
class ToolContext:
    db: Database
    user_id: int
    currency: str
    # Called with (reason, summary) to open a live chat with managers.
    on_handoff: Callable[[str, str], Awaitable[None]]
    handed_off: bool = field(default=False)


def _product_brief(p: Product, currency: str) -> dict:
    return {
        "sku": p.sku,
        "category": p.category,
        "name": p.name,
        "brand": p.brand,
        "price": money(p.price, currency),
        "stock": p.stock if p.stock > 0 else "out of stock (available on order)",
        "specs": p.specs,
    }


async def _cart_view(ctx: ToolContext) -> dict:
    lines = await ctx.db.cart(ctx.user_id)
    return {
        "items": [
            {"sku": li.sku, "name": li.name, "qty": li.qty, "price": money(li.price, ctx.currency),
             "subtotal": money(li.subtotal, ctx.currency)}
            for li in lines
        ],
        "total": money(sum(li.subtotal for li in lines), ctx.currency),
    }


async def execute_tool(name: str, args: dict, ctx: ToolContext) -> tuple[str, bool]:
    """Run a tool. Returns (result_json, is_error)."""
    try:
        result = await _dispatch(name, args or {}, ctx)
        return json.dumps(result, ensure_ascii=False), False
    except ToolError as e:
        return str(e), True
    except Exception:
        log.exception("tool %s failed", name)
        return "Internal error while running the tool.", True


class ToolError(Exception):
    pass


async def _dispatch(name: str, args: dict, ctx: ToolContext):
    db = ctx.db
    if name == "search_products":
        limit = max(1, min(int(args.get("limit") or 10), 25))
        products = await db.search_products(
            query=str(args.get("query") or ""),
            category=args.get("category") or None,
            min_price=args.get("min_price"),
            max_price=args.get("max_price"),
            in_stock_only=bool(args.get("in_stock_only")),
            limit=limit,
        )
        if not products:
            return {"results": [], "note": "Nothing found. Try fewer or different words, or another category."}
        return {"results": [_product_brief(p, ctx.currency) for p in products]}

    if name == "list_categories":
        return {"categories": [{"name": c, "products": n} for c, n in await db.categories()]}

    if name == "get_product":
        p = await db.get_product(str(args.get("sku", "")))
        if not p or not p.active:
            raise ToolError(f"No active product with SKU {args.get('sku')!r}.")
        return {**_product_brief(p, ctx.currency), "description": p.description}

    if name == "add_to_cart":
        items = args.get("items") or []
        if not isinstance(items, list) or not items:
            raise ToolError("`items` must be a non-empty list.")
        added, problems = [], []
        for item in items:
            sku = str(item.get("sku", ""))
            qty = max(1, min(int(item.get("qty") or 1), 50))
            p = await db.get_product(sku)
            if not p or not p.active:
                problems.append(f"SKU {sku!r} not found")
                continue
            await db.cart_add(ctx.user_id, sku, qty)
            added.append(f"{p.name} × {qty}")
        return {"added": added, "problems": problems, "cart": await _cart_view(ctx)}

    if name == "view_cart":
        return await _cart_view(ctx)

    if name == "get_my_orders":
        orders = await db.user_orders(ctx.user_id, limit=5)
        tickets = await db.user_tickets(ctx.user_id, limit=5)
        return {
            "orders": [
                {"id": o.id, "date": o.created_at[:10], "status": o.status, "total": money(o.total, ctx.currency),
                 "items": [f"{i.name} × {i.qty}" for i in o.items]}
                for o in orders
            ],
            "service_requests": [
                {"id": tk.id, "date": tk.created_at[:10], "status": tk.status, "product": tk.product}
                for tk in tickets
            ],
            "status_meanings": {
                "new": "received, waiting for a manager to confirm", "confirmed": "confirmed by manager",
                "paid": "paid", "shipped": "shipped / ready for pickup", "done": "completed",
                "cancelled": "cancelled", "in_progress": "service request being worked on", "rejected": "rejected",
            },
        }

    if name == "handoff_to_manager":
        if not ctx.handed_off:
            await ctx.on_handoff(str(args.get("reason", "")), str(args.get("summary", "")))
            ctx.handed_off = True
        return {"ok": True, "note": "A manager has been notified and will reply in this chat."}

    raise ToolError(f"Unknown tool {name!r}.")
