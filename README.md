# SIPRO Telegram assistant

A Telegram bot for a PC hardware store: it answers customers with AI and hands them to a human manager when needed. It handles components, peripherals, monitors, and ready-built PCs. It speaks Russian today, and more languages can be added later.

## What it does

**For customers (private chat with the bot)**

| Feature | How |
|---|---|
| AI consultant | Customers write a question in their own words, for example "нужен монитор для игр до 30 000" or "подойдёт ли RTX 4070 к БП на 550 Вт?". Claude searches the catalog, compares specs, checks compatibility, and recommends only products you actually stock, at catalog prices. |
| 🛍 Catalog | Customers browse categories, then products, then a product card. From the card they can add the product to the cart or ask the AI about it. |
| 🧩 PC builder | The customer picks a purpose, a budget, and any wishes. The AI puts together a compatible build from the catalog and adds it to the cart once the customer agrees. |
| 🛒 Cart and checkout | The checkout form collects name, phone (share-contact button), pickup or delivery address, and a comment. Managers get the order with status buttons. |
| 📦 My orders | Order and service-request statuses. Customers get a message whenever a manager changes a status. |
| 🛠 Warranty and repair | A form that creates a service ticket for managers. |
| ℹ️ Store info | Address, hours, delivery, payment, and warranty, read from `data/store_info.md`. The AI uses the same file. |
| 👨‍💼 Manager | A live chat with staff. The AI also hands off on its own for discounts, complaints, returns, bulk orders, or when the customer asks for a person. |

**For managers (a Telegram group with the bot)**

- New orders, service requests, and live-chat requests arrive here. A request comes with a summary from the AI and the last few messages.
- To answer a customer, **reply** to any bot message about them. Text, photos, and files all work.
- Reply `/close` to a customer message to end the live chat and hand the customer back to the AI.
- Status buttons on orders and tickets notify the customer automatically.
- `/orders` lists active orders, `/order 12` shows one order, and `/status 12 shipped` sets a status.
- For admins only (`ADMIN_IDS`): `/import` (send a CSV with this caption), `/export`, `/stats`, `/reload` (re-reads `store_info.md`).

## Setup

1. **Create the bot.** In [@BotFather](https://t.me/BotFather), run `/newbot` and copy the token.
2. **Create a managers group** and add the bot to it. The bot's default privacy mode is fine, because it only needs commands and replies to its own messages.
3. **Get an Anthropic API key** at https://console.anthropic.com.
4. **Configure:**
   ```bash
   cp .env.example .env   # fill in BOT_TOKEN, ANTHROPIC_API_KEY, CURRENCY
   ```
   `ADMIN_IDS` and `MANAGER_CHAT_ID` must be **numeric ids**, not @usernames. To find them, start the bot once with the placeholder values, then:
   - send `/id` to the bot in private chat to get your user id (`ADMIN_IDS`);
   - send `/id` in the managers' group to get the group id (`MANAGER_CHAT_ID`, starts with `-100`).

   Put both in `.env` and restart the bot.
5. **Fill in `data/store_info.md`** with your real address, hours, delivery, payment, and warranty terms. The AI answers store questions only from this file.
6. **Load the catalog.** Either run `python -m bot import data/catalog_sample.csv` to start with the demo catalog (40 items), or send your own CSV to the bot with the caption `/import`.
7. **Run:**
   ```bash
   python -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   python -m bot
   ```
   Or use Docker: `docker compose up -d --build`. The `data/` folder holds the database and store info, so keep it on a volume.

## Catalog format (CSV, UTF-8)

| column | required | example |
|---|---|---|
| `sku` | yes | `GPU-4070S-12` (no `:`, up to about 40 characters) |
| `category` | yes | `Видеокарты` |
| `name` | yes | `Gigabyte GeForce RTX 4070 SUPER WINDFORCE OC 12 ГБ` |
| `brand` | | `Gigabyte` |
| `price` | yes | `64990` |
| `stock` | | `4` (0 means "под заказ") |
| `specs` | | `Длина: 261 мм; Питание: 1×16-pin; Рекомендуемый БП: 650 Вт` |
| `description` | | free text |
| `image_url` | | a public image URL, shown on the product card |

- Put `specs` as `key: value` pairs separated by `;`. **Include the specs that matter for compatibility**: socket, memory type, form factor, GPU length, PSU wattage and connectors, and cooler height. The AI uses them to check builds.
- Each import is a full sync. Products missing from the file are hidden, not deleted.
- `/export` downloads the current catalog. You can edit it in Excel and import it back; CP1251 files from Excel are accepted too.
- The PC builder's budget buttons are based on the prices in the `Готовые ПК` category.

## How it's built

```
bot/
  __main__.py      entry point, router wiring, `import` CLI
  config.py        settings from .env
  db.py            SQLite: products, carts, orders, tickets, AI dialog history, manager relay
  ai/assistant.py  Claude tool-use loop (per-customer lock, prompt caching, refusal fallbacks)
  ai/tools.py      search_products, get_product, list_categories, add_to_cart, view_cart,
                   get_my_orders, handoff_to_manager (always scoped to the current customer)
  ai/prompts.py    system prompt (store rules, style, store info)
  handlers/        common (menu), catalog, cart (checkout), builder, service, handoff,
                   chat (AI catch-all), managers (group), admin
  texts.py         all customer-facing strings (i18n)
data/
  store_info.md    store facts used by the AI and the "О магазине" button
  catalog_sample.csv
```

**AI details**
- Model: `claude-opus-5` by default, with `CLAUDE_EFFORT=medium`. Set `CLAUDE_MODEL` / `CLAUDE_EFFORT` to trade quality for cost and speed. `low` effort works well for simple Q&A.
- **Refusal fallbacks are on** (`CLAUDE_FALLBACKS=true`). If a request is declined by a safety classifier, the Claude API retries it on a fallback model automatically. Set it to `false` if you route through Bedrock, Vertex, or Foundry.
- Prompt caching is on, so the system prompt, tools, and earlier conversation are reused cheaply between messages.
- The AI can't create orders or promise discounts. It only adds items to the cart after the customer agrees, and the customer confirms the order through the checkout form.
- If the Claude API is down or rate-limited, the customer is handed to a manager automatically.
- `AI_DAILY_LIMIT` caps AI replies per customer per day to protect the API budget. `/reset` clears a customer's AI conversation.

## Adding a language

1. Add a dict with the same keys as `RU` in `bot/texts.py`, for example `UZ = {...}`, and register it: `TEXTS = {"ru": RU, "uz": UZ}`.
2. Set `LANGUAGES=ru,uz` in `.env`. Customers get a language picker on `/start` and `/language`, and the AI replies in the chosen language.

## Development

```bash
pip install -r requirements-dev.txt
pytest          # unit tests, plus end-to-end flows through the real dispatcher with fake Telegram and Claude
ruff check bot tests
```

Known limitations: form state (such as a half-finished checkout) is kept in memory and resets on restart. The AI reads text only; photos go to managers during a live chat.
