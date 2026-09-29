# SIPRO Telegram assistant

A Telegram bot for a PC hardware store: it answers customers with AI and hands them to a human manager when needed. It handles components, peripherals, monitors, and ready-built PCs. It speaks Russian today, and more languages can be added later.

**It keeps working without AI.** If there's no API key, or the Claude API is down, slow, or over its budget, a rule-based assistant built into the bot answers instead. It searches the catalog, builds compatible PCs, checks compatibility, and answers store questions, so customers always get a reply.

## What it does

**For customers (private chat with the bot)**

| Feature | How |
|---|---|
| AI consultant | Customers write a question in their own words, for example "нужен монитор для игр до 30 000" or "подойдёт ли RTX 4070 к БП на 550 Вт?". Claude searches the catalog, compares specs, checks compatibility, and recommends only products you actually stock, at catalog prices. |
| Rule-based fallback | Used when the AI is off or failing (see [Working without AI](#working-without-ai)). It understands searches with price limits, PC-build requests, compatibility questions, store questions, order status, and requests for a manager. |
| 🛍 Catalog | Customers browse categories, then products, then a product card with a photo. From the card they can add the product to the cart or ask the assistant about it. |
| 🧩 PC builder | The customer picks a purpose, a budget, and any wishes (white, Wi-Fi, Intel/AMD, compact). The AI, or the rule-based configurator, puts together a compatible build from in-stock items. A single button adds the whole build to the cart. |
| 🛒 Cart and checkout | The cart warns about incompatible parts, such as a mismatched CPU socket or a GPU too long for the case. The checkout form collects name, phone (share-contact button), pickup or delivery address, and a comment. Managers get the order with status buttons. |
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
- If the AI goes down, the group gets one alert, and another when it recovers. Meanwhile customers are answered by the rule-based assistant.
- For admins only (`ADMIN_IDS`): `/import` (send a CSV with this caption), `/export`, `/stats` (includes AI status), `/reload` (re-reads `store_info.md`).

## Setup

1. **Create the bot.** In [@BotFather](https://t.me/BotFather), run `/newbot` and copy the token.
2. **Create a managers group** and add the bot to it. The bot's default privacy mode is fine, because it only needs commands and replies to its own messages.
3. **Optional: get an Anthropic API key** at https://console.anthropic.com. Without one, the bot runs on the rule-based assistant only.
4. **Configure:**
   ```bash
   cp .env.example .env   # fill in BOT_TOKEN, ANTHROPIC_API_KEY, CURRENCY
   ```
   `ADMIN_IDS` and `MANAGER_CHAT_ID` must be **numeric ids**, not @usernames. To find them, start the bot once with the placeholder values, then:
   - send `/id` to the bot in private chat to get your user id (`ADMIN_IDS`);
   - send `/id` in the managers' group to get the group id (`MANAGER_CHAT_ID`, starts with `-100`).

   Put both in `.env` and restart the bot.

   To get **someone else's** id (a store owner or another manager):
   - **forward** any of their messages to the bot in private chat, and it replies with the sender's id. This works for admins, or for anyone while `ADMIN_IDS` is still empty. If the person hides forwards in their privacy settings, the bot says so; ask them to send `/id` themselves.
   - in the managers' group, **reply `/id`** to their message. Replying to a bot post about a customer shows that customer's id.
5. **Replace the demo content in `data/store_info.md`** with your real address, hours, delivery, payment, and warranty terms. Keep the `## Section` headings; the rule-based assistant finds answers by them. Both assistants answer store questions only from this file.
6. **Load the catalog.** Either run `python -m bot import data/catalog_sample.csv` to start with the demo catalog (124 products in 16 categories, with images), or send your own CSV to the bot with the caption `/import`.
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
| `image_url` | | a public URL, or a path inside `data/`, such as `images/GPU-4070S-12.jpg` |

- Put `specs` as `key: value` pairs separated by `;`.
- **Images:** the demo catalog ships with generated illustration cards in `data/images/`. Replace them with real photos using the same file names, or put URLs in `image_url`. The bot uploads each image once and then reuses Telegram's cached copy. To regenerate the illustrations for your own CSV, run `pip install pillow && python scripts/make_product_images.py my_catalog.csv`.
- Each import is a full sync. Products missing from the file are hidden, not deleted.
- `/export` downloads the current catalog. You can edit it in Excel and import it back; CP1251 files from Excel are accepted too.
- The PC builder's budget buttons are based on the prices in the `Готовые ПК` category.

**Spec keys used for compatibility and the configurator.** Use these exact key names. A product missing a key simply isn't checked for that rule.

| Category | Keys |
|---|---|
| Процессоры | `Сокет: AM5`, `Память: DDR5` (or `DDR4/DDR5`), `TDP: 65 Вт`, `Встроенная графика: да/нет`, `Кулер в комплекте: да/нет` |
| Материнские платы | `Сокет`, `Чипсет: B650`, `Форм-фактор: ATX / mATX / Mini-ITX`, `Память: DDR5, 4 слота, до 192 ГБ`, `Wi-Fi: да/нет` |
| Оперативная память | `Тип: DDR5`, `Объём: 32 ГБ` |
| Видеокарты | `Длина: 261 мм`, `Рекомендуемый БП: 650 Вт` |
| Накопители | `Тип: SSD M.2 NVMe` (or `SSD 2.5" SATA`, `HDD 3.5"`), `Объём: 1 ТБ` |
| Блоки питания | `Мощность: 750 Вт`, `Форм-фактор: ATX / SFX` |
| Корпуса | `Форм-факторы плат: ATX, mATX, Mini-ITX`, `Форм-фактор БП: ATX / SFX`, `Макс. длина видеокарты: 360 мм`, `Макс. высота кулера: 170 мм`, `Радиатор: до 360 мм`, `Цвет` |
| Охлаждение | `Тип: башенный воздушный / СЖО / термопаста`, `Высота: 155 мм` or `Радиатор: 360 мм`, `TDP: до 220 Вт`, `Сокеты: AM4, AM5, LGA1700` |
| Готовые ПК | `Назначение: игры / работа / офис / монтаж` |

## Working without AI

The customer chat tries these in order:
1. **Live chat with a manager**, if one is open.
2. **The AI**, when an API key is set, `AI_ENABLED` isn't `false`, the customer's daily AI limit isn't used up, and the AI isn't in a cooldown.
3. **The rule-based assistant** (`bot/offline/`), otherwise. It also takes over when the AI errors or doesn't answer within `AI_TIMEOUT` seconds (default 60).

After an AI failure the bot skips the AI for 1 minute, doubling on each repeat failure up to 10 minutes. Customers never wait on a dead API, and the managers' group gets one alert when the AI goes down and another when it recovers.

What the rule-based assistant understands (in Russian):

| Customer writes | Reply |
|---|---|
| «монитор для игр до 25000», «ssd 1 тб», «беспроводная мышь», «процессор intel до 20к» | Matching products (price limits, brands, gaming monitors ≥144 Hz, 2K/4K, white, wireless…), with buttons that open the product cards |
| «собрать пк для игр за 100 тысяч», «комп для монтажа 250к» | A balanced, compatibility-checked build from stock, a similar ready-built PC if one exists, and an "add the build to cart" button. Without a budget, it starts the builder form. |
| «подойдёт ли 7800x3d к b650m-a?», «потянет ли бп 550 вт rtx 4070 super», «влезет ли 4080 super в NR200P» | Compatibility verdict with reasons |
| «где вы находитесь», «доставка», «рассрочка», «гарантия», «сколько стоит сборка» | The matching `## Section` of `store_info.md` |
| «где мой заказ», «статус заказа №12» | The customer's own orders only |
| «позовите менеджера», «скидка», «сломалась видеокарта» | Live chat with a manager, or the service form |
| anything else | A short help message with examples and a manager button |

The AI also uses the rule-based configurator and compatibility checker as tools (`build_pc`, `check_compatibility`), so both modes give consistent, checked answers.

## How it's built

```
bot/
  __main__.py      entry point, router wiring, `import` CLI
  config.py        settings from .env
  db.py            SQLite: products, carts, orders, tickets, AI dialog history, manager relay
  ai/assistant.py  Claude tool-use loop (per-customer lock, prompt caching, refusal fallbacks,
                   timeout + circuit breaker)
  ai/tools.py      search_products, get_product, list_categories, add_to_cart, view_cart, get_my_orders,
                   build_pc, check_compatibility, handoff_to_manager (always scoped to the current customer)
  ai/prompts.py    system prompt (store rules, style, store info)
  offline/         rule-based assistant: engine (intents, search), configurator, compat, specs, faq
  handlers/        common (menu), catalog, cart (checkout), builder, service, handoff,
                   chat (AI catch-all), managers (group), admin
  texts.py         all customer-facing strings (i18n)
data/
  store_info.md    store facts used by both assistants and the "О магазине" button
  catalog_sample.csv  demo catalog (124 products)
  images/          product images (demo: generated by scripts/make_product_images.py)
```

**AI details**
- Model: `claude-opus-5` by default, with `CLAUDE_EFFORT=medium`. Set `CLAUDE_MODEL` / `CLAUDE_EFFORT` to trade quality for cost and speed. `low` effort works well for simple Q&A.
- **Refusal fallbacks are on** (`CLAUDE_FALLBACKS=true`). If a request is declined by a safety classifier, the Claude API retries it on a fallback model automatically. Set it to `false` if you route through Bedrock, Vertex, or Foundry.
- Prompt caching is on, so the system prompt, tools, and earlier conversation are reused cheaply between messages.
- The AI can't create orders or promise discounts. It only adds items to the cart after the customer agrees, and the customer confirms the order through the checkout form.
- If the Claude API is down, rate-limited, or slow, the rule-based assistant answers (see [Working without AI](#working-without-ai)).
- `AI_DAILY_LIMIT` caps AI replies per customer per day to protect the API budget. After that, the rule-based assistant answers. `/reset` clears a customer's AI conversation.

## Adding a language

1. Add a dict with the same keys as `RU` in `bot/texts.py`, for example `UZ = {...}`, and register it: `TEXTS = {"ru": RU, "uz": UZ}`.
2. Set `LANGUAGES=ru,uz` in `.env`. Customers get a language picker on `/start` and `/language`, and the AI replies in the chosen language.

## Development

```bash
pip install -r requirements-dev.txt
pytest          # unit tests, plus end-to-end flows through the real dispatcher with fake Telegram and Claude
ruff check bot tests scripts
```

Known limitations: form state (such as a half-finished checkout) is kept in memory and resets on restart. The AI reads text only; photos go to managers during a live chat.
